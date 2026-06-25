# 知乎登录 Cookie 管理

> 日期：2026-06-25 | 状态：草稿

## 目标

解决知乎热榜源需要登录 Cookie 才能获取数据的问题，提供一键扫码登录 + Cookie 自动缓存功能。

## 产出物

| 文件 | 操作 | 说明 |
|------|------|------|
| `cookie_manager.py` | 新增 | Cookie 持久化存取 + 有效性检测 |
| `sources/zhihu.py` | 修改 | 启动时从 cookie_manager 加载 Cookie |
| `hotspot_crawler.py` | 修改 | 新增 `--login zhihu` CLI 参数 |

## 模块设计

### cookie_manager.py

```python
class CookieManager:
    def __init__(self, cache_dir: Path = Path(".crawler_cache")):
        ...

    def save(self, source: str, cookies: dict | str) -> None: ...
    def load(self, source: str) -> dict | None: ...
    def cookie_valid(self, source: str) -> bool: ...
    def get_cookie_str(self, source: str) -> str | None: ...
```

数据存在 `.crawler_cache/cookies/{source}.json`，格式：
```json
{
    "cookie": "xxx=yyy; aaa=bbb",
    "saved_at": "2026-06-25T10:00:00",
    "domain": ".zhihu.com"
}
```

### 扫码登录流程

1. `hotspot_crawler.py --login zhihu`
2. 用已有的 BrowserFetcher（Playwright 隐身配置）打开 `https://www.zhihu.com/signin`
3. 等待用户扫码（检测 `div.QRLogin` 或类似二维码元素）
4. 轮询检测登录状态（检查 Cookie 变化或页面跳转，最长 3 分钟）
5. 提取完整 Cookie → 调用 `CookieManager.save("zhihu", cookies)`
6. 关闭浏览器，输出结果

### 改造 sources/zhihu.py

在 `ZhihuSource.__init__()` 或 `search()` 中：
```python
from cookie_manager import CookieManager

cm = CookieManager()
cookie = cm.get_cookie_str("zhihu")
if cookie:
    self.headers["Cookie"] = cookie
```

### CLI 改动

新增：
```
python hotspot_crawler.py --login zhihu     # 扫码登录知乎
```

## 边界处理

| 场景 | 处理 |
|------|------|
| Playwright 未安装 | 提示 `pip install playwright && playwright install chromium` |
| 扫码超时（3 分钟） | 自动退出，不阻塞终端 |
| Cookie 过期 | sources/zhihu.py 检测到 401 → 提示重新 `--login zhihu` |
| 已有 Cookie 再次登录 | 覆盖旧 Cookie |
