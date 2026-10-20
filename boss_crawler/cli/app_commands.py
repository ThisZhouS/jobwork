"""应用层子命令：``boss_crawler app ...``。

前端（Electron 或任何 UI）只需要调这里的几个动作，加 ``--json`` 拿结构化输出：

* ``init``    建应用层表；
* ``status``  自检：库里多少数据、哪些平台已登录、有哪些数据源与 agent；
* ``login``   弹出有头浏览器让用户登录（用户点「初始化」时调）；
* ``run``     跑一次流水线（采集 → 背调 → 打分 → 适配度 → 可选定向简历）；
* ``data``    取前端展示用的数据；
* ``resume``  取最新简历版本与要问用户的问题。

这些动作故意不打印花哨表格，好让前端稳定解析。
"""
from __future__ import annotations

import json
from typing import Any

from ..app import Options, login_all, run_pipeline
from ..app.login import login_platforms
from ..app.pipeline import DEFAULT_PLATFORMS
from ..app.sources import sources
from ..store.app_store import AppStore


def _open_db(args):
    from ..store import Database, DatabaseError

    try:
        return Database(
            host=getattr(args, "host", None),
            port=getattr(args, "port", None),
            user=getattr(args, "user", None),
            database=getattr(args, "database", None),
        )
    except DatabaseError as exc:
        print(f"数据库不可用：{exc}")
        return None


def _read_json(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        print(f"读 {path} 失败：{exc}")
        return None


def _platform_list(args) -> list[str]:
    raw = getattr(args, "platforms", None)
    if not raw:
        return list(DEFAULT_PLATFORMS)
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _parse_pairs(raw: str | None, *, sep: str = "=") -> dict | None:
    """把 ``a=1,b=2`` 解析成字典；没给就返回 None（表示"不改这一项"）。"""
    if not raw:
        return None
    out: dict[str, str] = {}
    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if sep not in chunk:
            raise SystemExit(f"格式不对：{chunk}（应为 key{sep}value）")
        key, value = chunk.split(sep, 1)
        out[key.strip()] = value.strip()
    return out or None


def _agent_rows() -> list[dict]:
    """agent 列表：注册表声明 + 配置文件的启用状态。"""
    from ..agents.settings import effective

    try:
        return [
            {"name": row["name"], "kind": row["kind"],
             "enabled": row.get("enabled", True),
             "model": row.get("model") or {},
             "requires_models": row.get("requires_models") or []}
            for row in effective()
        ]
    except Exception:  # noqa: BLE001
        return []


def _printer(json_mode: bool):
    """统一的事件输出：JSON 模式走 JSONL，便于前端逐行解析。"""

    def emit(event: dict[str, Any]) -> None:
        if json_mode:
            print(json.dumps(event, ensure_ascii=False, default=str), flush=True)
            return
        kind = event.get("type")
        if kind == "progress":
            print(f"  [{event.get('current')}/{event.get('total')}] "
                  f"{event.get('name')} {event.get('message') or ''}", flush=True)
        elif kind == "error":
            print(f"  ! {event.get('agent') or event.get('name')}: "
                  f"{event.get('message')}", flush=True)
        elif kind == "warn":
            print(f"  - {event.get('name')}: {event.get('message')}", flush=True)
        elif kind == "step":
            print(f"  * {event.get('name')} [{event.get('status')}] "
                  f"{event.get('detail') or ''}", flush=True)
        elif kind == "login":
            print(f"  * {event.get('platform')} {event.get('status')}: "
                  f"{event.get('message')}", flush=True)

    return emit


def cmd_app(args) -> int:
    """应用层入口。"""
    db = _open_db(args)
    if db is None:
        return 2
    store = AppStore(db)
    emit = _printer(bool(args.json))

    try:
        if args.action == "init":
            info = store.init_schema()
            print(json.dumps(info, ensure_ascii=False) if args.json
                  else f"建表完成：共 {len(info['tables'])} 张表")
            return 0

        if args.action == "status":
            stat = store.stats()
            payload = {
                "db": {"ok": True, **stat},
                "login": store.logins(),
                "platforms": login_platforms(),
                "sources": sources(),
                "agents": _agent_rows(),
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                print(f"库内存量：岗位 {stat.get('jobs')} / 公司 {stat.get('companies')} / "
                      f"证据 {stat.get('backduty_evidence')} / 打分 {stat.get('company_score')}")
                print(f"登录态：{payload['login'] or '（无）'}")
                print("数据源：" + "，".join(s["name"] for s in payload["sources"]))
                print("agent：" + "，".join(a["name"] for a in payload["agents"]))
            return 0

        if args.action == "login":
            platforms = _platform_list(args)
            import asyncio

            result = asyncio.run(login_all(platforms, store=store, state_root=args.state,
                                           timeout=args.timeout, emit=emit))
            if args.json:
                print(json.dumps(result, ensure_ascii=False, default=str))
            else:
                for row in result["results"]:
                    print(f"  {row['platform']}: "
                          f"{'OK' if row.get('ok') else '未完成'} {row.get('reason') or ''}")
            return 0 if result.get("ok") else 3

        if args.action == "run":
            import asyncio

            from ..agents import AgentContext

            options = Options(
                platforms=tuple(_platform_list(args)),
                source=args.source,
                filters={"query": args.query, "city": args.city, "pages": args.pages,
                         "salary": args.salary, "experience": args.experience,
                         "degree": args.degree},
                limit=args.limit,
                job_limit=args.job_limit,
                enable_crawl=not args.no_crawl,
                enable_backduty=not args.no_backduty,
                enable_company_score=not args.no_score,
                enable_job_fit=not args.no_fit,
                enable_resume=args.with_resume,
                resume=_read_json(args.resume),
                no_browser=args.no_browser,
                state_root=args.state,
            )
            result = asyncio.run(run_pipeline(store, options,
                                              ctx=AgentContext(db=db), emit=emit))
            if args.json:
                print(json.dumps(result, ensure_ascii=False, default=str))
            else:
                print(f"\n完成：{result['summary']}")
            return 0 if result["status"] == "done" else 1

        if args.action == "data":
            view = store.data_view()
            if args.json:
                print(json.dumps(view, ensure_ascii=False, default=str))
            else:
                print(f"公司 {len(view['companies'])} 家、岗位 {len(view['jobs'])} 个")
                for row in view["companies"][:15]:
                    score = row.get("score") or {}
                    dims = score.get("dimensions") or {}
                    dim_text = " ".join(f"{k}{v:.0f}" for k, v in dims.items())
                    print(f"  {str(row['name'])[:22]:<24} "
                          f"{score.get('total') or 0:5.1f} {score.get('grade') or '-':<2} {dim_text}")
            return 0

        if args.action == "agents":
            from ..agents.settings import describe

            payload = describe()
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                print(f"配置文件：{payload['file']}"
                      f"{'' if payload['exists'] else '（尚未创建）'}")
                print(f"共 {payload['total']} 个 agent"
                      f"{'，停用 ' + '、'.join(payload['disabled']) if payload['disabled'] else '，全部启用'}")
                for row in payload["agents"]:
                    model = "、".join(f"{k}={v}" for k, v in (row["model"] or {}).items())
                    flags = []
                    if not row["enabled"]:
                        flags.append("已停用")
                    if model:
                        flags.append(model)
                    if row.get("configured"):
                        flags.append("有自定义配置")
                    print(f"  {row['name']:<18} {row['kind']:<9} "
                          f"{'，'.join(flags) if flags else '默认'}")
            return 0

        if args.action == "agent-set":
            from ..agents.settings import set_config

            if not args.name:
                print("需要 --name")
                return 2
            if args.enable and args.disable:
                print("--enable 与 --disable 不能同时给")
                return 2
            enabled = True if args.enable else (False if args.disable else None)
            model = _parse_pairs(args.model, sep="=")
            options = _parse_pairs(args.option, sep="=")
            try:
                conf = set_config(args.name, enabled=enabled, model=model, options=options)
            except (ValueError, KeyError) as exc:
                print(f"配置失败：{exc}")
                return 2
            print(f"{conf.name} 已更新：enabled={conf.enabled} "
                  f"model={conf.model or '{}'} options={conf.options or '{}'}")
            return 0

        if args.action == "agent-reset":
            from ..agents.settings import reset_config

            if not args.name:
                print("需要 --name")
                return 2
            reset_config(args.name)
            print(f"{args.name} 已恢复默认")
            return 0

        if args.action == "filters":
            from ..app.views import filter_options

            payload = filter_options()
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                for item in payload["fields"]:
                    print(f"{item['label']}（--{item['field']}）：" +
                          "、".join(o["label"] for o in item["options"][:12]) + " …")
            return 0

        if args.action == "cloud":
            from ..app.views import skill_cloud

            payload = skill_cloud(store, company_key=args.company_key)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                for row in payload["skills"][:20]:
                    print(f"  {row['name']:<20} {row['count']}")
            return 0

        if args.action == "company":
            from ..app.views import company_detail

            if not args.company_key:
                print("需要 --company-key")
                return 2
            payload = company_detail(store, args.company_key)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                print(f"{payload['name']}  {payload['basic'].get('reg_status') or ''}")
                score = payload.get("score") or {}
                print(f"  总分 {score.get('total')} ({(score.get('grade') or '-')})")
                for dim in score.get("dimensions") or []:
                    print(f"    {dim['name']} {dim['score']}")
            return 0

        if args.action == "job":
            from ..app.views import job_detail

            if not args.job_id:
                print("需要 --job-id")
                return 2
            payload = job_detail(store, args.job_id)
            if payload is None:
                print("没有这个岗位")
                return 2
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                print(f"{payload['title']}  {payload.get('salary') or ''}  "
                      f"{payload.get('city') or ''}")
            return 0

        if args.action == "series":
            from ..app.views import score_series

            if not args.company_key:
                print("需要 --company-key")
                return 2
            payload = score_series(store, args.company_key, field=args.field)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                print(f"{payload['field']}：共 {len(payload['points'])} 个点")
                for point in payload["points"]:
                    print(f"  {point['at']}  {point['value']}")
            return 0

        if args.action == "models":
            from ..agents.models import describe_models

            payload = describe_models()
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                for spec in payload["models"]:
                    print(f"  {spec['name']:<20} {spec['kind']:<10} "
                          f"enabled={spec['enabled']} key={spec['has_key']}  {spec['note'][:40]}")
            return 0

        if args.action == "resume":
            from ..agents.resume_tailor import QUESTIONS

            row = store.latest_resume()
            payload = {"ok": row is not None, "resume": row, "questions": list(QUESTIONS)}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, default=str))
            else:
                print("还没有简历版本" if not row
                      else f"最新简历版本 #{row['id']}（{row['name']}）")
            return 0
    finally:
        db.close()
    return 2
