"""知乎搜索工具。

反爬要点（都在工具里，agent 不用管）：

* 优先打 ``/api/v4/search_v3``：JSON 接口比 HTML 稳，字段也全；
* 未登录时该接口返回错误包（很短的 JSON），所以被挡判定要单独处理；
* 兜底退回搜索页 HTML，用 ``/question/`` 链接做锚点而不是 class 名；
* 仍然不行就返回 BLOCKED，让人去登录，而不是硬碰验证码。
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from ...base import AgentStatus
from ..base import Tool, ToolBox, ToolResult, register_tool
from ..parsing import extract_json_after, normalize_date, strip_tags

_QUESTION_URL = "https://www.zhihu.com/question/{id}"
_ARTICLE_URL = "https://zhuanlan.zhihu.com/p/{id}"

# 求职者最关心的问法，拼进检索词能显著提高命中率
QUERY_SUFFIXES = ("怎么样", "值得去吗", "面试", "加班 待遇", "裁员 欠薪")

_SEARCH_API = (
    "https://www.zhihu.com/api/v4/search_v3"
    "?t=general&q={query}&correction=1&offset=0&limit=20"
)


class ZhihuSearchTool(Tool):
    name = "zhihu_search"
    site = "知乎"
    description = "搜知乎上与公司相关的提问/回答/文章（需登录；返回结构化行）"
    params = ("company",)
    requires = ("http",)

    async def call(self, box: ToolBox, company: str = "", suffixes: int = 3, **_: Any) -> ToolResult:
        rows: list[dict] = []
        notes: list[str] = []
        blocked = False
        errors: list[str] = []

        for suffix in QUERY_SUFFIXES[: max(1, suffixes)]:
            url = _SEARCH_API.format(query=quote(f"{company} {suffix}"))
            outcome = await box.fetch_page(url, is_blocked=_json_blocked, min_len=40)
            if outcome.blocked:
                blocked = True
                continue
            if outcome.status is AgentStatus.FAILED:
                errors.append(outcome.error or "抓取失败")
                continue
            parsed = parse_search_json(outcome.html, company)
            if not parsed:
                # JSON 畸形或字段变更，退回 HTML 解析
                parsed = parse_search_html(outcome.html, company)
            rows.extend(parsed)

        if not rows and blocked:
            return ToolResult.blocked(
                self.name,
                "知乎要求登录（搜索接口未返回数据）",
                notes=["在浏览器登录知乎后把 cookie 目录传给 --state"],
            )
        if not rows:
            return ToolResult.empty(
                self.name,
                notes=notes or [f"没有搜到相关讨论{'；' + errors[0] if errors else ''}"],
            )
        return ToolResult.ok_(self.name, rows,
                              notes=notes + ([f"其他查询失败：{errors[0]}"] if errors else []))


def _json_blocked(html: str) -> bool:
    """知乎 JSON 接口被挡时返回的是很短的错误包，不是长 HTML。"""
    stripped = (html or "").strip()
    if not stripped:
        return True
    if stripped.startswith("{"):
        if extract_json_after(stripped, "error"):
            return True
        return '"data"' not in stripped
    return False


def parse_search_json(text: str, company: str) -> list[dict]:
    """解析 ``search_v3`` 返回。条目在 ``data[]``，正文在 ``object`` 里。"""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        return []

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        obj = row.get("object") or {}
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type") or row.get("type") or ""
        title = strip_tags(str(obj.get("title") or (obj.get("question") or {}).get("name") or ""))
        content = strip_tags(str(
            (row.get("highlight") or {}).get("content")
            or obj.get("content") or obj.get("excerpt") or ""
        ))
        if not title and not content:
            continue
        out.append({
            "title": title or content[:60],
            "url": object_url(obj, kind),
            "snippet": content or title,
            "published_at": timestamp_to_date(
                obj.get("created_time") or obj.get("updated_time") or obj.get("created")),
            "author": author_name(obj.get("author")),
            "kind": kind,
            "votes": obj.get("voteup_count"),
            "comments": obj.get("comment_count"),
            "company": company,
        })
    return out


def object_url(obj: dict[str, Any], kind: str) -> str:
    """把 API 里的各种 id 拼成人类可点的页面地址。"""
    raw = obj.get("url") or ""
    if isinstance(raw, str) and raw.startswith("http") and "/api/" not in raw:
        return raw
    if kind == "answer":
        question_id = (obj.get("question") or {}).get("id")
        if question_id:
            return f"{_QUESTION_URL.format(id=question_id)}/answer/{obj.get('id')}"
    question = obj.get("question") or {}
    if isinstance(question, dict) and question.get("id"):
        return _QUESTION_URL.format(id=question["id"])
    if obj.get("id") and kind == "article":
        return _ARTICLE_URL.format(id=obj["id"])
    if isinstance(raw, str) and "/api/v4/questions/" in raw:
        return raw.replace("https://www.zhihu.com/api/v4/questions/", _QUESTION_URL.format(id=""))
    return ""


def author_name(author: Any) -> str | None:
    if isinstance(author, dict):
        name = author.get("name") or author.get("headline")
        return str(name) if name else None
    return None


def timestamp_to_date(value: Any) -> str | None:
    """知乎给的是秒级时间戳；也兼容已经是字符串的日期。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.isdigit():
        return normalize_date(value)
    try:
        import datetime as dt

        return dt.datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return None


_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>(?:https://www\.zhihu\.com)?/(?:question|answer|p)/[^"]+)"[^>]*>(?P<body>.*?)</a>',
    re.S | re.I,
)


def parse_search_html(html: str, company: str) -> list[dict]:
    """从搜索页 HTML 里抠条目。用 ``/question/`` 链接做锚点，比 class 名稳。"""
    out: list[dict] = []
    for match in _LINK_RE.finditer(html or ""):
        title = strip_tags(match.group("body"))
        if len(title) < 6:
            continue
        href = match.group("href")
        url = href if href.startswith("http") else f"https://www.zhihu.com{href}"
        tail = strip_tags(html[match.end(): match.end() + 400])
        out.append({
            "title": title,
            "url": url,
            "snippet": tail[:200] or title,
            "published_at": normalize_date(match.group(0) + tail),
            "author": None,
            "kind": "html",
            "company": company,
        })
    return out


register_tool(ZhihuSearchTool())
