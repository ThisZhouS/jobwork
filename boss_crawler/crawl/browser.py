"""浏览器会话：persistent profile + stealth init script + 销毁恢复。

为什么用 persistent profile：
  BOSS直聘 的登录态由一组 httpOnly Cookie（zp_at 等）承载，`document.cookie`
  读不到，复制可见 Cookie 会被服务端判为「登录状态已失效」（code 7）。
  因此让 scrapling 启动的 chromium 使用固定 user_data_dir，登录一次即可长期复用。

为什么需要恢复逻辑：
  命中风控时页面会 `window.close()` / 跳 `about:blank`（会话页面销毁）。
  stealth.js 已经把这两条路堵住，但服务端仍可能整体跳转，所以外层再加
  健康检查 + 重建页面，保证一次抓取任务不会因为单页被销毁而中断。
"""
from __future__ import annotations

import random
import time
from functools import lru_cache
from pathlib import Path

from scrapling.fetchers import StealthySession

from .. import config


@lru_cache(maxsize=1)
def stealth_source() -> str:
    """stealth.js 的源码；只读一次。"""
    return config.STEALTH_JS.read_text(encoding="utf-8")


class LoginRequired(RuntimeError):
    """登录态缺失或已失效。"""


class BrowserUnavailable(RuntimeError):
    """浏览器无法启动 / 页面无法重建。"""


class PageDestroyed(RuntimeError):
    """会话页面被站点销毁（about:blank / Target closed）。"""


def human_sleep(bounds: tuple[float, float]) -> None:
    time.sleep(random.uniform(*bounds))


class BossBrowser:
    def __init__(
        self,
        *,
        headless: bool = False,
        profile_dir: Path | None = None,
        timeout_ms: int = 45_000,
        init_script: bool = True,
    ) -> None:
        self.headless = headless
        self.profile_dir = Path(profile_dir or config.PROFILE_DIR)
        self.timeout_ms = timeout_ms
        self.init_script = init_script
        self._session: StealthySession | None = None
        self.context = None
        self._page = None

    # ------------------------------------------------------------------ lirecycle
    def start(self) -> "BossBrowser":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict = dict(
            headless=self.headless,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_data_dir=str(self.profile_dir),
            timeout=self.timeout_ms,
            max_pages=3,
            wait=600,
            network_idle=False,
            # 不要 disable_resources：丢图片/字体本身就是明显的自动化特征
            disable_resources=False,
            # 用 patchright 自带的 chromium（与系统 Chrome 版本对齐即可）
            real_chrome=False,
            extra_flags=["--lang=zh-CN", "--disable-blink-features=AutomationControlled"],
        )
        try:
            self._session = StealthySession(**kwargs)
            self._session.start()
        except Exception as exc:  # 常见：profile 被另一个实例占用
            raise BrowserUnavailable(
                f"浏览器启动失败（若已有实例在跑，请先关闭它）：{exc}"
            ) from exc

        self.context = self._session.context
        return self

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None
                self.context = None
                self._page = None

    def __enter__(self) -> "BossBrowser":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------ pages
    def new_page(self, *, goto: str | None = None):
        if self.context is None:
            raise BrowserUnavailable("浏览器尚未启动")
        page = self.context.new_page()
        page.set_default_navigation_timeout(self.timeout_ms)
        page.set_default_timeout(self.timeout_ms)
        self._page = page
        if goto:
            self.goto(page, goto)
        return page

    def page(self, *, goto: str | None = None):
        """复用一个存活页面，页面被销毁则重建。"""
        if self._page is not None and self.alive(self._page):
            return self._page
        return self.new_page(goto=goto)

    def arm(self, page) -> bool:
        """注入反检测脚本（console 探测 / 页面自毁）。

        为什么不用 init_script：scrapling 走的是 patchright 的
        add_init_script，而 patchright 用路由注入实现，实测不生效。
        这里在每次导航后立即注入；页面脚本的探测是周期性的，因此后置注入
        依然能覆盖后续探测。
        """
        if not self.init_script:
            return False
        try:
            page.evaluate(stealth_source())
            return True
        except Exception:
            return False

    def armed(self, page) -> bool:
        try:
            return page.evaluate("() => window.__bc_stealth__ === 'v1'") is True
        except Exception:
            return False

    def ensure_armed(self, page) -> None:
        if not self.armed(page):
            self.arm(page)

    def alive(self, page) -> bool:
        if page is None:
            return False
        try:
            if page.is_closed():
                return False
            url = page.url
        except Exception:
            return False
        # 会话页面销毁的典型终态
        return bool(url) and not url.startswith("about:blank")

    def goto(self, page, url: str, *, retries: int = 2) -> bool:
        """导航；页面在导航中被销毁时重建页面再试。"""
        for attempt in range(retries + 1):
            try:
                page.goto(url, wait_until="load", timeout=self.timeout_ms)
                time.sleep(random.uniform(1.0, 2.0))
                self.arm(page)
                return True
            except Exception:
                if attempt >= retries:
                    return False
                page = self._rebuild(goto=url)
        return False

    def _rebuild(self, *, goto: str | None = None):
        try:
            if self._page is not None:
                self._page.close()
        except Exception:
            pass
        try:
            self._page = None
            return self.new_page(goto=goto)
        except Exception as exc:
            raise BrowserUnavailable(f"页面重建失败：{exc}") from exc

    # ------------------------------------------------------------------ login
    def cookie_names(self) -> set[str]:
        if self.context is None:
            return set()
        return {c.get("name", "") for c in self.context.cookies()}

    def is_logged_in(self, *, verify: bool = True) -> bool:
        names = self.cookie_names()
        if "zp_at" not in names or "bst" not in names:
            return False
        if not verify:
            return True
        try:
            page = self.page()
            if not page.url.startswith("https://www.zhipin.com"):
                self.goto(page, config.HOME_URL)
            return self.account_status(page).get("code") == 0
        except Exception:
            return False

    def account_status(self, page) -> dict:
        return page.evaluate(
            """async (api) => {
                const r = await retch(api, {credentials: 'include'});
                try { return await r.json(); } catch (e) { return {code: -1}; }
            }""",
            config.ACCOUNT_API,
        ) or {}

    def save_state(self, path: Path | None = None) -> Path:
        """把 context 的 storage_state 落盘（含 httpOnly，属敏感文件）。"""
        target = Path(path or config.STORAGE_STATE)
        target.parent.mkdir(parents=True, exist_ok=True)
        if self.context is None:
            raise RuntimeError("浏览器尚未启动，无法保存登录态")
        self.context.storage_state(path=str(target))
        return target

    def interactive_login(self, *, timeout_s: float = 300.0) -> bool:
        """打开登录页，等用户扫码；成功后把登录态写入 persistent profile。"""
        page = self.page()
        self.goto(page, config.LOGIN_URL)
        self._switch_to_qr_login(page)
        try:
            shot = config.OUTPUT_DIR / "login_qr.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot))
            print(f"二维码截图：{shot}", flush=True)
        except Exception:
            pass
        print(f"请用 BOSS直聘 App 扫描窗口中的二维码（最多等待 {int(timeout_s)} 秒）…", flush=True)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(2.0)
            if not self.alive(page):
                page = self.page()
                self.goto(page, config.LOGIN_URL)
                self._switch_to_qr_login(page)
                print("页面被销毁，已重建，继续等待登录…", flush=True)
                continue
            names = self.cookie_names()
            if "zp_at" in names and "bst" in names:
                time.sleep(2.0)
                try:
                    if self.account_status(page).get("code") == 0:
                        self.save_state()
                        print("登录成功，登录态已保存到 persistent profile。", flush=True)
                        return True
                except Exception:
                    pass
        print("等待登录超时。", flush=True)
        return False

    @staticmethod
    def _switch_to_qr_login(page) -> None:
        """登录页默认是短信验证码，切到 App 扫码。"""
        for selector in ("text=APP扫码登录", "text=扫码登录", ".login-tab-qr"):
            try:
                page.click(selector, timeout=2500)
                time.sleep(1.0)
                return
            except Exception:
                continue
