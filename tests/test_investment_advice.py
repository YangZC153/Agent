import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from investment_advice.dca import (
    DEFAULT_CONFIG,
    count_remaining_open_days,
    format_public_report,
    generate_investment_advice,
)


def fetcher_for(text):
    def _fetcher(url, timeout_seconds):
        return text

    return _fetcher


def market_text(previous, latest, latest_date="2026-06-25"):
    return "\n".join(
        [
            "observation_date,NASDAQ100",
            "2026-06-24,{}".format(previous),
            f"{latest_date},{latest}",
        ]
    )


class InvestmentAdviceTests(unittest.TestCase):
    def test_l1_boost_is_idempotent_for_same_report_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "investment_state.json"
            log_path = Path(tmp) / "investment.log"
            fetcher = fetcher_for(market_text(100, 98.28))

            result = generate_investment_advice(
                today=date(2026, 6, 26),
                state_path=state_path,
                log_path=log_path,
                fetcher=fetcher,
            )
            repeated = generate_investment_advice(
                today=date(2026, 6, 26),
                state_path=state_path,
                log_path=log_path,
                fetcher=lambda url, timeout_seconds: (_ for _ in ()).throw(RuntimeError("should not fetch")),
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(result["recommended_investment_amount"], 500)
            self.assertEqual(repeated, result)
            self.assertEqual(state["already_suggested_amount"], 500)
            self.assertEqual(len(state["history"]), 1)
            self.assertEqual(
                result["market_index_description"],
                "上一交易日（2026-06-24）100.00，最新交易日（2026-06-25）98.28",
            )
            self.assertEqual(result["market_change_description"], "下跌1.72%")
            self.assertNotIn("NASDAQ", result["investment_reason"])

            report_lines = format_public_report(result).splitlines()
            self.assertEqual(len(report_lines), 4)
            self.assertEqual(
                report_lines[0],
                "股市指数：上一交易日（2026-06-24）100.00，最新交易日（2026-06-25）98.28",
            )
            self.assertEqual(report_lines[1], "涨跌比例：下跌1.72%")
            self.assertTrue(report_lines[2].startswith("推荐投资金额："))
            self.assertTrue(report_lines[3].startswith("推荐原因说明："))

    def test_closed_day_returns_zero_without_fetching_market_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "investment_state.json"
            log_path = Path(tmp) / "investment.log"

            result = generate_investment_advice(
                today=date(2026, 6, 27),
                state_path=state_path,
                log_path=log_path,
                fetcher=lambda url, timeout_seconds: (_ for _ in ()).throw(RuntimeError("should not fetch")),
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(result["recommended_investment_amount"], 0)
            self.assertIn("今日不是投资开放日", result["investment_reason"])
            self.assertEqual(result["market_index_description"], "暂无完整行情数据")
            self.assertEqual(result["market_change_description"], "无法计算")
            self.assertEqual(state["already_suggested_amount"], 0)

    def test_same_boost_signal_is_not_reused_on_later_open_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "investment_state.json"
            log_path = Path(tmp) / "investment.log"
            fetcher = fetcher_for(market_text(100, 96.8))

            first = generate_investment_advice(
                today=date(2026, 6, 26),
                state_path=state_path,
                log_path=log_path,
                fetcher=fetcher,
            )
            second = generate_investment_advice(
                today=date(2026, 6, 29),
                state_path=state_path,
                log_path=log_path,
                fetcher=fetcher,
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(first["recommended_investment_amount"], 1000)
            self.assertEqual(second["recommended_investment_amount"], 250)
            self.assertIn("不重复加码", second["investment_reason"])
            self.assertEqual(state["used_boost_signal_dates"], ["2026-06-25"])

    def test_catchup_raises_amount_after_catchup_start_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "investment_state.json"
            log_path = Path(tmp) / "investment.log"
            today = date(2026, 10, 15)
            remaining_days = count_remaining_open_days(today, DEFAULT_CONFIG)
            already_suggested = DEFAULT_CONFIG["investment_plan"]["total_budget"] - remaining_days * 620
            state_path.write_text(
                json.dumps(
                    {
                        "total_budget": DEFAULT_CONFIG["investment_plan"]["total_budget"],
                        "already_suggested_amount": already_suggested,
                        "last_signal_date": None,
                        "last_report_date": None,
                        "used_boost_signal_dates": [],
                        "history": [],
                    }
                ),
                encoding="utf-8",
            )

            result = generate_investment_advice(
                today=today,
                state_path=state_path,
                log_path=log_path,
                fetcher=fetcher_for(market_text(100, 100.42, latest_date="2026-10-14")),
            )

            self.assertEqual(result["recommended_investment_amount"], 620)
            self.assertIn("预算收敛阶段", result["investment_reason"])

    def test_fetch_failure_uses_base_amount_before_catchup_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "investment_state.json"
            log_path = Path(tmp) / "investment.log"

            result = generate_investment_advice(
                today=date(2026, 6, 26),
                state_path=state_path,
                log_path=log_path,
                fetcher=lambda url, timeout_seconds: (_ for _ in ()).throw(RuntimeError("network down")),
            )

            self.assertEqual(result["recommended_investment_amount"], 250)
            self.assertIn("未能获取最新行情数据", result["investment_reason"])
            self.assertEqual(result["market_index_description"], "暂无完整行情数据")
            self.assertEqual(result["market_change_description"], "无法计算")

    def test_insufficient_history_uses_base_amount_with_specific_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "investment_state.json"
            log_path = Path(tmp) / "investment.log"

            result = generate_investment_advice(
                today=date(2026, 6, 26),
                state_path=state_path,
                log_path=log_path,
                fetcher=fetcher_for("observation_date,NASDAQ100\n2026-06-25,100"),
            )

            self.assertEqual(result["recommended_investment_amount"], 250)
            self.assertIn("有效历史数据不足", result["investment_reason"])

    def test_fred_html_primary_url_can_fall_back_to_derived_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "investment_state.json"
            log_path = Path(tmp) / "investment.log"
            seen_urls = []

            def fetcher(url, timeout_seconds):
                seen_urls.append(url)
                if "/data/" in url:
                    return "<html><body>table page</body></html>"
                return market_text(100, 98.28)

            result = generate_investment_advice(
                today=date(2026, 6, 26),
                state_path=state_path,
                log_path=log_path,
                fetcher=fetcher,
            )

            self.assertEqual(result["recommended_investment_amount"], 500)
            self.assertEqual(len(seen_urls), 2)


if __name__ == "__main__":
    unittest.main()
