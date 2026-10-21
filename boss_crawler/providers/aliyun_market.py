"""阿里云云市场（API 市场）的风险数据适配器。

为什么单独做一层：云市场上的风险/司法类接口由不同服务商提供，**每家路径和字段都不一样**，
但调用方式是一致的——``Authorization: APPCODE <code>`` + 一个 GET 地址。
所以这里不写死任何一家的字段，而是把「地址 + 参数 + 字段映射」放进
``config/risk_api.json``，买到哪个就填哪个，不用改代码。

实测到的行情（2026-10，云市场商品页）：

* 「司法不良（详版）」——￥2/10 次，可免费试用；
* 「全国企业数据报告」——￥0/10 次，覆盖工商/司法涉诉/经营异常；
* 「企业工商信息查询」——￥2/5 次起，￥60/1000 次。

对比天眼查 100 元起充，云市场的**最低门槛是 2 元**，试错成本低一个量级。

需要说清的代价：这些都是**第三方转售**数据（不少上游仍是天眼查/企查查或官方站点），
质量、稳定性、更新频率都不由阿里云保证，协议通常也禁止转售和长期缓存。
个人自用、低频查询是合理的用法。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = ROOT / "config" / "risk_api.json"
STATE_FILE = ROOT / ".state" / "aliyun_appcode.txt"
ENV_NAME = "ALIYUN_APPCODE"


@dataclass
class RiskApiProfile:
    """一个云市场接口的调用配方。"""

    name: str
    base: str
    path: str
    #: 请求参数名 -> 值模板，``{company}`` 会被替换成公司名
    params: dict[str, str] = field(default_factory=dict)
    #: 响应里「行列表」的位置，点号分隔；空表示响应本身是列表
    items_path: str = ""
    #: 统一字段 -> 原始字段名
    fields: dict[str, str] = field(default_factory=dict)
    enabled: bool = False
    budget: int = 20
    note: str = ""

    @property
    def url(self) -> str:
        return f"{self.base.rstrip('/')}/{self.path.lstrip('/')}"

    @property
    def configured(self) -> bool:
        return bool(self.base and self.path)


def config_path() -> Path:
    return CONFIG_FILE


def appcode() -> str:
    """AppCode 只从环境变量或 ``.state/`` 读，绝不写进代码或配置文件。"""
    value = os.environ.get(ENV_NAME, "").strip()
    if value:
        return value
    if STATE_FILE.exists():
        return STATE_FILE.read_text(encoding="utf-8").strip()
    return ""


def has_appcode() -> bool:
    return bool(appcode())


def load(path: Path | None = None) -> dict[str, RiskApiProfile]:
    """读配置。文件不存在或坏掉都返回空，不影响主流程。"""
    path = path or CONFIG_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 坏文件不该让整包起不来
        return {}
    out: dict[str, RiskApiProfile] = {}
    for name, raw in (data.get("profiles") or {}).items():
        if not isinstance(raw, dict):
            continue
        out[name] = RiskApiProfile(
            name=name,
            base=str(raw.get("base") or ""),
            path=str(raw.get("path") or ""),
            params={str(k): str(v) for k, v in (raw.get("params") or {}).items()},
            items_path=str(raw.get("items_path") or ""),
            fields={str(k): str(v) for k, v in (raw.get("fields") or {}).items()},
            enabled=bool(raw.get("enabled", False)),
            budget=int(raw.get("budget", 20) or 20),
            note=str(raw.get("note") or ""),
        )
    return out


def get_profile(name: str, path: Path | None = None) -> RiskApiProfile | None:
    return load(path).get(name)


def build_url(profile: RiskApiProfile, company: str, **extra: Any) -> str:
    """拼出带查询参数的 URL；参数值里的 ``{company}`` 会被替换。"""
    params = {key: str(value).replace("{company}", company)
              for key, value in (profile.params or {}).items()}
    for key, value in extra.items():
        params[key] = str(value).replace("{company}", company)
    if not params:
        return profile.url
    return f"{profile.url}?{urlencode(params)}"


def dig(payload: Any, path: str) -> Any:
    """按 ``a.b.c`` 取值；取不到返回 None。"""
    if not path:
        return payload
    node = payload
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if node is None:
            return None
    return node


def _first_dict_list(node: Any) -> list[dict] | None:
    """在响应里找第一个「字典列表」——不同服务商包层数不一样。"""
    if isinstance(node, list):
        if not node or all(isinstance(x, dict) for x in node):
            return [x for x in node if isinstance(x, dict)]
        return None
    if isinstance(node, dict):
        for value in node.values():
            found = _first_dict_list(value)
            if found is not None:
                return found
    return None


def normalize(payload: Any, profile: RiskApiProfile) -> list[dict[str, Any]]:
    """把任意形状的响应归一成统一的 risk 行。

    统一字段：``title / risk_type / case_no / court / amount / date / status / raw``。
    没配映射的字段就留空——**不猜**，猜错的字段比空字段更有害。
    """
    items = dig(payload, profile.items_path) if profile.items_path else None
    if not isinstance(items, list):
        items = _first_dict_list(payload) or []

    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {"raw": item}
        for target, source in (profile.fields or {}).items():
            row[target] = item.get(source)
        row.setdefault("title", "")
        row.setdefault("risk_type", "未分类")
        rows.append(row)
    return rows


def describe(path: Path | None = None) -> dict[str, Any]:
    """自检视图：有哪些配方、有没有填地址、有没有 AppCode（只报布尔）。"""
    profiles = load(path)
    return {
        "file": str(config_path()),
        "exists": config_path().exists(),
        "has_appcode": has_appcode(),
        "appcode_source": ENV_NAME if os.environ.get(ENV_NAME) else (
            str(STATE_FILE) if STATE_FILE.exists() else None),
        "profiles": [
            {"name": p.name, "configured": p.configured, "enabled": p.enabled,
             "budget": p.budget, "note": p.note}
            for p in profiles.values()
        ],
    }


__all__ = [
    "CONFIG_FILE",
    "ENV_NAME",
    "RiskApiProfile",
    "appcode",
    "build_url",
    "config_path",
    "describe",
    "dig",
    "get_profile",
    "has_appcode",
    "load",
    "normalize",
]
