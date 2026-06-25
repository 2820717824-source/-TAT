#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心编排器
管理搜索→爬取→去重→存储的全流程
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from config import CrawlerConfig
from dedupe import Deduplicator
from fetcher import Fetcher, FetchResult
from storage import ArticleSaverV2
# hotspot_crawler 中的 HotSearcher 暂不迁移，保持直接引用
import sys
sys.path.insert(0, '.')

from run_state import TaskLogger, ResumeState
from sources import HotItem
from rich.console import Console

console = Console()


@dataclass
class CrawlerReport:
    """爬取报告"""
    total: int = 0
    success: int = 0
    failed: int = 0
    deduped: int = 0
    elapsed: float = 0.0
    output_dir: str = ""


class CrawlerEngine:
    """核心编排器"""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.fetcher = Fetcher(config)
        self.dedup = Deduplicator(config.output_dir) if config.dedup_enabled else None
        self.saver = ArticleSaverV2(
            keyword=config.keyword,
            base_dir=config.output_dir or ".",
            formats=config.output_formats,
        )
        self.logger = TaskLogger()
        self.resume_state = ResumeState() if config.resume else None

    def run(self, hot_items) -> CrawlerReport:
        """执行全流程（接收外部传入的 hot_items 列表）"""
        report = CrawlerReport()
        results: list[FetchResult] = []
        start = time.time()

        # 失败恢复：优先重试上次失败的
        if self.resume_state:
            failed_items = self.resume_state.get_failed()
            # 先清空失败记录，本轮新产生的失败会重新记录
            self.resume_state.clear_failed()
            if failed_items and self.config.retry_failed:
                console.print(f"  [yellow]发现 {len(failed_items)} 条上次失败的记录，优先重试...[/yellow]")
                fake_items = [
                    HotItem(title=rec.get("url", "").rsplit("/", 1)[-1][:30], url=rec["url"], source="resume")
                    for rec in failed_items
                ]
                hot_items = fake_items + hot_items

        for i, item in enumerate(hot_items, 1):
            if self.resume_state and self.resume_state.is_completed(item.url):
                report.deduped += 1
                self.logger.log_request_skip(item.url, "resume_completed")
                continue

            if self.dedup and self.dedup.is_duplicate(item.title, item.url):
                report.deduped += 1
                self.logger.log_request_skip(item.url, "deduped")
                continue

            self.logger.log_request_start(item.url, item.source, i)
            result = self.fetcher.fetch(item.url, source=item.source, summary=item.summary)
            result.title = result.title or item.title

            self.saver.save(result, i)
            if result.status == "success":
                report.success += 1
                if self.dedup:
                    self.dedup.mark_seen(item.title, item.url)
                if self.resume_state:
                    self.resume_state.mark_completed(item.url)
            else:
                report.failed += 1
                if self.resume_state:
                    self.resume_state.mark_failed(item.url, result.error_msg)

            self.logger.log_request_done(
                item.url, result.status, result.crawl_time,
                title=result.title, error=result.error_msg,
            )
            results.append(result)

        # 汇总
        self.saver.save_summary(results)
        report.total = len(results)
        report.elapsed = time.time() - start

        if self.resume_state:
            remaining = self.resume_state.get_failed()
            if remaining:
                console.print(f"  [yellow]仍有 {len(remaining)} 条失败，可在下次运行时继续重试[/yellow]")

        self.logger.log_summary(self.config.keyword, {
            "total": report.total,
            "success": report.success,
            "failed": report.failed,
            "deduped": report.deduped,
            "elapsed": round(report.elapsed, 1),
        })

        report.output_dir = str(self.saver.output_dir)

        return report

    def close(self):
        """释放资源（可多次调用 run，最后调用一次 close）"""
        if self.dedup:
            self.dedup.close()
