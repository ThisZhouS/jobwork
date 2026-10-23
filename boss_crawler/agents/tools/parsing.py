"""工具层共享的纯函数：文本清理、情感判定、JSON 抽取、日期归一。

放在工具层而不是 agent 层，是因为**解析属于工具的职责**：工具把页面变成
结构化行，agent 只做汇总。这些函数不联网、不碰数据库，便于离线单测。
"""
from __future__ import annotations

import html as html_mod
import json
import re
from typing import Any, Iterable

from ..base import Finding

# ---------------------------------------------------------------- 情感词表
# 刻意保持小而有指向性：求职者关心的是"坑不坑"，不是泛泛的正负面。
NEGATIVE_WORDS: tuple[tuple[str, float], ...] = (
    ("欠薪", 1.0), ("拖欠工资", 1.0), ("发不出工资", 1.0), ("跑路", 1.0),
    ("裁员", 0.8), ("优化", 0.4), ("毁约", 1.0), ("违约", 0.8),
    ("仲裁", 0.9), ("劳动仲裁", 1.0), ("起诉", 0.7), ("被执行", 0.9),
    ("失信", 1.0), ("老赖", 1.0), ("违法", 0.9), ("处罚", 0.7),
    ("加班", 0.5), ("996", 0.8), ("007", 0.8), ("内卷", 0.5),
    ("离职率高", 0.8), ("坑", 0.8), ("避雷", 0.9), ("劝退", 0.8),
    ("压榨", 0.9), ("pua", 0.8), ("白嫖", 0.9), ("画饼", 0.7),
    ("扣绩效", 0.9), ("不交社保", 1.0), ("单休", 0.6), ("狼性", 0.6),
    ("竞业", 0.5), ("体检卡", 0.3), ("外包", 0.4), ("皮包", 0.9),
    ("经营异常", 0.9), ("吊销", 1.0), ("注销", 0.6), ("破产", 1.0),
)

POSITIVE_WORDS: tuple[tuple[str, float], ...] = (
    ("靠谱", 0.8), ("福利好", 0.9), ("双休", 0.8), ("不加班", 0.9),
    ("涨薪", 0.7), ("氛围好", 0.8), ("推荐", 0.6), ("良心", 0.9),
    ("稳定", 0.6), ("正规", 0.7), ("五险一金", 0.7), ("年终奖", 0.6),
    ("晋升", 0.5), ("培训", 0.4), ("上市", 0.5), ("融资", 0.5),
    ("offer", 0.3), ("满意", 0.7), ("值得", 0.6), ("好评", 0.8),
)


def sentiment_of(text: str) -> float | None:
    """启发式情感：返回 -1.0 / 0.0 / 1.0，无线索返回 None。

    用"负分 - 正分"的净强度决定符号，避免中性词被当成情绪。
    """
    if not text:
        return None
    lowered = text.lower()
    negative = sum(weight for word, weight in NEGATIVE_WORDS if word in lowered)
    positive = sum(weight for word, weight in POSITIVE_WORDS if word in lowered)
    if negative == 0 and positive == 0:
        return None
    net = positive - negative
    if net > 0.2:
        return 1.0
    if net < -0.2:
        return -1.0
    return 0.0


def sentiment_weight(text: str) -> float:
    """情绪越强，权重越高；上限 2.0。"""
    if not text:
        return 1.0
    lowered = text.lower()
    strength = sum(w for word, w in NEGATIVE_WORDS if word in lowered)
    strength += sum(w for word, w in POSITIVE_WORDS if word in lowered)
    return round(min(2.0, 1.0 + strength / 3.0), 2)


# ---------------------------------------------------------------- HTML
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def strip_tags(text: str) -> str:
    """去标签 + 反转义 + 压空白。用于从 HTML 片段取纯文本。"""
    if not text:
        return ""
    cleaned = _SCRIPT_RE.sub(" ", text)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = html_mod.unescape(cleaned)
    cleaned = _WS_RE.sub(" ", cleaned)
    return "\n".join(line.strip() for line in cleaned.splitlines() if line.strip())


def clip(text: str, limit: int = 300) -> str:
    """截断到 limit 字符，尽量不切在词中间。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "！", "？", "；", "\n", "，", " "):
        index = cut.rfind(sep)
        if index > limit * 0.6:
            return cut[: index + 1].strip()
    return cut.rstrip() + "…"


# ---------------------------------------------------------------- JSON
def extract_json_after(html: str, key: str) -> Any:
    """在整页 HTML 里找 ``"key":`` 后面的完整 JSON 值。

    比"定位某个 script 标签"稳：站点改版常常只是搬动位置，键名却很少变。
    """
    marker = f'"{key}"'
    index = html.find(marker)
    if index < 0:
        return None
    colon = html.find(":", index + len(marker))
    if colon < 0:
        return None
    decoder = json.JSONDecoder()
    for start in range(colon + 1, min(colon + 40, len(html))):
        if html[start] in "{[":
            try:
                value, _ = decoder.raw_decode(html[start:])
                return value
            except json.JSONDecodeError:
                continue
    return None


def extract_json_object(text: str) -> Any:
    """从纯 JSON 或 ``<html><body><p>{...}</p>`` 这类包裹中取对象。

    浏览器渲染 JSON 接口时经常套一层 HTML；直接 ``json.loads`` 会失败。
    注意不能对整段做 HTML 反转义再解析：``&quot;`` 会变成裸引号，反而破坏 JSON。
    """
    raw = (text or "").strip()
    if not raw:
        return None

    candidates = [raw]
    if raw.startswith("<"):
        try:
            from lxml import html as lxml_html

            candidates.append(lxml_html.fromstring(raw).text_content())
        except Exception:  # noqa: BLE001 - 解析失败就走下面的花括号截取
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start:end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def regex_field(html: str, key: str) -> str | None:
    """抓 ``"key":"value"`` 形式的标量字段。

    天眼查把 creditCode / regCapital 这类字段直接内嵌在页面 HTML 里，
    逐个正则取值比解析整棵 JSON 树稳得多。

    取到的原文可能带 JSON 转义（``\\u67d0`` 这类），所以用 ``json.loads``
    还原来正确处理 Unicode——手工 ``unicode_escape`` 对中文会失败。
    """
    pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*"((?:[^"\\]|\\.)*)"')
    match = pattern.search(html)
    if not match:
        return None
    raw = match.group(1)
    if "\\" not in raw:
        return raw
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw


# ---------------------------------------------------------------- 其他
_DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")


def normalize_date(text: str) -> str | None:
    """从任意文本里抽第一个日期，统一成 YYYY-MM-DD。"""
    match = _DATE_RE.search(text or "")
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def make_finding(
    source: str,
    *,
    title: str = "",
    url: str = "",
    snippet: str = "",
    published_at: str | None = None,
    author: str | None = None,
    **meta: Any,
) -> Finding:
    """统一构造 Finding，顺便算好情感与权重。"""
    text = f"{title} {snippet}"
    return Finding(
        source=source,
        title=clip(title, 120),
        url=url or "",
        snippet=clip(snippet, 300),
        published_at=published_at or normalize_date(text),
        author=author,
        sentiment=sentiment_of(text),
        weight=sentiment_weight(text),
        meta=meta,
    )


def dedupe(findings: Iterable[Finding]) -> list[Finding]:
    """按 URL（无 URL 时按来源+标题）去重，保序。"""
    seen: set[str] = set()
    out: list[Finding] = []
    for finding in findings:
        key = finding.url or f"{finding.source}:{finding.title}"
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def negative_ratio(findings: Iterable[Finding]) -> float:
    """负面占比。无判定样本时返回 0。"""
    judged = [f for f in findings if f.sentiment is not None]
    if not judged:
        return 0.0
    return round(sum(1 for f in judged if f.sentiment < 0) / len(judged), 3)


def dedupe_rows(rows: Iterable[dict], *, key: str = "url") -> list[dict]:
    """工具产出行的去重（按 url，缺失时按 title）。"""
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        marker = str(row.get(key) or row.get("title") or "")
        if not marker or marker in seen:
            continue
        seen.add(marker)
        out.append(row)
    return out
