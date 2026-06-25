#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百度热搜搜索源
"""

from __future__ import annotations

import json

from urllib.parse import quote

from . import (
    REQUEST_TIMEOUT,
    SearchSource,
    default_headers,
    fetch_url,
    HotItem,
    keyword_match,
    register_source,
)

BAIDU_API_URL = "https://top.baidu.com/api/board?tab=realtime"


@register_source
class BaiduHotSource(SearchSource):
    name = "baidu"
    display_name = "百度热搜"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        try:
            html = fetch_url(BAIDU_API_URL, self.session, headers={
                **default_headers("https://top.baidu.com/"),
                "Accept": "application/json, text/plain, */*",
            }, retry_times=2, retry_backoff=1.0)
            if not html:
                return self._fallback(keyword, max_results)

            data = json.loads(html)
            cards = data.get("data", {}).get("cards", [])
            for card in cards:
                for content in card.get("content", []):
                    title = content.get("word", content.get("query", "")).strip()
                    if not title:
                        continue
                    if keyword and not keyword_match(title, keyword):
                        continue
                    items.append(HotItem(
                        title=title,
                        url=content.get("url", content.get("appUrl",
                                        f"https://www.baidu.com/s?wd={quote(title)}")),
                        source=self.display_name,
                        hot_score=str(content.get("hotScore", content.get("heatScore", ""))),
                        summary=content.get("desc", ""),
                    ))
        except Exception:
            return self._fallback(keyword, max_results)

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]

    def _fallback(self, keyword: str, max_results: int) -> list[HotItem]:
        """备用方案：直接从热搜页面解析"""
        items = []
        try:
            html = fetch_url("https://top.baidu.com/board?tab=realtime", self.session)
            if not html:
                return items
            import re
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script"):
                text = script.string or ""
                if "hotSearch" not in text and "board" not in text:
                    continue
                for match in re.finditer(r'window\.__NUXT__\s*=\s*(\{.*?\})\s*;?\s*\n', text, re.DOTALL):
                    try:
                        data = json.loads(match.group(1))
                        cards = data.get("data", {}).get("cards", [])
                        for card in cards:
                            for content in card.get("content", []):
                                word = content.get("word", content.get("query", "")).strip()
                                if not word:
                                    continue
                                if keyword and not keyword_match(word, keyword):
                                    continue
                                items.append(HotItem(
                                    title=word,
                                    url=content.get("url", f"https://www.baidu.com/s?wd={quote(word)}"),
                                    source=self.display_name,
                                    hot_score=str(content.get("hotScore", content.get("heatScore", ""))),
                                ))
                    except (json.JSONDecodeError, KeyError):
                        pass
                if items:
                    break
        except Exception:
            pass

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]
