"""命令行参数定义。

参数分三层：全局（``--headless``）、子命令自有、共享参数组
（``add_input_args`` / ``add_db_args``）。共享组避免同一批参数在四个子命令里
各写一遍——改默认值或加参数只需要动一处。
"""

from __future__ import annotations

import argparse

from .. import config
from .app_commands import cmd_app
from .commands import (
    cmd_agents,
    cmd_crawl,
    cmd_db_init,
    cmd_db_load,
    cmd_db_stats,
    cmd_dd,
    cmd_doctor,
    cmd_embed,
    cmd_enrich,
    cmd_filters,
    cmd_login,
    cmd_process,
    cmd_search,
)

# 默认输入：原始抓取结果 + 已补详情的 enriched.jsonl
_RAW_INPUTS = [str(config.OUTPUT_DIR / "*.jsonl")]
_WITH_ENRICHED = _RAW_INPUTS + [str(config.OUTPUT_DIR / "clean" / "enriched.jsonl")]


def add_input_args(parser: argparse.ArgumentParser, *, with_enriched: bool = True) -> None:
    """统一的 ``-i/--input``：文件 / 目录 / glob 均可。"""
    parser.add_argument(
        "-i", "--input", nargs="+",
        default=list(_WITH_ENRICHED if with_enriched else _RAW_INPUTS),
        help="输入 JSONL（文件/目录/glob）"
        + ("，默认 output/*.jsonl 加已补详情的 enriched.jsonl" if with_enriched else "，默认 output/*.jsonl"),
    )


def add_db_args(parser: argparse.ArgumentParser) -> None:
    """统一的数据库连接参数；不给就走 ``config`` 里的默认值。"""
    parser.add_argument("--host", default=None, help="PostgreSQL 主机，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="PostgreSQL 端口，默认 5432")
    parser.add_argument("--user", default=None, help="PostgreSQL 用户，默认 postgres")
    parser.add_argument("--database", default=None, help="数据库名，默认 boss_jobs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boss_crawler", description="BOSS直聘 职位信息爬虫（scrapling）")
    parser.add_argument("--headless", action="store_true", help="无头模式（更易被检测，默认关闭）")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="扫码登录并保存登录态")
    login.add_argument("--timeout", type=float, default=300.0, help="等待扫码的秒数")
    login.add_argument("--force", action="store_true", help="已登录也重新扫码")
    login.set_defaults(func=cmd_login)

    crawl = sub.add_parser("crawl", help="抓取职位列表/详情")
    crawl.add_argument("-q", "--query", required=True, help="搜索关键词，如 Python")
    crawl.add_argument("-c", "--city", default="成都", help="城市名或 city code")
    crawl.add_argument("-p", "--pages", type=int, default=3, help="抓取页数（每页 30 条）")
    crawl.add_argument("--salary", default=None, help="薪资档位，如 20-50K / 10-20K（也可传 406 这类码）")
    crawl.add_argument("--experience", default=None, help="工作经验，如 3-5年 / 1-3年 / 经验不限")
    crawl.add_argument("--degree", default=None, help="学历要求，如 本科 / 大专 / 硕士")
    crawl.add_argument("--industry", default=None, help="公司行业，如 计算机软件 / 互联网 / 人工智能（也可传 100021）")
    crawl.add_argument("--detail", action="store_true", help="同时抓取职位详情")
    crawl.add_argument("--take", type=int, default=None, help="最多保留多少条")
    crawl.add_argument("--out", default=None, help="输出目录，默认 ./output")
    crawl.set_defaults(func=cmd_crawl)

    doctor = sub.add_parser("doctor", help="环境自检")
    doctor.set_defaults(func=cmd_doctor)

    filters_cmd = sub.add_parser("filters", help="列出筛选参数可选值")
    filters_cmd.set_defaults(func=cmd_filters)

    process = sub.add_parser("process", help="清洗与结构化已抓取的数据")
    add_input_args(process)
    process.add_argument("-o", "--out", default=None, help="输出目录，默认 output/")
    process.add_argument("--enrich", action="store_true", help="对缺地址的记录回源抓详情")
    process.add_argument("--limit", type=int, default=None, help="--enrich 最多补多少条")
    process.add_argument("-q", "--query", default="Python", help="--enrich 预热用关键词")
    process.add_argument("-c", "--city", default="全国", help="--enrich 预热用城市")
    process.set_defaults(func=cmd_process)

    enrich = sub.add_parser("enrich", help="回源补全详情（JD/地址/技能/福利），可断点续跑")
    add_input_args(enrich, with_enriched=False)
    enrich.add_argument("--only", choices=["all", "description", "address"], default="all",
                        help="只补缺失的哪一类")
    enrich.add_argument("--limit", type=int, default=None, help="最多补多少条")
    enrich.add_argument("-o", "--out", default=None, help="enriched.jsonl 输出目录")
    enrich.add_argument("-q", "--query", default="Python", help="预热用关键词")
    enrich.add_argument("-c", "--city", default="全国", help="预热用城市")
    enrich.set_defaults(func=cmd_enrich)

    db_init = sub.add_parser("db-init", help="创建数据库表结构（含向量列与相似度函数）")
    add_db_args(db_init)
    db_init.set_defaults(func=cmd_db_init)

    db_load = sub.add_parser("db-load", help="把清洗后的元数据写入 PostgreSQL")
    add_input_args(db_load)
    add_db_args(db_load)
    db_load.set_defaults(func=cmd_db_load)

    embed = sub.add_parser("embed", help="用 doubao-embedding-vision 向量化并入库")
    embed.add_argument("--owner", choices=["job", "company", "all"], default="all", help="向量化对象")
    embed.add_argument("--force", action="store_true", help="忽略指纹，强制重算")
    embed.add_argument("--limit", type=int, default=None, help="最多处理多少条（调试用）")
    add_input_args(embed)
    add_db_args(embed)
    embed.set_defaults(func=cmd_embed)

    search = sub.add_parser("search", help="向量检索（返回岗位/公司及其元数据）")
    search.add_argument("-q", "--query", required=True, help="查询文本")
    search.add_argument("-k", "--top", type=int, default=5, help="返回条数")
    search.add_argument("--owner", choices=["job", "company", "all"], default="all", help="检索对象")
    add_db_args(search)
    search.set_defaults(func=cmd_search)

    db_stats = sub.add_parser("db-stats", help="查看库内存量与向量化状态")
    add_db_args(db_stats)
    db_stats.set_defaults(func=cmd_db_stats)

    dd = sub.add_parser("dd", help="天眼查背调：读库里的公司名，查工商/母子公司/风险并入库")
    add_db_args(dd)
    dd.add_argument("--limit", type=int, default=None, help="最多背调多少家（调试用）")
    dd.add_argument("--include-anonymous", action="store_true", help="脱敏公司也查（通常查不到）")
    dd.add_argument("--depth", type=int, default=1, help="关联方往下查几层，默认 1")
    dd.add_argument("--max-related", type=int, default=3, help="每个主体最多查几家关联方风险")
    dd.add_argument("--min-percent", type=float, default=20.0, help="控股线，低于此比例不算子公司")
    dd.add_argument("--skip-risks", action="store_true", help="只抓工商与关系，不查失信/被执行")
    dd.add_argument("--only-relations", action="store_true", help="只抓关系，不查关联方风险")
    dd.add_argument("--max-cost", type=float, default=30.0, help="累计花费上限（元）")
    dd.add_argument("--dry-run", action="store_true", help="只列待查清单与预估成本，不调接口")
    dd.add_argument("--engine", choices=["async", "sync"], default="async",
                    help="async=队列+并发+重试的引擎（默认）；sync=逐家顺序执行")
    dd.add_argument("--source", choices=["cli", "api"], default="cli",
                    help="cli=天眼AI 免费额度（默认，需先 tyc login）；api=付费开放接口（按次计费）")
    dd.add_argument("--concurrency", type=int, default=4, help="--engine async 的在飞请求数")
    dd.add_argument("--delay", type=float, default=0.35, help="--engine async 的同主机请求间隔（秒）")
    dd.add_argument("--retries", type=int, default=3, help="--engine async 的重试次数")
    dd.add_argument("--verbose", action="store_true", help="打印每次请求的调试日志")
    dd.set_defaults(func=cmd_dd)

    agents = sub.add_parser("agents", help="可组合 agent：列出 / 单独跑 / 串联跑")
    add_db_args(agents)
    agents.add_argument("action", choices=["list", "tools", "run"],
                        help="list=列出 agent；tools=列出工具；run=执行")
    agents.add_argument("names", nargs="*", help="run 时：一个或多个 agent 名（按顺序串联）")
    agents.add_argument("--company", default="", help="公司名（背调类 agent 必填）")
    agents.add_argument("--company-key", default=None, help="库内 company_key（可选）")
    agents.add_argument("--resume", default=None, help="简历 JSON 文件路径")
    agents.add_argument("--job", default=None, help="岗位 JSON 文件路径")
    agents.add_argument("--kind", choices=["backduty", "scoring"], default=None,
                        help="list 时按类别过滤")
    agents.add_argument("--dump-dir", default=None, help="把抓到的原始 HTML 存到该目录")
    agents.add_argument("--state", default=None, help="浏览器登录态目录（如需登录才抓的站点）")
    agents.add_argument("--no-browser", action="store_true", help="禁止使用浏览器，只用 HTTP")
    agents.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    agents.set_defaults(func=cmd_agents)

    app_cmd = sub.add_parser("app", help="应用层流水线：登录 / 运行 / 取数（前端对接入口）")
    add_db_args(app_cmd)
    app_cmd.add_argument("action",
                         choices=["status", "init", "login", "run", "data", "resume",
                                  "filters", "cloud", "company", "job", "series", "models",
                                  "agents", "agent-set", "agent-reset",
                                  "model-set", "model-reset"],
                         help="status=自检 init=建表 login=弹窗登录 run=跑流水线 "
                              "data=列表 filters=筛选项 cloud=技能词云 company=公司详情 "
                              "job=岗位详情 series=维度折线 models=模型规格 "
                              "agents=agent 配置 agent-set=改配置 agent-reset=恢复默认 "
                              "model-set=改模型配置 model-reset=恢复默认")
    app_cmd.add_argument("--platforms", default=None,
                         help="逗号分隔的平台开关，如 tianyancha,zhihu,weibo,tieba（默认全开）")
    app_cmd.add_argument("--source", default="boss", help="招聘数据源（默认 boss）")
    app_cmd.add_argument("--query", default="", help="岗位关键词")
    app_cmd.add_argument("--city", default="", help="城市")
    app_cmd.add_argument("--pages", type=int, default=None, help="抓取页数")
    app_cmd.add_argument("--salary", default=None, help="薪资档位，如 20-50K")
    app_cmd.add_argument("--experience", default=None, help="工作经验，如 3-5年")
    app_cmd.add_argument("--degree", default=None, help="学历要求")
    app_cmd.add_argument("--limit", type=int, default=20, help="参与背调的公司数")
    app_cmd.add_argument("--concurrency", type=int, default=3,
                         help="背调任务并发数（对标 Scrapy CONCURRENT_REQUESTS）")
    app_cmd.add_argument("--retries", type=int, default=3,
                         help="单个任务最多尝试几次（含首次）")
    app_cmd.add_argument("--task-timeout", type=float, default=120.0,
                         help="单个任务的超时秒数")
    app_cmd.add_argument("--job-limit", type=int, default=50, help="参与适配度的岗位数")
    app_cmd.add_argument("--no-crawl", action="store_true", help="跳过采集（库里已有岗位时用）")
    app_cmd.add_argument("--no-backduty", action="store_true", help="跳过背调")
    app_cmd.add_argument("--no-score", action="store_true", help="跳过公司打分")
    app_cmd.add_argument("--no-fit", action="store_true", help="跳过适配度")
    app_cmd.add_argument("--with-resume", action="store_true", help="同时生成定向简历")
    app_cmd.add_argument("--job-id", default=None, help="resume/job 动作：目标岗位 id")
    app_cmd.add_argument("--company-key", default=None, help="company/series 动作：公司主键")
    app_cmd.add_argument("--field", default=None, help="series 动作：要画折线的字段（默认 total）")
    app_cmd.add_argument("--no-model", action="store_true", help="关停所有模型调用")
    # agent 配置
    app_cmd.add_argument("--name", default=None, help="agent-set/reset 动作：agent 名")
    app_cmd.add_argument("--enable", action="store_true", help="agent-set：启用")
    app_cmd.add_argument("--disable", action="store_true", help="agent-set：停用")
    app_cmd.add_argument("--model", default=None,
                         help="agent-set：按能力指定模型，如 chat=chat.doubao（可多次用逗号分隔）")
    app_cmd.add_argument("--option", default=None,
                         help="agent-set：透传选项，如 key=value（逗号分隔）")
    # 模型配置
    app_cmd.add_argument("--spec", default=None,
                         help="model-set/model-reset 动作：模型规格名，如 chat.doubao")
    app_cmd.add_argument("--model-id", default=None, help="model-set：供应商侧模型 id")
    app_cmd.add_argument("--dimension", type=int, default=None, help="model-set：向量维度")
    app_cmd.add_argument("--resume", default=None, help="简历 JSON 文件路径")
    app_cmd.add_argument("--state", default=".state/login", help="登录态目录")
    app_cmd.add_argument("--timeout", type=float, default=300.0, help="登录等待秒数")
    app_cmd.add_argument("--no-browser", action="store_true", help="禁止浏览器兜底")
    app_cmd.add_argument("--json", action="store_true", help="以 JSON 输出（前端用）")
    app_cmd.set_defaults(func=cmd_app)
    return parser
