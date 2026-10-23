"""Agent 契约层：所有 agent 只依赖这里，彼此不互相 import。

设计目标（对应用户要求「所有 agent 单独独立、模块化、后续自己设计组合」）：

* **单一入口**：每个 agent 只实现 ``run(request, ctx) -> AgentResult``；
* **形状统一**：背调类产出 :class:`Finding`，评分类产出 :class:`ScoreCard`，
  于是任意 agent 的输出都能被任意 agent 消费，组合方式由调用方决定；
* **失败可表达**：被登录墙/验证码挡住是常态，用 ``AgentStatus.BLOCKED``
  表达，而不是抛异常或返回空列表假装成功；
* **不做全局状态**：外部依赖（数据库、HTTP、浏览器）都在 :class:`AgentContext`
  里按需注入，agent 本身无副作用可直接单测。
"""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Protocol


# --------------------------------------------------------------------- 状态
class AgentStatus(str, Enum):
    """执行结果。BLOCKED 与 EMPTY 必须分开：前者要人去登录，后者是真的没数据。"""

    OK = "ok"
    PARTIAL = "partial"      # 拿到部分数据，但有关键缺口
    EMPTY = "empty"          # 正常跑完，确实没有相关内容
    BLOCKED = "blocked"      # 登录墙 / 验证码 / 反爬拦截
    FAILED = "failed"        # 代码或网络错误

    @property
    def is_usable(self) -> bool:
        return self in (AgentStatus.OK, AgentStatus.PARTIAL)


class AgentKind(str, Enum):
    BACKDUTY = "backduty"    # 背调：采集外部评价与工商信息
    SCORING = "scoring"      # 评分：把已有信息折算成分数


# --------------------------------------------------------------------- 证据
@dataclass
class Finding:
    """一条可追溯的证据。所有背调 agent 都产出这个，便于合并与展示。"""

    source: str                      # zhihu / tieba / weibo / tianyancha_web / tianyan_ai
    title: str = ""
    url: str = ""
    snippet: str = ""
    published_at: str | None = None
    author: str | None = None
    sentiment: float | None = None    # -1（负面）.. 1（正面）；None 表示未判定
    weight: float = 1.0               # 可信度/相关度权重，供评分 agent 加权
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_at": self.published_at,
            "author": self.author,
            "sentiment": self.sentiment,
            "weight": self.weight,
            "meta": self.meta,
        }

    @property
    def text(self) -> str:
        """标题 + 摘要，供关键词匹配用。"""
        return f"{self.title} {self.snippet}".strip()


# --------------------------------------------------------------------- 评分
@dataclass
class Dimension:
    """一个评分维度。分数固定 0-100，权重由 agent 自己给。"""

    name: str
    score: float
    weight: float = 1.0
    reason: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 1),
            "weight": self.weight,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class ScoreCard:
    """统一的评分卡。三个评分 agent 都用它，调用方可以用同一套代码展示。"""

    subject: str                     # 被评对象：公司名 / 简历 / 岗位适配
    dimensions: list[Dimension] = field(default_factory=list)
    total: float = 0.0
    grade: str = "?"
    verdict: str = ""                # 一句话结论
    advice: list[str] = field(default_factory=list)    # 提升方向
    notes: list[str] = field(default_factory=list)

    def finalize(self) -> "ScoreCard":
        """按权重算总分并定级。总分缺失时才重算，避免覆盖手工调整值。"""
        weight_sum = sum(d.weight for d in self.dimensions) or 1.0
        self.total = round(sum(d.score * d.weight for d in self.dimensions) / weight_sum, 1)
        self.grade = grade_of(self.total)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "total": self.total,
            "grade": self.grade,
            "verdict": self.verdict,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "advice": self.advice,
            "notes": self.notes,
        }

    def dimension(self, name: str) -> Dimension | None:
        for d in self.dimensions:
            if d.name == name:
                return d
        return None


def grade_of(total: float) -> str:
    """分数 -> 等级。分档刻意少一点，避免过度精确的假象。"""
    if total >= 85:
        return "A"
    if total >= 70:
        return "B"
    if total >= 55:
        return "C"
    if total >= 40:
        return "D"
    return "E"


# --------------------------------------------------------------------- 入参
@dataclass
class AgentRequest:
    """一次 agent 调用的输入。

    不同 agent 只读自己关心的字段；缺依赖时抛 :class:`MissingInput`，
    由调用方决定是跳过还是报错（组合时很有用）。
    """

    company_name: str = ""
    company_key: str | None = None
    company_aliases: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)     # 上游背调结果
    metrics: dict[str, Any] = field(default_factory=dict)     # 上游指标
    resume: dict[str, Any] | None = None
    job: dict[str, Any] | None = None
    options: dict[str, Any] = field(default_factory=dict)     # agent 私有参数
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def require_company(self) -> str:
        if not self.company_name.strip():
            raise MissingInput("缺少 company_name")
        return self.company_name.strip()

    def require_resume(self) -> dict[str, Any]:
        if not self.resume:
            raise MissingInput("缺少 resume")
        return self.resume

    def require_job(self) -> dict[str, Any]:
        if not self.job:
            raise MissingInput("缺少 job")
        return self.job

    def require_findings(self) -> list[Finding]:
        if not self.findings:
            raise MissingInput("缺少上游 findings（先跑背调 agent）")
        return self.findings

    def option(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


class MissingInput(ValueError):
    """输入不足。属于调用方的编排问题，不是 agent 的 bug。"""


# --------------------------------------------------------------------- 上下文
class Fetcher(Protocol):
    """HTTP 抓取器协议，便于替换与单测。"""

    async def get(self, url: str, **kwargs: Any) -> str: ...


class BrowserLike(Protocol):
    """浏览器协议：只要能取渲染后的 HTML 就够了。"""

    async def html(self, url: str, *, wait_selector: str | None = None) -> str: ...


@dataclass
class AgentContext:
    """外部依赖的注入点。默认全是 None，agent 应据此降级而不是崩。"""

    db: Any = None
    logger: Any = None
    http: Fetcher | None = None
    browser: BrowserLike | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def log(self, level: str, message: str) -> None:
        if self.logger is not None:
            getattr(self.logger, level, self.logger.info)(message)

    def require_http(self) -> Fetcher:
        if self.http is None:
            raise MissingInput("缺少 http 抓取器")
        return self.http

    def option(self, key: str, default: Any = None) -> Any:
        """读一个运行选项。与 :meth:`AgentRequest.option` 保持同名同语义。"""
        return self.options.get(key, default)

    def model_box(self):
        """模型调用器。拿不到模型时它返回失败结果，不抛异常。"""
        from .models import ModelBox

        box = self.options.get("_model_box")
        if box is None:
            box = ModelBox(self)
            self.options["_model_box"] = box
        return box

    def require_model(self, kind: str):
        """要一个**确定可用**的模型能力，不可用就抛 :class:`MissingInput`。"""
        box = self.model_box()
        if not box.available(kind):
            raise MissingInput(f"缺少可用的 {kind} 模型（可关停或用规则化兜底）")
        return box

    def require_browser(self) -> BrowserLike:
        if self.browser is None:
            raise MissingInput("缺少浏览器（该 agent 需要渲染页面）")
        return self.browser


# --------------------------------------------------------------------- 结果
@dataclass
class AgentResult:
    """agent 输出。背调类填 findings，评分类填 score。"""

    agent: str
    status: AgentStatus
    findings: list[Finding] = field(default_factory=list)
    score: ScoreCard | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    elapsed_s: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "status": self.status.value,
            "findings": [f.to_dict() for f in self.findings],
            "score": self.score.to_dict() if self.score else None,
            "notes": self.notes,
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 3),
            "meta": self.meta,
        }

    @property
    def usable(self) -> bool:
        return self.status.is_usable

    @classmethod
    def ok(cls, agent: str, **kwargs: Any) -> "AgentResult":
        return cls(agent=agent, status=AgentStatus.OK, **kwargs)

    @classmethod
    def blocked(cls, agent: str, reason: str, **kwargs: Any) -> "AgentResult":
        notes = list(kwargs.pop("notes", []))
        return cls(agent=agent, status=AgentStatus.BLOCKED, notes=[reason, *notes], **kwargs)

    @classmethod
    def failed(cls, agent: str, error: str, **kwargs: Any) -> "AgentResult":
        return cls(agent=agent, status=AgentStatus.FAILED, error=error, **kwargs)


def merge_findings(results: Iterable[AgentResult]) -> list[Finding]:
    """把多个背调结果拼起来，按 URL 去重（没有 URL 的按标题+来源）。"""
    seen: set[str] = set()
    merged: list[Finding] = []
    for result in results:
        for finding in result.findings:
            key = finding.url or f"{finding.source}:{finding.title}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(finding)
    return merged


# --------------------------------------------------------------------- 基类
class Agent(ABC):
    """所有 agent 的基类。子类只需实现 :meth:`run`。

    类属性说明：

    * ``name``：全局唯一，注册表与 CLI 都用它；
    * ``kind``：背调 or 评分，用于分组展示；
    * ``requires``：声明的外部依赖（``http`` / ``browser`` / ``db``），
      调度器可以据此提前准备，用户组合时也能看出哪个 agent 重；
    * ``produces``：产出类型（``findings`` / ``score``），便于推断能否串联。
    """

    name: str = ""
    kind: AgentKind = AgentKind.BACKDUTY
    version: str = "1.0"
    description: str = ""
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    #: 需要哪些模型能力（chat / embedding）。只声明能力，不写具体模型名——
    #: 具体用哪个由 ``agents/models`` 的注册表与配置决定，可随时替换或关停。
    requires_models: tuple[str, ...] = ()

    @abstractmethod
    async def run(self, request: AgentRequest, ctx: AgentContext) -> AgentResult:
        """执行。实现里应把可预期的问题转成状态，而不是抛异常。"""

    async def execute(self, request: AgentRequest, ctx: AgentContext) -> AgentResult:
        """带计时与异常兜底的包装。调度统一走这里。"""
        started = time.monotonic()
        try:
            result = await self.run(request, ctx)
        except MissingInput as exc:
            return AgentResult(
                agent=self.name,
                status=AgentStatus.FAILED,
                error=f"输入不足：{exc}",
                elapsed_s=time.monotonic() - started,
            )
        except Exception as exc:  # noqa: BLE001 - 兜底，避免一个 agent 拖垮整条链
            ctx.log("error", f"[{self.name}] 未捕获异常：{exc}")
            return AgentResult(
                agent=self.name,
                status=AgentStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_s=time.monotonic() - started,
            )
        result.elapsed_s = time.monotonic() - started
        return result

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "version": self.version,
            "description": self.description,
            "requires": list(self.requires),
            "produces": list(self.produces),
            "requires_models": list(self.requires_models),
        }
