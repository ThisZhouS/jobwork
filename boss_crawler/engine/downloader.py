"""下载器：异步发请求，负责并发上限、主机级限速与传输层错误转换。

对标 Scrapy 的 ``Downloader`` + ``AutoThrottle`` 扩展。这一层**只管传输**：
不判断业务错误码该不该重试（那是 :mod:`boss_crawler.engine.retry` 的事），
也不知道 response 里是什么业务含义（那是 spider 的事）。

并发由 ``asyncio.Semaphore`` 控制；限速按**主机**记录上次请求时间，同一主机的
请求不会挤在一起。传输层不重试——重试统一交给引擎，避免两处退避逻辑打架。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit

from .item import Request, Response
from .middleware import DownloaderMiddleware
from .settings import Settings


class HostThrottle:
    """按主机限速。``AUTOTHROTTLE`` 打开时按实测延迟自适应。"""

    def __init__(self, delay: float, *, auto: bool = True, target: float = 1.2,
                 max_delay: float = 8.0) -> None:
        self.base_delay = max(delay, 0.0)
        self.auto = auto
        self.target = max(target, 1.0)
        self.max_delay = max(max_delay, self.base_delay)
        self._last: dict[str, float] = {}
        self._delay: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def current_delay(self, host: str) -> float:
        return self._delay.get(host, self.base_delay)

    async def wait(self, host: str) -> None:
        """必要时等待，保证同一主机的请求间隔。"""
        if self.base_delay <= 0 and not self.auto:
            return
        async with self._lock:
            now = time.monotonic()
            last = self._last.get(host)
            delay = self.current_delay(host)
            if last is not None:
                remaining = delay - (now - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    now = time.monotonic()
            self._last[host] = now

    def observe(self, host: str, elapsed: float) -> None:
        """根据本次耗时调整下一轮的间隔（简化版 AutoThrottle）。"""
        if not self.auto:
            return
        target = elapsed * self.target
        previous = self.current_delay(host)
        # 平滑移动，避免一次慢请求把节奏拉到最长
        adjusted = (previous * 0.7) + (max(target, self.base_delay) * 0.3)
        self._delay[host] = round(min(max(adjusted, self.base_delay), self.max_delay), 3)


class _TransportProtocol:
    """传输层协议：只要能 ``fetch(url, params, headers, timeout) -> (status, text, ms)``。"""

    async def fetch(self, url: str, params: dict, headers: dict, timeout: float) -> tuple[int, str, int]:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class HttpxTransport(_TransportProtocol):
    """基于 httpx.AsyncClient 的真实传输实现（惰性导入，便于离线测试替换）。"""

    def __init__(self, timeout: float = 20.0) -> None:
        import httpx

        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def fetch(self, url: str, params: dict, headers: dict, timeout: float) -> tuple[int, str, int]:
        started = time.monotonic()
        response = await self._client.get(url, params=params, headers=headers, timeout=timeout)
        elapsed = int((time.monotonic() - started) * 1000)
        return response.status_code, response.text, elapsed

    async def close(self) -> None:
        await self._client.aclose()


class Downloader:
    """把 ``Request`` 变成 ``Response``，带并发上限、限速与中间件。"""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: _TransportProtocol | None = None,
        middlewares: list[DownloaderMiddleware] | None = None,
        stats: Any = None,
        logger: Any = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or HttpxTransport(float(settings.get("DOWNLOAD_TIMEOUT", 20.0)))
        # 不传就按配置自建：否则注入自定义 transport 时会静默丢掉 JSON 解析，
        # 导致 body 里的业务错误码永远读不到、业务级重试失效。
        if middlewares is None:
            from .middleware import build_middlewares

            middlewares = build_middlewares(settings, logger)
        self.middlewares = middlewares
        self.stats = stats
        self.semaphore = asyncio.Semaphore(max(1, int(settings.get("CONCURRENT_REQUESTS", 6))))
        self.throttle = HostThrottle(
            float(settings.get("DOWNLOAD_DELAY", 0.0)),
            auto=bool(settings.get("AUTOTHROTTLE", True)),
            target=float(settings.get("AUTOTHROTTLE_TARGET", 1.2)),
            max_delay=float(settings.get("AUTOTHROTTLE_MAX_DELAY", 8.0)),
        )
        self.timeout = float(settings.get("DOWNLOAD_TIMEOUT", 20.0))

    # ---------------------------------------------------------------- 主流程
    async def fetch(self, request: Request) -> Response:
        """执行一次请求（不含重试）。任何异常都转成 ``Response.error``。"""
        outgoing = request
        for middleware in self.middlewares:
            maybe = middleware.process_request(outgoing)
            if maybe is None:
                return Response(request=outgoing, status=0, error=RuntimeError("request dropped by middleware"))
            outgoing = maybe

        host = urlsplit(outgoing.url).netloc
        async with self.semaphore:
            await self.throttle.wait(host)
            try:
                status, text, elapsed = await self.transport.fetch(
                    outgoing.url, dict(outgoing.params), dict(outgoing.headers), self.timeout
                )
                response = Response(request=outgoing, status=status, text=text, elapsed_ms=elapsed)
            except Exception as exc:  # 网络异常：先给中间件机会转换
                response = None
                for middleware in reversed(self.middlewares):
                    converted = middleware.process_exception(outgoing, exc)
                    if converted is not None:
                        response = converted
                        break
                if response is None:
                    response = Response(request=outgoing, status=0, error=exc)
            else:
                self.throttle.observe(host, elapsed / 1000.0)

        # 响应阶段按相反顺序过链（与请求阶段对称）
        for middleware in reversed(self.middlewares):
            maybe = middleware.process_response(response)
            if maybe is None:
                return Response(request=outgoing, status=0, error=RuntimeError("response dropped by middleware"))
            response = maybe
        return response

    async def close(self) -> None:
        await self.transport.close()
