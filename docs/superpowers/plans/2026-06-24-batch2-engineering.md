# 批次 2 — 工程化（多格式输出 + 去重 + 编排器）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 给爬虫增加多格式输出（MD/JSONL/CSV）、内容去重（SHA256+SQLite）、核心编排器（CrawlerEngine），完成工程化基础。

**架构：** 新增 `dedupe.py`（去重）+ `storage.py`（存储）+ `engine.py`（编排器），扩展 `config.py`，改造 `hotspot_crawler.py` 入口集成 engine。

**参考来源：** universal-crawler 的 `dedupe.py`、`storage.py`、`engine.py`

## Global Constraints

- Python 3.10+
- SQLite3 为 Python 内置，无额外依赖
- JSONL/CSV 使用 Python 标准库（json/csv）
- 所有现有功能必须保持兼容
- 去重默认开启，可通过 `--no-dedup` 或 config 关闭
- 输出格式默认 `["md"]`，可通过 config 或 CLI 扩展

---

### Task 1: config.py — 扩充配置字段

**Files:**
- Modify: `C:/Users/24394/Desktop/爬虫热点/代码/config.py`

**Interfaces:**
- Produces: 扩展后的 `CrawlerConfig` dataclass

- [ ] **在 `CrawlerConfig` 中新增字段**

在 `output_formats` 字段之后增加：

```python
    output_dir: str | None = None
    dedup_enabled: bool = True
```

- [ ] **在 `load_config()` 中增加读取逻辑**

在 YAML 解析部分增加：

```python
    dedup_enabled = config_dict.get("dedup", {}).get("enabled", True)
    # CLI 覆盖
    if getattr(args, "no_dedup", False):
        dedup_enabled = False
```

- [ ] **在 `save_default_config()` 中更新模板**

```python
        "dedup": {
            "enabled": True,
        },
        "output": {
            "formats": ["md"],
            "dir": "./文章",
        },
```

---

### Task 2: dedupe.py — 内容去重

**Files:**
- Create: `C:/Users/24394/Desktop/爬虫热点/代码/dedupe.py`

**Interfaces:**
- Produces: `Deduplicator` class

- [ ] **创建 dedupe.py**

```python
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
            db_dir = os.getcwd()
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
```

---

### Task 3: storage.py — 多格式存储

**Files:**
- Create: `C:/Users/24394/Desktop/爬虫热点/代码/storage.py`

**Interfaces:**
- Consumes: `FetchResult` from fetcher.py
- Produces: `StorageResult` dataclass, `ArticleSaverV2` class

- [ ] **创建 storage.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多格式文章存储模块
- MD（Markdown 文件，兼容原有格式）
- JSONL（每行一个 JSON，适合数据分析）
- CSV（表格形式）
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from fetcher import FetchResult


@dataclass
class StorageResult:
    """单次存储结果"""
    path: str
    format: str
    size: int


class ArticleSaverV2:
    """多格式文章保存器"""

    def __init__(self, keyword: str, base_dir: str, formats: list[str] | None = None):
        self.keyword = keyword
        self.base_dir = base_dir or os.getcwd()
        self.formats = formats or ["md"]
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self.output_dir = Path(self.base_dir) / keyword / self.date_str

    def save(self, result: FetchResult, index: int) -> list[StorageResult]:
        """按 formats 列表分别保存，返回所有保存结果"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results: list[StorageResult] = []

        for fmt in self.formats:
            fmt = fmt.lower()
            if fmt == "md":
                path = self._save_md(result, index)
            elif fmt == "jsonl":
                path = self._save_jsonl(result, index)
            elif fmt == "csv":
                path = self._save_csv(result, index)
            else:
                continue
            if path:
                size = os.path.getsize(path)
                results.append(StorageResult(path=path, format=fmt, size=size))

        return results

    def _safe_filename(self, title: str, max_len: int = 40) -> str:
        safe = re.sub(r'[\\/:*?"<>|]', "", title)
        safe = safe.strip().replace(" ", "_")
        return safe[:max_len]

    def _url_slug(self, url: str, max_len: int = 12) -> str:
        slug = url[-16:-1] if len(url) > 16 else url
        return self._safe_filename(slug, max_len)

    def _filename(self, result: FetchResult, index: int, ext: str) -> str:
        title_slug = self._safe_filename(result.title)
        url_slug = self._url_slug(result.url)
        suffix = f"_{url_slug}" if url_slug else ""
        return f"{index:03d}_{title_slug}{suffix}.{ext}"

    def _frontmatter(self, result: FetchResult) -> dict:
        fm = {
            "title": result.title,
            "url": result.url,
            "source": result.source,
            "date": self.date_str,
            "keyword": self.keyword,
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": result.status,
        }
        if result.author:
            fm["author"] = result.author
        if result.summary:
            fm["summary"] = result.summary
        if result.error_msg:
            fm["error"] = result.error_msg
        return fm

    def _save_md(self, result: FetchResult, index: int) -> str:
        """保存为 Markdown 文件（兼容原有格式）"""
        fname = self._filename(result, index, "md")
        fpath = self.output_dir / fname

        lines = []
        lines.append("---")
        lines.append(yaml.dump(self._frontmatter(result), allow_unicode=True,
                               default_flow_style=False, sort_keys=False).strip())
        lines.append("---")
        lines.append("")
        lines.append(f"# {result.title}")
        lines.append("")
        lines.append(f"> 来源：{result.source}  |  日期：{self.date_str}")
        if result.url:
            lines.append(f"> 原文：[{result.url}]({result.url})")
        lines.append("")

        if result.status == "success" and result.content_markdown:
            lines.append(result.content_markdown)
        elif result.error_msg:
            lines.append(f"\n> 爬取失败：{result.error_msg}\n")

        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return str(fpath)

    def _save_jsonl(self, result: FetchResult, index: int) -> str:
        """保存为 JSONL（每行一个 JSON 对象）"""
        fname = self._filename(result, index, "jsonl")
        fpath = self.output_dir / fname

        data = {
            "title": result.title,
            "url": result.url,
            "source": result.source,
            "content": result.content_markdown if result.status == "success" else "",
            "status": result.status,
            "error": result.error_msg,
            "keyword": self.keyword,
            "date": self.date_str,
        }
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        return str(fpath)

    def _save_csv(self, result: FetchResult, index: int) -> str:
        """保存为 CSV（追加模式，自动创建表头）"""
        fname = f"{self.keyword}_{self.date_str}.csv"
        fpath = self.output_dir / fname

        is_new = not fpath.exists()
        with open(fpath, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["title", "url", "source", "content", "status", "keyword", "date"])
            writer.writerow([
                result.title,
                result.url,
                result.source,
                result.content_markdown if result.status == "success" else "",
                result.status,
                self.keyword,
                self.date_str,
            ])
        return str(fpath)

    def save_summary(self, results: list[FetchResult]) -> str:
        """生成汇总文件 _summary.md"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        success_count = sum(1 for r in results if r.status == "success")
        failed_count = sum(1 for r in results if r.status == "failed")
        total = len(results)

        lines = []
        lines.append(f"# 行业热点汇总 — {self.keyword}")
        lines.append("")
        lines.append(f"> 爬取日期：{self.date_str}")
        lines.append(f"> 成功：{success_count} 篇 | 失败：{failed_count} 篇 | 总计：{total} 篇")
        lines.append("")

        for i, r in enumerate(results, 1):
            status_icon = "✓" if r.status == "success" else "✗"
            lines.append(f"### {i:03d}. {r.title}")
            lines.append("")
            lines.append(f"- **来源**：{r.source}")
            lines.append(f"- **链接**：[{r.url}]({r.url})")
            if r.status == "success":
                lines.append(f"- **状态**：✅ 成功")
            else:
                lines.append(f"- **状态**：❌ 失败 ({r.error_msg})")
            lines.append("")

        fpath = self.output_dir / "_summary.md"
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return str(fpath)
```

---

### Task 4: engine.py — 核心编排器

**Files:**
- Create: `C:/Users/24394/Desktop/爬虫热点/代码/engine.py`

**Interfaces:**
- Consumes: `CrawlerConfig` from config.py, `Fetcher`/`FetchResult` from fetcher.py, `Deduplicator` from dedupe.py, `ArticleSaverV2` from storage.py
- Produces: `CrawlerEngine` class, `CrawlerReport` dataclass

- [ ] **创建 engine.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
核心编排器
管理搜索→爬取→去重→存储的全流程
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from config import CrawlerConfig
from dedupe import Deduplicator
from fetcher import Fetcher, FetchResult
from storage import ArticleSaverV2
# hotspot_crawler 中的 HotSearcher 暂不迁移，保持直接引用
import sys
sys.path.insert(0, '.')


@dataclass
class CrawlerReport:
    """爬取报告"""
    total: int = 0
    success: int = 0
    failed: int = 0
    deduped: int = 0
    elapsed: float = 0.0
    output_dir: str = ""


class CrawlerEngine:
    """核心编排器"""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.fetcher = Fetcher(config)
        self.dedup = Deduplicator(config.output_dir) if config.dedup_enabled else None
        self.saver = ArticleSaverV2(
            keyword=config.keyword,
            base_dir=config.output_dir or ".",
            formats=config.output_formats,
        )

    def run(self, hot_items) -> CrawlerReport:
        """执行全流程（接收外部传入的 hot_items 列表）"""
        report = CrawlerReport()
        results: list[FetchResult] = []
        start = time.time()

        for i, item in enumerate(hot_items, 1):
            # 去重检查
            if self.dedup and self.dedup.is_duplicate(item.title, item.url):
                report.deduped += 1
                continue

            # 爬取
            result = self.fetcher.fetch(item.url, source=item.source, summary=item.summary)
            result.title = result.title or item.title

            # 存储
            self.saver.save(result, i)
            if result.status == "success":
                report.success += 1
                if self.dedup:
                    self.dedup.mark_seen(result.title, result.content_markdown)
            else:
                report.failed += 1

            results.append(result)

        # 汇总
        self.saver.save_summary(results)
        report.total = len(results)
        report.elapsed = time.time() - start
        report.output_dir = str(self.saver.output_dir)

        if self.dedup:
            self.dedup.close()

        return report
```

---

### Task 5: hotspot_crawler.py — 集成 Engine

**Files:**
- Modify: `C:/Users/24394/Desktop/爬虫热点/代码/hotspot_crawler.py`

- [ ] **在 import 区添加 engine 导入**

```python
try:
    from engine import CrawlerEngine, CrawlerReport
    _HAS_ENGINE = True
except ImportError:
    _HAS_ENGINE = False
```

- [ ] **在 CLI 参数中添加 `--no-dedup` 和 `--output-format`**

```python
parser.add_argument(
    "--no-dedup", action="store_true",
    help="禁用内容去重",
)
parser.add_argument(
    "--output-format", type=str, default=None,
    help="输出格式: md/jsonl/csv (多个用逗号分隔，如: md,jsonl)",
)
```

- [ ] **在 run_pipeline 中增加 engine 路径**

在原有 `if _HAS_NEW_MODULES` 分支中，当 `_HAS_ENGINE` 时使用 `CrawlerEngine`：

```python
if _HAS_NEW_MODULES:
    if _HAS_ENGINE:
        config = CrawlerConfig(
            keyword=keyword,
            max_per_source=max_per_source,
            delay=delay,
            browser_mode=browser_mode,
            output_formats=output_formats,
            dedup_enabled=not no_dedup,
            output_dir=output_dir,
        )
        engine = CrawlerEngine(config)
        report = engine.run(hot_items)
        # 用 report 打印结果
    else:
        # 使用 Fetcher（批次 1 的逻辑）
        ...
```

转化 `--output-format CLI 参数`：

```python
if args.output_format:
    output_formats = [fmt.strip() for fmt in args.output_format.split(",")]
else:
    output_formats = ["md"]
```

---

## 执行顺序

```
Task 1 (config.py 扩展) → 无依赖
    ↓
Task 2 (dedupe.py) → 无依赖，可并行
Task 3 (storage.py) → 依赖 FetchResult（fetcher.py）
    ↓
Task 4 (engine.py) → 依赖 Task 1, 2, 3
    ↓
Task 5 (hotspot_crawler.py 集成) → 依赖 Task 4
```
