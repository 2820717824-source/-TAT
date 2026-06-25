# 爬虫架构升级设计文档

> 日期：2026-06-24
> 状态：草稿
> 参考代码库：`D:\js动态爬虫\`（5 个开源爬虫项目）

---

## 目标

将 `hotspot_crawler.py`（单文件 827 行，仅 requests）重构为模块化架构，核心解决 JS 动态渲染页面的爬取问题，同时为后续工程化扩展（去重、多格式输出、代理池、多搜索源）预留架构空间。

---

## 设计原则

1. **分批推进** — 每批产出可独立使用，不欠技术债
2. **保持兼容** — 现有 CLI 用法全部保留，只新增不破坏
3. **参考优先** — 从 `D:\js动态爬虫` 的成熟项目直接借鉴代码，不重复造轮子
4. **智能降级** — 能快则快（requests），不行再上浏览器（Playwright）

---

## 整体架构

```
                    ┌──────────────────────┐
                    │   hotspot_crawler.py  │  ← CLI 入口 + 流程编排
                    │   (--config / --browser)
                    └──┬───┬───┬───┬───┬───┘
                       │   │   │   │   │
          ┌────────────┘   │   │   │   └────────────┐
          ▼                ▼   ▼   ▼                ▼
    ┌──────────┐    ┌────────┐    ┌──────────┐  ┌────────┐
    │ config   │    │ fetcher│    │ storage  │  │searcher│  ← 后续批次
    │ YAML+CLI │    │双引擎  │    │多格式    │  │多源    │
    │ dataclass│    │requests│    │MD/JSONL  │  │百度/知  │
    └──────────┘    │Playwright│   │CSV/SQLite│  │乎/必应  │
                    │隐身+动作│   │去重      │  │/微博   │
                    └────────┘    └──────────┘  └────────┘
                           │                        │
                           ▼                        ▼
                    ┌────────────┐          ┌────────────┐
                    │browser_fetcher│        │(各搜索源)  │
                    │Playwright   │          │独立文件    │
                    │隐身配置     │          │            │
                    │(image_crawler)│        │            │
                    └────────────┘          └────────────┘
```

---

## 批次 1：JS 渲染 + 配置系统

### 文件清单

| 文件 | 操作 | 职责 | 代码来源 |
|------|:----:|------|---------|
| `代码/config.py` | 新增 | YAML 配置加载 + CLI 合并 + dataclass 校验 | universal-crawler `config.py` |
| `代码/browser_fetcher.py` | 新增 | Playwright 渲染 + 隐身 + 动作脚本 | image_crawler L580-617 + universal-crawler `browser_fetcher.py` |
| `代码/fetcher.py` | 新增 | 双引擎获取器（requests + Playwright 智能降级） | 从现有 `ArticleCrawler` 提取 |
| `代码/hotspot_crawler.py` | 重构 | 简化为 CLI 入口 + 流程编排 | 现有代码改造 |

### `config.py` 设计

```python
@dataclass
class CrawlerConfig:
    keyword: str
    sources: list[str] | None = None       # 默认 ["baidu","zhihu","bing"]
    max_per_source: int = 15
    delay: float = 2.0
    browser_mode: str = "auto"             # "auto"|"always"|"never"
    output_formats: list[str] | None = None # 默认 ["md"]
    output_dir: str | None = None
    url_file: str | None = None

def load_config(args: argparse.Namespace) -> CrawlerConfig
    # 1. 先加载 YAML（如果有 --config）
    # 2. 再用 CLI 参数覆盖
    # 3. CLI 参数 > YAML > 默认值
```

### `browser_fetcher.py` 设计

```python
class BrowserFetcher:
    def __init__(self, headless: bool = True):
        # 参考 image_crawler L540-548：启动参数
        #   --disable-blink-features=AutomationControlled
        #   --no-sandbox, --disable-web-security
        #   --disable-features=IsolateOrigins,site-per-process
        ...

    def _create_stealth_context(self):
        # 参考 image_crawler L580-617：
        #   viewport 1920x1080, locale zh-CN, timezone Asia/Shanghai
        #   JS 注入：覆盖 webdriver/plugins/languages/chrome/permissions
        ...

    def fetch(self, url: str, actions: list | None = None) -> str:
        # 1. 创建隐身上下文
        # 2. page.goto(url, wait_until="networkidle")
        # 3. 执行动作（滚动、点击展开等）
        # 4. 返回 page.content()
        ...

    def close(self):
        ...
```

**隐身配置对照：** 和 image_crawler `crawler_engine.py` L580-617 一致，5 处覆盖点全部保留。

### `fetcher.py` 设计

```python
class Fetcher:
    def __init__(self, config: CrawlerConfig):
        self.session = requests.Session()
        self.browser_fetcher: BrowserFetcher | None = None  # 按需创建

    def fetch(self, url: str) -> FetchResult:
        """入口，根据 browser_mode 自动选择路径"""
        ...

    def _requests_fetch(self, url: str) -> FetchResult | None:
        """requests 直连 + Readability 提取（保持现有逻辑）"""
        ...

    def _browser_fetch(self, url: str) -> FetchResult:
        """Playwright 渲染 + Readability 提取"""
        ...

    def _should_use_browser(self, html: str) -> bool:
        """智能降级判断：内容 < 200 字 或含 SPA 特征（__NEXT_DATA__ 等）"""
        ...
```

### `hotspot_crawler.py` 改造

**保留不变：**
- 所有现有 CLI 参数（keyword、--max、--delay、--url-file）
- 搜索逻辑（HotSearcher）和存储逻辑（ArticleSaver）暂不移动

**新增：**
- `--browser` 参数（choices: auto/always/never，默认 auto）
- `--config` 参数（指定 YAML 配置文件）
- `run_pipeline()` 中集成 Fetcher 替代原来的 ArticleCrawler

**删除：**
- 不删除任何现有功能，新增参数互不影响

---

## 批次 2：工程化（多格式输出 + 去重 + 编排器）

### 文件清单

| 文件 | 操作 | 职责 | 参考来源 |
|------|:----:|------|---------|
| `代码/storage.py` | 新增 | 多格式输出（MD / JSONL / CSV）+ 统一接口 | universal-crawler `storage.py` |
| `代码/dedupe.py` | 新增 | SHA256 内容去重 + SQLite 持久化 | universal-crawler `dedupe.py` |
| `代码/engine.py` | 新增 | 核心编排器（搜索→爬取→存储全流程控制） | 从 `run_pipeline` 提取 |
| `代码/config.py` | 修改 | 扩充 `CrawlerConfig` 支持新增配置项 | - |

### 设计原则

1. **向后兼容** — 批次 1 的所有功能不变，新增模块可选集成
2. **逐步迁移** — `hotspot_crawler.py` 保持入口角色，`engine.py` 逐步接管调度逻辑
3. **去重独立** — dedupe 不依赖其他模块，可单独使用

### `storage.py` 设计

```python
@dataclass
class StorageResult:
    path: str
    format: str
    size: int

class ArticleSaverV2:
    """多格式文章保存器，替代原有的 ArticleSaver"""

    def __init__(self, keyword: str, base_dir: str, formats: list[str]):
        # formats: ["md", "jsonl", "csv"]

    def save(self, result: FetchResult, index: int) -> list[StorageResult]:
        # 按 formats 列表分别保存
        # 始终输出 _summary.md

    def _save_md(self, result, index) -> str
    def _save_jsonl(self, result, index) -> str
    def _save_csv(self, result, index) -> str

    def save_summary(self, results: list[FetchResult]) -> str
```

JSONL 格式（每行一个 JSON，适合数据分析）：
```jsonl
{"title": "...", "url": "...", "source": "必应搜索", "content": "..."}
```

CSV 格式（表格形式）：
```csv
title,url,source,content
...,...,...,...
```

### `dedupe.py` 设计

```python
class Deduplicator:
    """内容去重器，SHA256 哈希 + SQLite 持久化"""

    def __init__(self, db_path: str = None):
        # SQLite 数据库，存储已爬内容的 SHA256 哈希

    def is_duplicate(self, title: str, content: str) -> bool
        # 计算 SHA256( title + content[:1000] )，查库

    def mark_seen(self, title: str, content: str)
        # 记录哈希到 SQLite

    def close(self)
```

去重策略：标题 + 内容前 1000 字的 SHA256，忽略格式差异。
跨运行持久化：SQLite 文件保存在 `output_dir/.crawler_cache/dedup.db`。

### `engine.py` 设计

```python
class CrawlerEngine:
    """核心编排器，管理搜索→爬取→去重→存储的全流程"""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.fetcher = Fetcher(config)
        self.dedup = Deduplicator()
        self.saver = ArticleSaverV2(...)

    def run(self) -> CrawlerReport
        # 1. 搜索
        # 2. 遍历结果
        #   2a. 去重检查 → 已存在则跳过
        #   2b. 爬取正文（Fetcher.fetch）
        #   2c. 存储（Saver.save）
        # 3. 生成汇总报告
        # 4. 返回 CrawlerReport

@dataclass
class CrawlerReport:
    total: int
    success: int
    failed: int
    deduped: int
    elapsed: float
    output_dir: str
```

### `config.py` 扩展

```python
@dataclass
class CrawlerConfig:
    # ... 原有字段 ...
    output_formats: list[str] | None = None  # ["md", "jsonl", "csv"]
    output_dir: str | None = None
    dedup_enabled: bool = True
```

### `hotspot_crawler.py` 集成

最终入口调 `CrawlerEngine(config).run()`：
```
run_pipeline():
    config = CrawlerConfig(...)
    engine = CrawlerEngine(config)
    report = engine.run()
    print_report(report)
```

同时保留旧的直接路径（HotSearcher + ArticleCrawler + ArticleSaver）作为降级。

## 批次 3：搜索源扩展（后续设计）

概要：searcher.py 模块化 + weibo 热搜源

---

## 设计约束

- Python 3.10+ 兼容
- Playwright 为可选依赖（try/import 包裹）
- 不引入新的大框架（Scrapy 等）
- 模块间通过 dataclass 传参，不共享全局状态

---

## 参考来源

| 参考文件 | 用途 | 复用方式 |
|---------|------|---------|
| `D:\js动态爬虫\image_crawler\...\crawler_engine.py` L540-617 | Playwright 隐身配置 | 直接复制启动参数 + JS 注入 |
| `D:\js动态爬虫\universal-crawler\...\browser_fetcher.py` L51-64 | 动作脚本（click/scroll/wait） | 适配后引用 |
| `D:\js动态爬虫\universal-crawler\...\config.py` | 配置加载模式 | 参考设计，不直接复制 |
