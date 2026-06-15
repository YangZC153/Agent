import unittest

from daily_run import format_report, normalize_arxiv_id


class DailyRunTests(unittest.TestCase):
    def test_normalizes_excel_numeric_arxiv_id(self):
        self.assertEqual(normalize_arxiv_id(2606.06970), "2606.0697")
        self.assertEqual(normalize_arxiv_id("2606.04448"), "2606.04448")

    def test_formats_no_paper_report(self):
        report = format_report([], {})

        self.assertIn("未发现新的相关论文", report)

    def test_formats_paper_report(self):
        paper = {
            "arxiv_id": "2606.00001",
            "title": "Test Paper",
            "topic_name": "Multimodal recommendation",
            "published_date": "2026-06-15",
            "authors": "A. Author",
            "code_open_source": "是",
            "code_url": "https://github.com/example/repo",
            "pdf_url": "https://arxiv.org/pdf/2606.00001",
        }
        result = {
            "affiliations": "Example University",
            "summary_cn": "这是一段用于验证飞书日报字段是否完整输出的中文论文总结。",
        }

        report = format_report([paper], {paper["arxiv_id"]: result})

        self.assertIn("代码开源: 是", report)
        self.assertIn("https://github.com/example/repo", report)
        self.assertIn("Example University", report)


if __name__ == "__main__":
    unittest.main()
