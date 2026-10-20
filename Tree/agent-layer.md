# agents/ — 工具层 + 可组合 agent

职责：把「查公司 / 评简历 / 算适配」拆成**互相独立、可任意串联**的小单元，
并把**反爬能力下沉到工具层**，让 agent 只做「调工具 + 总结」。

## 两层分工（本轮的核心调整）

```
agent（薄）  ──调用──▶  工具（厚：含全部反爬）
只负责汇总              UA 轮换 / 节流 / 重试 / cookie 登录态 /
                       浏览器兜底 / 被挡识别 / 解析成结构化数据 / 原始页落盘
```

- **工具负责"怎么拿到"**：脏活全在 `agents/tools/`，改反爬策略只改 `ToolBox`，
  agent 一行不动。
- **agent 负责"拿到什么、怎么总结"**：它不知道代理和验证码，只调工具、
  把结构化行汇总成 `Finding`。

## 目录

```
agents/
├── base.py        契约：AgentStatus / Finding / Dimension / ScoreCard /
│                  AgentRequest / AgentContext / AgentResult / Agent 抽象类
├── fetch.py       反爬原语：HttpFetcher（UA+限速+重试）、StealthBrowser、looks_blocked
├── toolagent.py   总结层：ToolCall 声明、ToolAgent 基类、行→Finding、情感分布
├── registry.py    注册表 + Pipeline（findings/metrics 自动往下传）
├── tools/         工具层（导入即注册）
│   ├── base.py        Tool 契约 + ToolBox（反爬主干）+ 工具注册表
│   ├── parsing.py     纯函数：情感词表、去标签、JSON/日期抽取、去重
│   └── sites/         各站点工具
│       ├── zhihu.py       zhihu_search
│       ├── tieba.py       tieba_search
│       ├── weibo.py       weibo_search
│       ├── tianyancha.py  tianyancha_search / _company / _risk / _full
│       └── tyc.py         tyc_bundle / tyc_ask（只用免费工具）
├── backduty/      5 个背调 agent（每个 10–30 行，只声明调哪些工具）
└── scoring/       3 个评分 agent（**空框架，规则待定义**）
    ├── framework.py    Rule / Rubric / ScoreContext / ScoringAgentMixin
    ├── rubric.py       写规则用的纯函数（插值、覆盖率、年限、缺口话术）
    └── company_score.py / resume_score.py / job_fit.py
```

## 现状

| agent | 调用的工具 | 状态 |
|---|---|---|
| `zhihu` | `zhihu_search` | 可用（需登录态） |
| `tieba` | `tieba_search` | 可用（多数免登录） |
| `weibo` | `weibo_search` | 可用（移动端接口常免登录） |
| `tianyancha_web` | `tianyancha_full` | 可用（免登录，有限频） |
| `tianyan_ai` | `tyc_bundle` | 可用（需 `tyc login`） |
| `company_score` | —— | **框架就绪，规则待定义** |
| `resume_score` | —— | **框架就绪，规则待定义** |
| `job_fit` | —— | **框架就绪，规则待定义** |

## 契约要点

- `AgentStatus` 五个状态：`OK` / `PARTIAL` / `EMPTY`（确实没有）/ `BLOCKED`
  （登录墙、验证码、限频）/ `FAILED`。**`EMPTY` 与 `BLOCKED` 必须分清**：
  前者是"查了没有"，后者是"没查到，得换方式"。
- `Agent.execute()` 是唯一对外入口：把异常统一转成 `FAILED`，把 `MissingInput`
  转成"输入不足：…"，所以单个 agent 崩了不会炸掉整条链。
- `Tool.execute()` 同理：参数校验 + 异常兜底 + 计时，工具内部崩了不冒泡。
- `Pipeline` 把上一环的 `findings`、`metrics` 顺着传给下一环。

## 加一个站点工具

```python
# agents/tools/sites/example.py
from ..base import Tool, ToolBox, ToolResult, register_tool

class ExampleSearchTool(Tool):
    name = "example_search"
    site = "示例站"
    description = "搜示例站"
    params = ("company",)

    async def call(self, box: ToolBox, company: str = "") -> ToolResult:
        outcome = await box.fetch_page(f"https://example.com/s?q={company}")
        if outcome.blocked:
            return ToolResult.blocked(self.name, "需要登录")
        return ToolResult.ok_(self.name, parse_rows(outcome.html))

register_tool(ExampleSearchTool())
```

再在 `tools/sites/__init__.py` 加一行 import 即可。

## 加一个 agent（只声明调什么工具）

```python
class ExampleAgent(ToolAgent):
    name = "example"
    site = "示例站"
    requires = ("http",)
    tools = (ToolCall("example_search", source="example"),)
```

要额外元数据就覆盖 `extra_meta()`；要改总结口径就覆盖 `summarize()`。

## 评分规则怎么填（后续工作）

框架刻意不含任何规则。填法：给 `Rule.scorer` 一个函数，返回 0–100，
或返回 `None` 表示"这次没数据"（框架会给中性分 60 并标注原因）。

```python
def score_status(ctx):                      # ctx: ScoreContext
    status = ctx.profile.get("reg_status")
    if not status:
        return None
    return 90 if ("存续" in status or "在业" in status) else 20

Rule("经营稳定性", weight=3.0, hint="登记状态", scorer=score_status)
```

`ScoreContext` 里能拿到 `profile / counts / findings / metrics / resume / job`。
规则全空时 agent 返回 `PARTIAL` 并在 `notes` 里说明，不会伪装成"算完了"。

## 用法

```powershell
python -m boss_crawler agents list                 # 看 agent，含各自用的工具
python -m boss_crawler agents tools                # 看工具清单与依赖
python -m boss_crawler agents run tianyan_ai --company 茶百道
python -m boss_crawler agents run tianyancha_web tianyan_ai company_score --company 茶百道
```

`--dump-dir` 让工具把原始页面落盘（`output/agents/<agent>/`），页面改版时校准解析器用。
