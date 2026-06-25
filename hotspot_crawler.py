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
import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import html2text
import requests
import yaml
from bs4 import BeautifulSoup
from readability import Document
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

# 搜索源模块
from searcher import Searcher
from sources import HotItem, default_headers, random_ua, REQUEST_TIMEOUT

# 新模块（可选依赖）
try:
    from config import CrawlerConfig, load_config
    from fetcher import Fetcher, FetchResult
    _HAS_NEW_MODULES = True
except ImportError:
    _HAS_NEW_MODULES = False

# 引擎模块（可选依赖）
try:
    from engine import CrawlerEngine, CrawlerReport
    _HAS_ENGINE = True
except ImportError:
    _HAS_ENGINE = False

# ============================================================
# Console
# ============================================================

console = Console()


# ============================================================
# 工具函数
# ============================================================

def safe_filename(title: str, max_len: int = 40) -> str:
    """移除文件名中的非法字符，截断到 max_len"""
    safe = re.sub(r'[\\/:*?"<>|]', "", title)
    safe = safe.strip().replace(" ", "_")
    if len(safe) > max_len:
        safe = safe[:max_len]
    return safe


# ============================================================
# 数据类
# ============================================================

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
# 正文爬取模块（旧路径降级用）
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
# 文件存储模块（旧路径降级用）
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
                console.print(f"    [dim]x[/dim] {r.title[:50]} — [red]{r.error_msg}[/red]")


def run_pipeline(
    keyword: str,
    max_per_source: int = 15,
    delay: float = 2.0,
    url_file: str = None,
    browser_mode: str = "auto",
    no_dedup: bool = False,
    resume: bool = True,
    retry_failed: bool = True,
    output_formats: list[str] | None = None,
    output_dir: str | None = None,
    source_configs: dict[str, dict] | None = None,
):
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
        searcher = Searcher(keyword, max_per_source=max_per_source, delay=delay,
                              source_configs=source_configs)
        hot_items = searcher.search_all()

    if not hot_items:
        console.print("\n  [yellow]未发现相关热点，爬取结束[/yellow]")
        console.print(f"  [yellow]提示：可尝试其他关键词，或确认网络连接[/yellow]")
        return

    # Step 2: 爬取正文
    if _HAS_NEW_MODULES and _HAS_ENGINE:
        # 使用 CrawlerEngine 全流程编排
        from config import CrawlerConfig
        from engine import CrawlerEngine
        cfg = CrawlerConfig(
            keyword=keyword,
            max_per_source=max_per_source,
            delay=delay,
            browser_mode=browser_mode,
            output_formats=output_formats or ["md"],
            dedup_enabled=not no_dedup,
            resume=resume,
            retry_failed=retry_failed,
            output_dir=output_dir,
        )
        engine = CrawlerEngine(cfg)
        report = engine.run(hot_items)
        # 用 report 打印结果
        console.print(f"\n  [bold green]爬取完成! 成功: {report.success}, 失败: {report.failed}, 去重跳过: {report.deduped}[/bold green]")
        console.print(f"  [dim]保存路径: {report.output_dir}[/dim]")
        console.print(f"  [dim]用时: {report.elapsed:.1f}秒[/dim]")
        if report.failed > 0:
            console.print(f"  [yellow]引擎报告有 {report.failed} 篇失败，详情见引擎日志[/yellow]")
    else:
        saver = ArticleSaver(keyword)
        results: list = []

        console.print(f"\n  [bold cyan]┌─ 正在爬取文章正文 [/bold cyan]")
        console.print(f"  [bold cyan]│[/bold cyan]")

        # 选择爬取引擎
        if _HAS_NEW_MODULES and browser_mode != "never":
            from config import CrawlerConfig
            from fetcher import Fetcher
            cfg = CrawlerConfig(
                keyword=keyword,
                max_per_source=max_per_source,
                delay=delay,
                browser_mode=browser_mode,
                url_file=url_file,
            )
            fetcher = Fetcher(cfg)
        else:
            crawler = ArticleCrawler(delay)

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
                if _HAS_NEW_MODULES and browser_mode != "never":
                    result = fetcher.fetch(item.url, source=item.source, summary=item.summary)
                else:
                    result = crawler.crawl(item)

                if result.status == "success":
                    fpath = saver.save(result, i)
                    progress.console.print(
                        f"  [dim]├[/dim]  [{i}/{len(hot_items)}] {result.title[:50]}"
                    )
                    progress.console.print(
                        f"  [dim]│[/dim]          [green]OK 已保存 ({result.crawl_time:.1f}s)[/green]"
                    )
                else:
                    fpath = saver.save(result, i)
                    progress.console.print(
                        f"  [dim]├[/dim]  [{i}/{len(hot_items)}] {result.title[:50]}"
                    )
                    progress.console.print(
                        f"  [dim]│[/dim]          [red]x {result.error_msg}[/red]"
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
# Login 流程
# ============================================================

def _login_zhihu():
    """打开 Playwright 浏览器让用户扫码登录知乎，自动提取 Cookie"""
    console.print("  [cyan]正在打开知乎登录页...[/cyan]")
    console.print("  [yellow]请用手机知乎 App 扫码登录[/yellow]")
    console.print("  [dim]等待登录中（最长 3 分钟）...[/dim]")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        console.print("  [red]Playwright 未安装，请运行: pip install playwright && playwright install chromium[/red]")
        sys.exit(1)

    from cookie_manager import CookieManager

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )
        page = context.new_page()
        page.goto("https://www.zhihu.com/signin", wait_until="networkidle")

        import time
        for _ in range(180):
            time.sleep(1)
            cookies = context.cookies()
            has_login = any(
                c["name"] in ("z_c0", "sessionid", "login")
                and "zhihu" in c["domain"]
                for c in cookies
            )
            if has_login:
                cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)
                CookieManager().save("zhihu", cookie_str)
                console.print(f"  [green]登录成功！Cookie 已保存[/green]")
                browser.close()
                return

        console.print("  [red]登录超时（3 分钟），请重试[/red]")
        browser.close()


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
  python hotspot_crawler.py --login zhihu
  python hotspot_crawler.py 人工智能 --max 10 --delay 3
  python hotspot_crawler.py 科技 --url-file urls.txt
        """,
    )
    parser.add_argument("keyword", nargs="?", default="", help="行业关键词，如：健康、科技、教育")
    parser.add_argument("--max", type=int, default=15, help="每源最多取 N 条（默认：15）")
    parser.add_argument("--delay", type=float, default=2.0, help="请求间隔秒数（默认：2.0，推荐 >= 1.0）")
    parser.add_argument("--url-file", type=str, default=None,
                        help="跳过搜索，从文件读取 URL（每行一条，支持 # 注释）")
    parser.add_argument(
        "--browser", choices=["auto", "always", "never"], default="auto",
        help="浏览器渲染模式: auto=智能降级, always=强制浏览器, never=禁用(默认: auto)",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="YAML 配置文件路径（CLI 参数会覆盖配置文件中对应的值）",
    )
    parser.add_argument(
        "--no-dedup", action="store_true",
        help="禁用内容去重",
    )
    parser.add_argument(
        "--resume", action="store_true", default=None,
        help="启用断点续爬（默认: auto，检测到失败记录时自动启用）",
    )
    parser.add_argument(
        "--no-resume", action="store_true", default=None,
        help="禁用断点续爬",
    )
    parser.add_argument(
        "--retry-failed", action="store_true", default=None,
        help="重试上次失败的 URL（默认: True，仅 --resume 时生效）",
    )
    parser.add_argument(
        "--no-retry-failed", action="store_true", default=None,
        help="不重试上次失败的 URL",
    )
    parser.add_argument(
        "--output-format", type=str, default=None,
        help="输出格式: md/jsonl/csv (多个用逗号分隔，如: md,jsonl)",
    )
    parser.add_argument(
        "--login", type=str, default=None,
        choices=["zhihu"],
        help="登录指定平台并保存 Cookie（当前支持: zhihu）",
    )

    args = parser.parse_args()

    if args.login:
        if args.login == "zhihu":
            _login_zhihu()
        sys.exit(0)

    if not args.keyword.strip():
        parser.print_help()
        sys.exit(1)

    if args.delay < 0:
        console.print("[red]--delay 不能为负数[/red]")
        sys.exit(1)

    # Parse output formats
    if args.output_format:
        output_formats = [fmt.strip() for fmt in args.output_format.split(",")]
    else:
        output_formats = ["md"]

    no_dedup = args.no_dedup
    resume = not args.no_resume if args.no_resume else (args.resume if args.resume is not None else True)
    retry_failed = not args.no_retry_failed if args.no_retry_failed else (args.retry_failed if args.retry_failed is not None else True)
    output_dir = None  # or from config

    try:
        run_pipeline(
            keyword=args.keyword.strip(),
            max_per_source=args.max,
            delay=args.delay,
            url_file=args.url_file,
            browser_mode=args.browser,
            no_dedup=no_dedup,
            resume=resume,
            retry_failed=retry_failed,
            output_formats=output_formats,
            output_dir=output_dir,
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
