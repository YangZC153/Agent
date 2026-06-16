#!/usr/bin/env python3
"""Deterministic daily pipeline for no-agent Hermes cron execution."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import time
from pathlib import Path

import fitz
import openpyxl
import requests

import monitor


PROJECT_DIR = Path(__file__).resolve().parent
MODEL = "deepseek-v4-flash"
MAX_PDF_TEXT_CHARS = 12000
API_ATTEMPTS = 3


def extract_first_pages(pdf_path: str, pages: int = 2) -> str:
    document = fitz.open(pdf_path)
    try:
        text = "\n\n".join(
            document[index].get_text("text")
            for index in range(min(pages, document.page_count))
        )
    finally:
        document.close()
    return text[:MAX_PDF_TEXT_CHARS]


def call_deepseek_json(prompt: str) -> dict:
    api_key = monitor.load_deepseek_api_key()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    last_error = None
    for attempt in range(1, API_ATTEMPTS + 1):
        try:
            response = requests.post(
                monitor.DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return strict JSON only.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": 1800,
                    "stream": False,
                },
                timeout=180,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            result = monitor.extract_json_object(content)
            if not result:
                raise ValueError("empty JSON response")
            return result
        except Exception as exc:
            last_error = exc
            if attempt < API_ATTEMPTS:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"DeepSeek request failed after {API_ATTEMPTS} attempts: {last_error}")


def process_paper(paper: dict) -> dict:
    pdf_text = extract_first_pages(paper["pdf_local_path"])
    prompt = f"""
根据给定 arXiv 论文信息返回 JSON：
{{
  "affiliations": "作者单位，多个单位用英文分号分隔",
  "summary_cn": "90-150个中文字符的单段总结"
}}

要求：
1. affiliations 仅从 PDF 前两页提取。删除邮箱、URL、脚注编号、正文句子和公式；无法确定时写“未找到单位信息”。
2. summary_cn 仅根据 abstract，总结方法核心、主要贡献和关键结果。不要分点，不要模板化。
3. 只返回 JSON。

标题：{paper["title"]}
Abstract：{paper["summary"]}
PDF前两页文本：
{pdf_text}
""".strip()
    result = call_deepseek_json(prompt)
    affiliations = str(result.get("affiliations", "")).replace("\n", " ").strip()
    summary_cn = str(result.get("summary_cn", "")).replace("\n", " ").strip()
    if not affiliations:
        affiliations = "未找到单位信息"
    if not summary_cn:
        raise ValueError(f"empty summary_cn for {paper['arxiv_id']}")
    return {
        "affiliations": affiliations,
        "summary_cn": summary_cn,
    }


def normalize_arxiv_id(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if "." in text:
        prefix, suffix = text.split(".", 1)
        text = f"{prefix}.{suffix.rstrip('0')}"
    return text


def update_excel(results: dict[str, dict]) -> None:
    workbook = openpyxl.load_workbook(monitor.EXCEL_FILE)
    sheet = workbook["Papers"]
    headers = {
        str(sheet.cell(row=1, column=col).value): col
        for col in range(1, sheet.max_column + 1)
    }
    normalized_results = {
        normalize_arxiv_id(arxiv_id): result
        for arxiv_id, result in results.items()
    }
    for row in range(2, sheet.max_row + 1):
        arxiv_id = normalize_arxiv_id(
            sheet.cell(row=row, column=headers["arxiv_id"]).value
        )
        result = normalized_results.get(arxiv_id)
        if not result:
            continue
        sheet.cell(
            row=row,
            column=headers["affiliations"],
            value=result["affiliations"],
        )
        sheet.cell(
            row=row,
            column=headers["summary_cn"],
            value=result["summary_cn"],
        )
    workbook.save(monitor.EXCEL_FILE)


def format_report(
    papers: list[dict],
    results: dict[str, dict],
    failures: list[str] | None = None,
    published: bool = True,
) -> str:
    failures = failures or []
    if not papers:
        return f"今日（{monitor.date.today().isoformat()}）未发现新的相关论文。"

    successful_papers = [
        paper for paper in papers if paper["arxiv_id"] in results
    ]
    lines = [
        f"论文日报 | {monitor.date.today().isoformat()}",
        f"共发现 {len(papers)} 篇新论文，已完成总结 {len(successful_papers)} 篇",
        "",
    ]
    for index, paper in enumerate(successful_papers, 1):
        result = results[paper["arxiv_id"]]
        lines.extend([
            f"{index}. {paper['title']}",
            f"主题: {paper.get('topic_name') or '未分类'}",
            f"arXiv: {paper['arxiv_id']} | {paper['published_date']}",
            f"作者: {paper['authors']}",
            f"单位: {result['affiliations']}",
            f"代码开源: {paper.get('code_open_source') or '摘要未说明'}",
        ])
        if paper.get("code_url"):
            lines.append(f"代码: {paper['code_url']}")
        lines.extend([
            f"PDF: {paper['pdf_url']}",
            f"中文总结: {result['summary_cn']}",
            "",
        ])
    if failures:
        lines.extend([
            "以下论文处理失败，将在下次自动重试：",
            *failures,
            "",
        ])
    if published:
        lines.append("完整列表: https://yangzc153.github.io/Agent/")
    else:
        lines.append("网页暂未发布本次结果，避免展示未补全的论文记录。")
    return "\n".join(lines).strip()


def run_monitor() -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        monitor.main()
    return json.loads(monitor.OUTPUT_JSON.read_text(encoding="utf-8"))


def run_command(command: list[str]) -> None:
    subprocess.run(
        command,
        cwd=PROJECT_DIR,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=900,
    )


def main() -> int:
    try:
        payload = run_monitor()
        papers = payload.get("papers_to_process", [])[:monitor.DAILY_LLM_LIMIT]
        if not papers:
            print(format_report([], {}))
            return 0

        results = {}
        failures = []
        for paper in papers:
            try:
                results[paper["arxiv_id"]] = process_paper(paper)
            except Exception as exc:
                failures.append(f"{paper['arxiv_id']}: {exc}")

        if results:
            update_excel(results)

        with contextlib.redirect_stdout(io.StringIO()):
            monitor.sync_pending_state_from_excel(refresh_output_json=True)

        if failures:
            print(format_report(papers, results, failures, published=False))
            return 0

        run_command([
            str(Path(monitor.sys.executable)),
            "viewer/build_data.py",
        ])
        run_command(["bash", "scripts/publish_viewer.sh"])
        print(format_report(papers, results))
        return 0
    except Exception as exc:
        print(f"论文日报运行失败，将在下次自动重试。\n{type(exc).__name__}: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
