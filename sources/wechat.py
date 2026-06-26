#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信搜一搜搜索源

通过搜狗的微信搜索入口获取微信公众号文章。
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

WEIXIN_URL = "https://weixin.sogou.com/weixin"


@register_source
class WeChatSearchSource(SearchSource):
    name = "wechat"
    display_name = "微信搜一搜"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        try:
            url = f"{WEIXIN_URL}?type=2&query={quote(keyword)}"
            html = fetch_url(url, self.session,
                             headers=default_headers("https://weixin.sogou.com/"),
                             retry_times=2, retry_backoff=1.0)
            if not html:
                return items

            soup = BeautifulSoup(html, "html.parser")
            news_list = soup.select_one(".news-list")
            if not news_list:
                return items

            for item in news_list.find_all("li", recursive=False):
                txt_box = item.select_one(".txt-box")
                if not txt_box:
                    continue
                a = txt_box.find("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if not title or not href:
                    continue
                # Sogou 的链接是相对路径 /link?url=...，补全
                if href.startswith("/"):
                    href = f"https://weixin.sogou.com{href}"

                summary_el = txt_box.select_one(".txt-info, p")
                summary = summary_el.get_text(strip=True) if summary_el else ""
                # 提取公众号名
                account_el = txt_box.select_one(".account")
                account = account_el.get_text(strip=True) if account_el else ""

                items.append(HotItem(
                    title=title,
                    url=href,
                    source=f"{self.display_name}({account})" if account else self.display_name,
                    summary=summary,
                ))
        except Exception:
            pass

        return items[:max_results]
