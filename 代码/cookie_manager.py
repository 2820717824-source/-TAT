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
