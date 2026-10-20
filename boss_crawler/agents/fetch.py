"""抓取层：HTTP 优先，被墙了再用浏览器。

为什么不直接用浏览器：启动 Chromium 要几秒且吃内存，而贴吧、部分知乎页面
用 HTTP 就能拿到。所以默认先用 :class:`HttpFetcher`，命中登录墙/验证码特征
时再升级到 :class:`StealthBrowser`。
"""
from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

# 出现这些特征说明拿到的不是正常内容。
# 刻意用完整短语而不是"验证""登录"这种词：正常页面的导航栏和 JS 包里到处都有它们。
_BLOCK_HINTS = (
    "请输入验证码",
    "安全验证",
    "访问过于频繁",
    "访问受限",
    "unusual traffic",
    "please verify you are human",
    "verify you are human",
    "403 forbidden",
    "请先登录后查看",
    "登录后查看完整",
    "系统检测到",
)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.S | re.I)

_UA_POOL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
)

#: 默认请求头。少了 Accept / Accept-Language，不少站点会直接返回挑战页。
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def looks_blocked(html: str, *, min_len: int = 800) -> bool:
    """粗判是否被挡。

    先剥掉 script/style 再找特征词——真实站点的 JS 包里常出现 captcha 这类
    变量名，直接在整页 HTML 上匹配会把正常页面误判成被拦截（实测天眼查
    搜索页 523KB 就是这样被误杀的）。
    """
    if html is None:
        return True
    text = html.strip()
    if len(text) < min_len:
        return True
    visible = _SCRIPT_STYLE_RE.sub(" ", text).lower()
    return any(hint.lower() in visible for hint in _BLOCK_HINTS)


class HttpFetcher:
    """带主机限速与重试的异步 HTTP 客户端。

    复用 ``engine.RetryPolicy``，让抓取层与爬虫引擎的退避语义保持一致。
    """

    def __init__(
        self,
        *,
        delay: float = 1.0,
        timeout: float = 20.0,
        retries: int = 2,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        retry_policy: Any = None,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.headers = dict(headers or {})
        self.cookies = dict(cookies or {})
        self._last: dict[str, float] = {}
        self._client: Any = None
        if retry_policy is None:
            from ..engine import RetryPolicy

            retry_policy = RetryPolicy(times=retries, backoff_base=1.0, backoff_max=10.0)
        self.retry_policy = retry_policy

    # -------------------------------------------------------------- 生命周期
    async def _ensure_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": random.choice(_UA_POOL), **DEFAULT_HEADERS, **self.headers},
                cookies=self.cookies or None,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _throttle(self, url: str) -> None:
        host = _host_of(url)
        last = self._last.get(host)
        if last is not None:
            wait = self.delay - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last[host] = time.monotonic()

    # -------------------------------------------------------------- 抓取
    async def get(self, url: str, **kwargs: Any) -> str:
        """取文本。重试用尽仍失败则抛异常，让上层决定是否升级到浏览器。"""
        client = await self._ensure_client()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            await self._throttle(url)
            try:
                response = await client.get(url, **kwargs)
                if response.status_code in (408, 425, 429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response.text
            except Exception as exc:  # noqa: BLE001 - 统一转成重试
                last_error = exc
                if attempt >= self.retries:
                    break
                await asyncio.sleep(self.retry_policy.delay_for(attempt + 1))
        raise RuntimeError(f"抓取失败：{url}（{last_error}）")

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        import json

        return json.loads(await self.get(url, **kwargs))


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


class StealthBrowser:
    """把 scrapling 的 ``StealthySession`` 包成「取 HTML」的接口。

    与 BOSS 采集复用同一套隐身实现（``crawl.browser.stealth_source``），
    但这里刻意不认识任何业务：只负责打开链接、等元素、返回 HTML。
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        state_file: str | None = None,
        timeout_ms: int = 30000,
    ) -> None:
        self.headless = headless
        self.state_file = state_file
        self.timeout_ms = timeout_ms
        self._session: Any = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> Any:
        if self._session is not None:
            return self._session
        from ..crawl.browser import stealth_source

        try:
            from scrapling.fetchers import StealthySession
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"scrapling 不可用：{exc}") from exc

        kwargs: dict[str, Any] = {"headless": self.headless, "source": stealth_source()}
        if self.state_file:
            kwargs["user_data_dir"] = self.state_file
        self._session = StealthySession(**kwargs)
        started = self._session.start()
        if asyncio.iscoroutine(started):
            await started
        return self._session

    async def html(self, url: str, *, wait_selector: str | None = None) -> str:
        """打开页面并返回渲染后的 HTML。同一实例内串行，避免并发抢同一个浏览器。"""
        async with self._lock:
            session = await self._ensure()
            response = session.fetch(url, wait_selector=wait_selector, timeout=self.timeout_ms)
            if asyncio.iscoroutine(response):
                response = await response
            return _html_of(response)

    async def close(self) -> None:
        if self._session is not None:
            result = self._session.close()
            if asyncio.iscoroutine(result):
                await result
            self._session = None


def _html_of(response: Any) -> str:
    """兼容 scrapling 不同版本/不同 carrier 的返回值。"""
    for attr in ("html_content", "text", "body"):
        value = getattr(response, attr, None)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, bytes) and value:
            return value.decode("utf-8", errors="ignore")
    if isinstance(response, str):
        return response
    return ""
