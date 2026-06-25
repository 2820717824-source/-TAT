#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行状态追踪：结构化日志 + 失败恢复
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class TaskLogger:
    """三流 JSONL 日志：request / error / summary"""

    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        self.log_dir = cache_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, file: str, data: dict) -> None:
        data["ts"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(data, ensure_ascii=False)
        with open(self.log_dir / file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def log_request_start(self, url: str, source: str, index: int) -> None:
        self._write("request_log.jsonl", {
            "event": "request_start",
            "url": url,
            "source": source,
            "index": index,
        })

    def log_request_done(self, url: str, status: str, elapsed: float,
                         title: str = "", error: str = "") -> None:
        self._write("request_log.jsonl", {
            "event": "request_done",
            "url": url,
            "status": status,
            "elapsed": round(elapsed, 2),
            "title": title,
        })
        if status == "failed":
            self._write("error_log.jsonl", {
                "event": "fetch_failed",
                "url": url,
                "error": error,
                "elapsed": round(elapsed, 2),
            })

    def log_request_skip(self, url: str, reason: str) -> None:
        self._write("request_log.jsonl", {
            "event": "request_skip",
            "url": url,
            "reason": reason,
        })

    def log_summary(self, keyword: str, stats: dict) -> None:
        self._write("summary_log.jsonl", {
            "event": "run_complete",
            "keyword": keyword,
            **stats,
        })
