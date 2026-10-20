# 应用流水线（`boss_crawler/app/`）

把你的组合方案落成一条可配置流水线。每一步产出都落库，**前端只读库**，
不需要关心流程怎么跑。

## 数据流

```
[招聘爬虫]  按筛选条件抓岗位（BOSS 直聘，可插拔其他平台）
     │ jobs 表
     ▼
[背调 agent] 天眼查 / 知乎 / 微博 / 贴吧（各自可选）
     │ backduty_evidence（逐条证据）
     │ backduty_raw（天眼查：不总结，直接存原数据）
     ▼
[公司打分 agent] 风险 / 待遇 / 压力 / 环境 / 福利
     │ company_score
     ▼
[岗位 agent] 岗位详情 × 用户简历 → 适配度（+ 问用户改进简历）
     │ job_fit
     ▼
[简历 agent] 用户确认后 → 定向简历
     │ resume_version
     ▼
[前端] 读 company_score / job_fit / backduty_* 展示
```

每一步都可以单独关掉（`:class:`Options`` 里的 ``enable_*``）。

## 表

| 表 | 内容 | 说明 |
|---|---|---|
| `app_run` | 每次运行的开关、时间、汇总 | 前端"历史"用 |
| `backduty_evidence` | 逐条证据（标题/URL/情感/来源） | `dedupe_key` 唯一，重跑不会堆重复 |
| `backduty_raw` | 天眼查原数据（jsonb） | 按 (company_key, agent) upsert |
| `company_score` | 五维打分，每次一份 | 保留历史可对比 |
| `job_fit` | 岗位适配度 | 每次一份 |
| `resume_version` | 简历版本 | `parent_id` 可追溯，`confirmed` 区分草稿/定稿 |
| `agent_error` | 报错、缺失数据、失败原因 | 每个 agent 都会写 |
| `platform_login` | 登录态登记 | 前端"初始化"页签读它 |

建表：`python -m boss_crawler app init`（幂等，可反复执行）。

## CLI 契约（前端对接）

所有命令支持 `--json`。长任务用 JSONL：每行一个事件。

```powershell
python -m boss_crawler app status --json
python -m boss_crawler app login  --platforms zhihu,weibo --json
python -m boss_crawler app run    --platforms tianyancha,zhihu --limit 5 --json
python -m boss_crawler app data   --json
python -m boss_crawler app resume --json
```

### 事件类型

```jsonc
{"type":"step","name":"crawl","status":"running"}
{"type":"progress","name":"backduty:zhihu","current":2,"total":5,"message":"茶百道"}
{"type":"error","agent":"zhihu","message":"需要登录"}
{"type":"step","name":"crawl","status":"done","detail":"岗位已入库"}
{"type":"done","ok":true,"run_id":3,"summary":{"companies":5,"evidence":37,"scores":5,"fits":12}}
```

### 各动作返回值

- `status` → `{"db":{...},"login":{"zhihu":false},"platforms":[...],"sources":[...],"agents":[...]}`
- `login` → `{"results":[{"platform":"zhihu","ok":true,"state":"...","reason":null}],"ok":true}`
- `run` → 最后一行 `{"run_id":3,"status":"done","summary":{...}}`
- `data` → `{"companies":[{"company_key","name","job_count","score":{"total","grade","dimensions","advice"},"evidence":{"total","negative","sources"}}],"jobs":[{"id","title","company","fit":{...}}]}`
- `resume` → `{"ok":true,"resume":{...},"questions":["..."]}`

## 可选项

```powershell
# 只跑打分（库里已有岗位和证据）
python -m boss_crawler app run --no-crawl --no-backduty --no-fit

# 只跑某几个平台
python -m boss_crawler app run --platforms tianyancha,tieba

# 加上定向简历
python -m boss_crawler app run --no-crawl --with-resume --resume 简历.json
```

## 登录

`app login` 会**弹出有头浏览器**，你手动登录，程序只负责等和记：

1. 每个平台用**独立持久化 profile**（`.state/login/<platform>`），
   滑块、设备指纹等上下文一并保留，下次直接可用；
2. 判定成功靠**关键 cookie 是否出现**（知乎 `z_c0`、微博 `SUB`、
   贴吧 `BDUSS`、天眼查 `TYCID`、BOSS `bst`），不看页面文案；
3. 用户关掉窗口或超时（默认 300 秒）就跳过，不影响其他平台。

**不做自动登录**：密码、短信、滑块不代劳，既不可靠也不合规。

## 其他招聘平台

`app/sources.py` 里 `JobSource` 是插槽，拉勾/智联/前程无忧已占位（`implemented=False`）。
接入只需实现 `build_steps(filters)`，返回若干条 CLI 子命令，
约定最后一步把岗位写进 `jobs` 表——编排层不关心你怎么采。

## 报错与缺失数据

每个 agent 都强制挂 `log_event` 工具（`ToolAgent.mandatory_tools` /
`ScoringAgentMixin.mandatory_tools`），状态不是 `OK` 时自动写一条：

- `BLOCKED`（登录墙/限频）→ level=`warn`, code=`blocked`
- `FAILED` → level=`error`
- 评分规则未定义 → code=`rules_undefined`

写库失败会降级到 `.state/logs/agents.jsonl`，所以任何环境都留得下痕迹。

## 已知边界

- **没有对话模型**：只有 embedding 可用，所以"定向简历"是**规则化重排**
  （按 JD 关键词排序、挑命中技能、拼概述），不擅长写漂亮话。
  接入对话模型后替换 `ResumeTailorAgent.rewrite` 即可。
- **`ask_user` 需要前端注入回调**（`ctx.options["ask_user"]`）。
  没有通道时返回 `EMPTY` 并跳过，不会卡住流水线；此时定向简历是**草稿**
  （`confirmed=false`）。
- **背调限频**：天眼查网页端连续请求会退化成壳页，工具会返回 `BLOCKED`
  而不是空结果；`--limit` 别开太大。
