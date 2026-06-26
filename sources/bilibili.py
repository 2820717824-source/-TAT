#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站热搜搜索源

数据来源：Bilibili 公开 API
- 热搜榜：https://api.bilibili.com/x/web-interface/search/square
- 热门视频：https://api.bilibili.com/x/web-interface/popular
"""

from __future__ import annotations

import json

from . import (
    SearchSource,
    default_headers,
    fetch_url,
    HotItem,
    register_source,
)

BILIBILI_TRENDING = "https://api.bilibili.com/x/web-interface/search/square?limit=50"
BILIBILI_POPULAR = "https://api.bilibili.com/x/web-interface/popular"


@register_source
class BilibiliHotSource(SearchSource):
    name = "bilibili"
    display_name = "B站热搜"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []

        # 先取热搜关键词
        try:
            html = fetch_url(BILIBILI_TRENDING, self.session, headers={
                **default_headers("https://www.bilibili.com/"),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.bilibili.com/",
            }, retry_times=2, retry_backoff=1.0)
            if html:
                data = json.loads(html)
                trending = data.get("data", {}).get("trending", {})
                for entry in trending.get("list", []):
                    title = (entry.get("show_name") or entry.get("keyword") or "").strip()
                    # 清理非法字符
                    title = title.encode("utf-8", errors="ignore").decode("utf-8")
                    if not title:
                        continue
                    if keyword and not self._keyword_match(title, keyword):
                        continue
                    heat = entry.get("heat_score", 0) or 0
                    url = entry.get("url", "") or f"https://search.bilibili.com/all?keyword={title}"
                    items.append(HotItem(
                        title=title,
                        url=url,
                        source=self.display_name,
                        hot_score=str(heat),
                    ))
        except Exception:
            pass

        # 热搜不够再用热门视频补充
        if len(items) < max_results:
            try:
                html = fetch_url(BILIBILI_POPULAR, self.session, headers={
                    **default_headers("https://www.bilibili.com/"),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.bilibili.com/",
                }, retry_times=1)
                if html:
                    data = json.loads(html)
                    for entry in data.get("data", {}).get("list", []):
                        if len(items) >= max_results:
                            break
                        title = (entry.get("title") or "").strip()
                        if not title:
                            continue
                        if keyword and not self._keyword_match(title, keyword):
                            continue
                        # 去重
                        if any(item.title == title for item in items):
                            continue
                        items.append(HotItem(
                            title=title,
                            url=f"https://www.bilibili.com/video/{entry.get('bvid', '')}",
                            source=self.display_name,
                            hot_score=str(entry.get("stat", {}).get("view", 0)),
                        ))
            except Exception:
                pass

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]

    @staticmethod
    def _keyword_match(title: str, keyword: str) -> bool:
        return keyword.lower() in title.lower()
