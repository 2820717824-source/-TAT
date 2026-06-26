#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双引擎文章获取器
- requests 直连（快路径，保持现有 Readability 提取）
- Playwright 渲染（慢路径，处理 JS 动态页面）
- 智能降级：自动判断是否需要浏览器
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import html2text
import requests
from bs4 import BeautifulSoup
from readability import Document

from config import CrawlerConfig
from browser_fetcher import BrowserFetcher


@dataclass
class FetchResult:
    """单篇文章获取结果"""
    title: str
    url: str
    source: str
    content_html: str = ""
    content_markdown: str = ""
    author: str = ""
    publish_time: str = ""
    summary: str = ""
    status: str = "pending"  # pending | success | failed
    error_msg: str = ""
    crawl_time: float = 0.0
    fallback: bool = False   # 是否从摘要回落（详情页获取失败时）


class Fetcher:
    """双引擎文章获取器"""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.session = requests.Session()
        self.converter = html2text.HTML2Text()
        self.converter.body_width = 0
        self.converter.skip_internal_links = False
        self.converter.protect_links = True
        self.converter.unicode_snob = True
        self.converter.ignore_links = False
        self.converter.ignore_images = False
        self.converter.ignore_emphasis = False

    def fetch(self, url: str, source: str = "", summary: str = "") -> FetchResult:
        """入口方法：根据 browser_mode 自动选择路径"""
        result = FetchResult(title=url, url=url, source=source, summary=summary)

        try:
            start = time.time()

            # 判断走哪条路
            if self.config.browser_mode == "always":
                result = self._browser_fetch(url, source, summary)
            elif self.config.browser_mode == "never":
                result = self._requests_fetch(url, source, summary)
            else:
                # auto 模式：先尝试 requests
                result = self._requests_fetch(url, source, summary)
                if result.status == "failed" or self._should_use_browser(result.content_html):
                    result = self._browser_fetch(url, source, summary)

            result.crawl_time = time.time() - start

        except Exception as e:
            result.status = "failed"
            result.error_msg = str(e)[:60]
            result.crawl_time = time.time() - start

        return result

    def _requests_fetch(self, url: str, source: str = "", summary: str = "") -> FetchResult:
        """requests 直连 + Readability 提取（保持现有逻辑不变）"""
        result = FetchResult(title="", url=url, source=source, summary=summary)

        try:
            headers = self._default_headers(urlparse(url).netloc)
            resp = self.session.get(url, headers=headers, timeout=15, allow_redirects=True)
            resp.raise_for_status()

            if resp.encoding and resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"

            html = resp.text
            if not html or len(html.strip()) < 200:
                result.status = "failed"
                result.error_msg = "内容为空或过短"
                return result

            # Readability 正文提取
            doc = Document(html, url=url)
            doc.summary()
            content_html = doc.content() or ""
            title = doc.title() or ""

            result.title = title
            result.content_html = content_html
            result.author = doc.author() or ""

            if not content_html or len(content_html.strip()) < 50:
                result.content_html = self._fallback_extract(html)
                if not result.content_html or len(result.content_html.strip()) < 50:
                    result.status = "failed"
                    result.error_msg = "正文提取失败"
                    return result

            result.content_markdown = self.converter.handle(result.content_html)

            # 质量检查：标题和正文不能太空
            if not self._quality_check(result):
                result.status = "failed"
                if not result.error_msg:
                    result.error_msg = "内容质量过低"
                return result

            result.status = "success"

        except requests.Timeout:
            result.status = "failed"
            result.error_msg = "网络超时"
        except requests.ConnectionError:
            result.status = "failed"
            result.error_msg = "连接被拒"
        except requests.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if code in (403, 429):
                result.status = "failed"
                result.error_msg = f"被拦截 (HTTP {code})"
            elif code == 404:
                result.status = "failed"
                result.error_msg = "页面不存在 (404)"
            else:
                result.status = "failed"
                result.error_msg = f"HTTP {code}"
        except Exception as e:
            result.status = "failed"
            result.error_msg = str(e)[:60]

        return result

    def _browser_fetch(self, url: str, source: str = "", summary: str = "") -> FetchResult:
        """Playwright 渲染 + Readability 提取"""
        result = FetchResult(title="", url=url, source=source, summary=summary)

        try:
            bf = BrowserFetcher(headless=True)
            html = bf.fetch(url)

            if not html or len(html.strip()) < 200:
                result.status = "failed"
                result.error_msg = "浏览器渲染后内容为空"
                return result

            # Readability 正文提取（复用 requests 路径的相同逻辑）
            doc = Document(html, url=url)
            doc.summary()
            content_html = doc.content() or ""
            title = doc.title() or ""

            result.title = title
            result.content_html = content_html
            result.author = doc.author() or ""

            if not content_html or len(content_html.strip()) < 50:
                result.content_html = self._fallback_extract(html)
                if not result.content_html or len(result.content_html.strip()) < 50:
                    result.status = "failed"
                    result.error_msg = "正文提取失败"
                    return result

            result.content_markdown = self.converter.handle(result.content_html)

            if not self._quality_check(result):
                result.status = "failed"
                if not result.error_msg:
                    result.error_msg = "内容质量过低"
                return result

            result.status = "success"

        except ImportError:
            result.status = "failed"
            result.error_msg = "Playwright 未安装 (pip install playwright)"
        except Exception as e:
            result.status = "failed"
            result.error_msg = str(e)[:60]

        return result

    def _should_use_browser(self, html: str) -> bool:
        """智能降级判断：内容太短或检测到 SPA 特征"""
        if not html or len(html.strip()) < 200:
            return True
        # 检测 SPA 框架特征
        spa_signals = ["__NEXT_DATA__", "__NUXT__", "vue-app", "react-app"]
        if any(sig in html for sig in spa_signals):
            return True
        return False

    def _quality_check(self, result: FetchResult) -> bool:
        """检查爬取结果是否有实际内容价值"""
        # 标题不能为空或占位符
        title = (result.title or "").strip()
        bad_titles = {"", "[no-title]", "[no-author]", "无标题", "untitled"}
        if title.lower() in bad_titles or len(title) < 3:
            result.error_msg = result.error_msg or "标题无意义"
            return False

        # 正文 Markdown 有效内容不能太少
        text = (result.content_markdown or "").strip()
        # 去掉标题行、空行、链接行后计算有效字数
        meaningful = sum(len(line.strip()) for line in text.split("\n")
                         if line.strip() and not line.startswith("#") and not line.startswith(">"))
        if meaningful < 100:
            result.error_msg = result.error_msg or f"正文有效内容过少 ({meaningful}字)"
            return False

        return True

    def _fallback_extract(self, html: str) -> str:
        """降级方案：BeautifulSoup 取文本最多的区域"""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        candidates = soup.find_all(["div", "article", "section", "main"])
        best = None
        best_len = 0
        for c in candidates:
            text_len = len(c.get_text(strip=True))
            if text_len > best_len:
                best_len = text_len
                best = c

        if best and best_len > 100:
            return str(best)
        body = soup.find("body")
        return str(body) if body else ""

    def _default_headers(self, referer: str = "") -> dict:
        """生成随机 UA 的请求头"""
        import random
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "DNT": "1",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
        return headers
