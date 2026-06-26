#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多提取器投票系统：并行运行多个正文提取器，评分选最优

提取器：
1. readability  — readability-lxml（现有方案）
2. text_density — BS4 文本密度（改进现有 fallback）
3. paragraphs   — 收集优质 <p> 标签簇

评分指标：内容长度(0.35) + 段落数(0.25) + 链接密度(0.20) + 文本/HTML比(0.20)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup
from readability import Document


# ============================================================
# 数据类
# ============================================================

@dataclass
class ExtractorResult:
    """单个提取器输出"""
    html: str
    text_length: int = 0
    paragraph_count: int = 0
    link_density: float = 0.0
    text_html_ratio: float = 0.0
    score: float = 0.0
    extractor_name: str = ""


# ============================================================
# 辅助函数
# ============================================================

def _clean_soup(soup: BeautifulSoup) -> None:
    """原地移除噪音标签"""
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                      "noscript", "form", "iframe", "svg", "canvas"]):
        tag.decompose()


def _get_text_stats(html: str) -> tuple[int, int, float, float]:
    """计算四个统计指标：(内容长度, 段落数, 链接密度, 文本/HTML比)"""
    soup = BeautifulSoup(html, "html.parser")
    _clean_soup(soup)
    text = soup.get_text(strip=True)
    text_len = len(text)
    good_ps = [p for p in soup.find_all("p") if len(p.get_text(strip=True)) > 20]
    link_text = sum(len(a.get_text(strip=True)) for a in soup.find_all("a"))
    link_density = link_text / max(text_len, 1)
    ratio = text_len / max(len(html), 1)
    return text_len, len(good_ps), link_density, ratio


# ============================================================
# 评分函数
# ============================================================

def score_content(html: str) -> ExtractorResult:
    """对提取的 HTML 进行加权评分"""
    text_len, p_count, link_den, ratio = _get_text_stats(html)

    # 内容长度得分：500-5000 最佳
    if 500 <= text_len <= 5000:
        length_score = 1.0
    elif text_len < 500:
        length_score = text_len / 500.0
    else:
        excess = text_len - 5000
        length_score = max(0.5, 1.0 - (excess / 15000.0) * 0.5)

    # 段落得分：>=5 个优质段落满分
    paragraph_score = min(p_count / 5.0, 1.0)

    # 链接得分：密度 >= 0.5 得 0 分
    link_score = max(0.0, 1.0 - link_den * 2.0)

    # 文本/HTML 比得分：>= 2% 满分
    ratio_score = min(ratio * 50.0, 1.0)

    final = (0.35 * length_score + 0.25 * paragraph_score +
             0.20 * link_score + 0.20 * ratio_score)

    return ExtractorResult(
        html=html, text_length=text_len, paragraph_count=p_count,
        link_density=link_den, text_html_ratio=ratio,
        score=round(final, 4),
    )


# ============================================================
# 提取器 1：Readability
# ============================================================

def extract_readability(html: str, url: str = "") -> ExtractorResult:
    """Readability 正文提取"""
    try:
        doc = Document(html, url=url)
        doc.summary()
        content = doc.content() or ""
        if not content.strip():
            return ExtractorResult(html="", extractor_name="readability")
        result = score_content(content)
        result.extractor_name = "readability"
        return result
    except Exception:
        return ExtractorResult(html="", extractor_name="readability")


# ============================================================
# 提取器 2：文本密度
# ============================================================

def _element_text_density(elem) -> float:
    """计算元素文本密度：文本长度 / (1 + 后代标签数)"""
    text = elem.get_text(strip=True)
    if len(text) < 50:
        return 0.0
    tag_count = len(elem.find_all()) + 1
    return len(text) / tag_count


def extract_text_density(html: str) -> ExtractorResult:
    """基于文本密度的正文提取（改进版 _fallback_extract）"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        _clean_soup(soup)
        candidates = soup.find_all(["div", "article", "section", "main", "td"])
        best, best_d = None, 0.0
        for c in candidates:
            d = _element_text_density(c)
            if d > best_d:
                best_d, best = d, c
        if best and len(best.get_text(strip=True)) >= 100:
            result = score_content(str(best))
            result.extractor_name = "text_density"
            return result
    except Exception:
        pass
    return ExtractorResult(html="", extractor_name="text_density")


# ============================================================
# 提取器 3：段落收集
# ============================================================

def extract_paragraphs(html: str) -> ExtractorResult:
    """收集优质 <p> 标签簇作为正文"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        _clean_soup(soup)

        # 策略 1：在容器内找段落簇（>=3 个优质段落）
        containers = soup.find_all(["article", "section", "div", "main"])
        best_c, best_n = None, 0
        for c in containers:
            good = [p for p in c.find_all("p") if len(p.get_text(strip=True)) > 30]
            if len(good) > best_n:
                best_n, best_c = len(good), c

        if best_c and best_n >= 3:
            result = score_content(str(best_c))
            result.extractor_name = "paragraphs"
            return result

        # 策略 2：全局收集段落
        all_ps = [str(p) for p in soup.find_all("p") if len(p.get_text(strip=True)) > 30]
        if len(all_ps) >= 2:
            combined = "<div>" + "\n".join(all_ps) + "</div>"
            result = score_content(combined)
            result.extractor_name = "paragraphs"
            return result
    except Exception:
        pass
    return ExtractorResult(html="", extractor_name="paragraphs")


# ============================================================
# 编排器
# ============================================================

def best_extraction(html: str, url: str = "") -> tuple[str, str, str]:
    """运行所有提取器，返回 (content_html, title, author)"""
    results = [
        extract_readability(html, url),
        extract_text_density(html),
        extract_paragraphs(html),
    ]
    valid = [r for r in results if r.html.strip() and r.score > 0]

    if not valid:
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        if body:
            return str(body), "", ""
        return "", "", ""

    winner = max(valid, key=lambda r: r.score)

    # 从 Readability 提取标题和作者
    title, author = "", ""
    try:
        doc = Document(html, url=url)
        title = doc.title() or ""
        if winner.extractor_name == "readability":
            author = doc.author() or ""
    except Exception:
        pass

    return winner.html, title, author
