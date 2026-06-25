# 批 4：弹性与可观测性

> 日期：2026-06-25 | 状态：草稿

## 目标

为爬虫工具增加失败恢复和结构化日志能力，让爬虫在中断后能续爬、跑完后可追溯。

## 产出物

新增 1 个文件 `run_state.py`，修改 `engine.py`、`hotspot_crawler.py`、`config.py`。

## 模块设计

### TaskLogger — 结构化日志

三个 JSONL 流，统一存放在 `.crawler_cache/logs/`：

| 文件 | 用途 | 事件类型 |
|------|------|---------|
| `request_log.jsonl` | 每次请求完整 trace | request_start / request_done / request_skip |
| `error_log.jsonl` | 只记失败，含错误详情 | fetch_failed |
| `summary_log.jsonl` | 每次运行一条汇总 | run_complete |

每条记录带 `ts`（ISO 时间戳）和 `event` 标签。

### ResumeState — 失败恢复

存放在 `.crawler_cache/resume/`：

| 文件 | 格式 | 用途 |
|------|------|------|
| `completed.txt` | 每行一个 SHA256(url) | 已成功，下次跳过 |
| `failed.jsonl` | JSONL，{url, error, ts} | 失败，下次优先重试 |

key 生成：`SHA256(url.lower().rstrip('/'))`，标准化后再哈希。

### engine.py 集成

1. 进入 run() 时检测 resume 状态 → 取出 failed 列表优先重试
2. 遍历 hot_items：检查 resume 跳过 → dedup → log_start → fetch → log_done → 保存 → mark_completed/mark_failed
3. 结束时 log_summary

### CLI 与配置

新增参数：
- `--resume`：启用续爬（默认 auto：检测到 failed.jsonl 时自动开启）
- `--retry-failed`：重试上次失败的（默认 True）

### 边界处理

| 场景 | 处理 |
|------|------|
| 首次运行 | 行为不变，零开销 |
| 进程崩溃 mid-write | append 模式，读取时 filter 过滤不合法行 |
| completed.txt 太大 | 加载到 set，O(1) 查询 |
| 不同 keyword | 共用目录，URL 不重叠 |
| 用户想重爬全部 | 删掉 `.crawler_cache/resume/` 或 `--no-resume` |

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `run_state.py` | 新增 | TaskLogger + ResumeState |
| `engine.py` | 修改 | 集成 run_state，新增 resume/retry_failed 参数 |
| `hotspot_crawler.py` | 修改 | 新增 --resume --retry-failed 参数 |
| `config.py` | 修改 | CrawlerConfig 新增 resume/retry_failed 字段 |
