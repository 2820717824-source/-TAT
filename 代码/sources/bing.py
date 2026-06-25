#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
必应搜索源
"""

from __future__ import annotations

from urllib.parse import quote

from bs4 import BeautifulSoup

from . import (
    SearchSource,
    default_headers,
    fetch_url,
    HotItem,
    register_source,
    random_ua,
)

BING_SEARCH_URL = "https://cn.bing.com/search?q={keyword}&setlang=zh-Hans"


@register_source
class BingSearchSource(SearchSource):
    name = "bing"
    display_name = "必应搜索"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        try:
            url = BING_SEARCH_URL.format(keyword=quote(keyword))
            html = fetch_url(url, self.session, headers={
                **default_headers("https://cn.bing.com/"),
                "User-Agent": random_ua(),
            }, retry_times=2, retry_backoff=1.0)
            if not html:
                return self._fallback(keyword, max_results)

            soup = BeautifulSoup(html, "html.parser")
            results = soup.select("#b_results .b_algo") or soup.select(".b_caption")
            if not results:
                return self._fallback(keyword, max_results)

            for result in results:
                h2 = result.find("h2")
                if not h2:
                    continue
                a = h2.find("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if not title or not href:
                    continue
                snippet_el = result.select_one(".b_caption p, .b_lineclamp2")
                summary = snippet_el.get_text(strip=True) if snippet_el else ""

                items.append(HotItem(
                    title=title,
                    url=href,
                    source=self.display_name,
                    summary=summary,
                ))
        except Exception:
            return self._fallback(keyword, max_results)

        return items[:max_results]

    def _fallback(self, keyword: str, max_results: int) -> list[HotItem]:
        """备用方案：通过百度搜索获取结果"""
        items = []
        try:
            search_url = f"https://www.baidu.com/s?wd={quote(keyword)}&tn=news"
            html = fetch_url(search_url, self.session,
                             headers=default_headers("https://www.baidu.com/"))
            if not html:
                return items
            soup = BeautifulSoup(html, "html.parser")
            for el in soup.select(".result, .c-container"):
                title_el = el.select_one("h3 a") or el.select_one(".t a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if not title or not href:
                    continue
                items.append(HotItem(
                    title=title,
                    url=href,
                    source="百度搜索（必应降级）",
                    summary="",
                ))
        except Exception:
            pass
        return items[:max_results]
