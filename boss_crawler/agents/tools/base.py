"""工具层契约：agent 只调工具，反爬全在工具里。

设计意图（这是本次重构的核心）：

* **工具负责"怎么拿到"**：UA 轮换、请求间隔、重试、cookie/登录态、
  浏览器兜底、被挡识别、原始页面落盘——所有脏活都在工具里。
* **agent 负责"拿到什么、怎么总结"**：它不知道也不关心代理和验证码，
  只调工具、把结构化结果汇成 :class:`~boss_crawler.agents.base.Finding`。

于是加一个站点 = 加一个 Tool；换一套反爬策略 = 改 ToolBox，agent 一行不动。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..base import AgentContext, AgentStatus, MissingInput
from ..fetch import HttpFetcher, StealthBrowser, looks_blocked

# ---------------------------------------------------------------- 结果


@dataclass
class ToolResult:
    """工具的统一产出。

    ``data`` 是**已解析好的结构化数据**（行列表 / 档案 dict / 计数 dict），
    不是原始 HTML——解析属于工具的职责，这样 agent 才能只做总结。
    """

    tool: str
    status: AgentStatus
    data: Any = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    url: str | None = None
    elapsed_s: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (AgentStatus.OK, AgentStatus.PARTIAL)

    @property
    def usable(self) -> bool:
        """拿到的东西能不能用（OK/PARTIAL/EMPTY 都算"工具正常完成了工作"）。"""
        return self.status in (AgentStatus.OK, AgentStatus.PARTIAL, AgentStatus.EMPTY)

    @classmethod
    def ok_(cls, tool: str, data: Any = None, **kwargs) -> "ToolResult":
        return cls(tool=tool, status=AgentStatus.OK, data=data, **kwargs)

    @classmethod
    def partial(cls, tool: str, data: Any = None, **kwargs) -> "ToolResult":
        return cls(tool=tool, status=AgentStatus.PARTIAL, data=data, **kwargs)

    @classmethod
    def empty(cls, tool: str, **kwargs) -> "ToolResult":
        return cls(tool=tool, status=AgentStatus.EMPTY, data=[], **kwargs)

    @classmethod
    def blocked(cls, tool: str, reason: str, **kwargs) -> "ToolResult":
        return cls(tool=tool, status=AgentStatus.BLOCKED, error=reason, **kwargs)

    @classmethod
    def failed(cls, tool: str, reason: str, **kwargs) -> "ToolResult":
        return cls(tool=tool, status=AgentStatus.FAILED, error=reason, **kwargs)


@dataclass
class FetchOutcome:
    """一次页面抓取的结局。反爬链路的三种归宿都在这里。"""

    html: str = ""
    status: AgentStatus = AgentStatus.OK
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    blocked: bool = False
    via_browser: bool = False

    @property
    def ok(self) -> bool:
        return self.status is AgentStatus.OK and bool(self.html)


# ---------------------------------------------------------------- ToolBox


class ToolBox:
    """工具共享的资源箱：HTTP 客户端、浏览器、落盘目录、登录态。

    反爬策略集中在这里，所以调整节流/重试/兜底不需要碰任何工具或 agent。
    允许从 ``ctx`` 注入现成的 http/browser（测试用假实现，完全离线）。
    """

    def __init__(
        self,
        ctx: AgentContext,
        *,
        delay: float = 2.0,
        retries: int = 2,
        timeout: float = 20.0,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        state: str | None = None,
        dump_dir: str | None = None,
        allow_browser: bool = True,
        min_html_len: int = 800,
    ) -> None:
        self.ctx = ctx
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.state = state or ctx.option("state")
        self.dump_dir = dump_dir or ctx.option("dump_dir")
        self.allow_browser = allow_browser and not ctx.option("no_browser")
        self.min_html_len = min_html_len
        self._http: HttpFetcher | None = None
        self._browser: StealthBrowser | None = None
        self._owns_http = False
        self._owns_browser = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ 资源
    async def http(self) -> HttpFetcher:
        if self.ctx.http is not None:
            return self.ctx.http
        async with self._lock:
            if self._http is None:
                self._http = HttpFetcher(
                    delay=self.delay,
                    timeout=self.timeout,
                    retries=self.retries,
                    headers=self.headers,
                    cookies=self.cookies,
                )
                self._owns_http = True
            return self._http

    async def browser(self) -> StealthBrowser | None:
        if not self.allow_browser:
            return None
        if self.ctx.browser is not None:
            return self.ctx.browser
        async with self._lock:
            if self._browser is None:
                self._browser = StealthBrowser(state_file=self.state)
                self._owns_browser = True
            return self._browser

    async def close(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.close()
        if self._browser is not None and self._owns_browser:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001 - 关闭失败不值得中断流程
                pass
        self._http = None
        self._browser = None

    # ------------------------------------------------------------ 反爬链路
    async def fetch_page(
        self,
        url: str,
        *,
        is_blocked: Callable[[str], bool] | None = None,
        min_len: int | None = None,
        wait_selector: str | None = None,
    ) -> FetchOutcome:
        """取一个页面：HTTP → 被挡判定 → 浏览器兜底。

        这是整个工具层的反爬主干，各站点工具都走它，所以"怎么绕"
        只有一份实现。
        """
        check = is_blocked or (lambda html: looks_blocked(html, min_len=min_len or self.min_html_len))
        notes: list[str] = []
        http_error: str | None = None
        http_blocked = False

        client = await self.http()

        if client is not None:
            try:
                html = await client.get(url)
                self._dump(url, html)
                if not check(html):
                    return FetchOutcome(html=html)
                http_blocked = True
                notes.append("HTTP 拿到的不是正常页面（疑似被挡）")
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if _looks_like_login(message):
                    http_blocked = True
                    notes.append(f"HTTP 被要求登录：{message[:80]}")
                else:
                    http_error = message

        if self.allow_browser:
            browser = await self.browser()
            if browser is not None:
                try:
                    html = await browser.html(url, wait_selector=wait_selector)
                    self._dump(url, html)
                    if check(html):
                        return FetchOutcome(status=AgentStatus.BLOCKED, blocked=True,
                                            via_browser=True, notes=notes,
                                            error="浏览器也没有拿到正常页面")
                    return FetchOutcome(html=html, via_browser=True, notes=notes)
                except Exception as exc:  # noqa: BLE001
                    return FetchOutcome(
                        status=AgentStatus.FAILED, via_browser=True, notes=notes,
                        error=f"浏览器抓取失败：{exc}")

        if http_blocked:
            return FetchOutcome(status=AgentStatus.BLOCKED, blocked=True, notes=notes,
                                error="被登录墙或验证码挡住")
        return FetchOutcome(status=AgentStatus.FAILED, notes=notes,
                            error=http_error or "未取到内容")

    def _dump(self, url: str, html: str) -> None:
        """把原始页面落盘，便于页面改版后重新校准解析器。"""
        if not self.dump_dir or not html:
            return
        import hashlib
        import pathlib

        try:
            target = pathlib.Path(self.dump_dir)
            target.mkdir(parents=True, exist_ok=True)
            name = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
            (target / f"{name}.html").write_text(html, encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------- Tool


class Tool:
    """一个工具 = 一件事：拿到某个站点的某类数据，并解析成结构化结果。"""

    name: str = ""
    site: str = ""
    description: str = ""
    #: 需要的参数名，供 CLI/文档展示与调用校验
    params: tuple[str, ...] = ()
    #: 这个工具依赖哪些外部条件（http / browser / cli）
    requires: tuple[str, ...] = ("http",)

    async def call(self, box: ToolBox, **params: Any) -> ToolResult:  # pragma: no cover
        raise NotImplementedError

    async def execute(self, box: ToolBox, **params: Any) -> ToolResult:
        """统一入口：计时、参数校验、异常兜底。工具内部崩了不会炸掉 agent。"""
        missing = [key for key in self.params if not str(params.get(key) or "").strip()]
        if missing:
            return ToolResult.failed(self.name, f"缺少参数：{', '.join(missing)}")
        started = time.perf_counter()
        try:
            result = await self.call(box, **params)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failed(self.name, f"{type(exc).__name__}: {exc}",
                                     elapsed_s=time.perf_counter() - started)
        result.elapsed_s = round(time.perf_counter() - started, 2)
        return result

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "site": self.site,
            "description": self.description,
            "params": list(self.params),
            "requires": list(self.requires),
        }


# ---------------------------------------------------------------- 注册表

_TOOLS: dict[str, Tool] = {}


def register_tool(tool: Tool | type[Tool]) -> Tool:
    instance = tool() if isinstance(tool, type) else tool
    if not instance.name:
        raise ValueError("工具必须有 name")
    if instance.name in _TOOLS:
        raise ValueError(f"工具名重复：{instance.name}")
    _TOOLS[instance.name] = instance
    return instance


def get_tool(name: str) -> Tool:
    if name not in _TOOLS:
        raise KeyError(f"没有这个工具：{name}（可用：{', '.join(sorted(_TOOLS)) or '无'}）")
    return _TOOLS[name]


def tool_catalog() -> list[dict[str, Any]]:
    return [tool.describe() for tool in _TOOLS.values()]


def tool_names() -> list[str]:
    return sorted(_TOOLS)


def reset_tools() -> None:
    """测试用：清空注册表。"""
    _TOOLS.clear()


def _looks_like_login(message: str) -> bool:
    lowered = (message or "").lower()
    return any(hint in lowered for hint in (
        "401", "403", "unauthorized", "forbidden", "login", "登录", "未登录", "请先登录",
    ))
