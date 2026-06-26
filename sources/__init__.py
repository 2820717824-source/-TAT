#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索源框架：基类 + 注册器 + 共享工具

参考 universal-crawler 的模块自动发现和工厂模式：
- importlib 扫描 sources/ 目录自动注册，新增源无需改 __init__.py
- validate_sources() 提供配置时校验（借鉴 _build() 的 fail-fast 理念）
"""

from __future__ import annotations

import importlib
import pkgutil
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests
from proxy_manager import ProxyProvider

# 模块级代理池（由引擎在启动时设置）
_proxy_pool: ProxyProvider | None = None


def set_proxy_pool(pool: ProxyProvider | None) -> None:
    """设置模块级代理池（引擎启动时调用）"""
    global _proxy_pool
    _proxy_pool = pool


# ============================================================
# 常量
# ============================================================

REQUEST_TIMEOUT = 15

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]


# ============================================================
# 工具函数
# ============================================================

def random_ua() -> str:
    return random.choice(USER_AGENTS)


def default_headers(referer: str = "") -> dict:
    headers = {
        "User-Agent": random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def keyword_match(title: str, keyword: str) -> bool:
    return keyword.lower() in title.lower()


def fetch_url(url: str, session: requests.Session, headers: dict = None,
              timeout: int = None, retry_times: int = 0,
              retry_backoff: float = 1.0,
              retryable_status: list[int] | None = None,
              proxy_pool: ProxyProvider | None = None) -> Optional[str]:
    """通用 GET 请求，支持指数退避重试 + 代理轮换

    参考 universal-crawler fetcher.py L47-73 的重试模式：
    - retry_times=0: 不重试（兼容旧行为）
    - retry_times>0: 在 429/5xx 和网络错误时指数退避重试
    - proxy_pool 提供时，失败后自动从池中换代理重试
    """
    if retryable_status is None:
        retryable_status = [429, 500, 502, 503, 504]

    # 使用传入的 pool，没有则用模块级 pool
    pool = proxy_pool or _proxy_pool
    last_error: str | None = None
    current_proxy: str | None = None

    for attempt in range(retry_times + 1):
        # 第一次失败后尝试用代理
        if attempt > 0 and pool and pool.available():
            current_proxy = pool.get_proxy()

        proxies = {"http": current_proxy, "https": current_proxy} if current_proxy else None

        try:
            resp = session.get(
                url,
                headers=headers or default_headers(),
                timeout=timeout or REQUEST_TIMEOUT,
                proxies=proxies,
            )
            # 成功
            if resp.status_code == 200:
                if resp.encoding and resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            # 可重试的状态码
            if resp.status_code in retryable_status:
                last_error = f"HTTP {resp.status_code}"
                if current_proxy:
                    pool.report_failure(current_proxy)
            else:
                # 401/403/404 等不重试
                return None
        except requests.RequestException as e:
            last_error = str(e)
            if current_proxy:
                pool.report_failure(current_proxy)

        if attempt < retry_times:
            sleep_seconds = retry_backoff * (2 ** attempt) + random.random()
            time.sleep(sleep_seconds)

    return None


def clean_text(text: str, html_unescape: bool = True,
               normalize_space: bool = True,
               strip: bool = True,
               max_length: int = 0) -> str:
    """文本清洗工具

    参考 universal-crawler cleaner.py L32-41 的清洗模式。
    """
    import html as _html
    import re as _re
    if html_unescape:
        text = _html.unescape(text)
    if normalize_space:
        text = _re.sub(r'\s+', ' ', text)
    if strip:
        text = text.strip()
    if max_length > 0 and len(text) > max_length:
        text = text[:max_length]
    return text


# ============================================================
# 数据类
# ============================================================

@dataclass
class HotItem:
    """单个热点条目"""
    title: str
    url: str
    source: str
    hot_score: str = ""
    summary: str = ""
    cover_url: str = ""


# ============================================================
# 搜索源基类 + 注册器
# ============================================================

class SearchSource(ABC):
    """搜索源基类，所有源继承此类并实现 search()

    参考 universal-crawler 的 Storage 基类：
    统一接口，每个源独立实现，通过注册器管理。
    """
    name: str = ""
    display_name: str = ""

    def __init__(self, session: requests.Session, config: dict | None = None):
        self.session = session
        self.config = config or {}

    @abstractmethod
    def search(self, keyword: str, max_results: int = 15) -> list[HotItem]:
        ...


_sources: dict[str, type[SearchSource]] = {}


def register_source(cls):
    """装饰器：用 cls.name 注册搜索源"""
    _sources[cls.name] = cls
    return cls


def get_source(name: str) -> type[SearchSource]:
    if name not in _sources:
        raise KeyError(f"未知搜索源: {name}，可用: {list_sources()}")
    return _sources[name]


def list_sources() -> list[str]:
    return list(_sources.keys())


def validate_sources(names: list[str]) -> list[str]:
    """校验 source 名称，返回未知名称列表（借鉴 universal-crawler _build() 的 fail-fast）"""
    unknown = [n for n in names if n not in _sources]
    if unknown:
        raise ValueError(
            f"未知搜索源: {unknown}，可用: {list_sources()}"
        )
    return names


def create_sources(names: list[str],
                   session: requests.Session | None = None,
                   source_configs: dict[str, dict] | None = None) -> list[SearchSource]:
    """根据名称列表创建搜索源实例，支持 per-source 配置

    参考 universal-crawler 的 build_storage() 工厂模式：
    通过 registry 将字符串名称映射到实现类。
    """
    if session is None:
        session = requests.Session()
    if source_configs is None:
        source_configs = {}
    validate_sources(names)
    return [
        get_source(name)(session, config=source_configs.get(name, {}))
        for name in names
    ]


# ============================================================
# 自动发现并注册所有内置源
# 参考 universal-crawler 的模块化设计：
# 用 importlib 扫目录自动导入，新增源只需放文件无需改 __init__.py
# ============================================================

def _discover_sources():
    """扫描 sources/ 下所有 .py 文件并导入（触发 @register_source）"""
    for imp, name, ispkg in pkgutil.iter_modules(__path__):
        if name != "__init__":
            importlib.import_module(f".{name}", __package__)


_discover_sources()
