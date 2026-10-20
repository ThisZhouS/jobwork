# 桌面端设计（框架与接口，暂不定视觉）

只定**结构、路由、数据契约**，不定配色/排版。所有数据都来自后端 CLI（`--json`），
前端不碰数据库。

## 一、页面框架

单窗口，左侧导航 + 右侧内容区，底部常驻对话口。

```
┌────────────┬──────────────────────────────────────────────┐
│ 导航        │ 内容区（路由出口）                             │
│            │                                              │
│ ▸ 概览      │  概览     筛选    词云    公司详情   岗位详情   │
│ ▸ 岗位      │                                              │
│ ▸ 公司      │                                              │
│ ▸ 简历      │                                              │
│ ▸ 设置      │                                              │
├────────────┴──────────────────────────────────────────────┤
│ 对话口（底部弹窗，任何页面可唤起）                            │
└───────────────────────────────────────────────────────────┘
```

### 路由表

| 路由 | 页面 | 主要数据 |
|---|---|---|
| `/` | 概览 | `app data` |
| `/jobs` | 岗位列表 + 筛选 | `app data`、`app filters` |
| `/jobs/:id` | 岗位详情 | `app job --job-id` |
| `/companies` | 公司列表（维度表） | `app data` |
| `/companies/:key` | 公司详情 | `app company --company-key` |
| `/companies/:key/series` | 单字段折线 | `app series --company-key --field` |
| `/skills` | 技能词云 | `app cloud` |
| `/resume` | 简历输入输出 | `app resume`、`app run --with-resume` |
| `/settings` | 初始化/登录/模型 | `app status`、`app login`、`app models` |

### 通用交互约定

- **一切跳转都带 key**：公司用 `company_key`，岗位用 `job_id`。不传名称。
- **每个列表行可跳详情**；详情内字段可跳折线（见第四节）。
- 长任务（`app run`）用 JSONL 事件流驱动进度条，允许「停止」（kill 子进程）。

## 二、六个功能块

### 1. 技能词云（`/skills`）

数据：`app cloud --json`

```json
{ "total": 137,
  "skills": [ {"name": "Python", "count": 21, "weight": 0.1533},
              {"name": "MySQL",  "count": 7,  "weight": 0.0511} ] }
```

- `count` = 出现在**多少个岗位**里（不是出现次数，避免一个岗位刷权重）；
- `weight` = 已归一化的占比，前端可直接映射字号/透明度，不必自己算；
- 支持按公司、城市过滤（`--company-key`）。

### 2. 维度图与表（`/companies`、详情页）

数据：`app data` 里的 `companies[].score`

```json
{ "total": 67.6, "grade": "C",
  "dimensions": {"风险": 60, "待遇": 72, "压力": 55, "环境": 60, "福利": 68},
  "is_labor_dispatch": null,
  "labor_dispatch_reason": "没有经营范围也没有评价，无法判断" }
```

两种展示，**同一份数据**：

- **维度图**：五维各一轴（雷达/条形均可）。要求**不叠加**——即不要把多家公司
  叠在同一张图上，一图一公司；列表页要比较就用表格。
- **表格**：公司名 / 总分 / 等级 / 五维 / 劳务派遣 / 证据数。

### 3. 字段折线（`/companies/:key/series`）

数据：`app series --company-key K --field 风险 --json`

```json
{ "company_key": "K", "field": "风险",
  "points": [ {"at": "2026-10-20T19:07:55+08:00", "value": 60} ] }
```

`field` 取 `total` 或任一维度名。**表格每个字段右侧挂一个「看趋势」入口**，
跳到该路由即可——这是"按不同字段设计可跳转至字段折线图"的落法。

### 4. 用户简历输入输出（`/resume`）

- 读：`app resume --json` → `{ok, resume:{id,name,content,confirmed}, questions:[...]}`
- 写：前端把内容存成 JSON，走 `app run --with-resume --resume <文件> --job ...`
  （文件由主进程写到临时目录，避免命令行长度问题）
- `questions` 是后端要问你的问题；回答后回填，`confirmed` 才会变 true。

### 5. 岗位筛选（`/jobs` 顶部）

**直接映射 BOSS 的筛选条件**，不发明字段：

`app filters --json` → `{fields:[{field,label,options:[{value,label,code}]}], text:[...], toggles:[...]}`

- `fields`：`salary` / `experience` / `degree` / `industry`（值是 BOSS 认的中文名或数字码）；
- `text`：`query`（必填）、`pages`；
- `toggles`：背调平台与三个开关。

提交时把这些**原样**拼成 `app run` 的参数，中间不做任何转换。

### 6. 对话口（底部弹窗）

一个常驻的对话空间，用途有三：

1. 跑流水线时看事件流（`progress` / `error` / `step`）；
2. 回答后端提出的问题（`questions`，用于改进简历）；
3. 触发命令（如"只跑天眼查"）。

数据：`app run --json` 的 JSONL；回答通过写入简历的 `answers` 回传。

> 现状：没有对话模型（Ark 密钥只有嵌入权限），所以这里是**表单式问答 + 日志流**，
> 不是自由聊天。模型可用后由后端 `agents/models` 接管，接口不变。

## 三、详情页字段

### 公司详情（`app company --company-key K`）

```jsonc
{
  "company_key": "K", "name": "茶百道",
  "basic": {"reg_status","reg_capital","estiblish_time","legal_person",
            "reg_location","staff_num","industry","business_scope",
            "credit_code","raw_available"},
  "risk": {"counts": {"法律诉讼": 1}, "items": [...], "evidence_negative": 9},
  "reviews": {"zhihu": [{"title","url","snippet","sentiment","published_at"}],
              "tieba": [...]},
  "jobs": [{"job_id","title","salary","city","skills","welfare","url"}],
  "score": {"total","grade","verdict","dimensions":[{name,score,weight,reason}],
            "advice","at"},
  "labor_dispatch": {"is_labor_dispatch": true/false/null, "reason", "evidence"}
}
```

**劳务派遣三态**：`true` 是、`false` 明确不是、`null` 信息不足。
UI 不要把 `null` 显示成"否"——这是把"不知道"伪装成结论。

### 岗位详情（`app job --job-id J`）

```jsonc
{
  "id": "J", "title": "后端工程师",
  "salary","experience","degree","city","district","industry",
  "skills": [...], "welfare": [...], "description": "...",
  "source": {"name": "BOSS直聘", "url": "https://www.zhipin.com/job_detail/...",
             "job_id": "J"},
  "company": {"company_key","name","legal_name",
              "score": {"total","grade","is_labor_dispatch","dimensions"}},
  "fit": {"total","grade","verdict","dimensions","advice"}
}
```

`source.url` 就是"岗位跳转"的地址（用系统浏览器打开，不要在应用内嵌）。

## 四、IPC 契约（主进程 ↔ 渲染进程）

渲染进程只发"动作名 + 参数"，主进程负责拼命令、spawn、解析。

```ts
window.api = {
  call(action: string, args?: Record<string, string|number|boolean>): Promise<any>
  stream(action: string, args?: Record<string, any>,
         onEvent: (e: ProgressEvent) => void): Promise<{code: number}>
  cancel(streamId: string): void
  openExternal(url: string): void
}
```

- `call` 对应一次性命令（`status`/`data`/`filters`/`cloud`/`company`/`job`/`series`/`models`/`resume`）；
- `stream` 对应 `run`/`login`，逐行解析 JSONL；
- 统一约定：**主进程按 UTF-8 解码**（Windows 上不要用默认 GBK）。

## 五、状态模型（前端本地）

```ts
type RunEvent =
  | {type:"step";     name:string; status:string; detail?:string}
  | {type:"progress"; name:string; current:number; total:number; message:string}
  | {type:"error";    agent?:string; name?:string; message:string}
  | {type:"warn";     name:string; message:string}
  | {type:"login";    platform:string; status:string; message:string}
  | {type:"done";     ok:boolean; run_id:number; summary:Record<string, any>}
```

页面级状态只有四份：`filters`（筛选表单）、`run`（当前事件流）、`selection`
（当前公司/岗位 key）、`resumeDraft`（简历草稿）。不做全局 store 之外的分层。

## 六、后端接口清单（本轮已实现）

```powershell
python -m boss_crawler app status   --json   # 自检
python -m boss_crawler app login    --platforms zhihu --json
python -m boss_crawler app run      --query Python --city 成都 --json
python -m boss_crawler app data     --json   # 列表（含维度、劳务派遣、证据数）
python -m boss_crawler app filters  --json   # BOSS 筛选条件
python -m boss_crawler app cloud    --json   # 技能词云
python -m boss_crawler app company  --company-key K --json
python -m boss_crawler app job      --job-id J --json
python -m boss_crawler app series   --company-key K --field 风险 --json
python -m boss_crawler app resume   --json
python -m boss_crawler app models   --json   # 模型规格与可用性
```

## 七、待你定的

1. 维度图用雷达还是条形（数据形状已就绪，两种都能画）；
2. 对话口是否要保留自然语言入口（现在只能表单问答）；
3. 词云是否要按公司/城市再筛一层（后端已支持 `--company-key`）。
