"""评分公共工具：区间映射、关键词匹配、年限解析、缺口描述。

三个评分 agent 都要做同样的事——"把某个量映射成 0-100 分"、"在文本里找关键词"、
"把缺口翻译成可执行的建议"。放在这里一次写好，避免三份各写一遍之后口径不一致。
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

#: 没有证据时的中性分。刻意不用 0 或 100：那会把"不知道"伪装成"很差/很好"。
NEUTRAL = 60.0


def clamp(score: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, score))


def interp(value: float, points: Sequence[tuple[float, float]], *, neutral: float = NEUTRAL) -> float:
    """按 (阈值, 分数) 折线线性插值。

    ``points`` 必须按阈值升序。低于首个阈值取首个分数，高于末尾取末尾分数。
    """
    if not points:
        return neutral
    ordered = sorted(points, key=lambda item: item[0])
    if value <= ordered[0][0]:
        return float(ordered[0][1])
    if value >= ordered[-1][0]:
        return float(ordered[-1][1])
    for (x0, y0), (x1, y1) in zip(ordered, ordered[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return float(y1)
            ratio = (value - x0) / (x1 - x0)
            return float(y0 + (y1 - y0) * ratio)
    return float(ordered[-1][1])


def as_text(value: Any) -> str:
    """把任意字段压成可搜索的文本。列表会展开，dict 取 value。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(as_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(as_text(v) for v in value)
    return str(value)


def normalize_skills(value: Any) -> list[str]:
    """把技能字段统一成小写去重列表。支持列表、逗号/顿号分隔的字符串。"""
    if value is None:
        return []
    raw: list[str] = []
    if isinstance(value, str):
        raw = re.split(r"[,，、;；/\|\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            raw.extend(normalize_skills(item))
    elif isinstance(value, dict):
        raw = [str(k) for k in value]
    else:
        raw = [str(value)]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item).strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def hits(text: str, keywords: Iterable[str]) -> list[str]:
    """返回 keywords 里出现在 text 中的那些（大小写不敏感）。"""
    lowered = (text or "").lower()
    return [kw for kw in keywords if kw and kw.lower() in lowered]


def coverage(required: Sequence[str], available: Sequence[str], *, text: str = "") -> float:
    """需求覆盖率 0-1。``text`` 用于兜底：技能列表没写但正文提到了也算。"""
    if not required:
        return 1.0
    lowered_text = (text or "").lower()
    available_set = {a.lower() for a in available}
    matched = 0
    for req in required:
        needle = req.lower()
        if needle in available_set or needle in lowered_text:
            matched += 1
    return matched / len(required)


_YEARS_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\+|年以上|年)")
_YEAR_RANGE = re.compile(r"(19|20)\d{2}\s*[-—~至]\s*((19|20)\d{2}|至今|现在|now)", re.I)
# "3-5年" 这种区间，按最低要求算：用人方要的是至少 3 年
_YEARS_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~至到]\s*(\d+(?:\.\d+)?)")


def parse_years(value: Any) -> float | None:
    """解析"3年""3-5年""3年以上"之类的年限要求。

    区间取下限：JD 写 3-5 年，意思是"至少 3 年"，用上限会误判为不匹配。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = as_text(value)
    range_match = _YEARS_RANGE.search(text)
    if range_match:
        try:
            return float(range_match.group(1))
        except ValueError:
            return None
    match = _YEARS_IN_TEXT.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def experience_years(experience: Any) -> float:
    """从简历经历里估算总年限：优先累加时间段，退回"X年"字样。"""
    if not experience:
        return 0.0
    entries = experience if isinstance(experience, list) else [experience]
    total = 0.0
    counted_period = False
    for entry in entries:
        if isinstance(entry, dict):
            span = " ".join(as_text(entry.get(k)) for k in ("start", "end", "period", "duration", "time"))
            total += _period_years(span)
            if _period_years(span) > 0:
                counted_period = True
            years = parse_years(entry.get("years")) or parse_years(entry.get("duration"))
            if years and not counted_period:
                total += years
        else:
            span = as_text(entry)
            period = _period_years(span)
            total += period
            if period > 0:
                counted_period = True
            elif not counted_period:
                total += parse_years(span) or 0.0
    return round(total, 1)


def _period_years(span: str) -> float:
    """把 "2021-03 ~ 2024-06" 算成 3.3 年。算不出来返回 0。"""
    text = span or ""
    import datetime as dt

    found = re.findall(r"(19|20)(\d{2})[.\-/年]?\s*(\d{1,2})?", text)
    dates: list[tuple[int, int]] = []
    for century, year, month in found:
        dates.append((int(century + year), int(month) if month else 1))
    if len(dates) >= 2:
        (y0, m0), (y1, m1) = dates[0], dates[1]
        if (y1, m1) < (y0, m0):
            return 0.0
        return round((y1 - y0) + (m1 - m0) / 12.0, 2)
    if len(dates) == 1 and re.search(r"至今|现在|now", text, re.I):
        now = dt.date.today()
        y0, m0 = dates[0]
        return round((now.year - y0) + (now.month - m0) / 12.0, 2)
    return 0.0


_QUANT_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:%|％|倍|万|亿|w|k|人|次|个|条|台|秒|ms|小时|天|月))"
    r"|(\d{2,})",
    re.I,
)


def quantification_hits(text: str) -> int:
    """数成果量化的痕迹：百分比、倍数、绝对数字都算。"""
    return len(_QUANT_RE.findall(text or ""))


def bullet_count(text: str) -> int:
    """粗略数条目数：换行、分号、项目符号都当作条目分隔。"""
    if not text:
        return 0
    parts = re.split(r"[\n;；•·]+", text)
    return sum(1 for part in parts if len(part.strip()) >= 6)


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def pick_lowest(dimensions: Sequence[Any]) -> Any | None:
    """分最低且有权重的维度，用来决定优先给哪方面的建议。"""
    candidates = [d for d in dimensions if getattr(d, "weight", 0) > 0]
    if not candidates:
        return None
    return min(candidates, key=lambda d: getattr(d, "score", 0.0))


def gap_advice(required: Sequence[str], available: Sequence[str], *, text: str = "",
               limit: int = 5) -> list[str]:
    """把技能缺口翻译成一句可执行的话。"""
    if not required:
        return []
    lowered_text = (text or "").lower()
    available_set = {a.lower() for a in available}
    missing = [r for r in required if r.lower() not in available_set and r.lower() not in lowered_text]
    if not missing:
        return []
    shown = "、".join(missing[:limit])
    return [f"岗位要求 {shown}，但简历里没有体现：补一个能在面试里讲清的小项目，或把已有经历中相关的部分明确写出来"]
