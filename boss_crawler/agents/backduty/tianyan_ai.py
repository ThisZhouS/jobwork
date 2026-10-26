"""天眼AI 背调 agent。

用官方 ``tyc`` CLI 的免费额度（免费会员即可，无需购买任何接口）。
它补齐了网页端拿不到的东西：风险总览、简介、规模、标签、知产评分。

工具调用与降级都在 ``tyc_bundle`` 工具里；这里只汇总。
"""
from __future__ import annotations

from typing import Any

from ..registry import register
from ..toolagent import ToolAgent, ToolCall


class TianyanAiAgent(ToolAgent):
    name = "tianyan_ai"
    site = "天眼AI"
    description = "调 tyc_bundle 工具（tyc CLI 免费额度），取工商/风险总览/规模/知产"
    requires = ("cli",)
    tools = (ToolCall("tyc_bundle", source="tianyan_ai",
                      params=lambda request: {"company": request.require_company()},
                      produces="data"),)

    def extra_meta(self, results) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for result in results:
            data = result.data
            if not isinstance(data, dict):
                continue
            bundle = data.get("bundle") or {}
            meta["company"] = data.get("company")
            meta["bundle"] = bundle
            meta["registration"] = _as_dict(bundle.get("registration"))
            meta["risk"] = _as_dict(bundle.get("risk"))
            meta["scale"] = _as_dict(bundle.get("scale"))
            meta["tags"] = _as_dict(bundle.get("tags"))
            meta["ipr_score"] = _as_dict(bundle.get("ipr_score"))
            meta["free_tools_only"] = True
        return meta


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        for key in ("data", "result"):
            inner = value.get(key)
            if isinstance(inner, dict):
                return inner
        return value
    if isinstance(value, list):
        return value[0] if value and isinstance(value[0], dict) else {}
    return {}


register(TianyanAiAgent)
