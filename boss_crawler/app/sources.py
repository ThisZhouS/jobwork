"""招聘数据源：BOSS 直聘，以及为其他平台预留的插槽。

方案里是"boss直聘爬虫 → 数据 → 数据库"，并且"预留其他平台的招聘爬虫接口"。
所以这里把"某个平台的岗位采集"抽象成 :class:`JobSource`：只要它能把岗位写进
``jobs`` 表，编排层不关心它是爬虫、接口还是人工导入。

新增一个平台：

```python
register_source(JobSource(
    name="lagou",
    label="拉勾",
    steps=lambda f: [["lagou-crawl", "-q", f["query"]]],
))
```
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

Emit = Callable[[dict], Any]


@dataclass
class JobSource:
    """一个招聘数据源。

    ``build_steps(filters)`` 返回若干条 CLI 子命令（不含 ``python -m boss_crawler``），
    按顺序执行；约定最后一步把数据写进 ``jobs`` 表。
    """

    name: str
    label: str
    description: str = ""
    build_steps: Callable[[dict[str, Any]], Sequence[Sequence[str]]] | None = None
    available: Callable[[], bool] = lambda: True
    #: 是否已实现；预留插槽为 False，编排时会跳过并说明
    implemented: bool = True


_SOURCES: dict[str, JobSource] = {}


def register_source(source: JobSource) -> JobSource:
    if not source.name:
        raise ValueError("数据源必须有 name")
    if source.name in _SOURCES:
        raise ValueError(f"数据源已存在：{source.name}")
    _SOURCES[source.name] = source
    return source


def get_source(name: str) -> JobSource:
    if name not in _SOURCES:
        raise KeyError(f"未知数据源：{name}（可用：{'、'.join(source_names())}）")
    return _SOURCES[name]


def source_names() -> list[str]:
    return sorted(_SOURCES)


def sources() -> list[dict]:
    return [
        {"name": s.name, "label": s.label, "description": s.description,
         "implemented": s.implemented}
        for s in sorted(_SOURCES.values(), key=lambda x: x.name)
    ]


def reset_sources() -> None:
    _SOURCES.clear()
    _register_builtin()


# ---------------------------------------------------------------- BOSS 直聘
def _boss_steps(filters: dict[str, Any]) -> list[list[str]]:
    """复用既有 CLI：抓取 → 清洗 → 入库。不重写爬虫。"""
    crawl = ["crawl", "-q", str(filters.get("query") or "Python")]
    if filters.get("city"):
        crawl += ["-c", str(filters["city"])]
    if filters.get("pages"):
        crawl += ["-p", str(filters["pages"])]
    if filters.get("salary"):
        crawl += ["--salary", str(filters["salary"])]
    if filters.get("experience"):
        crawl += ["--experience", str(filters["experience"])]
    if filters.get("degree"):
        crawl += ["--degree", str(filters["degree"])]
    if filters.get("take"):
        crawl += ["--take", str(filters["take"])]
    if filters.get("detail", True):
        crawl += ["--detail"]
    if filters.get("out"):
        crawl += ["--out", str(filters["out"])]

    process = ["process"]
    if filters.get("out"):
        process += ["-o", str(filters["out"])]
    load = ["db-load"]
    if filters.get("out"):
        load += ["-i", str(filters["out"])]
    return [crawl, process, load]


def _register_builtin() -> None:
    register_source(JobSource(
        name="boss",
        label="BOSS直聘",
        description="按筛选条件抓取岗位并写入数据库（复用既有 crawl→process→db-load）",
        build_steps=_boss_steps,
    ))
    # ---- 预留：其他平台只要实现 build_steps 就能接进来 ----
    register_source(JobSource(
        name="lagou", label="拉勾", implemented=False,
        description="预留插槽：实现 build_steps 后即可接入",
    ))
    register_source(JobSource(
        name="zhaopin", label="智联招聘", implemented=False,
        description="预留插槽：实现 build_steps 后即可接入",
    ))
    register_source(JobSource(
        name="51job", label="前程无忧", implemented=False,
        description="预留插槽：实现 build_steps 后即可接入",
    ))


async def run_source(name: str, filters: dict[str, Any], *, emit: Emit | None = None,
                     timeout: float = 1800.0) -> dict:
    """执行一个数据源的采集步骤。返回 ``{ok, steps}``。"""
    source = get_source(name)
    if not source.implemented or source.build_steps is None:
        return {"ok": False, "skipped": True,
                "reason": f"{source.label} 数据源还没实现（预留插槽）"}
    if not source.available():
        return {"ok": False, "skipped": True, "reason": f"{source.label} 依赖不可用"}

    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(_project_root()))
    env.setdefault("PYTHONIOENCODING", "utf-8")

    results = []
    for step in source.build_steps(filters):
        argv = [sys.executable, "-m", "boss_crawler", *[str(a) for a in step]]
        if emit:
            emit({"type": "step", "name": f"crawl:{name}:{step[0]}", "status": "running",
                  "detail": " ".join(argv[3:])})
        proc = await asyncio.create_subprocess_exec(
            *argv, env=env, cwd=str(_project_root()),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "reason": f"{step[0]} 超时"}
        text = (stdout or b"").decode("utf-8", "replace")
        ok = proc.returncode == 0
        results.append({"step": step[0], "ok": ok, "code": proc.returncode,
                        "tail": _tail(text)})
        if emit:
            emit({"type": "step", "name": f"crawl:{name}:{step[0]}",
                  "status": "done" if ok else "failed", "detail": _tail(text)})
        if not ok:
            return {"ok": False, "reason": f"{step[0]} 失败", "steps": results}
    return {"ok": True, "steps": results}


def _tail(text: str, limit: int = 300) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-2:])[:limit]


def _project_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[2]


_register_builtin()
