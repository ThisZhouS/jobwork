"""前端取数层：把"页面需要什么"翻译成 SQL，CLI 只负责打印。

和 :mod:`boss_crawler.store.app_store` 的分工：

* ``app_store`` 管**写**（流水线落库）与通用读；
* 这里管**读的视图**——一个函数对应前端一块内容，返回可直接渲染的 JSON。

前端因此不需要拼 SQL、也不需要知道证据存在哪张表。
"""
from __future__ import annotations

from typing import Any

from ..store.app_store import AppStore


# ---------------------------------------------------------------- 筛选条件
def filter_options() -> dict[str, Any]:
    """BOSS 的筛选条件原样映射给前端下拉框。

    ``value`` 是提交给 ``app run`` 的值（中文名或数字码都收），
    ``label`` 是展示文案。**不自己发明字段**——前端下拉框的选项就是爬虫认的选项。
    """
    from ..filters import FILTERS

    out: dict[str, Any] = {"fields": []}
    for field, (label, mapping) in FILTERS.items():
        out["fields"].append({
            "field": field,
            "label": label,
            "options": [{"value": name, "label": name, "code": code}
                        for name, code in mapping.items()],
        })
    out["text"] = [
        {"field": "query", "label": "搜索关键词", "required": True, "example": "Python"},
        {"field": "pages", "label": "抓取页数", "type": "number", "note": "每页 30 条"},
    ]
    out["toggles"] = [
        {"field": "platforms", "label": "背调平台",
         "options": ["tianyancha", "tianyan_ai", "zhihu", "weibo", "tieba"]},
        {"field": "enable_company_score", "label": "公司打分"},
        {"field": "enable_job_fit", "label": "岗位适配度"},
        {"field": "enable_resume", "label": "定向简历"},
    ]
    return out


# ---------------------------------------------------------------- 技能词云
def skill_cloud(store: AppStore, *, limit: int = 200,
                company_key: str | None = None, city: str | None = None) -> dict:
    """岗位技能词云：同一技能出现越多，词越大。

    统计口径是"出现在多少个岗位里"，不是"出现多少次"——一个岗位重复写
    "Python" 三次不该比三个岗位各写一次更大。
    """
    sql = """
        SELECT skill AS name, count(DISTINCT job_id) AS count
        FROM jobs, unnest(skills) AS skill
        WHERE skill IS NOT NULL AND skill <> ''
    """
    params: list[Any] = []
    if company_key:
        sql += " AND company_key = %s"
        params.append(company_key)
    if city:
        sql += " AND city = %s"
        params.append(city)
    sql += " GROUP BY skill ORDER BY count DESC, name LIMIT %s"
    params.append(limit)

    with store.db.cursor() as cur:
        cur.execute(sql, params)
        rows = [{"name": row["name"], "count": int(row["count"])} for row in cur.fetchall()]

    total = sum(row["count"] for row in rows) or 1
    for row in rows:
        # 前端可以直接拿 weight 决定字号，不必自己算比例
        row["weight"] = round(row["count"] / total, 4)
    return {"skills": rows, "total": sum(row["count"] for row in rows)}


# ---------------------------------------------------------------- 公司详情
def company_detail(store: AppStore, company_key: str) -> dict:
    """公司详情页：基本信息、风险、评价、在招岗位、维度、劳务派遣。"""
    score = next((row for row in store.latest_company_scores(limit=500)
                  if row["company_key"] == company_key), None)
    raw = store.get_raw(company_key, "tianyancha_web") or {}
    if not isinstance(raw, dict):
        raw = {}
    profile = raw.get("profile") or {}
    counts = raw.get("counts") or {}
    risks = raw.get("risks") or []

    evidence = store.evidence_for(company_key, limit=200)
    by_source: dict[str, list[dict]] = {}
    for row in evidence:
        by_source.setdefault(str(row.get("agent") or row.get("source") or "未知"), []).append({
            "title": row.get("title"), "url": row.get("url"),
            "snippet": row.get("snippet"), "sentiment": row.get("sentiment"),
            "published_at": row.get("published_at"),
        })

    with store.db.cursor() as cur:
        cur.execute(
            """SELECT job_id, title, salary, city, district, experience, degree,
                      industry, skills, welfare, url
               FROM jobs WHERE company_key = %s ORDER BY job_id LIMIT 50""",
            (company_key,),
        )
        jobs = [dict(row) for row in cur.fetchall()]
        cur.execute("SELECT company_name FROM jobs WHERE company_key = %s LIMIT 1",
                    (company_key,))
        name_row = cur.fetchone()

    return {
        "company_key": company_key,
        "name": (name_row or {}).get("company_name") or profile.get("name") or company_key,
        "basic": {
            "reg_status": profile.get("reg_status"),
            "reg_capital": profile.get("reg_capital"),
            "estiblish_time": profile.get("estiblish_time"),
            "legal_person": profile.get("legal_person_name"),
            "reg_location": profile.get("reg_location"),
            "staff_num": profile.get("staff_num"),
            "industry": profile.get("industry"),
            "business_scope": profile.get("business_scope"),
            "credit_code": profile.get("credit_code"),
            # 天眼查原始数据：前端要看什么自己取，这里不全量展开
            "raw_available": bool(raw),
        },
        "risk": {
            "counts": counts,
            "items": risks[:50],
            "evidence_negative": sum(1 for row in evidence if (row.get("sentiment") or 0) < 0),
        },
        "reviews": by_source,
        "jobs": jobs,
        "score": None if not score else {
            "total": score["total"], "grade": score["grade"],
            "verdict": score["verdict"],
            "dimensions": [{"name": d["name"], "score": d["score"],
                            "weight": d.get("weight"), "reason": d.get("reason")}
                           for d in (score["dimensions"] or [])],
            "advice": score["advice"],
            "at": score["created_at"],
        },
        "labor_dispatch": {
            "is_labor_dispatch": score.get("is_labor_dispatch") if score else None,
            "reason": score.get("labor_dispatch_reason") if score else None,
            "evidence": score.get("labor_dispatch_evidence") if score else None,
        },
    }


# ---------------------------------------------------------------- 岗位详情
def job_detail(store: AppStore, job_id: str) -> dict | None:
    """岗位详情页：岗位信息、信息来源、跳转链接、招聘公司。"""
    with store.db.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
        row = cur.fetchone()
    if row is None:
        return None
    job = dict(row)

    fit = next((item for item in store.latest_job_fits(limit=500)
                if item["job_id"] == job_id), None)
    score = None
    if job.get("company_key"):
        score = next((item for item in store.latest_company_scores(limit=500)
                      if item["company_key"] == job["company_key"]), None)

    return {
        "id": job["job_id"],
        "title": job["title"],
        # 岗位信息
        "salary": job.get("salary"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "experience": job.get("experience"),
        "degree": job.get("degree"),
        "city": job.get("city"),
        "district": job.get("district"),
        "industry": job.get("industry"),
        "skills": job.get("skills") or [],
        "welfare": job.get("welfare") or [],
        "description": job.get("description"),
        # 来源与跳转
        "source": {"name": "BOSS直聘", "url": job.get("url"),
                   "job_id": job["job_id"]},
        # 招聘公司
        "company": {
            "company_key": job.get("company_key"),
            "name": job.get("company_name"),
            "legal_name": job.get("legal_name"),
            "score": None if not score else {
                "total": score["total"], "grade": score["grade"],
                "is_labor_dispatch": score.get("is_labor_dispatch"),
                "dimensions": {d["name"]: d["score"] for d in (score["dimensions"] or [])},
            },
        },
        "fit": None if not fit else {
            "total": fit["total"], "grade": fit["grade"], "verdict": fit["verdict"],
            "dimensions": {d["name"]: d["score"] for d in (fit["dimensions"] or [])},
            "advice": fit["advice"],
        },
    }


# ---------------------------------------------------------------- 折线图
def score_series(store: AppStore, company_key: str, *, field: str | None = None) -> dict:
    """某公司某个字段的历史折线。

    ``field`` 为 ``None`` 时返回总分的序列；也可以传维度名（风险/待遇/…），
    这样前端"点某个字段看折线"就有了数据。
    """
    rows = store.company_score_series(company_key)
    if field and field != "total":
        points = [{"at": row["at"], "value": row.get(field)} for row in rows]
    else:
        points = [{"at": row["at"], "value": row["total"]} for row in rows]
    return {"company_key": company_key, "field": field or "total", "points": points}
