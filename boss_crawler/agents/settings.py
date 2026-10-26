"""agent 的声明式配置：能读、能写、能校验。

之前 agent 是"代码里注册了就跑"，没有地方可以调——想关掉某个背调平台、
想给某个 agent 单独指定模型，只能改代码。这里补上配置文件这一层：

```
config/agents.json
{
  "agents": {
    "zhihu":        {"enabled": false},
    "company_score":{"model": {"chat": "chat.doubao"}},
    "resume_tailor":{"options": {"max_questions": 3}}
  }
}
```

**写入口径**：只允许写已注册的 agent、已声明的模型能力，写错直接报错而不是静默忽略
——配置文件写错的代价是"以为生效了其实没有"，比报错更难查。
"""
from __future__ import annotations

import json
import os
import tempfile
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .. import config

CONFIG_DIR = config.CONFIG_DIR
CONFIG_FILE = CONFIG_DIR / "agents.json"


def config_path() -> Path:
    return CONFIG_FILE


# ---------------------------------------------------------------- 数据结构
@dataclass(frozen=True)
class AgentConfig:
    """单个 agent 的可调项。空值表示"沿用默认"。"""

    name: str
    enabled: bool = True
    #: 能力 → 模型规格名，例如 {"chat": "chat.doubao"}
    model: dict[str, str] = field(default_factory=dict)
    #: 透传给 agent 的选项（agent 用 ctx.option 读）
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "model": dict(self.model),
                "options": dict(self.options)}


# ---------------------------------------------------------------- 读写
def load(path: Path | None = None) -> dict[str, AgentConfig]:
    """读配置。文件不存在或坏掉都返回空配置，不影响主流程。"""
    path = path or CONFIG_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏文件不该让整包起不来
        warnings.warn(f"agent 配置无法解析，已按默认值运行：{path}（{exc}）",
                      RuntimeWarning, stacklevel=2)
        return {}
    items = raw.get("agents") or {}
    out: dict[str, AgentConfig] = {}
    for name, conf in items.items():
        if not isinstance(conf, dict):
            continue
        raw_enabled = conf.get("enabled", True)
        if isinstance(raw_enabled, bool):
            enabled = raw_enabled
        else:
            # JSON 里写成 "false"/"0"/"no" 时不能按真值处理
            enabled = str(raw_enabled).strip().lower() not in ("false", "0", "no", "off", "")
        out[name] = AgentConfig(
            name=name,
            enabled=enabled,
            model={str(k): str(v) for k, v in (conf.get("model") or {}).items()},
            options=dict(conf.get("options") or {}),
        )
    return out


def save(configs: dict[str, AgentConfig], path: Path | None = None) -> Path:
    """原子写：先写临时文件再替换，避免写到一半断电留下坏 JSON。"""
    path = path or CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_说明": "agent 配置。enabled=false 会在流水线里跳过该 agent；"
                 "model 按能力覆盖模型规格（见 config/models.json）。",
        "agents": {name: conf.to_dict() for name, conf in sorted(configs.items())},
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# ---------------------------------------------------------------- 校验
def _validate_agent(name: str) -> None:
    from .registry import get, load_errors

    try:
        get(name)
    except KeyError:
        errors = load_errors()
        hint = f"（子包加载错误：{errors}）" if errors else ""
        raise ValueError(f"未注册的 agent：{name}{hint}") from None


def _validate_model(model: dict[str, str]) -> None:
    from .models import KINDS, get_model

    for kind, spec in model.items():
        if kind not in KINDS:
            raise ValueError(f"未知模型能力：{kind}（可用：{'、'.join(KINDS)}）")
        try:
            get_model(spec)
        except KeyError as exc:
            raise ValueError(str(exc)) from None


def get_config(name: str, path: Path | None = None) -> AgentConfig:
    return load(path).get(name) or AgentConfig(name=name)


def set_config(
    name: str,
    *,
    enabled: bool | None = None,
    model: dict[str, str] | None = None,
    clear_models: Iterable[str] | None = None,
    options: dict[str, Any] | None = None,
    path: Path | None = None,
) -> AgentConfig:
    """改一个 agent 的配置并落盘，返回合并后的结果。

    ``None`` 表示"这一项不动"，所以要把某 agent 恢复默认请用 :func:`reset_config`。
    ``clear_models`` 只清掉指定能力的覆盖，其他能力与选项保持不变——这样设置页
    可以把某个能力改回"跟随默认"，而不用整条配置重置。
    """
    from .models import KINDS

    _validate_agent(name)
    if model is not None:
        _validate_model(model)
    clearing = {str(kind) for kind in (clear_models or ())}
    unknown = clearing - set(KINDS)
    if unknown:
        raise ValueError(f"未知模型能力：{'、'.join(sorted(unknown))}"
                         f"（可用：{'、'.join(KINDS)}）")
    both = clearing & set(model or {})
    if both:
        raise ValueError(f"同一能力不能同时设置和清除：{'、'.join(sorted(both))}")

    configs = load(path)
    current = configs.get(name) or AgentConfig(name=name)
    merged_model = dict(current.model)
    if model is not None:
        merged_model.update(model)
    for kind in clearing:
        merged_model.pop(kind, None)
    _validate_model(merged_model)
    updated = replace(
        current,
        enabled=current.enabled if enabled is None else bool(enabled),
        model=merged_model,
        options=current.options if options is None else dict(options),
    )
    # 与默认完全一致就不落盘：否则配置文件里会堆满
    # {"enabled": true, "model": {}, "options": {}} 的噪声，看着像有意配过
    if updated.enabled and not updated.model and not updated.options:
        configs.pop(name, None)
    else:
        configs[name] = updated
    save(configs, path)
    return updated


def reset_config(name: str, path: Path | None = None) -> AgentConfig:
    """删掉该 agent 的覆盖项，回到代码里的默认。"""
    configs = load(path)
    configs.pop(name, None)
    save(configs, path)
    return AgentConfig(name=name)


# ---------------------------------------------------------------- 生效
def effective(path: Path | None = None) -> list[dict[str, Any]]:
    """给 CLI / 前端用的合并视图：代码里的声明 + 配置文件里的覆盖。"""
    from .registry import catalog

    configs = load(path)
    rows: list[dict[str, Any]] = []
    for item in catalog():
        conf = configs.get(item["name"]) or AgentConfig(name=item["name"])
        rows.append({
            **item,
            "enabled": conf.enabled,
            "model": dict(conf.model),
            "options": dict(conf.options),
            "configured": item["name"] in configs,
        })
    return rows


def is_enabled(name: str, path: Path | None = None) -> bool:
    return get_config(name, path).enabled


def scope_context(ctx: Any, name: str, path: Path | None = None) -> Any:
    """按 agent 配置派生一个上下文：模型覆盖 + 私有选项。

    不改原 ctx，避免一个 agent 的模型选择污染另一个。
    """
    conf = get_config(name, path)
    if not conf.model and not conf.options:
        return ctx
    options = dict(getattr(ctx, "options", {}) or {})
    if conf.model:
        merged = dict(options.get("model_overrides") or {})
        merged.update(conf.model)
        options["model_overrides"] = merged
    if conf.options:
        # 复制嵌套字典，别改到原 ctx 共享的那一份
        agent_options = dict(options.get("agent_options") or {})
        agent_options[name] = dict(conf.options)
        options["agent_options"] = agent_options
        options.update(conf.options)
    return replace(ctx, options=options)


def describe(path: Path | None = None) -> dict[str, Any]:
    """自检用：有多少被停用、有多少自定义了模型。"""
    rows = effective(path)
    return {
        "file": str(config_path()),
        "exists": config_path().exists(),
        "total": len(rows),
        "disabled": [r["name"] for r in rows if not r["enabled"]],
        "models": {r["name"]: r["model"] for r in rows if r["model"]},
        "agents": rows,
    }


__all__ = [
    "AgentConfig",
    "config_path",
    "describe",
    "effective",
    "get_config",
    "is_enabled",
    "load",
    "reset_config",
    "save",
    "scope_context",
    "set_config",
]
