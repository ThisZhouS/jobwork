"""阿里云云市场风险接口工具（配置化，AppCode 认证）。

它是一层"适配器"而不是某个具体接口的客户端：

* 地址、参数名、字段映射都在 ``config/risk_api.json`` 里；
* 认证走 ``Authorization: APPCODE <code>``，code 只从 ``ALIYUN_APPCODE``
  环境变量或 ``.state/aliyun_appcode.txt`` 读；
* 有**调用预算**（默认 20 次/进程），防止配错导致刷爆余额；
* 拿不到配置或缺 AppCode 时返回 BLOCKED，绝不静默跳过——
  静默跳过会让人以为"查过了没风险"。

统一行字段：``title / risk_type / case_no / court / amount / date / status / raw``。
"""
from __future__ import annotations

from typing import Any

from ....providers import aliyun_market as market
from ...base import AgentStatus
from ..base import Tool, ToolBox, ToolResult, register_tool


class AliyunRiskTool(Tool):
    name = "aliyun_risk"
    site = "阿里云云市场"
    description = "调云市场风险接口（司法涉诉/工商），配置化适配、AppCode 认证、按次计费"
    params = ("company",)
    requires = ("http",)

    def __init__(self) -> None:
        self._calls = 0

    def reset(self) -> None:
        """测试用：重置预算计数。"""
        self._calls = 0

    async def call(self, box: ToolBox, company: str = "", profile: str = "judicial",
                   **_: Any) -> ToolResult:
        name = str(company or "").strip()
        if not name:
            return ToolResult.failed(self.name, "缺少公司名")

        conf = market.get_profile(profile)
        if conf is None:
            return ToolResult.blocked(
                self.name, f"没有名为 {profile} 的接口配方（见 config/risk_api.json）")
        if not conf.enabled:
            return ToolResult.blocked(
                self.name, f"接口配方 {profile} 未启用：在 config/risk_api.json 里把 enabled 设为 true")
        if not conf.configured:
            return ToolResult.blocked(
                self.name, f"接口配方 {profile} 还没填 base/path（从云市场商品页复制调用地址）")

        code = market.appcode()
        if not code:
            return ToolResult.blocked(
                self.name,
                "缺少 AppCode：设置环境变量 ALIYUN_APPCODE，或写入 .state/aliyun_appcode.txt")

        if self._calls >= conf.budget:
            return ToolResult.failed(
                self.name,
                f"已达本次预算上限 {conf.budget} 次；确认无误后调大 config 里的 budget")

        self._calls += 1
        http = await box.http()
        url = market.build_url(conf, name)
        headers = {"Authorization": f"APPCODE {code}", "Accept": "application/json"}

        try:
            raw = await http.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001 - 网络/权限问题统一降级
            return ToolResult.failed(self.name, f"云市场接口请求失败：{exc}")

        import json

        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            return ToolResult.failed(self.name, "云市场接口返回的不是 JSON")

        rows = market.normalize(payload, conf)
        if not rows:
            # 查不到 ≠ 安全：明确说"接口没返回可解析的行"
            return ToolResult.empty(
                self.name,
                notes=[f"{conf.name} 接口没有返回可解析的风险行（公司名可能不匹配，或该源无此公司）"],
                url=url, meta={"calls": self._calls})

        return ToolResult(
            tool=self.name,
            status=AgentStatus.OK,
            data=rows,                       # ToolAgent 按行列表消费
            notes=[f"{conf.name} 返回 {len(rows)} 条"],
            url=url,
            meta={"calls": self._calls, "budget": conf.budget,
                  "profile": conf.name, "counts": {"rows": len(rows)},
                  "raw": payload})


register_tool(AliyunRiskTool)


__all__ = ["AliyunRiskTool"]
