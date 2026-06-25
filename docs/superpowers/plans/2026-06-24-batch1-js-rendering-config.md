# 批次 1 — JS 渲染 + 配置系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给爬虫加上 Playwright JS 渲染能力（带隐身配置）+ YAML 配置系统，命令行加 `--browser` 参数智能降级。

**架构：** 新增 `config.py`（配置加载）+ `browser_fetcher.py`（Playwright 渲染）+ `fetcher.py`（双引擎获取器），改造 `hotspot_crawler.py` 入口。搜素和存储逻辑暂不移动。

**参考来源：**
- `D:\js动态爬虫\image_crawler-main\...\crawler_engine.py` L540-617 → 隐身配置
- `D:\js动态爬虫\universal-crawler-main\...\crawler\browser_fetcher.py` → 动作脚本

## Global Constraints

- Python 3.10+
- Playwright 为可选依赖，用 `try/except ImportError` 包裹
- 所有现有 CLI 用法必须保持兼容（keyword、--max、--delay、--url-file）
- 新增 `--browser` 参数缺省值 `auto`
- 新增 `--config` 参数指向 YAML 文件
- 模块间通过 dataclass 传参，不共享全局状态
- `browser_fetcher.py` 不被入口直接引用，只被 `fetcher.py` 引用

---

### Task 1: config.py — 配置加载模块

**Files:**
- Create: `C:/Users/24394/Desktop/爬虫热点/代码/config.py`

**Interfaces:**
- Produces: `CrawlerConfig` dataclass, `load_config(args) -> CrawlerConfig`, `save_default_config()`

- [ ] **Step 1: 创建 config.py 文件**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class CrawlerConfig:
    """爬虫配置，由 YAML + CLI 合并而来，CLI 参数优先"""
    keyword: str
    sources: list[str] | None = None
    max_per_source: int = 15
    delay: float = 2.0
    browser_mode: str = "auto"       # "auto" | "always" | "never"
    output_formats: list[str] | None = None  # 默认 ["md"]
    output_dir: str | None = None
    url_file: str | None = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = ["baidu", "zhihu", "bing"]
        if self.output_formats is None:
            self.output_formats = ["md"]
        if self.output_dir is None:
            self.output_dir = os.getcwd()


def load_config(args: argparse.Namespace) -> CrawlerConfig:
    """加载配置：YAML 文件（如果有）→ CLI 覆盖 → 返回 CrawlerConfig"""
    # 1. 先尝试从 YAML 加载
    config_dict = {}
    if getattr(args, "config", None):
        config_path = Path(args.config)
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                config_dict = yaml.safe_load(f) or {}
        else:
            print(f"  [警告] 配置文件不存在: {args.config}")

    # 2. 从 YAML 提取初始值
    keyword = config_dict.get("keyword", args.keyword)
    sources = config_dict.get("sources")
    max_per_source = config_dict.get("max_per_source", 15)
    delay = config_dict.get("delay", 2.0)
    browser_mode = config_dict.get("browser", {}).get("mode", "auto")
    output_formats = config_dict.get("output", {}).get("formats")
    output_dir = config_dict.get("output", {}).get("dir")

    # 3. CLI 参数覆盖（显式传入的才覆盖）
    if args.keyword:
        keyword = args.keyword
    if args.max != 15:  # 用户显式传了 --max
        max_per_source = args.max
    if args.delay != 2.0:
        delay = args.delay
    if args.url_file:
        sources = None
        url_file = args.url_file
    else:
        url_file = None
    if getattr(args, "browser", None):
        browser_mode = args.browser

    return CrawlerConfig(
        keyword=keyword,
        sources=sources,
        max_per_source=max_per_source,
        delay=delay,
        browser_mode=browser_mode,
        output_formats=output_formats,
        output_dir=output_dir,
        url_file=url_file,
    )


def save_default_config(path: str = "config.yaml"):
    """生成一份默认配置文件"""
    config = {
        "keyword": "行业关键词",
        "sources": ["baidu", "zhihu", "bing", "weibo"],
        "max_per_source": 15,
        "delay": 2.0,
        "browser": {
            "mode": "auto",     # auto | always | never
        },
        "output": {
            "formats": ["md"],
            "dir": "./文章",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  默认配置文件已生成: {path}")
```

---

### Task 2: browser_fetcher.py — Playwright 渲染器

**Files:**
- Create: `C:/Users/24394/Desktop/爬虫热点/代码/browser_fetcher.py`

**Interfaces:**
- Consumes: nothing from other tasks
- Produces: `BrowserFetcher` class, `fetch(url, actions) -> str`

**参考代码:**
- image_crawler `crawler_engine.py` L540-617（隐身配置）
- universal-crawler `browser_fetcher.py`（动作脚本框架）

- [ ] **Step 1: 创建 browser_fetcher.py**

```python
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
```

---

### Task 3: fetcher.py — 双引擎获取器

**Files:**
- Create: `C:/Users/24394/Desktop/爬虫热点/代码/fetcher.py`

**Interfaces:**
- Consumes: `CrawlerConfig` from config.py, `BrowserFetcher` from browser_fetcher.py
- Produces: `FetchResult` dataclass, `Fetcher` class

- [ ] **Step 1: 创建 fetcher.py，提取现有 ArticleCrawler 逻辑**

```python
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
```

---

### Task 4: 改造 hotspot_crawler.py — 集成新模块

**Files:**
- Modify: `C:/Users/24394/Desktop/爬虫热点/代码/hotspot_crawler.py`

**Interfaces:**
- Consumes: `CrawlerConfig` / `load_config` from config.py, `Fetcher` / `FetchResult` from fetcher.py

- [ ] **Step 1: 在 import 区添加新模块引用**

在文件顶部添加：

```python
# 新模块（可选依赖）
try:
    from config import CrawlerConfig, load_config
    from fetcher import Fetcher, FetchResult
    _HAS_NEW_MODULES = True
except ImportError:
    _HAS_NEW_MODULES = False
```

- [ ] **Step 2: 在 `run_pipeline()` 中增加配置加载和浏览器参数**

把 `run_pipeline()` 函数改为接收一个 `CrawlerConfig` 参数，并增加条件：

```python
def run_pipeline(
    keyword: str,
    max_per_source: int = 15,
    delay: float = 2.0,
    url_file: str = None,
    browser_mode: str = "auto",
):
    """执行完整爬取流水线"""
    start_time = time.time()
    print_banner()

    # 参数校验
    if delay < 0.5:
        console.print("  [yellow]--delay 过小可能导致被拦截，推荐 >= 1.0[/yellow]")
    if max_per_source < 1:
        console.print("  [red]--max 至少为 1[/red]")
        return

    # Step 1: 搜索热点
    # ...（保持现有 HotSearcher 逻辑不变）...

    # Step 2: 爬取正文（使用新 Fetcher 或旧 ArticleCrawler）
    if _HAS_NEW_MODULES and browser_mode != "never":
        config = CrawlerConfig(
            keyword=keyword,
            max_per_source=max_per_source,
            delay=delay,
            browser_mode=browser_mode,
            url_file=url_file,
        )
        fetcher = Fetcher(config)
        results = []
        for i, item in enumerate(hot_items, 1):
            result = fetcher.fetch(item.url, source=item.source, summary=item.summary)
            # ...（保存和进度显示逻辑）...
    else:
        # 降级到原有的 ArticleCrawler
        crawler = ArticleCrawler(delay)
        # ...（保持现有逻辑）...

    # Step 3 & 4: 生成汇总 + 报告（不变）
    ...
```

- [ ] **Step 3: 在 CLI 参数中新增 `--browser` 和 `--config`**

```python
parser.add_argument(
    "--browser", choices=["auto", "always", "never"], default="auto",
    help="浏览器渲染模式: auto=智能降级, always=强制浏览器, never=禁用(默认: auto)",
)
parser.add_argument(
    "--config", type=str, default=None,
    help="YAML 配置文件路径（CLI 参数会覆盖配置文件中对应的值）",
)
```

- [ ] **Step 4: 将 browser_mode 传递给 run_pipeline**

```python
try:
    run_pipeline(
        keyword=args.keyword.strip(),
        max_per_source=args.max,
        delay=args.delay,
        url_file=args.url_file,
        browser_mode=args.browser,
    )
except KeyboardInterrupt:
    ...
```

- [ ] **Step 5: 创建默认配置文件**

```bash
# 生成默认 config.yaml
python -c "from config import save_default_config; save_default_config('config.yaml')"
```

---

## 执行顺序

```
Task 1 (config.py)
    ↓
Task 2 (browser_fetcher.py)
    ↓
Task 3 (fetcher.py) —— 依赖 Task 1 和 Task 2
    ↓
Task 4 (hotspot_crawler.py) —— 依赖 Task 1 和 Task 3
```

每完成一个 Task，更新 CHANGELOG.md。
