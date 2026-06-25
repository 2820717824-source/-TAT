# 知乎登录 Cookie 管理 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans.

**Goal:** Add `--login zhihu` CLI command that opens Playwright browser for QR login, auto-extracts and caches Cookie.

**Architecture:** New `cookie_manager.py` handles save/load/validation of per-source cookies. CLI entry point triggers Playwright login flow. `sources/zhihu.py` auto-loads cached cookie at search time.

**Tech Stack:** Python 3.10+, stdlib + existing Playwright dependency. No new dependencies.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `cookie_manager.py` | **Create** | Cookie persistence (save/load/validate) |
| `sources/zhihu.py` | **Modify** | Load cookie from CookieManager at search time |
| `hotspot_crawler.py` | **Modify** | Add `--login zhihu` CLI arg + login flow |

---

## Task 1: Create cookie_manager.py

**Files:**
- Create: `cookie_manager.py`

**Interfaces:**
- Produces: `CookieManager` class

```python
class CookieManager:
    def __init__(self, cache_dir: Path = Path(".crawler_cache")): ...
    def save(self, source: str, cookie_str: str) -> None: ...
    def load(self, source: str) -> dict | None: ...
    def get_cookie_str(self, source: str) -> str | None: ...
    def cookie_valid(self, source: str) -> bool: ...
```

- [ ] **Step 1: Write cookie_manager.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cookie 持久化管理：保存/加载/验证各源的登录 Cookie
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class CookieManager:
    """按源保存/加载 Cookie"""

    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        self.cookie_dir = cache_dir / "cookies"
        self.cookie_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str) -> Path:
        return self.cookie_dir / f"{source}.json"

    def save(self, source: str, cookie_str: str) -> None:
        data = {
            "cookie": cookie_str,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._path(source), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, source: str) -> dict | None:
        path = self._path(source)
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def get_cookie_str(self, source: str) -> str | None:
        data = self.load(source)
        return data["cookie"] if data else None

    def cookie_valid(self, source: str) -> bool:
        return self._path(source).exists()
```

- [ ] **Step 2: Verify**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
python -c "
from cookie_manager import CookieManager
cm = CookieManager()
cm.save('zhihu', 'test_cookie=123')
assert cm.cookie_valid('zhihu')
assert cm.get_cookie_str('zhihu') == 'test_cookie=123'
assert cm.load('zhihu')['saved_at'] is not None
print('CookieManager OK')
"
```

---

## Task 2: Modify sources/zhihu.py to use CookieManager

**Files:**
- Modify: `sources/zhihu.py`

- [ ] **Step 1: Read current zhihu.py, add CookieManager import and cookie loading**

Add import at top:
```python
from cookie_manager import CookieManager
```

In `ZhihuSource.__init__()` or in `search()` method, after constructing headers, add:
```python
        # 自动加载缓存的 Cookie
        cm = CookieManager()
        cookie = cm.get_cookie_str("zhihu")
        if cookie:
            self.headers["Cookie"] = cookie
```

- [ ] **Step 2: Verify**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
python -c "
from sources.zhihu import ZhihuSource
src = ZhihuSource()
print(f'ZhihuSource init OK, cookie_loaded={src.headers.get(\"Cookie\", \"\")[:20]}...')
"
```

---

## Task 3: Add --login CLI + Playwright login flow

**Files:**
- Modify: `hotspot_crawler.py`

**Note:** The login flow uses Playwright directly (not through BrowserFetcher) because BrowserFetcher is designed for headless page content fetching and doesn't expose the page object. Login needs non-headless mode with interactive cookie access.

- [ ] **Step 1: Add --login CLI argument**

After the `--output-format` arg (~line 532), add:
```python
    parser.add_argument(
        "--login", type=str, default=None,
        choices=["zhihu"],
        help="登录指定平台并保存 Cookie（当前支持: zhihu）",
    )
```

- [ ] **Step 2: Add login handling in main()**

After `args = parser.parse_args()`, add:
```python
    if args.login:
        if args.login == "zhihu":
            _login_zhihu()
        sys.exit(0)
```

- [ ] **Step 3: Implement _login_zhihu() function**

Before `main()`, add:
```python
def _login_zhihu():
    """打开 Playwright 浏览器让用户扫码登录知乎，自动提取 Cookie"""
    console.print("  [cyan]正在打开知乎登录页...[/cyan]")
    console.print("  [yellow]请用手机知乎 App 扫码登录[/yellow]")
    console.print("  [dim]等待登录中（最长 3 分钟）...[/dim]")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("  [red]Playwright 未安装，请运行: pip install playwright && playwright install chromium[/red]")
        sys.exit(1)

    from cookie_manager import CookieManager

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )
        page = context.new_page()
        page.goto("https://www.zhihu.com/signin", wait_until="networkidle")

        import time
        for _ in range(180):
            time.sleep(1)
            cookies = context.cookies()
            has_login = any(
                c["name"] in ("z_c0", "sessionid", "login")
                and "zhihu" in c["domain"]
                for c in cookies
            )
            if has_login:
                cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)
                CookieManager().save("zhihu", cookie_str)
                console.print(f"  [green]登录成功！Cookie 已保存[/green]")
                browser.close()
                return

        console.print("  [red]登录超时（3 分钟），请重试[/red]")
        browser.close()
```

- [ ] **Step 4: Verify**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
python hotspot_crawler.py --help
# Should show --login in help text

python -c "
from cookie_manager import CookieManager
# Simulate login save
CookieManager().save('zhihu', 'test_cookie=abc')
assert CookieManager().cookie_valid('zhihu')
print('--login flow ready')
"
```
