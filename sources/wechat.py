#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信搜一搜搜索源

通过搜狗的微信搜索入口获取微信公众号文章和真实 mp.weixin.qq.com 链接。
requests 搜索获取标题，Playwright 解析跳转获取真实文章 URL。
"""

from __future__ import annotations

import asyncio
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

_PLAYWRIGHT_AVAILABLE = None


def _check_playwright() -> bool:
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is None:
        try:
            import playwright  # noqa
            _PLAYWRIGHT_AVAILABLE = True
        except ImportError:
            _PLAYWRIGHT_AVAILABLE = False
    return _PLAYWRIGHT_AVAILABLE


@register_source
class WeChatSearchSource(SearchSource):
    name = "wechat"
    display_name = "微信搜一搜"

    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        items = []
        sogou_items = []  # (title, sogou_url, summary, account)
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
                if href.startswith("/"):
                    href = f"https://weixin.sogou.com{href}"

                summary_el = txt_box.select_one(".txt-info, p")
                summary = summary_el.get_text(strip=True) if summary_el else ""
                account_el = txt_box.select_one(".account")
                account = account_el.get_text(strip=True) if account_el else ""

                sogou_items.append((title, href, summary, account))
        except Exception:
            return items

        if not sogou_items:
            return items

        # Playwright 解析：先打开搜索页建立会话，再一个个解析真实 URL
        resolved = self._resolve_urls(keyword, [h for _, h, _, _ in sogou_items])

        for title, href, summary, account in sogou_items:
            items.append(HotItem(
                title=title,
                url=resolved.get(href, href),
                source=f"{self.display_name}({account})" if account else self.display_name,
                summary=summary,
            ))

        return items[:max_results]

    def _resolve_urls(self, keyword: str, sogou_urls: list[str]) -> dict[str, str]:
        """用 Playwright 隐身浏览器解析搜狗跳转链接"""
        if not _check_playwright():
            return {}

        result: dict[str, str] = {}

        async def _resolve():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-web-security",
                    ],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                    viewport={"width": 1920, "height": 1080},
                )
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)

                # 先打开搜索页建立会话 Cookie
                search_page = await context.new_page()
                search_url = f"{WEIXIN_URL}?type=2&query={quote(keyword)}"
                try:
                    await search_page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(1)
                await search_page.close()

                # 逐个解析跳转链接
                for sogou_url in sogou_urls:
                    page = await context.new_page()
                    captured: list[str] = []
                    page.on("response", lambda resp: (
                        captured.append(resp.url)
                        if resp.status == 200 and "mp.weixin.qq.com/s" in resp.url
                        else None
                    ))

                    try:
                        await page.goto(sogou_url, wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(1)
                    except Exception:
                        pass

                    result[sogou_url] = captured[0] if captured else sogou_url
                    await page.close()

                await browser.close()

        try:
            asyncio.run(_resolve())
        except Exception:
            pass

        return result
