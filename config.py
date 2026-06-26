#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# 用于 source 名称校验（延迟导入，避免循环依赖）
_HAVE_SOURCES = False
try:
    from sources import list_sources, validate_sources
    _HAVE_SOURCES = True
except ImportError:
    pass


@dataclass
class CrawlerConfig:
    """爬虫配置，由 YAML + CLI 合并而来，CLI 参数优先

    参考 universal-crawler 的配置设计：
    类型化 dataclass + _build 式过滤 + 构建时校验。
    """
    keyword: str
    sources: list[str] | None = None
    source_configs: dict[str, dict] | None = None  # per-source 配置，如 {"weibo": {"cookie": "xxx"}}
    max_per_source: int = 15
    delay: float = 2.0
    browser_mode: str = "auto"       # "auto" | "always" | "never"
    output_formats: list[str] | None = None  # 默认 ["md"]
    output_dir: str | None = None
    dedup_enabled: bool = True
    resume: bool = True
    retry_failed: bool = True
    proxy: bool = False       # 是否启用代理池（默认关闭）
    url_file: str | None = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = ["baidu", "zhihu", "bing", "weibo"]
        if self.source_configs is None:
            self.source_configs = {}
        if self.output_formats is None:
            self.output_formats = ["md"]
        if self.output_dir is None:
            # TODO: 项目完成后改为 ../文章
            self.output_dir = str(Path(__file__).resolve().parent / "测试文章")
        # 校验 source 名称（fail-fast）
        if _HAVE_SOURCES:
            validate_sources(self.sources)


def load_config(args: argparse.Namespace) -> CrawlerConfig:
    """加载配置：YAML 文件（如果有）→ CLI 覆盖 → 返回 CrawlerConfig"""
    # 1. 先尝试从 YAML 加载
    config_dict = {}
    if getattr(args, "config", None):
        config_path = Path(args.config)
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                config_dict = yaml.safe_load(f) or {}
        else:
            print(f"  [警告] 配置文件不存在: {args.config}")

    # 2. 从 YAML 提取初始值
    keyword = config_dict.get("keyword", args.keyword)
    sources = config_dict.get("sources")
    source_configs = config_dict.get("source_configs", {})
    max_per_source = config_dict.get("max_per_source", 15)
    delay = config_dict.get("delay", 2.0)
    browser_mode = config_dict.get("browser", {}).get("mode", "auto")
    output_formats = config_dict.get("output", {}).get("formats")
    output_dir = config_dict.get("output", {}).get("dir")
    dedup_enabled = config_dict.get("dedup", {}).get("enabled", True)
    resume_enabled = config_dict.get("resume", {}).get("enabled", True)
    retry_failed = config_dict.get("resume", {}).get("retry_failed", True)
    proxy_enabled = config_dict.get("proxy", {}).get("enabled", False)

    # 3. CLI 参数覆盖（显式传入的才覆盖）
    if args.keyword:
        keyword = args.keyword
    if args.max != 15:
        max_per_source = args.max
    if args.delay != 2.0:
        delay = args.delay
    if args.url_file:
        sources = None
        url_file = args.url_file
    else:
        url_file = None
    if getattr(args, "browser", None):
        browser_mode = args.browser
    if getattr(args, "no_dedup", False):
        dedup_enabled = False
    if getattr(args, "no_resume", False):
        resume_enabled = False
    cli_fmt = getattr(args, "output_format", None)
    if cli_fmt:
        output_formats = [fmt.strip() for fmt in cli_fmt.split(",")]

    return CrawlerConfig(
        keyword=keyword,
        sources=sources,
        source_configs=source_configs,
        max_per_source=max_per_source,
        delay=delay,
        browser_mode=browser_mode,
        output_formats=output_formats,
        output_dir=output_dir,
        dedup_enabled=dedup_enabled,
        resume=resume_enabled, retry_failed=retry_failed,
        proxy=proxy_enabled,
        url_file=url_file,
    )


def save_default_config(path: str = "config.yaml"):
    """生成一份默认配置文件"""
    config = {
        "keyword": "行业关键词",
        "sources": ["baidu", "zhihu", "bing", "weibo"],
        "source_configs": {
            "zhihu": {
                "cookie": "你的知乎登录 Cookie（必填，否则知乎源返回空）",
            },
            "weibo": {
                "cookie": "你的微博 Cookie（可选，提高请求成功率）",
            },
        },
        "max_per_source": 15,
        "delay": 2.0,
        "browser": {
            "mode": "auto",     # auto | always | never
        },
        "dedup": {
            "enabled": True,
        },
        "resume": {
            "enabled": True,
            "retry_failed": True,
        },
        "proxy": {
            "enabled": False,
        },
        "output": {
            "formats": ["md"],
            "dir": "../测试文章",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  默认配置文件已生成: {path}")
