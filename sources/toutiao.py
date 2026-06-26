#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
今日头条热搜搜索源

数据来源：60s API（免费、无需注册）
- https://60s.viki.moe/v2/toutiao
"""

from __future__ import annotations

from . import (
    SearchSource,
    default_headers,
    fetch_url,
    HotItem,
    register_source,
)

TOUTIAO_API = "https://60s.viki.moe/v2/toutiao"


@register_source
class ToutiaoHotSource(SearchSource):
    name = "toutiao"
    display_name = "今日头条"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        try:
            html = fetch_url(TOUTIAO_API, self.session, headers={
                **default_headers("https://www.toutiao.com/"),
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
                    url=entry.get("link", "") or f"https://www.toutiao.com/search/?keyword={keyword}",
                    source=self.display_name,
                    hot_score=str(hot_value),
                    summary=entry.get("summary", ""),
                ))

        except Exception:
            return items

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]

    @staticmethod
    def _keyword_match(title: str, keyword: str) -> bool:
        return keyword.lower() in title.lower()
