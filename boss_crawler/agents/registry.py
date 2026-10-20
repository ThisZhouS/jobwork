"""注册表与组合器。

注册表让「加一个 agent」变成「新建一个文件 + 一行 register」，不需要改调度代码。
组合器则把多个 agent 串起来跑，由调用方自己决定顺序 —— 这正是用户说的
「后续我来设计对应的模块组合」。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .base import (
    Agent,
    AgentContext,
    AgentKind,
    AgentRequest,
    AgentResult,
    AgentStatus,
    Finding,
    merge_findings,
)

_REGISTRY: dict[str, type[Agent]] = {}


def register(cls: type[Agent]) -> type[Agent]:
    """注册一个 agent 类。可作装饰器用。"""
    if not cls.name:
        raise ValueError(f"{cls.__name__} 缺少 name")
    if cls.name in _REGISTRY and _REGISTRY[cls.name] is not cls:
        raise ValueError(f"agent 名称重复：{cls.name}")
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> type[Agent]:
    _load_builtin()
    if name not in _REGISTRY:
        raise KeyError(f"未知 agent：{name}（可用：{', '.join(sorted(_REGISTRY))}）")
    return _REGISTRY[name]


def catalog(kind: AgentKind | None = None) -> list[dict[str, Any]]:
    """列出所有已注册 agent 的能力声明。"""
    _load_builtin()
    items = [
        cls().describe()
        for cls in sorted(_REGISTRY.values(), key=lambda c: (c.kind.value, c.name))
    ]
    if kind is not None:
        items = [i for i in items if i["kind"] == kind.value]
    return items


def names(kind: AgentKind | None = None) -> list[str]:
    return [item["name"] for item in catalog(kind)]


_LOADED = False
_LOAD_ERRORS: dict[str, str] = {}


def _load_builtin() -> None:
    """惰性导入内置 agent。

    放在函数里是为了避免「registry -> backduty -> base -> registry」的循环导入，
    也让单个 agent 文件可以脱离整包单独运行。

    容错：某个子包整体缺失或导入失败时，只记录错误并跳过，其余 agent 照常可用。
    这样删掉一个 agent 目录不会让整个包炸掉（模块化的必然要求）。
    """
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    import importlib

    for module in ("boss_crawler.agents.tools",
                   "boss_crawler.agents.backduty",
                   "boss_crawler.agents.scoring",
                   "boss_crawler.agents.resume_tailor"):
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 - 单个子包坏掉不该拖累其他
            _LOAD_ERRORS[module] = f"{type(exc).__name__}: {exc}"


def load_errors() -> dict[str, str]:
    """返回内置子包的加载错误，供 CLI 提示「为什么少了一些 agent」。"""
    _load_builtin()
    return dict(_LOAD_ERRORS)


# ---------------------------------------------------------------- 组合
class Pipeline:
    """顺序执行多个 agent。

    默认行为：每一步都能读到之前所有 agent 的 findings 与 metrics，
    所以「背调 → 评分」这种链不用手写胶水。任何一步 FAILED 都不会中断整条链，
    除非 ``stop_on_failure=True``。
    """

    def __init__(self, steps: Sequence[str], *, stop_on_failure: bool = False) -> None:
        if not steps:
            raise ValueError("Pipeline 至少要一步")
        self.steps = list(steps)
        self.stop_on_failure = stop_on_failure

    async def run(
        self,
        request: AgentRequest,
        ctx: AgentContext,
        *,
        options_by_step: dict[str, dict] | None = None,
    ) -> list[AgentResult]:
        current = request
        results: list[AgentResult] = []
        for step in self.steps:
            agent = get(step)()
            step_request = _derive(current, base=request, options=(options_by_step or {}).get(step))
            result = await agent.execute(step_request, ctx)
            results.append(result)

            # 把本次产出回灌，供后续步骤使用
            current = _derive(
                current,
                base=request,
                findings=list(current.findings) + list(result.findings),
                metrics={**current.metrics, f"{step}": result.meta},
            )
            if result.score is not None:
                current.metrics[f"{step}_score"] = result.score.total

            if result.status is AgentStatus.FAILED and self.stop_on_failure:
                break
        return results


def _derive(
    request: AgentRequest,
    *,
    base: AgentRequest,
    findings: Iterable[Finding] | None = None,
    metrics: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> AgentRequest:
    """复制一份入参，避免各步骤之间互相污染。"""
    return AgentRequest(
        company_name=base.company_name,
        company_key=base.company_key,
        company_aliases=list(base.company_aliases),
        findings=list(findings if findings is not None else request.findings),
        metrics=dict(metrics if metrics is not None else request.metrics),
        resume=base.resume,
        job=base.job,
        options=dict(options if options is not None else base.options),
        run_id=base.run_id,
    )


async def run_agents(
    steps: Sequence[str],
    request: AgentRequest,
    ctx: AgentContext,
    **kwargs: Any,
) -> list[AgentResult]:
    """便捷函数：跑一条链并返回每步结果。"""
    return await Pipeline(steps).run(request, ctx, **kwargs)


__all__ = [
    "Pipeline",
    "catalog",
    "get",
    "load_errors",
    "merge_findings",
    "names",
    "register",
    "run_agents",
]
