# 爬虫热点项目

行业热点爬取工具，输入行业关键词，自动搜索多源热点、爬取全文、转 Markdown 存储。

## 项目结构

```
├── hotspot_crawler.py    ← CLI 入口 + 降级路径
├── searcher.py           ← 搜索编排器（策略链模式）
├── sources/              ← 搜索源包
│   ├── __init__.py       ← SearchSource 基类 + @register_source 注册器 + 工具函数
│   ├── baidu.py          ← 百度热搜
│   ├── zhihu.py          ← 知乎热榜（需 Cookie，支持自动加载缓存）
│   ├── bing.py           ← 必应搜索
│   └── weibo.py          ← 微博热搜
├── config.py             ← CrawlerConfig + YAML/CLI 合并 + 源名校验
├── fetcher.py            ← 双引擎获取器（requests + Playwright 智能降级）+ 内容质量检查
├── browser_fetcher.py    ← Playwright 渲染 + 隐身配置
├── dedupe.py             ← SHA256 去重 + SQLite
├── storage.py            ← 多格式输出（MD/JSONL/CSV）
├── engine.py             ← CrawlerEngine 编排器（集成日志 + 失败恢复）
├── run_state.py          ← TaskLogger（三流JSONL日志）+ ResumeState（SHA256失败恢复）
└── cookie_manager.py     ← Cookie 持久化管理（保存/加载/验证）
```

## 搜索源

所有源均继承 `SearchSource` 基类，通过 `@register_source` 装饰器自动注册。

| 源 | name | 是否需要 Cookie |
|----|------|----------------|
| 百度热搜 | baidu | 否 |
| 知乎热榜 | zhihu | 是（`--login zhihu` 扫码登录 或 source_configs.zhihu.cookie） |
| 必应搜索 | bing | 否 |
| 微博热搜 | weibo | 否（可选填提高成功率） |

新增源只需：在 `sources/` 下新建文件 → 类加 `@register_source` → 自动注册（importlib 扫描）。

## 配置

YAML 配置文件 + CLI 参数合并，CLI 参数优先。

```yaml
sources: ["baidu", "zhihu", "bing", "weibo"]
source_configs:
  zhihu:
    cookie: "你的知乎登录 Cookie"
  weibo:
    cookie: "你的微博 Cookie"
```

生成默认配置：`save_default_config()` 或复制 `config.yaml`。

## 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--browser` | auto | auto/always/never |
| `--delay` | 2.0 | 请求间隔（随机化 delay*0.5~1.5） |
| `--no-dedup` | false | 禁用去重 |
| `--resume` | auto | 断点续爬（检测到失败记录时自动启用） |
| `--no-resume` | — | 禁用断点续爬 |
| `--retry-failed` | true | 续爬时重试上次失败的 URL |
| `--no-retry-failed` | — | 不重试上次失败的 |
| `--login` | — | 登录平台并缓存 Cookie（当前支持: zhihu） |
| `--output-format` | md | md/jsonl/csv |

## 工程细节

- **重试策略**：`fetch_url()` 支持指数退避重试 (`backoff * 2^attempt + random()`)，只在 429/5xx 重试，401/403/404 不重试
- **去重 key**：`SHA256(title + url)`，SQLite 持久化到 `.crawler_cache/dedup.db`
- **智能降级**：requests 优先，内容<200字或检测到 SPA 特征时自动 fallback 到 Playwright
- **质量检查**：`fetcher.py` 的 `_quality_check()` 拒绝空标题（[no-title]/untitled）和有效字数<100的内容
- **失败恢复**：`run_state.py` ResumeState 追踪已完成/失败的 URL，支持断点续爬（`--resume`）
- **结构化日志**：`run_state.py` TaskLogger 三流 JSONL（request_log/error_log/summary_log）
- **知乎登录**：`python hotspot_crawler.py --login zhihu` 打开浏览器扫码，自动缓存 Cookie
- **GitHub**：`https://github.com/2820717824-source/-TAT`
- **默认输出目录**：`../文章`

## 参考项目

`D:\js动态爬虫\` 中的 5 个开源爬虫项目：
- `universal-crawler` — 工厂模式、指数退避重试、内容清洗、运行状态追踪
- `image_crawler` — Playwright 隐身配置、策略链模式
- `javaCrawling` — 动态代理池（后续批次参考）
- `python_spider` — Ajax 接口逆向（后续批次参考）
