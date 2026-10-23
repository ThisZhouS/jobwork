"""DeepSeek 对话模型（OpenAI 兼容接口）。

只实现 ``chat``：``POST {base_url}/chat/completions`` + Bearer 密钥。
Anthropic 兼容端点（``https://api.deepseek.com/anthropic``）不是 OpenAI 形状，
当前项目没有对应客户端，因此不接入——需要时再加独立 provider，避免把两种协议混在一起。

密钥只从 ``DEEPSEEK_API_KEY`` 或 ``.state/deepseek_key.txt`` 读，
不写进代码、配置、日志或返回值。
"""
from __future__ import annotations

from typing import Any, Sequence

from .ark import ArkClient
from .base import ModelResult, ModelSpec, ModelUnavailable, register_model


class DeepSeekClient(ArkClient):
    """复用 Ark 的 HTTP 细节，只暴露对话能力。"""

    async def __call__(self, op: str, **payload: Any) -> ModelResult:
        if op == "chat":
            return await self.chat(payload.get("messages") or [])
        raise ModelUnavailable(f"DeepSeek 规格未配置 {op} 能力", code="no_op")

    async def chat(self, messages: Sequence[dict]) -> ModelResult:
        data = await self._post("/chat/completions", {
            "model": self.spec.model_id,
            "messages": [dict(m) for m in messages],
            "temperature": 0.3,
            "max_tokens": 2048,
            "stream": False,
        })
        choices = data.get("choices") or []
        if not choices:
            raise ModelUnavailable("DeepSeek 没有返回 choices", code="empty")
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "").strip()
        return ModelResult(spec=self.spec.name, kind="chat", ok=bool(text), text=text,
                           usage=data.get("usage") or {})


def _builtin() -> None:
    from ... import config

    register_model(ModelSpec(
        name="chat.deepseek",
        kind="chat",
        provider="deepseek",
        model_id=getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-flash"),
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key_env="DEEPSEEK_API_KEY",
        capabilities=("chat", "json", "rewrite"),
        note="DeepSeek OpenAI 兼容对话模型；密钥从 DEEPSEEK_API_KEY 或 .state/deepseek_key.txt 读",
    ))


try:
    _builtin()
except ValueError:
    pass
