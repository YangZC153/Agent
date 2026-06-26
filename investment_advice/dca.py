#!/usr/bin/env python3
"""Generate a short, sanitized daily investment suggestion.

The public output intentionally contains only two fields:

推荐投资金额：xxx 元
推荐原因说明：...
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote, urlparse

import requests


PROJECT_DIR = Path(__file__).resolve().parents[1]
MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = MODULE_DIR / "config.json"
DEFAULT_STATE_FILE = MODULE_DIR / "investment_state.json"
DEFAULT_LOG_FILE = PROJECT_DIR / "logs" / "investment_dca.log"
USER_AGENT = "hermes-arxiv-agent-investment-advice/1.0"

DEFAULT_CONFIG = {
    "investment_plan": {
        "total_budget": 30000,
        "start_date": "2026-06-26",
        "end_date": "2026-11-03",
        "base_amount": 250,
        "max_daily_amount": 1000,
        "catchup_start_date": "2026-10-15",
    },
    "market_data": {
        "source_name": "internal_market_signal",
        "data_url": "https://fred.stlouisfed.org/data/NASDAQ100",
        "timeout_seconds": 30,
    },
    "reference_urls": {},
    "non_investment_dates": [
        "2026-07-03",
        "2026-09-07",
        "2026-09-25",
        "2026-10-01",
        "2026-10-02",
        "2026-10-05",
        "2026-10-06",
        "2026-10-07",
    ],
}

PUBLIC_BANNED_TOKENS = [
    "NASDAQ100",
    "NASDAQ-100",
    "NASDAQ 100",
    "FRED",
    "St. Louis Fed",
    "Federal Reserve",
    "fred.stlouisfed.org",
    "huaan",
    "Huaan",
    "华安",
    "040046",
    "ETF",
    "基金",
    "指数",
]


class MarketDataError(RuntimeError):
    """Raised when market data cannot be fetched or parsed."""


@dataclass(frozen=True)
class MarketPoint:
    observed_date: date
    close: float


@dataclass(frozen=True)
class Signal:
    trigger_level: str
    signal_amount: int
    threshold_label: str | None
    strong: bool = False
    reused_boost: bool = False

    @property
    def is_boost(self) -> bool:
        return self.trigger_level in {"L1", "L2", "L3"} and not self.reused_boost


@dataclass(frozen=True)
class InvestmentAdvice:
    recommended_investment_amount: int
    investment_reason: str

    def to_public_dict(self) -> dict:
        return {
            "recommended_investment_amount": self.recommended_investment_amount,
            "investment_reason": sanitize_public_reason(self.investment_reason),
        }


def deep_merge(base: dict, overlay: dict) -> dict:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path = DEFAULT_CONFIG_FILE) -> dict:
    config = DEFAULT_CONFIG
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"config must be a JSON object: {config_path}")
        config = deep_merge(config, loaded)
    return config


def parse_date(value: object, field_name: str = "date") -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc


def default_state(total_budget: int) -> dict:
    return {
        "total_budget": total_budget,
        "already_suggested_amount": 0,
        "last_signal_date": None,
        "last_report_date": None,
        "used_boost_signal_dates": [],
        "history": [],
    }


def log_investment_event(message: str, log_path: Path = DEFAULT_LOG_FILE) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def load_state(
    state_path: Path,
    total_budget: int,
    log_path: Path = DEFAULT_LOG_FILE,
) -> dict:
    if not state_path.exists():
        return default_state(total_budget)

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("state root is not an object")
    except Exception as exc:
        backup = state_path.with_name(
            f"investment_state_corrupted_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        state_path.replace(backup)
        log_investment_event(
            f"WARNING corrupted state moved to {backup.name}: {type(exc).__name__}: {exc}",
            log_path,
        )
        return default_state(total_budget)

    normalized = default_state(total_budget)
    normalized.update(state)
    normalized["total_budget"] = total_budget
    normalized["already_suggested_amount"] = int(
        normalized.get("already_suggested_amount") or 0
    )
    if not isinstance(normalized.get("used_boost_signal_dates"), list):
        normalized["used_boost_signal_dates"] = []
    if not isinstance(normalized.get("history"), list):
        normalized["history"] = []
    return normalized


def save_state(state: dict, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(f"{state_path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(state_path)


def is_investment_open_day(day: date, config: dict) -> bool:
    plan = config["investment_plan"]
    start_date = parse_date(plan["start_date"], "start_date")
    end_date = parse_date(plan["end_date"], "end_date")
    if day < start_date or day > end_date:
        return False
    if day.weekday() >= 5:
        return False
    non_investment_dates = {
        parse_date(item, "non_investment_dates") for item in config["non_investment_dates"]
    }
    return day not in non_investment_dates


def count_remaining_open_days(today: date, config: dict) -> int:
    end_date = parse_date(config["investment_plan"]["end_date"], "end_date")
    if today > end_date:
        return 0
    count = 0
    cursor = today
    while cursor <= end_date:
        if is_investment_open_day(cursor, config):
            count += 1
        cursor += timedelta(days=1)
    return count


def derive_fred_csv_url(data_url: str) -> str | None:
    parsed = urlparse(data_url)
    if "fred.stlouisfed.org" not in parsed.netloc:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2 and parts[0] == "data":
        series_id = parts[1]
        return f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={quote(series_id)}"
    return None


def default_fetcher(url: str, timeout_seconds: int) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response.text


def parse_market_points(text: str) -> list[MarketPoint]:
    if "<html" in text[:1000].lower():
        return []

    points_by_date: dict[date, MarketPoint] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "<", "!", "//")):
            continue

        parts = [part.strip().strip('"') for part in line.split(",")]
        if len(parts) < 2:
            parts = line.split()
        if len(parts) < 2:
            continue

        try:
            observed_date = date.fromisoformat(parts[0])
        except ValueError:
            continue

        value = parts[1].strip()
        if not value or value in {".", "NA", "NaN", "nan", "null"}:
            continue
        try:
            close = float(value)
        except ValueError:
            continue
        points_by_date[observed_date] = MarketPoint(observed_date, close)

    return [points_by_date[key] for key in sorted(points_by_date)]


def fetch_recent_market_points(
    config: dict,
    fetcher: Callable[[str, int], str] = default_fetcher,
    log_path: Path = DEFAULT_LOG_FILE,
) -> list[MarketPoint]:
    market_data = config["market_data"]
    data_url = str(market_data["data_url"])
    timeout_seconds = int(market_data.get("timeout_seconds") or 30)
    urls = [data_url]
    csv_url = derive_fred_csv_url(data_url)
    if csv_url and csv_url not in urls:
        urls.append(csv_url)

    errors: list[str] = []
    best_points: list[MarketPoint] = []
    for index, url in enumerate(urls):
        try:
            text = fetcher(url, timeout_seconds)
            points = parse_market_points(text)
            if len(points) > len(best_points):
                best_points = points
            if len(points) >= 2:
                if index > 0:
                    log_investment_event(
                        "market data primary URL was not parseable; used derived CSV endpoint",
                        log_path,
                    )
                return points[-2:]
            errors.append(f"{url}: valid_points={len(points)}")
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")

    if best_points:
        return best_points[-2:]

    raise MarketDataError("; ".join(errors) or "no valid market data")


def calculate_signal(daily_return: float, signal_date: date, state: dict, base_amount: int) -> Signal:
    if daily_return <= -0.030:
        signal = Signal("L3", 1000, "3%", strong=True)
    elif daily_return <= -0.020:
        signal = Signal("L2", 750, "2%")
    elif daily_return <= -0.015:
        signal = Signal("L1", 500, "1.5%")
    else:
        signal = Signal("Normal", base_amount, None)

    if signal.trigger_level != "Normal" and signal_date.isoformat() in set(
        state.get("used_boost_signal_dates", [])
    ):
        return Signal(
            trigger_level=signal.trigger_level,
            signal_amount=base_amount,
            threshold_label=signal.threshold_label,
            strong=signal.strong,
            reused_boost=True,
        )
    return signal


def percent_text(daily_return: float) -> str:
    return f"{abs(daily_return) * 100:.2f}%"


def move_text(daily_return: float) -> str:
    direction = "上涨" if daily_return >= 0 else "下跌"
    return f"{direction}{percent_text(daily_return)}"


def cap_amount(amount: int, max_daily_amount: int, remaining_budget: int) -> int:
    return max(0, min(int(amount), int(max_daily_amount), int(remaining_budget)))


def sanitize_public_reason(reason: str) -> str:
    cleaned = re.sub(r"https?://\S+", "", str(reason)).strip()
    for token in PUBLIC_BANNED_TOKENS:
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def format_public_report(result: InvestmentAdvice | dict) -> str:
    if isinstance(result, InvestmentAdvice):
        payload = result.to_public_dict()
    else:
        payload = {
            "recommended_investment_amount": int(
                result.get("recommended_investment_amount", 0)
            ),
            "investment_reason": sanitize_public_reason(
                result.get("investment_reason", "")
            ),
        }
    return (
        f"推荐投资金额：{payload['recommended_investment_amount']} 元\n"
        f"推荐原因说明：{payload['investment_reason']}"
    )


def find_existing_report(state: dict, today: date) -> InvestmentAdvice | None:
    if state.get("last_report_date") != today.isoformat():
        return None
    for item in reversed(state.get("history", [])):
        if item.get("report_date") == today.isoformat():
            return InvestmentAdvice(
                recommended_investment_amount=int(item.get("final_amount") or 0),
                investment_reason=str(item.get("reason") or ""),
            )
    return InvestmentAdvice(
        recommended_investment_amount=0,
        investment_reason="今日建议已生成，未找到历史原因说明，今日不重复计算。",
    )


def build_reason(
    *,
    daily_return: float | None,
    signal: Signal | None,
    signal_amount: int,
    catchup_amount: int,
    final_amount: int,
    base_amount: int,
    remaining_budget: int,
    data_status: str,
    catchup_active: bool,
) -> str:
    if remaining_budget < max(signal_amount, catchup_amount, base_amount) and final_amount < max(
        signal_amount, catchup_amount, base_amount
    ):
        if daily_return is not None:
            return f"最近一个交易日{move_text(daily_return)}，但受剩余计划预算限制，今日建议投资{final_amount}元。"
        return f"受剩余计划预算限制，今日建议投资{final_amount}元。"

    if data_status == "fetch_failed":
        if catchup_active and catchup_amount > base_amount:
            return f"今日未能获取最新行情数据，但已进入预算收敛阶段，因此按剩余预算和剩余开放日计算，建议投资{final_amount}元。"
        return f"今日未能获取最新行情数据，为避免中断计划，暂按基础投资{final_amount}元执行。"

    if data_status == "insufficient":
        if catchup_active and catchup_amount > base_amount:
            return f"有效历史数据不足，但已进入预算收敛阶段，因此按剩余预算和剩余开放日计算，建议投资{final_amount}元。"
        return f"有效历史数据不足，暂不触发行情加码，今日按基础投资{final_amount}元执行。"

    if daily_return is None or signal is None:
        return f"今日按计划建议投资{final_amount}元。"

    if catchup_active and catchup_amount > signal_amount:
        if signal.reused_boost:
            return f"最近一个交易日{move_text(daily_return)}，此前已按该信号加码，今日不重复加码；当前已进入预算收敛阶段，因此建议投资{final_amount}元。"
        if signal.trigger_level == "Normal":
            return f"最近一个交易日未触发加码，但当前已进入预算收敛阶段，距离计划结束剩余开放日较少，因此今日建议提高至{final_amount}元。"
        return f"最近一个交易日{move_text(daily_return)}，同时已进入预算收敛阶段，因此今日建议提高至{final_amount}元。"

    if signal.reused_boost:
        return f"最近一个交易日{move_text(daily_return)}，此前已按该信号加码，今日不重复加码，维持基础投资{base_amount}元。"

    if signal.trigger_level == "L1":
        return f"最近一个交易日下跌{percent_text(daily_return)}，触发“单日跌幅≥1.5%”加码规则，因此今日建议由基础{base_amount}元提高至{final_amount}元。"
    if signal.trigger_level == "L2":
        return f"最近一个交易日下跌{percent_text(daily_return)}，触发“单日跌幅≥2%”加码规则，因此今日建议提高至{final_amount}元。"
    if signal.trigger_level == "L3":
        return f"最近一个交易日下跌{percent_text(daily_return)}，触发“单日跌幅≥3%”强加码规则，因此今日建议提高至{final_amount}元。"

    if daily_return >= 0:
        return f"最近一个交易日上涨{percent_text(daily_return)}，未触发加码规则，因此今日维持基础投资{final_amount}元。"
    return f"最近一个交易日下跌{percent_text(daily_return)}，未达到1.5%加码阈值，因此今日维持基础投资{final_amount}元。"


def append_history_and_save(
    *,
    state: dict,
    state_path: Path,
    log_path: Path,
    report_date: date,
    signal_date: date | None,
    latest_close: float | None,
    previous_close: float | None,
    daily_return: float | None,
    trigger_level: str,
    signal_amount: int,
    catchup_amount: int,
    final_amount: int,
    reason: str,
    remaining_budget_before: int,
) -> None:
    remaining_budget_after = max(0, remaining_budget_before - final_amount)
    state["already_suggested_amount"] = int(state.get("already_suggested_amount") or 0) + final_amount
    state["last_signal_date"] = signal_date.isoformat() if signal_date else None
    state["last_report_date"] = report_date.isoformat()
    state.setdefault("history", []).append(
        {
            "report_date": report_date.isoformat(),
            "signal_date": signal_date.isoformat() if signal_date else None,
            "latest_close": latest_close,
            "previous_close": previous_close,
            "daily_return": daily_return,
            "trigger_level": trigger_level,
            "signal_amount": signal_amount,
            "catchup_amount": catchup_amount,
            "final_amount": final_amount,
            "reason": reason,
        }
    )
    save_state(state, state_path)
    log_investment_event(
        " ".join(
            [
                f"report_date={report_date.isoformat()}",
                f"signal_date={signal_date.isoformat() if signal_date else None}",
                f"daily_return={daily_return}",
                f"trigger_level={trigger_level}",
                f"signal_amount={signal_amount}",
                f"catchup_amount={catchup_amount}",
                f"final_amount={final_amount}",
                f"remaining_budget_before={remaining_budget_before}",
                f"remaining_budget_after={remaining_budget_after}",
                f"reason={reason}",
            ]
        ),
        log_path,
    )


def generate_investment_advice(
    *,
    today: date | None = None,
    config_path: Path = DEFAULT_CONFIG_FILE,
    state_path: Path = DEFAULT_STATE_FILE,
    log_path: Path = DEFAULT_LOG_FILE,
    fetcher: Callable[[str, int], str] = default_fetcher,
    config: dict | None = None,
) -> dict:
    report_date = today or date.today()
    resolved_config = deep_merge(DEFAULT_CONFIG, config or load_config(config_path))
    plan = resolved_config["investment_plan"]
    total_budget = int(plan["total_budget"])
    base_amount = int(plan["base_amount"])
    max_daily_amount = int(plan["max_daily_amount"])
    catchup_start_date = parse_date(plan["catchup_start_date"], "catchup_start_date")

    state = load_state(state_path, total_budget, log_path)
    existing = find_existing_report(state, report_date)
    if existing:
        log_investment_event(
            f"report_date={report_date.isoformat()} already generated; reused existing result",
            log_path,
        )
        return existing.to_public_dict()

    already_suggested_amount = int(state.get("already_suggested_amount") or 0)
    remaining_budget = max(0, total_budget - already_suggested_amount)
    if remaining_budget <= 0:
        reason = f"计划预算{total_budget}元已全部完成，今日不再建议新增投资。"
        append_history_and_save(
            state=state,
            state_path=state_path,
            log_path=log_path,
            report_date=report_date,
            signal_date=None,
            latest_close=None,
            previous_close=None,
            daily_return=None,
            trigger_level="BudgetCompleted",
            signal_amount=0,
            catchup_amount=0,
            final_amount=0,
            reason=reason,
            remaining_budget_before=remaining_budget,
        )
        return InvestmentAdvice(0, reason).to_public_dict()

    if not is_investment_open_day(report_date, resolved_config):
        reason = "今日不是投资开放日，不建议执行投资。"
        append_history_and_save(
            state=state,
            state_path=state_path,
            log_path=log_path,
            report_date=report_date,
            signal_date=None,
            latest_close=None,
            previous_close=None,
            daily_return=None,
            trigger_level="Closed",
            signal_amount=0,
            catchup_amount=0,
            final_amount=0,
            reason=reason,
            remaining_budget_before=remaining_budget,
        )
        return InvestmentAdvice(0, reason).to_public_dict()

    catchup_active = report_date >= catchup_start_date
    remaining_open_days = count_remaining_open_days(report_date, resolved_config)
    catchup_amount = 0
    if catchup_active and remaining_open_days > 0:
        catchup_amount = math.ceil(remaining_budget / remaining_open_days)

    latest_close = None
    previous_close = None
    signal_date = None
    daily_return = None
    trigger_level = "Normal"
    signal_amount = base_amount
    signal: Signal | None = None
    data_status = "ok"

    try:
        recent_points = fetch_recent_market_points(resolved_config, fetcher, log_path)
    except MarketDataError as exc:
        data_status = "fetch_failed"
        log_investment_event(
            f"report_date={report_date.isoformat()} market data fetch failed: {exc}",
            log_path,
        )
    else:
        if len(recent_points) < 2:
            data_status = "insufficient"
        else:
            previous, latest = recent_points[-2], recent_points[-1]
            previous_close = previous.close
            latest_close = latest.close
            signal_date = latest.observed_date
            if previous.close <= 0:
                data_status = "insufficient"
            else:
                daily_return = latest.close / previous.close - 1
                signal = calculate_signal(daily_return, signal_date, state, base_amount)
                trigger_level = signal.trigger_level
                if signal.reused_boost:
                    trigger_level = f"{trigger_level}_REUSED"
                signal_amount = signal.signal_amount

    if data_status != "ok":
        signal_amount = base_amount
        trigger_level = "DataUnavailable" if data_status == "fetch_failed" else "InsufficientData"

    raw_final_amount = max(signal_amount, catchup_amount)
    final_amount = cap_amount(raw_final_amount, max_daily_amount, remaining_budget)
    reason = build_reason(
        daily_return=daily_return,
        signal=signal,
        signal_amount=signal_amount,
        catchup_amount=catchup_amount,
        final_amount=final_amount,
        base_amount=base_amount,
        remaining_budget=remaining_budget,
        data_status=data_status,
        catchup_active=catchup_active,
    )
    reason = sanitize_public_reason(reason)

    if signal and signal.is_boost and signal_date:
        used_dates = set(state.get("used_boost_signal_dates", []))
        used_dates.add(signal_date.isoformat())
        state["used_boost_signal_dates"] = sorted(used_dates)

    append_history_and_save(
        state=state,
        state_path=state_path,
        log_path=log_path,
        report_date=report_date,
        signal_date=signal_date,
        latest_close=latest_close,
        previous_close=previous_close,
        daily_return=daily_return,
        trigger_level=trigger_level,
        signal_amount=signal_amount,
        catchup_amount=catchup_amount,
        final_amount=final_amount,
        reason=reason,
        remaining_budget_before=remaining_budget,
    )
    return InvestmentAdvice(final_amount, reason).to_public_dict()


def safe_fallback_advice(error: Exception) -> dict:
    return InvestmentAdvice(
        recommended_investment_amount=0,
        investment_reason=f"今日投资建议模块运行异常，暂不建议新增投资；错误已写入运行日志。",
    ).to_public_dict()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate daily investment advice.")
    parser.add_argument("--json", action="store_true", help="print JSON instead of two-line report")
    parser.add_argument("--date", help="override report date, YYYY-MM-DD")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_FILE)
    args = parser.parse_args(list(argv) if argv is not None else None)

    report_date = parse_date(args.date, "--date") if args.date else None
    try:
        result = generate_investment_advice(
            today=report_date,
            config_path=args.config,
            state_path=args.state,
            log_path=args.log,
        )
    except Exception as exc:
        log_investment_event(f"ERROR investment advice failed: {type(exc).__name__}: {exc}", args.log)
        result = safe_fallback_advice(exc)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(format_public_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
