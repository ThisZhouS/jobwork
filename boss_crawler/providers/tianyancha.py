"""天眼查开放平台（数据接口）的 HTTP 客户端。

用法::

    client = TianyanchaClient()
    hit = client.search("茶百道")            # 816，¥0.01
    ic  = client.ic(hit["id"])               # 1001，¥1.00，工商全景
    bad = client.dishonest(hit["id"])        # 843，¥0.15，失信人

约定：

* 鉴权用 ``Authorization: <token>`` 头，token 从 ``.env`` 的 ``TIANYANCHA_TOKEN``
  或 ``.state/tyc_token.txt`` 读，绝不写进代码；
* 所有接口都是 ``GET``，公共参数 ``keyword``（公司名 / 天眼查 id / 统一信用代码）；
* 返回统一包成 ``{"error_code": 0, "reason": "ok", "result": {...}}``，
  ``error_code != 0`` 时抛 :class:`TianyanchaError`，由调用方决定是否继续；
* 每次真实请求都记进 ``self.calls``，便于统计成本（:attr:`spent`）。
"""
from __future__ import annotations

import time
from typing import Any

import requests

from .. import config


class TianyanchaError(RuntimeError):
    """接口返回 ``error_code != 0``，或网络/鉴权失败。"""

    def __init__(self, message: str, *, code: int | None = None, api: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.api = api


# 这些错误码重试不会好转：token 无效、无接口权限、余额不足等
NON_RETRYABLE = {
    300000,
    300001,
    300002,
    300003,   # 余额不足
    300004,
    300009,   # 账号信息有误：token 不对或过期（实测值）
}

_HINTS = {
    300003: " -> 去开放平台充值",
    300009: " -> 检查 .env 里的 TIANYANCHA_TOKEN 是否正确/未过期",
}


def _hint(code: int | None) -> str:
    return _HINTS.get(code or 0, "")


def load_token() -> str:
    """按 ``.env`` -> ``.state/tyc_token.txt`` 的顺序取 token。"""
    if config.TYC_TOKEN:
        return config.TYC_TOKEN.strip()
    if config.TYC_TOKEN_FILE.exists():
        return config.TYC_TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


class TianyanchaClient:
    """天眼查数据接口客户端（同步、带限流与重试）。

    参数
    ----
    token:
        不传则自动从 ``.env`` / ``.state`` 读取。
    session:
        便于测试注入假 session。
    delay:
        两次请求之间的最小间隔（秒），默认 ``config.TYC_QPS_DELAY``。
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        session: requests.Session | None = None,
        delay: float | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> None:
        self.token = (token if token is not None else load_token()).strip()
        self.session = session or requests.Session()
        self.delay = config.TYC_QPS_DELAY if delay is None else delay
        self.timeout = config.TYC_TIMEOUT if timeout is None else timeout
        self.retries = config.TYC_MAX_RETRIES if retries is None else retries
        self.calls: list[dict[str, Any]] = []
        self._last_at = 0.0

    # ------------------------------------------------------------------ 基础
    @property
    def spent(self) -> float:
        """本次实例累计花费（元，按页面标价估算）。"""
        return sum(item.get("price", 0.0) for item in self.calls)

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_at)
        if wait > 0:
            time.sleep(wait)
        self._last_at = time.monotonic()

    def get(self, api: str, params: dict[str, Any]) -> dict[str, Any]:
        """调用一个接口，返回 ``result``；失败按 ``retries`` 退避重试。"""
        if not self.token:
            raise TianyanchaError(
                "缺少天眼查 token：请在 .env 写 TIANYANCHA_TOKEN=... 或放进 .state/tyc_token.txt",
                api=api,
            )
        path = config.TYC_API[api]
        url = f"{config.TYC_BASE_URL}{path}"
        headers = {
            "Authorization": self.token,
            "Accept": "application/json",
            "User-Agent": "boss-crawler/0.2 (+personal research)",
        }
        query = {k: v for k, v in params.items() if v is not None}
        last_error: Exception | None = None

        for attempt in range(self.retries):
            self._throttle()
            started = time.monotonic()
            try:
                response = self.session.get(url, params=query, headers=headers, timeout=self.timeout)
                elapsed = round((time.monotonic() - started) * 1000)
                payload = response.json()
            except Exception as exc:  # 网络/JSON 异常都重试
                last_error = exc
                time.sleep(min(2 ** attempt, 8))
                continue

            code = payload.get("error_code")
            self.calls.append(
                {
                    "api": api,
                    "keyword": query.get("keyword") or query.get("word"),
                    "code": code,
                    "http": response.status_code,
                    "ms": elapsed,
                    "price": config.TYC_PRICES.get(api, 0.0),
                }
            )
            if code == 0:
                return payload.get("result") or {}
            reason = payload.get("reason") or "unknown"
            # 这几类重试没有意义（token 错、无权限、余额不足），直接失败并给出处置建议
            if code in NON_RETRYABLE:
                raise TianyanchaError(
                    f"{api} 调用失败：{reason}（error_code={code}）{_hint(code)}",
                    code=code,
                    api=api,
                )
            last_error = TianyanchaError(f"{api} 调用失败：{reason}（error_code={code}）", code=code, api=api)
            time.sleep(min(2 ** attempt, 8))

        if isinstance(last_error, TianyanchaError):
            raise last_error
        raise TianyanchaError(f"{api} 调用失败：{last_error}", api=api)

    # ------------------------------------------------------------------ 便捷方法
    def search(self, word: str, *, page_size: int = 5) -> dict[str, Any]:
        """816 关键词搜索，返回 ``{"total": n, "items": [...]}``。"""
        return self.get("search", {"word": word, "pageSize": page_size, "pageNum": 1})

    def ic(self, keyword: str | int) -> dict[str, Any]:
        """1001 工商全景：基本信息 + 主要人员 + 股东 + 对外投资 + 分支 + 各类风险清单。"""
        return self.get("ic", {"keyword": keyword})

    def parent(self, keyword: str | int) -> dict[str, Any]:
        """963 总公司。"""
        return self.get("parent", {"keyword": keyword})

    def invest(self, keyword: str | int, *, page_num: int = 1, page_size: int = 20) -> dict[str, Any]:
        """823 对外投资（分页）。"""
        return self.get("invest", {"keyword": keyword, "pageNum": page_num, "pageSize": page_size})

    def dishonest(self, keyword: str | int, *, page_num: int = 1, page_size: int = 20) -> dict[str, Any]:
        """843 失信人。"""
        return self.get("dishonest", {"keyword": keyword, "pageNum": page_num, "pageSize": page_size})

    def zhixing(self, keyword: str | int, *, page_num: int = 1, page_size: int = 20) -> dict[str, Any]:
        """839 被执行人。"""
        return self.get("zhixing", {"keyword": keyword, "pageNum": page_num, "pageSize": page_size})
