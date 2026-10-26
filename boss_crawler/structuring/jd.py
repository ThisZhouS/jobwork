"""JD 结构化门面：把一段 JD 变成结构化字典。

三个子模块分别负责「切结构」「抽字段」「认技能」，本模块只做编排：

    structure_jd(text, title=..., welfare=...)
        -> {sections, responsibilities, requirements, skills, benefits,
            min_years, max_years, degree_required, hiring_count,
            work_schedule, seniority, ...}

对外只需要 ``structure_jd``，其余函数导出来是为了单测。
"""

import re

from .jd_extract import (
    _BENEFIT_WORDS,
    _PERCENT,
    extract_benefits,
    extract_degree,
    extract_hiring_count,
    extract_schedule,
    extract_seniority,
    extract_years,
)
from .jd_sections import (
    _dedupe,
    _looks_like_duty,
    _split_banner,
    _split_items,
    split_sections,
)
from .jd_skills import extract_skills, normalize_skills

def structure_jd(
    description: str | None,
    *,
    title: str = "",
    skills: list[str] | None = None,
    welfare: list[str] | None = None,
    degree: str = "",
    experience: str = "",
) -> dict:
    """JD 文本 -> 结构化字段。抽不到的留空/None，不猜测。"""
    text = (description or "").strip()
    preamble, sections = split_sections(text) if text else ("", {})

    responsibilities = sections.get("responsibilities", [])
    requirements = sections.get("requirements", [])
    bonus = sections.get("bonus", [])
    benefits_from_text = sections.get("benefits", [])
    company = sections.get("company", [])
    location = sections.get("location", [])
    schedule = sections.get("schedule", [])

    # 第一个小标题之前的正文，通常就是「职责」——很多 JD 直接以 "1、负责…" 开头，
    # 标题（常见是「任职要求」）出现在后面；这段不能丢。
    preamble_items = _split_items(preamble) if preamble.strip() else []
    numbered = bool(re.match(r"\s*(?:\d{1,2}\s*[、.．)）]|[①-⑳])", preamble.strip()))
    duty_like = [item for item in preamble_items if _looks_like_duty(item)]
    # 编号列表（1、2、3、）出现在首个标题之前时，整段就是职责，不再逐条筛
    take_all = numbered or len(duty_like) * 2 >= len(preamble_items)
    if take_all and preamble_items:
        responsibilities = preamble_items + responsibilities
    elif duty_like:
        responsibilities = duty_like + responsibilities
        rest = [item for item in preamble_items if item not in duty_like]
        if rest:
            # 标题前的非职责正文（如「工作周期:长期兼职」）不能丢，归入 other
            sections.setdefault("other", []).extend(rest)

    # 没有小标题时：整段当职责（很多 JD 就是一整段编号文本）
    if not responsibilities and not requirements:
        responsibilities = _split_items(text)

    # 职责里若混入「地点:… 薪资:…」这类元数据行，挪到 other 保留，不当作职责
    responsibilities, banner_items = _split_banner(responsibilities)
    if banner_items:
        sections.setdefault("other", []).extend(banner_items)

    min_years, max_years, years_text = extract_years(text)
    if min_years is None and not text:
        min_years, max_years, years_text = (None, None, "")

    joined = text
    benefits = extract_benefits(joined, welfare) if text else list(welfare or [])
    for item in benefits_from_text:
        for word in _BENEFIT_WORDS:
            if word in item and word not in benefits:
                benefits.append(word)

    return {
        "has_jd": bool(text),
        "jd_length": len(text),
        "sections": {
            "responsibilities": responsibilities,
            "requirements": requirements,
            "bonus": bonus,
            "benefits": benefits_from_text,
            "company": company[:5],
            "location": location[:3],
            "schedule": schedule[:3],
            "other": sections.get("other", [])[:10],
        },
        "responsibilities": responsibilities,
        "requirements": requirements,
        "skills": extract_skills(text, normalize_skills(skills)),
        "benefits": benefits,
        "min_years": min_years,
        "max_years": max_years,
        "years_text": years_text,
        "degree_required": extract_degree(text) or (degree or ""),
        "hiring_count": extract_hiring_count(text),
        "work_schedule": extract_schedule(text),
        "seniority": extract_seniority(title),
        "experience_field": experience,
        "percent_mentions": _dedupe(_PERCENT.findall(text)),
    }
