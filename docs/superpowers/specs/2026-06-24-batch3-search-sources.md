# 批次 3：搜索源模块化 + 微博热搜

> 交付日期：2026-06-24
> 状态：已完成 ✅

## 目标

1. 把 `HotSearcher` 从 `hotspot_crawler.py` 拆到独立模块
2. 新增微博热搜源
3. 做成可扩展的源注册机制
4. 参考 5 个项目改进工程细节

## 产出文件

| 文件 | 说明 |
|------|------|
| `代码/sources/__init__.py` | SearchSource 基类 + @register_source 注册器 + importlib 自动发现 + fetch_url(带重试) + clean_text |
| `代码/sources/baidu.py` | 百度热搜源 |
| `代码/sources/zhihu.py` | 知乎热榜源（需 Cookie 登录） |
| `代码/sources/bing.py` | 必应搜索源 |
| `代码/sources/weibo.py` | 微博热搜源（通过 weibo.com/ajax/side/hotSearch） |
| `代码/searcher.py` | Searcher 编排器（策略链 + 随机间隔 delay） |
| `代码/hotspot_crawler.py` | 移除 HotSearcher，引用新 Searcher |
| `代码/config.py` | 加 source_configs 字段、源名校验、默认输出路径 |
| `CLAUDE.md` | 项目文档（新建） |

## 从参考项目借鉴的模式

| 模式 | 来源 | 位置 |
|------|------|------|
| 指数退避重试 | universal-crawler fetcher.py:47-73 | sources/__init__.py fetch_url() |
| 随机间隔 delay | universal-crawler engine.py:235-240 | searcher.py search_all() |
| 文本清洗 | universal-crawler cleaner.py:32-41 | sources/__init__.py clean_text() |
| 策略链模式 | image_crawler crawler_engine.py:202-228 | searcher.py search_all() |
| 工厂+注册模式 | universal-crawler storage.py build_storage() | sources/__init__.py create_sources() |
| auth cookie 配置 | universal-crawler config.py RequestConfig | config.py source_configs |

## 测试结果

- 16/16 项全部通过
- 百度热搜 / 必应搜索 / 微博热搜 均正常返回
- 知乎返回空结果 + Cookie 配置提示（需登录态）
- 全管道测试：3 条 URL 成功抓取 2 篇
- fetch_url 重试：401 不重试，网络错误指数退避
