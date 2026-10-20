"""引擎的数据契约：``Request`` / ``Response`` / ``Item``。

这三个类只描述「流过引擎的东西长什么样」，不含任何业务判断，也不依赖
httpx / 数据库。引擎的其它模块（调度器、下载器、管道）都只面向它们编程，
所以换数据源、换存储都不需要动引擎。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Request:
    """一次待抓取的请求。

    ``meta`` 承载业务上下文（哪家公司、哪一步、归属关系），引擎不解读它，
    只原样带到 ``Response`` 和回调里——这是 Scrapy 里 ``request.meta`` 的角色。

    ``retry_times`` 由引擎在重投时递增，业务代码不该自己改。
    """

    url: str
    params: Mapping[str, Any] = field(default_factory=dict)
    meta: Mapping[str, Any] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    priority: int = 0
    callback: str = "parse"
    dont_filter: bool = False
    retry_times: int = 0

    @property
    def fingerprint(self) -> str:
        """去重指纹：URL + 排序后的参数 + 可选的业务区分键。"""
        extra = self.meta.get("fingerprint_extra", "")
        raw = self.url + "|" + "&".join(f"{k}={self.params[k]}" for k in sorted(self.params)) + f"|{extra}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def with_retry(self) -> "Request":
        """生成一个「重试计数 +1 且不被去重」的同款请求。"""
        return Request(
            url=self.url,
            params=dict(self.params),
            meta=dict(self.meta),
            headers=dict(self.headers),
            priority=self.priority,
            callback=self.callback,
            dont_filter=True,
            retry_times=self.retry_times + 1,
        )

    def __repr__(self) -> str:  # 日志里只打必要信息，避免刷屏
        tail = self.url.rsplit("/", 2)[-1] if self.url else "?"
        return f"<Request {tail} retry={self.retry_times} key={self.meta.get('company_key', '-')}>"


@dataclass
class Response:
    """一次请求的结果（成功或失败都在这里）。"""

    request: Request
    status: int = 0
    payload: Any = None
    text: str = ""
    elapsed_ms: int = 0
    error: Exception | None = None
    error_code: int | None = None      # 业务错误码（如天眼查 error_code）
    error_reason: str = ""

    @property
    def ok(self) -> bool:
        """传输层与业务层都成功才算 ok。"""
        return self.error is None and self.status == 200 and self.error_code in (None, 0)

    @property
    def meta(self) -> Mapping[str, Any]:
        return self.request.meta


class Item(dict):
    """流过管道的一条结构化结果。

    ``item_type`` 决定交给哪个管道处理，相当于 Scrapy 里用不同 Item 类区分，
    但更轻——不需要为每种产物定义一个类。
    """

    def __init__(self, item_type: str, **fields: Any) -> None:
        super().__init__(**fields)
        self.item_type = item_type

    def __repr__(self) -> str:
        return f"<Item {self.item_type} keys={len(self)}>"
