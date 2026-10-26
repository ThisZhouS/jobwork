"""记录级清洗：字段归一 + JD 结构化 + 公司聚合 + 质量报告。

``clean_record`` 是唯一入口，输出既包含原始字段（已归一），也包含
``structure_jd`` 产出的结构化字段，因此下游（导出、入库、向量化）只需读一个 dict。
"""

from __future__ import annotations

from .jd import structure_jd
from .text import (
    clean_company,
    extract_legal_name,
    normalize_text,
    parse_address,
    salary_unit,
)

def clean_record(record: dict, *, source_file: str = "") -> dict:
    """单条记录 -> 结构化记录（company / workplace 两个重点块）。

    注意：`legal_name` 取自公司介绍（company_intro），对脱敏岗位来说可能是
    用人方/客户名（例如介绍是华为），不一定是签约主体，因此与 `is_anonymous`
    一起看。
    """
    company = clean_company(record.get("company"))
    legal = extract_legal_name(
        record.get("company_intro") or record.get("intro"), company["name"]
    )

    workplace = parse_address(
        record.get("address"),
        city=record.get("city", ""),
        district=record.get("district", ""),
        business_district=record.get("business_district", ""),
    )

    skills = [str(s) for s in (record.get("skills") or record.get("skills_detail") or [])]
    welfare = [str(w) for w in (record.get("welfare") or [])]
    description = normalize_text(record.get("description"))
    jd = structure_jd(
        description,
        title=normalize_text(record.get("title")),
        skills=skills,
        welfare=welfare,
        degree=normalize_text(record.get("degree")),
        experience=normalize_text(record.get("experience")),
    )

    return {
        "job_id": record.get("job_id") or "",
        "title": normalize_text(record.get("title")),
        "salary": normalize_text(record.get("salary")),
        "salary_min": record.get("salary_min"),
        "salary_max": record.get("salary_max"),
        "salary_unit": salary_unit(record.get("salary")),
        "experience": normalize_text(record.get("experience")),
        "degree": normalize_text(record.get("degree")),
        "company": {
            "name": company["name"],
            "legal_name": legal,
            "raw": company["raw"],
            "key": company["key"],
            "is_anonymous": company["is_anonymous"],
            "is_truncated": company["is_truncated"],
            "industry": normalize_text(record.get("industry")),
            "industry_code": record.get("industry_code"),
            "scale": normalize_text(record.get("scale")),
            "stage": normalize_text(record.get("stage")),
            "intro": normalize_text(record.get("company_intro")),
        },
        "workplace": workplace,
        "skills": skills,
        "welfare": welfare,
        "description": description,
        # ---- JD 结构化字段 ----
        "has_jd": jd["has_jd"],
        "jd_length": jd["jd_length"],
        "jd": jd,
        "responsibilities": jd["responsibilities"],
        "requirements": jd["requirements"],
        "skills_all": jd["skills"],
        "jd_benefits": jd["benefits"],
        "min_years": jd["min_years"],
        "max_years": jd["max_years"],
        "degree_required": jd["degree_required"],
        "hiring_count": jd["hiring_count"],
        "work_schedule": jd["work_schedule"],
        "seniority": jd["seniority"],
        "url": record.get("url") or "",
        "source_file": source_file,
    }


def build_companies(jobs: list[dict]) -> list[dict]:
    """按公司聚合：岗位数、地址集合、薪资范围、行业。**

    脱敏公司（"某大型互联网公司"）保留原样，但用 is_anonymous 标出来，
    不要把它们当成同一家公司去合并不同企业。
    """
    groups: dict[str, dict] = {}
    for job in jobs:
        info = job["company"]
        key = str(info["key"] or job.get("job_id") or job.get("title") or "")
        group = groups.get(key)
        if group is None:
            group = {
                "key": key,
                "company_name": info["name"],
                "legal_name": info.get("legal_name", ""),
                "is_anonymous": info.get("is_anonymous", False),
                "is_truncated": info.get("is_truncated", False),
                "industry": info.get("industry", ""),
                "industry_code": info.get("industry_code"),
                "scale": info.get("scale", ""),
                "stage": info.get("stage", ""),
                "job_count": 0,
                "cities": [],
                "addresses": [],
                "address_sources": set(),
                "salary_unit": "month",
                "salary_min": None,
                "salary_max": None,
                "sample_titles": [],
            }
            groups[key] = group

        group["job_count"] += 1
        for field, bucket in (("city", "cities"), ("full", "addresses")):
            value = job["workplace"].get(field)
            if value and value not in group[bucket]:
                group[bucket].append(value)
        source = job["workplace"].get("source")
        if job["workplace"].get("full") and source:
            group["address_sources"].add(source)

        # 日薪/时薪和月薪不能混在一个区间里，只聚合月薪
        if job.get("salary_unit") == "month":
            low, high = job.get("salary_min"), job.get("salary_max")
            if low is not None:
                group["salary_min"] = low if group["salary_min"] is None else min(group["salary_min"], low)
            if high is not None:
                group["salary_max"] = high if group["salary_max"] is None else max(group["salary_max"], high)

        title = job.get("title") or ""
        if title and title not in group["sample_titles"] and len(group["sample_titles"]) < 5:
            group["sample_titles"].append(title)

    companies = sorted(groups.values(), key=lambda g: (-g["job_count"], g["company_name"]))
    for company in companies:
        sources = company.pop("address_sources")
        # detail 最可信；只有派生地址时明确标出来，不把「城市+商圈」当完整地址
        company["address_source"] = "detail" if "detail" in sources else (
            "list" if "list" in sources else ""
        )
    return companies


def build_report(jobs: list[dict], companies: list[dict]) -> dict:
    total = len(jobs)
    with_address = sum(1 for j in jobs if j["workplace"]["source"] == "detail")
    derived = sum(1 for j in jobs if j["workplace"]["source"] == "list")
    missing = sum(1 for j in jobs if j["workplace"]["source"] in {"none", "city-only"})
    all_skills = {s for j in jobs for s in (j.get("skills_all") or [])}
    return {
        "jobs": total,
        "companies": len(companies),
        "address_detail": with_address,
        "address_derived": derived,
        "address_missing": missing,
        "anonymous_companies": sum(1 for c in companies if c["is_anonymous"]),
        "truncated_companies": sum(1 for c in companies if c["is_truncated"]),
        "legal_name_recovered": sum(
            1 for c in companies if c["legal_name"] and c["legal_name"] != c["company_name"]
        ),
        # ---- JD 结构化质量 ----
        "with_jd": sum(1 for j in jobs if j.get("has_jd")),
        "with_duties": sum(1 for j in jobs if j.get("responsibilities")),
        "with_requirements": sum(1 for j in jobs if j.get("requirements")),
        "with_years": sum(1 for j in jobs if j.get("min_years") is not None),
        "with_schedule": sum(1 for j in jobs if j.get("work_schedule")),
        "with_seniority": sum(1 for j in jobs if j.get("seniority")),
        "skill_total": len(all_skills),
        "skill_links": sum(len(set(j.get("skills_all") or [])) for j in jobs),
        "benefit_total": len({b for j in jobs for b in (j.get("jd_benefits") or [])}),
        "duty_total": sum(len(j.get("responsibilities") or []) for j in jobs),
        "requirement_total": sum(len(j.get("requirements") or []) for j in jobs),
    }
