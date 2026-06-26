#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dynamic proxy pool that pulls free HTTP proxies from a GitHub list.

Provides proxy rotation with failure tracking and local caching.
Patterns follow the existing codebase conventions (sources/__init__.py style).
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ============================================================
# Constants
# ============================================================

PROXY_LIST_URL = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
CACHE_FILE = "proxies.json"
QUICK_TEST_TIMEOUT = 5
CACHE_TTL_HOURS = 1
MAX_FAIL_COUNT = 3


class ProxyProvider:
    """Dynamic proxy pool with failure tracking and local caching.

    Pulls free HTTP proxies from a GitHub list, caches them locally,
    and provides random proxy selection with failure tracking.
    """

    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        self._cache_dir = cache_dir
        self._cache_path = cache_dir / CACHE_FILE
        self._proxies: list[dict] = []
        self._load_cache()

    # ---- Public API ----

    def get_proxy(self) -> str | None:
        """Return a random proxy addr (ip:port), or None if pool is empty.

        If pool is empty and cache is expired, triggers a refresh.
        """
        if not self._proxies and self._cache_expired():
            self.refresh()
        if not self._proxies:
            return None
        return random.choice(self._proxies)["addr"]

    def refresh(self) -> int:
        """Pull proxy list from GitHub, quick-test first 50, cache valid ones.

        Returns:
            Number of valid proxies cached. On network error, returns current pool size.
        """
        try:
            resp = requests.get(PROXY_LIST_URL, timeout=QUICK_TEST_TIMEOUT * 3)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Failed to fetch proxy list: %s", e)
            return len(self._proxies)

        lines = resp.text.strip().splitlines()
        # Filter out empty lines and comments
        candidates = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]

        valid = []
        for addr in candidates[:50]:
            if self._quick_test(addr):
                valid.append({"addr": addr, "fail_count": 0})

        self._proxies = valid
        self._save_cache()
        logger.info("Refreshed proxy pool: %d valid proxies", len(valid))
        return len(valid)

    def report_failure(self, proxy_addr: str) -> None:
        """Increment fail_count for the given proxy. Remove if >= MAX_FAIL_COUNT."""
        for i, proxy in enumerate(self._proxies):
            if proxy["addr"] == proxy_addr:
                proxy["fail_count"] += 1
                if proxy["fail_count"] >= MAX_FAIL_COUNT:
                    self._proxies.pop(i)
                    logger.debug("Removed proxy %s (fail_count=%d)",
                                 proxy_addr, proxy["fail_count"])
                break

    def available(self) -> bool:
        """Return True if the pool has at least one proxy."""
        return len(self._proxies) > 0

    # ---- Internal methods ----

    def _quick_test(self, proxy_addr: str) -> bool:
        """Test if a proxy works by making a request through it.

        GET httpbin.org/ip through the proxy. Returns True if status 200.
        """
        proxies = {"http": f"http://{proxy_addr}", "https": f"http://{proxy_addr}"}
        try:
            resp = requests.get(
                "http://httpbin.org/ip",
                proxies=proxies,
                timeout=QUICK_TEST_TIMEOUT,
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _cache_expired(self) -> bool:
        """Return True if cache file doesn't exist or mtime > CACHE_TTL_HOURS old."""
        if not self._cache_path.exists():
            return True
        age_seconds = time.time() - self._cache_path.stat().st_mtime
        return age_seconds > CACHE_TTL_HOURS * 3600

    def _load_cache(self) -> None:
        """Load proxies from cache JSON.

        Expected format: {"proxies": [{"addr": "ip:port", "fail_count": 0}, ...]}
        Invalid or missing file -> empty pool.
        """
        if not self._cache_path.exists():
            self._proxies = []
            return
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
            self._proxies = data.get("proxies", [])
            # Normalise: ensure every entry has a fail_count
            for p in self._proxies:
                if "addr" not in p:
                    raise ValueError("Proxy entry missing 'addr' field")
                p.setdefault("fail_count", 0)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning("Failed to load proxy cache: %s", e)
            self._proxies = []

    def _save_cache(self) -> None:
        """Save proxies to cache JSON with metadata."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "proxies": self._proxies,
            "fetched_at": time.time(),
            "source": "TheSpeedX/PROXY-List",
        }
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
