"""Ark（火山方舟）模型实现。

只做两件事：把 ``chat`` / ``embed`` 两个操作翻译成 HTTP 请求，并把供应商
的各种失败翻成带 ``code`` 的 :class:`ModelUnavailable`——这样上层永远只需要
判断"能不能用"，不用认识 404/401 这些细节。

**密钥只在这里被读取一次，绝不写日志、绝不进返回值。**
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from .base import ModelResult, ModelSpec, ModelUnavailable, register_model

#: 一次最多嵌入多少条（Ark 限制比较宽松，但要防止极端输入）
EMBED_BATCH = 16


class ArkClient:
    """一个规格的调用实现。无状态，可复用。"""

    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec

    async def __call__(self, op: str, **payload: Any) -> ModelResult:
        if op == "embed":
            return await self.embed(payload.get("texts") or [])
        if op == "chat":
            return await self.chat(payload.get("messages") or [])
        raise ModelUnavailable(f"Ark 不支持的操作：{op}", code="no_op")

    # ------------------------------------------------------------ 嵌入
    async def embed(self, texts: Sequence[str]) -> ModelResult:
        items = [str(text) for text in texts if str(text).strip()]
        if not items:
            return ModelResult(spec=self.spec.name, kind="embedding", ok=True)
        vectors: list[list[float]] = []
        usage: dict[str, Any] = {}
        for start in range(0, len(items), EMBED_BATCH):
            batch = items[start:start + EMBED_BATCH]
            data = await self._post("/embeddings", {"model": self.spec.model_id,
                                                    "input": batch})
            for row in data.get("data") or []:
                vector = row.get("embedding")
                if isinstance(vector, list):
                    vectors.append([float(x) for x in vector])
            if isinstance(data.get("usage"), dict):
                usage.update(data["usage"])
        return ModelResult(spec=self.spec.name, kind="embedding", ok=True,
                           vectors=vectors, usage=usage)

    # ------------------------------------------------------------ 对话
    async def chat(self, messages: Sequence[dict]) -> ModelResult:
        payload = {
            "model": self.spec.model_id,
            "messages": [dict(m) for m in messages],
            "temperature": 0.3,
        }
        data = await self._post("/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            raise ModelUnavailable("Ark 没有返回 choices", code="empty")
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "").strip()
        return ModelResult(spec=self.spec.name, kind="chat", ok=bool(text), text=text,
                           usage=data.get("usage") or {})

    # ------------------------------------------------------------ HTTP
    async def _post(self, path: str, payload: dict) -> dict:
        key = self.spec.api_key()
        if not key:
            raise ModelUnavailable(f"缺少密钥（{self.spec.api_key_env}）", code="no_key")

        import httpx

        url = (self.spec.base_url or "").rstrip("/") + path
        headers = {"Authorization": f"Bearer {key}",
                   "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.spec.timeout) as client:
                response = await client.post(url, headers=headers,
                                             content=json.dumps(payload))
        except Exception as exc:  # noqa: BLE001 - 网络错误统一归类
            raise ModelUnavailable(f"请求失败：{type(exc).__name__}: {exc}",
                                   code="network") from exc

        if response.status_code >= 400:
            raise ModelUnavailable(_explain(response), code=_code_of(response))

        try:
            return response.json()
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailable(f"返回不是 JSON：{exc}", code="bad_json") from exc


def _explain(response: Any) -> str:
    """把供应商错误压成一句人话。注意：不打 Key，也不打完整请求体。"""
    body = ""
    try:
        body = response.text[:300]
    except Exception:  # noqa: BLE001
        pass
    lower = body.lower()
    if "unsupportedmodel" in lower or "unsupported model" in lower:
        return (f"{response.status_code} 该密钥不支持这个模型（供应商返回 UnsupportedModel）"
                "——如果是对话模型，说明当前密钥只有嵌入权限")
    if "authentication" in lower or "invalid api key" in lower:
        return f"{response.status_code} 密钥无效或权限不足"
    return f"{response.status_code} {body}".strip()


def _code_of(response: Any) -> str:
    lower = ""
    try:
        lower = response.text.lower()
    except Exception:  # noqa: BLE001
        pass
    if "unsupportedmodel" in lower or "unsupported model" in lower:
        return "unsupported"
    if response.status_code in (401, 403):
        return "no_key"
    if response.status_code == 429:
        return "rate_limit"
    return "http_error"


# ---------------------------------------------------------------- 内置规格
def _builtin() -> None:
    from ... import config

    base = getattr(config, "ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/plan/v3")
    model = getattr(config, "ARK_MODEL", "doubao-embedding-vision-250328")
    register_model(ModelSpec(
        name="embedding.doubao",
        kind="embedding",
        provider="ark",
        model_id=model,
        base_url=base,
        api_key_env="ARK_API_KEY",
        dimension=2048,
        capabilities=("embedding", "vision"),
        note="当前唯一已验证可用的能力（向量化）",
    ))
    register_model(ModelSpec(
        name="chat.doubao",
        kind="chat",
        provider="ark",
        model_id="doubao-seed-1.6",
        # 对话走 /api/v3，与 embedding 的 plan/v3 不是同一个前缀
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key_env="ARK_API_KEY",
        capabilities=("chat", "json", "rewrite"),
        enabled=False,
        note="默认停用：现有密钥只有嵌入权限，调用会返回 UnsupportedModel。"
             "拿到对话权限后把 enabled 改成 true（或改 config/models.json）",
    ))


try:
    _builtin()
except ValueError:
    pass
