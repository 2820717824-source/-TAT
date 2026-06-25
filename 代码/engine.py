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

    def run(self, hot_items) -> CrawlerReport:
        """执行全流程（接收外部传入的 hot_items 列表）"""
        report = CrawlerReport()
        results: list[FetchResult] = []
        start = time.time()

        for i, item in enumerate(hot_items, 1):
            # 去重检查
            if self.dedup and self.dedup.is_duplicate(item.title, item.url):
                report.deduped += 1
                continue

            # 爬取
            result = self.fetcher.fetch(item.url, source=item.source, summary=item.summary)
            result.title = result.title or item.title

            # 存储
            self.saver.save(result, i)
            if result.status == "success":
                report.success += 1
                if self.dedup:
                    # 用 item.title + item.url 做去重 key（与 is_duplicate 保持一致）
                    self.dedup.mark_seen(item.title, item.url)
            else:
                report.failed += 1

            results.append(result)

        # 汇总
        self.saver.save_summary(results)
        report.total = len(results)
        report.elapsed = time.time() - start
        report.output_dir = str(self.saver.output_dir)

        return report

    def close(self):
        """释放资源（可多次调用 run，最后调用一次 close）"""
        if self.dedup:
            self.dedup.close()
