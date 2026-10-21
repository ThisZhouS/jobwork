# 天眼查「风险提示」的平替

结论先说：**不存在既免费又稳定的第三方 API**。能工程化接入的只有两条官方/准官方渠道，
其余要么有滑块验证码，要么要企业实名 + 500 元起充。

本文是调研结论 + 已落地的实现说明。

## 一、接入结论

| 源 | 覆盖风险 | 接入方式 | 成本 | 反爬难度 | 推荐 |
|---|---|---|---|---|---|
| **巨潮资讯 cninfo** | 上市公司的处罚/立案/诉讼/风险提示 | POST JSON，免鉴权 | 免费 | 1/5 | ★★★★★ |
| **人民法院公告网** | 开庭/破产/执行/裁判公告 | AJAX，无验证码 | 免费 | 2/5 | ★★★★☆ |
| **阿里云云市场（司法不良）** | 司法涉诉/失信/被执行 | 官方通道 + AppCode | ￥2/10 次起 | 1/5 | ★★★★☆ |
| 水滴信用 | 失信/被执行/诉讼 | HTML | 免费 | 2/5 | ★★★☆☆ |
| 爱企查 | 司法/异常/处罚聚合 | HTML（部分需登录） | 免费 | 3/5 | ★★★☆☆ |
| 企查查 API | 全维度 + 案号金额 | 官方 API | 0.3–6 元/次，**起充 500** | 1/5 | ★★☆☆☆ |
| 启信宝 | 同上 | 官方 API | 企业实名 + 充值 | 1/5 | ★☆☆☆☆ |
| gsxt 国家企业信用信息公示系统 | 工商/经营异常/严重违法 | 极验滑块 | 免费 | 5/5 | ★☆☆☆☆ |
| 中国执行信息公开网 | 失信/被执行/限高 | 验证码 | 免费 | 4/5 | ★★☆☆☆ |
| 裁判文书网 | 文书全文 | 登录；robots 全站 Disallow | 免费 | 5/5 | ★☆☆☆☆ |
| 信用中国 | 行政处罚/黑名单 | 无 API，实测 412 | 免费 | 5/5 | ★☆☆☆☆ |

要点：

- **企查查比天眼查更贵**：单次 0.3 元听起来便宜，但最低充值 500 元，
  还要企业实名和场景审核。天眼查 100 元门槛反而是最低的。
- **gsxt / 执行网 / 裁判文书网**被滑块或验证码挡住，个人少量查询手动可行，
  脚本化基本不可行，且不该去破解（见第四节）。
- **巨潮资讯**是唯一「免鉴权 + 结构化 JSON + 稳定」的源，代价是只覆盖上市公司。

## 二、已落地：`cninfo` provider

`boss_crawler/agents/tools/sites/cninfo.py` + `agents/backduty/cninfo.py`

- 工具 `cninfo_notices`：`POST http://www.cninfo.com.cn/new/hisAnnouncement/query`
  （表单参数 `searchkey=公司名`，`isHLtitle=true`），自动翻页（单页 30 条，最多 4 页）；
- 解析：标题去掉 `<em>` 高亮、毫秒时间戳转 `YYYY-MM-DD`、拼 PDF 链接；
- 分类：按标题关键词判 `立案调查 / 重大诉讼 / 失信被执行 / 经营异常 / 股权风险 /
  业绩预警 / 监管问询 / 高管变动 / 风险提示`，其余归 `其他公告`；
- 节流：复用 `HttpFetcher` 的 delay（默认 2s ≈ 0.5 QPS，调研建议 ≤0.2 QPS 可再调大）；
- 重试：复用 `HttpFetcher` 的 retry_policy。

**实测（真实接口）**：

```
康美药业     ok      rows=30 risky=4
  重大诉讼 | 2026-08-26 | 康美药业关于涉及诉讼进展的公告（二）
  高管变动 | 2026-08-22 | 康美药业关于董事长辞职…的公告
比亚迪       partial rows=50 risky=0   （近期都是 H 股常规公告）
某非上市公司  empty   「未检索到公告（非上市公司的正常结果）」
```

## 三、降级链（重要）

信息不足 **不等于** 安全。这条链上每一环都要能表达「不知道」：

```
cninfo 有风险公告 → 记风险证据
cninfo 查不到     → EMPTY，注明"非上市公司的正常结果"
cninfo 报错       → FAILED，进 agent_error 表
以上都没有        → 风险维度仍然按"无数据"处理，不给正面分
```

所以工具在「有公告但全是常规公告」时返回 `PARTIAL` 并附一句
「没有风险类公告：这不等于无风险，只说明没有相关披露」。

## 四、不该做的事

- 破解滑块/验证码（gsxt 的极验、执行网的图形码）；
- 伪造 UA 绕 WAF、高频并发；
- 绕登录抓非公开数据；
- 转售或公开传播个人涉案信息——可能触及《网络安全法》《个人信息保护法》，
  严重的涉及刑法 285 条。

个人少量查询手点没问题，脚本化要克制在「公开披露信息 + 低频」范围内。

## 五、阿里云云市场（API 市场）：值得接，但不建议当唯一来源

天眼查 100 元起充，而云市场同类接口**最低 2 元**——试错成本低一个量级。
以下价格来自云市场商品页（2026-10 实测，会变）：

| 商品 | 价格 | 覆盖 |
|---|---|---|
| 司法不良（详版） | ￥2/10 次，可免费试用 | 司法不良/失信/被执行/涉诉 |
| 全国企业数据报告 | ￥0/10 次 | 工商+司法涉诉+经营异常+知产 |
| 企业工商信息查询 | ￥2/5 次；￥60/1000 次（0.06 元/次） | 工商、股东、变更、主要人员 |

调用方式统一：`Authorization: APPCODE <code>` + 一个 GET 地址，返回 JSON。

**但有三点必须知道**：

1. **都是第三方转售**。服务商（杭州网尚/安徽则悟/深圳云之鲲等）多数上游仍是
   天眼查、企查查或官方站点，阿里云只提供交易与调用通道，不保证数据质量与更新频率；
2. **协议通常禁止转售、长期缓存**。个人自用、低频查询没问题，落库长期保存要谨慎；
3. **按次计费**，配置写错可能刷出费用——所以适配器里带了**调用预算**（默认 20 次/进程）。

### 已落地的适配器

`boss_crawler/providers/aliyun_market.py` + `agents/tools/sites/aliyun_risk.py`

它不是某个接口的硬编码客户端，而是**配置化配方**：买到哪个接口，就把商品页上的
「调用地址」拆成 base/path、参数名、字段映射填进 `config/risk_api.json`，不用改代码。

```jsonc
{
  "profiles": {
    "judicial": {
      "enabled": true,
      "base": "https://xxxx.market.alicloudapi.com",
      "path": "/enterprise/risk",
      "params": { "keyword": "{company}" },
      "fields": { "title": "caseName", "case_no": "caseNo", "court": "court" },
      "budget": 20
    }
  }
}
```

AppCode 不写进配置文件，只从 `ALIYUN_APPCODE` 环境变量或 `.state/aliyun_appcode.txt` 读。

跑法：

```powershell
$env:ALIYUN_APPCODE = "你的 AppCode"
python -m boss_crawler app run --platforms aliyun --limit 5
```

**这个适配器没有用真实 AppCode 验证过**——我没有购买记录。离线测试覆盖了配置解析、
URL 拼装、响应归一、缺 key/缺配置/超预算的降级；真实响应字段需要你买到后按实际返回
调整 `fields` 映射。这一点我在文档里写明，不假装验证过。

### 建议

优先级从高到低：

1. **cninfo（已接）**——免费、免鉴权、结构化，缺点是只覆盖上市公司；
2. **云市场司法不良（￥2/10 次）**——想覆盖非上市公司时最划算的起点，先买 10 次试字段；
3. **人民法院公告网**——免费无验证码，但解析成本高于 2；
4. 天眼查/企查查官方 API——除非要长期稳定 SLA，否则性价比最差。

组合用：cninfo 打底（免费）+ 云市场补非上市（按次），比单独任何一家都便宜。

## 六、后续可做

1. **人民法院公告网 provider**：无验证码，能覆盖非上市公司（开庭/破产），
   接入成本比 cninfo 高一点，价值在于补上「非上市」这个盲区；
2. **公告正文解析**：现在只按标题分类，金额/案号要读 PDF，成本高收益也高；
3. **缓存**：同一家公司 7 天内不重复查，减少请求量。

## 来源

- [巨潮资讯公告接口](http://www.cninfo.com.cn/new/hisAnnouncement/query)
- [人民法院公告网](https://rmfygg.court.gov.cn/web/rmfyportal/noticeinfo)
- [gsxt](https://www.gsxt.gov.cn/index.html)｜[执行信息公开网](https://zxgk.court.gov.cn/shixin/)
- [信用中国](https://www.creditchina.gov.cn/)｜[裁判文书网 robots](https://wenshu.court.gov.cn/robots.txt)
- [企查查价格](https://openapi.qcc.com/data)｜[充值门槛](https://openapi.qcc.com/recharge)
- [启信宝购买指南](https://data.qixin.com/apiHelp/before-service/buy-guide)
- [水滴信用 robots](https://shuidi.cn/robots.txt)｜[爱企查 robots](https://aiqicha.baidu.com/robots.txt)
