"""分节：把整段 JD 切成「职责 / 要求 / 福利 / 公司介绍」等区块和条目。

站点返回的 JD 没有结构，只有一段带序号和换行的中文。这里用两层规则还原结构：

1. **定位标题**：先匹配已知小节名（岗位职责、任职要求…），再匹配中文序号标题
   （``一、岗位职责``），最后一层用关键词把 ``二、能力要求`` 这类陌生标题归类；
2. **切条目**：优先按 ``1、`` ``1.`` ``①`` ``•`` 等编号切；没有编号时按换行切；
   再没有就按 ``；`` 兜底（否则整段会变成一条）。

横幅行（``薪资:8k 地址:…``）、水印、纯噪声行会在这一层被识别并挪到 ``other``，
避免混进职责列表。
"""

import re

SECTION_NAMES: list[tuple[str, str]] = [
    ("任职资格要求", "requirements"),
    ("岗位职责描述", "responsibilities"),
    ("工作职责描述", "responsibilities"),
    ("任职资格", "requirements"),
    ("岗位职责", "responsibilities"),
    ("工作职责", "responsibilities"),
    ("职位职责", "responsibilities"),
    ("职责描述", "responsibilities"),
    ("岗位描述", "responsibilities"),
    ("职位描述", "responsibilities"),
    ("工作内容", "responsibilities"),
    ("任职要求", "requirements"),
    ("岗位要求", "requirements"),
    ("职位要求", "requirements"),
    ("技能要求", "requirements"),
    ("任职条件", "requirements"),
    ("岗位需求", "requirements"),
    ("我们需要", "requirements"),
    ("我们希望", "requirements"),
    ("你需要具备", "requirements"),
    ("加分项", "bonus"),
    ("优先条件", "bonus"),
    ("福利待遇", "benefits"),
    ("薪资福利", "benefits"),
    ("公司福利", "benefits"),
    ("薪酬福利", "benefits"),
    ("我们提供", "benefits"),
    ("公司介绍", "company"),
    ("公司简介", "company"),
    ("关于我们", "company"),
    ("团队介绍", "company"),
    ("企业介绍", "company"),
    ("工作地点", "location"),
    ("办公地点", "location"),
    ("工作地址", "location"),
    ("工作时间", "schedule"),
    ("作息时间", "schedule"),
]
"""小标题 -> 归一到哪个区块；长词在前，保证「任职资格要求」不被「任职资格」抢先匹配。"""

BOUNDARY_CHARS = set("。;；:：\n|【】[]（）()、,， \t")

WATERMARKS = [
    "BOSS直聘", "boss直聘", "kanzhun", "来自BOSS直聘", "举报", "微信扫码",
    "扫码查看", "更多职位", "上BOSS直聘", "职位描述", "职位要求",
]

_ITEM_PREFIX = re.compile(
    r"^\s*(?:\d{1,2}\s*[、.．)）]|[①-⑳]|[（(]\s*\d{1,2}\s*[)）]|[•·▪●○◆■*-]\s*)\s*"
)

# 「一、岗位职责」「二、能力要求」这类中文序号标题：标题词不固定，按关键词归类
_ORDINAL_RE = re.compile(r"(?:^|[\s。;；\n|])(?P<ordinal>[一二三四五六七八九十]{1,2})\s*[、.．]\s*(?P<title>[^\n。;；]{2,12})")
_ORDINAL_STOP = re.compile(r"\s*\d{1,2}\s*[、.．)）]|\s{2,}|$")

_SEP_BEFORE = set("\n；;。:：,， 、\t（(")


def _classify_title(title: str) -> str:
    """按关键词把中文标题归到语义区块（支持没见过的新标题）。"""
    rules = [
        ("responsibilities", ("职责", "工作内容", "岗位描述", "职位描述", "工作描述", "负责")),
        ("requirements", ("要求", "资格", "条件", "能力", "技能", "需求", "素质")),
        ("bonus", ("加分", "优先")),
        ("benefits", ("福利", "待遇", "薪酬", "薪资", "保障")),
        ("company", ("公司", "团队", "关于", "企业")),
        ("location", ("地点", "地址", "位置")),
        ("schedule", ("时间", "作息", "班次")),
    ]
    for section, words in rules:
        if any(word in title for word in words):
            return section
    return ""


def _clean_item(text: str) -> str:
    item = _ITEM_PREFIX.sub("", text).strip()
    item = re.sub(r"\s+", " ", item)
    item = item.strip(" 　\t,，;；。.、:：-|")
    for mark in WATERMARKS:
        item = item.replace(mark, "")
    return item.strip()


_BANNER_RE = re.compile(r"(薪资|地址|工作地点|职位编号|岗位编号|招聘人数)\s*[:：]")
_BANNER_HEAD_RE = re.compile(
    r"^\s*(薪资|地址|地点|工作地点|工作地址|工作时间|职位编号|岗位编号|招聘人数|工作周期)\s*[:：]"
)


def _is_noise(item: str) -> bool:
    if len(item) < 2:
        return True
    # 只剩标点/数字的碎片
    if not re.search(r"[\u4e00-\u9fa5A-Za-z]", item):
        return True
    # JD 里夹带的横幅行（"PSIG-网盘-数据开发工程师(J13219) 薪资:8k 地址:成都…"）
    # 判据：带元数据键、且没有句子标点（有标点的是正文，不能丢）
    if _BANNER_RE.search(item) and not re.search(r"[，。；,]", item) and len(item) < 60:
        return True
    return False


def _split_banner(items: list[str]) -> tuple[list[str], list[str]]:
    """把职责里混入的元数据行挑出来（"地点:remote 薪资:30K起 …"）。

    判据：条目**以**元数据键开头（"薪资:"/"地点:"/"工作时间:"…），这种一定是
    岗位横幅或条件说明，不是职责动作。
    """
    kept, moved = [], []
    for item in items:
        if _BANNER_HEAD_RE.match(item):
            moved.append(item)
        else:
            kept.append(item)
    return kept, moved


def _find_headers(text: str) -> list[tuple[int, int, str, str]]:
    """返回 [(start, end, name, section)]，按位置排序。

    两类标题：
      1) 固定词表（岗位职责 / 任职要求 …），短词要求出现在边界处；
      2) 中文序号标题（一、岗位职责 / 二、能力要求 …），按关键词归类。
    """
    found: list[tuple[int, int, str, str]] = []
    claimed: list[tuple[int, int]] = []

    for name, section in SECTION_NAMES:
        for match in re.finditer(re.escape(name), text):
            start, end = match.start(), match.end()
            if any(s <= start < e for s, e in claimed):
                continue
            before = text[start - 1] if start > 0 else "\n"
            after = text[end] if end < len(text) else "\n"
            short = len(name) <= 4
            if short and before not in BOUNDARY_CHARS and after not in BOUNDARY_CHARS | set(":："):
                continue
            claimed.append((start, end))
            found.append((start, end, name, section))

    for match in _ORDINAL_RE.finditer(text):
        title = match.group("title")
        stop = _ORDINAL_STOP.search(title)
        if stop:
            title = title[: stop.start()]
        title = title.strip(" 　:：")
        section = _classify_title(title)
        if not title or not section:
            continue
        start = match.start("ordinal")
        end = match.end("ordinal") + 1 + len(title)
        # 与固定词表命中的标题重叠时，保留固定词表那条
        if any(s <= start < e or s <= end <= e for s, e in claimed):
            continue
        if any(start <= s < end for s, _e in claimed):
            continue
        claimed.append((start, end))
        found.append((start, end, title, section))

    return sorted(set(found))


def split_sections(text: str) -> tuple[str, dict[str, list[str]]]:
    """把 JD 切成 {区块: [条目]}，外加第一个标题之前的开场白。"""
    headers = _find_headers(text)
    sections: dict[str, list[str]] = {}
    if not headers:
        return text, sections

    preamble = text[: headers[0][0]]
    for index, (start, end, _name, section) in enumerate(headers):
        chunk_end = headers[index + 1][0] if index + 1 < len(headers) else len(text)
        chunk = text[end:chunk_end]
        sections.setdefault(section, []).extend(_split_items(chunk))
    return preamble, sections


def _split_items(chunk: str) -> list[str]:
    """把一个区块切成条目：支持 1、/1./①/•/- 以及换行。"""
    if not chunk.strip():
        return []
    text = chunk.replace("\r", "\n")
    boundaries: set[int] = set()
    for match in re.finditer(r"\d{1,2}\s*[、.．)）](?!\d)", text):
        start = match.start()
        if start == 0 or text[start - 1] in _SEP_BEFORE or text[start - 1].isspace():
            boundaries.add(start)
    for match in re.finditer(r"[①-⑳]|[•·▪●○◆■]", text):
        boundaries.add(match.start())
    for match in re.finditer(r"\n", text):
        boundaries.add(match.end())

    points = sorted(b for b in boundaries if 0 <= b < len(text))
    segments: list[str] = []
    if points:
        head = text[: points[0]]
        if head.strip():
            segments.append(head)
        for index, point in enumerate(points):
            end = points[index + 1] if index + 1 < len(points) else len(text)
            segments.append(text[point:end])
    else:
        # 完全无编号的一整段：用中文分号当条目分隔（"负责A；参与B；维护C"）
        segments = [part for part in re.split(r"[;；]", text) if part.strip()]

    cleaned = [_clean_item(segment) for segment in segments]
    return _dedupe([item for item in cleaned if not _is_noise(item)])


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.replace(" ", "")
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# --------------------------------------------------------------------- 量化抽取


def _looks_like_duty(item: str) -> bool:
    """判断一段文本像不像「职责」（避免把开场白/亮点当职责）。"""
    if len(item) < 8:
        return False
    if item.endswith((":", "：")):
        return False
    verbs = ("负责", "参与", "完成", "搭建", "设计", "开发", "维护", "优化", "制定",
             "推动", "跟进", "对接", "支持", "分析", "输出", "落地", "管理", "编写")
    return any(verb in item for verb in verbs)
