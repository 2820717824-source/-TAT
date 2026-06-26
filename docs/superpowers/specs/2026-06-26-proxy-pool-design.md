# ProxyProvider：动态代理池

> 日期：2026-06-26 | 状态：草稿
> 参考来源：javaCrawling NetPoxyService + TheSpeedX/PROXY-List

## 目标

为爬虫工具添加零成本、轻量级的动态代理能力，解决百度/微博等源因 IP 限制返回 0 条的问题。量不大，不引入付费服务。

## 产出物

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `proxy_manager.py` | 新增 | ProxyProvider 类 |
| `sources/__init__.py` | 修改 | `fetch_url()` 增加 proxy 参数 + 429/5xx 自动换代理重试 |
| `config.py` | 修改 | CrawlerConfig 增加 `proxy` 配置段 |

## ProxyProvider 设计

```python
class ProxyProvider:
    """从 GitHub 公开代理列表拉取 HTTP 代理，带本地缓存和失效剔除"""

    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        # proxies.json 路径：cache_dir / proxies.json
        # 初始状态：缓存为空，延迟加载

    def get_proxy(self) -> str | None:
        """返回一个可用代理 "ip:port"，无可用时返回 None"""

    def refresh(self) -> int:
        """从 GitHub 拉取最新代理列表
         - URL: https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt
         - 解析后做 quick_test 过滤不可用的
         - 写入本地缓存 proxies.json
         - 返回可用代理数量
        """

    def report_failure(self, proxy: str) -> None:
        """标记代理失败，连续失败 3 次后从池中移除"""

    def _quick_test(self, proxy: str) -> bool:
        """快速测试代理是否可用
         - 目标：http://httpbin.org/ip 或 http://baidu.com
         - 超时：5 秒
         - 返回 True/False
        """

    def _load_cache(self) -> None: ...
    def _save_cache(self) -> None: ...
```

### 数据结构

`.crawler_cache/proxies.json`：
```json
{
    "proxies": [
        {"addr": "1.2.3.4:8080", "fail_count": 0},
        {"addr": "5.6.7.8:3128", "fail_count": 2}
    ],
    "fetched_at": "2026-06-26T10:00:00",
    "source": "github"
}
```

## 集成方式

### sources/__init__.py 的 fetch_url()

```python
def fetch_url(url, *, proxy=None, ...):
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = session.get(url, proxies=proxies, timeout=timeout, ...)
    except (RequestException, ConnectionError) as e:
        return None, str(e)
```

### 自动重试逻辑

只有启用了代理（`proxy=True` 或在 source_configs 中指定）才会走代理重试流程：

```
fetch_url(url, proxy_pool=None):
    for attempt in range(max_retries=3):
        proxy = proxy_pool.get_proxy() if proxy_pool else None
        resp, err = _do_request(url, proxy=proxy)
        if resp: return resp, None
        if proxy: proxy_pool.report_failure(proxy)
        if is_retryable(err): continue  # 429/5xx/网络错误
        break  # 401/403/404 不重试
    return None, err
```

注意：当前直连正常工作时不会自动开代理。代理只会在 YAML 中显式启用 `proxy: true` 时生效。失败计数（fail_count）每次启动重置，不持久化。

### config.py 扩展

```python
@dataclass
class CrawlerConfig:
    # ... 现有字段 ...
    proxy: bool = False  # 是否启用代理（默认关闭，量不大用不上）
```

## 范围和限制

- **第一版只覆盖搜索源请求**（`sources/__init__.py` 的 `fetch_url()`），不覆盖文章正文下载（`fetcher.py`）。原因是 IP 限制主要体现在搜索阶段，正文下载通常是不同的目标站点，受限概率低
- 代理默认关闭（`proxy: false`），需在 YAML 中显式启用
- 不实现代理测速/延迟排序，随机轮换足够

| 场景 | 处理 |
|------|------|
| GitHub raw 拉不下来 | 保留旧缓存继续用，不阻塞爬取 |
| 无可用代理 | `get_proxy()` 返回 None，保持直连 |
| 代理全部失效 | 自动触发 refresh 重新拉取 |
| 缓存过期 > 1 小时 | `_cache_expired()` 返回 True，下次 get_proxy 时自动 refresh |
| 连续失败 3 次 | 从池中移除该代理 |
| 初始化时无缓存 | 懒加载，第一次 get_proxy 时自动 refresh |

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|:----:|------|
| `proxy_manager.py` | 新增 | ProxyProvider 完整实现，~80 行 |
| `sources/__init__.py` | 修改 | fetch_url() 加 proxy 参数，新增 _proxy_retry() 重试逻辑 |
| `config.py` | 修改 | CrawlerConfig 加 `proxy: bool = False` |
