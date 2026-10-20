"""解析层：把 BOSS直聘 的接口 JSON 归一化成稳定的职位记录。

为什么不用 DOM 解析作为主路径：
  1. 列表页工资数字用了自定义字体（kanzhun-mix）做字形混淆，直接读文本会得到
     一串私用区字符；接口里的 salaryDesc 是明文。
  2. 页面被风控销毁时 DOM 会消失，而接口响应在销毁前已经拿到。
DOM 解析只作为兜底保留。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from scrapling.parser import Selector

JOB_URL = "https://www.zhipin.com/job_detail/{encrypt_id}.html"

_DESC_KEYS = ("postDescription", "jobDescription", "description", "jobDesc", "postDesc")
_ADDR_KEYS = ("address", "jobAddress", "locationName", "addressName")


def deep_find(obj: Any, keys: Iterable[str]) -> str:
    """在嵌套结构里找第一个命中的字符串值。"""
    wanted = tuple(keys)
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, value in cur.items():
                if key in wanted and isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(cur, list):
            stack.extend(x for x in cur if isinstance(x, (dict, list)))
    return ""


def parse_salary(text: str | None) -> tuple[int | None, int | None]:
    """'20-30K·14薪' -> (20000, 30000)；只取月薪区间。"""
    if not text:
        return None, None
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*[Kk千]?", text)
    if not nums:
        return None, None
    base = 1000 if re.search(r"[Kk千]", text) else 1
    values = [float(n) * base for n in nums[:2]]
    if len(values) == 1:
        return int(values[0]), int(values[0])
    return int(min(values)), int(max(values))


def normalize_job(raw: dict) -> dict:
    encrypt_id = raw.get("encryptJobId") or ""
    lo, hi = parse_salary(raw.get("salaryDesc"))
    return {
        "job_id": encrypt_id,
        "security_id": raw.get("securityId") or "",
        "lid": raw.get("lid") or "",
        "title": raw.get("jobName") or "",
        "salary": raw.get("salaryDesc") or "",
        "salary_min": lo,
        "salary_max": hi,
        "city": raw.get("cityName") or "",
        "district": raw.get("areaDistrict") or "",
        "business_district": raw.get("businessDistrict") or "",
        "experience": raw.get("jobExperience") or "",
        "degree": raw.get("jobDegree") or "",
        "labels": list(raw.get("jobLabels") or []),
        "skills": list(raw.get("skills") or []),
        "welfare": list(raw.get("welfareList") or []),
        "company": raw.get("brandName") or "",
        "industry": raw.get("brandIndustry") or "",
        "industry_code": raw.get("industry"),
        "stage": raw.get("brandStageName") or "",
        "scale": raw.get("brandScaleName") or "",
        "boss_name": raw.get("bossName") or "",
        "boss_title": raw.get("bossTitle") or "",
        "boss_online": bool(raw.get("bossOnline")),
        "gps": raw.get("gps") or None,
        "url": JOB_URL.format(encrypt_id=encrypt_id) if encrypt_id else "",
        "source": "joblist_api",
    }


def parse_joblist(payload: dict) -> tuple[list[dict], dict]:
    """返回 (职位列表, 分页信息)。"""
    zp = (payload or {}).get("zpData") or {}
    jobs = [normalize_job(item) for item in (zp.get("jobList") or []) if isinstance(item, dict)]
    meta = {
        "total": zp.get("totalCount"),
        "has_more": bool(zp.get("hasMore")),
        "lid": zp.get("lid") or "",
        "filter": zp.get("filterString") or "",
    }
    return jobs, meta


def parse_detail(payload: dict) -> dict:
    """详情接口结构（v2026-10 实测）：

        zpData.jobInfo     {postDescription, address, showSkills, jobStatusDesc, longitude/latitude}
        zpData.bossInfo    {name, title, activeTimeDesc, bossOnline}
        zpData.brandComInfo{introduce, scaleName, industryName, stageName, labels}

    字段随版本漂移，所以关键值先走精确路径，缺失时用 deep_find 兜底。
    """
    zp = (payload or {}).get("zpData") or {}
    job_info = zp.get("jobInfo") or {}
    boss_info = zp.get("bossInfo") or {}
    brand = zp.get("brandComInfo") or zp.get("brandInfo") or {}
    address = job_info.get("address") or deep_find(job_info, _ADDR_KEYS)
    return {
        "description": job_info.get("postDescription") or deep_find(job_info or zp, _DESC_KEYS),
        "address": address,
        "job_status": job_info.get("jobStatusDesc") or "",
        "skills_detail": list(job_info.get("showSkills") or []) or None,
        "boss_name": boss_info.get("name") or "",
        "boss_title": boss_info.get("title") or "",
        "boss_active_time": boss_info.get("activeTimeDesc") or "",
        "boss_online": boss_info.get("bossOnline"),
        "company_intro": brand.get("introduce") or deep_find(brand, ("brandIntroduction", "introduction")),
        "company_size": brand.get("scaleName") or deep_find(brand, ("brandScaleName",)),
        "company_industry": brand.get("industryName") or deep_find(brand, ("brandIndustry",)),
        "company_stage": brand.get("stageName") or deep_find(brand, ("brandStageName",)),
        "company_labels": list(brand.get("labels") or []) or None,
        "detail_source": "detail_api",
    }


def _first_text(node, selector: str) -> str:
    try:
        found = node.css(selector).first
        return found.get_all_text().strip() if found is not None else ""
    except Exception:
        return ""


def parse_joblist_dom(html: str) -> list[dict]:
    """兜底：接口拿不到时从列表页 DOM 取核心字段（工资字形会被混淆）。"""
    page = Selector(html)
    out: list[dict] = []
    for card in page.css(".job-card-box, .job-card-wrapper"):
        anchor = card.css("a").first
        href = (anchor.attrib.get("href") or "") if anchor is not None else ""
        encrypt_id = ""
        match = re.search(r"/job_detail/([^.]+)\.html", href)
        if match:
            encrypt_id = match.group(1)
        tags = [t.get_all_text().strip() for t in card.css(".tag-list li") if t.get_all_text().strip()]
        out.append({
            "job_id": encrypt_id,
            "title": _first_text(card, ".job-name"),
            "salary": _first_text(card, ".job-salary"),
            "company": _first_text(card, ".company-name"),
            "area": _first_text(card, ".job-area"),
            "tags": tags,
            "url": href if href.startswith("http") else f"https://www.zhipin.com{href}",
            "source": "dom",
        })
    return out
