# research/ — 反爬机制取证

这些文件是定位「控制台检测 / 会话页面销毁」时留下的材料，不参与爬虫运行。

| 文件 | 说明 |
| --- | --- |
| `probe_playwright.py` | 普通 Playwright 有头/无头探测。结果：`/web/geek/jobs?…&_security_check=1…` → `about:blank`，控制台出现成串 `console.table` / `console.clear`，并报 `Scripts may close only the windows that were opened by them.`（站点调用 `window.close()`） |
| `probe_scrapling.py` | scrapling `StealthySession` 探测。结果：正常落到 `/web/user/` 登录页，没有被销毁 |
| `probe_api.py` | 匿名直接请求 `/wapi/zpgeek/search/joblist.json`。结果：`{"code":37,"message":"您的环境存在异常."}` + `seed`/`name`/`ts` |
| `probe_cookie_replay.py` | 把 GUI 浏览器里可见的 `document.cookie` 回放进新浏览器。结果：`code:7 当前登录状态已失效`（登录票据在 httpOnly Cookie 里） |
| `cookie_bridge.py` | 一次性 localhost 接收器，用来把 Cookie 从 GUI 浏览器传到脚本，避免把凭据打进对话 |
| `smoke_session.py` | 浏览器启动 + 注入自检 |
| `dump_detail.py` | 详情接口响应结构取样（`jobInfo` / `bossInfo` / `brandComInfo`） |
| `check_selector_api.py` | scrapling 0.4.8 `Selector` API 验证（`css_first` 已移除，用 `.css(...).first`） |
| `filter_params.py` | 筛选参数取证：页面 URL、前端 POST 表单、接口 GET 三种方式对比 |
| `industry_probe.py` / `industry_ui.py` / `industry_vue.py` | 定位「公司行业」下拉框与码值（DOM 只暴露 `sel-industry-<索引>`，没有码） |
| `collect_industry_codes.py` | 用 24 组关键词采集 `brandIndustry ↔ industry` 码，得到 96 个行业 |
| `industry_codes.json` / `gen_industry_module.py` | 采集结果，以及生成 `boss_crawler/industry_codes.py` 的脚本 |
| `_vendor_*.js` / `_vendor_security.html` | 从站点下载的安全脚本：`browser-check-v2.js`、`geek/index.js`、`warlockdata.min.js`、`security.html` |
| `probe_headful.png` | 探测时截图（此时页面已被销毁，只剩空白） |
| `patchright_install.log` | patchright 浏览器下载日志 |
| `probe_scrapling.html` | scrapling 探测时落盘的页面 HTML |

关键对比（同一台机器、同一网络）：

```
普通 Playwright（有头） : 6s 后 about:blank（页面被销毁）
scrapling StealthySession: 正常停在登录页，登录后接口 code=0
```
