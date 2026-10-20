"""技能识别：从 JD 文本里抽技术栈，并把写法各异的表述规范化。

难点是噪音：平台会把「Linux开发/部署经验」「经济/工商管理相关专业」当技能返回。
这里做三件事：词典归一（``js``->JavaScript）、ASCII 技术词过滤、按类别打标，
最终只保留真正的技术栈。
"""

import re

from .jd_sections import _dedupe

SKILL_WORDS = {
    "数据": [
        "SQL", "MySQL", "PostgreSQL", "Oracle", "Redis", "MongoDB", "Hive", "Spark",
        "Flink", "Hadoop", "Kafka", "ClickHouse", "Doris", "Greenplum", "ETL",
        "数据仓库", "数据建模", "数据挖掘", "数据分析", "数据清洗", "数据治理",
        "指标体系", "埋点", "OLAP", "A/B测试", "AB测试", "Tableau", "PowerBI",
        "FineBI", "Superset", "Excel", "Pandas", "NumPy", "统计分析", "报表",
    ],
    "算法/AI": [
        "机器学习", "深度学习", "大模型", "LLM", "NLP", "自然语言处理", "CV",
        "计算机视觉", "推荐系统", "搜索推荐", "强化学习", "PyTorch", "TensorFlow",
        "Transformer", "RAG", "Agent", "微调", "向量数据库", "Prompt", "OCR",
        "知识图谱", "特征工程", "模型训练",
    ],
    "后端": [
        "Python", "Java", "Golang", "Go", "C++", "C#", "PHP", "Node.js", "Rust",
        "Scala", "Spring", "SpringBoot", "Spring Cloud", "Django", "Flask",
        "FastAPI", "Tornado", "微服务", "分布式", "高并发", "RESTful", "gRPC",
        "消息队列", "RabbitMQ", "RocketMQ", "Linux", "Docker", "Kubernetes", "K8s",
        "Jenkins", "CI/CD", "Git", "Nginx", "Tomcat", "多线程", "JVM",
    ],
    "前端": [
        "JavaScript", "TypeScript", "React", "Vue", "Angular", "Webpack", "Vite",
        "HTML", "CSS", "小程序", "前端工程化", "H5", "UniApp",
    ],
    "测试/运维": [
        "自动化测试", "Selenium", "Pytest", "JMeter", "性能测试", "接口测试",
        "单元测试", "Shell", "运维", "监控", "网络安全", "渗透测试",
    ],
    "产品/业务": [
        "需求分析", "原型设计", "Axure", "项目管理", "敏捷开发", "Scrum",
        "产品经理", "用户研究", "竞品分析", "数据驱动",
    ],
    "通用": [
        "算法", "架构设计", "英文", "英语", "沟通能力", "团队协作", "抗压能力",
    ],
}


def normalize_skills(raw: list[str] | None) -> list[str]:
    """把平台返回的技能串规范化成干净技能实体。

    平台的 skills 字段经常是描述串，例如：
        "Linux开发/部署经验"、"Spark原理/源码"、"经济/工商管理相关专业"、"AI Agent  智能体"
    处理策略：先整串查词典归一；再按分隔符切开，逐段取词典词或合法技术词；其余丢弃。
    """
    canonical: list[str] = []
    for item in raw or []:
        text = str(item or "").strip()
        if not text:
            continue
        text = re.sub(r"[（(][^）)]*[）)]", "", text).strip()
        if not text:
            continue
        # 1) 整串直接命中词典（如 "CI/CD"、"SpringCloud" 归一）
        whole = _dict_skill(text)
        if whole:
            canonical.extend(whole)
            continue
        # 2) 按分隔符切开逐段处理
        for token in re.split(r"[、,，/／;；|]+", text):
            token = token.strip(" 　")
            if not token:
                continue
            hit = _dict_skill(token)
            if hit:
                canonical.extend(hit)
                continue
            if _looks_like_tech_token(token):
                canonical.append(token)
    return _dedupe(canonical)


def _dict_skill(text: str) -> list[str]:
    """在词典里找 text 包含的技能词（取最长匹配，支持子串）。"""
    lowered = text.lower()
    hits: list[str] = []
    for _category, words in SKILL_WORDS.items():
        for word in words:
            needle = word.lower()
            if needle in lowered:
                hits.append(word)
    # 去掉被更长命中包含的短词（如 "Spring" 与 "Spring Cloud"）
    hits = sorted(set(hits), key=len, reverse=True)
    kept: list[str] = []
    for word in hits:
        if not any(word != other and word.lower() in other.lower() for other in kept):
            kept.append(word)
    return kept


_TECH_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9+#.\- ]{1,23}$")


def _looks_like_tech_token(token: str) -> bool:
    """纯技术词：ASCII 起头、长度合理、不含中文描述性词。"""
    if not _TECH_TOKEN.match(token):
        return False
    if re.search(r"(经验|专业|学历|优先|相关|背景|证书)", token):
        return False
    return True


def skill_category(name: str) -> str:
    """技能 -> 分类（数据 / 算法AI / 后端 / 前端 / 测试运维 / 产品业务 / 通用）。"""
    below = str(name or "").strip().lower()
    for category, words in SKILL_WORDS.items():
        if any(word.lower() == below for word in words):
            return category
    return "其他"


def extract_skills(text: str, known: list[str] | None = None) -> list[str]:
    """技能词典命中 + API 自带技能（小写不敏感匹配拉丁词）。"""
    hits: list[str] = []
    lowered = text.lower()
    for _category, words in SKILL_WORDS.items():
        for word in words:
            needle = word.lower()
            if needle.isascii():
                pattern = r"(?<![a-z0-9+#.])" + re.escape(needle) + r"(?![a-z0-9+#])"
                if re.search(pattern, lowered):
                    hits.append(word)
            elif word in text:
                hits.append(word)
    for word in known or []:
        if word:
            hits.append(str(word).strip())
    return _dedupe([h for h in hits if h])
