"""模型 API 层：和工具层同构 —— 声明式、可替换、可关停、可观察。

工具层解决"怎么拿到数据"，模型层解决"怎么生成文字/向量"。两者都遵守同一套
纪律，所以 agent 里写起来是一个形状：

```python
class MyAgent(Agent):
    requires_models = ("chat",)        # 声明要什么能力，不写具体模型
```

**为什么要这么绕一层**：

* 现在的 Ark 密钥只支持 ``/embeddings``，``/chat/completions`` 会返回
  ``UnsupportedModel``。把模型抽象出来，调用方就不必到处写 try/except，
  也便于以后换供应商；
* 模型名、endpoint、密钥来源都是**配置**，不是代码里的常量；
* 关掉模型（``--no-model``）时行为和"没配模型"完全一致——不会崩，
  只是降级到规则化输出。

## 三个可控旋钮

| 旋钮 | 位置 | 作用 |
|---|---|---|
| ``enabled`` | ``ModelSpec`` / ``config/models.json`` | 某个模型规格彻底停用 |
| ``ctx.option("models_enabled", False)`` | 运行时 | 全局关停（离线/省钱/测试） |
| ``ctx.option("model_overrides", {"chat": "chat.xxx"})`` | 运行时 | 按能力临时指定规格 |

## 定义一个新模型

```python
register_model(ModelSpec(
    name="chat.doubao",
    kind="chat",
    provider="ark",
    model_id="doubao-seed-1.6",
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    api_key_env="ARK_API_KEY",
    capabilities=("chat", "json"),
))
```

密钥**永远从环境变量或密钥文件读**，不进代码、不进日志、不进返回值。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

#: 能力：一个规格可以同时提供多种
KINDS = ("chat", "embedding", "rerank")


class ModelUnavailable(RuntimeError):
    """模型不可用（没配、被关停、密钥缺失、供应商不支持）。

    这是**预期内**的结果，不是异常路径：调用方据此降级到规则化逻辑。
    """

    def __init__(self, message: str, *, code: str = "unavailable") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ModelSpec:
    """一个模型规格（纯配置，不含调用逻辑）。"""

    name: str
    kind: str
    provider: str
    model_id: str
    base_url: str = ""
    #: 从哪个环境变量取密钥（变量名，不是密钥本身）
    api_key_env: str = "ARK_API_KEY"
    #: 向量维度（embedding 才有）
    dimension: int | None = None
    capabilities: tuple[str, ...] = ()
    enabled: bool = True
    timeout: float = 60.0
    note: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("模型规格必须有 name")
        if self.kind not in KINDS:
            raise ValueError(f"未知模型类型：{self.kind}（可用：{'、'.join(KINDS)}）")

    @property
    def key_env(self) -> str:
        return self.api_key_env

    def api_key(self) -> str | None:
        """读密钥。不读日志、不缓存、不打印。"""
        from ... import config

        value = os.environ.get(self.api_key_env)
        if value:
            return value.strip()
        try:
            path = getattr(config, "ARK_KEY_FILE", None)
            if path and Path(path).exists():
                text = Path(path).read_text(encoding="utf-8").strip()
                return text or None
        except Exception:  # noqa: BLE001
            return None
        return None

    def describe(self) -> dict:
        """对外描述：**绝不含密钥**。"""
        return {
            "name": self.name,
            "kind": self.kind,
            "provider": self.provider,
            "model_id": self.model_id,
            "dimension": self.dimension,
            "capabilities": list(self.capabilities),
            "enabled": self.enabled,
            "has_key": bool(self.api_key()),
            "note": self.note,
        }


@dataclass
class ModelResult:
    """一次模型调用的结果。失败也返回对象，不抛给业务层。"""

    spec: str
    kind: str
    ok: bool
    text: str = ""
    vectors: list[list[float]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    latency_s: float = 0.0
    error: str = ""
    code: str = ""

    @property
    def usable(self) -> bool:
        return self.ok and bool(self.text or self.vectors)


# ---------------------------------------------------------------- 注册表
_MODELS: dict[str, ModelSpec] = {}
_LOADED = False
_LOAD_ERRORS: dict[str, str] = {}


def register_model(spec: ModelSpec) -> ModelSpec:
    if spec.name in _MODELS:
        raise ValueError(f"模型规格已存在：{spec.name}")
    _MODELS[spec.name] = spec
    return spec


def unregister_model(name: str) -> None:
    """测试与临时停用用。"""
    _MODELS.pop(name, None)


def get_model(name: str) -> ModelSpec:
    _load_builtin()
    if name not in _MODELS:
        raise KeyError(f"未知模型规格：{name}（可用：{'、'.join(model_names()) or '无'}）")
    return _MODELS[name]


def model_names() -> list[str]:
    _load_builtin()
    return sorted(_MODELS)


def models_for(kind: str, *, enabled_only: bool = True) -> list[ModelSpec]:
    _load_builtin()
    return [spec for spec in _MODELS.values()
            if spec.kind == kind and (spec.enabled or not enabled_only)]


def model_catalog() -> list[dict]:
    _load_builtin()
    return [spec.describe() for spec in sorted(_MODELS.values(), key=lambda s: s.name)]


def load_errors() -> dict[str, str]:
    _load_builtin()
    return dict(_LOAD_ERRORS)


def reset_models() -> None:
    _MODELS.clear()
    _LOAD_ERRORS.clear()
    global _LOADED
    _LOADED = False


def _load_builtin() -> None:
    """导入内置规格 + 应用的声明式覆盖（config/models.json）。"""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        from . import ark  # noqa: F401  导入即注册
    except Exception as exc:  # noqa: BLE001 - 单文件坏了不该拖累整体
        _LOAD_ERRORS["boss_crawler.agents.models.ark"] = f"{type(exc).__name__}: {exc}"
    try:
        apply_overrides()
    except Exception as exc:  # noqa: BLE001
        _LOAD_ERRORS["config/models.json"] = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- 声明式覆盖
def overrides_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "models.json"


def apply_overrides(path: Path | None = None) -> dict:
    """用 ``config/models.json`` 调整规格（不写代码就能换模型/停用）。

    格式::

        {
          "overrides": {
            "chat.doubao": {"enabled": false},
            "embedding.doubao": {"model_id": "其它模型", "dimension": 1024}
          },
          "extra": [
            {"name": "chat.local", "kind": "chat", "provider": "local",
             "model_id": "rule-based", "enabled": true}
          ]
        }
    """
    path = path or overrides_path()
    if not path.exists():
        return {"applied": 0, "added": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    applied = added = 0
    for name, changes in (data.get("overrides") or {}).items():
        spec = _MODELS.get(name)
        if spec is None or not isinstance(changes, dict):
            continue
        # 下划线开头的是人写的注释（如 _why），不是规格字段
        changes = {k: v for k, v in changes.items() if not str(k).startswith("_")}
        merged = {**spec.__dict__, **changes}
        try:
            _MODELS[name] = ModelSpec(**merged)
        except TypeError:
            continue   # 写错的字段就跳过，别让整份配置失效
        applied += 1
    for raw in data.get("extra") or []:
        if not isinstance(raw, dict) or raw.get("name") in _MODELS:
            continue
        try:
            _MODELS[raw["name"]] = ModelSpec(**raw)
            added += 1
        except Exception:  # noqa: BLE001 - 单条写错就跳过
            continue
    return {"applied": applied, "added": added}


# ---------------------------------------------------------------- 写回覆盖
#: 允许通过配置改的字段。故意不含 ``api_key``/``api_key_env``：
#: 密钥永远不入配置文件，只从环境变量或 .state/ 读。
WRITABLE_FIELDS = ("enabled", "model_id", "dimension", "note", "provider")


def overrides_document(path: Path | None = None) -> dict:
    """读原始覆盖文档（保留 ``_说明`` 等人工注释）。"""
    path = path or overrides_path()
    if not path.exists():
        return {"overrides": {}, "extra": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"overrides": {}, "extra": []}
    data.setdefault("overrides", {})
    data.setdefault("extra", [])
    return data


def save_override(name: str, path: Path | None = None, **changes) -> dict:
    """改一个模型规格并写回 ``config/models.json``，立即生效。

    只接受 :data:`WRITABLE_FIELDS`，写错字段直接报错——静默忽略会让人
    以为配置生效了，这类问题比报错难查得多。
    """
    _load_builtin()
    if name not in _MODELS:
        raise KeyError(f"未知模型规格：{name}（可用：{'、'.join(sorted(_MODELS))}）")
    unknown = set(changes) - set(WRITABLE_FIELDS)
    if unknown:
        raise ValueError(f"不能写这些字段：{'、'.join(sorted(unknown))}"
                         f"（可写：{'、'.join(WRITABLE_FIELDS)}）")
    if "dimension" in changes and changes["dimension"] is not None:
        try:
            changes["dimension"] = int(changes["dimension"])
        except (TypeError, ValueError):
            raise ValueError("dimension 必须是整数") from None

    path = path or overrides_path()
    data = overrides_document(path)
    current = {k: v for k, v in (data["overrides"].get(name) or {}).items()
               if not str(k).startswith("_")}
    # 只留下确实需要覆盖的字段，避免把默认值抄进配置文件
    spec = _MODELS[name]
    for key, value in changes.items():
        if value is None:
            current.pop(key, None)
        elif getattr(spec, key, None) == value and key != "enabled":
            current.pop(key, None)   # 与默认相同就不写
        else:
            current[key] = value
    # 保留原有注释，别把 _why 之类的人工说明冲掉
    notes = {k: v for k, v in (data["overrides"].get(name) or {}).items()
             if str(k).startswith("_")}
    if current or notes:
        data["overrides"][name] = {**notes, **current}
    else:
        data["overrides"].pop(name, None)
    _write_document(data, path)
    apply_overrides(path)
    return {"name": name, "override": current, "spec": describe_spec(name)}


def reset_override(name: str, path: Path | None = None) -> dict:
    """删掉该规格的覆盖项，恢复代码里的默认。"""
    path = path or overrides_path()
    data = overrides_document(path)
    existed = data["overrides"].pop(name, None) is not None
    _write_document(data, path)
    reset_models()
    apply_overrides(path)
    return {"name": name, "removed": existed}


def _write_document(data: dict, path: Path) -> None:
    """原子写：临时文件 + 替换，避免写坏配置文件。"""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def describe_spec(name: str) -> dict:
    """单个规格的安全视图（绝不包含密钥本身）。"""
    spec = _MODELS[name]
    return {
        "name": spec.name, "kind": spec.kind, "provider": spec.provider,
        "model_id": spec.model_id, "enabled": spec.enabled,
        "dimension": spec.dimension, "note": spec.note,
        "has_key": bool(spec.api_key()),
        "writable": list(WRITABLE_FIELDS),
    }


# ---------------------------------------------------------------- 调用器
class ModelBox:
    """按"能力"取模型并调用，把可控旋钮和失败降级集中在一处。

    agent 不直接 import 任何供应商 SDK，也不碰密钥。
    """

    def __init__(self, ctx: Any = None, *, log: Any = None) -> None:
        self.ctx = ctx
        self._log = log

    # ------------------------------------------------------------ 取用
    def resolve(self, kind: str) -> ModelSpec:
        """挑一个可用规格：运行时覆盖 > 环境变量 > 注册表顺序。"""
        overrides = (self.ctx.option("model_overrides") if self.ctx else None) or {}
        wanted = overrides.get(kind)
        if wanted:
            spec = get_model(wanted)
            if not spec.enabled:
                raise ModelUnavailable(f"{wanted} 已被停用", code="disabled")
            return spec

        env_name = os.environ.get(f"MODEL_{kind.upper()}")
        if env_name:
            try:
                return get_model(env_name)
            except KeyError:
                pass

        candidates = models_for(kind)
        if not candidates:
            raise ModelUnavailable(f"没有可用的 {kind} 模型", code="no_spec")
        for spec in candidates:
            if spec.api_key():
                return spec
        raise ModelUnavailable(f"{kind} 模型缺少密钥（{candidates[0].api_key_env}）",
                              code="no_key")

    def _check_enabled(self) -> None:
        if self.ctx is None:
            return
        if not self.ctx.option("models_enabled", True):
            raise ModelUnavailable("模型已被关停（--no-model / models_enabled=False）",
                                   code="models_off")

    # ------------------------------------------------------------ 调用
    async def chat(self, messages: Sequence[dict], *, kind: str = "chat",
                   **kwargs: Any) -> ModelResult:
        return await self._call(kind, "chat", messages=messages, **kwargs)

    async def embed(self, texts: Sequence[str], *, kind: str = "embedding",
                    **kwargs: Any) -> ModelResult:
        return await self._call(kind, "embed", texts=texts, **kwargs)

    async def _call(self, kind: str, op: str, **payload: Any) -> ModelResult:
        started = time.perf_counter()
        try:
            self._check_enabled()
            spec = self.resolve(kind)
            if self.ctx is not None and self.ctx.option("model_dry_run", False):
                raise ModelUnavailable("dry-run：不实际调用", code="dry_run")
            client = _client_for(spec)
            result = await client(op, **payload)
            result.latency_s = round(time.perf_counter() - started, 2)
            return result
        except ModelUnavailable as exc:
            result = ModelResult(spec="", kind=kind, ok=False, error=str(exc),
                                 code=exc.code,
                                 latency_s=round(time.perf_counter() - started, 2))
            await self._record(result)
            return result
        except Exception as exc:  # noqa: BLE001 - 供应商各种异常统一兜底
            result = ModelResult(spec="", kind=kind, ok=False,
                                 error=f"{type(exc).__name__}: {exc}", code="error",
                                 latency_s=round(time.perf_counter() - started, 2))
            await self._record(result)
            return result

    async def _record(self, result: ModelResult) -> None:
        """模型不可用要留痕（可观察），但不影响业务。"""
        recorder = self._log or (self.ctx.option("log_model") if self.ctx else None)
        if recorder is None:
            return
        try:
            maybe = recorder({"kind": result.kind, "ok": result.ok,
                              "code": result.code, "error": result.error})
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 便捷
    async def text_of(self, messages: Sequence[dict], **kwargs: Any) -> str | None:
        """要一段文字：拿不到就 None（调用方走规则化兜底）。"""
        result = await self.chat(messages, **kwargs)
        return result.text if result.usable else None

    def available(self, kind: str) -> bool:
        try:
            self._check_enabled()
            self.resolve(kind)
            return True
        except ModelUnavailable:
            return False


def _client_for(spec: ModelSpec):
    """按 provider 找实现。没实现的 provider 明确报错，不静默。"""
    from . import ark

    if spec.provider == "ark":
        return ark.ArkClient(spec)
    raise ModelUnavailable(f"未实现的模型供应商：{spec.provider}", code="no_provider")


def describe_models() -> dict:
    """给前端/自检用：有哪些规格、哪些可用、密钥有没有配（不泄漏值）。"""
    _load_builtin()
    return {
        "models": model_catalog(),
        "by_kind": {kind: [spec.name for spec in models_for(kind)] for kind in KINDS},
        "errors": load_errors(),
    }
