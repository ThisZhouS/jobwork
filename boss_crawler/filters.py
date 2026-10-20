"""职位筛选参数：界面文案 <-> 接口数字码。

BOSS直聘 的筛选档位是固定枚举（薪资/经验/学历），公司行业则是数字行业码。
用户既可以传中文档位（"20-50K"/"3-5年"/"本科"/"计算机软件"），也可以直接传码。
"""
from __future__ import annotations

from . import config
from .industry_codes import INDUSTRY_CODES

# key 与接口查询参数同名
FILTERS: dict[str, tuple[str, dict[str, str]]] = {
    "salary": ("薪资待遇", config.SALARY_CODES),
    "experience": ("工作经验", config.EXPERIENCE_CODES),
    "degree": ("学历要求", config.DEGREE_CODES),
    "industry": ("公司行业", INDUSTRY_CODES),
}

_IGNORED = {"", "不限", "全部", "任意", "all", "any"}


def _norm(text: str) -> str:
    return (
        str(text)
        .strip()
        .replace(" ", "")
        .replace("－", "-")
        .replace("—", "-")
        .replace("~", "-")
        .upper()
    )


def resolve_code(field: str, value: str | None) -> str | None:
    """把用户输入解析成接口码；None / 不限 表示不筛。"""
    if field not in FILTERS:
        raise KeyError(f"未知筛选字段：{field}")
    label, mapping = FILTERS[field]
    if value is None:
        return None
    raw = str(value).strip()
    if _norm(raw) in {_norm(x) for x in _IGNORED}:
        return None
    if raw.isdigit():
        return raw

    wanted = _norm(raw)
    for name, code in mapping.items():
        if _norm(name) == wanted:
            return code

    options = "、".join(mapping)
    raise ValueError(f"{label}「{value}」无法识别，可选：{options}（也可直接传数字码）")


def resolve_filters(
    *,
    salary: str | None = None,
    experience: str | None = None,
    degree: str | None = None,
    industry: str | None = None,
) -> dict[str, str]:
    raw = {"salary": salary, "experience": experience, "degree": degree, "industry": industry}
    out: dict[str, str] = {}
    for field, value in raw.items():
        code = resolve_code(field, value)
        if code:
            out[field] = code
    return out


def describe(filters: dict[str, str]) -> str:
    """把解析后的码翻回可读文案，用于日志。"""
    if not filters:
        return "无"
    parts = []
    for field, code in filters.items():
        label, mapping = FILTERS[field]
        name = next((k for k, v in mapping.items() if v == code), code)
        parts.append(f"{label}={name}({code})")
    return " ".join(parts)
