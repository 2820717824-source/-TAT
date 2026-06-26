# ProxyProvider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dynamic proxy pool that pulls free HTTP proxies from GitHub, caches them locally, and automatically rotates on 429/5xx failures.

**Architecture:** New `proxy_manager.py` provides `ProxyProvider` class. Modified `fetch_url()` in `sources/__init__.py` accepts proxy pool and rotates proxies on retryable failures. Engine/Searcher creates proxy pool when `config.proxy` is True.

**Tech Stack:** Python 3.10+ stdlib only (requests, hashlib, json, pathlib, threading), no new dependencies.

**Reference:** javaCrawling NetPoxyService (API pull → TTL filter → random rotation pattern), adapted for TheSpeedX/PROXY-List HTTP proxy list.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `proxy_manager.py` | **Create** | ProxyProvider class |
| `sources/__init__.py` | **Modify** | Add proxy pool param to `fetch_url()` + `set_proxy_pool()` setter |
| `config.py` | **Modify** | Add `proxy: bool` field + default config yaml section |
| `searcher.py` | **Modify** | Wire proxy pool into sources when enabled |
| `engine.py` | **Modify** | Pass proxy config through to Searcher |

---

## Task 1: Create proxy_manager.py — ProxyProvider

**Files:**
- Create: `proxy_manager.py`
- No test file (tested via curl/manual run)

**Interfaces:**
- Produces: `ProxyProvider` class with methods: `get_proxy()`, `refresh()`, `report_failure()`, `available()`

### Step 1: Write ProxyProvider

Create `proxy_manager.py` with the following implementation (~80 lines):

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态代理池：从 GitHub 公开代理列表拉取 HTTP 代理，带本地缓存和失效剔除

参考 javaCrawling NetPoxyService 的设计模式：
数据源 API → 解析 → TTL 过滤 → 随机轮换 → 失败剔除
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

PROXY_LIST_URL = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
CACHE_FILE = "proxies.json"
QUICK_TEST_TIMEOUT = 5
CACHE_TTL_HOURS = 1
MAX_FAIL_COUNT = 3


class ProxyProvider:
    """动态代理池，从 GitHub 拉取 HTTP 代理列表，自动缓存和失效剔除"""

    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        self.cache_path = cache_dir / CACHE_FILE
        self._proxies: list[dict] = []  # [{"addr": "ip:port", "fail_count": 0}, ...]
        self._load_cache()

    # ── 公共接口 ──

    def get_proxy(self) -> Optional[str]:
        """返回一个随机可用代理 "ip:port"，无可用时返回 None"""
        if not self._proxies:
            if self._cache_expired():
                self.refresh()
            if not self._proxies:
                return None
        proxy = random.choice(self._proxies)
        return proxy["addr"]

    def refresh(self) -> int:
        """从 GitHub 拉取最新代理列表，测试可用后缓存，返回可用数量"""
        try:
            resp = requests.get(PROXY_LIST_URL, timeout=10)
            if resp.status_code != 200:
                return len(self._proxies)
            lines = resp.text.strip().split("\n")
            raw_proxies = [line.strip() for line in lines if line.strip() and ":" in line]
            # 快速测试前 50 个
            tested = []
            for addr in raw_proxies[:50]:
                if self._quick_test(addr):
                    tested.append({"addr": addr, "fail_count": 0})
            if tested:
                self._proxies = tested
                self._save_cache()
            return len(self._proxies)
        except requests.RequestException:
            return len(self._proxies)

    def report_failure(self, proxy_addr: str) -> None:
        """标记代理失败，连续失败 MAX_FAIL_COUNT 次后移除"""
        for p in self._proxies:
            if p["addr"] == proxy_addr:
                p["fail_count"] += 1
                if p["fail_count"] >= MAX_FAIL_COUNT:
                    self._proxies.remove(p)
                break

    def available(self) -> bool:
        """是否有可用代理"""
        return len(self._proxies) > 0

    # ── 内部方法 ──

    def _quick_test(self, proxy_addr: str) -> bool:
        """快速测试代理是否可用"""
        try:
            resp = requests.get(
                "http://httpbin.org/ip",
                proxies={"http": proxy_addr, "https": proxy_addr},
                timeout=QUICK_TEST_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _cache_expired(self) -> bool:
        """缓存是否过期（超过 CACHE_TTL_HOURS 小时）"""
        if not self.cache_path.exists():
            return True
        mtime = datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=timezone.utc)
        age = (datetime.now(timezone.utc) - mtime).total_seconds()
        return age > CACHE_TTL_HOURS * 3600

    def _load_cache(self) -> None:
        """从本地缓存加载"""
        if self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self._proxies = data.get("proxies", [])
            except (json.JSONDecodeError, OSError):
                self._proxies = []

    def _save_cache(self) -> None:
        """保存到本地缓存"""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "proxies": self._proxies,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "github",
        }
        self.cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 1: Write proxy_manager.py with full ProxyProvider implementation**

Write the file with all the code above. Verify it parses:

```bash
cd "C:\Users\24394\Desktop\爬虫热点"
python -c "from proxy_manager import ProxyProvider; p=ProxyProvider(); print('OK, proxies:', len(p._proxies))"
```

Expected: `OK, proxies: 0` (no cache yet, but class loads fine)

- [ ] **Step 2: Commit**

```bash
git add proxy_manager.py
git commit -m "feat: add ProxyProvider - dynamic proxy pool from GitHub"
```

---

## Task 2: Update sources/__init__.py — proxy support in fetch_url

**Files:**
- Modify: `sources/__init__.py`
  - Add module-level `_proxy_pool` variable and `set_proxy_pool()` function
  - Modify `fetch_url()` to accept proxy pool and rotate on retryable failure

**Interfaces:**
- Consumes: `ProxyProvider` from Task 1
- Produces: `set_proxy_pool(pool)`, updated `fetch_url()` with proxy rotation

### Step 1: Add module-level proxy pool variable

After the imports block (~line 22), add:

```python
from proxy_manager import ProxyProvider

# 模块级代理池（由引擎在启动时设置）
_proxy_pool: ProxyProvider | None = None


def set_proxy_pool(pool: ProxyProvider | None) -> None:
    """设置模块级代理池（引擎启动时调用）"""
    global _proxy_pool
    _proxy_pool = pool
```

### Step 2: Modify fetch_url() to accept proxy_pool parameter

Change the function signature and add proxy rotation within the retry loop.

Replace the existing `fetch_url()` function (lines 66-106) with:

```python
def fetch_url(url: str, session: requests.Session, headers: dict = None,
              timeout: int = None, retry_times: int = 0,
              retry_backoff: float = 1.0,
              retryable_status: list[int] | None = None,
              proxy_pool: ProxyProvider | None = None) -> Optional[str]:
    """通用 GET 请求，支持指数退避重试 + 代理轮换

    参考 universal-crawler fetcher.py L47-73 的重试模式：
    - retry_times=0: 不重试（兼容旧行为）
    - retry_times>0: 在 429/5xx 和网络错误时指数退避重试
    - proxy_pool 提供时，失败后自动从池中换代理重试
    """
    if retryable_status is None:
        retryable_status = [429, 500, 502, 503, 504]

    # 使用传入的 pool，没有则用模块级 pool
    pool = proxy_pool or _proxy_pool
    last_error: str | None = None
    current_proxy: str | None = None

    for attempt in range(retry_times + 1):
        # 第一次失败后尝试用代理
        if attempt > 0 and pool and pool.available():
            current_proxy = pool.get_proxy()

        proxies = {"http": current_proxy, "https": current_proxy} if current_proxy else None

        try:
            resp = session.get(
                url,
                headers=headers or default_headers(),
                timeout=timeout or REQUEST_TIMEOUT,
                proxies=proxies,
            )
            if resp.status_code == 200:
                if resp.encoding and resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            if resp.status_code in retryable_status:
                last_error = f"HTTP {resp.status_code}"
                if current_proxy:
                    pool.report_failure(current_proxy)
            else:
                return None
        except requests.RequestException as e:
            last_error = str(e)
            if current_proxy:
                pool.report_failure(current_proxy)

        if attempt < retry_times:
            sleep_seconds = retry_backoff * (2 ** attempt) + random.random()
            time.sleep(sleep_seconds)

    return None
```

Key changes from original:
1. Added `proxy_pool` parameter
2. On first retryable failure (attempt > 0), tries to get a proxy from pool
3. Passes proxy to `session.get()` via `proxies=`
4. On failure with proxy, calls `pool.report_failure()`

- [ ] **Step 1: Add `set_proxy_pool()` to sources/__init__.py**

Add the import and function after the constants block.

- [ ] **Step 2: Replace `fetch_url()` with proxy-aware version**

Replace the original function (lines 66-106) with the updated version.

- [ ] **Step 3: Verify module loads without error**

```bash
cd "C:\Users\24394\Desktop\爬虫热点"
python -c "from sources import fetch_url, set_proxy_pool; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add sources/__init__.py
git commit -m "feat: add proxy rotation support to fetch_url"
```

---

## Task 3: Update config.py — add proxy field

**Files:**
- Modify: `config.py`
  - Add `proxy: bool` field to CrawlerConfig
  - Update `load_config()` to parse proxy from YAML
  - Update `save_default_config()` to include proxy section

### Step 1: Add proxy field to CrawlerConfig dataclass

After line 41 (`retry_failed: bool = True`), add:

```python
    proxy: bool = False       # 是否启用代理池（默认关闭）
```

### Step 2: Update load_config() to parse proxy from YAML

After line 81 (`retry_failed = ...`), add:

```python
    proxy_enabled = config_dict.get("proxy", {}).get("enabled", False)
```

In the CLI override section, no CLI arg for proxy (YAML-only for now — user doesn't need to toggle this from command line).

In the `CrawlerConfig(...)` constructor, after `retry_failed`:

```python
        proxy=proxy_enabled,
```

### Step 3: Update save_default_config()

Insert a `proxy` section in the YAML template after `resume` block (line ~144):

```python
        "proxy": {
            "enabled": False,
        },
```

### Step 4: Verify config loads

```bash
cd "C:\Users\24394\Desktop\爬虫热点"
python -c "from config import CrawlerConfig; cfg=CrawlerConfig(keyword='test'); print('proxy:', cfg.proxy)"
```

Expected: `proxy: False`

### Step 5: Commit

```bash
git add config.py
git commit -m "feat: add proxy config option to CrawlerConfig"
```

---

## Task 4: Wire proxy into engine / searcher

**Files:**
- Modify: `engine.py` — create ProxyProvider when proxy enabled
- Modify: `searcher.py` — set proxy pool on sources

**Interfaces:**
- Consumes: Updated `CrawlerConfig` with `proxy` field (Task 3)
- Produces: ProxyProvider created and wired into sources at startup

### Step 1: Update engine.py — create ProxyProvider in __init__

Add import at top:

```python
from proxy_manager import ProxyProvider
from sources import set_proxy_pool
```

In `CrawlerEngine.__init__()`, after existing init code (~line 53), add:

```python
        self.proxy_pool: ProxyProvider | None = None
        if config.proxy:
            self.proxy_pool = ProxyProvider()
            set_proxy_pool(self.proxy_pool)
            if not self.proxy_pool.available():
                n = self.proxy_pool.refresh()
                console.print(f"  [dim]代理池: 拉取到 {n} 个可用代理[/dim]")
```

### Step 2: Verify full pipeline can initialize with proxy

```bash
cd "C:\Users\24394\Desktop\爬虫热点"
PYTHONIOENCODING=utf-8 python -c "
from config import CrawlerConfig
from engine import CrawlerEngine
cfg = CrawlerConfig(keyword='test', proxy=True)
e = CrawlerEngine(cfg)
print('Engine OK, proxy available:', e.proxy_pool.available() if e.proxy_pool else False)
"
```

Expected: `Engine OK, proxy available: True` (or False if GitHub unreachable — either is OK, just shouldn't crash)

### Step 3: Quick integration test

```bash
cd "C:\Users\24394\Desktop\爬虫热点"
PYTHONIOENCODING=utf-8 python hotspot_crawler.py 测试 --max 1 --delay 1 --browser never
```

Expected: Runs normally, no regression.

### Step 4: Commit

```bash
git add engine.py searcher.py
git commit -m "feat: wire proxy pool into engine"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - ProxyProvider with refresh/load/save/get_proxy/report_failure ✓ (Task 1)
   - fetch_url proxy parameter + rotation ✓ (Task 2)
   - Config field ✓ (Task 3)
   - Engine integration ✓ (Task 4)
   - Quick test filtering ✓ (Task 1)
   - Cache with expiry ✓ (Task 1)

2. **Placeholder scan:** All steps have complete code. No TBD/TODO. ✓

3. **Type consistency:**
   - `ProxyProvider.get_proxy()` returns `str | None` — used in `fetch_url()` as `proxies={"http": proxy, "https": proxy}` ✓
   - `ProxyProvider.report_failure(proxy_addr: str)` — called with string ✓
   - `set_proxy_pool(pool: ProxyProvider | None)` — module-level setter ✓
   - `CrawlerConfig.proxy: bool = False` — default off ✓
