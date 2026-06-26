#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
360 搜索源
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
)

SO_URL = "https://www.so.com/s"


@register_source
class SoSearchSource(SearchSource):
    name = "360"
    display_name = "360 搜索"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        try:
            url = f"{SO_URL}?q={quote(keyword)}&pn=1"
            html = fetch_url(url, self.session,
                             headers=default_headers("https://www.so.com/"),
                             retry_times=2, retry_backoff=1.0)
            if not html:
                return items

            soup = BeautifulSoup(html, "html.parser")
            for result in soup.select(".res-list"):
                h3 = result.find("h3")
                if not h3:
                    continue
                a = h3.find("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if not title or not href:
                    continue
                summary_el = result.select_one(".res-desc, p")
                summary = summary_el.get_text(strip=True) if summary_el else ""

                items.append(HotItem(
                    title=title,
                    url=href,
                    source=self.display_name,
                    summary=summary,
                ))
        except Exception:
            pass

        return items[:max_results]
