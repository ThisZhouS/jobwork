/* 渲染进程：路由 + 页面 + 组件。只调 window.api，不碰 Node。
   视觉依据 docs/concepts/v2/01~04，结构说明见 Tree/desktop-redesign.md。 */
"use strict";

// ---------------------------------------------------------------- 基础
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const pageEl = () => $("#page");

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const fmt = (v, digits = 1) =>
  (v === null || v === undefined || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(digits);
const gradeClass = (g) => "grade grade-" + (g || "?");
const icon = (name, cls = "ni") => `<svg class="${cls}"><use href="#i-${name}"/></svg>`;
const laborPill = (flag, reason) => {
  const tip = reason ? ` title="${esc(reason)}"` : "";
  if (flag === true) return `<span class="pill pill-warn"${tip}>${icon("alert")}疑似派遣</span>`;
  if (flag === false) return `<span class="pill pill-ok"${tip}>${icon("check")}非派遣</span>`;
  return `<span class="pill pill-dim"${tip}>派遣：未知</span>`;
};
/* 表格内用紧凑标记，避免每行一个圆角胶囊 */
const laborMini = (flag, reason) => {
  const tip = reason ? ` title="${esc(reason)}"` : "";
  if (flag === true) return `<span class="mini mini-warn"${tip}>疑似</span>`;
  if (flag === false) return `<span class="mini mini-ok"${tip}>否</span>`;
  return `<span class="mini"${tip}>未知</span>`;
};
const pct = (v) => (v === null || v === undefined) ? "—" : Math.round(Number(v)) + "%";

const state = { data: null, filters: null, cloudKind: "all" };

async function call(action, args) {
  const res = await window.api.call(action, args || {});
  if (res.code !== 0) {
    chatLog("err", action, res.stderr || res.stdout || `退出码 ${res.code}`);
    return null;
  }
  return res.data;
}

// ---------------------------------------------------------------- 路由
const ROUTES = {
  "/": ["概览", pageOverview],
  "/jobs": ["岗位", pageJobs],
  "/companies": ["公司", pageCompanies],
  "/skills": ["技能词云", pageSkills],
  "/resume": ["简历", pageResume],
  "/settings": ["设置", pageSettings],
};

function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query] = raw.split("?");
  return { path, params: Object.fromEntries(new URLSearchParams(query || "")) };
}
const go = (hash) => { location.hash = hash; };
const goCompany = (k) => go("#/companies/" + encodeURIComponent(k));
const goJob = (id) => go("#/jobs/" + encodeURIComponent(id));
const goSeries = (k, f) => go(`#/companies/${encodeURIComponent(k)}?series=${encodeURIComponent(f)}`);

function crumb(...parts) {
  const items = parts.map((p, i) =>
    i === parts.length - 1 ? `<b>${esc(p)}</b>` : `${esc(p)}<span class="sep">${icon("chevron")}</span>`);
  $("#crumb").innerHTML = `${icon("home")}${items.join("")}`;
}

async function router() {
  const { path, params } = parseHash();
  $$("#nav a, .foot-link").forEach((a) => {
    const route = a.dataset.route;
    a.classList.toggle("active", route === path || (route !== "/" && path.startsWith(route)));
  });

  let m;
  try {
    if ((m = path.match(/^\/companies\/(.+)$/))) {
      crumb("公司", "详情");
      await pageCompanyDetail(decodeURIComponent(m[1]), params);
    } else if ((m = path.match(/^\/jobs\/(.+)$/))) {
      crumb("岗位", "详情");
      await pageJobDetail(decodeURIComponent(m[1]));
    } else {
      const entry = ROUTES[path] || ROUTES["/"];
      crumb("求职背调", entry[0]);
      await entry[1](params);
    }
  } catch (exc) {
    pageEl().innerHTML = `<div class="empty">页面出错：${esc(exc.message)}</div>`;
  }
}
window.addEventListener("hashchange", router);

// ---------------------------------------------------------------- 对话抽屉
const drawer = () => $("#chat-drawer");
const openDrawer = () => { drawer().hidden = false; $("#chat-badge").hidden = true; };
$("#chat-fab").addEventListener("click", () => {
  drawer().hidden = !drawer().hidden;
  if (!drawer().hidden) $("#chat-badge").hidden = true;
});
$("#chat-close").addEventListener("click", () => { drawer().hidden = true; });

const nowTime = () => {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

function chatLog(kind, who, text) {
  $("#chat-badge").hidden = false;
  const log = $("#chat-log");
  const node = document.createElement("div");
  node.className = "msg msg-" + kind;
  node.innerHTML = `<div class="msg-meta"><b>${esc(who)}</b><span>${nowTime()}</span></div>
    <div class="bubble">${esc(text)}</div>`;
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
}
function chatProgress(name, current, total, message) {
  let node = $("#chat-progress");
  if (!node) {
    node = document.createElement("div");
    node.id = "chat-progress";
    node.className = "msg msg-progress";
    $("#chat-log").appendChild(node);
  }
  node.textContent = `[${current}/${total}] ${name} ${message || ""}`;
  $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
}
function chatQuestions(questions, onSubmit) {
  const box = $("#chat-questions");
  box.innerHTML = "";
  if (!questions.length) {
    // 没有问题就直接给一个提交入口，避免卡住
    const only = document.createElement("button");
    only.className = "btn btn-sm";
    only.innerHTML = `${icon("check")}直接生成`;
    only.addEventListener("click", () => onSubmit([]));
    box.appendChild(only);
    return;
  }
  questions.forEach((question, index) => {
    const item = document.createElement("div");
    item.className = "q-item";
    item.innerHTML = `<div class="q-text">${index + 1}. ${esc(question)}</div>`;
    box.appendChild(item);
  });
  const row = document.createElement("div");
  row.className = "chat-compose";
  row.innerHTML = `<input type="text" id="q-input" placeholder="回答第一个问题，回车提交…">
    <button class="btn btn-sm" id="q-send">${icon("external")}发送</button>`;
  box.appendChild(row);

  let cursor = 0;
  const input = $("#q-input");
  const send = () => {
    const value = input.value.trim();
    if (!value) return;
    chatLog("out", "我", `${questions[cursor]} → ${value}`);
    answers.push({ question: questions[cursor], answer: value });
    cursor += 1;
    input.value = "";
    if (cursor >= questions.length) {
      box.innerHTML = "";
      chatLog("step", "系统", "问题已答完，开始生成");
      onSubmit(answers);
    } else {
      input.placeholder = `回答：${questions[cursor]}`;
      input.focus();
    }
  };
  const answers = [];
  $("#q-send").addEventListener("click", send);
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") send(); });
  input.focus();
}

async function streamRun(args, onDone) {
  openDrawer();
  chatLog("step", "系统", "开始运行流水线…");
  return window.api.stream("run", args, (event) => {
    if (event.type === "step") chatLog("step", "步骤", `${event.name} [${event.status}] ${event.detail || ""}`);
    else if (event.type === "progress") chatProgress(event.name, event.current, event.total, event.message);
    else if (event.type === "error") chatLog("err", event.agent || "错误", event.message || "");
    else if (event.type === "warn") chatLog("err", event.name || "警告", event.message || "");
    else if (event.type === "login") chatLog("step", "登录", `${event.platform}: ${event.message}`);
    else if (event.type === "__done__") {
      chatLog("step", "系统", `运行结束（退出码 ${event.code}）`);
      if (onDone) onDone(event);
    }
  });
}

// ---------------------------------------------------------------- 组件
const kpi = (value, label) =>
  `<div class="card kpi"><div class="kpi-num">${esc(value)}</div><div class="kpi-label">${esc(label)}</div></div>`;

const cardTitle = (text, iconName, info) =>
  `<div class="card-title">${iconName ? icon(iconName, "ni ti") : ""}${esc(text)}${info ? icon("info", "ni info") : ""}</div>`;

const toneOf = (value) => {
  const n = Number(value) || 0;
  if (n >= 80) return ["tone-good", "fill-good"];
  if (n >= 70) return ["tone-cyan", "fill-cyan"];
  if (n >= 60) return ["tone-mid", "fill-mid"];
  return ["tone-low", "fill-low"];
};

const metricRow = (name, value) => {
  const [tone, fill] = toneOf(value);
  return `<div class="metric">
    <div class="metric-top"><span class="metric-name">${esc(name)}</span>
      <span class="metric-val ${tone}">${fmt(value, 1)}</span></div>
    <div class="metric-bar"><div class="metric-fill ${fill}" style="width:${Math.max(0, Math.min(100, Number(value) || 0))}%"></div></div>
  </div>`;
};

const specRow = (label, value) =>
  `<div class="spec-row"><span class="spec-label">${esc(label)}</span><span class="spec-value">${value}</span></div>`;

const dimBar = (name, value) => `
  <div class="dim-row"><span class="dim-name">${esc(name)}</span>
    <div class="dim-bar"><div class="dim-fill" style="width:${Math.max(0, Math.min(100, Number(value) || 0))}%"></div></div>
    <span class="dim-val">${fmt(value, 0)}</span></div>`;

function gradeBadge(grade, circular) {
  const cls = circular ? "grade grade-round grade-" + (grade || "?") : gradeClass(grade);
  return `<span class="${cls}">${esc(grade || "?")}</span>`;
}

function rankRow(label, value, ratio, opts = {}) {
  const href = opts.href ? ` style="cursor:pointer" data-${opts.href.kind}="${esc(opts.href.id)}"` : "";
  const badge = opts.badge ? `<span class="rank-badge b${opts.badge}">#${opts.badge}</span>` : "";
  return `<div class="rank-row"${href}>
    ${badge}
    <span class="rank-label" style="width:${opts.labelWidth || 108}px" title="${esc(label)}">${esc(label)}</span>
    <div class="rank-bar"><div class="rank-fill" style="width:${Math.max(2, Math.min(100, ratio * 100)).toFixed(0)}%"></div></div>
    <span class="rank-num">${esc(value)}</span>
  </div>`;
}

function radarSVG(dimensions, size = 340) {
  if (!dimensions || !dimensions.length) return `<div class="empty">暂无评分</div>`;
  const cx = size / 2, cy = size / 2, R = size / 2 - 58;
  const n = dimensions.length;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const rings = [0.2, 0.4, 0.6, 0.8, 1].map((f) => {
    const pts = dimensions.map((_, i) => pt(i, R * f).join(",")).join(" ");
    return `<polygon points="${pts}" fill="none" stroke="rgba(148,163,184,.18)" stroke-width="1"/>`;
  }).join("");
  const axes = dimensions.map((_, i) => {
    const [x, y] = pt(i, R);
    return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="rgba(148,163,184,.18)"/>`;
  }).join("");
  const labels = dimensions.map((dim, i) => {
    const [x, y] = pt(i, R + 30);
    const anchor = Math.abs(x - cx) < 6 ? "middle" : (x > cx ? "start" : "end");
    return `<text x="${x}" y="${y - 4}" text-anchor="${anchor}" fill="#94A3B8" font-size="12">${esc(dim.name)}</text>
            <text x="${x}" y="${y + 12}" text-anchor="${anchor}" fill="#22D3EE" font-size="12.5" font-weight="600">${pct(dim.score)}</text>`;
  }).join("");
  const shape = dimensions
    .map((dim, i) => pt(i, R * Math.max(0, Math.min(100, dim.score)) / 100).join(",")).join(" ");
  const dots = dimensions
    .map((dim, i) => pt(i, R * Math.max(0, Math.min(100, dim.score)) / 100))
    .map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3.5" fill="#22D3EE"/>`).join("");
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img">
    ${rings}${axes}
    <polygon points="${shape}" fill="rgba(34,211,238,.14)" stroke="#22D3EE" stroke-width="2.2"/>
    ${dots}${labels}</svg>`;
}

function lineSVG(points, width = 640, height = 200) {
  if (!points || points.length < 2) return `<div class="empty">数据点不足（多跑几次流水线会积累历史）</div>`;
  const values = points.map((p) => Number(p.value)).filter((v) => !Number.isNaN(v));
  const min = Math.min(...values), max = Math.max(...values);
  const pad = 30, iw = width - pad * 2, ih = height - pad * 2;
  const span = (max - min) || 1;
  const coords = points.map((p, i) => [
    pad + (iw * i) / (points.length - 1),
    pad + ih - ((Number(p.value) - min) / span) * ih,
  ]);
  const path = coords.map((c, i) => `${i ? "L" : "M"}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(" ");
  const dots = coords.map((c) => `<circle cx="${c[0]}" cy="${c[1]}" r="3" fill="#22D3EE"/>`).join("");
  const first = String(points[0].at).slice(0, 10);
  const last = String(points[points.length - 1].at).slice(0, 10);
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="max-width:100%" role="img">
    <path d="${path}" fill="none" stroke="#22D3EE" stroke-width="2"/>${dots}
    <text x="${pad}" y="${height - 8}" fill="#64748B" font-size="11">${esc(first)}</text>
    <text x="${width - pad}" y="${height - 8}" fill="#64748B" font-size="11" text-anchor="end">${esc(last)}</text>
    <text x="${pad}" y="${pad - 10}" fill="#22D3EE" font-size="11">max ${fmt(max, 0)}</text>
    <text x="${width - pad}" y="${pad - 10}" fill="#64748B" font-size="11" text-anchor="end">min ${fmt(min, 0)}</text>
  </svg>`;
}

function pager(total, shown, page = 1) {
  return `<div class="table-foot">
    <span>显示 1–${shown} 条，共 ${total} 条</span>
    <div class="pager">
      <button disabled>‹</button><button class="active">1</button><button disabled>›</button>
    </div>
  </div>`;
}

function bindNav() {
  $$("tr[data-company]").forEach((row) => row.addEventListener("click", (e) => {
    if (e.target.closest("[data-series]")) return;
    goCompany(row.dataset.company);
  }));
  $$("[data-job]").forEach((node) => node.addEventListener("click", (e) => {
    if (e.target.closest("[data-series]") || e.target.closest("[data-company]")) return;
    goJob(node.dataset.job);
  }));
  $$("[data-series]").forEach((node) => node.addEventListener("click", (e) => {
    e.stopPropagation();
    goSeries(node.dataset.company || node.dataset.seriesCompany, node.dataset.series);
  }));
  $$("[data-url]").forEach((node) => node.addEventListener("click", (e) => {
    e.stopPropagation();
    if (node.dataset.url) window.api.openExternal(node.dataset.url);
  }));
  $$("[data-company]:not(tr)").forEach((node) => {
    if (node.dataset.series) return;
    node.addEventListener("click", () => goCompany(node.dataset.company));
  });
}

// ---------------------------------------------------------------- 概览
async function pageOverview() {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const data = state.data || await call("data");
  if (!data) { pageEl().innerHTML = `<div class="empty">取数失败，看右下角对话</div>`; return; }
  state.data = data;

  const sorted = [...(data.companies || [])].sort((a, b) => {
    const sa = a.score && a.score.total != null ? a.score.total : -1;
    const sb = b.score && b.score.total != null ? b.score.total : -1;
    return sb - sa;
  });
  const scored = sorted.filter((c) => c.score && c.score.total != null);
  const fitted = (data.jobs || []).filter((j) => j.fit).sort((a, b) => b.fit.total - a.fit.total);
  const negatives = sorted.reduce((sum, c) => sum + ((c.evidence || {}).negative || 0), 0);

  const rows = sorted.slice(0, 20).map((company) => {
    const s = company.score || {};
    const dims = s.dimensions || {};
    const dimCell = (name) => s.total != null
      ? `<td class="num link" data-company="${esc(company.company_key)}" data-series="${esc(name)}">${fmt(dims[name], 0)}</td>`
      : `<td class="num">—</td>`;
    return `<tr class="clickable" data-company="${esc(company.company_key)}">
      <td class="link">${esc(company.name)}</td>
      <td class="num score">${fmt(s.total)}</td>
      <td class="center">${gradeBadge(s.grade, true)}</td>
      ${dimCell("风险")}${dimCell("待遇")}${dimCell("压力")}${dimCell("环境")}${dimCell("福利")}
      <td>${laborMini(s.is_labor_dispatch, s.labor_dispatch_reason)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="9" class="empty">暂无公司数据</td></tr>`;

  const maxFit = fitted.length ? fitted[0].fit.total : 1;
  const rail = fitted.slice(0, 5).map((job, index) =>
    rankRow(job.title, fmt(job.fit.total), Math.min(1, job.fit.total / (maxFit || 1)),
            { badge: index + 1, labelWidth: 120, href: { kind: "job", id: job.id } })).join("")
    || `<div class="empty">需要一份已确认简历<br><span class="chart-note">在「简历」页生成定向版本</span></div>`;

  pageEl().innerHTML = `
    <div class="grid grid-4">
      ${kpi(sorted.length, "公司")}
      ${kpi((data.jobs || []).length, "岗位")}
      ${kpi(scored.length, "已打分公司")}
      ${kpi(negatives, "负面证据")}
    </div>

    <div class="grid grid-21 section">
      <div class="card">
        <div class="card-head">
          ${cardTitle("公司评分", "building", true)}
          <div class="card-sub">${icon("filter")}最近一次</div>
        </div>
        <table>
          <thead><tr>
            <th>公司</th><th class="num">总分</th><th class="center">等级</th>
            <th class="num">风险</th><th class="num">待遇</th><th class="num">压力</th>
            <th class="num">环境</th><th class="num">福利</th><th class="center">派遣</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        ${pager(sorted.length, Math.min(20, sorted.length))}
      </div>

      <div class="card">
        <div class="card-head">
          ${cardTitle("适配度 TOP", "star", true)}
          <div class="card-sub">${fitted.length} 个</div>
        </div>
        ${rail}
        <div style="border-top:1px solid var(--line-soft);margin-top:6px;padding-top:12px">
          <span class="link">共 ${scored.length} 家已打分 ${icon("chevron")}</span>
        </div>
      </div>
    </div>`;
  bindNav();
}

// ---------------------------------------------------------------- 公司列表
async function pageCompanies() {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const data = state.data || await call("data");
  if (!data) { pageEl().innerHTML = `<div class="empty">取数失败</div>`; return; }
  state.data = data;

  const sorted = [...(data.companies || [])].sort((a, b) => {
    const sa = a.score && a.score.total != null ? a.score.total : -1;
    const sb = b.score && b.score.total != null ? b.score.total : -1;
    return sb - sa;
  });

  const rows = sorted.map((company) => {
    const s = company.score || {};
    const dims = s.dimensions || {};
    const dimCell = (name) => s.total != null
      ? `<td class="num link" data-company="${esc(company.company_key)}" data-series="${esc(name)}" title="看 ${esc(name)} 趋势">${fmt(dims[name], 0)}</td>`
      : `<td class="num">—</td>`;
    return `<tr class="clickable" data-company="${esc(company.company_key)}">
      <td class="link">${esc(company.name)}</td>
      <td class="num score">${fmt(s.total)}</td>
      <td class="center">${gradeBadge(s.grade, true)}</td>
      ${dimCell("风险")}${dimCell("待遇")}${dimCell("压力")}${dimCell("环境")}${dimCell("福利")}
      <td>${laborMini(s.is_labor_dispatch, s.labor_dispatch_reason)}</td>
      <td class="num">${company.job_count ?? "—"}</td>
      <td class="num">${company.evidence ? company.evidence.total : 0}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="11" class="empty">暂无公司</td></tr>`;

  pageEl().innerHTML = `
    <div class="page-head"><div class="page-title">公司</div>
      <div class="page-sub">${sorted.length} 家 · 点维度数值看该字段趋势</div></div>
    <div class="card">
      <div class="card-head">${cardTitle("公司列表", "building", true)}
        <div class="card-sub">${icon("filter")}按总分排序</div></div>
      <table>
        <thead><tr>
          <th>公司</th><th class="num">总分</th><th class="center">等级</th>
          <th class="num">风险</th><th class="num">待遇</th><th class="num">压力</th>
          <th class="num">环境</th><th class="num">福利</th><th class="center">派遣</th>
          <th class="num">岗位</th><th class="num">证据</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${pager(sorted.length, sorted.length)}
    </div>`;
  bindNav();
}

// ---------------------------------------------------------------- 公司详情
async function pageCompanyDetail(key, params) {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const detail = await call("company", { company_key: key });
  if (!detail) { pageEl().innerHTML = `<div class="empty">取数失败</div>`; return; }

  const score = detail.score || {};
  const basic = detail.basic || {};
  const dispatch = detail.labor_dispatch || {};
  const dims = score.dimensions || [];
  const field = params.series;
  crumb("公司", detail.name);

  let seriesCard = "";
  if (field) {
    const series = await call("series", { company_key: key, field });
    const chips = [...dims.map((d) => ({ name: d.name, key: d.name })), { name: "总分", key: "total" }]
      .map((c) => `<button class="chip ${c.key === field ? "active" : ""}"
        data-series="${esc(c.key)}" data-series-company="${esc(key)}">${esc(c.name)}</button>`).join("");
    seriesCard = `<div class="card section">
      <div class="card-head">${cardTitle(field + " 历史趋势", "clock", true)}
        <div class="chips">${chips}</div></div>
      ${lineSVG(series ? series.points : [])}
      <div class="chart-note left">数据来自历次流水线运行，跑得越多越有参考价值</div>
    </div>`;
  }

  const negative = detail.risk?.evidence_negative || 0;
  const meta = [basic.industry, basic.reg_location, basic.staff_num].filter(Boolean);

  const jobItems = (detail.jobs || []).slice(0, 5).map((job) => `
    <div class="rank-row" style="cursor:pointer" data-job="${esc(job.job_id)}">
      <span class="rank-label" style="width:auto;flex:1;display:flex;flex-direction:column;line-height:1.3">
        <span>${esc(job.title)}</span>
        <em class="chart-note" style="font-style:normal">${esc(job.city || "")}${job.experience ? " · " + esc(job.experience) : ""}</em>
      </span>
      <span class="tag">${esc(job.salary || "—")}</span>
    </div>`).join("") || `<div class="empty">无在招岗位</div>`;

  const reviewItems = Object.entries(detail.reviews || {}).flatMap(([source, items]) =>
    items.slice(0, 6).map((r) => ({ source, ...r }))).slice(0, 6).map((r) => {
      const neutral = r.sentiment == null;
      const dot = neutral ? "dot-neu" : (r.sentiment < 0 ? "dot-neg" : "dot-pos");
      return `<div class="review">
        <span class="dot ${dot}"></span>
        <div class="review-body">
          ${r.url
            ? `<span class="link review-title" data-url="${esc(r.url)}">${esc(r.title || "(无标题)")}</span>`
            : `<span class="review-title">${esc(r.title || "(无标题)")}</span>`}
          ${r.snippet ? `<div class="review-snippet">${esc(String(r.snippet).slice(0, 120))}</div>` : ""}
        </div>
        <div class="review-side">${esc(r.source)}<br>${esc(String(r.published_at || "").slice(0, 10))}</div>
      </div>`;
    }).join("") || `<div class="empty">暂无评价（背调未跑或平台未登录）</div>`;

  const riskItems = Object.keys(detail.risk?.counts || {}).length
    ? Object.entries(detail.risk.counts).map(([name, count]) => `
        <div class="rank-row"><span class="rank-label" style="width:auto;flex:1">${esc(name)}</span>
          <span class="rank-num" style="width:auto;color:var(--text)">${esc(count)}</span></div>`).join("")
    : `<div class="empty">无风险计数</div>`;

  pageEl().innerHTML = `
    <div class="detail-head">
      <div class="detail-logo">${esc((detail.name || "?").slice(0, 1))}</div>
      <div class="detail-name">
        <h1>${esc(detail.name)}</h1>
        <div class="meta">
          ${meta.length ? meta.map((m) => `<span>${esc(m)}</span>`).join("<span>·</span>")
                        : `<span>工商信息未入库</span>`}
        </div>
      </div>
      <div class="detail-score">
        <span class="big">${score.total != null ? fmt(score.total, 1) : "—"}</span>
        <span class="of">/100</span>
      </div>
      ${score.grade ? `<div class="grade-box g-${esc(score.grade)}">${esc(score.grade)}</div>` : ""}
      ${laborPill(dispatch.is_labor_dispatch, dispatch.reason)}
      <a class="link" href="#/companies" style="margin-left:4px">← 列表</a>
    </div>

    <div class="grid grid-21">
      <div class="card">
        <div class="card-head">${cardTitle("公司评分", "building", true)}
          <div class="card-sub">五维 · 不叠加</div></div>
        <div class="radar-wrap">${radarSVG(dims)}</div>
        ${score.verdict ? `<div class="chart-note left" style="text-align:center">${esc(score.verdict)}</div>` : ""}
        ${(score.advice || []).length
          ? `<div style="margin-top:10px;text-align:center">${score.advice.map((a) => `<span class="tag tag-cyan">${esc(a)}</span>`).join("")}</div>`
          : ""}
      </div>

      <div style="display:flex;flex-direction:column;gap:18px;min-width:0">
        <div class="card">
          <div class="card-head">${cardTitle("工商信息", "file", true)}
            <div class="card-sub">${basic.raw_available ? "天眼查" : "未入库"}</div></div>
          <dl class="kv">
            <dt>注册资本</dt><dd>${esc(basic.reg_capital || "—")}</dd>
            <dt>成立时间</dt><dd>${esc(basic.estiblish_time || "—")}</dd>
            <dt>法定代表人</dt><dd>${esc(basic.legal_person || "—")}</dd>
            <dt>人员规模</dt><dd>${esc(basic.staff_num || "—")}</dd>
            <dt>所属行业</dt><dd>${esc(basic.industry || "—")}</dd>
            <dt>注册地址</dt><dd>${esc(basic.reg_location || "—")}</dd>
            <dt>信用代码</dt><dd>${esc(basic.credit_code || "—")}</dd>
          </dl>
          ${!basic.raw_available ? `<div class="chart-note left">天眼查原始数据未入库，以上为空属正常</div>` : ""}
        </div>
        <div class="card">
          <div class="card-head">${cardTitle("在招岗位", "briefcase", true)}
            <div class="card-sub">${(detail.jobs || []).length} 个</div></div>
          ${jobItems}
        </div>
      </div>
    </div>

    <div class="grid grid-2 section">
      <div class="card">
        <div class="card-head">${cardTitle("维度明细", "layers", true)}
          <div class="card-sub">点名称看趋势</div></div>
        ${dims.map((dim) => `
          <div class="dim-row" style="cursor:pointer" data-company="${esc(key)}" data-series="${esc(dim.name)}"
               title="${esc(dim.reason || "")}">
            <span class="dim-name link">${esc(dim.name)}</span>
            <div class="dim-bar"><div class="dim-fill" style="width:${Math.min(100, dim.score)}%"></div></div>
            <span class="dim-val">${fmt(dim.score, 0)}</span>
          </div>`).join("") || `<div class="empty">暂无维度</div>`}
      </div>
      <div class="card">
        <div class="card-head">${cardTitle("风险", "alert", true)}
          <div class="card-sub">负面证据 ${negative}</div></div>
        ${riskItems}
      </div>
    </div>

    <div class="card section">
      <div class="card-head">${cardTitle("评价", "chat", true)}
        <div class="card-sub">${Object.values(detail.reviews || {}).reduce((n, arr) => n + arr.length, 0)} 条</div></div>
      ${reviewItems}
    </div>
    ${seriesCard}`;
  bindNav();
}

// ---------------------------------------------------------------- 岗位
async function pageJobs() {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const [filters, data] = await Promise.all([
    state.filters ? Promise.resolve(state.filters) : call("filters"),
    state.data ? Promise.resolve(state.data) : call("data"),
  ]);
  if (filters) state.filters = filters;
  if (data) state.data = data;
  if (!filters || !data) { pageEl().innerHTML = `<div class="empty">取数失败</div>`; return; }

  const selects = filters.fields.map((f) => `
    <div class="field" style="flex:1;min-width:132px">
      <select data-filter="${esc(f.field)}">
        <option value="">${esc(f.label)}：不限</option>
        ${f.options.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("")}
      </select>
    </div>`).join("");

  const jobs = data.jobs || [];
  const rows = jobs.map((job) => `
    <tr class="clickable" data-job="${esc(job.id)}">
      <td><span class="link">${esc(job.title)}</span></td>
      <td style="color:var(--text-dim)">${esc(job.company || "—")}</td>
      <td class="num">${esc(job.salary || "—")}</td>
      <td style="color:var(--text-dim)">${esc(job.city || "—")}</td>
      <td class="num">${job.fit ? fmt(job.fit.total) : "—"}</td>
      <td class="center">${job.fit ? gradeBadge(job.fit.grade, true) : "—"}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="empty">暂无岗位</td></tr>`;

  pageEl().innerHTML = `
    <div class="card">
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center">
        <div class="field" style="flex:2;min-width:200px">
          <input type="text" id="f-query" placeholder="搜索关键词，如 Python、数据分析">
        </div>
        <div class="field" style="flex:1;min-width:110px">
          <input type="text" id="f-city" placeholder="城市">
        </div>
        ${selects}
        <div class="field" style="width:94px">
          <label>页数</label>
          <input type="number" id="f-pages" value="1" min="1" max="10">
        </div>
        <div class="field" style="width:94px">
          <label>公司数</label>
          <input type="number" id="f-limit" value="10" min="1" max="50">
        </div>
        <button class="btn" id="btn-run">${icon("search")}开始采集</button>
      </div>
      <div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:14px">
        <span class="card-sub">背调平台</span>
        <div class="checkbox-row" id="f-platforms"></div>
        <span class="card-sub">开关</span>
        <div class="checkbox-row" id="f-toggles"></div>
      </div>
      <div style="display:flex;gap:9px;margin-top:14px">
        <button class="btn btn-ghost btn-sm" id="btn-nocrawl">只重算（不采集）</button>
        <button class="btn btn-danger btn-sm" id="btn-stop" disabled>停止</button>
      </div>
    </div>

    <div class="card section">
      <div class="card-head">${cardTitle("岗位列表", "briefcase", true)}
        <div class="card-sub">${icon("filter")}共 ${jobs.length} 条</div></div>
      <table>
        <thead><tr>
          <th>岗位</th><th>公司</th><th class="num">薪资</th><th>城市</th>
          <th class="num">适配度</th><th class="center">等级</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
      ${pager(jobs.length, jobs.length)}
    </div>`;

  const platformsBox = $("#f-platforms");
  const togglesBox = $("#f-toggles");
  (filters.toggles || []).forEach((toggle) => {
    if (toggle.field === "platforms") {
      toggle.options.forEach((p, i) => platformsBox.insertAdjacentHTML("beforeend",
        `<label><input type="checkbox" data-platform="${esc(p)}" ${i < 4 ? "checked" : ""}> ${esc(p)}</label>`));
    } else {
      togglesBox.insertAdjacentHTML("beforeend",
        `<label><input type="checkbox" data-toggle="${esc(toggle.field)}" checked> ${esc(toggle.label)}</label>`);
    }
  });

  let stream = null;
  const runBtn = $("#btn-run"), stopBtn = $("#btn-stop");

  async function start(noCrawl) {
    const query = $("#f-query").value.trim();
    if (!query && !noCrawl) { chatLog("err", "校验", "请填关键词"); openDrawer(); return; }
    const args = {
      query,
      city: $("#f-city").value.trim(),
      pages: $("#f-pages").value,
      limit: $("#f-limit") ? $("#f-limit").value : 10,
      platforms: $$("input[data-platform]:checked").map((n) => n.dataset.platform).join(","),
      no_crawl: !!noCrawl,
    };
    $$("input[data-toggle]").forEach((node) => {
      if (!node.checked) args["no_" + node.dataset.toggle.replace("enable_", "")] = true;
    });
    runBtn.disabled = true;
    stopBtn.disabled = false;
    stream = await streamRun(args, async () => {
      runBtn.disabled = false;
      stopBtn.disabled = true;
      state.data = null;
      const fresh = await call("data");
      if (fresh) state.data = fresh;
      router();
    });
  }

  runBtn.addEventListener("click", () => start(false));
  $("#btn-nocrawl").addEventListener("click", () => start(true));
  stopBtn.addEventListener("click", () => {
    if (stream) window.api.cancel(stream);
    runBtn.disabled = false;
    stopBtn.disabled = true;
    chatLog("step", "流水线", "已请求停止");
  });
  bindNav();
}

// ---------------------------------------------------------------- 岗位详情
async function pageJobDetail(id) {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const job = await call("job", { job_id: id });
  if (!job) { pageEl().innerHTML = `<div class="empty">没有这个岗位</div>`; return; }
  crumb("岗位", job.title);

  const company = job.company || {};
  const fit = job.fit || {};
  const fitDims = fit.dimensions || {};
  const [fitTone] = fit.total != null ? toneOf(fit.total) : ["tone-good"];

  pageEl().innerHTML = `
    <div class="page-head" style="align-items:flex-start">
      <div style="flex:1;min-width:0">
        <div class="page-title" style="font-size:26px">${esc(job.title)}</div>
        <div class="chips" style="margin-top:12px">
          <span class="pill">${icon("briefcase")}${esc(job.salary || "薪资面议")}</span>
          ${job.city ? `<span class="pill">${icon("building")}${esc(job.city)}${job.district ? " · " + esc(job.district) : ""}</span>` : ""}
          ${job.experience ? `<span class="pill">${esc(job.experience)}</span>` : ""}
          ${job.degree ? `<span class="pill">${esc(job.degree)}</span>` : ""}
        </div>
      </div>
      ${fit.total != null ? `<div style="display:flex;align-items:center;gap:12px">
        <span class="card-sub" style="font-size:13px">适配度</span>
        <span class="detail-score" style="margin:0"><span class="big ${fitTone}">${fmt(fit.total, 1)}</span></span>
        ${fit.grade ? `<div class="grade-box g-${esc(fit.grade)}">${esc(fit.grade)}</div>` : ""}
      </div>` : ""}
      <a class="link" href="#/jobs" style="align-self:center">← 列表</a>
    </div>

    <div class="grid grid-21">
      <div class="card">
        <div class="card-head">${cardTitle("岗位信息", "briefcase", true)}</div>
        <div class="spec-rows">
          ${specRow("薪资范围", esc(job.salary || "—"))}
          ${specRow("经验要求", esc(job.experience || "—"))}
          ${specRow("学历要求", esc(job.degree || "—"))}
          ${specRow("所属行业", esc(job.industry || "—"))}
          ${specRow("岗位来源", `${icon("external")} ${esc(job.source?.name || "—")}`)}
        </div>
        ${(job.skills || []).length ? `<div style="margin-top:16px">
          <div class="spec-label" style="margin-bottom:8px">技能要求</div>
          ${job.skills.map((s) => `<span class="tag-outline">${esc(s)}</span>`).join("")}
        </div>` : ""}
        ${(job.welfare || []).length ? `<div style="margin-top:16px">
          <div class="spec-label" style="margin-bottom:8px">福利</div>
          ${job.welfare.map((s) => `<span class="tag-outline">${esc(s)}</span>`).join("")}
        </div>` : ""}
        <div class="prose" style="margin-top:18px">${esc(job.description || "（未采集到 JD 正文）")}</div>
      </div>

      <div style="display:flex;flex-direction:column;gap:18px;min-width:0">
        <div class="card">
          <div class="card-head">${cardTitle("招聘公司", "building", true)}</div>
          ${company.name ? `
            <div style="display:flex;align-items:center;gap:12px">
              <div class="detail-logo" style="width:44px;height:44px;border-radius:11px;font-size:19px">${esc(company.name.slice(0, 1))}</div>
              <div style="flex:1;min-width:0">
                <div class="link" style="font-size:14px;font-weight:600" data-company="${esc(company.company_key || "")}">${esc(company.name)}</div>
                <div class="chart-note">${esc(company.legal_name || "点击查看背调详情")}</div>
              </div>
              ${company.score && company.score.total != null ? `<div style="text-align:right">
                <div class="chart-note">公司评分</div>
                <div style="display:flex;align-items:center;gap:8px">
                  <span class="score" style="color:var(--cyan);font-size:16px">${fmt(company.score.total, 1)}</span>
                  ${company.score.grade ? gradeBadge(company.score.grade, true) : ""}
                </div>
              </div>` : ""}
            </div>
            ${company.score ? `<div style="margin-top:12px">${laborPill(company.score.is_labor_dispatch, "")}</div>` : ""}`
            : `<div class="empty">无公司信息</div>`}
        </div>

        <div class="card">
          <div class="card-head">${cardTitle("信息来源", "external", true)}</div>
          <div class="spec-rows">
            ${specRow("来源", esc(job.source?.name || "—"))}
            ${specRow("链接", job.source?.url
              ? `<span class="link" data-url="${esc(job.source.url)}">${icon("external")} ${esc(job.source.url.replace(/^https?:\/\//, "").slice(0, 30))}…</span>`
              : "—")}
          </div>
          <div style="display:flex;gap:9px;margin-top:14px;flex-wrap:wrap">
            ${job.source?.url ? `<button class="btn btn-sm" id="btn-open-source">${icon("external")}打开原帖</button>` : ""}
            <button class="btn btn-ghost btn-sm" id="btn-tailor">按此岗位改简历</button>
          </div>
        </div>

        ${Object.keys(fitDims).length ? `<div class="card">
          <div class="card-head">${cardTitle("适配度明细", "layers", true)}
            <div class="card-sub">${fit.grade || ""}</div></div>
          ${Object.entries(fitDims).map(([name, value]) => metricRow(name, value)).join("")}
          ${(fit.advice || []).length
            ? `<div style="margin-top:12px">${fit.advice.map((a) => `<span class="tag tag-cyan">${esc(a)}</span>`).join("")}</div>`
            : ""}
        </div>` : ""}
      </div>
    </div>`;

  bindNav();
  const openBtn = $("#btn-open-source");
  if (openBtn) openBtn.addEventListener("click", () => window.api.openExternal(job.source.url));
  $("#btn-tailor").addEventListener("click", () => go(`#/resume?job=${encodeURIComponent(id)}`));
}

// ---------------------------------------------------------------- 技能词云
/* 估算文字像素宽度：中文按 1em，西文按 0.56em */
function estimateWidth(text, size) {
  let units = 0;
  for (const ch of String(text)) {
    units += /[\u3000-\u9fff\uff00-\uffef]/.test(ch) ? 1.02 : 0.64;
  }
  return units * size;
}

/* 螺旋布局：从中心往外找不与已放置词冲突的位置，得到真正的"云"而不是字墙 */
function layoutCloud(items, W, H) {
  const placed = [];
  const cx = W / 2, cy = H / 2;
  const maxR = Math.hypot(W, H) / 2;
  for (const item of items) {
    const w = estimateWidth(item.name, item.size);
    const h = item.size * 1.05;
    let spot = null;
    for (let r = 0; r < maxR && !spot; r += 5) {
      const steps = Math.max(10, Math.round(r / 3));
      for (let s = 0; s < steps; s++) {
        // 角度随半径递增，形成螺旋而非同心圆
        const angle = (s / steps) * Math.PI * 2 + r * 0.18;
        const x = cx + Math.cos(angle) * r;
        const y = cy + Math.sin(angle) * r * 0.78;   // 压扁成横向椭圆
        const left = x, top = y;                     // 以中心点定位，配合 translate(-50%,-50%)
        const halfW = w / 2, halfH = h / 2;
        if (left - halfW < 2 || top - halfH < 2 ||
            left + halfW > W - 2 || top + halfH > H - 2) continue;
        const hit = placed.some((b) =>
          Math.abs(left - b.x) < halfW + b.halfW + 12 &&
          Math.abs(top - b.y) < halfH + b.halfH + 9);
        if (!hit) { spot = { x: left, y: top }; break; }
      }
    }
    if (!spot) continue;
    placed.push({ ...spot, halfW: w / 2, halfH: h / 2 });
    item.x = (spot.x / W) * 100;
    item.y = (spot.y / H) * 100;
  }
  return items.filter((item) => item.x !== undefined);
}

async function pageSkills(params) {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const cloud = await call("cloud");
  if (!cloud) { pageEl().innerHTML = `<div class="empty">取数失败</div>`; return; }

  const all = cloud.skills || [];
  const kind = params.kind || state.cloudKind || "all";
  state.cloudKind = kind;
  const filtered = kind === "all" ? all : all.filter((s) => (s.kind || "tech") === kind);
  // 只取前 56 个：词太多会挤成一堵字墙，失去"云"的呼吸感
  const items = filtered.slice(0, 56);
  const max = Math.max(...items.map((s) => s.count), 1);
  const min = Math.min(...items.map((s) => s.count), 1);
  const total = filtered.reduce((n, s) => n + s.count, 0);
  const grand = all.reduce((n, s) => n + s.count, 0) || 1;

  // 先算好每个词的视觉参数，实际排布要等容器有了宽度再做（见 paintCloud）
  const prepared = items.map((item) => {
    const norm = max === min ? 1 : (item.count - min) / (max - min);
    const ratio = item.count / max;
    return {
      name: item.name,
      count: item.count,
      size: 11 + Math.pow(norm, 1.5) * 46,
      far: ratio < 0.16,
      opacity: ratio < 0.16 ? 0.45 : Math.min(1, 0.86 + ratio * 0.14),
    };
  });

  const rail = items.slice(0, 10).map((item) =>
    rankRow(item.name, Math.round((item.count / grand) * 100) + "%", item.count / max,
            { labelWidth: 108 })).join("") || `<div class="empty">暂无</div>`;

  pageEl().innerHTML = `
    <div class="grid grid-rail">
      <div class="card">
        <div class="card-head">${cardTitle("技能词云", "cloud", true)}
          <button class="chip" style="cursor:default">${icon("grid")}按频次</button></div>
        <div class="cloud" id="cloud-box"></div>
        <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--line-soft);padding-top:14px;gap:12px;flex-wrap:wrap">
          <div class="chips">
            <button class="chip ${kind === "all" ? "active" : ""}" data-kind="all">${icon("layers")}全部 ${all.length}</button>
            <button class="chip ${kind === "tech" ? "active" : ""}" data-kind="tech">${icon("grid")}技术栈</button>
            <button class="chip ${kind === "tag" ? "active" : ""}" data-kind="tag">${icon("star")}其他标签</button>
          </div>
          <span class="card-sub">共 ${total} 次提及</span>
        </div>
      </div>

      <div class="card">
        <div class="card-head">${cardTitle("TOP 10", "layers", true)}
          <div class="card-sub">${items.length} 个词</div></div>
        ${rail}
        <div style="border-top:1px solid var(--line-soft);padding-top:12px;margin-top:6px">
          <span class="card-sub">${icon("info")}百分比 = 该词岗位数 / 全部提及</span>
        </div>
      </div>
    </div>`;

  $$("[data-kind]").forEach((chip) => chip.addEventListener("click", () => {
    go("#/skills?kind=" + chip.dataset.kind);
  }));

  // 容器有了真实尺寸之后才排布，否则按错宽度算出来的位置会互相重叠
  const box = $("#cloud-box");
  const paint = () => {
    const W = box.clientWidth || 900;
    const H = box.clientHeight || 470;
    const laid = layoutCloud(prepared.map((p) => ({ ...p })), W, H);
    box.innerHTML = laid.map((item) => `
      <span class="${item.far ? "far" : ""}"
        style="left:${item.x.toFixed(2)}%;top:${item.y.toFixed(2)}%;font-size:${item.size.toFixed(0)}px;opacity:${item.opacity.toFixed(2)}"
        title="${esc(item.name)} · 出现在 ${item.count} 个岗位">${esc(item.name)}</span>`).join("")
      || `<div class="empty">没有符合条件的词</div>`;
  };
  paint();
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (document.body.contains(box)) paint();
    }, 180);
  });
}

// ---------------------------------------------------------------- 简历
async function pageResume(params) {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const payload = await call("resume");
  const resume = payload && payload.ok ? payload.resume : null;
  const questions = (payload && payload.questions) || [];
  const targetJob = params.job || "";

  const sample = `{
  "name": "张三",
  "summary": "3 年后端开发，熟悉高并发订单系统",
  "skills": ["Python", "MySQL", "Redis"],
  "experience": [
    {"title": "后端工程师", "org": "某公司",
     "highlights": ["日订单百万级", "接口 P99 80ms"]}
  ]
}`;

  pageEl().innerHTML = `
    <div class="page-head"><div class="page-title">简历</div>
      <div class="page-sub">母版 → 按岗位定向；定向版本未经确认不会生效</div></div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head">${cardTitle("母版简历", "file", true)}
          ${resume ? `<span class="pill ${resume.confirmed ? "pill-ok" : "pill-warn"}">#${resume.id} ${resume.confirmed ? "已确认" : "草稿"}</span>` : ""}</div>
        <div class="field">
          <label>JSON：name / summary / skills[] / experience[] / projects[]</label>
          <textarea id="resume-content" style="min-height:320px;font-family:Consolas,monospace;font-size:12px">${esc(resume ? JSON.stringify(resume.content, null, 2) : sample)}</textarea>
        </div>
        <div style="display:flex;gap:10px;align-items:center;margin-top:12px">
          <button class="btn btn-sm" id="btn-save-resume">${icon("check")}保存母版</button>
          <span class="chart-note" id="save-hint"></span>
        </div>
      </div>

      <div class="card">
        <div class="card-head">${cardTitle("定向到岗位", "briefcase", true)}</div>
        <div class="field">
          <label>岗位 ID（岗位详情页可一键带入）</label>
          <input type="text" id="resume-job" value="${esc(targetJob)}" placeholder="job_id">
        </div>
        <div style="display:flex;gap:9px;margin-top:12px">
          <button class="btn btn-sm" id="btn-tailor-run">生成定向版本</button>
        </div>
        ${questions.length ? `<div class="chart-note left" style="margin-top:12px">
          ${icon("info")} 生成时会先问你 ${questions.length} 个问题（在底部对话里回答）</div>` : ""}
        <div id="tailor-result" style="margin-top:14px"></div>
      </div>
    </div>`;

  async function readResume() {
    try { return JSON.parse($("#resume-content").value); }
    catch (exc) { chatLog("err", "校验", "简历 JSON 不合法：" + exc.message); openDrawer(); return null; }
  }

  $("#btn-save-resume").addEventListener("click", async () => {
    const content = await readResume();
    if (!content) return;
    const tmp = await window.api.writeTemp("resume_master.json", JSON.stringify(content, null, 2));
    $("#save-hint").textContent = "已缓存，生成时会用它";
    void tmp;
  });

  $("#btn-tailor-run").addEventListener("click", async () => {
    const jobId = $("#resume-job").value.trim();
    if (!jobId) { chatLog("err", "校验", "请填岗位 ID"); openDrawer(); return; }
    const content = await readResume();
    if (!content) return;
    openDrawer();
    chatQuestions(questions, async (answers) => {
      const merged = await window.api.writeTemp("resume_with_answers.json",
        JSON.stringify({ content, answers }, null, 2));
      await streamRun({
        no_crawl: true, no_backduty: true, no_score: true, no_fit: true,
        with_resume: true, job_id: jobId, resume: merged.path, limit: 1,
      }, async () => {
        const fresh = await call("resume");
        const box = $("#tailor-result");
        if (fresh && fresh.ok && fresh.resume) {
          box.innerHTML = `<div class="card" style="background:var(--bg-input)">
            <div class="card-head">${cardTitle("版本 #" + fresh.resume.id, "file")}
              <span class="pill ${fresh.resume.confirmed ? "pill-ok" : "pill-warn"}">${fresh.resume.confirmed ? "已确认" : "草稿"}</span></div>
            <pre style="font-size:12px;white-space:pre-wrap;max-height:320px;overflow-y:auto">${esc(JSON.stringify(fresh.resume.content, null, 2))}</pre>
          </div>`;
        }
      });
    });
    chatLog("step", "简历", "请在下方回答问题（可留空直接提交）");
  });
}

// ---------------------------------------------------------------- 设置
async function pageSettings() {
  pageEl().innerHTML = `<div class="loading">加载中…</div>`;
  const [status, models] = await Promise.all([call("status"), call("models")]);
  if (!status) { pageEl().innerHTML = `<div class="empty">自检失败</div>`; return; }

  const db = status.db || {};
  const login = status.login || {};

  pageEl().innerHTML = `
    <div class="grid grid-2">
      <div class="card">
        <div class="card-head">${cardTitle("数据库", "layers", true)}
          ${db.ok ? `<span class="pill pill-ok">${icon("check")}正常</span>` : `<span class="pill pill-bad">异常</span>`}</div>
        <dl class="kv">
          <dt>岗位</dt><dd>${db.jobs ?? "—"}</dd>
          <dt>公司</dt><dd>${db.companies ?? "—"}</dd>
          <dt>打分记录</dt><dd>${db.company_score ?? "—"}</dd>
          <dt>背调证据</dt><dd>${db.backduty_evidence ?? "—"}</dd>
          <dt>天眼查原文</dt><dd>${db.backduty_raw ?? "—"}</dd>
          <dt>适配度</dt><dd>${db.job_fit ?? "—"}</dd>
          <dt>简历版本</dt><dd>${db.resume_version ?? "—"}</dd>
          <dt>报错日志</dt><dd>${db.agent_error ?? "—"}</dd>
        </dl>
        <div style="display:flex;gap:9px;margin-top:16px">
          <button class="btn btn-sm" id="btn-init">${icon("refresh")}初始化 / 建表</button>
          <button class="btn btn-ghost btn-sm" id="btn-refresh">刷新</button>
        </div>
      </div>

      <div class="card">
        <div class="card-head">${cardTitle("模型", "layers", true)}
          <div class="card-sub">只显示有无密钥</div></div>
        ${(models?.models || []).map((m) => `
          <div class="rank-row">
            <span class="rank-label" style="width:auto;flex:1">${esc(m.name)}
              <span class="chart-note">${esc(m.kind)}</span></span>
            ${m.enabled
              ? (m.has_key ? `<span class="pill pill-ok">可用</span>` : `<span class="pill pill-warn">缺密钥</span>`)
              : `<span class="pill pill-dim">停用</span>`}
          </div>
          ${m.note ? `<div class="chart-note left" style="margin:-2px 0 8px">${esc(m.note)}</div>` : ""}
        `).join("") || `<div class="empty">无模型</div>`}
      </div>
    </div>

    <div class="grid grid-2 section">
      <div class="card">
        <div class="card-head">${cardTitle("数据源", "briefcase", true)}</div>
        ${(status.sources || []).map((s) => `
          <div class="rank-row">
            <span class="rank-label" style="width:auto;flex:1">${esc(s.label)}
              <span class="chart-note">${esc(s.name)}</span></span>
            ${s.implemented ? `<span class="pill pill-ok">已接入</span>` : `<span class="pill pill-dim">预留</span>`}
          </div>`).join("")}
        <div class="chart-note left">预留插槽：实现 build_steps 即可接入新平台</div>
      </div>

      <div class="card">
        <div class="card-head">${cardTitle("背调 agent", "layers", true)}</div>
        ${(status.agents || []).map((a) => `
          <div class="rank-row">
            <span class="rank-label" style="width:auto;flex:1">${esc(a.name)}</span>
            <span class="pill pill-dim">${esc(a.kind)}</span>
          </div>`).join("")}
      </div>
    </div>

    <div class="card section">
      <div class="card-head">${cardTitle("平台登录", "check", true)}
        <div class="card-sub">会弹出真实浏览器窗口</div></div>
      <div class="checkbox-row" id="login-platforms">
        ${(status.platforms || []).map((p) =>
          `<label title="${esc(p.note || "")}"><input type="checkbox" data-login="${esc(p.key)}"> ${esc(p.label)}</label>`).join("")}
      </div>
      <div style="display:flex;gap:12px;align-items:center;margin-top:14px">
        <button class="btn btn-sm" id="btn-login">${icon("check")}登录所选</button>
        <span class="chart-note">登录态存 .state/login，背调自动带上</span>
      </div>
      <div style="margin-top:12px">
        ${Object.entries(login).length
          ? Object.entries(login).map(([platform, v]) => `
            <div class="rank-row"><span class="rank-label" style="width:auto;flex:1">${esc(platform)}</span>
              <span class="pill ${(v === "ok" || (v && v.status === "ok")) ? "pill-ok" : "pill-dim"}">
                ${esc(typeof v === "string" ? v : (v && v.status) || "未知")}</span></div>`).join("")
          : `<div class="chart-note left">还没有登录记录</div>`}
      </div>
    </div>`;

  $("#btn-init").addEventListener("click", async () => {
    chatLog("step", "初始化", "开始建表…");
    openDrawer();
    const result = await call("init");
    chatLog("step", "初始化", result ? "完成" : "失败");
    router();
  });
  $("#btn-refresh").addEventListener("click", router);
  $("#btn-login").addEventListener("click", async () => {
    const platforms = $$("input[data-login]:checked").map((n) => n.dataset.login);
    if (!platforms.length) { chatLog("err", "校验", "请选择平台"); openDrawer(); return; }
    openDrawer();
    chatLog("step", "登录", `将为 ${platforms.join("、")} 弹出浏览器`);
    await window.api.stream("login", { platforms: platforms.join(",") }, (event) => {
      if (event.type === "login") chatLog("step", "登录", `${event.platform}: ${event.message}`);
      else if (event.type === "step") chatLog("step", "登录", `${event.name} ${event.detail || ""}`);
      else if (event.type === "error") chatLog("err", "登录", event.message || "");
      else if (event.type === "__done__") { chatLog("step", "登录", "流程结束"); router(); }
    });
  });
}

// ---------------------------------------------------------------- 启动
(async function boot() {
  const [status, models] = await Promise.all([call("status"), call("models")]);
  const db = (status && status.db) || {};
  const pill = $("#db-status");
  pill.textContent = db.ok ? `已连接 · ${db.jobs} 岗位` : "数据库未连接";

  const list = (models && models.models) || [];
  const usable = list.filter((m) => m.enabled && m.has_key);
  const chatModel = usable.find((m) => m.kind === "chat");

  $("#topbar-right").innerHTML = `
    <span class="pill ${db.ok ? "pill-ok" : "pill-bad"}"><span class="dot"></span>${db.ok ? "已连接" : "未连接"}</span>
    <span class="pill">${icon("briefcase")}${db.jobs ?? 0}</span>
    <span class="pill">${icon("building")}${db.companies ?? 0}</span>
    <span class="pill ${chatModel ? "pill-cyan" : "pill-dim"}">${icon("layers")}模型 ${usable.length}</span>`;

  router();
})();
