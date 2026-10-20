"""字段抽取：从 JD 文本里取年限、学历、招聘人数、工时、福利、资深度。

都是正则 + 词表，输入原文、输出标量（缺失返回 ``None`` / ``""``），不猜、不补。
抽不到就是源数据没写，保持缺失比编一个更可信。
"""

import re

from .jd_sections import _dedupe

_YEARS_RANGE = re.compile(r"(\d{1,2})\s*[-~至到—–]\s*(\d{1,2})\s*年")
_YEARS_MIN = re.compile(r"(\d{1,2})\s*年(?:以上|及以上|\+)")
_YEARS_EXP = re.compile(r"(\d{1,2})\s*年(?:以上)?(?:的)?(?:相关)?(?:工作)?经验")
_NO_YEARS = [
    "经验不限", "无经验", "接受无经验", "0经验", "不限经验", "应届",
    "有无经验均可", "有无相关工作经验均可", "无需经验", "经验要求不限",
]

_DEGREE_WORDS = ["博士", "硕士", "本科", "大专", "中专", "高中", "初中"]
_DEGREE_RE = re.compile(r"(博士|硕士|统招本科|本科|大专|专科|中专|高中|初中)(?:及)?(?:以上)?")
_HIRING_RE = re.compile(r"招\s*(\d{1,3})\s*人")
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?\s*%)")

_SCHEDULE_RULES = [
    ("双休", ["周末双休", "双休"]),
    ("大小周", ["大小周"]),
    ("单休", ["单休"]),
    ("996", ["996"]),
    ("弹性工作", ["弹性工作", "弹性上下班", "弹性打卡"]),
    ("排班/倒班", ["排班", "倒班", "轮班"]),
    ("朝九晚六", ["朝九晚六", "9:00-18:00", "9-6"]),
]

_BENEFIT_WORDS = [
    "五险一金", "六险一金", "七险一金", "公积金", "补充医疗保险", "商业保险",
    "年终奖", "年终奖金", "年底双薪", "十三薪", "13薪", "14薪", "15薪",
    "带薪年假", "带薪病假", "双休", "弹性工作", "免费班车", "班车",
    "餐补", "餐饮补贴", "包吃", "包住", "房补", "住房补贴", "交通补助", "交通补贴",
    "通讯补贴", "话补", "高温补贴", "节日福利", "节日礼品", "生日福利", "团建",
    "定期体检", "年度体检", "股票期权", "期权", "股权激励", "培训", "导师带教",
    "不加班", "零食下午茶", "下午茶", "员工旅游", "出国游",
]

# 技能词典：命中的词直接当结构化技能；API 自带的 skills 字段也会并入


_SENIORITY_RULES = [
    ("实习", ["实习", "实习生"]),
    ("应届", ["应届", "校招", "管培"]),
    ("总监", ["总监", "VP", "副总"]),
    ("经理", ["经理", "主管", "负责人", "Leader", "leader"]),
    ("专家/架构", ["专家", "架构师", "Principal"]),
    ("资深/高级", ["资深", "高级", "Senior", "senior"]),
    ("初级", ["初级", "助理", "Junior", "junior"]),
]


def extract_years(text: str) -> tuple[int | None, int | None, str]:
    """返回 (最小年限, 最大年限, 命中文本)。"""
    for word in _NO_YEARS:
        if word in text:
            return 0, None, word
    match = _YEARS_RANGE.search(text)
    if match:
        return int(match.group(1)), int(match.group(2)), match.group(0)
    match = _YEARS_MIN.search(text) or _YEARS_EXP.search(text)
    if match:
        return int(match.group(1)), None, match.group(0)
    return None, None, ""


def extract_degree(text: str) -> str:
    match = _DEGREE_RE.search(text)
    if not match:
        return ""
    word = match.group(1)
    return "大专" if word in {"专科"} else word


def extract_hiring_count(text: str) -> int | None:
    match = _HIRING_RE.search(text)
    return int(match.group(1)) if match else None


def extract_schedule(text: str) -> str:
    for label, words in _SCHEDULE_RULES:
        if any(word in text for word in words):
            return label
    return ""


_BENEFIT_ALIASES = {
    "周末双休": "双休",
    "双休日": "双休",
    "五险": "五险一金",
    "带薪休假": "带薪年假",
    "年底双薪": "十三薪",
}


def extract_benefits(text: str, welfare: list[str] | None = None) -> list[str]:
    hits = [word for word in _BENEFIT_WORDS if word in text]
    for word in welfare or []:
        word = str(word or "").strip()
        word = _BENEFIT_ALIASES.get(word, word)
        if word and word not in hits:
            hits.append(word)
    return _dedupe(hits)


def extract_seniority(title: str) -> str:
    for label, words in _SENIORITY_RULES:
        if any(word in title for word in words):
            return label
    return ""
