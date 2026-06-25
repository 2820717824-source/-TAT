#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
内容去重模块
- SHA256 内容哈希去重
- SQLite 持久化（跨运行）
- 去重范围：标题 + 内容前 1000 字
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path


class Deduplicator:
    """内容去重器，SHA256 哈希 + SQLite 持久化"""

    def __init__(self, db_dir: str | None = None):
        if db_dir is None:
            # 固定到项目代码目录，不受 CWD 影响
            db_dir = str(Path(__file__).resolve().parent)
        db_path = Path(db_dir) / ".crawler_cache" / "dedup.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS dedup (
                hash TEXT PRIMARY KEY,
                title TEXT,
                first_seen TEXT DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    def _hash(self, title: str, content: str) -> str:
        """计算 SHA256 哈希（标题 + 内容前 1000 字）"""
        text = (title or "") + (content or "")[:1000]
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def is_duplicate(self, title: str, content: str) -> bool:
        """检查是否已爬取过"""
        h = self._hash(title, content)
        cursor = self._conn.execute("SELECT 1 FROM dedup WHERE hash = ?", (h,))
        return cursor.fetchone() is not None

    def mark_seen(self, title: str, content: str):
        """记录已爬取"""
        h = self._hash(title, content)
        self._conn.execute(
            "INSERT OR IGNORE INTO dedup (hash, title) VALUES (?, ?)",
            (h, (title or "")[:200]),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()
