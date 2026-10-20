"""下载器中间件：在请求发出前、响应返回后插入可插拔的处理。

对标 Scrapy 的 ``DownloaderMiddleware``。三个钩子都是可选的，实现哪个就
在哪个阶段生效：

* :meth:`process_request` —— 出发前：加头、加签名；返回 ``None`` 表示丢弃；
* :meth:`process_response` —— 回来后：解析、纠错、记录；
* :meth:`process_exception` —— 网络异常时：可转成响应，也可放行。

新增一个中间件只需写一个类并注册进 ``MIDDLEWARES``，引擎不用改。
"""
from __future__ import annotations

from typing import Any

from .item import Request, Response


class DownloaderMiddleware:
    """中间件基类。默认全部放行。"""

    def process_request(self, request: Request) -> Request | None:
        return request

    def process_response(self, response: Response) -> Response | None:
        return response

    def process_exception(self, request: Request, exception: Exception) -> Response | None:
        return None


class HeaderMiddleware(DownloaderMiddleware):
    """统一注入请求头（token、UA、Accept）。"""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = dict(headers or {})

    def process_request(self, request: Request) -> Request | None:
        if not self.headers:
            return request
        merged = {**self.headers, **dict(request.headers)}
        return _replace_headers(request, merged)


class JsonMiddleware(DownloaderMiddleware):
    """把 ``Response.text`` 解析成 ``payload``，并抽出业务错误码。

    ``error_code_field`` 指定业务错误码字段名（天眼查是 ``error_code``）。
    解析失败时保留原响应，交给重试或 spider 处理。
    """

    def __init__(self, error_code_field: str = "error_code", reason_field: str = "reason") -> None:
        self.error_code_field = error_code_field
        self.reason_field = reason_field

    def process_response(self, response: Response) -> Response | None:
        if response.payload is not None or not response.text:
            return response
        import json

        try:
            payload = json.loads(response.text)
        except (ValueError, TypeError):
            return response
        response.payload = payload
        if isinstance(payload, dict):
            code = payload.get(self.error_code_field)
            if code is not None:
                try:
                    response.error_code = int(code)
                except (TypeError, ValueError):
                    response.error_code = None
            response.error_reason = str(payload.get(self.reason_field) or "")
        return response


class LoggingMiddleware(DownloaderMiddleware):
    """把每次请求/响应的关键信息喂给 logger（默认 debug 级，不刷屏）。"""

    def __init__(self, logger: Any) -> None:
        self.logger = logger

    def process_request(self, request: Request) -> Request | None:
        if hasattr(self.logger, "debug"):
            self.logger.debug(f"-> {request}")
        return request

    def process_response(self, response: Response) -> Response | None:
        if hasattr(self.logger, "debug"):
            state = "ok" if response.ok else f"fail(status={response.status}, code={response.error_code})"
            self.logger.debug(f"<- {response.request} {state} {response.elapsed_ms}ms")
        return response


def _replace_headers(request: Request, headers: dict[str, str]) -> Request:
    return Request(
        url=request.url,
        params=dict(request.params),
        meta=dict(request.meta),
        headers=headers,
        priority=request.priority,
        callback=request.callback,
        dont_filter=request.dont_filter,
        retry_times=request.retry_times,
    )


def build_middlewares(settings, logger: Any = None, extra: list[DownloaderMiddleware] | None = None) -> list[DownloaderMiddleware]:
    """按顺序组装中间件链。

    顺序有意义：请求阶段**从上到下**，响应阶段**从下到上**（与 Scrapy 一致），
    所以解析类中间件要放在接近下载器的位置。
    """
    chain: list[DownloaderMiddleware] = []
    default_headers = settings.get("DEFAULT_HEADERS") or {}
    if default_headers:
        chain.append(HeaderMiddleware(default_headers))
    chain.append(JsonMiddleware(
        error_code_field=settings.get("ERROR_CODE_FIELD", "error_code"),
        reason_field=settings.get("ERROR_REASON_FIELD", "reason"),
    ))
    if logger is not None:
        chain.append(LoggingMiddleware(logger))
    chain.extend(extra or [])
    return chain
