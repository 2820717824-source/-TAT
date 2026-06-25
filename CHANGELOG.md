# 爬虫升级改动日志

> 项目：`hotspot_crawler.py` 架构级重写
> 方案：混合架构（方案C）— 分批推进
> 启动日期：2026-06-24

---

## 批次规划

| 批次 | 涉及文件 | 目标 | 状态 |
|:----:|---------|------|:----:|
| 第 1 批 | `config.py` + `browser_fetcher.py` + `fetcher.py` + 改 `hotspot_crawler.py` | JS 渲染搞定，当天能用 | ✅ |
| 第 2 批 | `storage.py` + `dedupe.py` + `engine.py` | 多格式输出 + 去重，数据可积累 | ✅ |
| 第 3 批 | `sources/` 包 + `searcher.py` + 微博热搜源 | 搜索源模块化 + 注册机制 | ✅ |
| 未来 | `cleaner.py`、`proxy_manager.py`、`run_state.py` | 按需加入 | ⏳ |

---

## 改动记录

### 2026-06-24

#### 批次 1 — JS 渲染 + 配置系统

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `代码/config.py` | 新增 | YAML 配置加载 + dataclass 校验 | ✅ |
| `代码/browser_fetcher.py` | 新增 | Playwright 渲染器 + 隐身配置 + 动作脚本 | ✅ |
| `代码/fetcher.py` | 新增 | requests/Playwright 双引擎获取器 | ✅ |
| `代码/hotspot_crawler.py` | 修改 | 加 `--browser`/`--config` 参数 + 智能降级逻辑 | ✅ |
| `本文档` | 新建 | 改动日志 |

#### 批次 3 — 搜索源模块化 + 微博热搜

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `代码/sources/__init__.py` | 新增 | 搜索源基类 `SearchSource` + 装饰器注册器 `register_source` |
| `代码/sources/baidu.py` | 新增 | 百度热搜源（从原 `HotSearcher.search_baidu` 提取） |
| `代码/sources/zhihu.py` | 新增 | 知乎热榜源（从原 `HotSearcher.search_zhihu` 提取） |
| `代码/sources/bing.py` | 新增 | 必应搜索源（从原 `HotSearcher.search_bing` 提取） |
| `代码/sources/weibo.py` | 新增 | **微博热搜源**，通过 `https://weibo.com/ajax/side/hotSearch` 获取 |
| `代码/searcher.py` | 新增 | `Searcher` 编排器，替代原 `HotSearcher`，自动遍历已注册源 |
| `代码/hotspot_crawler.py` | 修改 | 移除 `HotSearcher` 类，引用新 `Searcher`；保留旧 `ArticleCrawler`/`ArticleSaver` 降级路径 |
| `代码/config.py` | 修改 | 默认 sources 增加 "weibo" |
| `CHANGELOG.md` | 修改 | 新增批次 3 记录 |

新增源只需一步：在 `sources/` 下新建文件，类加 `@register_source` 装饰器即可自动注册（无需改 `__init__.py`，使用 importlib 自动发现）。

**参考来源（D:\js动态爬虫）：**
- `universal-crawler` 的工厂模式 + 配置校验 — 实现 `validate_sources()` 和 `create_sources()` 工厂
- `universal-crawler` 的 Auth 配置 — Weibo 源支持通过 YAML `source_configs` 传入 Cookie
- `image_crawler` 的策略链模式 — `Searcher.search_all()` 的源遍历策略

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `代码/config.py` | 修改 | 扩充 `output_dir`、`dedup_enabled` 字段 | ✅ |
| `代码/dedupe.py` | 新增 | SHA256 内容去重 + SQLite 持久化 | ✅ |
| `代码/storage.py` | 新增 | 多格式输出（MD/JSONL/CSV） | ✅ |
| `代码/engine.py` | 新增 | CrawlerEngine 全流程编排器 | ✅ |
| `代码/hotspot_crawler.py` | 修改 | 集成 Engine + `--no-dedup`/`--output-format` 参数 | ✅ |

