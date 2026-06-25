# Batch 4: Resilience & Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add failure recovery and structured logging so crawling survives interruptions and runs are traceable.

**Architecture:** New `run_state.py` provides two classes — `TaskLogger` (3-stream JSONL logging) and `ResumeState` (SHA256-based completion tracking with failed-URL retry). `CrawlerEngine.run()` gains a resume loop that checks previous failures first, then logs and tracks each request. CLI gains `--resume` and `--retry-failed` flags.

**Tech Stack:** Python 3.10+, stdlib only (json, hashlib, pathlib, datetime), no new dependencies.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `run_state.py` | **Create** | TaskLogger + ResumeState |
| `config.py` | **Modify** | Add resume / retry_failed to CrawlerConfig |
| `engine.py` | **Modify** | Integrate TaskLogger + ResumeState into run() |
| `hotspot_crawler.py` | **Modify** | Add --resume --retry-failed CLI args + wire into run_pipeline |

---

## Task 1: Create run_state.py — TaskLogger

**Files:**
- Create: `run_state.py`
- No tests (output files verified by inspection)

**Interfaces:**
- Produces: `TaskLogger` class with methods below

```python
class TaskLogger:
    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        ...

    def log_request_start(self, url: str, source: str, index: int) -> None: ...
    def log_request_done(self, url: str, status: str, elapsed: float, title: str = "", error: str = "") -> None: ...
    def log_request_skip(self, url: str, reason: str) -> None: ...
    def log_summary(self, keyword: str, stats: dict) -> None: ...
```

- [ ] **Step 1: Create `run_state.py` with TaskLogger class**

Write the file with three log streams under `.crawler_cache/logs/`:

```python
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
```

- [ ] **Step 2: Verify file creates and runs without import error**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
python -c "from run_state import TaskLogger; print('OK')"
```

Expected output: `OK`

---

## Task 2: Add ResumeState to run_state.py

**Files:**
- Modify: `run_state.py` (append to the same file)

**Interfaces:**
- Consumes: `TaskLogger.log_request_skip()` from Task 1
- Produces: `ResumeState` class

```python
class ResumeState:
    def __init__(self, cache_dir: Path = Path(".crawler_cache")): ...
    def _url_key(self, url: str) -> str: ...
    def is_completed(self, url: str) -> bool: ...
    def mark_completed(self, url: str) -> None: ...
    def mark_failed(self, url: str, error: str) -> None: ...
    def get_failed(self) -> list[dict]: ...
    def clear_failed(self) -> None: ...
```

- [ ] **Step 1: Add ResumeState class to run_state.py**

```python
import hashlib


class ResumeState:
    """失败恢复：记录已完成/失败的 URL，下次从断点续爬"""

    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        self.resume_dir = cache_dir / "resume"
        self.resume_dir.mkdir(parents=True, exist_ok=True)
        self.completed_file = self.resume_dir / "completed.txt"
        self.failed_file = self.resume_dir / "failed.jsonl"
        self._completed_cache: set[str] | None = None

    def _url_key(self, url: str) -> str:
        """标准化 URL 后取 SHA256"""
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
                        continue  # 跳过崩溃造成的残缺行
        return records

    def clear_failed(self) -> None:
        if self.failed_file.exists():
            self.failed_file.unlink()
```

- [ ] **Step 2: Verify both classes load correctly**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
python -c "from run_state import TaskLogger, ResumeState; print('OK')"
```

Expected: `OK`

---

## Task 3: Update config.py — add resume fields

**Files:**
- Modify: `config.py` line ~38

**Interfaces:**
- Consumes: existing CrawlerConfig class
- Produces: CrawlerConfig with `resume: bool = True` and `retry_failed: bool = True`

- [ ] **Step 1: Add resume/retry_failed to CrawlerConfig dataclass**

Add two new fields after `dedup_enabled: bool = True`:

```python
    dedup_enabled: bool = True
    resume: bool = True            # 启用失败续爬
    retry_failed: bool = True      # 启动时优先重试上次失败的
    url_file: str | None = None
```

- [ ] **Step 2: Wire loading from load_config()**

In `load_config()` after the dedup line (~line 77), add:

```python
    resume = config_dict.get("resume", {}).get("enabled", True)
    retry_failed = config_dict.get("resume", {}).get("retry_failed", True)
```

And in the CLI override section after `dedup_enabled`, add:

```python
    if getattr(args, "no_resume", False):
        resume = False
```

Then in the `CrawlerConfig(...)` return statement, add `resume=resume` and `retry_failed=retry_failed`.

Also add `--no-resume` to the CLI args (but that's handled in config.py's `load_config` or passed from hotspot_crawler.py).

- [ ] **Step 3: Verify import works**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
python -c "from config import CrawlerConfig; cfg = CrawlerConfig(keyword='test'); print(cfg.resume, cfg.retry_failed)"
```

Expected: `True True`

---

## Task 4: Integrate into engine.py — add run_state logic

**Files:**
- Modify: `engine.py`

**Interfaces:**
- Consumes: `TaskLogger`, `ResumeState` from run_state.py, `CrawlerConfig` from config.py
- Produces: Updated `CrawlerEngine` with `run_state` integration

- [ ] **Step 1: Add imports and init run_state**

At top of `engine.py`, after existing imports:

```python
from run_state import TaskLogger, ResumeState
```

In `CrawlerEngine.__init__()`, add after existing lines:

```python
        self.logger = TaskLogger()
        self.resume_state = ResumeState() if config.resume else None
```

- [ ] **Step 2: Add resume retry loop at start of run()**

At the beginning of `run()`, after `start = time.time()`:

```python
        # 失败恢复：如果启用了续爬，优先重试上次失败的 URL
        if self.resume_state:
            failed_items = self.resume_state.get_failed()
            if failed_items:
                console.print(f"  [yellow]发现上次 {len(failed_items)} 条失败记录，优先重试...[/yellow]")
                # 把失败的 URL 转成 Fake HotItem 插到最前面
                fake_items = []
                for rec in failed_items:
                    title = rec.get("url", "").rsplit("/", 1)[-1][:30] or "unknown"
                    fake_items.append(HotItem(
                        title=title,
                        url=rec["url"],
                        source="resume",
                    ))
                hot_items = fake_items + hot_items
```

Wait, I need to import HotItem. Let me check if it's already imported. Looking at the current engine.py, it doesn't import HotItem. I need to add it.

Actually, looking at the engine.py more carefully, the `run()` method takes `hot_items` as a parameter. The items come from `searcher.py` which returns `list[HotItem]`. So I need to import HotItem.

Let me adjust:

```python
from sources import HotItem
```

And the resume retry logic:

```python
        # 失败恢复：优先重试上次失败的
        if self.resume_state:
            failed_items = self.resume_state.get_failed()
            if failed_items:
                console.print(f"  [yellow]发现 {len(failed_items)} 条上次失败的记录，优先重试...[/yellow]")
                fake_items = [
                    HotItem(title=rec.get("url", "").rsplit("/", 1)[-1][:30], url=rec["url"], source="resume")
                    for rec in failed_items
                ]
                hot_items = fake_items + hot_items
```

- [ ] **Step 3: Add per-request logging + resume tracking inside the loop**

Replace the existing loop body (around lines 53-73) with:

```python
        for i, item in enumerate(hot_items, 1):
            if self.resume_state and self.resume_state.is_completed(item.url):
                report.deduped += 1
                self.logger.log_request_skip(item.url, "resume_completed")
                continue

            if self.dedup and self.dedup.is_duplicate(item.title, item.url):
                report.deduped += 1
                self.logger.log_request_skip(item.url, "deduped")
                continue

            self.logger.log_request_start(item.url, item.source, i)
            result = self.fetcher.fetch(item.url, source=item.source, summary=item.summary)
            result.title = result.title or item.title

            self.saver.save(result, i)
            if result.status == "success":
                report.success += 1
                if self.dedup:
                    self.dedup.mark_seen(item.title, item.url)
                if self.resume_state:
                    self.resume_state.mark_completed(item.url)
            else:
                report.failed += 1
                if self.resume_state:
                    self.resume_state.mark_failed(item.url, result.error_msg)

            self.logger.log_request_done(
                item.url, result.status, result.crawl_time,
                title=result.title, error=result.error_msg,
            )
            results.append(result)
```

- [ ] **Step 4: Add summary logging at end of run()**

After the existing `report.elapsed = time.time() - start`, add:

```python
        if self.resume_state:
            remaining = self.resume_state.get_failed()
            if remaining:
                console.print(f"  [yellow]仍有 {len(remaining)} 条失败，可在下次运行时继续重试[/yellow]")
                self.logger.log_summary(self.config.keyword, {
                    "total": report.total,
                    "success": report.success,
                    "failed": report.failed,
                    "deduped": report.deduped,
                    "remaining_failed": len(remaining),
                    "elapsed": round(report.elapsed, 1),
                })
            else:
                self.resume_state.clear_failed()
        else:
            self.logger.log_summary(self.config.keyword, {
                "total": report.total,
                "success": report.success,
                "failed": report.failed,
                "deduped": report.deduped,
                "elapsed": round(report.elapsed, 1),
            })
```

- [ ] **Step 5: Add import for console + HotItem at top**

Add to existing imports:

```python
from sources import HotItem
from run_state import TaskLogger, ResumeState
from rich.console import Console

console = Console()
```

Note: `console` may already exist in the module that calls engine. Instead of creating a new console here, we should use the one from `hotspot_crawler.py`. Actually, let me keep it simpler - just import and use directly. The rich Console is lightweight.

Actually wait, looking at the existing code more carefully, engine.py doesn't use `console` at all currently. Let me add it.

- [ ] **Step 6: Verify import works**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
python -c "from engine import CrawlerEngine; from config import CrawlerConfig; cfg=CrawlerConfig(keyword='test'); e=CrawlerEngine(cfg); print('OK')"
```

Expected: `OK`

---

## Task 5: Update hotspot_crawler.py — CLI args + wiring

**Files:**
- Modify: `hotspot_crawler.py`

**Interfaces:**
- Consumes: Updated `CrawlerConfig` with resume/retry_failed fields, updated `CrawlerEngine`

- [ ] **Step 1: Add --resume and --no-resume CLI args**

After `--no-dedup` block (~line 520), add:

```python
    parser.add_argument(
        "--resume", action="store_true", default=None,
        help="启用断点续爬（默认: auto，检测到失败记录时自动启用）",
    )
    parser.add_argument(
        "--no-resume", action="store_true", default=None,
        help="禁用断点续爬",
    )
```

- [ ] **Step 2: Wire through run_pipeline()**

In `run_pipeline()` signature, add `resume: bool = True`:

```python
def run_pipeline(
    keyword: str,
    max_per_source: int = 15,
    delay: float = 2.0,
    url_file: str = None,
    browser_mode: str = "auto",
    no_dedup: bool = False,
    resume: bool = True,
    output_formats: list[str] | None = None,
    output_dir: str | None = None,
    source_configs: dict[str, dict] | None = None,
):
```

In the CrawlerConfig construction inside the Step 2 section:

```python
        cfg = CrawlerConfig(
            keyword=keyword,
            max_per_source=max_per_source,
            delay=delay,
            browser_mode=browser_mode,
            output_formats=output_formats or ["md"],
            dedup_enabled=not no_dedup,
            resume=resume,
            output_dir=output_dir,
        )
```

- [ ] **Step 3: Wire CLI args into run_pipeline call**

In `main()` where `run_pipeline()` is called, add `resume`:

```python
    resume = not args.no_resume if args.no_resume else (args.resume or True)
    
    run_pipeline(
        keyword=args.keyword.strip(),
        max_per_source=args.max,
        delay=args.delay,
        url_file=args.url_file,
        browser_mode=args.browser,
        no_dedup=no_dedup,
        resume=resume,
        output_formats=output_formats,
        output_dir=output_dir,
    )
```

- [ ] **Step 4: Verify full pipeline runs**

```bash
cd "C:/Users/24394/Desktop/爬虫热点/代码"
PYTHONIOENCODING=utf-8 python hotspot_crawler.py 测试 --max 1 --delay 1 --browser never
```

Expected: Runs normally, creates `.crawler_cache/logs/` with JSONL files.

---

## Self-Review Checklist

1. **Spec coverage:** 
   - TaskLogger with 3 streams ✓ (Task 1)
   - ResumeState with completed/failed tracking ✓ (Task 2)
   - CrawlerConfig fields ✓ (Task 3)
   - Engine integration ✓ (Task 4)
   - CLI flags ✓ (Task 5)

2. **Placeholder scan:** All steps have complete code. No TBD/TODO. ✓

3. **Type consistency:** 
   - `ResumeState.__init__(cache_dir: Path)` — same in Task 2 and Task 4 ✓
   - `TaskLogger.log_request_done(url, status, elapsed, title, error)` — same in Task 1 and Task 4 ✓
   - `CrawlerConfig(keyword, ..., resume=resume)` — same in Task 3 and Task 5 ✓
