#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行业热点爬取工具 v1.0
输入行业关键词，自动搜索热点新闻、爬取全文、转成 Markdown 存到本地。

用法:
    python hotspot_crawler.py <行业关键词>
    python hotspot_crawler.py <行业关键词> --max 10 --delay 3
    python hotspot_crawler.py <行业关键词> --url-file urls.txt
"""

import argparse
import json
import os
import random
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

import html2text
import requests
import yaml
from bs4 import BeautifulSoup
from readability import Document
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

# ============================================================
# Console
# ============================================================

console = Console()

# ============================================================
# User-Agent 轮换池
# ============================================================

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
# 来源 URL 配置
# ============================================================

BAIDU_API_URL = "https://top.baidu.com/api/board?tab=realtime"
ZHIHU_API_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50"
BING_SEARCH_URL = "https://cn.bing.com/search?q={keyword}&setlang=zh-Hans"
REQUEST_TIMEOUT = 15


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


def safe_filename(title: str, max_len: int = 40) -> str:
    """移除文件名中的非法字符，截断到 max_len"""
    safe = re.sub(r'[\\/:*?"<>|]', "", title)
    safe = safe.strip().replace(" ", "_")
    if len(safe) > max_len:
        safe = safe[:max_len]
    return safe


def keyword_match(title: str, keyword: str) -> bool:
    """检查标题是否包含行业关键词（不区分大小写）"""
    return keyword.lower() in title.lower()


# ============================================================
# 数据类
# ============================================================

@dataclass
class HotItem:
    """单个热点条目"""
    title: str
    url: str
    source: str          # 来源名称：百度热搜/知乎热榜/必应新闻
    hot_score: str = ""  # 热度值
    summary: str = ""    # 摘要
    cover_url: str = ""  # 封面图


@dataclass
class ArticleResult:
    """爬取结果"""
    title: str
    url: str
    source: str
    content_html: str = ""
    content_markdown: str = ""
    author: str = ""
    publish_time: str = ""
    summary: str = ""
    status: str = "pending"  # pending | success | failed
    error_msg: str = ""
    crawl_time: float = 0.0


# ============================================================
# 搜索模块
# ============================================================

class HotSearcher:
    """多源热点搜索"""

    def __init__(self, keyword: str, max_per_source: int = 15, delay: float = 2.0):
        self.keyword = keyword
        self.max_per_source = max_per_source
        self.delay = delay
        self.session = requests.Session()

    def _fetch(self, url: str, headers: dict = None, timeout: int = None) -> Optional[str]:
        """通用 GET 请求"""
        try:
            resp = self.session.get(
                url,
                headers=headers or default_headers(),
                timeout=timeout or REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            # 自动检测编码
            if resp.encoding and resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as e:
            return None

    def search_baidu(self) -> list[HotItem]:
        """百度热搜榜爬取 + 关键词过滤"""
        items = []
        try:
            html = self._fetch(BAIDU_API_URL, headers={
                **default_headers("https://top.baidu.com/"),
                "Accept": "application/json, text/plain, */*",
            })
            if not html:
                console.print("  [dim]├[/dim]  [yellow][百度热搜][/yellow] 请求失败，尝试解析页面...")
                return self._search_baidu_fallback()

            data = json.loads(html)
            cards = data.get("data", {}).get("cards", [])
            for card in cards:
                content_list = card.get("content", [])
                for content in content_list:
                    title = content.get("word", content.get("query", "")).strip()
                    if not title:
                        continue
                    hot_score = str(content.get("hotScore", content.get("heatScore", "")))
                    url = content.get("url", content.get("appUrl", f"https://www.baidu.com/s?wd={quote(title)}"))
                    if self.keyword and not keyword_match(title, self.keyword):
                        continue
                    items.append(HotItem(
                        title=title,
                        url=url,
                        source="百度热搜",
                        hot_score=hot_score,
                        summary=content.get("desc", ""),
                    ))

        except Exception as e:
            console.print(f"  [dim]├[/dim]  [yellow][百度热搜][/yellow] 解析异常: {e}，尝试页面解析...")
            return self._search_baidu_fallback()

        # 按热度排序（降序）
        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:self.max_per_source]

    def _search_baidu_fallback(self) -> list[HotItem]:
        """备用方案：直接从热搜页面解析"""
        items = []
        try:
            html = self._fetch("https://top.baidu.com/board?tab=realtime")
            if not html:
                return items
            # 尝试从 script 标签中的 JSON 数据提取
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script"):
                text = script.string or ""
                if "hotSearch" not in text and "board" not in text:
                    continue
                # 尝试找完整 JSON 对象
                for match in re.finditer(r'window\.__NUXT__\s*=\s*(\{.*?\})\s*;?\s*\n', text, re.DOTALL):
                    try:
                        data = json.loads(match.group(1))
                        cards = data.get("data", {}).get("cards", [])
                        for card in cards:
                            for content in card.get("content", []):
                                word = content.get("word", content.get("query", "")).strip()
                                if not word:
                                    continue
                                if self.keyword and not keyword_match(word, self.keyword):
                                    continue
                                items.append(HotItem(
                                    title=word,
                                    url=content.get("url", f"https://www.baidu.com/s?wd={quote(word)}"),
                                    source="百度热搜",
                                    hot_score=str(content.get("hotScore", content.get("heatScore", ""))),
                                ))
                    except (json.JSONDecodeError, KeyError):
                        pass
                if items:
                    break
        except Exception:
            console.print("  [dim]├[/dim]  [yellow][百度热搜][/yellow] 备用解析异常，跳过")

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:self.max_per_source]

    def search_zhihu(self) -> list[HotItem]:
        """知乎热榜爬取 + 关键词过滤（API 需要 Cookie 时自动降级）"""
        items = []
        try:
            headers = {
                **default_headers("https://www.zhihu.com/"),
                "Accept": "application/json, text/plain, */*",
            }
            html = self._fetch(ZHIHU_API_URL, headers=headers)
            if not html:
                console.print("  [dim]├[/dim]  [yellow][知乎热榜][/yellow] API 请求失败，尝试页面解析...")
                return self._search_zhihu_fallback()

            data = json.loads(html)
            # API 返回 401 时 data 里是 error
            if "error" in data:
                console.print("  [dim]├[/dim]  [yellow][知乎热榜][/yellow] 需要登录验证，尝试页面解析...")
                return self._search_zhihu_fallback()

            detail_list = data.get("data", [])
            for item in detail_list:
                target = item.get("target", {})
                title = target.get("title", "").strip()
                if not title:
                    title = target.get("question", {}).get("title", "")
                if not title:
                    continue
                url_id = target.get("id", "")
                url = f"https://www.zhihu.com/question/{url_id}" if url_id else ""
                if not url:
                    url = target.get("url", "")
                detail = item.get("detail_text", "")
                if self.keyword and not keyword_match(title, self.keyword):
                    continue
                items.append(HotItem(
                    title=title,
                    url=url,
                    source="知乎热榜",
                    hot_score=detail,
                ))
        except json.JSONDecodeError:
            return self._search_zhihu_fallback()
        except Exception as e:
            console.print(f"  [dim]├[/dim]  [yellow][知乎热榜][/yellow] 解析异常: {e}")

        items.sort(key=lambda x: int(x.hot_score) if x.hot_score.isdigit() else 0, reverse=True)
        return items[:self.max_per_source]

    def _search_zhihu_fallback(self) -> list[HotItem]:
        """备用方案：从知乎热门内容页提取"""
        items = []
        try:
            html = self._fetch("https://www.zhihu.com/explore", headers=default_headers("https://www.zhihu.com/"))
            if not html:
                return items
            # 尝试从初始数据中找热门话题
            match = re.search(r'<script id="js-initialData"[^>]*>({.*?})</script>', html, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                entities = data.get("initialState", {}).get("entities", {})
                # 查找热门问题
                questions = entities.get("questions", {})
                for qid, qdata in questions.items():
                    title = qdata.get("title", "").strip()
                    if not title:
                        continue
                    if self.keyword and not keyword_match(title, self.keyword):
                        continue
                    items.append(HotItem(
                        title=title,
                        url=f"https://www.zhihu.com/question/{qid}",
                        source="知乎热榜",
                    ))
        except Exception:
            console.print("  [dim]├[/dim]  [yellow][知乎热榜][/yellow] 备用解析异常，跳过")
        return items[:self.max_per_source]

    def search_bing(self) -> list[HotItem]:
        """必应搜索 + 结果提取（使用 Web 搜索，因新闻搜索需验证）"""
        items = []
        try:
            url = BING_SEARCH_URL.format(keyword=quote(self.keyword))
            html = self._fetch(url, headers={
                **default_headers("https://cn.bing.com/"),
                "User-Agent": random_ua(),
            })
            if not html:
                console.print("  [dim]├[/dim]  [yellow][必应搜索][/yellow] 请求失败")
                return self._search_bing_fallback()

            soup = BeautifulSoup(html, "html.parser")
            # Bing Web 搜索结果
            results = soup.select("#b_results .b_algo") or soup.select(".b_caption")
            if not results:
                return self._search_bing_fallback()

            for result in results:
                h2 = result.find("h2")
                if not h2:
                    continue
                a = h2.find("a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a.get("href", "")
                if not title or not href:
                    continue
                # 摘要
                snippet_el = result.select_one(".b_caption p, .b_lineclamp2")
                summary = snippet_el.get_text(strip=True) if snippet_el else ""

                items.append(HotItem(
                    title=title,
                    url=href,
                    source="必应搜索",
                    summary=summary,
                ))
        except Exception as e:
            console.print(f"  [dim]├[/dim]  [yellow][必应搜索][/yellow] 解析异常: {e}")

        return items[:self.max_per_source]

    def _search_bing_fallback(self) -> list[HotItem]:
        """备用方案：通过百度搜索获取结果"""
        # 当必应无法访问时，使用百度搜索作为补充
        items = []
        try:
            search_url = f"https://www.baidu.com/s?wd={quote(self.keyword)}&tn=news"
            html = self._fetch(search_url, headers=default_headers("https://www.baidu.com/"))
            if not html:
                return items
            soup = BeautifulSoup(html, "html.parser")
            for el in soup.select(".result, .c-container"):
                title_el = el.select_one("h3 a") or el.select_one(".t a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if not title or not href:
                    continue
                items.append(HotItem(
                    title=title,
                    url=href,
                    source="百度搜索",
                    summary="",
                ))
        except Exception:
            console.print("  [dim]├[/dim]  [yellow][必应降级-百度搜索][/yellow] 备用解析异常，跳过")
        return items[:self.max_per_source]

    def search_all(self) -> list[HotItem]:
        """执行所有来源搜索，返回去重合并后的结果"""
        console.print(f"\n  [bold cyan]┌─ 正在搜索: 「{self.keyword}」[/bold cyan]")
        console.print(f"  [bold cyan]│[/bold cyan]")

        # 并行搜索三个来源
        results = {}
        sources = [
            ("百度热搜", self.search_baidu),
            ("知乎热榜", self.search_zhihu),
            ("必应搜索", self.search_bing),
        ]

        for name, search_fn in sources:
            try:
                items = search_fn()
                results[name] = items
                emoji = "✓" if items else "–"
                console.print(
                    f"  [dim]├[/dim]  [{name}] 发现 [bold]{len(items)}[/bold] 条相关热点    [green]{emoji}[/green]"
                )
            except Exception as e:
                results[name] = []
                console.print(
                    f"  [dim]├[/dim]  [{name}] 出错: {e}    [red]✗[/red]"
                )
            time.sleep(self.delay)

        # 去重合并（按标题去重）
        seen_titles = set()
        merged: list[HotItem] = []
        for name in sources:
            for item in results.get(name[0], []):
                if item.title not in seen_titles:
                    seen_titles.add(item.title)
                    merged.append(item)

        console.print(f"  [dim]├[/dim]")
        console.print(f"  [bold cyan]└[/bold cyan] 去重合并后: 共 [bold]{len(merged)}[/bold] 篇待爬取")
        return merged


# ============================================================
# 正文爬取模块
# ============================================================

class ArticleCrawler:
    """文章正文爬取 + Readability 提取 + html2text 转换"""

    def __init__(self, delay: float = 2.0):
        self.delay = delay
        self.session = requests.Session()
        self.converter = html2text.HTML2Text()
        self.converter.body_width = 0  # 不自动换行
        self.converter.skip_internal_links = False
        self.converter.protect_links = True
        self.converter.unicode_snob = True
        self.converter.ignore_links = False
        self.converter.ignore_images = False
        self.converter.ignore_emphasis = False

    def crawl(self, item: HotItem) -> ArticleResult:
        """爬取单篇文章：获取 HTML → Readability 提取 → html2text 转换"""
        result = ArticleResult(
            title=item.title,
            url=item.url,
            source=item.source,
            summary=item.summary,
        )

        try:
            start = time.time()
            headers = default_headers(urlparse(item.url).netloc)
            resp = self.session.get(item.url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()

            # 编码处理
            if resp.encoding and resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"

            html = resp.text
            if not html or len(html.strip()) < 200:
                result.status = "failed"
                result.error_msg = "内容为空或过短"
                result.crawl_time = time.time() - start
                return result

            result.content_html = html
            result.crawl_time = time.time() - start

            # Readability 正文提取
            doc = Document(html, url=item.url)
            doc.summary()  # 解析正文，填充 .content
            content_html = doc.content() or ""
            title = doc.title() or item.title

            result.title = title
            result.content_html = content_html
            result.author = doc.author() or ""

            if not content_html or len(content_html.strip()) < 50:
                # 降级方案：BeautifulSoup 取文本最多的区域
                result.content_html = self._fallback_extract(html)
                if not result.content_html or len(result.content_html.strip()) < 50:
                    result.status = "failed"
                    result.error_msg = "正文提取失败"
                    return result

            # HTML → Markdown
            result.content_markdown = self.converter.handle(result.content_html)
            result.status = "success"

        except requests.Timeout:
            result.status = "failed"
            result.error_msg = "网络超时"
        except requests.ConnectionError:
            result.status = "failed"
            result.error_msg = "连接被拒"
        except requests.HTTPError as e:
            code = e.response.status_code if e.response else 0
            if code in (403, 429):
                result.status = "failed"
                result.error_msg = f"被拦截 (HTTP {code})"
            elif code == 404:
                result.status = "failed"
                result.error_msg = "页面不存在 (404)"
            else:
                result.status = "failed"
                result.error_msg = f"HTTP {code}"
        except Exception as e:
            result.status = "failed"
            result.error_msg = str(e)[:60]

        return result

    def _fallback_extract(self, html: str) -> str:
        """降级方案：用 BeautifulSoup 提取文本最多的区域"""
        soup = BeautifulSoup(html, "html.parser")
        # 移除无用标签
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        # 找文本最多的 div/article/section
        candidates = soup.find_all(["div", "article", "section", "main"])
        best = None
        best_len = 0
        for c in candidates:
            text_len = len(c.get_text(strip=True))
            if text_len > best_len:
                best_len = text_len
                best = c

        if best and best_len > 100:
            return str(best)
        # 最终降级：返回 body
        body = soup.find("body")
        return str(body) if body else ""


# ============================================================
# 文件存储模块
# ============================================================

class ArticleSaver:
    """将文章保存为 Markdown 文件"""

    def __init__(self, keyword: str, base_dir: str = None):
        self.keyword = keyword
        self.base_dir = base_dir or os.getcwd()
        self.date_str = datetime.now().strftime("%Y-%m-%d")
        self.output_dir = Path(self.base_dir) / keyword / self.date_str

    def save(self, result: ArticleResult, index: int) -> str:
        """保存单篇文章，返回文件路径"""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 文件名（取 URL 末尾一段做后缀防同名覆盖）
        title_slug = safe_filename(result.title)
        url_slug = safe_filename(result.url[-16:-1] if len(result.url) > 16 else result.url, max_len=12)
        suffix = f"_{url_slug}" if url_slug else ""
        fname = f"{index:03d}_{title_slug}{suffix}.md"
        fpath = self.output_dir / fname

        # YAML frontmatter
        front = {
            "title": result.title,
            "url": result.url,
            "source": result.source,
            "date": self.date_str,
            "keyword": self.keyword,
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": result.status,
        }
        if result.author:
            front["author"] = result.author
        if result.publish_time:
            front["publish_time"] = result.publish_time
        if result.summary:
            front["summary"] = result.summary
        if result.error_msg:
            front["error"] = result.error_msg

        lines = []
        lines.append("---")
        lines.append(yaml.dump(front, allow_unicode=True, default_flow_style=False, sort_keys=False).strip())
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
            lines.append(f"\n> ⚠️ 爬取失败：{result.error_msg}\n")

        content = "\n".join(lines)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(content)

        return str(fpath)

    def save_summary(self, results: list[ArticleResult]):
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


# ============================================================
# 主流程
# ============================================================

def print_banner():
    """打印启动横幅"""
    banner = """
  [bold cyan]╔══════════════════════════════════════════════════════════╗
  ║   行业热点爬取工具 v1.0                                  ║
  ╚══════════════════════════════════════════════════════════╝[/bold cyan]
"""
    console.print(banner)


def print_report(results: list[ArticleResult], keyword: str, elapsed: float, output_dir: str):
    """打印爬取统计报告"""
    success = sum(1 for r in results if r.status == "success")
    failed = sum(1 for r in results if r.status == "failed")

    report = (
        "\n  ╔══ 爬取完毕! ══╗\n"
        f"  ║  成功: {success} 篇  |  失败: {failed} 篇  |  总计: {len(results)} 篇\n"
        f"  ║  保存路径: {output_dir}\n"
        f"  ║  用时: {elapsed:.1f} 秒\n"
        "  ╚══ 爬取完毕 ══╝"
    )
    console.print(f"[bold green]{report}[/bold green]")

    if failed > 0:
        console.print(f"\n  [yellow]失败详情:[/yellow]")
        for r in results:
            if r.status == "failed":
                console.print(f"    [dim]✗[/dim] {r.title[:50]} — [red]{r.error_msg}[/red]")


def run_pipeline(keyword: str, max_per_source: int = 15, delay: float = 2.0, url_file: str = None):
    """执行完整爬取流水线"""
    start_time = time.time()
    print_banner()

    # 参数校验
    if delay < 0.5:
        console.print("  [yellow]--delay 过小可能导致被拦截，推荐 >= 1.0[/yellow]")
    if max_per_source < 1:
        console.print("  [red]--max 至少为 1[/red]")
        return

    # Step 1: 搜索热点
    hot_items: list[HotItem] = []
    if url_file:
        # 从文件读取 URL 列表
        url_path = Path(url_file)
        if not url_path.exists():
            console.print(f"  [red]文件不存在: {url_file}[/red]")
            return
        with open(url_path, encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith("#"):
                    hot_items.append(HotItem(title=url, url=url, source="手动输入"))
        console.print(f"  [dim]├[/dim]  从文件读取 [bold]{len(hot_items)}[/bold] 条 URL")
    else:
        searcher = HotSearcher(keyword, max_per_source, delay)
        hot_items = searcher.search_all()

    if not hot_items:
        console.print("\n  [yellow]未发现相关热点，爬取结束[/yellow]")
        console.print(f"  [yellow]提示：可尝试其他关键词，或确认网络连接[/yellow]")
        return

    # Step 2: 爬取正文
    crawler = ArticleCrawler(delay)
    saver = ArticleSaver(keyword)
    results: list[ArticleResult] = []

    console.print(f"\n  [bold cyan]┌─ 正在爬取文章正文 [/bold cyan]")
    console.print(f"  [bold cyan]│[/bold cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]爬取中...", total=len(hot_items))

        for i, item in enumerate(hot_items, 1):
            result = crawler.crawl(item)

            if result.status == "success":
                fpath = saver.save(result, i)
                progress.console.print(
                    f"  [dim]├[/dim]  [{i}/{len(hot_items)}] {result.title[:50]}"
                )
                progress.console.print(
                    f"  [dim]│[/dim]          → [green]✓ 已保存 ({result.crawl_time:.1f}s)[/green]"
                )
            else:
                fpath = saver.save(result, i)
                progress.console.print(
                    f"  [dim]├[/dim]  [{i}/{len(hot_items)}] {result.title[:50]}"
                )
                progress.console.print(
                    f"  [dim]│[/dim]          → [red]✗ {result.error_msg}[/red]"
                )

            results.append(result)
            progress.advance(task)

            if i < len(hot_items):
                time.sleep(delay)

        # 确保进度条到100%
        progress.update(task, completed=len(hot_items))

    console.print(f"  [bold cyan]└──────────────────────────────────────────────────────[/bold cyan]")

    # Step 3: 生成汇总
    summary_path = saver.save_summary(results)
    console.print(f"\n  [dim]汇总文件: {summary_path}[/dim]")

    # Step 4: 报告
    elapsed = time.time() - start_time
    print_report(results, keyword, elapsed, str(saver.output_dir))


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="行业热点爬取工具 — 输入行业关键词，自动搜索热点并保存为 Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python hotspot_crawler.py 健康
  python hotspot_crawler.py 人工智能 --max 10 --delay 3
  python hotspot_crawler.py 科技 --url-file urls.txt
        """,
    )
    parser.add_argument("keyword", help="行业关键词，如：健康、科技、教育")
    parser.add_argument("--max", type=int, default=15, help="每源最多取 N 条（默认：15）")
    parser.add_argument("--delay", type=float, default=2.0, help="请求间隔秒数（默认：2.0，推荐 >= 1.0）")
    parser.add_argument("--url-file", type=str, default=None,
                        help="跳过搜索，从文件读取 URL（每行一条，支持 # 注释）")

    args = parser.parse_args()

    if not args.keyword.strip():
        parser.print_help()
        sys.exit(1)

    if args.delay < 0:
        console.print("[red]--delay 不能为负数[/red]")
        sys.exit(1)

    try:
        run_pipeline(
            keyword=args.keyword.strip(),
            max_per_source=args.max,
            delay=args.delay,
            url_file=args.url_file,
        )
    except KeyboardInterrupt:
        console.print("\n  [yellow]用户中断，爬取结束[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n  [red]程序异常: {e}[/red]")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
