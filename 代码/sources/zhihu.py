#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知乎热榜搜索源

注意：知乎热榜 API 需要登录认证（HTTP 401）。
- 通过 source_configs 传入 cookie 后可正常工作
- 无 cookie 时返回空结果并给出提示
"""

from __future__ import annotations

import json
import re

from . import (
    SearchSource,
    default_headers,
    fetch_url,
    HotItem,
    keyword_match,
    register_source,
)
from cookie_manager import CookieManager

ZHIHU_API_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50"


@register_source
class ZhihuHotSource(SearchSource):
    name = "zhihu"
    display_name = "知乎热榜"
    _no_cookie_warned = False

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        # 优先用 --login 缓存的 Cookie，其次用 config 配置
        cm = CookieManager()
        cookie = cm.get_cookie_str("zhihu") or self.config.get("cookie", "")
        items = []

        if not cookie:
            self._warn_no_cookie()
            return items

        try:
            headers = {
                **default_headers("https://www.zhihu.com/"),
                "Accept": "application/json, text/plain, */*",
            }
            if cookie:
                headers["Cookie"] = cookie

            html = fetch_url(ZHIHU_API_URL, self.session, headers=headers)
            if not html:
                return items

            data = json.loads(html)
            if "error" in data:
                return items

            for item in data.get("data", []):
                target = item.get("target", {})
                title = target.get("title", "").strip()
                if not title:
                    title = target.get("question", {}).get("title", "")
                if not title:
                    continue
                url_id = target.get("id", "")
                url = f"https://www.zhihu.com/question/{url_id}" if url_id else ""
                if not url:
                    url = target.get("url", "")
                detail = item.get("detail_text", "")
                if keyword and not keyword_match(title, keyword):
                    continue
                items.append(HotItem(
                    title=title,
                    url=url,
                    source=self.display_name,
                    hot_score=detail,
                ))
        except (json.JSONDecodeError, Exception):
            return items

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:max_results]

    @classmethod
    def _warn_no_cookie(cls):
        """只打印一次提示"""
        if not cls._no_cookie_warned:
            from rich.console import Console
            console = Console()
            console.print(
                "  [dim]├[/dim]  [yellow][知乎热榜][/yellow] 需要 Cookie 才能获取数据。"
            )
            console.print(
                "  [dim]│[/dim]          配置方式：在 config.yaml 的 source_configs.zhihu.cookie 中"
            )
            console.print(
                "  [dim]│[/dim]          填入从浏览器复制的知乎登录 Cookie。"
            )
            cls._no_cookie_warned = True
