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

import hashlib


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


class ResumeState:
    """失败恢复：记录已完成/失败的 URL，下次从断点续爬"""

    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        self.resume_dir = cache_dir / "resume"
        self.resume_dir.mkdir(parents=True, exist_ok=True)
        self.completed_file = self.resume_dir / "completed.txt"
        self.failed_file = self.resume_dir / "failed.jsonl"
        self._completed_cache: set[str] | None = None

    def _url_key(self, url: str) -> str:
        normalized = url.lower().rstrip("/")
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _load_completed(self) -> set[str]:
        if self._completed_cache is None:
            seen: set[str] = set()
            if self.completed_file.exists():
                with open(self.completed_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and len(line) == 64:
                            seen.add(line)
            self._completed_cache = seen
        return self._completed_cache

    def is_completed(self, url: str) -> bool:
        return self._url_key(url) in self._load_completed()

    def mark_completed(self, url: str) -> None:
        key = self._url_key(url)
        self._load_completed().add(key)
        with open(self.completed_file, "a", encoding="utf-8") as f:
            f.write(key + "\n")

    def mark_failed(self, url: str, error: str) -> None:
        record = {
            "url": url,
            "error": str(error)[:120],
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.failed_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_failed(self) -> list[dict]:
        if not self.failed_file.exists():
            return []
        records: list[dict] = []
        with open(self.failed_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def clear_failed(self) -> None:
        if self.failed_file.exists():
            self.failed_file.unlink()
