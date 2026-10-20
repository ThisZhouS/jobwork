"""百度贴吧工具。

贴吧是各来源里最容易拿的：列表页基本不需要登录，只有"查看完整内容"
或深度翻页才要 cookie。所以工具里优先 HTTP，失败才升级浏览器。

两类入口：
* ``/f?kw=<公司名>``  —— 同名贴吧（有人气时最直接）
* ``/f/search/res``    —— 全站帖子搜索（覆盖"没有独立吧"的公司）
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from ...base import AgentStatus
from ..base import Tool, ToolBox, ToolResult, register_tool
from ..parsing import normalize_date, strip_tags

_POST_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>/p/\d+[^"]*)"[^>]*>(?P<body>.*?)</a>',
    re.S | re.I,
)
# 搜索页每条结果包在 <div class="s_post">…</div> 里
_SEARCH_ITEM_RE = re.compile(
    r'<div[^>]+class="[^"]*s_post[^"]*"[^>]*>(?P<body>.*?)</div>\s*</div>', re.S | re.I)
_TITLE_RE = re.compile(
    r'<a[^>]+href="(?P<href>/p/\d+[^"]*)"[^>]*>(?P<body>.*?)</a>', re.S | re.I)
_FLOOR_RE = re.compile(r"(?P<date>20\d{2}[-/]\d{1,2}[-/]\d{1,2})")

_MIN_HTML = 500


class TiebaSearchTool(Tool):
    name = "tieba_search"
    site = "百度贴吧"
    description = "搜贴吧同名吧与全站帖子（多数免登录；返回结构化行）"
    params = ("company",)
    requires = ("http",)

    async def call(self, box: ToolBox, company: str = "", **_: Any) -> ToolResult:
        keyword = quote(company)
        urls = (
            f"https://tieba.baidu.com/f?kw={keyword}&ie=utf-8",
            f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={keyword}",
        )
        rows: list[dict] = []
        blocked = False
        errors: list[str] = []
        notes: list[str] = []

        for url in urls:
            outcome = await box.fetch_page(url, min_len=_MIN_HTML)
            if outcome.blocked:
                blocked = True
                continue
            if outcome.status is AgentStatus.FAILED:
                errors.append(outcome.error or "抓取失败")
                continue
            found = parse_tieba_search(outcome.html, company)
            if not found:
                found = parse_tieba_bar(outcome.html, company)
            rows.extend(found)

        if not rows and blocked:
            return ToolResult.blocked(
                self.name, "贴吧要求验证或登录",
                notes=["请在浏览器打开贴吧完成验证，再用 --state 传登录态目录"],
            )
        if not rows:
            return ToolResult.empty(self.name,
                                    notes=[f"没有搜到相关帖子{'；' + errors[0] if errors else ''}"])
        return ToolResult.ok_(self.name, rows, notes=notes)


def parse_tieba_search(html: str, company: str) -> list[dict]:
    """解析全站搜索结果页。"""
    out: list[dict] = []
    blocks = _SEARCH_ITEM_RE.findall(html or "")
    targets = blocks or [html or ""]
    for block in targets:
        for match in _TITLE_RE.finditer(block):
            title = strip_tags(match.group("body"))
            if len(title) < 5:
                continue
            snippet = strip_tags(block)[:400]
            out.append({
                "title": title,
                "url": f"https://tieba.baidu.com{match.group('href')}",
                "snippet": snippet or title,
                "published_at": first_date(block),
                "company": company,
                "entry": "search",
            })
            break      # 每个结果块只取主标题，避免楼中楼重复
    return out


def parse_tieba_bar(html: str, company: str) -> list[dict]:
    """解析贴吧列表页里的主题帖链接。"""
    out: list[dict] = []
    seen: set[str] = set()
    for match in _POST_LINK_RE.finditer(html or ""):
        title = strip_tags(match.group("body"))
        if len(title) < 5:
            continue
        href = match.group("href")
        if href in seen:
            continue
        seen.add(href)
        tail = strip_tags(html[match.end(): match.end() + 300])
        out.append({
            "title": title,
            "url": f"https://tieba.baidu.com{href}",
            "snippet": tail or title,
            "published_at": first_date(match.group(0) + tail),
            "company": company,
            "entry": "bar",
        })
    return out


def first_date(text: str) -> str | None:
    match = _FLOOR_RE.search(text or "")
    return normalize_date(match.group("date")) if match else None


register_tool(TiebaSearchTool())
