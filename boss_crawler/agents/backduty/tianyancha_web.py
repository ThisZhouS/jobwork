"""天眼查网页端背调 agent。

**这个 agent 是必须的**：开放平台接口按次计费且有充值门槛（100/1000 元），
网页端在免登录状态下就能拿到工商档案与规模/风险计数，是真正零成本的兜底。

反爬与解析都在 ``tianyancha_full`` 工具里（它内部串起搜索→详情→风险子页），
这个 agent 只负责汇总。
"""
from __future__ import annotations

from typing import Any

from ..registry import register
from ..toolagent import ToolAgent, ToolCall


class TianyanchaWebAgent(ToolAgent):
    name = "tianyancha_web"
    site = "天眼查网页端"
    description = "调 tianyancha_full 工具，取工商档案与规模/风险计数（免登录、不走付费接口）"
    requires = ("http",)
    tools = (
        ToolCall(
            "tianyancha_full",
            source="tianyancha_web",
            params=lambda request: {
                "company": request.require_company(),
                "include_risk": bool(request.option("include_risks", True)),
            },
            produces="raw",
        ),
    )

    def extra_meta(self, results) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for result in results:
            data = result.data
            if isinstance(data, dict):
                meta["company_id"] = data.get("company_id")
                meta["profile"] = data.get("profile") or {}
                meta["counts"] = data.get("counts") or {}
                meta["risks"] = data.get("risks") or []
                meta["match_score"] = data.get("match_score")
        return meta


register(TianyanchaWebAgent)
