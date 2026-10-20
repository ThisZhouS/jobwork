/* 渲染进程：路由 + 页面 + 组件。只调 window.api，不碰 Node。 */
"use strict";

// ---------------------------------------------------------------- 工具
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const page = () => $("#page");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmt(n, digits = 1) {
  return (n === null || n === undefined || Number.isNaN(Number(n))) ? "—" : Number(n).toFixed(digits);
}
function gradeClass(g) { return "grade grade-" + (g || "?"); }
function laborPill(v, reason) {
  if (v === true) return `<span class="pill pill-warn" title="${esc(reason || "")}">疑似劳务派遣</span>`;
  if (v === false) return `<span class="pill pill-ok" title="${esc(reason || "")}">非劳务派遣</span>`;
  return `<span class="pill pill-dim" title="${esc(reason || "")}">劳务派遣：未知</span>`;
}
async function call(action, args) {
  const res = await window.api.call(action, args || {});
  if (res.code !== 0) {
    chatLog("err", `${action} 失败`, res.stderr || res.stdout || `退出码 ${res.code}`);
    return null;
  }
  return res.data;
}
function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---------------------------------------------------------------- 路由
const routes = {
  "/": pageOverview,
  "/jobs": pageJobs,
  "/companies": pageCompanies,
  "/skills": pageSkills,
  "/resume": pageResume,
  "/settings": pageSettings,
};

let state = {
  data: null,          // app data 缓存
  filters: null,       // app filters 缓存
  lastRun: null,
};

function parseHash() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const [path, query] = hash.split("?");
  const params = Object.fromEntries(new URLSearchParams(query || ""));
  return { path, params };
}

async function router() {
  const { path, params } = parseHash();
  $$("#nav a").forEach((a) => {
    const r = a.dataset.route;
    a.classList.toggle("active", r === path || (r !== "/" && path.startsWith(r)));
  });
  // 详情页
  let m;
  if ((m = path.match(/^\/companies\/(.+)$/))) return pageCompanyDetail(decodeURIComponent(m[1]), params);
  if ((m = path.match(/^\/jobs\/(.+)$/))) return pageJobDetail(decodeURIComponent(m[1]));
  const fn = routes[path] || pageOverview;
  try { await fn(params); } catch (e) { page().innerHTML = `<div class="empty">页面出错：${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", router);

function go(hash) { location.hash = hash; }
function goCompany(key) { go("#/companies/" + encodeURIComponent(key)); }
function goJob(id) { go("#/jobs/" + encodeURIComponent(id)); }
function goSeries(key, field) { go("#/companies/" + encodeURIComponent(key) + "?series=" + encodeURIComponent(field)); }

// ---------------------------------------------------------------- 对话口
const chatDrawer = () => $("#chat-drawer");
function chatOpen() { chatDrawer().hidden = false; }
function chatToggle() { chatDrawer().hidden = !chatDrawer().hidden; }
$("#chat-toggle").addEventListener("click", chatToggle);
$("#chat-close").addEventListener("click", () => { chatDrawer().hidden = true; });

function chatLog(kind, who, text) {
  chatOpen();
  $("#chat-badge").hidden = false;
  const log = $("#chat-log");
  const div = document.createElement("div");
  div.className = "msg msg-" + kind;
  div.innerHTML = `<div class="who">${esc(who)}</div><div class="bubble">${esc(text)}</div>`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}
function chatProgress(name, current, total, message) {
  let el = $("#chat-progress");
  if (!el) {
    el = document.createElement("div");
    el.id = "chat-progress";
    el.className = "msg msg-progress";
    $("#chat-log").appendChild(el);
  }
  el.textContent = `[${current}/${total}] ${name} ${message || ""}`;
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
}
function chatQuestions(questions, onSubmit) {
  const box = $("#chat-questions");
  box.innerHTML = "";
  questions.forEach((q, i) => {
    const div = document.createElement("div");
    div.className = "q-item";
    div.innerHTML = `<div class="q-text">${i + 1}. ${esc(q)}</div>
      <div class="q-answer"><input type="text" data-q="${i}" placeholder="可不答，直接提交">
      <button class="btn btn-sm" data-answer="${i}">答</button></div>`;
    box.appendChild(div);
  });
  const submit = document.createElement("button");
  submit.className = "btn btn-sm";
  submit.textContent = "全部提交";
  submit.style.marginTop = "4px";
  submit.addEventListener("click", () => {
    const answers = $$("input[data-q]", box).map((input, i) => ({
      question: questions[i], answer: input.value.trim(),
    })).filter((a) => a.answer);
    onSubmit(answers);
  });
  box.appendChild(submit);
}

// 流式运行：把事件喂给对话口
async function streamRun(args, onDone) {
  chatOpen();
  chatLog("sys", "系统", "开始运行流水线…");
  const id = await window.api.stream("run", args, (event) => {
    if (event.type === "step") chatLog("sys", "步骤", `${event.name} [${event.status}] ${event.detail || ""}`);
    else if (event.type === "progress") chatProgress(event.name, event.current, event.total, event.message);
    else if (event.type === "error") chatLog("err", event.agent || "错误", event.message || "");
    else if (event.type === "warn") chatLog("err", event.name || "警告", event.message || "");
    else if (event.type === "login") chatLog("sys", "登录", `${event.platform}: ${event.message}`);
    else if (event.type === "__done__") {
      chatLog("sys", "系统", `运行结束（退出码 ${event.code}）`);
      if (onDone) onDone(event);
    }
  });
  return id;
}

// ---------------------------------------------------------------- 组件
function kpi(num, label) {
  return `<div class="card kpi"><div class="kpi-num">${esc(num)}</div><div class="kpi-label">${esc(label)}</div></div>`;
}
function dimBar(name, value) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  return `<div class="dim-row"><span class="dim-name">${esc(name)}</span>
    <div class="dim-bar"><div class="dim-fill" style="width:${v}%"></div></div>
    <span class="dim-val">${fmt(value, 0)}</span></div>`;
}
function radarSVG(dims, size = 260) {
  // dims: [{name, score}]，五维雷达，不叠加
  if (!dims || !dims.length) return `<div class="empty">暂无评分</div>`;
  const cx = size / 2, cy = size / 2, R = size / 2 - 34;
  const n = dims.length;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  let rings = "";
  [0.25, 0.5, 0.75, 1].forEach((f) => {
    const pts = dims.map((_, i) => pt(i, R * f).join(",")).join(" ");
    rings += `<polygon points="${pts}" fill="none" stroke="#22314f" stroke-width="1"/>`;
  });
  let axes = "", labels = "";
  dims.forEach((d, i) => {
    const [x, y] = pt(i, R);
    axes += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#22314f"/>`;
    const [lx, ly] = pt(i, R + 16);
    labels += `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle">${esc(d.name)}</text>`;
  });
  const dataPts = dims.map((d, i) => pt(i, R * Math.max(0, Math.min(100, d.score)) / 100).join(",")).join(" ");
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
    ${rings}${axes}
    <polygon points="${dataPts}" fill="rgba(34,211,238,.18)" stroke="#22d3ee" stroke-width="2"/>
    ${labels}</svg>`;
}
function lineSVG(points, w = 560, h = 200) {
  if (!points || points.length < 2) return `<div class="empty">数据点不足（需要重跑几次流水线积累历史）</div>`;
  const vals = points.map((p) => Number(p.value)).filter((v) => !Number.isNaN(v));
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = 26, iw = w - pad * 2, ih = h - pad * 2;
  const span = (max - min) || 1;
  const xy = points.map((p, i) => {
    const x = pad + (iw * i) / (points.length - 1);
    const y = pad + ih - ((Number(p.value) - min) / span) * ih;
    return [x, y];
  });
  const path = xy.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const dots = xy.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="#22d3ee"/>`).join("");
  const labels = `<text x="${pad}" y="${h - 6}" fill="#5b6a8c" font-size="11">${esc(String(points[0].at).slice(0, 10))}</text>
    <text x="${w - pad}" y="${h - 6}" fill="#5b6a8c" font-size="11" text-anchor="end">${esc(String(points[points.length - 1].at).slice(0, 10))}</text>
    <text x="${pad}" y="${pad - 8}" fill="#22d3ee" font-size="12">max ${fmt(max, 0)}</text>
    <text x="${w - pad}" y="${pad - 8}" fill="#8b98b8" font-size="12" text-anchor="end">min ${fmt(min, 0)}</text>`;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="max-width:100%">
    <path d="${path}" fill="none" stroke="#22d3ee" stroke-width="2"/>${dots}${labels}</svg>`;
}
function companyRow(c) {
  const s = c.score || {};
  const dims = s.dimensions || {};
  return `<tr data-company="${esc(c.company_key)}">
    <td class="link">${esc(c.name)}</td>
    <td class="num score">${fmt(s.total)}</td>
    <td><span class="${gradeClass(s.grade)}">${esc(s.grade || "?")}</span></td>
    <td class="num">${fmt(dims["风险"], 0)}</td><td class="num">${fmt(dims["待遇"], 0)}</td>
    <td class="num">${fmt(dims["压力"], 0)}</td><td class="num">${fmt(dims["环境"], 0)}</td>
    <td class="num">${fmt(dims["福利"], 0)}</td>
    <td>${laborPill(s.is_labor_dispatch, s.labor_dispatch_reason)}</td>
    <td class="num">${c.evidence ? c.evidence.total : 0}</td></tr>`;
}

// ---------------------------------------------------------------- 页面：概览
async function pageOverview() {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const data = state.data || await call("data");
  if (!data) { page().innerHTML = `<div class="empty">取数失败，看对话口</div>`; return; }
  state.data = data;
  // 有打分的排前面，未打分的沉底（概览页一眼看到结论）
  const sorted = [...data.companies].sort((a, b) => {
    const sa = a.score && a.score.total != null ? a.score.total : -1;
    const sb = b.score && b.score.total != null ? b.score.total : -1;
    return sb - sa;
  });
  const scored = sorted.filter((c) => c.score && c.score.total != null);
  const fitted = data.jobs.filter((j) => j.fit);
  const negEvidence = data.companies.reduce((s, c) => s + ((c.evidence || {}).negative || 0), 0);

  page().innerHTML = `
    <div class="page-head"><div class="page-title">概览</div>
      <div class="page-sub">采集 → 背调 → 打分 → 适配度 的当前状态</div></div>
    <div class="grid grid-4">
      ${kpi(data.companies.length, "公司")}
      ${kpi(data.jobs.length, "岗位")}
      ${kpi(scored.length, "已打分公司")}
      ${kpi(negEvidence, "负面证据")}
    </div>
    <div class="grid grid-21" style="margin-top:16px">
      <div class="card">
        <div class="card-title">公司评分（点行看详情，点维度看趋势）</div>
        <table><thead><tr>
          <th>公司</th><th class="num">总分</th><th>等级</th>
          <th class="num">风险</th><th class="num">待遇</th><th class="num">压力</th>
          <th class="num">环境</th><th class="num">福利</th><th>劳务派遣</th><th class="num">证据</th>
        </tr></thead><tbody>
          ${sorted.slice(0, 15).map(companyRow).join("") || `<tr><td colspan="10" class="empty">还没有数据，先去「岗位」跑一次流水线</td></tr>`}
        </tbody></table>
      </div>
      <div class="card">
        <div class="card-title">岗位适配度 TOP</div>
        ${fitted.length ? fitted.slice(0, 8).map((j) => `
          <div class="dim-row" style="cursor:pointer" data-job="${esc(j.id)}">
            <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.title)}</span>
            <span class="score">${fmt(j.fit.total)}</span>
            <span class="${gradeClass(j.fit.grade)}">${esc(j.fit.grade || "?")}</span>
          </div>`).join("") : `<div class="empty">还没有适配度数据<br><span style="font-size:12px">需要一份已确认的简历</span></div>`}
        <div style="margin-top:12px;color:var(--text-faint);font-size:12px">
          共 ${data.companies.length} 家公司，${scored.length} 家已打分
        </div>
      </div>
    </div>`;
  bindRowNav();
}

function bindRowNav() {
  $$("[data-company]").forEach((el) => el.addEventListener("click", () => goCompany(el.dataset.company)));
  $$("[data-job]").forEach((el) => el.addEventListener("click", () => goJob(el.dataset.job)));
  $$("[data-series]").forEach((el) => el.addEventListener("click", (e) => {
    e.stopPropagation();
    goSeries(el.dataset.company, el.dataset.series);
  }));
}

// ---------------------------------------------------------------- 页面：岗位（筛选 + 列表）
async function pageJobs() {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const [filters, data] = await Promise.all([
    state.filters ? Promise.resolve(state.filters) : call("filters"),
    state.data ? Promise.resolve(state.data) : call("data"),
  ]);
  if (filters) state.filters = filters;
  if (data) state.data = data;
  if (!filters || !data) { page().innerHTML = `<div class="empty">取数失败，看对话口</div>`; return; }

  const filterFields = filters.fields.map((f) => `
    <div class="field" style="min-width:150px;flex:1">
      <label>${esc(f.label)}</label>
      <select data-filter="${esc(f.field)}">
        <option value="">不限</option>
        ${f.options.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("")}
      </select>
    </div>`).join("");

  page().innerHTML = `
    <div class="page-head"><div class="page-title">岗位</div>
      <div class="page-sub">筛选条件直接映射 BOSS 直聘，提交后跑采集 + 背调 + 打分</div></div>
    <div class="card">
      <div class="card-title">筛选与运行</div>
      <div style="display:flex;gap:14px;flex-wrap:wrap">
        <div class="field" style="min-width:200px;flex:2">
          <label>关键词（必填）</label>
          <input type="text" id="f-query" placeholder="如 Python、数据分析">
        </div>
        <div class="field" style="min-width:120px;flex:1">
          <label>城市</label>
          <input type="text" id="f-city" placeholder="如 成都">
        </div>
        ${filterFields}
        <div class="field" style="min-width:90px">
          <label>页数</label>
          <input type="number" id="f-pages" value="1" min="1" max="10">
        </div>
        <div class="field" style="min-width:90px">
          <label>公司数</label>
          <input type="number" id="f-limit" value="10" min="1" max="50">
        </div>
      </div>
      <div class="field"><label>背调平台与开关</label>
        <div class="checkbox-row" id="f-toggles"></div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn" id="btn-run">开始运行</button>
        <button class="btn btn-danger" id="btn-stop" disabled>停止</button>
        <button class="btn btn-ghost" id="btn-nocrawl">只重算（不采集）</button>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="card-title">岗位列表（点行看详情）</div>
      <table><thead><tr>
        <th>岗位</th><th>公司</th><th>薪资</th><th>城市</th>
        <th class="num">适配度</th><th>等级</th>
      </tr></thead><tbody>
        ${(data.jobs || []).map((j) => `<tr data-job="${esc(j.id)}">
          <td class="link">${esc(j.title)}</td>
          <td>${esc(j.company || "")}</td>
          <td>${esc(j.salary || "—")}</td>
          <td>${esc(j.city || "—")}</td>
          <td class="num score">${j.fit ? fmt(j.fit.total) : "—"}</td>
          <td>${j.fit ? `<span class="${gradeClass(j.fit.grade)}">${esc(j.fit.grade || "?")}</span>` : "—"}</td>
        </tr>`).join("") || `<tr><td colspan="6" class="empty">暂无岗位</td></tr>`}
      </tbody></table>
    </div>`;

  // 开关
  const toggles = $("#f-toggles");
  filters.toggles.forEach((t) => {
    if (t.field === "platforms") {
      t.options.forEach((p, i) => {
        toggles.insertAdjacentHTML("beforeend",
          `<label><input type="checkbox" data-platform="${esc(p)}" ${i < 4 ? "checked" : ""}> ${esc(p)}</label>`);
      });
    } else {
      toggles.insertAdjacentHTML("beforeend",
        `<label><input type="checkbox" data-toggle="${esc(t.field)}" checked> ${esc(t.label)}</label>`);
    }
  });

  let currentStream = null;
  const runBtn = $("#btn-run"), stopBtn = $("#btn-stop");
  async function startRun(noCrawl) {
    const query = $("#f-query").value.trim();
    if (!query && !noCrawl) { chatLog("err", "校验", "请填关键词"); return; }
    const platforms = $$("input[data-platform]:checked").map((i) => i.dataset.platform);
    const args = {
      query, city: $("#f-city").value.trim(),
      pages: $("#f-pages").value, limit: $("#f-limit").value,
      platforms: platforms.join(","),
      no_crawl: !!noCrawl,
    };
    $$("input[data-toggle]").forEach((i) => {
      if (!i.checked) args["no_" + i.dataset.toggle.replace("enable_", "")] = true;
    });
    runBtn.disabled = true; stopBtn.disabled = false;
    currentStream = await streamRun(args, async () => {
      runBtn.disabled = false; stopBtn.disabled = false;
      state.data = null;
      const fresh = await call("data");
      if (fresh) { state.data = fresh; }
      router();
    });
  }
  runBtn.addEventListener("click", () => startRun(false));
  $("#btn-nocrawl").addEventListener("click", () => startRun(true));
  stopBtn.addEventListener("click", () => {
    if (currentStream) window.api.cancel(currentStream);
    runBtn.disabled = false; stopBtn.disabled = true;
    chatLog("sys", "系统", "已停止");
  });
  bindRowNav();
}

// ---------------------------------------------------------------- 页面：公司（维度表）
async function pageCompanies() {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const data = state.data || await call("data");
  if (!data) { page().innerHTML = `<div class="empty">取数失败</div>`; return; }
  state.data = data;
  page().innerHTML = `
    <div class="page-head"><div class="page-title">公司</div>
      <div class="page-sub">点公司名看详情；点维度数值看该字段的历史折线</div></div>
    <div class="card">
      <table><thead><tr>
        <th>公司</th><th class="num">总分</th><th>等级</th>
        <th class="num">风险</th><th class="num">待遇</th><th class="num">压力</th>
        <th class="num">环境</th><th class="num">福利</th><th>劳务派遣</th><th class="num">证据</th>
      </tr></thead><tbody>
        ${(data.companies || []).map((c) => {
          const s = c.score || {};
          const dims = s.dimensions || {};
          const dimCell = (name) => s.total != null
            ? `<td class="num link" data-company="${esc(c.company_key)}" data-series="${name}" title="看${name}趋势">${fmt(dims[name], 0)}</td>`
            : `<td class="num">—</td>`;
          return `<tr>
            <td class="link" data-company="${esc(c.company_key)}">${esc(c.name)}</td>
            <td class="num score">${fmt(s.total)}</td>
            <td>${s.grade ? `<span class="${gradeClass(s.grade)}">${esc(s.grade)}</span>` : "—"}</td>
            ${dimCell("风险")}${dimCell("待遇")}${dimCell("压力")}${dimCell("环境")}${dimCell("福利")}
            <td>${laborPill(s.is_labor_dispatch, s.labor_dispatch_reason)}</td>
            <td class="num">${c.evidence ? c.evidence.total : 0}</td></tr>`;
        }).join("") || `<tr><td colspan="10" class="empty">暂无公司</td></tr>`}
      </tbody></table>
    </div>`;
  bindRowNav();
}

// ---------------------------------------------------------------- 页面：公司详情
async function pageCompanyDetail(key, params) {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const d = await call("company", { company_key: key });
  if (!d) { page().innerHTML = `<div class="empty">取数失败</div>`; return; }
  const s = d.score || {};
  const b = d.basic || {};
  const dispatch = d.labor_dispatch || {};
  const seriesField = params.series;

  let seriesHtml = "";
  if (seriesField) {
    const series = await call("series", { company_key: key, field: seriesField });
    seriesHtml = `<div class="card section">
      <div class="card-title">${esc(seriesField)} · 历史趋势</div>
      ${lineSVG(series ? series.points : [])}
      <div class="chart-note">数据来自历次流水线运行；点别的维度可切换</div>
    </div>`;
  }

  const dimList = (s.dimensions || []).map((dim) => dim.name);
  page().innerHTML = `
    <div class="detail-head">
      <h2>${esc(d.name)}</h2>
      ${b.reg_status ? `<span class="pill pill-cyan">${esc(b.reg_status)}</span>` : ""}
      ${s.total != null ? `<span class="score" style="font-size:20px">${fmt(s.total)}</span>
        <span class="${gradeClass(s.grade)}" style="font-size:16px">${esc(s.grade || "?")}</span>` : ""}
      ${laborPill(dispatch.is_labor_dispatch, dispatch.reason)}
      <a class="link" href="#/companies">← 返回列表</a>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">维度评分（点字段看趋势）</div>
        <div class="radar-wrap">${radarSVG(s.dimensions || [])}</div>
        <div>${(s.dimensions || []).map((dim) =>
          `<div class="dim-row" style="cursor:pointer" data-company="${esc(key)}" data-series="${esc(dim.name)}" title="看${esc(dim.name)}趋势">
            <span class="dim-name link">${esc(dim.name)}</span>
            <div class="dim-bar"><div class="dim-fill" style="width:${Math.min(100, dim.score)}%"></div></div>
            <span class="dim-val">${fmt(dim.score, 0)}</span></div>`).join("")}
        </div>
        ${s.verdict ? `<div style="margin-top:8px;color:var(--text-dim);font-size:13px">${esc(s.verdict)}</div>` : ""}
        ${(s.advice || []).length ? `<div style="margin-top:8px">${s.advice.map((a) => `<div class="tag tag-cyan">${esc(a)}</div>`).join("")}</div>` : ""}
      </div>
      <div class="card">
        <div class="card-title">基本信息</div>
        <dl class="kv">
          <dt>注册资本</dt><dd>${esc(b.reg_capital || "—")}</dd>
          <dt>成立时间</dt><dd>${esc(b.estiblish_time || "—")}</dd>
          <dt>法定代表人</dt><dd>${esc(b.legal_person || "—")}</dd>
          <dt>人员规模</dt><dd>${esc(b.staff_num || "—")}</dd>
          <dt>所属行业</dt><dd>${esc(b.industry || "—")}</dd>
          <dt>注册地址</dt><dd>${esc(b.reg_location || "—")}</dd>
          <dt>信用代码</dt><dd>${esc(b.credit_code || "—")}</dd>
          <dt>经营范围</dt><dd>${esc(b.business_scope || "—")}</dd>
        </dl>
        ${!b.raw_available ? `<div class="chart-note">天眼查原始数据未入库，以上多为空属正常</div>` : ""}
      </div>
    </div>
    ${seriesHtml}
    <div class="grid grid-2 section">
      <div class="card">
        <div class="card-title">风险</div>
        ${Object.keys(d.risk?.counts || {}).length
          ? Object.entries(d.risk.counts).map(([k, v]) => `<div class="dim-row"><span style="flex:1">${esc(k)}</span><span class="score">${v}</span></div>`).join("")
          : `<div class="empty">无风险计数</div>`}
        <div class="chart-note">负面证据 ${d.risk?.evidence_negative || 0} 条</div>
      </div>
      <div class="card">
        <div class="card-title">在招岗位（${(d.jobs || []).length}）</div>
        ${(d.jobs || []).slice(0, 8).map((j) => `
          <div class="dim-row" style="cursor:pointer" data-job="${esc(j.job_id)}">
            <span class="link" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.title)}</span>
            <span class="tag">${esc(j.salary || "—")}</span>
          </div>`).join("") || `<div class="empty">无在招岗位</div>`}
      </div>
    </div>
    <div class="card section">
      <div class="card-title">评价（${Object.values(d.reviews || {}).reduce((n, arr) => n + arr.length, 0)} 条）</div>
      ${Object.entries(d.reviews || {}).map(([src, items]) => `
        <div style="margin-bottom:12px"><div class="card-sub">${esc(src)}（${items.length}）</div>
        ${items.slice(0, 6).map((r) => `
          <div class="review-item">
            <div class="r-title">
              ${r.sentiment != null ? `<span class="${r.sentiment < 0 ? "senti-neg" : "senti-pos"}">${r.sentiment < 0 ? "负" : "正"}</span>` : ""}
              ${r.url ? `<a class="link" data-url="${esc(r.url)}">${esc(r.title || "(无标题)")}</a>` : esc(r.title || "(无标题)")}
            </div>
            ${r.snippet ? `<div class="r-snippet">${esc(String(r.snippet).slice(0, 140))}</div>` : ""}
            <div class="r-meta">${esc(r.published_at || "")}</div>
          </div>`).join("")}
        </div>`).join("") || `<div class="empty">暂无评价（背调未跑或平台未登录）</div>`}
    </div>`;
  bindRowNav();
  $$("[data-url]").forEach((el) => el.addEventListener("click", (e) => {
    e.stopPropagation(); window.api.openExternal(el.dataset.url);
  }));
}

// ---------------------------------------------------------------- 页面：岗位详情
async function pageJobDetail(id) {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const d = await call("job", { job_id: id });
  if (!d) { page().innerHTML = `<div class="empty">没有这个岗位</div>`; return; }
  const c = d.company || {};
  const f = d.fit || {};
  page().innerHTML = `
    <div class="detail-head">
      <h2>${esc(d.title)}</h2>
      <span class="pill pill-cyan">${esc(d.salary || "薪资面议")}</span>
      ${d.city ? `<span class="pill">${esc(d.city)}${d.district ? " · " + esc(d.district) : ""}</span>` : ""}
      ${f.total != null ? `<span class="score" style="font-size:20px">${fmt(f.total)}</span>
        <span class="${gradeClass(f.grade)}">${esc(f.grade || "?")}</span>` : ""}
      <a class="link" href="#/jobs">← 返回列表</a>
    </div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">岗位信息</div>
        <dl class="kv">
          <dt>经验要求</dt><dd>${esc(d.experience || "—")}</dd>
          <dt>学历要求</dt><dd>${esc(d.degree || "—")}</dd>
          <dt>所属行业</dt><dd>${esc(d.industry || "—")}</dd>
          <dt>技能要求</dt><dd>${(d.skills || []).map((s) => `<span class="tag">${esc(s)}</span>`).join("") || "—"}</dd>
          <dt>福利</dt><dd>${(d.welfare || []).map((s) => `<span class="tag">${esc(s)}</span>`).join("") || "—"}</dd>
        </dl>
        <div class="section-title" style="margin-top:14px">岗位描述</div>
        <div style="font-size:13px;color:var(--text-dim);white-space:pre-wrap;max-height:300px;overflow-y:auto">${esc(d.description || "（未采集到 JD 正文）")}</div>
      </div>
      <div>
        <div class="card">
          <div class="card-title">招聘公司</div>
          ${c.name ? `
            <div class="dim-row"><span class="link" style="flex:1;font-size:15px" data-company="${esc(c.company_key || "")}">${esc(c.name)}</span>
              ${c.score && c.score.total != null ? `<span class="score">${fmt(c.score.total)}</span>
                <span class="${gradeClass(c.score.grade)}">${esc(c.score.grade || "?")}</span>` : ""}
            </div>
            ${c.score ? `<div style="margin-top:6px">${laborPill(c.score.is_labor_dispatch, "")}</div>` : ""}
            <div class="chart-note">点公司名看背调详情</div>` : `<div class="empty">无公司信息</div>`}
        </div>
        <div class="card section">
          <div class="card-title">信息来源</div>
          <dl class="kv">
            <dt>来源</dt><dd>${esc(d.source?.name || "—")}</dd>
            <dt>岗位链接</dt><dd>${d.source?.url ? `<a class="link" data-url="${esc(d.source.url)}">${esc(d.source.url.slice(0, 48))}…</a>` : "—"}</dd>
          </dl>
          <div style="margin-top:10px">
            ${d.source?.url ? `<button class="btn btn-sm" id="btn-open-source">在浏览器打开原帖</button>` : ""}
            <button class="btn btn-ghost btn-sm" id="btn-tailor">按这个岗位改简历</button>
          </div>
        </div>
        ${f.dimensions ? `<div class="card section">
          <div class="card-title">适配度明细</div>
          ${Object.entries(f.dimensions).map(([k, v]) => dimBar(k, v)).join("")}
          ${(f.advice || []).length ? `<div style="margin-top:8px">${f.advice.map((a) => `<div class="tag tag-cyan">${esc(a)}</div>`).join("")}</div>` : ""}
        </div>` : ""}
      </div>
    </div>`;
  bindRowNav();
  const openBtn = $("#btn-open-source");
  if (openBtn) openBtn.addEventListener("click", () => window.api.openExternal(d.source.url));
  $$("[data-url]").forEach((el) => el.addEventListener("click", (e) => {
    e.stopPropagation(); window.api.openExternal(el.dataset.url);
  }));
  $("#btn-tailor").addEventListener("click", () => {
    go("#/resume?job=" + encodeURIComponent(id));
  });
}

async function pageSkills() {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const data = await call("cloud");
  if (!data) { page().innerHTML = `<div class="empty">取数失败</div>`; return; }
  const skills = data.skills || [];
  const max = Math.max(...skills.map((s) => s.count), 1);
  page().innerHTML = `
    <div class="page-head"><div class="page-title">技能词云</div>
      <div class="page-sub">按"出现在多少个岗位"统计，共 ${data.total} 次提及</div></div>
    <div class="card"><div class="cloud">
      ${skills.map((s) => {
        const size = 13 + (s.count / max) * 34;
        const opacity = 0.45 + (s.count / max) * 0.55;
        return `<span style="font-size:${size.toFixed(0)}px;opacity:${opacity.toFixed(2)}" title="出现在 ${s.count} 个岗位">${esc(s.name)}</span>`;
      }).join("") || `<div class="empty">暂无技能数据</div>`}
    </div></div>`;
}

// ---------------------------------------------------------------- 页面：简历
async function pageResume(params) {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const data = await call("resume");
  const r = data && data.ok ? data.resume : null;
  const questions = (data && data.questions) || [];
  const targetJob = params.job || "";

  page().innerHTML = `
    <div class="page-head"><div class="page-title">简历</div>
      <div class="page-sub">输入母版简历 → 选岗位 → 生成定向版本。定向版本未经你确认不会生效</div></div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">母版简历（JSON）</div>
        <div class="field"><label>内容：name / summary / skills[] / experience[] / projects[]</label>
          <textarea id="resume-content" style="min-height:280px;font-family:Consolas,monospace;font-size:12px">${esc(r ? JSON.stringify(r.content, null, 2) : `{
  "name": "张三",
  "summary": "3 年后端开发，熟悉高并发订单系统",
  "skills": ["Python", "MySQL", "Redis"],
  "experience": [
    {"title": "后端工程师", "org": "某公司", "highlights": ["日订单百万级", "接口 P99 80ms"]}
  ]
}`)}</textarea>
        </div>
        <div style="display:flex;gap:10px">
          <button class="btn" id="btn-save-resume">保存母版</button>
          ${r ? `<span class="pill ${r.confirmed ? "pill-ok" : "pill-warn"}">当前版本 #${r.id} ${r.confirmed ? "已确认" : "草稿（未确认）"}</span>` : ""}
        </div>
        <div class="chart-note">保存会写入 .state/tmp 再交给后端，不污染命令行</div>
      </div>
      <div class="card">
        <div class="card-title">定向到岗位</div>
        <div class="field"><label>岗位 ID（可从岗位详情页点「按这个岗位改简历」自动带过来）</label>
          <input type="text" id="resume-job" value="${esc(targetJob)}" placeholder="job_id">
        </div>
        <button class="btn" id="btn-tailor-run">生成定向版本</button>
        <div id="tailor-result" style="margin-top:14px"></div>
      </div>
    </div>`;

  $("#btn-save-resume").addEventListener("click", async () => {
    let content;
    try { content = JSON.parse($("#resume-content").value); }
    catch (e) { chatLog("err", "校验", "简历不是合法 JSON：" + e.message); return; }
    const tmp = await window.api.writeTemp("resume_input.json", JSON.stringify(content, null, 2));
    // 存母版：走 run 的 --resume 会先入库；这里用单独文件路径传给 run
    chatLog("sys", "简历", `已写入临时文件，运行定向时会使用：${tmp.path}`);
    state._resumePath = tmp.path;
    chatLog("sys", "简历", "母版已就绪，点「生成定向版本」生效");
  });

  $("#btn-tailor-run").addEventListener("click", async () => {
    const jobId = $("#resume-job").value.trim();
    if (!jobId) { chatLog("err", "校验", "请填岗位 ID"); return; }
    let resumePath = state._resumePath;
    if (!resumePath) {
      let content;
      try { content = JSON.parse($("#resume-content").value); }
      catch (e) { chatLog("err", "校验", "简历不是合法 JSON：" + e.message); return; }
      const tmp = await window.api.writeTemp("resume_input.json", JSON.stringify(content, null, 2));
      resumePath = tmp.path;
    }
    chatOpen();
    chatQuestions(questions, async (answers) => {
      const payload = { content: JSON.parse($("#resume-content").value), answers };
      const tmp = await window.api.writeTemp("resume_with_answers.json", JSON.stringify(payload, null, 2));
      await streamRun({
        no_crawl: true, no_backduty: true, no_score: true, no_fit: true,
        with_resume: true, job_id: jobId, resume: tmp.path, limit: 1,
      }, async () => {
        const fresh = await call("resume");
        const out = $("#tailor-result");
        if (fresh && fresh.ok && fresh.resume) {
          const rr = fresh.resume;
          out.innerHTML = `<div class="card" style="background:var(--bg-elev)">
            <div class="card-title">版本 #${rr.id} ${rr.confirmed
              ? `<span class="pill pill-ok">已确认</span>` : `<span class="pill pill-warn">草稿</span>`}</div>
            <pre style="font-size:12px;white-space:pre-wrap;max-height:320px;overflow-y:auto">${esc(JSON.stringify(rr.content, null, 2))}</pre>
          </div>`;
        }
      });
    });
    chatLog("sys", "简历", "请先在下方回答问题（可不答直接提交）");
  });
}

// ---------------------------------------------------------------- 页面：设置
async function pageSettings() {
  page().innerHTML = `<div class="loading">加载中…</div>`;
  const [status, models] = await Promise.all([call("status"), call("models")]);
  if (!status) { page().innerHTML = `<div class="empty">自检失败，看对话口</div>`; return; }

  const db = status.db || {};
  const login = status.login || {};
  const checkPill = (ok) => ok
    ? `<span class="pill pill-ok">正常</span>` : `<span class="pill pill-bad">异常</span>`;

  page().innerHTML = `
    <div class="page-head"><div class="page-title">设置</div>
      <div class="page-sub">初始化、平台登录、数据源与模型可用性</div></div>
    <div class="grid grid-2">
      <div class="card">
        <div class="card-title">数据库</div>
        <div class="dim-row"><span style="flex:1">连接状态</span>${checkPill(db.ok)}</div>
        <div class="dim-row"><span style="flex:1">岗位</span><span class="score">${db.jobs ?? "—"}</span></div>
        <div class="dim-row"><span style="flex:1">公司</span><span class="score">${db.companies ?? "—"}</span></div>
        <div class="dim-row"><span style="flex:1">公司打分记录</span><span class="score">${db.company_score ?? "—"}</span></div>
        <div class="dim-row"><span style="flex:1">背调证据</span><span class="score">${db.backduty_evidence ?? "—"}</span></div>
        <div class="dim-row"><span style="flex:1">天眼查原始数据</span><span class="score">${db.backduty_raw ?? "—"}</span></div>
        <div class="dim-row"><span style="flex:1">岗位适配度</span><span class="score">${db.job_fit ?? "—"}</span></div>
        <div class="dim-row"><span style="flex:1">简历版本</span><span class="score">${db.resume_version ?? "—"}</span></div>
        <div class="dim-row"><span style="flex:1">报错日志</span><span class="score">${db.agent_error ?? "—"}</span></div>
        <div style="margin-top:14px;display:flex;gap:10px">
          <button class="btn btn-sm" id="btn-init">初始化 / 建表</button>
          <button class="btn btn-ghost btn-sm" id="btn-refresh">刷新自检</button>
          <a class="btn btn-ghost btn-sm" href="#/companies">看公司</a>
        </div>
      </div>
      <div class="card">
        <div class="card-title">模型（密钥只显示有无，不显示值）</div>
        ${(models?.models || []).map((m) => `
          <div class="dim-row">
            <span style="flex:1">${esc(m.name)} <span style="color:var(--text-faint);font-size:12px">${esc(m.kind)}</span></span>
            ${m.enabled
              ? (m.has_key ? `<span class="pill pill-ok">可用</span>` : `<span class="pill pill-warn">缺密钥</span>`)
              : `<span class="pill pill-dim">停用</span>`}
          </div>
          ${m.note ? `<div class="chart-note" style="text-align:left;margin:2px 0 8px">${esc(m.note)}</div>` : ""}
        `).join("") || `<div class="empty">无模型规格</div>`}
      </div>
    </div>
    <div class="grid grid-2 section">
      <div class="card">
        <div class="card-title">数据源（岗位从哪来）</div>
        ${(status.sources || []).map((s) => `
          <div class="dim-row">
            <span style="flex:1">${esc(s.label)} <span style="color:var(--text-faint);font-size:12px">${esc(s.name)}</span></span>
            ${s.implemented ? `<span class="pill pill-ok">已接入</span>` : `<span class="pill pill-dim">预留</span>`}
          </div>`).join("")}
        <div class="chart-note" style="text-align:left">预留插槽：实现对应 build_steps 即可接入新平台</div>
      </div>
      <div class="card">
        <div class="card-title">背调 agent</div>
        ${(status.agents || []).map((a) => `
          <div class="dim-row"><span style="flex:1">${esc(a.name)}</span>
            <span class="pill pill-dim">${esc(a.kind)}</span></div>`).join("")}
      </div>
    </div>
    <div class="card section">
      <div class="card-title">平台登录（会弹出真实浏览器窗口，请在窗口里完成登录）</div>
      <div class="checkbox-row" id="login-platforms">
        ${(status.platforms || []).map((p) =>
          `<label title="${esc(p.note || "")}"><input type="checkbox" data-login="${esc(p.key)}"> ${esc(p.label)}</label>`).join("")}
      </div>
      <div style="margin-top:12px;display:flex;gap:10px;align-items:center">
        <button class="btn btn-sm" id="btn-login">登录所选平台</button>
        <span style="font-size:12px;color:var(--text-faint)">登录态存到 .state/login，背调时自动带上</span>
      </div>
      <div id="login-status" style="margin-top:12px">
        ${Object.entries(login).length
          ? Object.entries(login).map(([p, v]) => `
            <div class="dim-row"><span style="flex:1">${esc(p)}</span>
              <span class="pill ${(v === "ok" || (v && v.status === "ok")) ? "pill-ok" : "pill-dim"}">
                ${esc(typeof v === "string" ? v : (v && v.status) || "未知")}</span></div>`).join("")
          : `<div class="chart-note" style="text-align:left">还没有登录记录</div>`}
      </div>
    </div>`;

  $("#btn-init").addEventListener("click", async () => {
    chatLog("sys", "初始化", "开始建表…");
    const res = await call("init");
    chatLog("sys", "初始化", res ? "完成" : "失败，看对话口");
    router();
  });
  $("#btn-refresh").addEventListener("click", router);
  // 登录用流式：进度实时进对话口
  $("#btn-login").addEventListener("click", async () => {
    const platforms = $$("input[data-login]:checked").map((i) => i.dataset.login);
    if (!platforms.length) { chatLog("err", "校验", "请选择要登录的平台"); return; }
    chatLog("sys", "登录", `将为 ${platforms.join("、")} 弹出浏览器，请在窗口里完成登录`);
    await window.api.stream("login", { platforms: platforms.join(",") }, (event) => {
      if (event.type === "login") chatLog("sys", "登录", `${event.platform}: ${event.message}`);
      else if (event.type === "step") chatLog("sys", "登录", `${event.name} ${event.detail || ""}`);
      else if (event.type === "error") chatLog("err", "登录", event.message || "");
      else if (event.type === "__done__") { chatLog("sys", "登录", "流程结束"); router(); }
    });
  });
}

// ---------------------------------------------------------------- 启动
(async function boot() {
  const status = await call("status");
  const dbOk = !!(status && status.db && status.db.ok);
  const pill = $("#db-status");
  pill.textContent = dbOk
    ? `已连接 · ${status.db.jobs} 岗位`
    : "数据库未连接";
  pill.className = "pill " + (dbOk ? "pill-ok" : "pill-bad");
  router();
})();


