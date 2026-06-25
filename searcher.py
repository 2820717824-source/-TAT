#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索编排器：多源搜索 → 去重合并

参考 image_crawler 的策略链模式：
每个源作为链上的一个策略，顺序执行、独立容错、统一合并。
"""

from __future__ import annotations

import random
import time
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from sources import HotItem, create_sources, list_sources

console = Console()


class Searcher:
    """多源热点搜索编排器"""

    def __init__(self, keyword: str, source_names: list[str] | None = None,
                 max_per_source: int = 15, delay: float = 2.0,
                 source_configs: dict[str, dict] | None = None):
        self.keyword = keyword
        self.source_names = source_names or list_sources()
        self.max_per_source = max_per_source
        self.delay = delay
        self.source_configs = source_configs or {}
        self.sources = create_sources(self.source_names, source_configs=self.source_configs)

    def search_all(self) -> list[HotItem]:
        """执行所有来源搜索，返回去重合并后的结果

        参考 image_crawler 的提取器链模式（StaticCrawler.extract_images）：
        每个源是一个独立策略，名称带日志，失败不影响其他源。
        """
        console.print(f"\n  [bold cyan]┌─ 正在搜索: 「{self.keyword}」[/bold cyan]")
        console.print(f"  [bold cyan]│[/bold cyan]")

        # 策略链：每个源顺序执行，独立 try/except
        results = {}
        for src in self.sources:
            try:
                items = src.search(self.keyword, self.max_per_source)
                results[src.display_name] = items
                status = "[green]OK[/green]" if items else "-"
                console.print(
                    f"  [dim]├[/dim]  [{src.display_name}] 发现 [bold]{len(items)}[/bold] 条相关热点    {status}"
                )
            except Exception as e:
                results[src.display_name] = []
                console.print(
                    f"  [dim]├[/dim]  [{src.display_name}] 出错: {e}    [red]ERR[/red]"
                )
            # 参考 universal-crawler engine.py L235-240：随机间隔代替固定 delay
            actual_delay = self.delay * (0.5 + random.random())
            time.sleep(actual_delay)

        # 去重合并（按标题去重，保持源顺序优先级）
        seen_titles = set()
        merged: list[HotItem] = []
        for src in self.sources:
            for item in results.get(src.display_name, []):
                if item.title not in seen_titles:
                    seen_titles.add(item.title)
                    merged.append(item)

        console.print(f"  [dim]├[/dim]")
        console.print(f"  [bold cyan]└[/bold cyan] 去重合并后: 共 [bold]{len(merged)}[/bold] 篇待爬取")
        return merged
