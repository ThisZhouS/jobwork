"""公司打分：风险 / 待遇 / 压力 / 环境 / 福利。

维度按方案确定。每个维度都遵守同一条纪律：
**有信号才打分，没信号返回 ``None``（框架给中性分 60 并注明"无数据"）**，
绝不把"查不到"当成"没问题"或"很好"。

数据来源（都在 ``ScoreContext`` 里）：

* ``ctx.counts``   —— 天眼查/天眼AI 侧栏计数（法律诉讼、经营异常、行政处罚…）
* ``ctx.findings`` —— 知乎/贴吧/微博的证据（带 sentiment 与文本）
* ``ctx.metrics["jobs_summary"]`` —— 该公司的在招岗位汇总
  （``count`` / ``salary_avg`` / ``salary_max`` / ``welfare`` / ``skills``），
  由流水线在算分前塞进来
* ``ctx.profile``  —— 工商档案（登记状态、注册资本、成立时间）

改权重就是改 :attr:`CompanyScoreAgent.DIMENSIONS`；想换口径就换 ``scorer``。
"""
from __future__ import annotations

from typing import Any, Iterable

from ..base import Agent
from ..registry import register
from .framework import Rubric, Rule, ScoreContext, ScoringAgentMixin
from .rubric import interp

# ---------------------------------------------------------------- 词表
#: 指向"钱少/坑"的词
PAY_BAD = ("拖欠工资", "欠薪", "克扣", "罚款", "没有年终奖", "工资低", "不交社保")
#: 指向"待遇还行"的词
PAY_GOOD = ("年终奖", "十三薪", "14薪", "期权", "股票", "补贴", "涨薪", "按时发")
#: 压力信号
PRESSURE_WORDS = ("996", "007", "大小周", "单休", "加班严重", "无偿加班", "内卷",
                  "pua", "压力大", "随叫随到", "通宵", "常态化加班")
#: 环境信号（好/坏）
ENV_GOOD = ("氛围好", "环境好", "办公环境", "团队年轻", "扁平", "不加班", "双休", "弹性")
ENV_BAD = ("氛围差", "管理混乱", "勾心斗角", "办公室", "甲醛", "工位", "搬迁", "临时工位")
#: 福利信号
WELFARE_WORDS = ("五险一金", "六险一金", "补充医疗", "双休", "周末双休", "年假",
                 "年终奖", "餐补", "房补", "交通补贴", "团建", "体检", "节日福利")
#: 风险计数字段 -> 权重（越大越危险）
RISK_COUNTS = {
    "失信": 4.0, "被执行人": 4.0, "经营异常": 3.0, "行政处罚": 2.5,
    "股权冻结": 2.5, "开庭公告": 1.5, "法律诉讼": 1.0, "立案信息": 1.0,
    "自身风险": 1.2, "周边风险": 0.4,
}


# ---------------------------------------------------------------- 取信号
def _texts(ctx: ScoreContext) -> list[str]:
    out: list[str] = []
    for finding in ctx.findings:
        for attr in ("title", "snippet"):
            value = getattr(finding, attr, None)
            if value:
                out.append(str(value))
    return out


def _hits(texts: Iterable[str], words: Iterable[str]) -> int:
    blob = " ".join(texts)
    return sum(blob.count(word) for word in words)


def _jobs(ctx: ScoreContext) -> dict[str, Any]:
    value = ctx.metrics.get("jobs_summary") if isinstance(ctx.metrics, dict) else None
    return value if isinstance(value, dict) else {}


def _risk_points(ctx: ScoreContext) -> float | None:
    """把各种风险计数折成一个"危险度"分值（0 起，越高越糟）。"""
    total = 0.0
    seen = False
    for key, weight in RISK_COUNTS.items():
        value = ctx.counts.get(key)
        if isinstance(value, (int, float)):
            total += float(value) * weight
            seen = True
    risks = ctx.metrics.get("risks")
    if isinstance(risks, list) and risks:
        total += len(risks) * 2.0
        seen = True
    return total if seen else None


# ---------------------------------------------------------------- 五个维度
def score_risk(ctx: ScoreContext) -> float | None:
    """风险：工商风险计数 + 负面证据比例。分越高越安全。"""
    points = _risk_points(ctx)
    ratio = _negative_ratio(ctx)
    if points is None and ratio is None:
        return None
    parts: list[float] = []
    if points is not None:
        # 0 分 -> 100 分；50 分危险度 -> 30 分
        parts.append(interp(points, [(0, 100), (5, 85), (15, 65), (50, 30), (120, 5)]))
    if ratio is not None:
        parts.append(interp(ratio, [(0, 92), (0.2, 75), (0.4, 55), (0.7, 30), (1.0, 10)]))
    return sum(parts) / len(parts)


def score_pay(ctx: ScoreContext) -> float | None:
    """待遇：岗位薪资区间 + 正负面措辞。"""
    jobs = _jobs(ctx)
    parts: list[float] = []
    high = jobs.get("salary_max")
    low = jobs.get("salary_min")
    if isinstance(high, (int, float)) and high > 0:
        # 单位：元/月
        parts.append(interp(float(high), [(3000, 25), (6000, 45), (10000, 65),
                                          (20000, 82), (40000, 95)]))
    elif isinstance(low, (int, float)) and low > 0:
        parts.append(interp(float(low), [(3000, 20), (6000, 40), (10000, 60),
                                         (20000, 78), (40000, 92)]))
    texts = _texts(ctx)
    good = _hits(texts, PAY_GOOD)
    bad = _hits(texts, PAY_BAD)
    if good or bad:
        parts.append(max(0.0, min(100.0, 60 + good * 8 - bad * 15)))
    if not parts:
        return None
    return sum(parts) / len(parts)


def score_pressure(ctx: ScoreContext) -> float | None:
    """压力：加班/内卷措辞密度。分越高越轻松。"""
    texts = _texts(ctx)
    if not texts:
        return None
    hits = _hits(texts, PRESSURE_WORDS)
    base = interp(hits, [(0, 80), (1, 68), (3, 52), (6, 35), (12, 15)])
    return base


def score_environment(ctx: ScoreContext) -> float | None:
    """环境：办公氛围类措辞的正负对比。"""
    texts = _texts(ctx)
    if not texts:
        return None
    good = _hits(texts, ENV_GOOD)
    bad = _hits(texts, ENV_BAD + PRESSURE_WORDS)
    if not good and not bad:
        return None
    return max(0.0, min(100.0, 62 + good * 9 - bad * 11))


def score_welfare(ctx: ScoreContext) -> float | None:
    """福利：在招岗位的福利标签 + 证据里提到的福利项。"""
    jobs = _jobs(ctx)
    parts: list[float] = []
    tags = jobs.get("welfare")
    if isinstance(tags, list) and tags:
        parts.append(interp(len(tags), [(0, 45), (2, 60), (4, 72), (6, 85), (10, 95)]))
    texts = _texts(ctx)
    hits = _hits(texts, WELFARE_WORDS)
    if hits:
        parts.append(interp(hits, [(0, 50), (1, 65), (3, 78), (6, 90)]))
    if not parts:
        return None
    return sum(parts) / len(parts)


def _negative_ratio(ctx: ScoreContext) -> float | None:
    judged = [f for f in ctx.findings if getattr(f, "sentiment", None) is not None]
    if not judged:
        return None
    negative = sum(1 for f in judged if f.sentiment < 0)
    return negative / len(judged)


# ---------------------------------------------------------------- 劳务派遣
#: 命中这些词基本可以认定是劳务派遣/人力外包
DISPATCH_STRONG = ("劳务派遣", "劳务外包", "人才派遣", "人力资源外包", "岗位外包",
                   "猎头服务", "人力资源服务")
#: 命中这些词只是可疑，需要两个以上才判定
DISPATCH_WEAK = ("外包", "派遣", "驻场", "人力外包", "劳务", "临时工")


def detect_labor_dispatch(ctx: ScoreContext) -> dict[str, Any]:
    """判断这家公司是不是劳务派遣/人力外包。

    **单列成字段，不进五个维度**：劳务派遣不是"公司好不好"的一个侧面，
    而是"这岗位到底跟谁签合同"的性质问题——它该被单独展示给人看。
    返回 ``is_labor_dispatch`` 为 ``None`` 表示**没有足够信息判断**，
    不能默认 False（那会把"不知道"伪装成"不是派遣"）。
    """
    scope = str(ctx.profile.get("business_scope") or "")
    name = str(ctx.profile.get("name") or ctx.request.company_name or "")
    texts = _texts(ctx)
    corpus = " ".join([name, scope, *texts])

    strong = [word for word in DISPATCH_STRONG if word in corpus]
    # 公司名里出现"人力资源""劳务"这类，权重更高
    name_hit = [word for word in DISPATCH_STRONG + DISPATCH_WEAK if word in name]
    weak = [word for word in DISPATCH_WEAK if word in corpus]

    if name_hit or strong:
        hits = list(dict.fromkeys(name_hit + strong))
        return {
            "is_labor_dispatch": True,
            "labor_dispatch_reason": "命中关键词：" + "、".join(hits[:4]),
            "labor_dispatch_evidence": hits[:6],
        }
    if len(weak) >= 2:
        return {
            "is_labor_dispatch": True,
            "labor_dispatch_reason": "多个可疑词同时出现：" + "、".join(weak[:4]),
            "labor_dispatch_evidence": weak[:6],
        }
    if weak:
        return {
            "is_labor_dispatch": None,
            "labor_dispatch_reason": f"只命中一个可疑词（{weak[0]}），不足以判断",
            "labor_dispatch_evidence": weak[:3],
        }
    if scope or texts:
        return {"is_labor_dispatch": False,
                "labor_dispatch_reason": "经营范围与评价里未见派遣/外包字样",
                "labor_dispatch_evidence": []}
    return {"is_labor_dispatch": None,
            "labor_dispatch_reason": "没有经营范围也没有评价，无法判断",
            "labor_dispatch_evidence": []}


# ---------------------------------------------------------------- agent
class CompanyScoreAgent(ScoringAgentMixin, Agent):
    name = "company_score"
    description = "公司打分：风险/待遇/压力/环境/福利 + 是否劳务派遣"
    requires = ()

    #: 维度名 / 权重 / 该维度看什么 / 打分函数
    DIMENSIONS = (
        ("风险", 3.0, "失信·被执行·经营异常·诉讼数量·负面证据占比", score_risk),
        ("待遇", 3.0, "在招岗位薪资区间、拖欠/年终奖等措辞", score_pay),
        ("压力", 2.5, "996/大小周/无偿加班/内卷等措辞密度", score_pressure),
        ("环境", 2.0, "办公氛围、管理、团队类措辞正负对比", score_environment),
        ("福利", 2.0, "五险一金/双休/补贴/体检等福利项数量", score_welfare),
    )

    def build_rubric(self, request) -> Rubric:
        return Rubric(rules=[
            Rule(name=name, weight=weight, hint=hint, scorer=scorer)
            for name, weight, hint, scorer in self.DIMENSIONS
        ])

    def subject_of(self, request, ctx) -> str:
        return str(request.company_name or ctx.profile.get("name") or "公司")

    def extra_meta(self, request, ctx: ScoreContext, card) -> dict:
        """劳务派遣是独立字段：不进五维，单独给前端展示。"""
        info = detect_labor_dispatch(ctx)
        if info.get("is_labor_dispatch") is True:
            card.advice.append("这家公司疑似劳务派遣/人力外包，确认劳动合同签约主体")
        return info


register(CompanyScoreAgent)
