"""把天眼查 1001（工商全景）的返回拆成「档案 + 关系 + 风险」。

纯函数、不联网，便于回归测试。三个入口：

* :func:`parse_profile` —— 工商档案（名称、法人、注册资本、参保、联系方式…）
* :func:`parse_relations` —— 母公司 / 子公司 / 分支三条边，子公司按持股比例分级
* :func:`parse_risks` —— 1001 自带的风险清单（经营异常、严重违法、行政处罚）

注意概念区分：

* ``headquarters`` 是**总公司**（工商登记上的隶属关系，通常即母公司）；
* ``investList`` 是**对外投资**，不等于子公司：可能是 5% 的财务投资。
  按 ``percent`` 分级：``100%`` 全资、``>50%`` 控股（真子公司）、``<=50%`` 参股；
* ``branchList`` 是**分支机构**（分公司），不是独立法人，不能当子公司看。
"""
from __future__ import annotations

import re
from typing import Any

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)")


def to_percent(value: Any) -> float | None:
    """把 ``"100%"``/``"51.5%"``/``51.5`` 统一成浮点百分比。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _PERCENT_RE.search(str(value))
    return float(match.group(1)) if match else None


def classify_invest(percent: float | None) -> str:
    """按持股比例给对外投资分级。"""
    if percent is None:
        return "参与投资(比例未知)"
    if percent >= 99.99:
        return "全资子公司"
    if percent > 50:
        return "控股子公司"
    if percent >= 20:
        return "参股公司"
    return "财务投资"


def parse_profile(result: dict[str, Any]) -> dict[str, Any]:
    """从 1001 的 ``result`` 里取工商档案字段。"""
    base = result.get("base") or {}
    return {
        "tyc_id": result.get("id") or base.get("id"),
        "name": result.get("name") or base.get("name"),
        "credit_code": result.get("creditCode"),
        "legal_person": result.get("legalPersonName"),
        "reg_status": result.get("regStatus"),
        "reg_capital": result.get("regCapital"),
        "estiblish_time": result.get("estiblishTime"),
        "reg_location": result.get("regLocation"),
        "industry": result.get("industry"),
        "business_scope": result.get("businessScope"),
        "phone": result.get("phoneNumber"),
        "email": result.get("email"),
        "website": result.get("website"),
        "staff_num": result.get("staffNum") or base.get("staffNum"),
        "company_org_type": result.get("companyOrgType"),
    }


def parse_relations(result: dict[str, Any], *, from_key: str) -> list[dict[str, Any]]:
    """抽出母公司、子公司、分支三条边，返回待落库的行。"""
    rows: list[dict[str, Any]] = []

    parent = result.get("headquarters")
    if parent and parent.get("name"):
        rows.append(
            {
                "from_key": from_key,
                "relation": "parent",
                "to_tyc_id": parent.get("id"),
                "to_name": parent.get("name"),
                "to_credit_code": None,
                "percent": None,
                "to_reg_status": parent.get("reg_status"),
                "grade": "总公司",
            }
        )

    for item in result.get("investList") or []:
        percent = to_percent(item.get("percent"))
        rows.append(
            {
                "from_key": from_key,
                "relation": "subsidiary",
                "to_tyc_id": item.get("id"),
                "to_name": item.get("name"),
                "to_credit_code": item.get("creditCode"),
                "percent": percent,
                "to_reg_status": item.get("regStatus"),
                "grade": classify_invest(percent),
            }
        )

    for item in result.get("branchList") or []:
        rows.append(
            {
                "from_key": from_key,
                "relation": "branch",
                "to_tyc_id": item.get("id"),
                "to_name": item.get("name"),
                "to_credit_code": None,
                "percent": None,
                "to_reg_status": item.get("regStatus"),
                "grade": "分支机构",
            }
        )
    return rows


def parse_risks(result: dict[str, Any], *, entity_key: str, entity_name: str) -> list[dict[str, Any]]:
    """把 1001 自带的三类风险清单标准化。"""
    rows: list[dict[str, Any]] = []

    for item in result.get("abnormalList") or []:
        rows.append(
            {
                "entity_key": entity_key,
                "entity_name": entity_name,
                "risk_type": "abnormal",
                "occurred_at": item.get("putDate"),
                "department": item.get("putDepartment"),
                "reason": item.get("putReason"),
                "removed_at": item.get("removeDate"),
                "detail": item,
            }
        )

    for item in result.get("illegalList") or []:
        rows.append(
            {
                "entity_key": entity_key,
                "entity_name": entity_name,
                "risk_type": "illegal",
                "occurred_at": item.get("putDate"),
                "department": item.get("putDepartment"),
                "reason": item.get("putReason"),
                "removed_at": item.get("removeDate"),
                "detail": item,
            }
        )

    for item in result.get("punishList") or []:
        rows.append(
            {
                "entity_key": entity_key,
                "entity_name": entity_name,
                "risk_type": "punish",
                "occurred_at": item.get("decisionDate"),
                "department": item.get("departmentName"),
                "reason": item.get("reason") or item.get("content"),
                "removed_at": None,
                "detail": item,
            }
        )
    return rows


def parse_dishonest(result: dict[str, Any], *, entity_key: str, entity_name: str) -> list[dict[str, Any]]:
    """843 失信人 -> 风险行。"""
    rows = []
    for item in result.get("items") or []:
        rows.append(
            {
                "entity_key": entity_key,
                "entity_name": entity_name,
                "risk_type": "dishonest",
                "occurred_at": item.get("regdate") or item.get("publishdate"),
                "department": item.get("courtname") or item.get("gistunit"),
                "reason": item.get("duty") or item.get("disrupttypename"),
                "removed_at": None,
                "detail": item,
            }
        )
    return rows


def parse_zhixing(result: dict[str, Any], *, entity_key: str, entity_name: str) -> list[dict[str, Any]]:
    """839 被执行人 -> 风险行。"""
    rows = []
    for item in result.get("items") or []:
        rows.append(
            {
                "entity_key": entity_key,
                "entity_name": entity_name,
                "risk_type": "zhixing",
                "occurred_at": item.get("caseCreateTime"),
                "department": item.get("execCourtName"),
                "reason": f"执行标的 {item.get('execMoney')}" if item.get("execMoney") else None,
                "removed_at": None,
                "detail": item,
            }
        )
    return rows


def risk_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    """按类型计数，用于一句话结论。"""
    summary: dict[str, int] = {}
    for row in rows:
        summary[row["risk_type"]] = summary.get(row["risk_type"], 0) + 1
    return summary


def verdict(summary: dict[str, int]) -> str:
    """把风险计数翻译成投递建议（规则可解释、可调整）。"""
    if summary.get("dishonest") or summary.get("zhixing"):
        return "高危：有失信/被执行记录"
    if summary.get("illegal") or summary.get("abnormal"):
        return "警惕：严重违法或经营异常"
    if summary.get("punish"):
        return "关注：有行政处罚"
    return "暂未发现明显风险"
