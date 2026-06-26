#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博热搜搜索源

参考 universal-crawler 的 auth/cookies 配置模式：
支持通过 config 传入 Cookie 提高请求成功率。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from . import (
    SearchSource,
    default_headers,
    fetch_url,
    HotItem,
    register_source,
)

WEIBO_HOT_URL = "https://weibo.com/ajax/side/hotSearch"


@register_source
class WeiboHotSource(SearchSource):
    name = "weibo"
    display_name = "微博热搜"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        # 优先用 --login 缓存的 Cookie，其次用 config 配置
        cookie = self.config.get("cookie", "")
        if not cookie:
            try:
                from cookie_manager import CookieManager
                cookie = CookieManager().get_cookie_str("weibo") or ""
            except ImportError:
                pass
        try:
            headers = {
                **default_headers("https://weibo.com/"),
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://weibo.com/",
            }
            if cookie:
                headers["Cookie"] = cookie

            html = fetch_url(WEIBO_HOT_URL, self.session, headers=headers, retry_times=2, retry_backoff=1.0)
            if not html:
                return self._fallback(keyword, max_results, cookie)

            data = json.loads(html)
            realtime = data.get("data", {}).get("realtime", [])
            for entry in realtime:
                word = entry.get("word", "").strip()
                if not word:
                    continue
                if keyword and not self._keyword_match(word, keyword):
                    continue
                raw_hot = entry.get("raw_hot", entry.get("hotNum", 0))
                url = f"https://s.weibo.com/weibo?q={self._quote(word)}&type=hot"
                items.append(HotItem(
                    title=word,
                    url=url,
                    source=self.display_name,
                    hot_score=str(raw_hot),
                    summary=entry.get("flag_desc", ""),
                ))
        except Exception:
            return self._fallback(keyword, max_results, cookie)

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]

    def _fallback(self, keyword: str, max_results: int, cookie: str = "") -> list[HotItem]:
        """备用方案：从微博热搜榜页面解析"""
        items = []
        try:
            headers = {
                **default_headers("https://weibo.com/"),
                "Accept": "text/html, */*",
            }
            if cookie:
                headers["Cookie"] = cookie

            html = fetch_url(WEIBO_HOT_URL, self.session, headers=headers)
            if not html:
                return items

            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script"):
                text = script.string or ""
                if "hotSearch" not in text and "hot_search" not in text:
                    continue
                values = re.findall(r'"word"\s*:\s*"([^"]+)"', text)
                scores = re.findall(r'"raw_hot"\s*:\s*(\d+)', text)
                for i, word in enumerate(values):
                    if keyword and not self._keyword_match(word, keyword):
                        continue
                    score = scores[i] if i < len(scores) else ""
                    items.append(HotItem(
                        title=word,
                        url=f"https://s.weibo.com/weibo?q={self._quote(word)}&type=hot",
                        source=self.display_name,
                        hot_score=score,
                    ))
                if items:
                    break
        except Exception:
            pass

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]

    @staticmethod
    def _keyword_match(title: str, keyword: str) -> bool:
        return keyword.lower() in title.lower()

    @staticmethod
    def _quote(text: str) -> str:
        from urllib.parse import quote
        return quote(text)
