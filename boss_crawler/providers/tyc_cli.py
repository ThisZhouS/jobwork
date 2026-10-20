"""天眼AI（tyc-cli）适配器：免费替代付费 REST 接口。

为什么需要这一层
----------------
付费开放平台的接口有充值门槛（100 / 1000 元起），而天眼查自家提供了
免费接入：``npm install -g tyc-cli`` + ``tyc login``，共 162 个工具。
本模块把它的命令行包成可测试的 Python 接口，使背调链路从「按次付费」
切换到「免费额度」，且**不改变上层数据结构**。

免费额度（实测 ``tyc <类别>`` 输出里的「数据权益」字段，2026-10）：

============================  ==========================================
工具                          能给到的东西
============================  ==========================================
``company companies``         实体锚定：名称 -> id / 信用代码 / 登记状态
``company registration-info`` 核心工商：信用代码、登记状态、法人、注册资本、
                              成立日期、地址、经营范围
``risk overview``             风险总览：自身 / 周边 / 预警风险
``company profile``           企业简介文本
``company scale``             规模等级
``company tags``              标签画像（领域、主营、榜单）
``intellectual_property ipr-score``  创新力评分
``operation bids``            招投标
============================  ==========================================

需要 VIP/SVIP 的（宽限期已于 2026-09-01 结束）：对外投资 ``external-investments``、
分支机构 ``branches``、股权穿透 ``equity-tree``、控制企业 ``controlled-companies``、
年报、联系方式、历史信息、失信/被执行明细等。

结论：求职背调要判断「公司靠不靠谱」，免费部分（工商 + 风险总览 + 规模 + 简介）
已经够用；完整股权树与风险明细才需要付费。
"""
from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any, Callable

# 实测确认可用的免费工具（免费会员可用）
FREE_TOOLS: tuple[str, ...] = (
    "company.companies",
    "company.registration-info",
    "company.profile",
    "company.scale",
    "company.tags",
    "company.logo",
    "risk.overview",
    "operation.bids",
    "intellectual_property.ipr-score",
)

# 需要 VIP 及以上的常用维度：代码里显式列出来，避免调用后才发现扣不了额度
VIP_TOOLS: tuple[str, ...] = (
    "company.external-investments",
    "company.equity-tree",
    "company.controlled-companies",
    "company.branches",
    "company.annual-reports",
    "company.contact-info",
    "company.change-records",
    "history.historical-overview",
    "executive.person-profile",
)

_NOT_INSTALLED_HINT = "未安装 tyc-cli：npm install -g tyc-cli"
_NOT_AUTHED_HINTS = ("未配置 Authorization", "tyc init --authorization", "未登录", "401", "unauthorized")


class TycCliError(RuntimeError):
    """CLI 调用失败。``kind`` 便于上层区分「该提示登录」还是「该报 bug」。"""

    def __init__(self, message: str, *, kind: str = "cli_error", code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind          # not_installed / not_authed / timeout / bad_json / cli_error
        self.code = code

    @property
    def needs_login(self) -> bool:
        return self.kind == "not_authed"


def _default_exec(args: list[str], timeout: float) -> tuple[int, str, str]:
    """同步执行 CLI。返回 (returncode, stdout, stderr)。"""
    import subprocess

    completed = subprocess.run(  # noqa: S603 - args 是列表，无 shell 注入面
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout,
    )
    return completed.returncode, completed.stdout, completed.stderr


class TycCli:
    """天眼AI 命令行封装。

    参数
    ----
    command:
        可执行文件路径，默认 ``tyc``。
    timeout:
        单次调用超时（秒）。
    exec:
        注入点，签名 ``(args, timeout) -> (code, out, err)``。
        测试时传入假的即可完全离线，不依赖真的装了 tyc。
    """

    def __init__(
        self,
        *,
        command: str = "tyc",
        timeout: float = 60.0,
        exec: Callable[[list[str], float], tuple[int, str, str]] | None = None,
    ) -> None:
        self.command = command
        self.timeout = timeout
        self._exec = exec or _default_exec
        self._resolved: str | None = None

    # ------------------------------------------------------------ 可用性
    def _resolve(self) -> str:
        """找到真正可执行的路径。

        Windows 上 npm 会同时生成 ``tyc``（无扩展名的 shell 脚本）、``tyc.cmd``、
        ``tyc.ps1``。``shutil.which("tyc")`` 很可能命中那个无扩展名脚本，
        而 CreateProcess 执行它会报 WinError 2，所以必须优先挑 .cmd/.exe。
        """
        if self._resolved is not None:
            return self._resolved
        import os

        candidates = [self.command]
        if os.name == "nt":
            candidates = [f"{self.command}{ext}" for ext in (".cmd", ".exe", ".bat")] + candidates
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                self._resolved = found
                return found
        self._resolved = ""
        return ""

    @property
    def installed(self) -> bool:
        return bool(self._resolve())

    def require_installed(self) -> None:
        if not self.installed:
            raise TycCliError(_NOT_INSTALLED_HINT, kind="not_installed")

    # ------------------------------------------------------------ 调用
    def call(self, tool: str, *args: str, compact: bool = True) -> Any:
        """调用一个工具并把 JSON 解析出来。``tool`` 形如 ``company registration-info``。"""
        executable = self._resolve()
        if not executable:
            raise TycCliError(_NOT_INSTALLED_HINT, kind="not_installed")
        argv = [executable, *tool.split(), *args]
        if compact:
            argv.append("--compact")
        try:
            code, out, err = self._exec(argv, self.timeout)
        except FileNotFoundError as exc:
            raise TycCliError(_NOT_INSTALLED_HINT, kind="not_installed") from exc
        except Exception as exc:  # noqa: BLE001 - 超时等统一归一
            raise TycCliError(f"调用失败：{exc}", kind="timeout") from exc

        if code != 0:
            detail = (err or out or "").strip()
            kind = "not_authed" if _looks_unauthed(detail) else "cli_error"
            raise TycCliError(f"tyc 返回 {code}：{detail[:300]}", kind=kind, code=code)

        return _parse_json(out)

    async def acall(self, tool: str, *args: str, compact: bool = True) -> Any:
        """异步版：把阻塞的 subprocess 丢到线程池，避免卡住事件循环。"""
        return await asyncio.to_thread(self.call, tool, *args, compact=compact)

    # ------------------------------------------------------------ 语义方法
    def anchor(self, name: str) -> list[dict]:
        """实体锚定：模糊名 -> 精确企业候选。"""
        return _items(self.call("company companies", name))

    def registration(self, name: str) -> dict:
        """核心工商信息。免费会员拿不到完整联系方式，属预期。"""
        return _payload(self.call("company registration-info", name))

    def risk_overview(self, name: str) -> dict:
        """风险总览：自身 / 周边 / 预警。免费额度里最有价值的一个。"""
        return _payload(self.call("risk overview", name))

    def profile(self, name: str) -> dict:
        return _payload(self.call("company profile", name))

    def scale(self, name: str) -> dict:
        return _payload(self.call("company scale", name))

    def tags(self, name: str) -> dict:
        return _payload(self.call("company tags", name))

    def ipr_score(self, name: str) -> dict:
        return _payload(self.call("intellectual_property ipr-score", name))

    def bids(self, name: str) -> dict:
        return _payload(self.call("operation bids", name))

    # ------------------------------------------------------------ 批量
    def basic_bundle(self, name: str) -> dict:
        """一次拿免费里最值得拿的几项。单项失败不影响其他项。

        顺序刻意是「先锚定再取详情」：锚定失败时后面的工具也会失败，
        但那样报错信息会指向真正的原因。
        """
        bundle: dict[str, Any] = {"query": name, "items": [], "errors": {}}
        try:
            bundle["items"] = self.anchor(name)
        except TycCliError as exc:
            bundle["errors"]["anchor"] = str(exc)
            if exc.kind in ("not_installed", "not_authed"):
                raise
        for key, fn in (
            ("registration", self.registration),
            ("risk", self.risk_overview),
            ("profile", self.profile),
            ("scale", self.scale),
            ("tags", self.tags),
            ("ipr_score", self.ipr_score),
        ):
            try:
                bundle[key] = fn(name)
            except TycCliError as exc:
                bundle["errors"][key] = str(exc)
        return bundle


# ---------------------------------------------------------------- 解析
def _looks_unauthed(text: str) -> bool:
    lowered = (text or "").lower()
    return any(hint.lower() in lowered for hint in _NOT_AUTHED_HINTS)


def _parse_json(text: str) -> Any:
    """CLI 正常输出是 JSON。夹杂提示行时，取第一个能解析的 JSON 片段。"""
    raw = (text or "").strip()
    if not raw:
        raise TycCliError("tyc 无输出", kind="bad_json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
            return value
        except json.JSONDecodeError:
            continue
    raise TycCliError(f"tyc 输出不是 JSON：{raw[:200]}", kind="bad_json")


def _payload(value: Any) -> dict:
    """统一取出业务数据：有的工具返回 {data: ...}，有的是裸对象。"""
    if isinstance(value, dict):
        for key in ("data", "result", "items"):
            if key in value and isinstance(value[key], (dict, list)):
                inner = value[key]
                return inner if isinstance(inner, dict) else {"items": inner}
        return value
    if isinstance(value, list):
        return {"items": value}
    return {"value": value}


def _items(value: Any) -> list[dict]:
    """候选列表：兼容 list / {items: []} / {data: {items: []}} 等形状。"""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("items", "data", "result", "list"):
            inner = value.get(key)
            if isinstance(inner, list):
                return [v for v in inner if isinstance(v, dict)]
            if isinstance(inner, dict):
                return _items(inner)
    return []


__all__ = [
    "FREE_TOOLS",
    "VIP_TOOLS",
    "TycCli",
    "TycCliError",
]
