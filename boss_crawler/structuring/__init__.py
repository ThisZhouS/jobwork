"""结构化层：把平台返回的原始数据变成可查询的结构化数据。

两个子域，都是**纯函数、无 IO**，可以独立测试：

* :mod:`boss_crawler.structuring.jd` —— 分节、切条目、抽年限/学历/工时/福利/
  招聘人数/资深度、技能抽取与规范化；
* :mod:`boss_crawler.structuring.text` —— 公司名规范化、地址拆解、薪资单位；
* :mod:`boss_crawler.structuring.cleaning` —— ``clean_record`` 入口、公司聚合、质量报告。

跨包调用请只用本门面，不要深入内部模块。
"""
from .cleaning import build_companies, build_report, clean_record
from .jd import (
    extract_benefits,
    extract_degree,
    extract_hiring_count,
    extract_schedule,
    extract_seniority,
    extract_skills,
    extract_years,
    normalize_skills,
    skill_category,
    split_sections,
    structure_jd,
)
from .text import (
    clean_company,
    collapse_repeat_prefix,
    collapse_repeat_tail,
    extract_legal_name,
    normalize_text,
    parse_address,
    salary_unit,
    strip_trailing_city,
)

__all__ = [
    # JD 结构化
    "structure_jd",
    "split_sections",
    "extract_years",
    "extract_degree",
    "extract_hiring_count",
    "extract_schedule",
    "extract_benefits",
    "extract_skills",
    "extract_seniority",
    "normalize_skills",
    "skill_category",
    # 文本与地址
    "normalize_text",
    "clean_company",
    "extract_legal_name",
    "parse_address",
    "salary_unit",
    "collapse_repeat_prefix",
    "collapse_repeat_tail",
    "strip_trailing_city",
    # 记录级清洗
    "clean_record",
    "build_companies",
    "build_report",
]
