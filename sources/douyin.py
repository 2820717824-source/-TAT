#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音热搜搜索源

数据来源：60s API（免费、无需注册）
- https://60s.viki.moe/v2/douyin
"""

from __future__ import annotations

from . import (
    SearchSource,
    default_headers,
    fetch_url,
    HotItem,
    register_source,
)

DOUYIN_API = "https://60s.viki.moe/v2/douyin"


@register_source
class DouyinHotSource(SearchSource):
    name = "douyin"
    display_name = "抖音热点"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        try:
            html = fetch_url(DOUYIN_API, self.session, headers={
                **default_headers("https://www.douyin.com/"),
                "Accept": "application/json, text/plain, */*",
            }, retry_times=2, retry_backoff=1.0)
            if not html:
                return items

            import json
            data = json.loads(html)
            entries = data.get("data", [])

            for entry in entries:
                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                if keyword and not self._keyword_match(title, keyword):
                    continue

                hot_value = entry.get("hot_value", 0) or 0
                items.append(HotItem(
                    title=title,
                    url=entry.get("link", "") or "",
                    source=self.display_name,
                    hot_score=str(hot_value),
                ))

        except Exception:
            return items

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]

    @staticmethod
    def _keyword_match(title: str, keyword: str) -> bool:
        return keyword.lower() in title.lower()
