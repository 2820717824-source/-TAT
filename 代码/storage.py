#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多格式文章存储模块
- MD（Markdown 文件，兼容原有格式）
- JSONL（每行一个 JSON，适合数据分析）
- CSV（表格形式）
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from fetcher import FetchResult


@dataclass
class StorageResult:
    """单次存储结果"""
    path: str
    format: str
    size: int


class ArticleSaverV2:
    """多格式文章保存器"""

    def __init__(self, keyword: str, base_dir: str, formats: list[str] | None = None):
        self.keyword = keyword
        self.base_dir = base_dir or os.getcwd()
        self.formats = formats or ["md"]
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self.output_dir = Path(self.base_dir) / keyword / self.date_str

    def save(self, result: FetchResult, index: int) -> list[StorageResult]:
        """按 formats 列表分别保存，返回所有保存结果"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results: list[StorageResult] = []

        for fmt in self.formats:
            fmt = fmt.lower()
            if fmt == "md":
                path = self._save_md(result, index)
            elif fmt == "jsonl":
                path = self._save_jsonl(result, index)
            elif fmt == "csv":
                path = self._save_csv(result, index)
            else:
                continue
            if path:
                size = os.path.getsize(path)
                results.append(StorageResult(path=path, format=fmt, size=size))

        return results

    def _safe_filename(self, title: str, max_len: int = 40) -> str:
        safe = re.sub(r'[\\/:*?"<>|]', "", title)
        safe = safe.strip().replace(" ", "_")
        return safe[:max_len]

    def _url_slug(self, url: str, max_len: int = 12) -> str:
        slug = url[-16:-1] if len(url) > 16 else url
        return self._safe_filename(slug, max_len)

    def _filename(self, result: FetchResult, index: int, ext: str) -> str:
        title_slug = self._safe_filename(result.title)
        url_slug = self._url_slug(result.url)
        suffix = f"_{url_slug}" if url_slug else ""
        return f"{index:03d}_{title_slug}{suffix}.{ext}"

    def _frontmatter(self, result: FetchResult) -> dict:
        fm = {
            "title": result.title,
            "url": result.url,
            "source": result.source,
            "date": self.date_str,
            "keyword": self.keyword,
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": result.status,
        }
        if result.author:
            fm["author"] = result.author
        if result.summary:
            fm["summary"] = result.summary
        if result.error_msg:
            fm["error"] = result.error_msg
        return fm

    def _save_md(self, result: FetchResult, index: int) -> str:
        """保存为 Markdown 文件（兼容原有格式）"""
        fname = self._filename(result, index, "md")
        fpath = self.output_dir / fname

        lines = []
        lines.append("---")
        lines.append(yaml.dump(self._frontmatter(result), allow_unicode=True,
                               default_flow_style=False, sort_keys=False).strip())
        lines.append("---")
        lines.append("")
        lines.append(f"# {result.title}")
        lines.append("")
        lines.append(f"> 来源：{result.source}  |  日期：{self.date_str}")
        if result.url:
            lines.append(f"> 原文：[{result.url}]({result.url})")
        lines.append("")

        if result.status == "success" and result.content_markdown:
            lines.append(result.content_markdown)
        elif result.error_msg:
            lines.append(f"\n> 爬取失败：{result.error_msg}\n")

        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return str(fpath)

    def _save_jsonl(self, result: FetchResult, index: int) -> str:
        """保存为 JSONL（每行一个 JSON 对象）"""
        fname = self._filename(result, index, "jsonl")
        fpath = self.output_dir / fname

        data = {
            "title": result.title,
            "url": result.url,
            "source": result.source,
            "content": result.content_markdown if result.status == "success" else "",
            "status": result.status,
            "error": result.error_msg,
            "keyword": self.keyword,
            "date": self.date_str,
        }
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        return str(fpath)

    def _save_csv(self, result: FetchResult, index: int) -> str:
        """保存为 CSV（追加模式，自动创建表头）"""
        fname = f"{self.keyword}_{self.date_str}.csv"
        fpath = self.output_dir / fname

        is_new = not fpath.exists()
        with open(fpath, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["title", "url", "source", "content", "status", "keyword", "date"])
            writer.writerow([
                result.title,
                result.url,
                result.source,
                result.content_markdown if result.status == "success" else "",
                result.status,
                self.keyword,
                self.date_str,
            ])
        return str(fpath)

    def save_summary(self, results: list[FetchResult]) -> str:
        """生成汇总文件 _summary.md"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        success_count = sum(1 for r in results if r.status == "success")
        failed_count = sum(1 for r in results if r.status == "failed")
        total = len(results)

        lines = []
        lines.append(f"# 行业热点汇总 — {self.keyword}")
        lines.append("")
        lines.append(f"> 爬取日期：{self.date_str}")
        lines.append(f"> 成功：{success_count} 篇 | 失败：{failed_count} 篇 | 总计：{total} 篇")
        lines.append("")

        for i, r in enumerate(results, 1):
            status_icon = "✓" if r.status == "success" else "✗"
            lines.append(f"### {i:03d}. {r.title}")
            lines.append("")
            lines.append(f"- **来源**：{r.source}")
            lines.append(f"- **链接**：[{r.url}]({r.url})")
            if r.status == "success":
                lines.append(f"- **状态**：✅ 成功")
            else:
                lines.append(f"- **状态**：❌ 失败 ({r.error_msg})")
            lines.append("")

        fpath = self.output_dir / "_summary.md"
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return str(fpath)
