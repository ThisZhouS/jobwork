"""文本与地址工具：公司名规范化、地址拆解、薪资单位。

与 JD 解析无关，单独成模块，方便其他入口（如人工补录）复用。
"""

from __future__ import annotations

import re
import unicodedata

_TRUNC_RE = re.compile(r"(?:\.{2,}|…)$")
_ANON_RE = re.compile(r"某(?:大型|知名|上市|互联网|计算机|软件|科技|集团|公司|企业)")
_DISTRICT_RE = re.compile(r"([\u4e00-\u9fa5]{2,4}?(?:区|县|市|旗))")
_LEGAL_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9()（）·]{2,30}?(?:股份有限公司|有限责任公司|有限公司|集团))"
)
_WS_RE = re.compile(r"\s+")
_EDGE_PUNCT = "，,、;；:：·—-_/\\|"


def normalize_text(value: object) -> str:
    """全角转半角、压缩空白、去掉首尾标点。"""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = _WS_RE.sub(" ", text).strip()
    return text.strip(_EDGE_PUNCT + " ")


def clean_company(name: str | None) -> dict:
    """公司名：去截断符、识别脱敏/截断、保留原名。"""
    raw = normalize_text(name)
    truncated = bool(_TRUNC_RE.search(raw))
    cleaned = _TRUNC_RE.sub("", raw).strip()
    anonymous = bool(_ANON_RE.search(cleaned))
    return {
        "name": cleaned,
        "raw": raw,
        "is_anonymous": anonymous,
        "is_truncated": truncated,
        "key": re.sub(r"\s+", "", cleaned),
    }


def extract_legal_name(intro: str | None, fallback: str = "") -> str:
    """从公司介绍首句里提取工商全称，如「华为技术有限公司」。"""
    text = normalize_text(intro)
    if not text:
        return fallback
    head = re.split(r"[。；;\n]", text)[0]
    match = _LEGAL_RE.search(head)
    return match.group(1).strip() if match else fallback


def collapse_repeat_prefix(text: str) -> str:
    """折叠重复的地址前缀：'成都武侯区X广场成都武侯区X广场1栋' -> '成都武侯区X广场1栋'。

    站点会把「商圈 + 详细地址」直接拼起来，出现整段重复。
    """
    for size in range(len(text) // 2, 3, -1):
        if text[:size] == text[size: size * 2]:
            return text[size:]
    return text


def collapse_repeat_tail(text: str) -> str:
    """折叠重复的地址尾段：'新开普大厦高新区新开普大厦' -> '高新区新开普大厦'。

    只在「重复段 ≥4 字，且删完还剩 ≥4 字」时动手，避免把 '成都成都银行大厦'
    这类真名切坏。
    """
    length = len(text)
    for size in range(length // 2, 3, -1):
        tail = text[-size:]
        first = text.find(tail)
        if first == -1 or first == length - size:
            continue
        remaining = text[:first] + text[first + size:]
        if len(remaining.strip()) < 4:
            continue
        return remaining.strip()
    return text


def strip_trailing_city(text: str, city: str) -> str:
    """去掉地址尾部重复的城市名：'成都武侯区(阿里中心)成都' -> '成都武侯区(阿里中心)'。"""
    city = normalize_text(city)
    if not city or len(text) <= len(city) + 2:
        return text
    if text.endswith(city):
        return text[: -len(city)].rstrip(" ,，、")
    return text


def parse_address(
    address: str | None,
    *,
    city: str = "",
    district: str = "",
    business_district: str = "",
) -> dict:
    """把详细地址拆成 城市 / 区县 / 详细地址，并标注来源。

    来源优先级：detail（详情接口的完整地址）> list（城市+区+商圈拼出来）> none。
    """
    raw = normalize_text(address)
    city = normalize_text(city)
    district = normalize_text(district)
    business_district = normalize_text(business_district)

    if not raw:
        if district or business_district:
            full = f"{city}{district}{business_district}"
            return {
                "full": full,
                "city": city,
                "district": district,
                "business_district": business_district,
                "detail": "",
                "source": "list",
            }
        return {
            "full": city,
            "city": city,
            "district": "",
            "business_district": "",
            "detail": "",
            "source": "none" if not city else "city-only",
        }

    text = raw
    # 去掉开头的城市名，避免 "成都成都锦江区…" 这类重复
    if city and text.startswith(city):
        text = text[len(city):]

    parsed_district = district
    detail = text
    match = _DISTRICT_RE.search(text)
    if match:
        # 详情地址权威：地址里能解析出区县时以它为准
        parsed_district = match.group(1)
        index = match.start()
        detail = (text[:index] + text[index + len(match.group(1)):]).strip()

    detail = normalize_text(detail)
    if parsed_district and detail.startswith(parsed_district):
        detail = normalize_text(detail[len(parsed_district):])

    # 详情地址只给了城市（"成都"）时，退化为「城市+区+商圈」的派生地址
    if not detail and not match and city:
        derived = f"{city}{parsed_district}{business_district}"
        if len(derived) > len(raw):
            return {
                "full": derived,
                "city": city,
                "district": parsed_district,
                "business_district": business_district,
                "detail": "",
                "source": "list",
            }

    return {
        # full 保持源串（只折叠整段前缀重复与尾部城市名），detail 才是清洗后的组件
        "full": strip_trailing_city(collapse_repeat_prefix(raw), city),
        "city": city,
        "district": parsed_district,
        "business_district": business_district,
        "detail": collapse_repeat_tail(collapse_repeat_prefix(detail)),
        "source": "detail",
    }


def salary_unit(salary: str | None) -> str:
    """判断薪资单位：日薪/时薪/月薪。不做换算，只标注。"""
    text = normalize_text(salary)
    if not text:
        return ""
    if "元/天" in text or "/天" in text:
        return "day"
    if "元/时" in text or "/时" in text or "元/小时" in text:
        return "hour"
    return "month"


