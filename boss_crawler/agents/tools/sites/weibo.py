"""微博工具。

``s.weibo.com`` 搜索页要登录（SUB cookie），但移动端
``m.weibo.cn/api/container/getIndex`` 常免登录就能返回 JSON，所以优先走它。

微博的特点是"事件驱动"：欠薪、裁员、爆雷往往先在微博炸开。
所以这里抓到的负面信号对背调价值最高。
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from ...base import AgentStatus
from ..base import Tool, ToolBox, ToolResult, register_tool
from ..parsing import extract_json_object, normalize_date, strip_tags

_DETAIL_URL = "https://m.weibo.cn/detail/{id}"
# 微博搜索容器 id 的固定格式：100103type=1&q=关键词
_CONTAINER_TEMPLATE = "100103type%3D1%26q%3D{query}"

#: 检索词后缀：把"公司名"变成"公司名 + 求职相关事件"
QUERY_SUFFIXES = ("评价", "避雷", "欠薪", "裁员")

_DETAIL_RE = re.compile(
    r'href="(?P<href>(?:https?:)?//(?:m\.)?weibo\.c(?:n|om)/(?:detail|status)/[^"]+)"', re.I)


class WeiboSearchTool(Tool):
    name = "weibo_search"
    site = "微博"
    description = "搜微博上关于公司的评价/避雷/欠薪讨论（移动端接口常免登录）"
    params = ("company",)
    requires = ("http",)

    async def call(self, box: ToolBox, company: str = "", suffixes: int = 2, **_: Any) -> ToolResult:
        rows: list[dict] = []
        blocked = False
        errors: list[str] = []

        for suffix in QUERY_SUFFIXES[: max(1, suffixes)]:
            keyword = quote(f"{company} {suffix}")
            url = ("https://m.weibo.cn/api/container/getIndex"
                   f"?containerid={_CONTAINER_TEMPLATE.format(query=keyword)}&page_type=searchall")
            outcome = await box.fetch_page(url, is_blocked=_json_blocked, min_len=40)
            if outcome.blocked:
                blocked = True
                continue
            if outcome.status is AgentStatus.FAILED:
                errors.append(outcome.error or "抓取失败")
                continue
            parsed = parse_weibo_json(outcome.html, company)
            if not parsed:
                parsed = parse_weibo_html(outcome.html, company)
            rows.extend(parsed)

        if not rows and blocked:
            return ToolResult.blocked(
                self.name, "微博要求登录（搜索接口未返回数据）",
                notes=["浏览器登录微博后把 cookie 目录传给 --state"],
            )
        if not rows:
            return ToolResult.empty(self.name,
                                    notes=[f"没有搜到相关讨论{'；' + errors[0] if errors else ''}"])
        return ToolResult.ok_(self.name, rows)


def _json_blocked(html: str) -> bool:
    stripped = (html or "").strip()
    if not stripped:
        return True
    if stripped.startswith("{"):
        squashed = stripped.replace(" ", "")
        return '"ok":1' not in squashed and '"cards"' not in squashed
    return False


def parse_weibo_json(text: str, company: str) -> list[dict]:
    """解析 m.weibo.cn 的 container 返回，递归找 card_type=9 的博文。"""
    payload = extract_json_object(text)
    if not isinstance(payload, dict) or payload.get("ok") != 1:
        return []

    mblogs: list[dict[str, Any]] = []
    walk_cards(payload.get("data") or {}, mblogs)

    out: list[dict] = []
    for blog in mblogs:
        content = strip_tags(str(blog.get("text") or ""))
        if not content:
            continue
        user = blog.get("user") or {}
        out.append({
            "title": content[:60],
            "url": _DETAIL_URL.format(id=blog.get("id") or blog.get("mid") or ""),
            "snippet": content,
            "published_at": normalize_date(str(blog.get("created_at") or "")),
            "author": user.get("screen_name") if isinstance(user, dict) else None,
            "reposts": blog.get("reposts_count"),
            "comments": blog.get("comments_count"),
            "attitudes": blog.get("attitudes_count"),
            "company": company,
        })
    return out


def walk_cards(node: Any, out: list[dict[str, Any]]) -> None:
    """cards / card_group 可以任意嵌套，统一递归到 mblog。"""
    if isinstance(node, dict):
        if node.get("card_type") == 9 and isinstance(node.get("mblog"), dict):
            out.append(node["mblog"])
        for key in ("cards", "card_group"):
            walk_cards(node.get(key), out)
    elif isinstance(node, list):
        for item in node:
            walk_cards(item, out)


def parse_weibo_html(html: str, company: str) -> list[dict]:
    """登录态下的 s.weibo.com 页面：用 ``/detail/`` 或 ``/status/`` 链接做锚点。"""
    out: list[dict] = []
    seen: set[str] = set()
    for match in _DETAIL_RE.finditer(html or ""):
        href = match.group("href")
        if href in seen:
            continue
        seen.add(href)
        url = href if href.startswith("http") else f"https:{href}"
        tail = strip_tags(html[match.end(): match.end() + 500])
        if len(tail) < 8:
            continue
        out.append({
            "title": tail[:60],
            "url": url,
            "snippet": tail[:300],
            "published_at": normalize_date(tail),
            "author": None,
            "company": company,
        })
    return out


register_tool(WeiboSearchTool())
