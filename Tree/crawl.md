# boss_crawler/crawl —— 采集层

## 文件

| 文件 | 职责 | 关键符号 |
|---|---|---|
| `__init__.py` | 门面 | `BossBrowser` `JobCrawler` `LoginRequired` `BrowserUnavailable` `PageDestroyed` `human_sleep` |
| `browser.py` | 浏览器会话生命周期 | `BossBrowser`（`start/close/goto/new_page/arm/alive/account_status/interactive_login`）、`stealth_source()` |
| `parser.py` | 接口响应解析（纯函数） | `parse_joblist` `parse_joblist_dom` `parse_detail` `normalize_job` `parse_salary` `deep_find` |
| `job_crawler.py` | 抓取编排 | `JobCrawler`（`run` `_enrich_details` `enrich_records` `_fetch_json`） |

## 反爬应对

| 检测手段 | 应对位置 |
|---|---|
| 控制台检测（devtools 探针） | `browser.stealth_source()` 注入的 stealth.js 把 `console.table/clear` 变空操作 |
| 会话页面销毁（`window.close` / `about:blank`） | stealth.js 拦截 + `browser.alive()` 健康检查 + `_rebuild()` 重建并重新预热 |
| 风控 `code=37`（环境异常） | `job_crawler._fetch_json` 退避后重新预热 SPA，让页面重新签发 `__zp_stoken__` |
| 登录失效 `code=7` | 抛 `LoginRequired`，由 CLI 提示重新 `login` |

## 注意

* `patchright` 的 `add_init_script` 在本环境是空操作，所以 stealth.js 用
  `page.evaluate()` 在 `arm()` 里注入；
* 登录态是 httpOnly Cookie（`zp_at`/`bst`），只能靠持久化 `user_data_dir` 复用，
  不能导出可见 Cookie 复制；
* 抓取节流在 `config`（列表 4–9s、详情 2–5s），**不要调小**。
