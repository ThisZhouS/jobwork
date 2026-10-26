"""平台登录：弹出有头浏览器，让用户自己登，然后把登录态留下来。

设计取舍：

* **不做自动登录**。用户名密码、短信、滑块都不该由程序代劳——那既不可靠
  也不合规。程序只负责"把窗口弹出来 + 等 + 记住"。
* 登录态用**持久化浏览器 profile**（``user_data_dir``）保存，不是导出 cookie
  再回填。这样滑块、设备指纹之类的上下文一起被保留，下次直接可用。
* 判定"登录成功"用**关键 cookie 是否出现**，不用页面文本——各平台成功后的
  跳转和文案都不一样，cookie 更稳定。
"""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

Emit = Callable[[dict], Any]


@dataclass(frozen=True)
class PlatformLogin:
    key: str
    label: str
    url: str
    #: 出现其中任意一个 cookie 即视为已登录
    signal_cookies: tuple[str, ...]
    note: str = ""


PLATFORMS: dict[str, PlatformLogin] = {
    "tianyancha": PlatformLogin(
        "tianyancha", "天眼查", "https://www.tianyancha.com/login",
        ("TYCID", "auth_token", "tyc-user-info"),
        "不登录也能查基础工商，登录后能看更多明细",
    ),
    "zhihu": PlatformLogin(
        "zhihu", "知乎", "https://www.zhihu.com/signin",
        ("z_c0",), "不登录只能看极少量内容，建议登录",
    ),
    "weibo": PlatformLogin(
        "weibo", "微博", "https://passport.weibo.com/sso/signin",
        ("SUB",), "移动端接口多数免登录，登录后结果更全",
    ),
    "tieba": PlatformLogin(
        "tieba", "百度贴吧", "https://tieba.baidu.com/",
        ("BDUSS",), "多数帖子免登录可看，登录后翻页更稳",
    ),
    "boss": PlatformLogin(
        "boss", "BOSS直聘", "https://www.zhipin.com/web/user/?ka=header-login",
        ("bst", "geek_zp_token", "__zp_stoken__"),
        "爬岗位需要登录；登录后仍需注意频控",
    ),
}


def login_platforms() -> list[dict]:
    return [{"key": p.key, "label": p.label, "note": p.note} for p in PLATFORMS.values()]


def state_dir_for(platform: str, root: str | Path = ".state/login") -> Path:
    return Path(root) / platform


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def login(platform: str, *, state_root: str | Path = ".state/login",
                timeout: float = 300.0, poll: float = 2.0,
                emit: Emit | None = None) -> dict:
    """弹出浏览器等用户登录。返回 ``{platform, ok, state, reason}``。"""
    cfg = PLATFORMS.get(platform)
    if cfg is None:
        return {"platform": platform, "ok": False,
                "reason": f"未知平台：{platform}（可用：{'、'.join(PLATFORMS)}）"}

    directory = state_dir_for(platform, state_root)
    directory.mkdir(parents=True, exist_ok=True)
    if emit:
        emit({"type": "login", "platform": platform, "status": "opening",
              "message": f"正在打开 {cfg.label} 登录页，请在浏览器窗口里完成登录"})

    session = None
    try:
        try:
            from scrapling.fetchers import AsyncStealthySession as SessionClass
        except Exception:  # noqa: BLE001 - 老版本只有同步实现
            from scrapling.fetchers import StealthySession as SessionClass  # type: ignore[assignment]

        from ..crawl.browser import stealth_source

        session = SessionClass(  # type: ignore[call-arg]
            headless=False,
            user_data_dir=str(directory),
            source=stealth_source(),
        )
        await _maybe_await(session.start())

        # 不能用 session.fetch()：它在返回后会关闭页面，持久化 context 里
        # 只有这一个标签页时，整个浏览器窗口会跟着消失。登录必须自己建页并保持打开。
        context = getattr(session, "context", None)
        if context is None:
            raise RuntimeError("浏览器上下文未就绪")
        page = await _maybe_await(context.new_page())
        try:
            await _maybe_await(page.goto(
                cfg.url, referer="https://www.google.com/",
                wait_until="domcontentloaded", timeout=45_000))
        except Exception as exc:  # noqa: BLE001 - 页面慢不该导致窗口直接关掉
            if emit:
                emit({"type": "login", "platform": platform, "status": "waiting",
                      "message": f"{cfg.label} 页面加载较慢（{type(exc).__name__}），"
                                 "窗口已打开，可手动继续登录"})
        if emit:
            emit({"type": "login", "platform": platform, "status": "waiting",
                  "message": f"等待 {cfg.label} 登录完成（最多 {int(timeout)} 秒）"})

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await _has_signal(session, cfg.signal_cookies):
                if emit:
                    emit({"type": "login", "platform": platform, "status": "done",
                          "message": f"{cfg.label} 登录成功，登录态已保存"})
                return {"platform": platform, "ok": True, "state": str(directory)}
            await asyncio.sleep(poll)
        return {"platform": platform, "ok": False, "state": str(directory),
                "reason": f"等待 {int(timeout)} 秒仍未检测到登录态（可在登录页手动登录后重试）"}
    except Exception as exc:  # noqa: BLE001 - 登录失败要能说清原因
        message = f"{type(exc).__name__}: {exc}"
        if emit:
            emit({"type": "login", "platform": platform, "status": "failed",
                  "message": message})
        return {"platform": platform, "ok": False, "reason": message}
    finally:
        if session is not None:
            try:
                await _maybe_await(session.close())
            except Exception:  # noqa: BLE001
                pass


async def _has_signal(session, names: tuple[str, ...]) -> bool:
    """检查持久化 context 里有没有关键 cookie。"""
    try:
        context = getattr(session, "context", None)
        if context is None:
            return False
        cookies = await _maybe_await(context.cookies())
    except Exception:  # noqa: BLE001 - 窗口被用户关掉时这里会抛
        return False
    return any(cookie.get("name") in names for cookie in (cookies or []))


async def login_all(platforms: list[str], *, store=None, state_root: str | Path = ".state/login",
                    timeout: float = 300.0, emit: Emit | None = None) -> dict:
    """按顺序登多个平台。用户关掉窗口就跳到下一个。"""
    results = []
    for platform in platforms:
        result = await login(platform, state_root=state_root, timeout=timeout, emit=emit)
        results.append(result)
        if store is not None:
            try:
                store.set_login(platform, str(result.get("state") or ""),
                                bool(result.get("ok")), result.get("reason"))
            except Exception:  # noqa: BLE001 - 记账失败不影响登录本身
                pass
    return {"results": results, "ok": all(r.get("ok") for r in results) if results else True}
