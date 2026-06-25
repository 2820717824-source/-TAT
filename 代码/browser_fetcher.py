#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Playwright 浏览器渲染器
- 从 image_crawler/crawler_engine.py 借鉴隐身配置（L540-617）
- 从 universal-crawler/browser_fetcher.py 借鉴动作脚本（L51-64）
"""

from __future__ import annotations

import time
from typing import Any


class BrowserFetcher:
    """Playwright 浏览器渲染器，带隐身配置和动作脚本"""

    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout
        self._playwright = None
        self._browser = None

    def fetch(self, url: str, actions: list[dict] | None = None) -> str:
        """加载页面并返回渲染后的 HTML

        参考 image_crawler/crawler_engine.py L540-617:
        - 启动参数：--disable-blink-features=AutomationControlled
        - 隐身上下文：覆盖 webdriver/plugins/languages/chrome/permissions
        - viewport 1920x1080, locale zh-CN

        参考 universal-crawler/browser_fetcher.py:
        - 动作脚本：click/scroll/wait
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "需要安装 Playwright: pip install playwright && playwright install chromium"
            )

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
            ],
        )

        context = self._browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            permissions=['notifications'],
            device_scale_factor=1,
            extra_http_headers={
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            },
        )

        # 注入隐身脚本（参考 image_crawler L598-615）
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en']
            });
            window.chrome = { runtime: {} };
            const originalQuery = navigator.permissions.query;
            navigator.permissions.query = (params) => (
                params.name === 'notifications'
                    ? Promise.resolve({ state: 'prompt' })
                    : originalQuery(params)
            );
        """)

        page = context.new_page()
        page.set_default_timeout(self.timeout)

        page.goto(url, wait_until='networkidle', timeout=self.timeout)

        # 执行动作脚本（参考 universal-crawler _run_action）
        if actions:
            self._run_actions(page, actions)

        html = page.content()
        page.close()
        context.close()
        self._browser.close()
        self._playwright.stop()

        return html

    def _run_actions(self, page: Any, actions: list[dict]) -> None:
        """执行动作脚本（点击/滚动/等待）

        参考 universal-crawler/browser_fetcher.py _run_action() L51-64
        """
        for action in actions:
            action_type = action.get("type")
            if action_type == "wait":
                seconds = int(float(action.get("seconds", 1)) * 1000)
                page.wait_for_timeout(seconds)
            elif action_type == "click":
                page.click(action["selector"])
            elif action_type == "scroll":
                times = int(action.get("times", 1))
                pause = int(float(action.get("pause", 1)) * 1000)
                for _ in range(times):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(pause)
            elif action_type == "wait_for":
                page.wait_for_selector(
                    action["selector"],
                    timeout=int(action.get("timeout", 15000)),
                )
