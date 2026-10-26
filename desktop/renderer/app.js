/* 渲染进程：路由 + 页面 + 组件。只调 window.api，不碰 Node。
   视觉依据 docs/concepts/v2/01~04，结构说明见 Tree/desktop-redesign.md。 */
"use strict";

// ---------------------------------------------------------------- 基础
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
const pageEl = () => $("#page");

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const markMatch = (text, needle) => {
  const source = String(text ?? "");
  const query = String(needle ?? "").trim().toLowerCase();
  if (!query) return esc(source);
  const lower = source.toLowerCase();
  let at = lower.indexOf(query);
  if (at < 0) return esc(source);
  let out = "";
  let cursor = 0;
  while (at >= 0) {
    out += esc(source.slice(cursor, at)) + "<mark>" + esc(source.slice(at, at + query.length)) + "</mark>";
    cursor = at + query.length;
    at = lower.indexOf(query, cursor);
  }
  return out + esc(source.slice(cursor));
};
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

/* 薪资口径统一为月薪：时薪按 174h、日薪按 21.75 天、年薪按 12 个月折算 */
function salaryMonthly(raw) {
  const text = String(raw ?? "").replace(/\s+/g, "");
  if (!text || /面议/.test(text)) return null;
  const tokens = [...text.matchAll(/(\d+(?:\.\d+)?)([万千wWkK])?/g)];
  if (!tokens.length) return null;
  const globalUnit = /万|w/i.test(text) ? 10000 : /k|千/i.test(text) ? 1000 : 1;
  const amount = (match) => {
    const n = Number(match[1]);
    const suffix = match[2] || "";
    const unit = /万|w/i.test(suffix) ? 10000 : /k|千/i.test(suffix) ? 1000 : (suffix ? 1 : globalUnit);
    return n * unit;
  };
  let low = amount(tokens[0]);
  let high = tokens[1] ? amount(tokens[1]) : low;
  if (!Number.isFinite(low) || !Number.isFinite(high)) return null;
  if (high < low) [low, high] = [high, low];
  if (/\/时|每小时|时薪/.test(text)) { low *= 174; high *= 174; }
  else if (/\/天|每天|日薪/.test(text)) { low *= 21.75; high *= 21.75; }
  else if (/\/年|每年|年薪/.test(text)) { low /= 12; high /= 12; }
  return { low, high, mid: (low + high) / 2 };
}
const salaryK = (v) => {
  const k = v / 1000;
  return (k >= 100 ? Math.round(k) : Math.round(k * 10) / 10).toString().replace(/\.0$/, "") + "K";
};

function skeletonListBody() {
  const bar = (w, h = 10) => `<div class="skel" style="width:${w};height:${h}px"></div>`;
  return `<div class="card">
    <div class="card-head">${bar("120px", 12)}</div>
    <div class="list-toolbar">${bar("200px", 32)}${bar("110px", 32)}${bar("96px", 32)}${bar("96px", 32)}</div>
    <div class="skel-table">${Array.from({ length: 9 }, (_, i) => bar(`${96 - (i % 3) * 7}%`)).join("")}</div>
  </div>`;
}

function skeletonOverviewBody() {
  return `<div class="grid grid-4">${Array.from({ length: 4 }, () => `<div class="card skel-kpi"></div>`).join("")}</div>
    <div class="card skel-stage"></div>
    <div class="grid grid-21">${Array.from({ length: 2 }, () => `<div class="card skel-stage" style="height:180px"></div>`).join("")}</div>`;
}

function skeletonPage(kind = "list") {
  const bar = (w, h = 10) => `<div class="skel" style="width:${w};height:${h}px"></div>`;
  if (kind === "detail") {
    return `<div class="skeleton">
      <div class="skel-head">${bar("54px", 54)}<div class="skel-head-text">${bar("220px", 26)}${bar("320px", 10)}</div></div>
      <div class="grid grid-21 section">
        <div class="card">${bar("140px", 12)}<div class="skel skel-chart"></div></div>
        <div class="card">${bar("120px", 12)}<div class="skel-lines">${bar("100%")}${bar("92%")}${bar("100%")}${bar("84%")}</div></div>
      </div>
    </div>`;
  }
  if (kind === "overview") {
    return `<div class="skeleton">
      <div class="skel-head"><div class="skel-head-text">${bar("160px", 28)}${bar("360px", 10)}</div></div>
      ${skeletonOverviewBody()}
    </div>`;
  }
  return `<div class="skeleton">
    <div class="skel-head"><div class="skel-head-text">${bar("160px", 28)}${bar("340px", 10)}</div></div>
    ${skeletonListBody()}
  </div>`;
}

// 首屏骨架保留真实页头，异步取数时用户仍知道自己停在哪一页
function loadingPage(title, sub, body, actions = "") {
  return `<div class="page-head">
    <div><div class="page-title">${esc(title)}</div><div class="page-sub">${esc(sub)}</div></div>
    ${actions ? `<div class="page-actions">${actions}</div>` : ""}
  </div><div class="skeleton" aria-busy="true">${body}</div>`;
}

function skelLines(count, height = 10) {
  return `<div class="skel-lines">${Array.from({ length: count }, (_, i) =>
    `<div class="skel" style="width:${100 - (i % 3) * 8}%;height:${height}px"></div>`).join("")}</div>`;
}

const state = {
  data: null,
  filters: null,
  cloudKind: "all",
  cloud: null,
  resume: null,
  cfgAgent: "",
  status: null,
  models: null,
};

// ---------------------------------------------------------------- 本机存储守卫
const STORE_PROBE_KEY = "swarm.probe.v1";
const storeHealth = { failed: false, at: 0, error: "" };
let pendingBackupFocus = false;

function renderStorageAlert() {
  const node = $("#storage-alert");
  if (!node) return;
  node.hidden = !storeHealth.failed;
}

function markStoreFailed(error, { quiet = false } = {}) {
  const first = !storeHealth.failed;
  storeHealth.failed = true;
  storeHealth.at = Date.now();
  storeHealth.error = error?.name || "";
  renderStorageAlert();
  if (first && !quiet) toast("本机存储写入失败 · 改动可能无法保留", "warn");
}

function recoverStore() {
  if (!storeHealth.failed) return true;
  storeHealth.failed = false;
  storeHealth.error = "";
  const ok = flushLocalState();
  renderStorageAlert();
  if (ok) {
    const tip = $("#track-tip");
    if (tip) tip.textContent = "已恢复保存 · 仅存本机";
    toast("本机存储已恢复，改动已重新保存", "ok");
  }
  return ok;
}

function writeLocal(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
    if (storeHealth.failed) recoverStore();
    return true;
  } catch (error) {
    markStoreFailed(error);
    return false;
  }
}

function probeStorage() {
  try {
    localStorage.setItem(STORE_PROBE_KEY, "1");
    localStorage.removeItem(STORE_PROBE_KEY);
    return true;
  } catch {
    return false;
  }
}

function retryStorage() {
  if (!probeStorage()) {
    markStoreFailed(null, { quiet: true });
    toast("仍无法写入本机存储，请检查磁盘空间或权限", "warn");
    return;
  }
  if (storeHealth.failed) recoverStore();
  else toast("本机存储写入正常", "ok");
}

function initStorageGuard() {
  $("#storage-retry")?.addEventListener("click", retryStorage);
  $("#storage-backup")?.addEventListener("click", () => { pendingBackupFocus = true; });
  if (!probeStorage()) markStoreFailed(null, { quiet: true });
  else renderStorageAlert();
}

// ---------------------------------------------------------------- 本地关注清单
const WATCH_KEY = "swarm.watch.v1";
const watch = (() => {
  try {
    const saved = JSON.parse(localStorage.getItem(WATCH_KEY) || "{}");
    return {
      companies: new Set(saved.companies || []),
      jobs: new Set(saved.jobs || []),
    };
  } catch {
    return { companies: new Set(), jobs: new Set() };
  }
})();
const watchTotal = () => watch.companies.size + watch.jobs.size;
const watchSet = (kind) => (kind === "job" ? watch.jobs : watch.companies);

function saveWatch() {
  writeLocal(WATCH_KEY, {
    companies: [...watch.companies],
    jobs: [...watch.jobs],
  });
}

function toggleWatch(kind, id) {
  const set = watchSet(kind);
  if (!set || !id) return false;
  if (set.has(id)) set.delete(id); else set.add(id);
  saveWatch();
  return set.has(id);
}

function watchButton(kind, id, label, { large = false, shortcut = "" } = {}) {
  const on = watchSet(kind).has(id);
  const hint = shortcut ? `（${shortcut}）` : "";
  return `<button type="button" class="watch-btn${large ? " watch-lg" : ""}${on ? " on" : ""}"
    data-watch="${kind}" data-watch-id="${esc(id)}" data-watch-label="${esc(label)}"
    data-watch-shortcut="${esc(shortcut)}"
    aria-pressed="${on}" aria-label="${on ? "取消关注" : "关注"}${esc(label)}"
    title="${on ? "取消关注" : "关注"}${hint}">${icon("star")}${large ? `<span>${on ? "已关注" : "关注"}</span>` : ""}</button>`;
}

function syncWatchButton(btn, on) {
  btn.classList.toggle("on", on);
  btn.setAttribute("aria-pressed", String(on));
  btn.setAttribute("aria-label", (on ? "取消关注" : "关注") + (btn.dataset.watchLabel || ""));
  btn.title = `${on ? "取消关注" : "关注"}${btn.dataset.watchShortcut ? `（${btn.dataset.watchShortcut}）` : ""}`;
  const label = btn.querySelector("span");
  if (label) label.textContent = on ? "已关注" : "关注";
}

function syncWatchLinks() {
  const link = $("#watch-link");
  if (!link) return;
  link.innerHTML = `${icon("star")}关注 ${watchTotal()}`;
  link.title = `公司 ${watch.companies.size} 家 · 岗位 ${watch.jobs.size} 个`;
}

// ---------------------------------------------------------------- 对比清单
const COMPARE_KEY = "swarm.compare.v1";
function compareSelection() {
  try {
    const saved = JSON.parse(localStorage.getItem(COMPARE_KEY) || "null");
    return Array.isArray(saved)
      ? saved.filter((key) => typeof key === "string" && key.length <= 200).slice(0, 6)
      : null;
  } catch {
    return null;
  }
}
function saveCompareSelection(keys) {
  writeLocal(COMPARE_KEY, keys ? keys.slice(0, 6) : null);
}

// ---------------------------------------------------------------- 最近查看
const RECENT_KEY = "swarm.recent.v1";
const RECENT_MAX = 8;
function recentItems() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    if (!Array.isArray(saved)) return [];
    const seen = new Set();
    return saved.filter((entry) => {
      if (!entry || (entry.kind !== "company" && entry.kind !== "job")) return false;
      if (typeof entry.id !== "string" || !entry.id || entry.id.length > 200) return false;
      const key = entry.kind + ":" + entry.id;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, RECENT_MAX);
  } catch {
    return [];
  }
}
function rememberRecent(kind, id) {
  if ((kind !== "company" && kind !== "job") || !id) return;
  const list = recentItems().filter((entry) => !(entry.kind === kind && entry.id === id));
  list.unshift({ kind, id, at: new Date().toISOString() });
  writeLocal(RECENT_KEY, list.slice(0, RECENT_MAX));
}
function clearRecent() {
  writeLocal(RECENT_KEY, null);
}

// ---------------------------------------------------------------- 投递跟进（本地）
const TRACK_KEY = "swarm.track.v1";
const STAGES = [
  { id: "todo", label: "待投", icon: "clock" },
  { id: "applied", label: "已投", icon: "check" },
  { id: "interview", label: "面试", icon: "chat" },
  { id: "offer", label: "Offer", icon: "star" },
  { id: "accepted", label: "已接受", icon: "check" },
  { id: "rejected", label: "已拒", icon: "alert" },
];
const STAGE_IDS = new Set(STAGES.map((s) => s.id));
const TERMINAL_STAGES = new Set(["accepted", "rejected"]);
const isTerminalStage = (stage) => TERMINAL_STAGES.has(stage);
const stageShortcut = (key) => {
  const index = Number(key) - 1;
  return Number.isInteger(index) && index >= 0 && index < STAGES.length ? STAGES[index] : null;
};
const stageMeta = (id) => STAGES.find((s) => s.id === id) || null;
const INTERVIEW_ROUNDS = ["一面", "二面", "三面", "四面", "HR 面"];
const isInterviewRound = (value) => INTERVIEW_ROUNDS.includes(value);
const PREP_ITEMS = [
  "查公司业务与近期动态",
  "对照 JD 准备 3 个项目故事",
  "准备 2–3 个反问",
  "测试设备或确认路线证件",
  "打印简历或作品集",
];
const PREP_TOTAL = PREP_ITEMS.length;
const normalizePrep = (value) => Array.from({ length: PREP_TOTAL }, (_, index) => Array.isArray(value) && value[index] === true);

const track = (() => {
  try {
    const saved = JSON.parse(localStorage.getItem(TRACK_KEY) || "{}");
    const clean = {};
    Object.entries(saved || {}).forEach(([id, rec]) => {
      if (!rec || !STAGE_IDS.has(rec.stage)) return;
      const history = Array.isArray(rec.history)
        ? rec.history
          .filter((step) => step && STAGE_IDS.has(step.stage) && Number.isFinite(Date.parse(step.at)))
          .slice(-20)
          .map((step) => ({ stage: step.stage, at: new Date(step.at).toISOString() }))
        : [];
      const followed = Number.isFinite(Date.parse(rec.followed))
        ? new Date(rec.followed).toISOString() : "";
      const snoozeAt = Date.parse(rec.snoozedUntil);
      // 已过期的延后不再保留，避免下次导出还带着一条无效时间
      const snoozedUntil = Number.isFinite(snoozeAt) && snoozeAt > Date.now()
        ? new Date(snoozeAt).toISOString() : "";
      const interviewAt = Number.isFinite(Date.parse(rec.interviewAt))
        ? new Date(rec.interviewAt).toISOString() : "";
      const offerUntil = Number.isFinite(Date.parse(rec.offerUntil))
        ? new Date(rec.offerUntil).toISOString() : "";
      const prep = normalizePrep(rec.prep);
      clean[id] = {
        stage: rec.stage,
        at: String(rec.at || ""),
        note: String(rec.note || "").slice(0, 500),
        ...(isInterviewRound(rec.round) ? { round: rec.round } : {}),
        ...(prep.some(Boolean) ? { prep } : {}),
        ...(followed ? { followed } : {}),
        ...(snoozedUntil ? { snoozedUntil } : {}),
        ...(interviewAt ? { interviewAt } : {}),
        ...(offerUntil ? { offerUntil } : {}),
        ...(history.length ? { history } : {}),
      };
    });
    return clean;
  } catch {
    return {};
  }
})();

function saveTrack() {
  const saved = writeLocal(TRACK_KEY, track);
  syncNavDue();
  syncHudNext();
  scheduleSnoozeWake();
  scheduleInterviewWake();
  scheduleOfferWake();
  return saved;
}

// ---------------------------------------------------------------- 桌面提醒
// 窗口在前台时用应用内提示；失焦或最小化时交给主进程发系统通知。
const NOTIFY_KEY = "swarm.notify.v1";
let notifyPref = (() => {
  try {
    return JSON.parse(localStorage.getItem(NOTIFY_KEY) ?? "true") !== false;
  } catch {
    return true;
  }
})();
const notifySupported = () => typeof window.api?.notify === "function";

function saveNotifyPref() {
  return writeLocal(NOTIFY_KEY, notifyPref);
}

async function sendDesktopNotification(title, body, href = "") {
  if (!notifyPref || !notifySupported()) return false;
  try {
    const result = await window.api.notify({ title, body, href });
    return !!result?.ok;
  } catch {
    return false;
  }
}

function deliverTimedReminder(text, tone, { title, body, href = "" }) {
  const focused = document.visibilityState === "visible" && document.hasFocus();
  if (focused) {
    toast(text, tone);
    return;
  }
  if (!notifyPref || !notifySupported()) return;
  void sendDesktopNotification(title, body, href).then((ok) => {
    if (!ok) toast(text, tone);
  });
}

// 存储恢复后把内存里的关注与跟进补写回去，避免失败期间的改动只剩当前窗口
function flushLocalState() {
  const watchSaved = writeLocal(WATCH_KEY, {
    companies: [...watch.companies],
    jobs: [...watch.jobs],
  });
  const trackSaved = writeLocal(TRACK_KEY, track);
  return watchSaved && trackSaved;
}

const trackOf = (id) => track[id] || null;

function setTrackStage(id, stage) {
  if (!id || !STAGE_IDS.has(stage)) return false;
  const now = new Date().toISOString();
  const rec = track[id];
  if (!rec) {
    track[id] = { stage, at: now, followed: now, note: "", ...(stage === "interview" ? { round: INTERVIEW_ROUNDS[0] } : {}), history: [{ stage, at: now }] };
  } else {
    let history = Array.isArray(rec.history) ? rec.history.slice(-19) : [];
    if (rec.stage !== stage) {
      // 旧记录没有历史，先把当前阶段补成起点，时间线才完整
      if (!history.length) history = [{ stage: rec.stage, at: rec.at || now }];
      history = [...history, { stage, at: now }];
    }
    track[id] = {
      ...rec, stage, at: now, followed: now,
      ...(stage === "interview" && !isInterviewRound(rec.round) ? { round: INTERVIEW_ROUNDS[0] } : {}),
      ...(history.length ? { history } : {}),
    };
    delete track[id].snoozedUntil;
  }
  saveTrack();
  return true;
}

function setTrackNote(id, note) {
  if (!id) return false;
  const rec = track[id];
  if (rec) {
    if (rec.note === note) return !storeHealth.failed;
    // 备注是记录，不算一次跟进：只刷新更新时间，不改跟进计时
    if (!Number.isFinite(Date.parse(rec.followed))) rec.followed = rec.at || new Date().toISOString();
    rec.note = note;
    rec.at = new Date().toISOString();
  } else {
    const now = new Date().toISOString();
    track[id] = { stage: "todo", at: now, followed: now, note, history: [{ stage: "todo", at: now }] };
  }
  return saveTrack();
}

function touchTrack(id) {
  const rec = track[id];
  if (!rec) return false;
  const now = new Date().toISOString();
  rec.at = now;
  rec.followed = now;
  delete rec.snoozedUntil;
  saveTrack();
  return true;
}

function clearTrack(id) {
  delete track[id];
  saveTrack();
}

function snapshotTrack(id) {
  const rec = track[id];
  return rec ? JSON.parse(JSON.stringify(rec)) : null;
}

function restoreTrack(id, snapshot) {
  if (!id) return;
  if (snapshot) track[id] = JSON.parse(JSON.stringify(snapshot));
  else delete track[id];
  saveTrack();
}

function stageCounts(jobs) {
  const counts = { total: 0, none: 0 };
  STAGES.forEach((s) => { counts[s.id] = 0; });
  (jobs || []).forEach((job) => {
    const rec = trackOf(job.id);
    if (!rec) { counts.none++; return; }
    counts.total++;
    counts[rec.stage]++;
  });
  return counts;
}

function stageTime(rec) {
  if (!rec || !rec.at) return "";
  const at = new Date(rec.at);
  return Number.isNaN(at.getTime())
    ? "" : at.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function trackHistorySummary(rec, limit = 3) {
  const history = Array.isArray(rec?.history) ? rec.history : [];
  if (history.length < 2) return "";
  return history.slice(-limit).map((step) => stageMeta(step.stage)?.label || step.stage).join(" → ");
}

function stageTip(rec, jobId) {
  if (!rec) return "投递进度：点击设置";
  const label = stageMeta(rec.stage)?.label || rec.stage;
  const round = interviewRound(rec);
  const path = trackHistorySummary(rec);
  const due = followupReason(rec);
  const soon = interviewSoon(rec);
  const clash = jobId ? interviewClash(jobId, rec) : null;
  const snoozed = snoozedLabel(rec);
  const prepDone = interviewPrepDone(rec);
  const offer = rec.stage === "offer" ? offerDeadlineState(rec) : null;
  const last = due || snoozed || isTerminalStage(rec.stage) ? "" : followedAgo(rec);
  return [round ? `${round} · ${label}` : label, stageTime(rec), offer ? `答复截止 ${offer.stamp}` : "", due, soon && !due.includes("30 分钟内") ? "30 分钟内开始" : "", prepDone ? `面试准备 ${prepDone}/${PREP_TOTAL}` : "", clash ? `面试冲突 · ${interviewClashText(jobId, rec, clash)}` : "", snoozed, last ? `上次跟进 ${last}` : "", rec.note, path ? `阶段轨迹：${path}` : ""]
    .filter(Boolean).join(" · ");
}

function stageGap(from, to) {
  const a = Date.parse(from?.at);
  const b = Date.parse(to?.at);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return "";
  const mins = Math.max(0, Math.round((b - a) / 60000));
  if (mins < 60) return `${mins}分`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时`;
  return `${Math.floor(hours / 24)}天`;
}

function trackTimelineHTML(rec) {
  const history = Array.isArray(rec?.history) ? rec.history : [];
  if (history.length < 2) return "";
  const steps = history.slice(-3);
  return `<div class="track-timeline" title="阶段变更记录 · 仅存本机" aria-label="阶段变更记录">
    ${steps.map((step, index) => `${index ? `<span class="tt-gap">${esc(stageGap(steps[index - 1], step))}</span><span class="tt-arrow">${icon("chevron")}</span>` : ""}<span class="tt-step ${esc(step.stage)}"><b>${esc(stageMeta(step.stage)?.label || step.stage)}</b><em>${esc(stageTime(step))}</em></span>`).join("")}
    ${history.length > steps.length ? `<span class="tt-more">共 ${history.length} 次</span>` : ""}
  </div>`;
}

// ---------------------------------------------------------------- 本地数据备份
const BACKUP_APP = "swarm.workbench";
const BACKUP_VERSION = 1;
const TRACK_ID = /^[A-Za-z0-9_-]{1,64}$/;
let pendingBackup = null;
let droppedBackupFile = null;

function buildBackup() {
  return {
    app: BACKUP_APP,
    version: BACKUP_VERSION,
    exported_at: new Date().toISOString(),
    watch: { companies: [...watch.companies], jobs: [...watch.jobs] },
    track: Object.fromEntries(Object.entries(track).map(([id, rec]) => [id, {
      stage: rec.stage,
      at: rec.at,
      note: rec.note || "",
      ...(isInterviewRound(rec.round) ? { round: rec.round } : {}),
      ...(Array.isArray(rec.prep) && rec.prep.some(Boolean) ? { prep: normalizePrep(rec.prep) } : {}),
      ...(rec.followed ? { followed: rec.followed } : {}),
      ...(rec.snoozedUntil ? { snoozedUntil: rec.snoozedUntil } : {}),
      ...(rec.interviewAt ? { interviewAt: rec.interviewAt } : {}),
      ...(rec.offerUntil ? { offerUntil: rec.offerUntil } : {}),
      ...(Array.isArray(rec.history) && rec.history.length ? { history: rec.history } : {}),
    }])),
    compare: compareSelection(),
  };
}

function normalizeBackup(raw) {
  if (!raw || typeof raw !== "object" || raw.app !== BACKUP_APP) {
    throw new Error("不是 SWARM 备份文件");
  }
  if (raw.version !== BACKUP_VERSION) {
    throw new Error(`备份版本 ${raw.version == null ? "未知" : raw.version} 不受支持`);
  }
  const sourceWatch = raw.watch && typeof raw.watch === "object" ? raw.watch : {};
  const companies = [...new Set((Array.isArray(sourceWatch.companies) ? sourceWatch.companies : [])
    .filter((name) => typeof name === "string")
    .map((name) => name.trim())
    .filter((name) => name && name.length <= 200))].slice(0, 5000);
  const jobIds = [...new Set((Array.isArray(sourceWatch.jobs) ? sourceWatch.jobs : [])
    .filter((id) => typeof id === "string" && TRACK_ID.test(id)))].slice(0, 5000);
  const compare = Array.isArray(raw.compare)
    ? [...new Set(raw.compare
      .filter((key) => typeof key === "string" && key.trim() && key.length <= 200)
      .map((key) => key.trim()))].slice(0, 6)
    : null;
  const records = {};
  let skipped = 0;
  const sourceTrack = raw.track && typeof raw.track === "object" && !Array.isArray(raw.track) ? raw.track : {};
  Object.entries(sourceTrack).slice(0, 20000).forEach(([id, rec]) => {
    if (!TRACK_ID.test(id) || !rec || !STAGE_IDS.has(rec.stage) || !Number.isFinite(Date.parse(rec.at))) {
      skipped++;
      return;
    }
    const history = Array.isArray(rec.history)
      ? rec.history
        .filter((step) => step && STAGE_IDS.has(step.stage) && Number.isFinite(Date.parse(step.at)))
        .slice(-20)
        .map((step) => ({ stage: step.stage, at: new Date(step.at).toISOString() }))
      : [];
    const followed = Number.isFinite(Date.parse(rec.followed))
      ? new Date(rec.followed).toISOString() : "";
    const snoozedUntil = Number.isFinite(Date.parse(rec.snoozedUntil))
      ? new Date(rec.snoozedUntil).toISOString() : "";
    const interviewAt = Number.isFinite(Date.parse(rec.interviewAt))
      ? new Date(rec.interviewAt).toISOString() : "";
    const offerUntil = Number.isFinite(Date.parse(rec.offerUntil))
      ? new Date(rec.offerUntil).toISOString() : "";
    const prep = normalizePrep(rec.prep);
    records[id] = {
      stage: rec.stage,
      at: new Date(rec.at).toISOString(),
      note: String(rec.note || "").slice(0, 500),
      ...(isInterviewRound(rec.round) ? { round: rec.round } : {}),
      ...(prep.some(Boolean) ? { prep } : {}),
      ...(followed ? { followed } : {}),
      ...(snoozedUntil ? { snoozedUntil } : {}),
      ...(interviewAt ? { interviewAt } : {}),
      ...(offerUntil ? { offerUntil } : {}),
      ...(history.length ? { history } : {}),
    };
  });
  if (!companies.length && !jobIds.length && !Object.keys(records).length) {
    throw new Error("备份中没有可导入的关注或跟进数据");
  }
  return {
    watch: { companies, jobs: jobIds },
    track: records,
    compare,
    exportedAt: typeof raw.exported_at === "string" ? raw.exported_at : "",
    skipped,
  };
}

function applyBackup(data, mode = "replace") {
  if (!data) return;
  if (mode === "merge") {
    data.watch.companies.forEach((name) => watch.companies.add(name));
    data.watch.jobs.forEach((id) => watch.jobs.add(id));
    Object.entries(data.track).forEach(([id, rec]) => {
      const current = track[id];
      if (!current || Date.parse(rec.at) > Date.parse(current.at)) track[id] = rec;
    });
    if (data.compare) {
      const merged = [...new Set([...(compareSelection() || []), ...data.compare])].slice(0, 6);
      saveCompareSelection(merged.length ? merged : null);
    }
  } else {
    watch.companies = new Set(data.watch.companies);
    watch.jobs = new Set(data.watch.jobs);
    Object.keys(track).forEach((id) => delete track[id]);
    Object.assign(track, data.track);
    saveCompareSelection(data.compare && data.compare.length ? data.compare : null);
  }
  saveWatch();
  saveTrack();
  syncWatchLinks();
}

function setBackupStatus(text, tone = "") {
  const node = $("#backup-status");
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("is-error", tone === "error");
  node.classList.toggle("is-ok", tone === "ok");
}

function backupPreviewHTML(data, fileName) {
  const exported = data.exportedAt ? new Date(data.exportedAt) : null;
  const when = exported && !Number.isNaN(exported.getTime())
    ? exported.toLocaleString("zh-CN") : "未知时间";
  const trackCount = Object.keys(data.track).length;
  return `
    <div class="backup-preview">
      <div class="backup-preview-main">
        <div class="backup-preview-title">${icon("file")}${esc(fileName)}</div>
        <div class="backup-preview-meta">关注 ${data.watch.companies.length} 家公司 · ${data.watch.jobs.length} 个岗位
          · 跟进 ${trackCount} 条${data.compare && data.compare.length ? ` · 对比 ${data.compare.length} 家` : ""}</div>
        <div class="backup-preview-meta">导出于 ${esc(when)}${data.skipped ? ` · 已跳过 ${data.skipped} 条无效记录` : ""}</div>
      </div>
      <div class="backup-actions">
        <button type="button" class="btn btn-sm" data-backup-mode="replace">覆盖导入</button>
        <button type="button" class="btn btn-ghost btn-sm" data-backup-mode="merge">合并导入</button>
        <button type="button" class="btn btn-ghost btn-sm" data-backup-cancel>取消</button>
      </div>
    </div>
    <div class="backup-warn">覆盖会替换本机现有的关注、对比选择与跟进；合并保留较新的跟进记录，并追加关注与对比。</div>`;
}

function renderBackupPreview(data, fileName) {
  pendingBackup = data;
  const panel = $("#backup-panel");
  if (!panel) return;
  panel.innerHTML = backupPreviewHTML(data, fileName);
  panel.hidden = false;
  $$("[data-backup-mode]", panel).forEach((btn) => btn.addEventListener("click", async () => {
    if (!pendingBackup) return;
    const mode = btn.dataset.backupMode === "merge" ? "merge" : "replace";
    applyBackup(pendingBackup, mode);
    pendingBackup = null;
    panel.hidden = true;
    panel.innerHTML = "";
    const cmp = compareSelection();
    toast(`${mode === "merge" ? "已合并导入" : "已覆盖导入"} · 关注 ${watchTotal()} · 跟进 ${Object.keys(track).length}${cmp ? ` · 对比 ${cmp.length}` : ""}`);
    await pageSettings({ agent: state.cfgAgent });
  }));
  const cancel = $("[data-backup-cancel]", panel);
  if (cancel) cancel.addEventListener("click", () => {
    pendingBackup = null;
    panel.hidden = true;
    panel.innerHTML = "";
    setBackupStatus("已取消导入");
  });
  const primary = $("[data-backup-mode='replace']", panel);
  if (primary) primary.focus();
}

function backupName(filePath) {
  return String(filePath || "备份").split(/[\\/]/).pop();
}

async function exportBackup() {
  if (!watchTotal() && !Object.keys(track).length) {
    setBackupStatus("还没有可导出的关注或跟进数据", "error");
    if (!$("#backup-status")) toast("还没有可导出的关注或跟进数据", "warn");
    return;
  }
  if (!window.api.backupSave) {
    setBackupStatus("当前版本不支持导出", "error");
    return;
  }
  setBackupStatus("正在导出…");
  const stamp = new Date().toISOString().slice(0, 10);
  const res = await window.api.backupSave(`swarm-backup-${stamp}.json`, JSON.stringify(buildBackup(), null, 2));
  if (res.canceled) {
    setBackupStatus("已取消导出");
    if (!$("#backup-status")) toast("已取消导出", "info");
    return;
  }
  if (!res.ok) {
    const error = "导出失败：" + (res.error || "未知错误");
    setBackupStatus(error, "error");
    if (!$("#backup-status")) toast(error, "warn");
    return;
  }
  setBackupStatus(`已导出到 ${backupName(res.filePath)}`, "ok");
  toast("本地备份已导出");
}

async function importBackup() {
  if (!window.api.backupOpen) {
    setBackupStatus("当前版本不支持导入", "error");
    return;
  }
  setBackupStatus("请选择备份文件…");
  const res = await window.api.backupOpen();
  if (res.canceled) { setBackupStatus("已取消导入"); return; }
  if (!res.ok) { setBackupStatus("读取失败：" + (res.error || "未知错误"), "error"); return; }
  prepareBackup(res.text, backupName(res.filePath));
}

function prepareBackup(text, fileName) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    setBackupStatus("导入失败：文件不是有效的 JSON", "error");
    return;
  }
  let data;
  try {
    data = normalizeBackup(parsed);
  } catch (err) {
    setBackupStatus("导入失败：" + err.message, "error");
    return;
  }
  renderBackupPreview(data, fileName);
  setBackupStatus("已读取文件，请选择导入方式");
}

async function importDroppedBackup(file) {
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) {
    setBackupStatus("导入失败：文件超过 4 MB", "error");
    return;
  }
  if (!/\.json$/i.test(file.name) && file.type !== "application/json") {
    setBackupStatus("导入失败：请拖入 JSON 备份文件", "error");
    return;
  }
  setBackupStatus(`正在读取 ${file.name}…`);
  try {
    prepareBackup(await file.text(), file.name);
  } catch {
    setBackupStatus("导入失败：无法读取该文件", "error");
  }
}

function followupMarkdown(jobs) {
  const rows = (jobs || []).filter((job) => trackOf(job.id))
    .sort((a, b) => String(trackOf(b.id).at).localeCompare(String(trackOf(a.id).at)));
  if (!rows.length) return "";
  const cell = (value) => String(value || "").replace(/\|/g, "\\|").replace(/\r?\n/g, " ").trim();
  return [
    "# 投递跟进",
    "",
    "| 岗位 | 公司 | 阶段 | 更新 | 备注 |",
    "| --- | --- | --- | --- | --- |",
    ...rows.map((job) => {
      const rec = trackOf(job.id);
      return `| ${cell(job.title)} | ${cell(job.company)} | ${stageMeta(rec.stage).label} | ${stageTime(rec)} | ${cell(rec.note)} |`;
    }),
  ].join("\n");
}

const DAY_MS = 86400000;
const SNOOZE_DAYS = 3;
const SNOOZE_PRESETS = [
  { days: 1, label: "1 天" },
  { days: 3, label: "3 天" },
  { days: 7, label: "1 周" },
  { days: 14, label: "2 周" },
];
const INTERVIEW_PRESETS = [
  { label: "明天 10:00", days: 1, hour: 10 },
  { label: "明天 14:00", days: 1, hour: 14 },
  { label: "后天 10:00", days: 2, hour: 10 },
  { label: "下周一 10:00", days: "monday", hour: 10 },
];
const INTERVIEW_OUTCOMES = [
  { id: "waiting", label: "等结果", hint: `延后 ${SNOOZE_DAYS} 天提醒` },
  { id: "next", label: "进入下一轮", hint: "清空本轮时间，待安排" },
  { id: "offer", label: "收到 Offer", hint: "阶段标记为 Offer" },
  { id: "rejected", label: "未通过", hint: "归档到已拒" },
];
const INTERVIEW_GRACE_MS = 2 * 60 * 60 * 1000;
const INTERVIEW_SLOT_MS = 60 * 60 * 1000;
const INTERVIEW_SOON_MS = 30 * 60 * 1000;
const HUD_LIVE_MS = 30 * 60 * 1000;
const pad2 = (value) => String(value).padStart(2, "0");

function interviewTime(rec) {
  const at = Date.parse(rec?.interviewAt);
  return Number.isFinite(at) ? at : 0;
}

function interviewRound(rec) {
  return isInterviewRound(rec?.round) ? rec.round : "";
}

function interviewNextRound(rec) {
  const index = INTERVIEW_ROUNDS.indexOf(interviewRound(rec));
  return index >= 0 && index < INTERVIEW_ROUNDS.length - 1 ? INTERVIEW_ROUNDS[index + 1] : "";
}

function interviewPrepDone(rec) {
  return normalizePrep(rec?.prep).filter(Boolean).length;
}

function interviewStamp(rec) {
  const at = interviewTime(rec);
  if (!at) return "";
  const date = new Date(at);
  return `${pad2(date.getMonth() + 1)}/${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function interviewCountdown(rec) {
  const at = interviewTime(rec);
  if (!at) return "";
  const now = new Date();
  const target = new Date(at);
  const dayIndex = (date) => Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / DAY_MS);
  const days = dayIndex(target) - dayIndex(now);
  if (days === 0) return "今天";
  if (days === 1) return "明天";
  if (days === -1) return "昨天";
  return days > 1 ? `${days} 天后` : `${-days} 天前`;
}

function interviewClock(rec) {
  const at = interviewTime(rec);
  if (!at) return "";
  const date = new Date(at);
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function interviewPhase(rec, now = Date.now()) {
  const at = interviewTime(rec);
  if (!at) return "";
  if (now < at) return "upcoming";
  return now < at + INTERVIEW_GRACE_MS ? "live" : "past";
}

function interviewStarted(rec, now = Date.now()) {
  if (!rec || rec.stage !== "interview") return false;
  const at = interviewTime(rec);
  return !!at && now >= at;
}

function interviewGapText(delta) {
  const minutes = Math.round(Math.abs(delta) / 60000);
  return minutes === 0 ? "时间完全重合" : `仅相隔 ${minutes} 分钟`;
}

function interviewSoon(rec, now = Date.now()) {
  if (!rec || rec.stage !== "interview") return false;
  const at = interviewTime(rec);
  return at > now && at - now <= INTERVIEW_SOON_MS;
}

function interviewConflicts(jobId, at) {
  if (!Number.isFinite(at)) return [];
  return Object.entries(track)
    .filter(([id, rec]) => id !== jobId && rec.stage === "interview" && interviewTime(rec))
    .map(([id, rec]) => ({ id, at: interviewTime(rec) }))
    .filter((item) => Math.abs(item.at - at) < INTERVIEW_SLOT_MS)
    .sort((a, b) => Math.abs(a.at - at) - Math.abs(b.at - at));
}

function interviewJobTitle(jobId) {
  return (state.data?.jobs || []).find((job) => job.id === jobId)?.title || "另一场面试";
}

function interviewClash(jobId, rec) {
  if (!rec || rec.stage !== "interview") return null;
  const at = interviewTime(rec);
  return at ? interviewConflicts(jobId, at)[0] || null : null;
}

function interviewClashText(jobId, rec, clash) {
  if (!clash) return "";
  return `与「${interviewJobTitle(clash.id)}」${interviewGapText(clash.at - interviewTime(rec))}`;
}

function localInputValue(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

function interviewInputValue(rec) {
  const at = interviewTime(rec);
  return at ? localInputValue(new Date(at)) : "";
}

function interviewPresetAt(days, hour) {
  const date = new Date();
  const offset = days === "monday"
    ? (8 - date.getDay()) % 7 || 7
    : Number(days);
  date.setDate(date.getDate() + offset);
  date.setHours(hour, 0, 0, 0);
  return date;
}

function offerDeadline(rec) {
  const at = Date.parse(rec?.offerUntil);
  return Number.isFinite(at) ? at : 0;
}

function offerDeadlineState(rec, now = Date.now()) {
  if (!rec || rec.stage !== "offer") return null;
  const at = offerDeadline(rec);
  if (!at) return null;
  const target = new Date(at);
  const today = new Date(now);
  const dayIndex = (date) => Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / DAY_MS);
  const days = dayIndex(target) - dayIndex(today);
  return {
    at,
    days,
    expired: now >= at,
    soon: now < at && at - now <= 2 * DAY_MS,
    clock: `${pad2(target.getHours())}:${pad2(target.getMinutes())}`,
    stamp: `${pad2(target.getMonth() + 1)}/${pad2(target.getDate())} ${pad2(target.getHours())}:${pad2(target.getMinutes())}`,
  };
}

function offerDeadlineShort(rec, now = Date.now()) {
  const state = offerDeadlineState(rec, now);
  if (!state) return "";
  if (state.expired) return state.days <= -1 ? `已过期 ${-state.days} 天` : "今天已过截止";
  if (state.days === 0) return `今天 ${state.clock} 截止`;
  if (state.days === 1) return `明天 ${state.clock} 截止`;
  return `剩 ${state.days} 天截止`;
}

function offerDeadlineLabel(rec, now = Date.now()) {
  const state = offerDeadlineState(rec, now);
  if (!state) return "";
  if (state.expired) return state.days <= -1 ? `已过答复期 ${-state.days} 天` : `今天 ${state.clock} 已过截止`;
  if (state.days <= 1) return offerDeadlineShort(rec, now);
  return `${offerDeadlineShort(rec, now)} · ${state.stamp}`;
}

function offerInputValue(rec) {
  const at = offerDeadline(rec);
  return at ? localInputValue(new Date(at)) : "";
}

function offerPresetAt(days = 3) {
  const date = new Date();
  date.setDate(date.getDate() + Number(days));
  date.setHours(18, 0, 0, 0);
  return date;
}

function snoozeEnd(rec) {
  const until = Date.parse(rec?.snoozedUntil);
  return Number.isFinite(until) && until > Date.now() ? until : 0;
}

function snoozeDay(rec) {
  const until = snoozeEnd(rec);
  if (!until) return "";
  const date = new Date(until);
  return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
}

function snoozedLabel(rec) {
  const day = snoozeDay(rec);
  return day ? `已延后至 ${day}` : "";
}

function snoozeTrack(id, days = SNOOZE_DAYS) {
  const rec = track[id];
  if (!rec) return "";
  rec.snoozedUntil = new Date(Date.now() + days * DAY_MS).toISOString();
  saveTrack();
  return snoozedLabel(rec);
}

function unsnoozeTrack(id) {
  const rec = track[id];
  if (!rec || !snoozeEnd(rec)) return false;
  delete rec.snoozedUntil;
  saveTrack();
  return true;
}

let snoozeMenuAnchor = null;
let snoozeMenuPick = null;

function snoozePresetWhen(days) {
  const date = new Date(Date.now() + days * DAY_MS);
  const day = `${pad2(date.getMonth() + 1)}/${pad2(date.getDate())}`;
  return days === 1 ? `明天 · ${day}` : `周${"日一二三四五六"[date.getDay()]} · ${day}`;
}

function closeSnoozeMenu(refocus = false) {
  const menu = $("#snooze-menu");
  const anchor = snoozeMenuAnchor;
  snoozeMenuAnchor = null;
  snoozeMenuPick = null;
  if (!menu || menu.hidden) return;
  const hadFocus = menu.contains(document.activeElement);
  menu.hidden = true;
  anchor?.setAttribute("aria-expanded", "false");
  if (refocus || hadFocus) anchor?.focus({ preventScroll: true });
}

function openSnoozeMenu(anchor, { jobId, title, onPick }) {
  const rec = trackOf(jobId);
  if (!anchor || !rec || isTerminalStage(rec.stage) || snoozeEnd(rec)) return;
  let menu = $("#snooze-menu");
  if (!menu) {
    menu = document.createElement("div");
    menu.id = "snooze-menu";
    menu.className = "snooze-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", "延后提醒时长");
    menu.hidden = true;
    menu.innerHTML = `
      <div class="snooze-menu-head">${icon("clock")}<span>延后提醒</span><em id="snooze-menu-job"></em></div>
      ${SNOOZE_PRESETS.map((preset) => `<button type="button" role="menuitem" data-snooze-days="${preset.days}">
        <span>${preset.label}</span><em>${snoozePresetWhen(preset.days)}</em>
      </button>`).join("")}
      <div class="snooze-menu-foot">延后期间不进入待行动 · Esc 关闭</div>`;
    document.body.appendChild(menu);
    menu.addEventListener("click", (event) => {
      const option = event.target.closest("[data-snooze-days]");
      if (!option) return;
      const pick = snoozeMenuPick;
      closeSnoozeMenu(false);
      pick?.(Number(option.dataset.snoozeDays));
    });
    menu.addEventListener("keydown", (event) => {
      const options = [...menu.querySelectorAll('[role="menuitem"]')];
      const index = options.indexOf(document.activeElement);
      if (event.key === "Escape") {
        event.preventDefault();
        closeSnoozeMenu(true);
        return;
      }
      if (event.key === "Tab") {
        event.preventDefault();
        closeSnoozeMenu(true);
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
        const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1
          : (index + step + options.length) % options.length;
        options[next]?.focus({ preventScroll: true });
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (!snoozeMenuAnchor || menu.hidden) return;
      if (menu.contains(event.target) || snoozeMenuAnchor.contains(event.target)) return;
      closeSnoozeMenu(false);
    });
    window.addEventListener("scroll", () => closeSnoozeMenu(false), true);
    window.addEventListener("resize", () => closeSnoozeMenu(false));
    window.addEventListener("hashchange", () => closeSnoozeMenu(false));
  }
  if (snoozeMenuAnchor === anchor && !menu.hidden) {
    closeSnoozeMenu(true);
    return;
  }
  closeSnoozeMenu(false);
  snoozeMenuAnchor = anchor;
  snoozeMenuPick = onPick;
  anchor.setAttribute("aria-expanded", "true");
  const head = menu.querySelector("#snooze-menu-job");
  if (head) {
    head.textContent = title || "";
    head.title = title || "";
  }
  menu.querySelectorAll("[data-snooze-days]").forEach((option) => {
    const label = option.querySelector("em");
    if (label) label.textContent = snoozePresetWhen(Number(option.dataset.snoozeDays));
  });
  menu.hidden = false;
  menu.style.visibility = "hidden";
  menu.style.left = "0px";
  menu.style.top = "0px";
  const rect = anchor.getBoundingClientRect();
  const box = menu.getBoundingClientRect();
  const left = Math.max(8, Math.min(window.innerWidth - box.width - 8, rect.right - box.width));
  let top = rect.bottom + 6;
  if (top + box.height > window.innerHeight - 8) top = rect.top - box.height - 6;
  top = Math.max(8, Math.min(window.innerHeight - box.height - 8, top));
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  menu.style.visibility = "";
  menu.querySelector('[data-snooze-days="3"]')?.focus({ preventScroll: true });
}

let interviewDialogOpen = false;

function openInterviewScheduler(jobId, { anchor = null, focusAfterSave = null } = {}) {
  if (interviewDialogOpen) return false;
  const job = (state.data?.jobs || []).find((item) => item.id === jobId);
  const rec = trackOf(jobId);
  if (!job) {
    toast("找不到岗位数据，请先刷新", "warn");
    return false;
  }
  if (!rec || rec.stage !== "interview") {
    toast("先把岗位标记为「面试」，再安排时间", "warn");
    return false;
  }
  const rescheduling = !!interviewTime(rec);
  const dialogLabel = rescheduling ? "调整面试时间" : "安排面试";
  interviewDialogOpen = true;
  const dialog = document.createElement("dialog");
  dialog.className = "confirm-dialog interview-dialog";
  dialog.setAttribute("aria-label", dialogLabel);
  dialog.innerHTML = `
    <form class="interview-form" novalidate>
      <div class="confirm-head">${icon("clock")}${dialogLabel}</div>
      <div class="confirm-body interview-body">
        <p class="interview-job"><b>${esc(job.title)}</b><span>${esc(job.company || "—")}</span></p>
        <label class="interview-label" for="interview-dialog-round">面试轮次</label>
        <select id="interview-dialog-round" class="interview-round-select">
          <option value="">不标轮次</option>
          ${INTERVIEW_ROUNDS.map((round) => `<option value="${esc(round)}">${esc(round)}</option>`).join("")}
        </select>
        <label class="interview-label" for="interview-dialog-at">面试时间</label>
        <input id="interview-dialog-at" type="datetime-local" step="60" aria-describedby="interview-dialog-hint">
        <div class="interview-presets" role="group" aria-label="快捷时间">
          ${INTERVIEW_PRESETS.map((preset) => `<button type="button" class="chip interview-preset"
            data-interview-preset data-days="${preset.days}" data-hour="${preset.hour}">${esc(preset.label)}</button>`).join("")}
        </div>
        <p class="interview-conflict" role="status" hidden></p>
        <button type="button" class="chip interview-suggest" data-interview-suggest hidden></button>
        <p class="interview-error" hidden>请选择有效的面试时间</p>
        <p class="interview-hint" id="interview-dialog-hint">保存后总览、岗位列表与看板同步倒计时 · 仅存本机</p>
      </div>
      <div class="confirm-actions">
        <button type="button" class="btn btn-ghost btn-sm" data-interview-cancel>取消</button>
        <button type="submit" class="btn btn-sm">${icon("check")}保存时间</button>
      </div>
    </form>`;
  document.body.appendChild(dialog);
  const form = dialog.querySelector("form");
  const input = dialog.querySelector("#interview-dialog-at");
  const error = dialog.querySelector(".interview-error");
  const conflict = dialog.querySelector(".interview-conflict");
  const suggest = dialog.querySelector("[data-interview-suggest]");
  const roundSelect = dialog.querySelector("#interview-dialog-round");
  roundSelect.value = interviewRound(rec) || INTERVIEW_ROUNDS[0];
  input.value = interviewInputValue(rec) || localInputValue(interviewPresetAt(1, 10));
  const syncConflict = () => {
    const at = Date.parse(input.value);
    const clashes = interviewConflicts(jobId, at);
    if (!clashes.length) {
      conflict.hidden = true;
      suggest.hidden = true;
      return;
    }
    const first = clashes[0];
    const more = clashes.length > 1 ? `，另有 ${clashes.length - 1} 场` : "";
    conflict.innerHTML = `${icon("alert")}<span>与「${esc(interviewJobTitle(first.id))}」的面试${interviewGapText(first.at - at)}${more} · 按每场约 1 小时估算</span>`;
    conflict.hidden = false;
    const safeAt = Math.max(...clashes.map((item) => item.at)) + INTERVIEW_SLOT_MS;
    const safeDate = new Date(safeAt);
    suggest.dataset.at = String(safeAt);
    suggest.textContent = `顺延到 ${pad2(safeDate.getHours())}:${pad2(safeDate.getMinutes())}`;
    suggest.title = `避开冲突：${safeDate.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })} · 与对方相隔 1 小时`;
    suggest.hidden = false;
  };
  syncConflict();
  let closedBy = "";
  const close = (reason) => {
    if (!dialog.open) return;
    closedBy = reason;
    dialog.close();
  };
  const refocus = () => {
    if (anchor && document.contains(anchor)) {
      anchor.focus({ preventScroll: true });
      return;
    }
    const selector = `[data-interview-schedule="${CSS.escape(jobId)}"], [data-interview-row="${CSS.escape(jobId)}"], [data-job="${CSS.escape(jobId)}"]`;
    document.querySelector(selector)?.focus({ preventScroll: true });
  };
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close("cancel");
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close("cancel");
  });
  dialog.addEventListener("close", () => {
    interviewDialogOpen = false;
    dialog.remove();
    if (closedBy !== "save") refocus();
  });
  dialog.querySelector("[data-interview-cancel]").addEventListener("click", () => close("cancel"));
  dialog.querySelectorAll("[data-interview-preset]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = localInputValue(interviewPresetAt(button.dataset.days, Number(button.dataset.hour)));
      error.hidden = true;
      syncConflict();
      input.focus({ preventScroll: true });
    });
  });
  input.addEventListener("input", () => {
    error.hidden = true;
    syncConflict();
  });
  suggest.addEventListener("click", () => {
    const at = Number(suggest.dataset.at);
    if (!Number.isFinite(at) || at <= 0) return;
    input.value = localInputValue(new Date(at));
    error.hidden = true;
    syncConflict();
    input.focus({ preventScroll: true });
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const parsed = Date.parse(input.value);
    if (!input.value || !Number.isFinite(parsed)) {
      error.hidden = false;
      input.focus({ preventScroll: true });
      return;
    }
    const current = trackOf(jobId);
    if (!current || current.stage !== "interview") {
      close("cancel");
      toast("岗位状态已变化，请重新标记面试阶段", "warn");
      return;
    }
    const clashes = interviewConflicts(jobId, parsed);
    const before = snapshotTrack(jobId);
    const chosenRound = roundSelect.value;
    if (isInterviewRound(chosenRound)) current.round = chosenRound; else delete current.round;
    current.interviewAt = new Date(parsed).toISOString();
    saveTrack();
    close("save");
    const saved = trackOf(jobId);
    toast(`${rescheduling ? "面试已改期" : "面试已安排"} · ${chosenRound ? `${chosenRound} · ` : ""}${interviewCountdown(saved)} ${interviewClock(saved)}${clashes.length ? " · 时间冲突" : ""}`, clashes.length ? "warn" : "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(jobId, before);
        document.dispatchEvent(new CustomEvent("interviewchange"));
        routing.then(() => {
          const selector = `[data-interview-schedule="${CSS.escape(jobId)}"], [data-interview-row="${CSS.escape(jobId)}"], [data-job="${CSS.escape(jobId)}"]`;
          document.querySelector(selector)?.focus({ preventScroll: true });
        });
        toast(rescheduling ? "已恢复原面试时间" : "已撤销面试安排", "info");
      },
    });
    document.dispatchEvent(new CustomEvent("interviewchange"));
    if (focusAfterSave) routing.then(() => focusAfterSave());
  });
  dialog.showModal();
  input.focus({ preventScroll: true });
  return true;
}

function applyInterviewFeedback(id, outcome, text) {
  const rec = track[id];
  if (!rec || rec.stage !== "interview") return null;
  const before = snapshotTrack(id);
  const stamp = interviewStamp(rec) || `${pad2(new Date().getMonth() + 1)}/${pad2(new Date().getDate())}`;
  if (outcome === "next") {
    touchTrack(id);
    const nextRound = interviewNextRound(track[id]);
    if (nextRound) track[id].round = nextRound; else delete track[id].round;
    // 新一轮重新准备，旧清单只对新记录有意义
    delete track[id].prep;
    delete track[id].interviewAt;
    saveTrack();
  } else if (outcome === "offer" || outcome === "rejected") {
    setTrackStage(id, outcome);
  } else {
    touchTrack(id);
    track[id].snoozedUntil = new Date(Date.now() + SNOOZE_DAYS * DAY_MS).toISOString();
    saveTrack();
  }
  if (text) {
    const note = [track[id].note || "", `[${stamp} 面试反馈] ${text}`]
      .filter(Boolean).join("\n").slice(-500);
    setTrackNote(id, note);
  }
  return before;
}

let feedbackDialogOpen = false;

function openInterviewFeedback(jobId, { anchor = null, focusAfterSave = null } = {}) {
  if (feedbackDialogOpen) return false;
  const job = (state.data?.jobs || []).find((item) => item.id === jobId);
  const rec = trackOf(jobId);
  if (!job || !rec || rec.stage !== "interview" || !interviewTime(rec)) {
    toast("找不到可记录的面试，请刷新后重试", "warn");
    return false;
  }
  const round = interviewRound(rec);
  const nextRound = interviewNextRound(rec);
  feedbackDialogOpen = true;
  const dialog = document.createElement("dialog");
  dialog.className = "confirm-dialog interview-dialog feedback-dialog";
  dialog.setAttribute("aria-label", `记录面试反馈${round ? ` · ${round}` : ""}`);
  dialog.innerHTML = `
    <form class="feedback-form" novalidate>
      <div class="confirm-head">${icon("chat")}记录面试反馈${round ? ` · ${esc(round)}` : ""}</div>
      <div class="confirm-body interview-body">
        <p class="interview-job"><b>${esc(job.title)}</b><span>${esc(job.company || "—")} · ${round ? `${esc(round)} · ` : ""}面试 ${esc(interviewStamp(rec))}</span></p>
        <span class="interview-label" id="feedback-outcome-label">面试结果</span>
        <div class="feedback-outcomes" role="radiogroup" aria-labelledby="feedback-outcome-label">
          ${INTERVIEW_OUTCOMES.map((item) => `<button type="button" class="feedback-outcome" role="radio"
            data-feedback-outcome="${item.id}" data-outcome="${item.id}"
            aria-checked="${item.id === "waiting"}" tabindex="${item.id === "waiting" ? "0" : "-1"}">
            <b>${esc(item.label)}</b><em>${esc(item.id === "next" && nextRound ? `${nextRound}待安排` : item.hint)}</em></button>`).join("")}
        </div>
        <label class="interview-label" for="feedback-note">复盘备注（可选）</label>
        <textarea id="feedback-note" class="feedback-note" rows="3" maxlength="300"
          placeholder="被问到的题、卡住的点、下一步准备…"></textarea>
        <p class="interview-hint">按所选结果更新阶段或提醒 · 复盘会追加到跟进备注 · 仅存本机</p>
      </div>
      <div class="confirm-actions">
        <button type="button" class="btn btn-ghost btn-sm" data-feedback-cancel>取消</button>
        <button type="submit" class="btn btn-sm">${icon("check")}保存反馈</button>
      </div>
    </form>`;
  document.body.appendChild(dialog);
  const form = dialog.querySelector("form");
  const noteInput = dialog.querySelector("#feedback-note");
  const options = [...dialog.querySelectorAll("[data-feedback-outcome]")];
  const selectedOutcome = () => options.find((btn) => btn.getAttribute("aria-checked") === "true")?.dataset.feedbackOutcome || "waiting";
  const pickOutcome = (btn, focus = true) => {
    options.forEach((other) => {
      const on = other === btn;
      other.setAttribute("aria-checked", String(on));
      other.tabIndex = on ? 0 : -1;
    });
    if (focus) btn.focus({ preventScroll: true });
  };
  options.forEach((btn) => btn.addEventListener("click", () => pickOutcome(btn, false)));
  dialog.querySelector(".feedback-outcomes").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    const index = options.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    const delta = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
    pickOutcome(options[(index + delta + options.length) % options.length]);
  });
  let closedBy = "";
  const close = (reason) => {
    if (!dialog.open) return;
    closedBy = reason;
    dialog.close();
  };
  const refocus = () => {
    if (anchor && document.contains(anchor)) {
      anchor.focus({ preventScroll: true });
      return;
    }
    const selector = `[data-interview-row="${CSS.escape(jobId)}"], [data-interview-schedule="${CSS.escape(jobId)}"], [data-interview-feedback="${CSS.escape(jobId)}"]`;
    document.querySelector(selector)?.focus({ preventScroll: true });
  };
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close("cancel");
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close("cancel");
  });
  dialog.addEventListener("close", () => {
    feedbackDialogOpen = false;
    dialog.remove();
    if (closedBy !== "save") refocus();
  });
  dialog.querySelector("[data-feedback-cancel]").addEventListener("click", () => close("cancel"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const current = trackOf(jobId);
    if (!current || current.stage !== "interview" || !interviewTime(current)) {
      close("cancel");
      toast("岗位状态已变化，请刷新后重试", "warn");
      return;
    }
    const outcome = selectedOutcome();
    const before = applyInterviewFeedback(jobId, outcome, noteInput.value.trim());
    if (!before) {
      close("cancel");
      return;
    }
    close("save");
    const message = outcome === "waiting"
      ? `反馈已记录 · ${SNOOZE_DAYS} 天后再提醒`
      : outcome === "next" ? `反馈已记录 · ${nextRound || "下一轮"}待安排`
      : outcome === "offer" ? "反馈已记录 · 已标记 Offer"
      : "反馈已记录 · 已归档为已拒";
    toast(message, "ok", {
      label: "撤销",
      onClick: () => {
        restoreTrack(jobId, before);
        document.dispatchEvent(new CustomEvent("trackchange", { detail: { id: jobId } }));
        document.dispatchEvent(new CustomEvent("interviewchange"));
        routing.then(() => {
          const selector = `[data-interview-feedback="${CSS.escape(jobId)}"], [data-interview-schedule="${CSS.escape(jobId)}"], [data-interview-row="${CSS.escape(jobId)}"], [data-touch-job="${CSS.escape(jobId)}"], [data-job="${CSS.escape(jobId)}"]`;
          document.querySelector(selector)?.focus({ preventScroll: true });
        });
        toast("已撤销面试反馈", "info");
      },
    });
    document.dispatchEvent(new CustomEvent("trackchange", { detail: { id: jobId } }));
    document.dispatchEvent(new CustomEvent("interviewchange"));
    if (focusAfterSave) routing.then(() => focusAfterSave());
  });
  dialog.showModal();
  options.find((btn) => btn.getAttribute("aria-checked") === "true")?.focus({ preventScroll: true });
  return true;
}

function exportableInterviews(now = Date.now()) {
  return Object.entries(track)
    .filter(([, rec]) => rec.stage === "interview")
    .map(([id, rec]) => ({ id, rec, at: interviewTime(rec) }))
    .filter(({ at }) => at && at + INTERVIEW_SLOT_MS > now)
    .sort((a, b) => a.at - b.at);
}

function icsEscape(value) {
  return String(value ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/\r?\n/g, "\\n")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,");
}

function icsDate(at) {
  const date = new Date(at);
  return `${date.getUTCFullYear()}${pad2(date.getUTCMonth() + 1)}${pad2(date.getUTCDate())}T${pad2(date.getUTCHours())}${pad2(date.getUTCMinutes())}${pad2(date.getUTCSeconds())}Z`;
}

function icsFold(line) {
  const encoder = new TextEncoder();
  const parts = [];
  let current = "";
  let bytes = 0;
  for (const char of String(line)) {
    const size = encoder.encode(char).length;
    if (bytes + size > 75) {
      parts.push(current);
      current = ` ${char}`;
      bytes = 1 + size;
    } else {
      current += char;
      bytes += size;
    }
  }
  parts.push(current);
  return parts.join("\r\n");
}

function interviewIcs(rows = exportableInterviews()) {
  const stamp = icsDate(Date.now());
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SWARM TALENT//Interview Calendar//ZH",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:SWARM 面试日程",
    "X-WR-CALDESC:来自 SWARM 求职工作台的面试安排（仅本机生成）",
  ];
  rows.forEach(({ id, rec, at }) => {
    const job = (state.data?.jobs || []).find((item) => item.id === id) || {};
    const title = job.title || "岗位";
    const company = job.company || "";
    const round = interviewRound(rec);
    const facts = [
      `公司：${company || "—"}`,
      `岗位：${title}`,
      round ? `轮次：${round}` : "",
      job.city ? `城市：${job.city}` : "",
      "来源：SWARM 求职背调工作台",
    ].filter(Boolean);
    lines.push(
      "BEGIN:VEVENT",
      `UID:swarm-${id}-${at}@local`,
      `DTSTAMP:${stamp}`,
      `DTSTART:${icsDate(at)}`,
      `DTEND:${icsDate(at + INTERVIEW_SLOT_MS)}`,
      `SUMMARY:${icsEscape(`面试 · ${round ? `${round} · ` : ""}${company ? `${company} · ` : ""}${title}`)}`,
      `DESCRIPTION:${icsEscape(facts.join("\n"))}`,
      ...(job.city ? [`LOCATION:${icsEscape(job.city)}`] : []),
      "STATUS:CONFIRMED",
      "TRANSP:OPAQUE",
      "BEGIN:VALARM",
      "TRIGGER:-PT30M",
      "ACTION:DISPLAY",
      `DESCRIPTION:${icsEscape(`面试 30 分钟后开始 · ${title}`)}`,
      "END:VALARM",
      "END:VEVENT",
    );
  });
  lines.push("END:VCALENDAR");
  return `${lines.map(icsFold).join("\r\n")}\r\n`;
}

function icsFileName() {
  const now = new Date();
  return `swarm-interviews-${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}.ics`;
}

let icsDialogOpen = false;

function openInterviewIcsDialog({ anchor = null } = {}) {
  if (icsDialogOpen) return false;
  const rows = exportableInterviews();
  if (!rows.length) {
    toast("暂无可以导出的面试", "info");
    return false;
  }
  const ics = interviewIcs(rows);
  const first = rows[0];
  const when = `${interviewCountdown(first.rec)} ${interviewClock(first.rec)}`;
  icsDialogOpen = true;
  const dialog = document.createElement("dialog");
  dialog.className = "confirm-dialog interview-dialog ics-dialog";
  dialog.setAttribute("aria-label", "导出面试日历");
  dialog.innerHTML = `
    <div class="confirm-head">${icon("download")}导出面试日历</div>
    <div class="confirm-body interview-body">
      <p class="ics-summary"><b>${rows.length} 场面试</b><span>${esc(when)} 起 · 每场按 1 小时 · 含提前 30 分钟提醒</span></p>
      <pre class="ics-preview" tabindex="0" aria-label="日历文件预览">${esc(ics)}</pre>
      <p class="interview-hint">.ics 可导入系统日历、Outlook 或手机日历 · 文件仅在本机生成</p>
    </div>
    <div class="confirm-actions">
      <button type="button" class="btn btn-ghost btn-sm" data-ics-cancel>取消</button>
      <button type="button" class="btn btn-ghost btn-sm" data-ics-copy>${icon("copy")}复制</button>
      <button type="button" class="btn btn-sm" data-ics-download>${icon("download")}下载 .ics</button>
    </div>`;
  document.body.appendChild(dialog);
  let closedBy = "";
  const close = (reason) => {
    if (!dialog.open) return;
    closedBy = reason;
    dialog.close();
  };
  const refocus = () => {
    if (anchor && document.contains(anchor)) {
      anchor.focus({ preventScroll: true });
      return;
    }
    $("#btn-export-ics")?.focus({ preventScroll: true });
  };
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close("cancel");
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close("cancel");
  });
  dialog.addEventListener("close", () => {
    icsDialogOpen = false;
    dialog.remove();
    refocus();
  });
  dialog.querySelector("[data-ics-cancel]").addEventListener("click", () => close("cancel"));
  dialog.querySelector("[data-ics-copy]").addEventListener("click", async () => {
    try {
      await copyText(ics);
      close("done");
      toast(`已复制 ${rows.length} 场面试 · 粘贴到日历应用`, "ok");
    } catch {
      toast("复制失败，可手动选择预览内容", "warn");
    }
  });
  dialog.querySelector("[data-ics-download]").addEventListener("click", () => {
    try {
      const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = icsFileName();
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      close("done");
      toast(`已导出 ${rows.length} 场面试 · 用日历应用打开 .ics`, "ok");
    } catch {
      toast("下载失败，可改用「复制」", "warn");
    }
  });
  dialog.showModal();
  dialog.querySelector("[data-ics-download]")?.focus({ preventScroll: true });
  return true;
}

let snoozeTimer = 0;
function scheduleSnoozeWake() {  clearTimeout(snoozeTimer);
  snoozeTimer = 0;
  const upcoming = Object.values(track)
    .map((rec) => Date.parse(rec.snoozedUntil))
    .filter((until) => Number.isFinite(until) && until > Date.now());
  if (!upcoming.length) return;
  const next = Math.min(...upcoming);
  // 浏览器定时器上限约 24.8 天；长延后先睡一段，醒来再续
  const delay = Math.min(next - Date.now() + 200, 6 * 60 * 60 * 1000);
  snoozeTimer = setTimeout(() => {
    snoozeTimer = 0;
    const now = Date.now();
    const ids = Object.keys(track).filter((id) => {
      const until = Date.parse(track[id]?.snoozedUntil);
      return Number.isFinite(until) && until <= now;
    });
    if (ids.length) {
      ids.forEach((id) => { delete track[id].snoozedUntil; });
      saveTrack();
      document.dispatchEvent(new CustomEvent("snoozeexpired", { detail: { ids } }));
      // 到期是后台事件，不抢掉用户手里仍可撤销的提示
      if (!toastUndo) {
        toast(ids.length === 1 ? "1 个岗位延后结束，已回到待行动" : `${ids.length} 个岗位延后结束，已回到待行动`, "info");
      }
    }
    scheduleSnoozeWake();
  }, delay);
}

let interviewTimer = 0;

function nextLocalMidnight() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 0, 50).getTime();
}

function scheduleInterviewWake() {
  clearTimeout(interviewTimer);
  interviewTimer = 0;
  const now = Date.now();
  const records = Object.entries(track)
    .filter(([, rec]) => rec.stage === "interview" && interviewTime(rec))
    .map(([id, rec]) => ({ id, at: interviewTime(rec) }));
  if (!records.length) return;
  const upcoming = records
    .flatMap(({ at }) => [at - INTERVIEW_SOON_MS, at, at + HUD_LIVE_MS, at + INTERVIEW_GRACE_MS])
    .filter((time) => time > now);
  if (!upcoming.length) return;
  const next = Math.min(nextLocalMidnight(), ...upcoming);
  interviewTimer = setTimeout(() => {
    interviewTimer = 0;
    const stamp = Date.now();
    const soon = records.filter(({ at }) => Math.abs(stamp - (at - INTERVIEW_SOON_MS)) < 2500);
    const started = records.filter(({ at }) => Math.abs(stamp - at) < 2500);
    const ended = records.filter(({ at }) => Math.abs(stamp - (at + INTERVIEW_GRACE_MS)) < 2500);
    document.dispatchEvent(new CustomEvent("interviewchange"));
    if (!toastUndo) {
      const jobTitle = (jobId) => (state.data?.jobs || []).find((job) => job.id === jobId)?.title || "";
      const hrefOf = (id) => `#/jobs/${encodeURIComponent(id)}`;
      if (soon.length && !started.length) {
        const title = soon.length === 1 ? jobTitle(soon[0].id) : "";
        const prepDone = soon.length === 1 ? interviewPrepDone(track[soon[0].id]) : 0;
        const text = soon.length === 1
          ? `面试提醒 · 30 分钟后${title ? ` · ${title}` : ""}${prepDone ? ` · 准备 ${prepDone}/${PREP_TOTAL}` : ""}`
          : `${soon.length} 场面试 30 分钟后开始`;
        deliverTimedReminder(text, "info", {
          title: "面试 30 分钟后",
          body: title ? `${title}${prepDone ? ` · 准备 ${prepDone}/${PREP_TOTAL}` : ""}` : `${soon.length} 场面试即将开始`,
          href: soon.length === 1 ? hrefOf(soon[0].id) : "",
        });
      } else if (started.length) {
        const title = started.length === 1 ? jobTitle(started[0].id) : "";
        deliverTimedReminder(started.length === 1 ? `面试开始${title ? ` · ${title}` : ""}` : `${started.length} 场面试开始`, "info", {
          title: "面试开始",
          body: title || `${started.length} 场面试开始`,
          href: started.length === 1 ? hrefOf(started[0].id) : "",
        });
      } else if (ended.length) {
        const title = ended.length === 1 ? jobTitle(ended[0].id) : "";
        deliverTimedReminder(ended.length === 1
          ? `面试结束${title ? ` · ${title}` : ""} · 记得记录反馈`
          : `${ended.length} 场面试结束 · 记得记录反馈`, "info", {
          title: "面试结束",
          body: title ? `${title} · 记得记录反馈` : `${ended.length} 场面试结束 · 记得记录反馈`,
          href: ended.length === 1 ? hrefOf(ended[0].id) : "",
        });
      }
    }
    scheduleInterviewWake();
  }, Math.max(250, next - now));
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  if (Object.values(track).some((rec) => rec.stage === "interview" && interviewTime(rec))) {
    document.dispatchEvent(new CustomEvent("interviewchange"));
  }
  if (Object.values(track).some((rec) => rec.stage === "offer" && offerDeadline(rec))) {
    document.dispatchEvent(new CustomEvent("offerchange"));
  }
  scheduleInterviewWake();
  scheduleOfferWake();
});

let offerTimer = 0;

function scheduleOfferWake() {
  clearTimeout(offerTimer);
  offerTimer = 0;
  const now = Date.now();
  const records = Object.entries(track)
    .filter(([, rec]) => rec.stage === "offer" && offerDeadline(rec))
    .map(([id, rec]) => ({ id, at: offerDeadline(rec) }));
  if (!records.length) return;
  const upcoming = records.flatMap(({ at }) => [at - DAY_MS, at]).filter((time) => time > now);
  if (!upcoming.length) return;
  const next = Math.min(nextLocalMidnight(), ...upcoming);
  offerTimer = setTimeout(() => {
    offerTimer = 0;
    const stamp = Date.now();
    const soon = records.filter(({ at }) => Math.abs(stamp - (at - DAY_MS)) < 2500);
    const ended = records.filter(({ at }) => Math.abs(stamp - at) < 2500);
    document.dispatchEvent(new CustomEvent("offerchange"));
    if (!toastUndo) {
      const jobTitle = (jobId) => (state.data?.jobs || []).find((job) => job.id === jobId)?.title || "";
      const hrefOf = (id) => `#/jobs/${encodeURIComponent(id)}`;
      if (ended.length) {
        const title = ended.length === 1 ? jobTitle(ended[0].id) : "";
        deliverTimedReminder(ended.length === 1
          ? `Offer 答复截止已到${title ? ` · ${title}` : ""} · 记得回复或记录结果`
          : `${ended.length} 个 Offer 已到答复截止`, "warn", {
          title: "Offer 答复截止已到",
          body: title ? `${title} · 记得回复或记录结果` : `${ended.length} 个 Offer 已到答复截止`,
          href: ended.length === 1 ? hrefOf(ended[0].id) : "",
        });
      } else if (soon.length) {
        const title = soon.length === 1 ? jobTitle(soon[0].id) : "";
        deliverTimedReminder(soon.length === 1
          ? `Offer 明天截止${title ? ` · ${title}` : ""} · 记得回复`
          : `${soon.length} 个 Offer 明天截止`, "info", {
          title: "Offer 明天截止",
          body: title ? `${title} · 记得回复` : `${soon.length} 个 Offer 明天截止`,
          href: soon.length === 1 ? hrefOf(soon[0].id) : "",
        });
      }
    }
    scheduleOfferWake();
  }, Math.max(250, next - now));
}

function daysSince(rec) {
  const at = Date.parse(rec?.followed || rec?.at);
  return Number.isFinite(at) ? Math.max(0, Math.floor((Date.now() - at) / DAY_MS)) : 0;
}

function followedAgo(rec) {
  if (!Number.isFinite(Date.parse(rec?.followed || rec?.at))) return "";
  const days = daysSince(rec);
  return days === 0 ? "今天" : days === 1 ? "昨天" : `${days} 天前`;
}

function trackStampText(rec) {
  if (!rec) return "LOCAL · 仅本机";
  const last = isTerminalStage(rec.stage) || followupReason(rec) ? "" : followedAgo(rec);
  return `更新于 ${stageTime(rec)}${last ? ` · 上次跟进 ${last}` : ""}`;
}

function followupDue(rec) {
  if (!rec || snoozeEnd(rec)) return false;
  const days = daysSince(rec);
  return rec.stage === "offer" || rec.stage === "interview"
    || (rec.stage === "applied" && days >= 7) || (rec.stage === "todo" && days >= 3);
}

function followupReason(rec) {
  if (!rec || snoozeEnd(rec)) return "";
  const days = daysSince(rec);
  const age = days ? `${days} 天前更新` : "今天更新";
  if (rec.stage === "offer") {
    const deadline = offerDeadlineShort(rec);
    return deadline ? `Offer ${deadline} · ${age}` : `Offer 待回复 · ${age}`;
  }
  if (rec.stage === "interview") {
    const at = interviewTime(rec);
    if (!at) return `面试进行中 · ${age}`;
    const phase = interviewPhase(rec);
    if (phase === "live") return `面试进行中 · ${interviewClock(rec)} 开始`;
    if (phase === "past") return "面试已过 · 待反馈";
    return `面试 ${interviewStamp(rec)} · ${interviewCountdown(rec)}${interviewSoon(rec) ? " · 30 分钟内" : ""}`;
  }
  if (rec.stage === "applied" && days >= 7) return `投递 ${days} 天未跟进`;
  if (rec.stage === "todo" && days >= 3) return `待投 ${days} 天未启动`;
  return "";
}

function syncNavDue() {
  const badge = $("#nav-jobs-due");
  if (!badge) return;
  const count = (state.data?.jobs || []).filter((job) => followupDue(trackOf(job.id))).length;
  badge.hidden = count === 0;
  badge.textContent = count > 9 ? "9+" : String(count);
  if (count) badge.title = `${count} 个岗位待跟进`;
  else badge.removeAttribute("title");
  const tab = badge.closest(".tab");
  if (tab) {
    if (count) tab.setAttribute("aria-label", `岗位，${count} 个待跟进`);
    else tab.removeAttribute("aria-label");
  }
}

const FOLLOWUP_ORDER = { offer: 0, interview: 1, applied: 2, todo: 3 };
const FOLLOWUP_ICON = { offer: "star", interview: "chat", applied: "check", todo: "clock" };

function actionQueue(jobs, limit = 4) {
  const items = [];
  (jobs || []).forEach((job) => {
    const rec = trackOf(job.id);
    const reason = followupReason(rec);
    if (!reason) return;
    items.push({
      job,
      rec,
      days: daysSince(rec),
      reason,
      order: FOLLOWUP_ORDER[rec.stage] ?? 4,
      iconName: FOLLOWUP_ICON[rec.stage] || "clock",
    });
  });
  const nextInterview = (rec) => {
    const at = interviewTime(rec);
    return at && at + INTERVIEW_GRACE_MS >= Date.now() ? at : Infinity;
  };
  const offerDeadlineOf = (rec) => (rec?.stage === "offer" ? offerDeadline(rec) || Infinity : Infinity);
  items.sort((a, b) => {
    if (a.order !== b.order) return a.order - b.order;
    // 同是 Offer 时先回复临近截止的，没设截止的排在后面
    if (a.order === FOLLOWUP_ORDER.offer) {
      const ao = offerDeadlineOf(a.rec);
      const bo = offerDeadlineOf(b.rec);
      if (ao !== bo) return ao - bo;
    }
    const ai = nextInterview(a.rec);
    const bi = nextInterview(b.rec);
    if (ai !== bi) {
      if (ai === Infinity) return 1;
      if (bi === Infinity) return -1;
      return ai - bi;
    }
    return b.days - a.days;
  });
  return limit == null ? items : items.slice(0, limit);
}

function actionMarkdown(items) {
  if (!items.length) return "";
  return [
    "# 今日行动",
    "",
    ...items.map(({ job, rec, reason }) =>
      `- [ ] ${reason} · ${job.title} @ ${job.company || "—"}（${stageMeta(rec.stage).label}）`),
    "",
    `> 生成于 ${new Date().toLocaleString("zh-CN")} · 来自本机跟进记录`,
  ].join("\n");
}

const RISK_LABELS = {
  lawsuit: "诉讼", abnormal: "经营异常", executed: "被执行", dishonest: "失信",
  punishment: "行政处罚", penalty: "处罚", equity: "股权冻结",
};

// JD 经常被平台压成一段：在这里按常见小标题、编号和元信息还原结构
const JD_HEADINGS = [
  "主要职责", "工作职责", "岗位职责", "职位职责", "职责描述", "工作内容",
  "职位描述", "岗位描述", "任职要求", "岗位要求", "任职资格", "任职条件",
  "职位要求", "加分项", "其他说明", "福利待遇", "岗位福利",
];
const JD_META_KEYS = [...new Set([
  "招聘截止时间", "工作地点", "工作城市", "经验要求", "学历要求", "薪资范围",
  "薪资待遇", "招聘人数", "工作周期", "每周工期", "工作时间", "工作时段",
  "结算方式", "截止时间", "薪资", "地址", "地点", "经验", "学历",
])].sort((a, b) => b.length - a.length);
const JD_HEAD_SRC = JD_HEADINGS.join("|");
const JD_META_SRC = JD_META_KEYS.join("|");
const JD_HEAD_BREAK = new RegExp(`([^\\n])\\s*(?=(?:${JD_HEAD_SRC})(?:\\s*[:：]|\\s))`, "g");
const JD_NUM_BREAK = /([^\n])\s*(?=\d{1,2}[.、)）](?!\d))/g;
const JD_HEAD_LINE = new RegExp(`^(${JD_HEAD_SRC})\\s*[:：]?\\s*([\\s\\S]*)$`);
const JD_NUM_LINE = /^(\d{1,2}[.、)）])(?!\d)\s*([\s\S]+)$/;
const JD_META_RE = new RegExp(`(${JD_META_SRC})\\s*[:：]\\s*([\\s\\S]*?)(?=\\s+(?:${JD_META_SRC})\\s*[:：]|$)`, "g");

function jdTokens(text) {
  const normalized = String(text || "")
    .replace(/\r\n?/g, "\n")
    .replace(JD_HEAD_BREAK, "$1\n")
    .replace(JD_NUM_BREAK, "$1\n")
    .trim();
  if (!normalized) return [];
  const tokens = [];
  const pushLine = (line) => {
    const num = line.match(JD_NUM_LINE);
    if (num) { tokens.push({ type: "li", mark: num[1], text: num[2] }); return; }
    const bullet = line.match(/^[•·\-–—]\s*([\s\S]+)$/);
    if (bullet) { tokens.push({ type: "li", mark: "•", text: bullet[1] }); return; }
    JD_META_RE.lastIndex = 0;
    const matches = [...line.matchAll(JD_META_RE)];
    if (matches.length && matches.every((m) => m[2].trim().length <= 42)) {
      const prefix = line.slice(0, matches[0].index).trim();
      if (prefix) tokens.push({ type: "p", text: prefix });
      matches.forEach((m) => tokens.push({ type: "meta", key: m[1], value: m[2].trim() }));
      return;
    }
    tokens.push({ type: "p", text: line });
  };
  normalized.split("\n").map((line) => line.trim()).filter(Boolean).forEach((line) => {
    const head = line.match(JD_HEAD_LINE);
    if (head) {
      tokens.push({ type: "head", text: head[1] });
      const rest = head[2].trim();
      if (rest) pushLine(rest);
      return;
    }
    pushLine(line);
  });
  return tokens;
}

function formatJobDescription(text) {
  if (!String(text || "").trim()) return `<div class="jd-empty">（未采集到 JD 正文）</div>`;
  const tokens = jdTokens(text);
  let html = "";
  let open = null;
  const close = () => {
    if (!open) return;
    html += open === "list" ? "</ul>" : "</div>";
    open = null;
  };
  tokens.forEach((token) => {
    if (token.type === "meta") {
      if (open !== "meta") { close(); html += `<div class="jd-meta">`; open = "meta"; }
      html += `<span class="jd-meta-item"><b>${esc(token.key)}</b><span>${esc(token.value)}</span></span>`;
      return;
    }
    if (token.type === "li") {
      if (open !== "list") { close(); html += `<ul class="jd-list">`; open = "list"; }
      html += `<li><i>${esc(token.mark)}</i><span>${esc(token.text)}</span></li>`;
      return;
    }
    close();
    if (token.type === "head") html += `<h4 class="jd-sec">${esc(token.text)}</h4>`;
    else html += `<p>${esc(token.text)}</p>`;
  });
  close();
  return `<div class="jd">${html}</div>`;
}

function buildInterviewBrief(job, detail, rec) {
  const company = job.company && typeof job.company === "object" ? job.company : { name: job.company };
  const score = (detail && detail.score) || {};
  const basic = (detail && detail.basic) || {};
  const risk = (detail && detail.risk) || {};
  const dispatch = (detail && detail.labor_dispatch) || {};
  const dims = Array.isArray(score.dimensions)
    ? score.dimensions.map((d) => `${d.name} ${fmt(d.score, 0)}`).join(" · ")
    : Object.entries(score.dimensions || {}).map(([name, value]) => `${name} ${fmt(value, 0)}`).join(" · ");
  const lines = [];

  lines.push(`# 面试简报 · ${job.title || "岗位"}`, "");
  lines.push(`> ${company.name || "—"} · ${job.salary || "薪资面议"} · ${job.city || "城市未知"} · 生成于 ${new Date().toLocaleString("zh-CN")}`, "");

  lines.push("## 岗位");
  lines.push(`- 薪资：${job.salary || "—"}`);
  lines.push(`- 地点：${job.city || "—"}${job.district ? ` ${job.district}` : ""}`);
  lines.push(`- 要求：${job.experience || "—"} · ${job.degree || "—"}`);
  if ((job.skills || []).length) lines.push(`- 技能：${job.skills.slice(0, 10).join("、")}`);
  if (job.source && job.source.url) lines.push(`- 原帖：${job.source.url}`);
  lines.push("");

  if (rec) {
    lines.push("## 我的跟进");
    lines.push(`- 阶段：${stageMeta(rec.stage).label}（更新于 ${stageTime(rec)}）`);
    const path = trackHistorySummary(rec, 5);
    if (path) lines.push(`- 轨迹：${path}`);
    if (rec.note) lines.push(`- 备注：${rec.note.replace(/\r?\n/g, " ")}`);
    lines.push("");
  }

  lines.push("## 公司背调");
  if (detail) {
    lines.push(`- 总分：${score.total != null ? `${fmt(score.total, 1)}${score.grade ? `（${score.grade}）` : ""}${score.verdict ? ` — ${score.verdict}` : ""}` : "暂无评分"}`);
    if (dims) lines.push(`- 五维：${dims}`);
    const reg = [basic.reg_status, basic.industry, basic.reg_capital, basic.reg_location].filter(Boolean);
    if (reg.length) lines.push(`- 工商：${reg.join(" · ")}`);
    const dispatchState = dispatch.is_labor_dispatch === true ? "疑似派遣/外包"
      : dispatch.is_labor_dispatch === false ? "未发现派遣迹象" : "无法判断";
    lines.push(`- 派遣：${dispatchState}${dispatch.reason ? ` — ${dispatch.reason}` : ""}`);
    const counts = Object.entries(risk.counts || {});
    if (counts.length) {
      lines.push(`- 风险：${counts.map(([name, count]) => `${name} ${count}`).join(" · ")}`);
    } else if ((risk.items || []).length) {
      const types = [...new Set(risk.items.map((item) => RISK_LABELS[item.risk_type] || item.risk_type).filter(Boolean))];
      lines.push(`- 风险：${risk.items.length} 条记录${types.length ? `（${types.join("、")}）` : ""}`);
    } else {
      lines.push("- 风险：暂无记录");
    }
    lines.push(`- 负面证据：${Number(risk.evidence_negative || 0)} 条`);
  } else {
    lines.push("- 未关联到公司背调数据");
  }
  lines.push("");

  const reviews = Object.entries((detail && detail.reviews) || {}).flatMap(([source, items]) =>
    (items || []).map((item) => ({ source, ...item })));
  if (reviews.length) {
    lines.push("## 口碑摘要");
    reviews.sort((a, b) => (Number(a.sentiment ?? 0) - Number(b.sentiment ?? 0))
      || String(b.published_at || "").localeCompare(String(a.published_at || "")));
    reviews.slice(0, 4).forEach((review) => {
      const tone = review.sentiment == null ? "" : (review.sentiment < 0 ? "负面 · " : review.sentiment > 0 ? "正面 · " : "中性 · ");
      const meta = [review.source, review.published_at ? String(review.published_at).slice(0, 10) : ""].filter(Boolean).join(" · ");
      lines.push(`- ${tone}${review.title || "(无标题)"}${meta ? `（${meta}）` : ""}`);
      const snippet = String(review.snippet || "").replace(/\s+/g, " ").trim();
      if (snippet && snippet !== String(review.title || "").trim()) {
        lines.push(`  ${snippet.slice(0, 100)}${snippet.length > 100 ? "…" : ""}`);
      }
    });
    lines.push("");
  }

  if (job.fit) {
    lines.push("## 适配度");
    lines.push(`- 总分：${job.fit.total != null ? fmt(job.fit.total, 1) : "—"}${job.fit.grade ? `（${job.fit.grade}）` : ""}`);
    const fitDims = Object.entries(job.fit.dimensions || {}).map(([name, value]) => `${name} ${fmt(value, 0)}`).join(" · ");
    if (fitDims) lines.push(`- 维度：${fitDims}`);
    if (job.fit.verdict) lines.push(`- 说明：${job.fit.verdict}`);
    if ((job.fit.advice || []).length) lines.push(`- 建议：${job.fit.advice.join("；")}`);
    const fitWhen = job.fit.at ? stageTime({ at: job.fit.at }) : "";
    const fitBase = job.fit.resume_id ? `简历 #${job.fit.resume_id}` : "未记录简历版本";
    lines.push(`- 来源：${fitWhen ? `${fitWhen} · ` : ""}基于${fitBase}${job.fit.resume_state === "stale" ? "（母版已变化，分数可能过期）" : ""}`);
    lines.push("");
  }

  const coverage = skillCoverage(job.skills || []);
  if (coverage) {
    lines.push("## 简历技能对照");
    lines.push(`- 覆盖：${coverage.covered.length}/${coverage.list.length}${coverage.missing.length ? ` · 缺口 ${coverage.missing.length} 项` : " · 无缺口"}`);
    if (coverage.covered.length) lines.push(`- 已写进母版：${coverage.covered.join("、")}`);
    if (coverage.missing.length) lines.push(`- 待补：${coverage.missing.join("、")}`);
    lines.push("");
  }

  lines.push("## 面试前检查");
  lines.push(`- [ ] ${job.source && job.source.url ? "打开原帖确认岗位仍在招" : "核对岗位是否仍在招"}`);
  lines.push((job.skills || []).length
    ? `- [ ] 准备与「${job.skills.slice(0, 3).join(" / ")}」相关的项目案例`
    : "- [ ] 准备 2-3 个与 JD 相关的项目案例");
  lines.push("- [ ] 根据背调记录准备 1-2 个反问");
  lines.push("- [ ] 确认面试时间与联系人（见跟进备注）");
  return lines.join("\n");
}

const followupKind = (rec) => {
  if (!rec || rec.stage === "todo") return "打招呼话术";
  if (rec.stage === "offer") return "回复话术";
  if (isTerminalStage(rec.stage)) return "";
  return "跟进话术";
};
const followupLabel = (rec) => {
  const kind = followupKind(rec);
  return kind ? `复制${kind}` : "";
};

function followupMessage(job, rec) {
  if (rec && isTerminalStage(rec.stage)) return "";
  const title = job?.title || "该岗位";
  const company = job?.company && typeof job.company === "object" ? job.company.name : job?.company;
  const hello = company ? `${company} 招聘团队您好` : "您好";
  const at = Date.parse(rec?.at || "");
  const dateText = Number.isFinite(at)
    ? `${new Date(at).getMonth() + 1} 月 ${new Date(at).getDate()} 日` : "";
  const stage = rec?.stage || "todo";
  let body;
  if (stage === "applied") {
    body = `我${dateText ? `在 ${dateText}` : "近期"}投递了「${title}」岗位，想跟进一下简历筛选进度。如需补充作品或项目材料，请随时告诉我。谢谢！`;
  } else if (stage === "interview") {
    body = `我${dateText ? `在 ${dateText}` : "最近"}参加了「${title}」岗位的面试，感谢上次的沟通。想确认一下后续流程和时间安排；如需补充材料，请随时联系我。谢谢！`;
  } else if (stage === "offer") {
    body = `感谢贵司发放「${title}」岗位的 Offer。我想进一步确认入职时间、薪资结构与试用期安排，方便时请回复，谢谢！`;
  } else {
    body = `我在招聘平台看到「${title}」岗位${job?.city ? `（${job.city}）` : ""}，和我的经历比较匹配，想进一步了解岗位职责与团队情况。方便时请回复，谢谢！`;
  }
  const name = String(state.resume?.resume?.content?.name || "").trim();
  return `${hello}，${body}${name ? `\n\n${name}` : ""}`;
}

async function copyText(text) {
  if (window.api.clipboardWrite) {
    try {
      const res = await window.api.clipboardWrite(text);
      if (res && res.ok) return;
    } catch {
      // 桥不可用时继续尝试浏览器剪贴板
    }
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // 剪贴板权限被拒时退回 execCommand
    }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("copy failed");
}

const tsvCell = (value) => String(value ?? "").replace(/[\t\r\n]+/g, " ").trim();

async function call(action, args) {
  const res = await window.api.call(action, args || {});
  if (res.code !== 0) {
    chatLog("err", action, res.stderr || res.stdout || `退出码 ${res.code}`);
    return null;
  }
  return res.data;
}

// 详情页来回切换很频繁：短缓存减少后端往返，刷新/采集结束会显式清空
const detailCache = new Map();
const detailPending = new Map();
const DETAIL_TTL = 60000;
let detailEpoch = 0;
function cachedDetail(action, args) {
  const key = `${action}:${JSON.stringify(args || {})}`;
  const hit = detailCache.get(key);
  if (hit && Date.now() - hit.at < DETAIL_TTL) return Promise.resolve(hit.data);
  const pending = detailPending.get(key);
  if (pending) return pending;
  const epoch = detailEpoch;
  const request = call(action, args).then((data) => {
    if (data && epoch === detailEpoch) detailCache.set(key, { at: Date.now(), data });
    return data;
  }).finally(() => {
    if (detailPending.get(key) === request) detailPending.delete(key);
  });
  detailPending.set(key, request);
  return request;
}
function prefetchDetail(action, args) {
  const key = `${action}:${JSON.stringify(args || {})}`;
  if (detailCache.has(key) || detailPending.has(key)) return;
  cachedDetail(action, args).catch(() => {});
}
function clearDetailCache() {
  detailEpoch += 1;
  detailCache.clear();
  detailPending.clear();
}

// ---------------------------------------------------------------- 轻提示
let toastTimer = 0;
let toastSeq = 0;
let toastUndo = null;
let toastHide = null;
let toastLeft = 0;
let toastAt = 0;
let toastHoldable = false;
let toastPointer = null;
document.addEventListener("pointermove", (event) => {
  toastPointer = { x: event.clientX, y: event.clientY };
}, { passive: true });
function toastHovered(host) {
  if (!host) return false;
  if (host.matches(":hover")) return true;
  if (!toastPointer) return false;
  const hit = document.elementFromPoint(toastPointer.x, toastPointer.y);
  return !!hit && host.contains(hit);
}
function armToast(ms) {
  clearTimeout(toastTimer);
  toastLeft = ms;
  toastAt = Date.now();
  toastTimer = setTimeout(() => {
    toastTimer = 0;
    const host = $("#toast-host");
    if (host && (toastHovered(host) || host.contains(document.activeElement))) {
      host.classList.add("holding");
      toastLeft = 0;
      return;
    }
    toastHide?.();
  }, ms);
}
function holdToast() {
  if (!toastHoldable || !toastHide || !toastTimer) return;
  clearTimeout(toastTimer);
  toastTimer = 0;
  toastLeft = Math.max(0, toastLeft - (Date.now() - toastAt));
  $("#toast-host")?.classList.add("holding");
}
function releaseToast() {
  if (!toastHide || toastTimer) return;
  $("#toast-host")?.classList.remove("holding");
  armToast(Math.max(toastLeft, 900));
}
function toast(message, tone = "ok", action = null) {
  let host = $("#toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast-host";
    host.setAttribute("role", "status");
    host.setAttribute("aria-live", "polite");
    const resumeIfFree = () => {
      if (!toastHovered(host) && !host.contains(document.activeElement)) releaseToast();
    };
    host.addEventListener("pointerenter", holdToast);
    host.addEventListener("pointerleave", resumeIfFree);
    host.addEventListener("focusin", holdToast);
    host.addEventListener("focusout", (event) => {
      if (!host.contains(event.relatedTarget)) resumeIfFree();
    });
    document.body.appendChild(host);
  }
  const seq = ++toastSeq;
  const life = action ? 5000 : tone === "info" ? 6000 : 1800;
  toastUndo = null;
  toastHide = null;
  toastHoldable = !!action;
  host.classList.remove("holding");
  host.innerHTML = `<div class="toast ${tone}${action ? " has-action" : ""}" style="--toast-life:${life}ms">${icon(tone === "warn" ? "alert" : tone === "info" ? "refresh" : "check")}<span>${esc(message)}</span>${action ? `<button type="button" class="toast-action" title="撤销（Ctrl+Z）" aria-keyshortcuts="Control+Z">${esc(action.label || "撤销")}</button><i class="toast-life" aria-hidden="true"></i>` : ""}</div>`;
  toastHide = () => {
    if (seq !== toastSeq) return;
    toastHide = null;
    toastHoldable = false;
    host.classList.remove("show", "holding");
    toastUndo = null;
  };
  if (action) {
    const run = () => {
      clearTimeout(toastTimer);
      toastTimer = 0;
      toastHide = null;
      toastHoldable = false;
      toastUndo = null;
      host.classList.remove("show", "holding");
      if (document.activeElement?.classList.contains("toast-action")) document.activeElement.blur();
      action.onClick?.();
      setTimeout(() => { if (!host.classList.contains("show")) host.innerHTML = ""; }, 220);
    };
    toastUndo = run;
    host.querySelector(".toast-action")?.addEventListener("click", run);
  }
  host.classList.add("show");
  armToast(life);
  if (action && (toastHovered(host) || host.contains(document.activeElement))) holdToast();
}

function askConfirm({ title, body, confirmText = "继续", cancelText = "取消", danger = false }) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "confirm-dialog";
    dialog.setAttribute("aria-labelledby", "confirm-title");
    dialog.setAttribute("aria-describedby", "confirm-body");
    dialog.innerHTML = `<form method="dialog">
      <div class="confirm-head">${icon(danger ? "alert" : "info")}<b id="confirm-title">${esc(title)}</b></div>
      <div class="confirm-body" id="confirm-body">${esc(body)}</div>
      <div class="confirm-actions">
        <button type="submit" value="cancel" class="btn btn-ghost btn-sm" autofocus>${esc(cancelText)}</button>
        <button type="submit" value="ok" class="btn btn-sm${danger ? " btn-danger" : ""}">${esc(confirmText)}</button>
      </div>
    </form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("close", () => {
      const ok = dialog.returnValue === "ok";
      dialog.remove();
      resolve(ok);
    }, { once: true });
    dialog.showModal();
  });
}

// ---------------------------------------------------------------- HUD / 外壳
const intText = (v) => (v === null || v === undefined || Number.isNaN(Number(v)))
  ? "—" : Number(v).toLocaleString("en-US");

function specOf(name) {
  return ((state.models && state.models.models) || []).find((m) => m.name === name) || null;
}

function defaultSpecName(kind) {
  const list = ((state.models && state.models.models) || [])
    .filter((m) => m.kind === kind && m.enabled);
  const usable = list.find((m) => m.has_key);
  return (usable || list[0] || {}).name || "";
}

const HUD_NEXT_WINDOW_MS = DAY_MS;
let hudNextKey = "";

function hudNextInterview() {
  const now = Date.now();
  const records = Object.entries(track)
    .filter(([, rec]) => rec.stage === "interview" && interviewTime(rec))
    .map(([id, rec]) => ({ id, rec, at: interviewTime(rec) }));
  const live = records
    .filter(({ at }) => at <= now && now - at <= HUD_LIVE_MS)
    .sort((a, b) => b.at - a.at)[0];
  const upcoming = records
    .filter(({ at }) => at > now && at - now <= HUD_NEXT_WINDOW_MS)
    .sort((a, b) => a.at - b.at)[0];
  return live ? { ...live, live: true } : upcoming ? { ...upcoming, live: false } : null;
}

function hudNextOffer() {
  const now = Date.now();
  return Object.entries(track)
    .filter(([, rec]) => rec.stage === "offer" && offerDeadline(rec) > now && offerDeadline(rec) - now <= 2 * DAY_MS)
    .map(([id, rec]) => ({ id, rec, at: offerDeadline(rec) }))
    .sort((a, b) => a.at - b.at)[0] || null;
}

function syncHudNext() {
  const node = $("#hud-next");
  const local = $("#hud-local");
  if (!node || !local) return;
  const next = hudNextInterview();
  const offer = next ? null : hudNextOffer();
  if (!next && !offer) {
    node.hidden = true;
    local.hidden = false;
    hudNextKey = "";
    return;
  }
  const jobId = next ? next.id : offer.id;
  const job = (state.data?.jobs || []).find((item) => item.id === jobId);
  const title = job?.title || "岗位";
  let key = "";
  let className = "";
  let html = "";
  let titleText = "";
  let aria = "";
  if (next) {
    const stamp = next.live ? interviewClock(next.rec) : `${interviewCountdown(next.rec)} ${interviewClock(next.rec)}`;
    key = `${next.id}:${next.live ? "live" : "next"}:${stamp}`;
    className = `hud-tag hud-next${next.live ? " live" : interviewSoon(next.rec) ? " soon" : ""}`;
    html = `${icon(next.live ? "play" : "clock")}<span>${next.live ? "LIVE" : "NEXT"} ${esc(stamp)}</span>`;
    titleText = next.live
      ? `面试进行中 · ${title} · 打开岗位详情`
      : `下一场面试 · ${title} · ${stamp} · 打开岗位详情`;
    aria = next.live
      ? `面试进行中：${title}，打开岗位详情`
      : `下一场面试：${title}，${stamp}，打开岗位详情`;
  } else {
    const state = offerDeadlineState(offer.rec);
    const stamp = offerDeadlineShort(offer.rec);
    key = `${offer.id}:offer:${state?.stamp || offer.at}`;
    className = `hud-tag hud-next offer${state?.days === 0 ? " soon" : ""}`;
    html = `${icon("star")}<span>OFFER ${esc(stamp)}</span>`;
    titleText = `Offer 答复截止 · ${title} · ${offerDeadlineLabel(offer.rec)} · 打开岗位详情`;
    aria = `Offer 答复截止：${title}，${offerDeadlineLabel(offer.rec)}，打开岗位详情`;
  }
  node.hidden = false;
  local.hidden = true;
  node.href = `#/jobs/${encodeURIComponent(jobId)}`;
  node.className = className;
  node.innerHTML = html;
  node.title = titleText;
  node.setAttribute("aria-label", aria);
  if (key !== hudNextKey) {
    hudNextKey = key;
    node.classList.add("tick");
    setTimeout(() => node.classList.remove("tick"), 320);
  }
}

document.addEventListener("interviewchange", syncHudNext);
document.addEventListener("offerchange", syncHudNext);

function renderHud() {
  const status = state.status || {};
  const db = status.db || {};
  const agents = status.agents || [];
  const models = (state.models && state.models.models) || [];
  const usable = models.filter((m) => m.enabled && m.has_key);
  const enabled = agents.filter((a) => a.enabled !== false).length;
  const set = (id, text, cls) => {
    const node = $(id);
    if (!node) return;
    node.textContent = text;
    if (cls !== undefined) node.className = cls;
  };
  set("#hud-db", status.db ? (db.ok ? "ONLINE" : "OFFLINE") : "—",
      status.db ? (db.ok ? "ok" : "bad") : "");
  set("#hud-jobs", intText(db.jobs));
  set("#hud-companies", intText(db.companies));
  set("#hud-modules", agents.length ? `${enabled}/${agents.length}` : "—");
  set("#hud-models", models.length ? `${usable.length}/${models.length}` : "—");
  const foot = $("#foot-modules");
  if (foot) foot.textContent = agents.length
    ? `${enabled} MODULES ACTIVE`
    : (state.status ? "NO MODULE DATA" : "SYNCING MODULES");
  syncNavDue();
  syncHudNext();
}

function renderTopbar() {
  const known = !!state.status;
  const failed = !known && bootstrapError;
  const status = state.status || {};
  const db = status.db || {};
  const login = status.login || {};
  const models = (state.models && state.models.models) || [];
  const chat = models.find((m) => m.kind === "chat");
  const chatReady = chat && chat.enabled && chat.has_key;
  const box = $("#topbar-right");
  if (!box) return;
  box.innerHTML = `
    <span class="pill ${known ? (db.ok ? "pill-ok" : "pill-bad") : failed ? "pill-bad" : "pill-dim"}">${icon("database")}${known ? (db.ok ? "DB ONLINE" : "DB OFFLINE") : failed ? "DB 读取失败" : "DB 检查中"}</span>
    <span class="pill ${known ? "" : failed ? "pill-bad" : "pill-dim"}">${icon("check")}${known ? `登录 ${Object.keys(login).length}` : failed ? "登录 未知" : "登录 …"}</span>
    <span class="pill ${known && chatReady ? "pill-cyan" : failed ? "pill-bad" : "pill-dim"}">${icon("layers")}CHAT ${known ? (chat ? esc(chat.name) : "未配置") : failed ? "读取失败" : "…"}</span>
    <button class="btn btn-ghost btn-xs" id="btn-palette" title="搜索岗位 / 公司，或跳转页面（Ctrl+K）">${icon("search")}搜索 <kbd class="kbd">Ctrl K</kbd></button>
    <button class="btn btn-ghost btn-xs" id="btn-shell-refresh" title="重新读取数据库与配置">${icon("refresh")}刷新</button>`;
  $("#btn-shell-refresh").addEventListener("click", () => refreshShell(true));
  $("#btn-palette").addEventListener("click", () => window.CommandPalette && window.CommandPalette.toggle());
}

let refreshing = false;
async function refreshShell(withData) {
  if (refreshing) return;
  refreshing = true;
  if (withData) toast("正在刷新数据…", "info");
  try {
    if (withData) {
      // 一次 bootstrap 把数据、筛选项、技能云与简历都换新，避免刷新后覆盖读数凭空消失
      const payload = await call("bootstrap");
      if (!payload) {
        toast("刷新失败，详见对话日志", "warn");
        return;
      }
      if (payload.status) state.status = payload.status;
      if (payload.models) state.models = payload.models;
      if (payload.data) state.data = payload.data;
      if (payload.filters) state.filters = payload.filters;
      if (payload.cloud) state.cloud = payload.cloud;
      if (payload.resume) state.resume = payload.resume;
      bootstrapDone = true;
      bootstrapError = !state.status;
      clearDetailCache();
      const partial = payload.errors && Object.keys(payload.errors).length;
      if (partial) console.warn("refresh 部分数据读取失败", payload.errors);
      renderHud();
      renderTopbar();
      await router();
      toast(partial ? "部分数据刷新失败，详见对话日志" : "数据与配置已刷新", partial ? "warn" : "ok");
      return;
    }
    const [status, models] = await Promise.all([call("status"), call("models")]);
    if (status) state.status = status;
    if (models) state.models = models;
    renderHud();
    renderTopbar();
    await router();
  } finally {
    refreshing = false;
  }
}

// 首屏一次取齐：状态、配置、列表、筛选项、词云与简历共用一次 Python 启动
let bootstrapPromise = null;
let bootstrapDone = false;
let bootstrapError = false;
function loadBootstrap() {
  if (bootstrapDone) return Promise.resolve(null);
  if (!bootstrapPromise) {
    bootstrapPromise = call("bootstrap")
      .then((payload) => {
        if (payload) {
          if (payload.status) state.status = payload.status;
          if (payload.models) state.models = payload.models;
          if (payload.data) state.data = payload.data;
          if (payload.filters) state.filters = payload.filters;
          if (payload.cloud) state.cloud = payload.cloud;
          if (payload.resume) state.resume = payload.resume;
          bootstrapDone = true;
          bootstrapError = !state.status;
          renderHud();
          renderTopbar();
          if (payload.errors && Object.keys(payload.errors).length) {
            console.warn("bootstrap 部分数据读取失败", payload.errors);
          }
        } else {
          bootstrapError = true;
          renderTopbar();
        }
        return payload;
      })
      .finally(() => { bootstrapPromise = null; });
  }
  return bootstrapPromise;
}

let filtersPromise = null;
function loadFilters() {
  if (state.filters) return Promise.resolve(state.filters);
  if (!filtersPromise) {
    filtersPromise = call("filters")
      .then((filters) => {
        if (filters) state.filters = filters;
        return filters;
      })
      .finally(() => { filtersPromise = null; });
  }
  return filtersPromise;
}

function tickClock() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const node = $("#hud-clock");
  if (node) node.textContent = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
tickClock();
setInterval(tickClock, 1000);

// ---------------------------------------------------------------- 路由
const ROUTES = {
  "/": ["概览", pageOverview],
  // 外部链接与旧会话使用 #/overview，保留为概览别名。
  "/overview": ["概览", pageOverview],
  "/jobs": ["岗位", pageJobs],
  "/companies": ["公司", pageCompanies],
  "/compare": ["对比", pageCompare],
  "/job-compare": ["岗位对比", pageJobCompare],
  "/skills": ["技能词云", pageSkills],
  "/resume": ["简历", pageResume],
  "/modules": ["模块", pageModules],
  "/settings": ["设置", pageSettings],
};

function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query] = raw.split("?");
  return { path, params: Object.fromEntries(new URLSearchParams(query || "")) };
}
const go = (hash) => { location.hash = hash; };

// 详情路径来自外部链接或旧通知，坏编码不应该把页面炸成异常堆栈。
function decodeRoutePart(value) {
  try { return decodeURIComponent(value); } catch { return null; }
}
const emptyWithAction = (text, href, label) =>
  `<div class="empty">${esc(text)}<a class="btn btn-ghost btn-sm empty-action" href="${esc(href)}">${esc(label)}</a></div>`;

const APP_TITLE = "SWARM 求职背调工作台";
const ROUTE_TITLES = {
  "/": "总览", "/jobs": "岗位", "/companies": "公司", "/compare": "对比",
  "/job-compare": "岗位对比", "/skills": "技能", "/resume": "简历",
  "/modules": "模块", "/settings": "设置",
};
function setPageTitle(text) {
  const clean = String(text || "").replace(/\s+/g, " ").trim().slice(0, 48);
  document.title = clean ? `${clean} · ${APP_TITLE}` : `SWARM · 求职背调工作台`;
}
function currentPageTitle(path) {
  const heading = document.querySelector("#page .page-title")?.textContent
    || document.querySelector("#page .detail-name h1")?.textContent
    || "";
  const clean = heading.replace(/\s+/g, " ").trim();
  if (clean) return clean;
  if (path.startsWith("/jobs/")) return "岗位";
  if (path.startsWith("/companies/")) return "公司";
  return ROUTE_TITLES[path] || "总览";
}
// 记住进入详情前的列表筛选，返回时不用重新设条件
function rememberList() {
  const hash = location.hash;
  if (!/^#\/companies(\?|$)/.test(hash) && !/^#\/jobs(\?|$)/.test(hash)) return;
  try {
    sessionStorage.setItem("swarm.back", hash);
    sessionStorage.setItem("swarm.back.y", String(window.scrollY));
    const row = document.activeElement?.closest?.("tr[data-company], tr[data-job]");
    const focusKey = row && row.matches(":focus-visible")
      ? (row.dataset.company ? "company:" + row.dataset.company : "job:" + row.dataset.job)
      : "";
    if (focusKey) sessionStorage.setItem("swarm.back.focus", focusKey);
    else sessionStorage.removeItem("swarm.back.focus");
  } catch { /* 忽略存储失败 */ }
}
function backHash(fallback) {
  try { return sessionStorage.getItem("swarm.back") || fallback; } catch { return fallback; }
}
const JOB_ORDER_KEY = "swarm.jobs.order";
function saveJobOrder(ids) {
  try { sessionStorage.setItem(JOB_ORDER_KEY, JSON.stringify(ids.slice(0, 500))); } catch { /* 忽略存储失败 */ }
}
function jobOrder() {
  try {
    const ids = JSON.parse(sessionStorage.getItem(JOB_ORDER_KEY) || "[]");
    if (!Array.isArray(ids)) return [];
    const clean = ids.filter((id) => typeof id === "string" && id);
    const known = new Set((state.data?.jobs || []).map((job) => job.id));
    return known.size ? clean.filter((id) => known.has(id)) : clean;
  } catch { return []; }
}
function takeBackScroll() {
  try {
    if (sessionStorage.getItem("swarm.back") !== location.hash) {
      sessionStorage.removeItem("swarm.back.focus");
      return;
    }
    const y = Number(sessionStorage.getItem("swarm.back.y") || 0);
    const focusKey = sessionStorage.getItem("swarm.back.focus") || "";
    sessionStorage.removeItem("swarm.back.y");
    sessionStorage.removeItem("swarm.back");
    sessionStorage.removeItem("swarm.back.focus");
    if (y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
    if (!focusKey) return;
    const split = focusKey.indexOf(":");
    const kind = focusKey.slice(0, split);
    const id = focusKey.slice(split + 1);
    if (!id || (kind !== "company" && kind !== "job")) return;
    const row = $$(kind === "company" ? "tr[data-company]" : "tr[data-job]")
      .find((node) => node.dataset[kind] === id);
    if (row) requestAnimationFrame(() => row.focus({ preventScroll: true }));
  } catch { /* 忽略存储失败 */ }
}
const goCompany = (k) => { rememberRecent("company", k); rememberList(); go("#/companies/" + encodeURIComponent(k)); };
const goJob = (id) => { rememberRecent("job", id); rememberList(); go("#/jobs/" + encodeURIComponent(id)); };
const goSeries = (k, f) => go(`#/companies/${encodeURIComponent(k)}?series=${encodeURIComponent(f)}`);

function crumb(...parts) {
  const items = parts.map((p, i) =>
    i === parts.length - 1 ? `<b>${esc(p)}</b>` : `${esc(p)}<span class="sep">${icon("chevron")}</span>`);
  $("#crumb").innerHTML = `${icon("home")}${items.join("")}`;
}

let pageAbort = null;
let routeSeq = 0;
let routing = Promise.resolve();
let leaveGuard = null;

function router() {
  const seq = ++routeSeq;
  const run = () => renderRoute(seq);
  routing = routing.then(run, run);
  return routing;
}

let lastRouteKey = null;

async function renderRoute(seq) {
  // 串行化路由：排队期间已有更新的导航时直接跳过，保证 DOM 始终属于最新地址
  if (seq !== routeSeq) return;
  if (leaveGuard) {
    const guard = leaveGuard;
    const ok = await guard.check();
    if (seq !== routeSeq) return;
    if (!ok) {
      try { history.replaceState(null, "", guard.hash()); } catch { /* 忽略不支持的环境 */ }
      return;
    }
    if (leaveGuard === guard) leaveGuard = null;
  }
  if (window.SwarmMap) window.SwarmMap.stop();
  if (pageAbort) pageAbort.abort();
  pageAbort = new AbortController();
  const { path: rawPath, params } = parseHash();
  const companyMatch = rawPath.match(/^\/companies\/(.+)$/);
  const jobMatch = rawPath.match(/^\/jobs\/(.+)$/);
  const known = !!ROUTES[rawPath] || !!companyMatch || !!jobMatch;
  const path = known ? rawPath : "/";
  // 未知地址继续渲染概览会把导航高亮和地址栏留在两个状态，统一归位到根路由。
  if (!known) {
    try { history.replaceState(null, "", "#/"); } catch { /* 忽略不支持的环境 */ }
  }
  const routeKey = path;
  const routeChanged = routeKey !== lastRouteKey;
  lastRouteKey = routeKey;
  let backPending = false;
  try {
    backPending = sessionStorage.getItem("swarm.back") === location.hash
      && sessionStorage.getItem("swarm.back.y") !== null;
  } catch { /* 忽略存储失败 */ }
  if (routeChanged && !backPending) window.scrollTo(0, 0);
  $$("#nav a").forEach((a) => {
    const route = a.dataset.route;
    const active = route === "/"
      ? path === "/" || path === "/overview"
      : route === path || path.startsWith(route);
    a.classList.toggle("active", active);
  });
  // 先给窗口一个正确分区标题，详情/设置再异步细化，避免慢查询期间沿用上一页标题。
  setPageTitle(path.startsWith("/jobs/") ? "岗位" : path.startsWith("/companies/") ? "公司" : ROUTE_TITLES[path] || "总览");

  let failed = false;
  try {
    if (companyMatch) {
      const key = decodeRoutePart(companyMatch[1]);
      crumb("公司", "详情");
      if (key == null) pageEl().innerHTML = emptyWithAction("公司地址无法解析", "#/companies", "返回公司列表");
      else await pageCompanyDetail(key, params);
    } else if (jobMatch) {
      const id = decodeRoutePart(jobMatch[1]);
      crumb("岗位", "详情");
      if (id == null) pageEl().innerHTML = emptyWithAction("岗位地址无法解析", "#/jobs", "返回岗位列表");
      else await pageJobDetail(id);
    } else {
      const entry = ROUTES[path];
      crumb("SWARM", entry[0]);
      await entry[1](params);
    }
  } catch (exc) {
    failed = true;
    pageEl().innerHTML = emptyWithAction(`页面出错：${exc.message || "未知错误"}`, "#/", "回到概览");
  }
  if (seq !== routeSeq) return;
  setPageTitle(failed ? "页面出错" : currentPageTitle(path));
  syncHudNext();
  if (routeChanged) {
    pageEl().classList.remove("route-enter");
    void pageEl().offsetWidth;
    pageEl().classList.add("route-enter");
  }
}
window.addEventListener("hashchange", router);

// 阻止文件被拖到窗口其他位置时 Electron 直接导航到 file://。
document.addEventListener("dragover", (event) => {
  if (event.dataTransfer && [...event.dataTransfer.types].includes("Files")) event.preventDefault();
});
document.addEventListener("drop", (event) => {
  if (!event.dataTransfer || ![...event.dataTransfer.types].includes("Files")) return;
  event.preventDefault();
  if (event.target.closest("#backup-card")) return;
  const file = event.dataTransfer.files && event.dataTransfer.files[0];
  if (!file) return;
  if (!/\.json$/i.test(file.name) && file.type !== "application/json") {
    toast("只支持拖入 JSON 备份文件", "warn");
    return;
  }
  if (parseHash().path === "/settings") {
    importDroppedBackup(file);
    return;
  }
  droppedBackupFile = file;
  if (window.CommandPalette) window.CommandPalette.close();
  go("#/settings");
  toast(`正在打开设置以导入 ${file.name}`, "info");
});

// 键盘：Ctrl/Cmd+1..7 直达页签；Esc 收起抽屉。Ctrl+K 由 command.js 接管。
const ROUTE_ORDER = ["/", "/jobs", "/companies", "/skills", "/resume", "/modules", "/settings"];

function bindSearchClear(input) {
  if (!input) return;
  const button = input.parentElement.querySelector("[data-search-clear]");
  if (!button) return;
  const sync = () => { button.hidden = input.value.length === 0; };
  sync();
  input.addEventListener("input", sync);
  button.addEventListener("click", () => {
    if (!input.value) return;
    input.value = "";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  });
}

function stepJob(delta) {
  if (!/^#\/jobs(?:\?|$)/.test(backHash(""))) return false;
  const match = parseHash().path.match(/^\/jobs\/(.+)$/);
  if (!match) return false;
  const id = decodeURIComponent(match[1]);
  const order = jobOrder();
  const pos = order.indexOf(id);
  const target = pos >= 0 ? order[pos + delta] : null;
  if (!target) return false;
  goJob(target);
  window.scrollTo(0, 0);
  return true;
}

function listKeyboardContext() {
  const { path } = parseHash();
  if (path === "/jobs") {
    const board = $("#job-board");
    return { card: $("#job-table-card"), search: $("#l-job-q"), row: board && !board.hidden ? ".board-card" : "tr[data-job]" };
  }
  if (path === "/companies") {
    return { card: $("#company-table-card"), search: $("#l-company-q"), row: "tr[data-company]" };
  }
  return null;
}

document.addEventListener("keydown", (event) => {
  if (event.key === "?" && !event.ctrlKey && !event.metaKey && !event.altKey
      && !document.documentElement.classList.contains("palette-open")) {
    const typing = event.target.closest?.("input, select, textarea, [contenteditable='true']");
    if (!typing) {
      event.preventDefault();
      toggleKeysheet();
      return;
    }
  }
  const sheet = $("#keysheet");
  if (sheet && !sheet.hidden) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeKeysheet();
    }
    return;
  }
  if (event.altKey) return;
  if (event.shiftKey && !/^[wt]$/i.test(event.key)) return;
  if ((event.ctrlKey || event.metaKey) && /^[1-7]$/.test(event.key)) {
    event.preventDefault();
    go("#" + ROUTE_ORDER[Number(event.key) - 1]);
    return;
  }
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "z"
      && !document.documentElement.classList.contains("palette-open")
      && $("#chat-drawer").hidden
      && !event.target.closest?.("input, select, textarea, [contenteditable='true']")
      && !document.querySelector("dialog[open]") && toastUndo) {
    event.preventDefault();
    toastUndo();
    return;
  }
  if (event.key === "Escape" && !$("#chat-drawer").hidden) {
    event.preventDefault();
    $("#chat-drawer").hidden = true;
    return;
  }

  if (event.ctrlKey || event.metaKey) return;
  if (document.documentElement.classList.contains("palette-open")) return;
  if (!$("#chat-drawer").hidden) return;
  if ((event.key === "[" || event.key === "]")
      && !event.target.closest?.("input, select, textarea, [contenteditable='true']")) {
    if (stepJob(event.key === "]" ? 1 : -1)) {
      event.preventDefault();
      return;
    }
  }
  if (/^\/jobs\/[^/]+$/.test(parseHash().path) && !event.repeat
      && !event.target.closest?.("input, select, textarea, [contenteditable='true']")
      && !document.querySelector("dialog[open]")) {
    const stageKey = stageShortcut(event.key);
    if (stageKey) {
      const btn = document.querySelector(`[data-set-stage="${stageKey.id}"]`);
      if (btn) {
        event.preventDefault();
        btn.click();
      }
      return;
    }
    const action = {
      w: () => $('#page .page-head [data-watch="job"]')?.click(),
      b: () => $("#btn-brief")?.click(),
      c: () => $("#btn-copy-jd")?.click(),
      m: () => {
        const btn = $("#btn-track-message");
        if (btn && !btn.hidden) { btn.click(); return; }
        const closed = document.querySelector(".stage-btn.on")?.dataset.setStage || "";
        if (isTerminalStage(closed)) {
          toast(`${stageMeta(closed).label}的岗位不需要跟进话术`, "info");
        }
      },
      t: () => {
        const btn = $("#btn-track-touch");
        if (btn && !btn.hidden) { btn.click(); return; }
        const closed = document.querySelector(".stage-btn.on")?.dataset.setStage || "";
        toast(isTerminalStage(closed) ? `${stageMeta(closed).label}的岗位不再提醒跟进` : "先选择阶段，再记录跟进", isTerminalStage(closed) ? "info" : "warn");
      },
      s: () => {
        const btn = $("#btn-track-snooze");
        if (btn && !btn.hidden) { btn.click(); return; }
        const closed = document.querySelector(".stage-btn.on")?.dataset.setStage || "";
        toast(isTerminalStage(closed) ? `${stageMeta(closed).label}的岗位不再提醒跟进` : "先选择阶段，再延后提醒", isTerminalStage(closed) ? "info" : "warn");
      },
      p: () => {
        const block = $("#interview-prep");
        if (!block || block.hidden) {
          toast("先标记为面试阶段，再维护准备清单", "info");
          return;
        }
        const inputs = [...block.querySelectorAll("[data-prep-index]")];
        const next = inputs.find((input) => !input.checked);
        if (!next) {
          toast("面试准备已全部完成", "ok");
          return;
        }
        next.focus({ preventScroll: true });
        next.closest(".prep-item")?.scrollIntoView({ block: "nearest" });
      },
    }[event.key.toLowerCase()];
    if (action) {
      event.preventDefault();
      action();
      return;
    }
  }
  if (/^\/companies\/[^/]+$/.test(parseHash().path) && !event.repeat
      && !event.target.closest?.("input, select, textarea, [contenteditable='true']")
      && !document.querySelector("dialog[open]")) {
    const action = {
      w: () => $('#page .detail-head [data-watch="company"]')?.click(),
      c: () => $("#btn-copy-company")?.click(),
      j: () => $("#company-all-jobs")?.click(),
    }[event.key.toLowerCase()];
    if (action) {
      event.preventDefault();
      action();
      return;
    }
  }
  const ctx = listKeyboardContext();
  if (!ctx || !ctx.card) return;
  if (document.querySelector("dialog[open]")) return;
  const typing = !!event.target.closest("input, select, textarea, [contenteditable='true']");
  const fromSearch = typing && event.target === ctx.search;
  if (!typing && event.key === "/") {
    event.preventDefault();
    if (ctx.search) { ctx.search.focus(); ctx.search.select(); }
    return;
  }
  if (event.key === "Escape" && fromSearch) {
    event.preventDefault();
    if (ctx.search.value) {
      ctx.search.value = "";
      ctx.search.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      ctx.search.blur();
    }
    return;
  }
  const rows = [...ctx.card.querySelectorAll(ctx.row)];
  if (!rows.length) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    if (typing && !fromSearch) return;
    event.preventDefault();
    const current = rows.indexOf(document.activeElement.closest(ctx.row));
    const next = event.key === "ArrowDown"
      ? (current < 0 ? 0 : Math.min(rows.length - 1, current + 1))
      : (current < 0 ? rows.length - 1 : Math.max(0, current - 1));
    rows[next].focus({ preventScroll: true });
    rows[next].scrollIntoView({ block: "nearest" });
    return;
  }
  if (typing) return;
  const stageKey = stageShortcut(event.key);
  if (stageKey) {
    const row = document.activeElement.closest?.(ctx.row);
    if (!row) return;
    const select = row.querySelector("[data-stage-job]");
    if (!select) return;
    const next = stageKey.id;
    if (select.value === next) return;
    event.preventDefault();
    const id = row.dataset.job || row.dataset.company;
    select.value = next;
    select.dispatchEvent(new Event("change", { bubbles: true }));
    const rowsAfter = [...ctx.card.querySelectorAll(ctx.row)];
    const same = rowsAfter.find((item) => (item.dataset.job || item.dataset.company) === id);
    const target = same || rowsAfter[0];
    if (target) {
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: "nearest" });
    } else {
      ctx.search?.focus();
    }
    return;
  }
  if (event.key === "Home" || event.key === "End") {
    event.preventDefault();
    const target = event.key === "Home" ? rows[0] : rows[rows.length - 1];
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: "nearest" });
    return;
  }
  if ((event.key === "v" || event.key === "V") && document.activeElement.closest?.(ctx.row)) {
    const next = $("#job-board")?.hidden ? "board" : "list";
    const btn = document.querySelector(`[data-job-view="${next}"]`);
    if (!btn) return;
    event.preventDefault();
    btn.click();
    return;
  }
  if (event.key === "w" || event.key === "W") {
    const row = document.activeElement.closest?.(ctx.row);
    const btn = row && row.querySelector("[data-watch]");
    if (!btn) return;
    event.preventDefault();
    const kind = row.dataset.company != null ? "company" : "job";
    const id = btn.dataset.watchId;
    btn.click();
    const nextRows = [...ctx.card.querySelectorAll(ctx.row)];
    const same = nextRows.find((item) => item.dataset[kind] === id);
    const target = same || nextRows[0];
    if (target) {
      target.focus({ preventScroll: true });
      if (!same) target.scrollIntoView({ block: "nearest" });
    } else {
      ctx.search?.focus();
    }
    return;
  }
  if ((event.key === "c" || event.key === "C") && (ctx.row === "tr[data-job]" || ctx.row === ".board-card")) {
    const row = document.activeElement.closest?.(ctx.row);
    const link = row?.querySelector(".company-link");
    if (!link || !link.dataset.company) return;
    event.preventDefault();
    goCompany(link.dataset.company);
    return;
  }
  if ((event.key === "i" || event.key === "I") && (ctx.row === "tr[data-job]" || ctx.row === ".board-card")) {
    const row = document.activeElement.closest?.(ctx.row);
    const id = row?.dataset.job;
    if (!id || event.repeat) return;
    event.preventDefault();
    const rec = trackOf(id);
    if (!rec || rec.stage !== "interview") {
      toast(`先用 1–${STAGES.length} 标记为「面试」，再安排时间`, "warn");
      return;
    }
    openInterviewScheduler(id, {
      anchor: row,
      focusAfterSave: () => {
        const selector = `${ctx.row}[data-job="${CSS.escape(id)}"]`;
        document.querySelector(selector)?.focus({ preventScroll: true });
      },
    });
    return;
  }
  if ((event.key === "t" || event.key === "T") && (ctx.row === "tr[data-job]" || ctx.row === ".board-card")) {
    const row = document.activeElement.closest?.(ctx.row);
    const id = row?.dataset.job;
    if (!id || event.repeat) return;
    event.preventDefault();
    const rec = trackOf(id);
    if (!rec) {
      toast(`先按 1–${STAGES.length} 标记阶段，再记录跟进`, "warn");
      return;
    }
    if (isTerminalStage(rec.stage)) {
      toast(`${stageMeta(rec.stage).label}的岗位不再提醒跟进`, "info");
      return;
    }
    const before = snapshotTrack(id);
    if (!touchTrack(id)) return;
    const title = row.querySelector(".link")?.textContent.trim() || "";
    document.dispatchEvent(new CustomEvent("trackchange", { detail: { id } }));
    toast(`已记录本次跟进${title ? ` · ${title}` : ""}`, "ok", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        document.dispatchEvent(new CustomEvent("trackchange", { detail: { id } }));
        toast("已撤销本次跟进", "info");
      },
    });
    return;
  }
  if ((event.key === "s" || event.key === "S") && (ctx.row === "tr[data-job]" || ctx.row === ".board-card")) {
    const row = document.activeElement.closest?.(ctx.row);
    const id = row?.dataset.job;
    if (!id || event.repeat) return;
    event.preventDefault();
    const rec = trackOf(id);
    if (!rec) {
      toast(`先按 1–${STAGES.length} 标记阶段，再延后提醒`, "warn");
      return;
    }
    if (isTerminalStage(rec.stage)) {
      toast(`${stageMeta(rec.stage).label}的岗位不再提醒跟进`, "info");
      return;
    }
    const wasSnoozed = !!snoozeEnd(rec);
    const before = snapshotTrack(id);
    if (wasSnoozed ? !unsnoozeTrack(id) : !snoozeTrack(id)) return;
    const title = row.querySelector(".link")?.textContent.trim() || "";
    document.dispatchEvent(new CustomEvent("trackchange", { detail: { id } }));
    toast(wasSnoozed
      ? `已取消延后${title ? ` · ${title}` : ""}`
      : `已延后 ${SNOOZE_DAYS} 天 · ${snoozeDay(trackOf(id))} 重新提醒${title ? ` · ${title}` : ""}`, "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        document.dispatchEvent(new CustomEvent("trackchange", { detail: { id } }));
        toast(wasSnoozed ? "已恢复延后" : "已撤销延后", "info");
      },
    });
    return;
  }
  if (event.key === "PageDown" || event.key === "PageUp") {
    if (ctx.row === ".board-card") return;
    if (!document.activeElement.closest?.(ctx.row)) return;
    const label = event.key === "PageDown" ? "下一页" : "上一页";
    const btn = ctx.card.querySelector(`.pager button[aria-label="${label}"]:not([disabled])`);
    if (!btn) return;
    event.preventDefault();
    btn.click();
    const nextRows = [...ctx.card.querySelectorAll(ctx.row)];
    const target = event.key === "PageDown" ? nextRows[0] : nextRows.at(-1);
    if (target) target.focus({ preventScroll: true });
  }
});

// ---------------------------------------------------------------- 快捷键面板
const KEY_ROWS = [
  { label: "打开 / 关闭本面板", keys: ["?"] },
  { label: "打开命令面板", keys: ["Ctrl", "K"] },
  { label: "切换页面", keys: ["Ctrl", "1…7"] },
  { label: "撤销最近一次操作", keys: ["Ctrl", "Z"] },
  { label: "聚焦当前列表搜索", keys: ["/"] },
  { label: "在列表行间移动", keys: ["↑", "↓"] },
  { label: "跳到列表首行 / 末行", keys: ["Home", "End"] },
  { label: "打开当前行", keys: ["Enter"] },
  { label: "关注 / 取消关注当前行", keys: ["W"] },
  { label: "列表翻页", keys: ["PgUp", "PgDn"] },
  { label: "岗位详情内上一岗 / 下一岗", keys: ["[", "]"] },
  { label: "岗位详情：快速标记投递阶段", keys: [`1…${STAGES.length}`] },
  { label: "岗位列表：标记焦点行阶段", keys: [`1…${STAGES.length}`] },
  { label: "岗位列表：记录当前行跟进", keys: ["T"] },
  { label: "岗位列表：延后 / 取消延后当前行", keys: ["S"] },
  { label: "岗位列表：打开当前行的公司背调", keys: ["C"] },
  { label: "岗位列表：安排面试时间", keys: ["I"] },
  { label: "岗位列表：切换列表 / 看板视图", keys: ["V"] },
  { label: "看板：在列内 / 跨列移动焦点", keys: ["↑", "↓", "←", "→"] },
  { label: "看板：把当前卡片移到上一列 / 下一列", keys: ["Alt", "←/→"] },
  { label: "岗位详情：关注 / 生成简报 / 复制 JD", keys: ["W", "B", "C"] },
  { label: "岗位详情：复制跟进话术 / 记录本次跟进", keys: ["M", "T"] },
  { label: "岗位详情：延后 / 取消延后", keys: ["S"] },
  { label: "岗位详情：跳到下一项面试准备", keys: ["P"] },
  { label: "公司详情：关注 / 复制摘要 / 查看岗位", keys: ["W", "C", "J"] },
  { label: "关闭弹层 · 搜索中清空 / 退出", keys: ["Esc"] },
];
let keysheetBuilt = false;
let keysheetLastFocus = null;

function buildKeysheet() {
  if (keysheetBuilt) return;
  const host = document.createElement("div");
  host.id = "keysheet";
  host.hidden = true;
  host.innerHTML = `
    <div class="keysheet-scrim" data-keys-close></div>
    <div class="keysheet-panel" role="dialog" aria-modal="true" aria-labelledby="keysheet-title">
      <div class="keysheet-head">
        <span class="keysheet-title" id="keysheet-title">${icon("info")}键盘快捷键</span>
        <button type="button" class="keysheet-close" data-keys-close aria-label="关闭快捷键"><kbd class="kbd">ESC</kbd></button>
      </div>
      <div class="keysheet-grid">
        ${KEY_ROWS.map((row) => `<div class="keysheet-row">
          <span>${esc(row.label)}</span>
          <span class="keysheet-keys">${row.keys.map((key) => `<kbd class="kbd">${esc(key)}</kbd>`).join("")}</span>
        </div>`).join("")}
      </div>
      <div class="keysheet-foot"><span>输入框内不触发快捷键</span><span>? 再次开关</span></div>
    </div>`;
  document.body.appendChild(host);
  host.addEventListener("click", (event) => {
    if (event.target.closest("[data-keys-close]")) closeKeysheet();
  });
  host.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      event.preventDefault();
      host.querySelector(".keysheet-close")?.focus();
    }
  });
  keysheetBuilt = true;
}

function openKeysheet() {
  buildKeysheet();
  keysheetLastFocus = document.activeElement;
  const host = $("#keysheet");
  host.hidden = false;
  document.documentElement.classList.add("keysheet-open");
  host.querySelector(".keysheet-close")?.focus();
}

function closeKeysheet() {
  const host = $("#keysheet");
  if (!host || host.hidden) return;
  const trapped = host.contains(document.activeElement);
  host.hidden = true;
  document.documentElement.classList.remove("keysheet-open");
  // 焦点留在隐藏面板里会让后续 Enter / Tab 落到看不见的按钮上
  if (trapped) document.activeElement.blur();
  if (keysheetLastFocus && typeof keysheetLastFocus.focus === "function" && keysheetLastFocus !== document.body) keysheetLastFocus.focus();
}

function toggleKeysheet() {
  const host = $("#keysheet");
  if (host && !host.hidden) closeKeysheet();
  else openKeysheet();
}

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
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
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
  const list = document.createElement("div");
  list.className = "q-list";
  questions.forEach((question, index) => {
    const item = document.createElement("div");
    item.className = "q-item";
    item.innerHTML = `<div class="q-text"><span class="q-step">${String(index + 1).padStart(2, "0")}</span>${esc(question)}</div>`;
    list.appendChild(item);
  });
  box.appendChild(list);
  const row = document.createElement("div");
  row.className = "chat-compose";
  row.innerHTML = `<input type="text" id="q-input" placeholder="第 1/${questions.length} 问：${esc(questions[0])}">
    <button class="btn btn-sm" id="q-send">${icon("external")}发送</button>
    <button type="button" class="chip" id="q-skip" title="跳过剩余问题；未回答时按规则生成草稿">跳过追问</button>`;
  box.appendChild(row);

  let cursor = 0;
  const answers = [];
  const input = $("#q-input");
  const finish = (skipped) => {
    box.innerHTML = "";
    if (skipped) {
      chatLog("step", "系统", answers.length
        ? `已答 ${answers.length}/${questions.length}，其余跳过`
        : "已跳过追问，将按规则生成未确认草稿");
    } else {
      chatLog("step", "系统", "问题已答完，开始生成");
    }
    onSubmit(answers);
  };
  const send = () => {
    const value = input.value.trim();
    if (!value) { finish(true); return; }
    chatLog("out", "我", `${questions[cursor]} → ${value}`);
    answers.push({ question: questions[cursor], answer: value });
    list.children[cursor]?.classList.add("is-answered");
    cursor += 1;
    input.value = "";
    if (cursor >= questions.length) { finish(false); return; }
    input.placeholder = `第 ${cursor + 1}/${questions.length} 问：${questions[cursor]}`;
    input.focus();
  };
  $("#q-send").addEventListener("click", send);
  $("#q-skip").addEventListener("click", () => finish(true));
  input.addEventListener("keydown", (event) => { if (event.key === "Enter") send(); });
  input.focus();
}

// 采集流不绑在岗位页：句柄放模块级，切走页面后仍能看日志、停止，回来时状态一致。
let crawlRun = null;
const crawlChange = () => document.dispatchEvent(new CustomEvent("crawlchange"));
const CRAWL_FORM_KEY = "swarm.crawl.v1";
const CRAWL_LAST_KEY = "swarm.lastRun.v1";
const CRAWL_LAST_STATUS = { done: "上次", partial: "上次部分", failed: "上次中断", stopped: "上次停止" };
const CRAWL_LAST_TITLE = { done: "上次运行", partial: "上次部分完成", failed: "上次中断", stopped: "上次已停止" };
function readCrawlForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(CRAWL_FORM_KEY) || "null");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : null;
  } catch {
    return null;
  }
}
function readLastCrawl() {
  try {
    const saved = JSON.parse(localStorage.getItem(CRAWL_LAST_KEY) || "null");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return null;
    if (!CRAWL_LAST_STATUS[saved.status] || typeof saved.clock !== "string") return null;
    return saved;
  } catch {
    return null;
  }
}

const hudRun = $("#hud-run");
let hudRunTimer = 0;
function crawlElapsed(startedAt) {
  const sec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
}
// 后端的 done 事件带各阶段计数；进程退出事件没有，缺统计时至少保留岗位总数。
function crawlSummaryParts(summary, jobCount) {
  const info = summary && typeof summary === "object" ? summary : {};
  const count = (value) => {
    const n = Math.round(Number(value));
    return Number.isFinite(n) && n > 0 ? n : null;
  };
  const parts = [];
  const jobs = count(jobCount);
  if (jobs) parts.push(`共 ${jobs} 条岗位`);
  const companies = count(info.companies);
  if (companies) parts.push(`${companies} 家公司`);
  const evidence = count(info.evidence);
  if (evidence) parts.push(`${evidence} 条证据`);
  const fits = count(info.fits);
  if (fits) parts.push(`${fits} 条匹配`);
  if (info.resume && info.resume.ok) {
    parts.push(info.resume.confirmed ? "定向简历已确认" : "定向简历草稿已生成");
  }
  return parts;
}
function crawlLastNote(record) {
  if (!record) return "";
  const count = (value) => {
    const n = Math.round(Number(value));
    return Number.isFinite(n) && n > 0 ? n : null;
  };
  const companies = count(record.summary?.companies);
  const evidence = count(record.summary?.evidence);
  const jobs = count(record.jobs);
  const bits = [];
  if (companies) bits.push(`${companies} 公司`);
  if (evidence) bits.push(`${evidence} 证据`);
  if (!bits.length && jobs) bits.push(`${jobs} 岗位`);
  return `${CRAWL_LAST_STATUS[record.status]} ${record.clock}${bits.length ? ` · ${bits.join(" · ")}` : ""}`;
}
function crawlLastTitle(record) {
  if (!record) return "";
  const facts = crawlSummaryParts(record.summary, record.jobs);
  return `${CRAWL_LAST_TITLE[record.status]} ${record.clock}`
    + (record.elapsed ? ` · 耗时 ${record.elapsed}` : "")
    + (facts.length ? ` · ${facts.join(" · ")}` : "");
}
function syncHudRun() {
  clearInterval(hudRunTimer);
  hudRunTimer = 0;
  if (!hudRun) return;
  if (!crawlRun) {
    hudRun.hidden = true;
    hudRun.classList.remove("stopping");
    return;
  }
  const run = crawlRun;
  hudRun.hidden = false;
  hudRun.classList.toggle("stopping", !!run.stopping);
  const paint = () => {
    hudRun.textContent = `${run.stopping ? "STOPPING" : run.noCrawl ? "RECALC" : "RUNNING"} ${crawlElapsed(run.startedAt)}`;
    hudRun.title = run.stopping
      ? `${run.label}已请求停止，等待进程退出`
      : `${run.label}运行中 · 点击回到岗位页查看日志或停止`;
  };
  paint();
  if (!run.stopping) hudRunTimer = setInterval(paint, 1000);
}
document.addEventListener("crawlchange", syncHudRun);
syncHudRun();
hudRun?.addEventListener("click", (event) => {
  if (parseHash().path !== "/jobs") return;
  event.preventDefault();
  const panel = $("#crawl-panel");
  if (!panel) return;
  panel.open = true;
  panel.scrollIntoView({ block: "start", behavior: "smooth" });
});

function crawlStreamListener(onDone) {
  // done 事件先于进程退出到达，先存下回合统计，等 __done__ 再一并交给收尾逻辑。
  let outcome = null;
  return (event) => {
    if (event.type === "step") chatLog("step", "步骤", `${event.name} [${event.status}] ${event.detail || ""}`);
    else if (event.type === "progress") chatProgress(event.name, event.current, event.total, event.message);
    else if (event.type === "error") chatLog("err", event.agent || "错误", event.message || "");
    else if (event.type === "warn") chatLog("err", event.name || "警告", event.message || "");
    else if (event.type === "login") chatLog("step", "登录", `${event.platform}: ${event.message}`);
    else if (event.type === "done") outcome = event;
    else if (event.type === "__done__") {
      chatLog("step", "系统", `运行结束（退出码 ${event.code}）`);
      if (onDone) onDone({ ...event, outcome });
    }
  };
}

function streamRun(args, onDone) {
  openDrawer();
  chatLog("step", "系统", "开始运行流水线…");
  return window.api.stream("run", args, crawlStreamListener(onDone));
}

// ---------------------------------------------------------------- 组件
const kpi = (value, label, note = "", accent = "pink", index = "") =>
  `<div class="card kpi" style="--tab:var(--${accent})">
    <div class="kpi-head"><span>${esc(label)}</span><em>${esc(index || "—")}</em></div>
    <div class="kpi-num">${esc(value)}</div>
    <div class="kpi-note">${esc(note)}</div>
    <div class="kpi-rule"><i></i></div>
  </div>`;

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

// 规则未定义或维度全无数据时后端返回中性 60 分；界面上不能把它当成真实适配结论
function fitNeutral(fit) {
  if (!fit || fit.total == null) return false;
  const verdict = String(fit.verdict || "");
  if (verdict) return /中性|尚未定义/.test(verdict);
  const source = fit.dimensions || {};
  const values = (Array.isArray(source) ? source.map((d) => Number(d.score)) : Object.values(source).map(Number))
    .filter((v) => Number.isFinite(v));
  return values.length > 0 && values.every((v) => v === 60) && !(fit.advice || []).length;
}

function fitSourceHTML(fit) {
  if (!fit || !fit.at) return "";
  const when = stageTime({ at: fit.at }) || "时间未知";
  const version = fit.resume_id
    ? `简历 #${fit.resume_id}${fit.resume_name ? `（${fit.resume_name}）` : ""}`
    : "未记录简历版本";
  const state = fit.resume_state || "unknown";
  const badge = state === "current"
    ? `<span class="mini mini-ok">当前母版</span>`
    : state === "stale"
      ? `<span class="mini mini-warn" title="适配度基于${esc(version)}，当前母版已变化">母版已变化</span>`
      : `<span class="mini" title="这条适配度来自旧版计算，没有记录使用的简历版本">旧版计算</span>`;
  const action = state === "stale" ? `<a class="link" href="#/resume">去简历页</a>` : "";
  return `<div class="chart-note fit-source">${icon("info")}
    <span>适配于 ${esc(when)} · 基于${esc(version)}</span>${badge}${action}</div>`;
}

function fitTitle(fit) {
  if (!fit) return "适配度";
  const bits = [fit.verdict || "适配度"];
  if (fit.resume_state === "stale") bits.push("母版已变化，建议重新适配");
  else if (fit.resume_id) bits.push(`基于简历 #${fit.resume_id}`);
  if (fit.at) bits.push(`适配于 ${stageTime({ at: fit.at })}`);
  return bits.filter(Boolean).join(" · ");
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

const COMPARE_COLORS = ["#ff5c8a", "#5cb8f0", "#5fd3b0", "#f0c060", "#b18cff", "#ff9a62"];

function multiRadarSVG(companies, size = 340) {
  const scored = (companies || []).filter((c) => c.score && c.score.dimensions);
  if (!scored.length) return `<div class="empty">关注的公司还没有评分</div>`;
  const dims = Object.keys(scored[0].score.dimensions);
  const cx = size / 2, cy = size / 2, R = size / 2 - 58;
  const n = dims.length;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  };
  const rings = [0.2, 0.4, 0.6, 0.8, 1].map((f) => {
    const pts = dims.map((_, i) => pt(i, R * f).join(",")).join(" ");
    return `<polygon points="${pts}" fill="none" stroke="#2a2a37" stroke-width="1"/>`;
  }).join("");
  const axes = dims.map((_, i) => {
    const [x, y] = pt(i, R);
    return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#2a2a37"/>`;
  }).join("");
  const labels = dims.map((dim, i) => {
    const [x, y] = pt(i, R + 28);
    const anchor = Math.abs(x - cx) < 6 ? "middle" : (x > cx ? "start" : "end");
    return `<text x="${x}" y="${y + 4}" text-anchor="${anchor}" fill="#8a8a9e" font-size="11" font-family="Cascadia Mono, Consolas, monospace">${esc(dim)}</text>`;
  }).join("");
  const shapes = scored.map((company, index) => {
    const color = COMPARE_COLORS[index % COMPARE_COLORS.length];
    const points = dims.map((dim, i) => {
      const value = Math.max(0, Math.min(100, Number(company.score.dimensions[dim]) || 0));
      return pt(i, R * value / 100).join(",");
    }).join(" ");
    return `<polygon class="radar-shape" data-compare-key="${esc(company.company_key)}" points="${points}" fill="${color}" fill-opacity=".07" stroke="${color}" stroke-width="1.8"/>`;
  }).join("");
  const legend = scored.map((company, index) => `<span class="radar-legend" data-compare-key="${esc(company.company_key)}"><i style="background:${COMPARE_COLORS[index % COMPARE_COLORS.length]}"></i>${esc(company.name)}</span>`).join("");
  return `<div class="radar-wrap"><svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img"
    aria-label="关注公司五维评分雷达叠加图">${rings}${axes}${shapes}${labels}</svg></div>
    <div class="radar-legend-row">${legend}</div>`;
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
    return `<polygon points="${pts}" fill="none" stroke="#2a2a37" stroke-width="1"/>`;
  }).join("");
  const axes = dimensions.map((_, i) => {
    const [x, y] = pt(i, R);
    return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#2a2a37"/>`;
  }).join("");
  const labels = dimensions.map((dim, i) => {
    const [x, y] = pt(i, R + 30);
    const anchor = Math.abs(x - cx) < 6 ? "middle" : (x > cx ? "start" : "end");
    return `<text x="${x}" y="${y - 4}" text-anchor="${anchor}" fill="#8a8a9e" font-size="11" font-family="Cascadia Mono, Consolas, monospace">${esc(dim.name)}</text>
            <text x="${x}" y="${y + 12}" text-anchor="${anchor}" fill="#5cb8f0" font-size="11.5" font-family="Cascadia Mono, Consolas, monospace">${pct(dim.score)}</text>`;
  }).join("");
  const shape = dimensions
    .map((dim, i) => pt(i, R * Math.max(0, Math.min(100, dim.score)) / 100).join(",")).join(" ");
  const dots = dimensions
    .map((dim, i) => pt(i, R * Math.max(0, Math.min(100, dim.score)) / 100))
    .map(([x, y]) => `<circle cx="${x}" cy="${y}" r="3" fill="#5cb8f0"/>`).join("");
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img">
    ${rings}${axes}
    <polygon points="${shape}" fill="rgba(92,184,240,.13)" stroke="#5cb8f0" stroke-width="2"/>
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
  const dots = coords.map((c) => `<circle cx="${c[0]}" cy="${c[1]}" r="2.6" fill="#5cb8f0"/>`).join("");
  const first = String(points[0].at).slice(0, 10);
  const last = String(points[points.length - 1].at).slice(0, 10);
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="max-width:100%" role="img">
    <path d="${path}" fill="none" stroke="#5cb8f0" stroke-width="1.8"/>${dots}
    <text x="${pad}" y="${height - 8}" fill="#525264" font-size="9" font-family="Cascadia Mono, Consolas, monospace">${esc(first)}</text>
    <text x="${width - pad}" y="${height - 8}" fill="#525264" font-size="9" text-anchor="end" font-family="Cascadia Mono, Consolas, monospace">${esc(last)}</text>
    <text x="${pad}" y="${pad - 10}" fill="#5fd3b0" font-size="9" font-family="Cascadia Mono, Consolas, monospace">max ${fmt(max, 0)}</text>
    <text x="${width - pad}" y="${pad - 10}" fill="#525264" font-size="9" text-anchor="end" font-family="Cascadia Mono, Consolas, monospace">min ${fmt(min, 0)}</text>
  </svg>`;
}

function pager(total, { page = 1, size = total || 1, id = "" } = {}) {
  const pages = Math.max(1, Math.ceil(total / Math.max(1, size)));
  const current = Math.min(pages, Math.max(1, page));
  const start = total ? (current - 1) * size + 1 : 0;
  const end = Math.min(total, current * size);
  const numbers = [];
  if (pages <= 7) {
    for (let n = 1; n <= pages; n++) numbers.push(n);
  } else {
    const wanted = [...new Set([1, pages, current - 1, current, current + 1])]
      .filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
    wanted.forEach((n, i) => {
      if (i && n - wanted[i - 1] > 1) numbers.push("…");
      numbers.push(n);
    });
  }
  return `<div class="table-foot">
    <span>显示 ${start}–${end} 条，共 ${total} 条</span>
    <div class="pager" data-pager="${esc(id)}">
      <button data-page="${current - 1}" ${current <= 1 ? "disabled" : ""} aria-label="上一页" title="上一页（PageUp）">‹</button>
      ${numbers.map((n) => n === "…"
        ? `<span class="pager-gap">…</span>`
        : `<button data-page="${n}" class="${n === current ? "active" : ""}"
             ${n === current ? 'aria-current="page"' : ""} aria-label="第 ${n} 页">${n}</button>`).join("")}
      <button data-page="${current + 1}" ${current >= pages ? "disabled" : ""} aria-label="下一页" title="下一页（PageDown）">›</button>
    </div>
  </div>`;
}

function bindPager(id, page, pages, onGo) {
  const box = $(`[data-pager="${id}"]`);
  if (!box) return;
  $$("button[data-page]", box).forEach((btn) => btn.addEventListener("click", () => {
    const next = Number(btn.dataset.page);
    if (!btn.disabled && next >= 1 && next <= pages && next !== page) onGo(next);
  }));
}

function paintSortHeaders(root, sort, dir) {
  $$("th[data-sort]", root).forEach((th) => {
    const active = th.dataset.sort === sort;
    if (active) th.setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
    else th.removeAttribute("aria-sort");
    th.classList.toggle("sorted", active);
    th.dataset.dir = active ? dir : "";
    const button = th.querySelector(".th-sort");
    if (button) {
      button.setAttribute("aria-label",
        `${button.textContent.trim()}，${active ? (dir === "asc" ? "当前升序" : "当前降序") : "点击排序"}`);
    }
  });
}

function bindSortHeaders(root, state, defaults, onSort) {
  root.addEventListener("click", (event) => {
    const button = event.target.closest(".th-sort");
    const th = button && button.closest("th[data-sort]");
    if (!th || !root.contains(th)) return;
    const { sort, dir } = state();
    const nextDir = sort === th.dataset.sort ? (dir === "asc" ? "desc" : "asc") : defaults[th.dataset.sort];
    onSort(th.dataset.sort, nextDir);
  });
}

const SORT_LABELS = {
  score: "总分", jobs: "岗位数", evidence: "证据数", name: "名称",
  fit: "适配度", track: "跟进时间", company: "公司", title: "岗位", salary: "薪资",
  employer: "公司评分", urgency: "行动优先", snooze: "延后到期",
};
const ALPHA_SORTS = new Set(["name", "company", "title"]);

function paintSortSelect(select, sort, dir, defaults) {
  if (!select) return;
  $$("option", select).forEach((option) => {
    if (option.value === "urgency") {
      option.textContent = SORT_LABELS.urgency;
      return;
    }
    const optionDir = option.value === sort ? dir : defaults[option.value];
    option.textContent = ALPHA_SORTS.has(option.value)
      ? `${SORT_LABELS[option.value]} ${optionDir === "asc" ? "A→Z" : "Z→A"}`
      : `${SORT_LABELS[option.value]} ${optionDir === "asc" ? "↑" : "↓"}`;
  });
  select.value = sort;
}

const debounce = (fn, ms = 140) => {
  let timer = 0;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
};

// 用 replaceState 同步筛选条件，不触发 hashchange，避免整页重绘。
function syncQuery(path, entries) {
  const query = new URLSearchParams();
  Object.entries(entries).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) query.set(key, String(value));
  });
  const text = query.toString();
  history.replaceState(null, "", "#" + path + (text ? "?" + text : ""));
}

function bindNav() {
  $$("tr[data-company]").forEach((row) => row.addEventListener("click", (e) => {
    if (e.target.closest("[data-series]") || e.target.closest("[data-watch]")) return;
    goCompany(row.dataset.company);
  }));
  $$("[data-job]").forEach((node) => node.addEventListener("click", (e) => {
    if (e.target.closest("[data-series]") || e.target.closest("[data-company]")
        || e.target.closest("[data-watch]") || e.target.closest("[data-stage-job]")) return;
    goJob(node.dataset.job);
  }));
  $$("[data-watch]").forEach((btn) => btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const on = toggleWatch(btn.dataset.watch, btn.dataset.watchId);
    syncWatchButton(btn, on);
    syncWatchLinks();
    toast(`${on ? "已关注 " : "已取消关注 "}${btn.dataset.watchLabel || ""}`);
    document.dispatchEvent(new CustomEvent("watchchange", {
      detail: { kind: btn.dataset.watch, id: btn.dataset.watchId, on },
    }));
  }));
  $$("tr[data-company], tr[data-job]").forEach((row) => {
    row.tabIndex = 0;
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.target.closest("a, [data-watch], [data-stage-job]")) return;
      event.preventDefault();
      if (row.dataset.company) goCompany(row.dataset.company);
      else if (row.dataset.job) goJob(row.dataset.job);
    });
  });
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

// ---------------------------------------------------------------- 模块视图
const stageAccent = { source: "pink", backduty: "cyan", score: "teal", fit: "amber", tailor: "purple" };

function agentsOf(kind) {
  return ((state.status && state.status.agents) || []).filter((a) => a.kind === kind);
}

function agentByName(name) {
  return ((state.status && state.status.agents) || []).find((a) => a.name === name) || null;
}

function pipelineStages() {
  const status = state.status || {};
  const sources = status.sources || [];
  const backduty = agentsOf("backduty");
  const pick = (name) => agentByName(name);
  const single = (name) => {
    const agent = pick(name);
    return agent ? [agent] : [];
  };
  return [
    {
      id: "source", no: "01", name: "采集", en: "SOURCE",
      modules: sources.map((s) => ({ ...s, source: true, enabled: s.implemented !== false })),
      note: `${sources.filter((s) => s.implemented).length}/${sources.length} 已接入 · 适配器可扩展`,
    },
    {
      id: "backduty", no: "02", name: "背调", en: "BACKDUTY", modules: backduty,
      note: `${backduty.filter((a) => a.enabled !== false).length}/${backduty.length} 启用 · 多平台取证`,
    },
    {
      id: "score", no: "03", name: "公司评分", en: "SCORE", modules: single("company_score"),
      note: "五维规则评分 · 输出等级",
    },
    {
      id: "fit", no: "04", name: "岗位适配", en: "FIT", modules: single("job_fit"),
      note: "简历 × 岗位 · 输出适配度",
    },
    {
      id: "tailor", no: "05", name: "简历定制", en: "TAILOR", modules: single("resume_tailor"),
      note: "先问再改 · 产出简历版本",
    },
  ].map((stage) => ({ ...stage, accent: stageAccent[stage.id] }));
}

function moduleChip(mod, accent) {
  const enabled = mod.enabled !== false;
  const caps = mod.requires_models || [];
  const title = [mod.label, mod.description].filter(Boolean).join(" · ") || mod.name;
  if (mod.source) {
    return `<span class="mod-chip ${enabled ? "" : "off"}" style="--tab:var(--${accent})" title="${esc(title)}">
      <span class="dot"></span>${esc(mod.label || mod.name)}${enabled ? "" : " · 预留"}</span>`;
  }
  return `<a class="mod-chip ${enabled ? "" : "off"}" style="--tab:var(--${accent})"
      href="#/settings?agent=${encodeURIComponent(mod.name)}" title="${esc(title)}">
      <span class="dot"></span>${esc(mod.name)}${caps.length ? `<span class="cap">${esc(caps.join("+"))}</span>` : ""}</a>`;
}

function pipelineHTML() {
  return `<div class="pipeline">${pipelineStages().map((stage) => `
    <div class="stage" style="--tab:var(--${stage.accent})">
      <div class="stage-head">
        <span class="stage-no">${stage.no}</span>
        <span class="stage-name">${esc(stage.name)}</span>
        <span class="stage-en">${esc(stage.en)}</span>
      </div>
      <div class="stage-mods">${stage.modules.map((m) => moduleChip(m, stage.accent)).join("")
        || `<span class="stage-note">未注册模块</span>`}</div>
      <div class="stage-note">${esc(stage.note)}</div>
    </div>`).join("")}</div>`;
}

function agentModelLabel(agent) {
  const caps = agent.requires_models || [];
  if (!caps.length) return "规则模块 · 不调用模型";
  return caps.map((cap) => {
    const name = (agent.model && agent.model[cap]) || defaultSpecName(cap);
    return `${cap} → ${name || "无可用规格"}`;
  }).join(" / ");
}

function agentModelAlert(agent) {
  return (agent.requires_models || []).some((cap) => {
    const name = (agent.model && agent.model[cap]) || defaultSpecName(cap);
    const spec = specOf(name);
    return !name || !spec || !spec.enabled || !spec.has_key;
  });
}

function moduleCard(agent, index) {
  const enabled = agent.enabled !== false;
  const caps = agent.requires_models || [];
  const tools = [...new Set([...(agent.tools || []), ...(agent.mandatory_tools || [])])];
  const chosen = caps.map((cap) => ({
    cap,
    name: (agent.model && agent.model[cap]) || defaultSpecName(cap),
  }));
  const badModel = agentModelAlert(agent);
  const modelText = caps.length
    ? chosen.map((row) => `${row.cap} → ${row.name || "未配置"}`).join(" / ")
    : "";
  return `<article class="module-card ${enabled ? "" : "is-off"}" style="--tab:var(--${agent.kind === "backduty" ? "cyan" : "teal"})">
    <div class="mod-top">
      <span class="mod-no">${String(index).padStart(2, "0")}</span>
      <div class="mod-title"><b>${esc(agent.name)}</b><em>${esc(agent.kind)} · v${esc(agent.version || "1.0")}</em></div>
      <span class="mod-state ${enabled ? "" : "off"}">${enabled ? "ON" : "OFF"}</span>
    </div>
    <p class="mod-desc">${esc(agent.description || "未填写描述")}</p>
    <div class="mod-meta">
      <div class="mod-kv"><span>tools</span><b class="${tools.length ? "" : "none"}">${esc(tools.join(", ") || "无外部工具")}</b></div>
      <div class="mod-kv"><span>models</span>${caps.length
        ? `<b class="${badModel ? "warn" : ""}">${esc(modelText)}</b>`
        : `<b class="none">规则模块 · 不调用模型</b>`}</div>
      <div class="mod-kv"><span>produces</span><b>${esc((agent.produces || []).join(", ") || "—")}</b></div>
      <div class="mod-kv"><span>requires</span><b>${esc((agent.requires || []).join(", ") || "—")}</b></div>
    </div>
    <div class="mod-actions">
      <span class="pill ${Object.keys(agent.model || {}).length ? "pill-cyan" : "pill-dim"}">
        ${Object.keys(agent.model || {}).length ? `覆盖 ${Object.keys(agent.model).length} 项` : "默认模型"}</span>
      <a class="link" href="#/settings?agent=${encodeURIComponent(agent.name)}">配置 ${icon("chevron")}</a>
    </div>
  </article>`;
}

function fact(k, v) {
  return `<div class="fact"><span class="fact-k">${esc(k)}</span><span class="fact-v">${esc(v)}</span></div>`;
}


async function pageOverview() {
  if (window.SwarmMap) window.SwarmMap.stop();
  pageEl().innerHTML = loadingPage("总览", "正在读取本地数据与流水线状态…", skeletonOverviewBody());
  if (!state.data || !state.status || !state.models) await loadBootstrap();
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
  const neutralFits = fitted.filter((job) => fitNeutral(job.fit)).length;
  const negatives = sorted.reduce((sum, c) => sum + ((c.evidence || {}).negative || 0), 0);
  const avg = scored.length
    ? scored.reduce((sum, c) => sum + Number(c.score.total || 0), 0) / scored.length : null;
  const follow = stageCounts(data.jobs || []);
  const actions = actionQueue(data.jobs || []);
  const dueTotal = actionQueue(data.jobs || [], null).length;
  const snoozedTotal = (data.jobs || []).filter((job) => !!snoozeEnd(trackOf(job.id))).length;
  const interviews = (data.jobs || [])
    .map((job) => ({ job, rec: trackOf(job.id) }))
    .filter(({ rec }) => rec && rec.stage === "interview" && interviewTime(rec)
      && interviewTime(rec) + INTERVIEW_GRACE_MS >= Date.now())
    .sort((a, b) => interviewTime(a.rec) - interviewTime(b.rec));
  const interviewRows = interviews.slice(0, 3);
  const liveInterviews = interviews.filter(({ rec }) => interviewPhase(rec) === "live").length;
  const clashOf = (entry) => interviews.find((other) =>
    other.job.id !== entry.job.id
    && Math.abs(interviewTime(other.rec) - interviewTime(entry.rec)) < INTERVIEW_SLOT_MS);
  const clashCount = interviews.filter((entry) => clashOf(entry)).length;
  const soonCount = interviews.filter(({ rec }) => interviewSoon(rec)).length;
  const pendingInterviews = (data.jobs || [])
    .map((job) => ({ job, rec: trackOf(job.id) }))
    .filter(({ rec }) => rec && rec.stage === "interview" && !interviewTime(rec))
    .sort((a, b) => (Date.parse(a.rec.at) || 0) - (Date.parse(b.rec.at) || 0));
  const pendingRows = pendingInterviews.slice(0, 3);
  const market = marketCoverage();
  const topMissing = market
    ? market.missing.slice(0, 4).map((w) => `${esc(w.name)} ${w.count || 0} 岗`).join("、")
    : "";
  const agents = (state.status && state.status.agents) || [];
  const activeModules = agents.filter((a) => a.enabled !== false).length;
  const swarmStages = pipelineStages().map((stage) => {
    const configurable = stage.modules.find((m) => !m.source);
    return {
      no: stage.no,
      name: stage.name,
      en: stage.en,
      accent: stage.accent,
      href: configurable
        ? `#/settings?agent=${encodeURIComponent(configurable.name)}`
        : "#/modules",
      modules: stage.modules.map((m) => ({
        name: m.label || m.name,
        enabled: m.enabled !== false,
      })),
    };
  });

  const topCompanies = scored.slice(0, 8);
  const rows = topCompanies.map((company) => {
    const s = company.score || {};
    const dims = s.dimensions || {};
    const dimCell = (name) => s.total != null
      ? `<td class="num link" data-company="${esc(company.company_key)}" data-series="${esc(name)}">${fmt(dims[name], 0)}</td>`
      : `<td class="num">—</td>`;
    return `<tr class="clickable" tabindex="0" data-company="${esc(company.company_key)}">
      <td class="link"><span class="name-cell">${watchButton("company", company.company_key, company.name)}${esc(company.name)}</span></td>
      <td class="num score">${fmt(s.total)}</td>
      <td class="center">${gradeBadge(s.grade, true)}</td>
      ${dimCell("风险")}${dimCell("待遇")}${dimCell("压力")}${dimCell("环境")}${dimCell("福利")}
      <td>${laborMini(s.is_labor_dispatch, s.labor_dispatch_reason)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="9" class="empty">暂无公司数据</td></tr>`;

  const maxFit = fitted.length ? fitted[0].fit.total : 1;
  const rail = fitted.slice(0, 5).map((job, index) =>
    rankRow(job.title, `${fitNeutral(job.fit) ? "≈" : ""}${fmt(job.fit.total)}`,
            Math.min(1, job.fit.total / (maxFit || 1)),
            { badge: index + 1, labelWidth: 120, href: { kind: "job", id: job.id } })).join("")
    || `<div class="empty">需要一份已确认简历<br><span class="chart-note">在「简历」页生成定向版本</span></div>`;

  const recentRail = (() => {
    const companyMap = new Map((data.companies || []).map((company) => [company.company_key, company]));
    const jobMap = new Map((data.jobs || []).map((job) => [job.id, job]));
    const chips = recentItems().map((entry) => {
      if (entry.kind === "company") {
        const company = companyMap.get(entry.id);
        if (!company) return null;
        return `<a class="recent-chip" href="#/companies/${encodeURIComponent(company.company_key)}"
          data-company="${esc(company.company_key)}" title="${esc(company.name)}">
          <span class="recent-kind">公司</span><b>${esc(company.name)}</b>
          <em>${company.score?.total != null ? `${fmt(company.score.total)} 分` : "未评分"}${company.job_count ? ` · ${company.job_count} 岗` : ""}</em>
        </a>`;
      }
      const job = jobMap.get(entry.id);
      if (!job) return null;
      return `<a class="recent-chip job" href="#/jobs/${encodeURIComponent(job.id)}"
        data-job="${esc(job.id)}" title="${esc(job.title)}">
        <span class="recent-kind">岗位</span><b>${esc(job.title)}</b>
        <em>${esc(job.company || "—")}${job.fit ? ` · 适配 ${fitNeutral(job.fit) ? "≈" : ""}${fmt(job.fit.total)}` : ""}</em>
      </a>`;
    }).filter(Boolean).slice(0, 5);
    if (!chips.length) return "";
    return `<div class="recent-rail" id="recent-rail">
      <span class="recent-label">${icon("clock")}最近查看</span>
      <div class="recent-list">${chips.join("")}</div>
      <button type="button" class="recent-clear" id="recent-clear" title="清空本机最近查看记录">清空</button>
    </div>`;
  })();

  pageEl().innerHTML = `
    <div class="page-head">
      <div>
        <div class="page-title">总览</div>
        <div class="page-sub">${scored.length} 家公司 · ${fitted.length} 个岗位${neutralFits === fitted.length && fitted.length ? "仅有中性适配分" : "已适配"} · ${activeModules}/${agents.length} 个模块在线 · 数据仅存本机</div>
      </div>
      <div class="page-actions">
        <a class="btn btn-ghost btn-sm" href="#/companies?grade=watch" id="watch-link"
           title="公司 ${watch.companies.size} 家 · 岗位 ${watch.jobs.size} 个">${icon("star")}关注 ${watchTotal()}</a>
        ${dueTotal ? `<a class="btn btn-ghost btn-sm" href="#/jobs?stage=due" id="overview-due"
           title="Offer、面试中的岗位与超期未跟进的投递">${icon("alert")}待行动 ${dueTotal}</a>` : ""}
        ${snoozedTotal ? `<a class="btn btn-ghost btn-sm" href="#/jobs?stage=snoozed" id="overview-snoozed"
           title="延后期间不计入待行动，到期后自动回来">${icon("clock")}延后中 ${snoozedTotal}</a>` : ""}
        ${watch.companies.size >= 2 ? `<a class="btn btn-ghost btn-sm" href="#/compare">${icon("layers")}对比关注</a>` : ""}
        ${watch.jobs.size >= 2 ? `<a class="btn btn-ghost btn-sm" href="#/job-compare">${icon("briefcase")}岗位对比</a>` : ""}
        <a class="btn btn-ghost btn-sm" href="#/modules">${icon("layers")}模块面板</a>
        <button class="btn btn-sm" id="btn-overview-refresh">${icon("refresh")}刷新</button>
      </div>
    </div>

    <div class="grid grid-4">
      ${kpi(intText(sorted.length), "公司实体", "已完成背调入库", "pink", "COMPANIES")}
      ${kpi(intText((data.jobs || []).length), "岗位总量", "BOSS 直聘采集", "cyan", "JOBS")}
      ${kpi(avg == null ? "—" : fmt(avg, 1), "平均公司分", `已评分 ${scored.length} 家`, "teal", "SCORE")}
      ${kpi(intText(negatives), "负面证据", "来自背调 Finding", "amber", "RISK")}
    </div>

    ${market ? `<a class="cov-strip ${market.pct < 35 ? "is-low" : ""}" href="#/skills?gap=1" id="overview-coverage"
      title="母版简历 skills[] 与 ${market.total} 个市场技能词的本地匹配 · 点击打开技能对照">
      <span class="cov-score"><b>${market.pct}<small>%</small></b><em>简历覆盖</em></span>
      <span class="cov-body">
        <span class="cov-title">母版命中 <b>${market.covered}</b> / ${market.total} 个市场技能词 · 还缺 ${market.missing.length} 个</span>
        <div class="gap-meter" role="progressbar" aria-valuemin="0" aria-valuemax="100"
             aria-valuenow="${market.pct}" aria-label="简历技能覆盖率"><i style="--gap-w:${market.pct}%"></i></div>
        <span class="cov-note">${market.missing.length ? `高频缺口：${topMissing}${market.missing.length > 4 ? " 等" : ""}` : "市场高频词已全部覆盖"}</span>
      </span>
      <span class="cov-go">技能对照 ${icon("chevron")}</span>
    </a>` : ""}

    ${recentRail}

    <div class="card track-board section">
      <div class="card-head">
        ${cardTitle("投递漏斗", "briefcase", true)}
        <div class="card-sub">${follow.total ? `已跟进 ${follow.total} 个岗位 · 阶段变更自动记录` : "在岗位页「进度」列标记第一个目标"}</div>
      </div>
      <div class="track-flow">
        ${STAGES.map((s, i) => `${i ? `<span class="track-arrow">${icon("chevron")}</span>` : ""}<a class="track-step ${s.id}" href="#/jobs?stage=${s.id}" aria-label="${s.label} ${follow[s.id]} 个岗位">
          <span class="track-step-top">${icon(s.icon)}${s.label}</span>
          <b>${follow[s.id]}</b>
        </a>`).join("")}
        <a class="track-step none" href="#/jobs?stage=none" aria-label="未标记 ${follow.none} 个岗位">
          <span class="track-step-top">${icon("briefcase")}未标记</span>
          <b>${follow.none}</b>
        </a>
      </div>
      <div class="table-foot">
        <span>阶段：待投 → 已投 → 面试 → Offer → 已接受，拒绝单独归档</span>
        <div style="display:flex;align-items:center;gap:12px">
          <button class="btn btn-ghost btn-sm" id="btn-copy-track">${icon("file")}复制清单</button>
          <a class="link" href="#/jobs?stage=tracked">查看跟进清单 ${icon("chevron")}</a>
          <a class="link" href="#/jobs?view=board" id="overview-board"
             title="看板视图：按阶段分组，拖动卡片或按 Alt + ←/→ 更新进度">${icon("grid")}看板视图</a>
        </div>
      </div>
    </div>

    ${interviews.length || pendingInterviews.length ? `<div class="card interview-board section" id="overview-interviews">
      <div class="card-head">
        ${cardTitle("面试日程", "clock", true)}
        <div class="card-sub">${[
          interviews.length ? `${interviews.length} 场日程` : "",
          liveInterviews ? `${liveInterviews} 场进行中` : "",
          soonCount ? `${soonCount} 场 30 分钟内` : "",
          pendingInterviews.length ? `${pendingInterviews.length} 场待安排` : "",
          clashCount ? `${clashCount} 场时间冲突` : "",
          interviews.length > 1 ? "按时间排序" : "",
          interviews.length > interviewRows.length ? `显示最近 ${interviewRows.length} 场` : "",
        ].filter(Boolean).join(" · ")}</div>
      </div>
      <div class="interview-list">
        ${interviewRows.map(({ job, rec }) => {
          const at = new Date(interviewTime(rec));
          const countdown = interviewCountdown(rec);
          const live = interviewPhase(rec) === "live";
          const soon = interviewSoon(rec);
          const clash = clashOf({ job, rec });
          const clashTitle = clash
            ? `与「${clash.job.title}」的面试${interviewGapText(interviewTime(clash.rec) - interviewTime(rec))} · 按每场约 1 小时估算`
            : "";
          const started = interviewStarted(rec);
          const prepDone = interviewPrepDone(rec);
          return `<div class="interview-slot">
            <a class="interview-item${countdown === "今天" || live ? " today" : ""}${live ? " live" : ""}${soon ? " soon" : ""}${clash ? " conflict" : ""}"
              data-interview-row="${esc(job.id)}" href="#/jobs/${encodeURIComponent(job.id)}">
              <span class="interview-when"><b>${pad2(at.getMonth() + 1)}/${pad2(at.getDate())}</b><em>${pad2(at.getHours())}:${pad2(at.getMinutes())}</em></span>
              <span class="interview-main"><b>${esc(job.title)}</b><em>${interviewRound(rec) ? `<span class="interview-round">${esc(interviewRound(rec))}</span> · ` : ""}${esc(job.company || "—")} · ${esc(live ? "进行中" : `${countdown}${soon ? " · 30 分钟内" : ""}`)}${at.getTime() > Date.now() ? ` · <span class="interview-prep${prepDone === 0 ? " zero" : prepDone === PREP_TOTAL ? " done" : ""}" title="面试准备：已完成 ${prepDone}/${PREP_TOTAL}">准备 ${prepDone}/${PREP_TOTAL}</span>` : ""}</em></span>
              ${clash ? `<span class="interview-clash" title="${esc(clashTitle)}">${icon("alert")}冲突</span>` : ""}
              <span class="interview-go">${icon("chevron")}</span>
            </a>
            ${started ? `<button type="button" class="btn btn-ghost btn-xs interview-reschedule interview-feedback" data-interview-feedback="${esc(job.id)}"
                aria-haspopup="dialog" aria-label="${esc(`记录面试反馈：${job.title}`)}"
                title="${esc(`记录「${job.title}」的面试结果与复盘`)}">${icon("chat")}记反馈</button>`
              : `<button type="button" class="btn btn-ghost btn-xs interview-reschedule" data-interview-schedule="${esc(job.id)}"
                aria-haspopup="dialog" aria-label="${esc(`改期：${job.title}`)}"
                title="${esc(`调整「${job.title}」的面试时间`)}">${icon("clock")}改期</button>`}
          </div>`;
        }).join("")}
        ${pendingRows.map(({ job, rec }) => {
          const prepDone = interviewPrepDone(rec);
          return `<div class="interview-item pending" data-interview-pending="${esc(job.id)}">
          <span class="interview-when"><b>待定</b><em>未安排</em></span>
          <a class="interview-main" href="#/jobs/${encodeURIComponent(job.id)}" title="打开岗位详情">
            <b>${esc(job.title)}</b>
            <em>${interviewRound(rec) ? `<span class="interview-round">${esc(interviewRound(rec))}</span> · ` : ""}${esc(job.company || "—")} · 已标记面试，等待安排时间${prepDone ? ` · <span class="interview-prep${prepDone === PREP_TOTAL ? " done" : ""}" title="面试准备：已完成 ${prepDone}/${PREP_TOTAL}">准备 ${prepDone}/${PREP_TOTAL}</span>` : ""}</em>
          </a>
          <button type="button" class="btn btn-ghost btn-xs interview-schedule" data-interview-schedule="${esc(job.id)}"
            aria-haspopup="dialog" title="${esc(`安排「${job.title}」的面试时间`)}">${icon("clock")}安排时间</button>
        </div>`;
        }).join("")}
      </div>
      <div class="table-foot">
        <span>${pendingInterviews.length > pendingRows.length
          ? `还有 ${pendingInterviews.length - pendingRows.length} 场待安排 · 安排后才能倒计时`
          : pendingInterviews.length ? "安排时间后开始倒计时 · 仅存本机" : "面试时间来自投递跟进 · 仅存本机"}</span>
        <div style="display:flex;align-items:center;gap:12px">
          ${interviews.length ? `<button type="button" class="btn btn-ghost btn-sm" id="btn-export-ics"
            title="把已排期的面试导出为 .ics · 可导入系统日历或手机日历">${icon("download")}导出日历</button>` : ""}
          <a class="link" href="#/jobs?stage=interview">查看全部面试 ${icon("chevron")}</a>
        </div>
      </div>
    </div>` : ""}

    ${actions.length ? `<div class="card action-board section">
      <div class="card-head">
        ${cardTitle("行动队列", "alert", true)}
        <div class="card-sub">Offer 按答复截止 → 面试 → 超 7 天未跟进 → 待投超 3 天</div>
      </div>
      <div class="action-grid">
        ${actions.map(({ job, rec, reason, iconName }) => `
          <div class="action-item">
            <a class="action-link" href="#/jobs/${encodeURIComponent(job.id)}"
               title="${esc([rec.note, trackHistorySummary(rec) ? `阶段轨迹：${trackHistorySummary(rec)}` : ""].filter(Boolean).join(" · "))}">
              <span class="action-ic ${rec.stage}">${icon(iconName)}</span>
              <span class="action-main">
                <b>${esc(job.title)}</b>
                <em>${esc(job.company || "—")} · ${esc(reason)}</em>
              </span>
              <span class="action-badge ${rec.stage}">${stageMeta(rec.stage).label}</span>
              <span class="action-go">${icon("chevron")}</span>
            </a>
            ${rec.stage === "interview" && interviewPhase(rec) === "past"
              ? `<button type="button" class="action-quick action-feedback" data-interview-feedback="${esc(job.id)}"
                  aria-haspopup="dialog" title="${esc(`记录「${job.title}」的面试结果与复盘`)}"
                  aria-label="${esc(`记录面试反馈：${job.title}`)}">${icon("chat")}</button>`
              : `<button type="button" class="action-quick" data-touch-job="${esc(job.id)}"
                  title="${esc(`记录今天已跟进「${job.title}」，重置提醒，不改阶段`)}"
                  aria-label="${esc(`记录跟进：${job.title}`)}">${icon("check")}</button>`}
            <button type="button" class="action-quick action-snooze" data-snooze-job="${esc(job.id)}"
              title="${esc(`延后 3 天提醒「${job.title}」，期间不进入待行动`)}"
              aria-label="${esc(`延后 3 天：${job.title}`)}">${icon("clock")}</button>
            <button type="button" class="action-quick action-caret" data-snooze-menu="${esc(job.id)}"
              aria-haspopup="menu" aria-expanded="false"
              title="选择延后时长：1 天 / 3 天 / 1 周 / 2 周"
              aria-label="${esc(`选择延后时长：${job.title}`)}">${icon("chevron")}</button>
          </div>`).join("")}
      </div>
      <div class="table-foot">
        <span>${actions.length < dueTotal ? `显示 ${actions.length} / 共 ${dueTotal} 项待办` : `${dueTotal} 项待办`} · 按阶段、答复截止与停留时长自动生成${snoozedTotal ? ` · ${snoozedTotal} 个延后中` : ""}</span>
        <div style="display:flex;align-items:center;gap:12px">
          <button class="btn btn-ghost btn-sm" id="btn-copy-actions">${icon("file")}复制行动清单</button>
          <a class="link" href="#/jobs?stage=due">全部待行动 ${icon("chevron")}</a>
        </div>
      </div>
    </div>` : ""}

    <div class="card swarm-card">
      <div class="card-head">
        ${cardTitle("模块集群态势", "grid", true)}
        <div class="swarm-head">
          <span class="swarm-live"><i></i>LIVE</span>
          <span class="card-sub">五阶段 · ${activeModules}/${agents.length} 模块在线 · 粒子密度 = 活跃度</span>
        </div>
      </div>
      <div class="swarm-stage">
        <canvas id="swarm-map" role="img"
          aria-label="模块集群动画：采集、背调、评分、适配、定制五个阶段，粒子密度表示模块活跃度"></canvas>
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        ${cardTitle("模块流水线", "layers", true)}
        <div class="card-sub">采集 → 背调 → 评分 → 适配 → 定制 · 点击模块直接配置</div>
      </div>
      ${pipelineHTML()}
    </div>

    <div class="grid grid-21 section">
      <div class="card">
        <div class="card-head">
          ${cardTitle("公司评分", "building", true)}
          <div class="card-sub">${icon("filter")}TOP ${topCompanies.length} · 已评分 ${scored.length} 家</div>
        </div>
        <table>
          <thead><tr>
            <th>公司</th><th class="num">总分</th><th class="center">等级</th>
            <th class="num">风险</th><th class="num">待遇</th><th class="num">压力</th>
            <th class="num">环境</th><th class="num">福利</th><th class="center">派遣</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="table-foot">
          <span>按总分排序 · 仅显示已评分公司</span>
          <a class="link" href="#/companies">全部 ${sorted.length} 家 ${icon("chevron")}</a>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          ${cardTitle("适配度 TOP", "star", true)}
          <div class="card-sub">${fitted.length} 个${neutralFits ? ` · ${neutralFits} 中性` : ""}</div>
        </div>
        ${rail}
        ${neutralFits ? `<div class="chart-note left" style="margin:2px 0 10px">${neutralFits === fitted.length
          ? "适配规则尚未定义，当前排名只反映中性占位分"
          : `${neutralFits} 个岗位的适配分为中性占位`}</div>` : ""}
        <div style="border-top:1px solid var(--line);margin-top:6px;padding-top:12px">
          <a class="link" href="#/companies">共 ${scored.length} 家已打分 ${icon("chevron")}</a>
        </div>
      </div>
    </div>`;
  bindNav();
  const swarmCanvas = $("#swarm-map");
  if (swarmCanvas && window.SwarmMap) window.SwarmMap.mount(swarmCanvas, swarmStages);
  const refresh = $("#btn-overview-refresh");
  if (refresh) refresh.addEventListener("click", () => refreshShell(true));
  const copyTrack = $("#btn-copy-track");
  if (copyTrack) copyTrack.addEventListener("click", async () => {
    const markdown = followupMarkdown(data.jobs || []);
    if (!markdown) {
      toast("还没有跟进记录，先在岗位页「进度」列标记", "warn");
      return;
    }
    try {
      await copyText(markdown);
      toast("跟进清单已复制为 Markdown");
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
  const copyActions = $("#btn-copy-actions");
  if (copyActions) copyActions.addEventListener("click", async () => {
    const allDue = actionQueue(data.jobs || [], null);
    try {
      await copyText(actionMarkdown(allDue));
      toast(`已复制 ${allDue.length} 项待办为 Markdown`);
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
  $$("[data-touch-job]").forEach((btn) => btn.addEventListener("click", () => {
    const id = btn.dataset.touchJob;
    const before = snapshotTrack(id);
    if (!touchTrack(id)) return;
    const title = btn.closest(".action-item")?.querySelector(".action-main b")?.textContent || "";
    toast(`已记录本次跟进${title ? ` · ${title}` : ""}`, "ok", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        router();
        toast("已撤销本次跟进", "info");
      },
    });
    router();
  }));
  const snoozeQueueJob = (id, days, title) => {
    const before = snapshotTrack(id);
    const queue = [...$$("[data-snooze-job]")].map((node) => node.dataset.snoozeJob);
    const at = queue.indexOf(id);
    const nextId = queue[at + 1] || queue[at - 1] || "";
    if (!snoozeTrack(id, days)) return;
    toast(`已延后 ${days} 天 · ${snoozeDay(trackOf(id))} 重新提醒${title ? ` · ${title}` : ""}`, "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        router().then(() => document.querySelector(`[data-snooze-job="${id}"]`)?.focus({ preventScroll: true }));
        toast("已撤销延后", "info");
      },
    });
    router().then(() => {
      // 队列单项消失后把焦点交给下一个同类按钮；队列清空则落到「延后中」入口
      const target = nextId ? document.querySelector(`[data-snooze-job="${nextId}"]`) : $("#overview-snoozed");
      target?.focus({ preventScroll: true });
    });
  };
  $$("[data-snooze-job]").forEach((btn) => btn.addEventListener("click", () => {
    const id = btn.dataset.snoozeJob;
    const title = btn.closest(".action-item")?.querySelector(".action-main b")?.textContent || "";
    snoozeQueueJob(id, SNOOZE_DAYS, title);
  }));
  $$("[data-snooze-menu]").forEach((btn) => btn.addEventListener("click", () => {
    const id = btn.dataset.snoozeMenu;
    const title = btn.closest(".action-item")?.querySelector(".action-main b")?.textContent || "";
    openSnoozeMenu(btn, {
      jobId: id,
      title,
      onPick: (days) => snoozeQueueJob(id, days, title),
    });
  }));
  $$("[data-interview-schedule]").forEach((btn) => btn.addEventListener("click", () => {
    const id = btn.dataset.interviewSchedule;
    openInterviewScheduler(id, {
      anchor: btn,
      focusAfterSave: () => document.querySelector(`[data-interview-row="${CSS.escape(id)}"]`)?.focus({ preventScroll: true }),
    });
  }));
  const focusAfterFeedback = (id) => {
    const selector = [
      `[data-interview-row="${CSS.escape(id)}"]`,
      `[data-interview-feedback="${CSS.escape(id)}"]`,
      `[data-interview-schedule="${CSS.escape(id)}"]`,
      `[data-touch-job="${CSS.escape(id)}"]`,
      `[data-snooze-job="${CSS.escape(id)}"]`,
      `[data-job="${CSS.escape(id)}"]`,
    ].join(", ");
    const target = document.querySelector(selector)
      || document.querySelector(".action-board [data-interview-feedback], .action-board [data-touch-job]");
    target?.focus({ preventScroll: true });
  };
  $$("[data-interview-feedback]").forEach((btn) => btn.addEventListener("click", () => {
    openInterviewFeedback(btn.dataset.interviewFeedback, {
      anchor: btn,
      focusAfterSave: () => focusAfterFeedback(btn.dataset.interviewFeedback),
    });
  }));
  const exportIcs = $("#btn-export-ics");
  if (exportIcs) exportIcs.addEventListener("click", () => openInterviewIcsDialog({ anchor: exportIcs }));
  const recentClear = $("#recent-clear");
  if (recentClear) recentClear.addEventListener("click", () => {
    clearRecent();
    const recent = $("#recent-rail");
    if (recent) {
      recent.classList.add("removing");
      setTimeout(() => recent.remove(), 160);
    }
    toast("已清空最近查看");
  });
  document.addEventListener("recentchange", () => {
    const recent = $("#recent-rail");
    if (recent) {
      recent.classList.add("removing");
      setTimeout(() => recent.remove(), 160);
    }
  }, { signal: pageAbort.signal });
  document.addEventListener("snoozeexpired", () => { void router(); }, { signal: pageAbort.signal });
  document.addEventListener("interviewchange", () => {
    closeSnoozeMenu(false);
    void router();
  }, { signal: pageAbort.signal });
  document.addEventListener("offerchange", () => {
    closeSnoozeMenu(false);
    void router();
  }, { signal: pageAbort.signal });
}

// ---------------------------------------------------------------- 公司列表
async function pageCompanies(params = {}) {
  pageEl().innerHTML = loadingPage("公司", "正在读取公司与评分…", skeletonListBody());
  if (!state.data) await loadBootstrap();
  const data = state.data || await call("data");
  if (!data) { pageEl().innerHTML = `<div class="empty">取数失败</div>`; return; }
  state.data = data;

  const sorted = [...(data.companies || [])].sort((a, b) => {
    const sa = a.score && a.score.total != null ? a.score.total : -1;
    const sb = b.score && b.score.total != null ? b.score.total : -1;
    return sb - sa;
  });
  const sortDefaults = { score: "desc", jobs: "desc", evidence: "desc", name: "asc" };
  const sortParam = String(params.sort || "");
  const view = {
    q: String(params.q || ""),
    grade: String(params.grade || ""),
    sort: sortDefaults[sortParam] ? sortParam : "score",
    dir: "",
    size: Number(params.size) === 50 ? 50 : 20,
    page: Math.max(1, Number(params.page) || 1),
  };
  view.dir = params.dir === "asc" || params.dir === "desc" ? params.dir : sortDefaults[view.sort];

  const gradeOf = (company) => (company.score && company.score.grade) || "";
  const scoreOf = (company) => (company.score && company.score.total != null ? Number(company.score.total) : -1);
  const evidenceOf = (company) => Number((company.evidence || {}).total || 0);

  pageEl().innerHTML = `
    <div class="page-head"><div>
      <div class="page-title">公司</div>
        <div class="page-sub">${sorted.length} 家 · 点维度数值看该字段趋势 · 本地筛选不重新取数
          <span class="kbd-guide">↑↓ 浏览 · Enter 打开 · W 关注 · / 搜索 · Esc 清空</span></div>
    </div>
    <div class="page-actions">
      <a class="btn btn-ghost btn-sm" id="company-compare" href="#/compare"
         title="并排对比关注的公司（至少 2 家）">${icon("layers")}对比关注 ${watch.companies.size}</a>
    </div></div>
    <div class="card" id="company-table-card">
      <div class="card-head">${cardTitle("公司列表", "building", true)}
        <div class="card-sub">${icon("filter")}<span id="company-count" aria-live="polite">—</span></div></div>
      <div class="list-toolbar">
        <div class="field toolbar-search">
          <input type="search" id="l-company-q" placeholder="搜索公司名称…" autocomplete="off"
                 value="${esc(view.q)}" aria-label="搜索公司名称">
          <button type="button" class="search-clear" data-search-clear="l-company-q"
                  aria-label="清除搜索" title="清除搜索（Esc）" ${view.q ? "" : "hidden"}>×</button>
        </div>
        <div class="field toolbar-select">
          <select id="l-company-grade" aria-label="按等级筛选">
            <option value="">全部等级</option>
            <option value="watch" ${view.grade === "watch" ? "selected" : ""}>已关注（${watch.companies.size}）</option>
            <option value="scored" ${view.grade === "scored" ? "selected" : ""}>已评分</option>
            <option value="unscored" ${view.grade === "unscored" ? "selected" : ""}>未评分</option>
            <option value="A" ${view.grade === "A" ? "selected" : ""}>A 级</option>
            <option value="B" ${view.grade === "B" ? "selected" : ""}>B 级</option>
            <option value="C" ${view.grade === "C" ? "selected" : ""}>C 级</option>
            <option value="D" ${view.grade === "D" ? "selected" : ""}>D 级</option>
            <option value="E" ${view.grade === "E" ? "selected" : ""}>E 级</option>
          </select>
        </div>
        <div class="field toolbar-select">
          <select id="l-company-sort" aria-label="排序方式">
            <option value="score" ${view.sort === "score" ? "selected" : ""}>总分</option>
            <option value="jobs" ${view.sort === "jobs" ? "selected" : ""}>岗位数</option>
            <option value="evidence" ${view.sort === "evidence" ? "selected" : ""}>证据数</option>
            <option value="name" ${view.sort === "name" ? "selected" : ""}>名称</option>
          </select>
        </div>
        <div class="field toolbar-select toolbar-size">
          <select id="l-company-size" aria-label="每页数量">
            <option value="20" ${view.size === 20 ? "selected" : ""}>20 / 页</option>
            <option value="50" ${view.size === 50 ? "selected" : ""}>50 / 页</option>
          </select>
        </div>
        <button class="btn btn-ghost btn-sm" id="l-company-reset">${icon("refresh")}重置</button>
        <button class="btn btn-ghost btn-sm" id="l-company-copy">${icon("copy")}复制结果</button>
        <span class="toolbar-hint" id="company-hint">${watch.companies.size} 关注 · ${sorted.length} 家入库</span>
      </div>
      <table>
        <thead><tr>
          <th data-sort="name"><button type="button" class="th-sort" title="按公司名称排序">公司</button></th>
          <th class="num" data-sort="score"><button type="button" class="th-sort" title="按总分排序">总分</button></th>
          <th class="center">等级</th>
          <th class="num">风险</th><th class="num">待遇</th><th class="num">压力</th>
          <th class="num">环境</th><th class="num">福利</th><th class="center">派遣</th>
          <th class="num" data-sort="jobs"><button type="button" class="th-sort" title="按岗位数排序">岗位</button></th>
          <th class="num" data-sort="evidence"><button type="button" class="th-sort" title="按证据数排序">证据</button></th>
        </tr></thead>
        <tbody id="company-rows"></tbody>
      </table>
      <div id="company-foot"></div>
    </div>`;

  const rowHTML = (company) => {
    const s = company.score || {};
    const dims = s.dimensions || {};
    const dimCell = (name) => s.total != null
      ? `<td class="num link" data-company="${esc(company.company_key)}" data-series="${esc(name)}" title="看 ${esc(name)} 趋势">${fmt(dims[name], 0)}</td>`
      : `<td class="num">—</td>`;
    return `<tr class="clickable" tabindex="0" data-company="${esc(company.company_key)}">
      <td class="link"><span class="name-cell">${watchButton("company", company.company_key, company.name)}<span>${markMatch(company.name, view.q)}</span></span></td>
      <td class="num score">${fmt(s.total)}</td>
      <td class="center">${gradeBadge(s.grade, true)}</td>
      ${dimCell("风险")}${dimCell("待遇")}${dimCell("压力")}${dimCell("环境")}${dimCell("福利")}
      <td>${laborMini(s.is_labor_dispatch, s.labor_dispatch_reason)}</td>
      <td class="num">${company.job_count ?? "—"}</td>
      <td class="num">${company.evidence ? company.evidence.total : 0}</td>
    </tr>`;
  };

  let copyRows = [];
  const paint = () => {
    const needle = view.q.trim().toLowerCase();
    const visible = sorted.filter((company) => {
      if (needle && !String(company.name || "").toLowerCase().includes(needle)
          && !String(company.company_key || "").toLowerCase().includes(needle)) return false;
      if (view.grade === "watch" && !watch.companies.has(company.company_key)) return false;
      if (view.grade === "scored" && scoreOf(company) < 0) return false;
      if (view.grade === "unscored" && scoreOf(company) >= 0) return false;
      if (/^[A-E]$/.test(view.grade) && gradeOf(company) !== view.grade) return false;
      return true;
    });
    const dir = view.dir === "asc" ? 1 : -1;
    const nameAsc = (a, b) => String(a.name).localeCompare(String(b.name), "zh-CN");
    const compare = {
      score: (a, b) => {
        const sa = scoreOf(a);
        const sb = scoreOf(b);
        if (sa < 0 && sb < 0) return nameAsc(a, b);
        if (sa < 0) return 1;
        if (sb < 0) return -1;
        return dir * (sa - sb) || nameAsc(a, b);
      },
      jobs: (a, b) => dir * (Number(a.job_count || 0) - Number(b.job_count || 0)) || nameAsc(a, b),
      evidence: (a, b) => dir * (evidenceOf(a) - evidenceOf(b)) || nameAsc(a, b),
      name: (a, b) => dir * nameAsc(a, b),
    }[view.sort] || ((a, b) => scoreOf(b) - scoreOf(a));
    visible.sort(compare);

    const pages = Math.max(1, Math.ceil(visible.length / view.size));
    view.page = Math.min(pages, Math.max(1, view.page));
    const pageRows = visible.slice((view.page - 1) * view.size, view.page * view.size);
    const emptyText = !sorted.length
      ? "还没有公司数据<br><span class=\"chart-note\">先在「岗位」页采集岗位，跑完背调与评分后这里会自动出现</span>"
      : view.grade === "watch" && !needle
        ? "还没有关注的公司<br><span class=\"chart-note\">点击列表或详情页的星标，把目标公司加入关注</span>"
        : "没有匹配的公司<br><span class=\"chart-note\">调整关键词、等级或清除筛选</span>";
    const emptyAction = !sorted.length
      ? `<div class="empty-action"><a class="btn btn-ghost btn-sm" href="#/jobs">${icon("briefcase")}去岗位页采集</a></div>`
      : (needle || view.grade)
        ? `<div class="empty-action"><button type="button" class="btn btn-ghost btn-sm" data-reset-filters="company">清除搜索与筛选</button></div>`
        : "";
    $("#company-rows").innerHTML = pageRows.map(rowHTML).join("")
      || `<tr><td colspan="11"><div class="empty">${emptyText}${emptyAction}</div></td></tr>`;
    $("#company-count").textContent = visible.length === sorted.length
      ? `${sorted.length} 家`
      : `${visible.length} / ${sorted.length} 家`;
    $("#company-hint").textContent = `${watch.companies.size} 关注 · ${sorted.length} 家入库`;
    copyRows = visible;
    const copyBtn = $("#l-company-copy");
    if (copyBtn) {
      copyBtn.disabled = !copyRows.length;
      copyBtn.title = copyRows.length ? `复制当前筛选的 ${copyRows.length} 家公司（TSV，可粘贴到表格）` : "当前筛选没有可复制的公司";
      copyBtn.setAttribute("aria-label", copyBtn.title);
    }
    const watchOpt = $("#l-company-grade").querySelector('option[value="watch"]');
    if (watchOpt) watchOpt.textContent = `已关注（${watch.companies.size}）`;
    const compareLink = $("#company-compare");
    if (compareLink) compareLink.innerHTML = `${icon("layers")}对比关注 ${watch.companies.size}`;
    $("#company-foot").innerHTML = pager(visible.length, { page: view.page, size: view.size, id: "companies" });
    bindPager("companies", view.page, pages, (next) => {
      view.page = next;
      syncQuery("/companies", queryState());
      paint();
      bindNav();
      $("#company-table-card").scrollIntoView({ block: "start", behavior: "smooth" });
    });
    bindNav();
    paintSortSelect($("#l-company-sort"), view.sort, view.dir, sortDefaults);
    paintSortHeaders($("#company-table-card"), view.sort, view.dir);
  };

  const queryState = () => ({
    q: view.q.trim(),
    grade: view.grade,
    sort: view.sort === "score" ? "" : view.sort,
    dir: view.dir === sortDefaults[view.sort] ? "" : view.dir,
    size: view.size === 20 ? "" : view.size,
    page: view.page === 1 ? "" : view.page,
  });

  const apply = (resetPage) => {
    if (resetPage) view.page = 1;
    syncQuery("/companies", queryState());
    paint();
  };

  $("#l-company-q").addEventListener("input", debounce((event) => {
    view.q = event.target.value;
    apply(true);
  }, 120));
  bindSearchClear($("#l-company-q"));
  $("#l-company-grade").addEventListener("change", (event) => {
    view.grade = event.target.value;
    apply(true);
  });
  $("#l-company-sort").addEventListener("change", (event) => {
    view.sort = event.target.value;
    view.dir = sortDefaults[view.sort];
    apply(true);
  });
  $("#l-company-size").addEventListener("change", (event) => {
    view.size = Number(event.target.value) === 50 ? 50 : 20;
    apply(true);
  });
  const resetFilters = () => {
    view.q = "";
    view.grade = "";
    view.sort = "score";
    view.dir = sortDefaults.score;
    view.size = 20;
    view.page = 1;
    $("#l-company-q").value = "";
    $("#l-company-grade").value = "";
    $("#l-company-sort").value = "score";
    $("#l-company-size").value = "20";
    apply(true);
  };
  $("#l-company-reset").addEventListener("click", resetFilters);
  $("#l-company-copy").addEventListener("click", async () => {
    if (!copyRows.length) return;
    const lines = ["公司\t总分\t等级\t岗位数\t证据数\t负面证据"];
    copyRows.forEach((company) => {
      const score = company.score || {};
      lines.push([
        company.name,
        score.total != null ? fmt(score.total) : "",
        score.grade || "",
        company.job_count ?? 0,
        company.evidence?.total ?? 0,
        company.evidence?.negative ?? 0,
      ].map(tsvCell).join("\t"));
    });
    try {
      await copyText(lines.join("\n"));
      toast(`已复制 ${copyRows.length} 家公司，可直接粘贴到表格`);
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
  bindSortHeaders($("#company-table-card"), () => view, sortDefaults, (sort, dir) => {
    view.sort = sort;
    view.dir = dir;
    $("#l-company-sort").value = sort;
    apply(true);
  });
  $("#company-rows").addEventListener("click", (event) => {
    if (!event.target.closest("[data-reset-filters]")) return;
    resetFilters();
    $("#l-company-q").focus();
  });

  paint();
  takeBackScroll();
  document.addEventListener("watchchange", paint, { signal: pageAbort.signal });
}

// ---------------------------------------------------------------- 岗位对比
async function pageJobCompare() {
  pageEl().innerHTML = loadingPage("岗位对比", "正在读取关注岗位…", skeletonListBody());
  if (!state.data) await loadBootstrap();
  const data = state.data || await call("data");
  if (!data) { pageEl().innerHTML = `<div class="empty">取数失败</div>`; return; }
  state.data = data;

  const jobs = data.jobs || [];
  const companies = data.companies || [];
  const companyByKey = new Map(companies.map((company) => [company.company_key, company]));
  const companyOf = (job) => companyByKey.get(job.company_key)
    || companies.find((company) => company.name === job.company) || null;
  const salaryOf = (job) => salaryMonthly(job.salary);
  const fitOf = (job) => (job.fit && job.fit.total != null ? Number(job.fit.total) : null);
  const scoreOf = (job) => {
    const score = (companyOf(job) || {}).score;
    return score && score.total != null ? Number(score.total) : null;
  };
  const stageOf = (job) => trackOf(job.id);
  const watched = jobs.filter((job) => watch.jobs.has(job.id));
  const picked = [...watched].sort((a, b) => {
    const fitA = fitOf(a);
    const fitB = fitOf(b);
    if (fitA != null || fitB != null) {
      if (fitA == null) return 1;
      if (fitB == null) return -1;
      if (fitB !== fitA) return fitB - fitA;
    }
    return ((salaryOf(b) || {}).mid || -1) - ((salaryOf(a) || {}).mid || -1);
  }).slice(0, 6);
  const overflow = watched.length - picked.length;
  const neutralFits = picked.filter((job) => fitNeutral(job.fit)).length;

  const shortTitle = (text, max = 14) => {
    const value = String(text || "");
    return value.length > max ? value.slice(0, max) + "…" : value;
  };
  const jobLink = (job) => `<a class="link" href="#/jobs/${encodeURIComponent(job.id)}">${esc(job.title)}</a>`;
  const companyLink = (job) => {
    const company = companyOf(job);
    if (!company || !company.company_key) return esc(job.company || "—");
    return `<a class="link" href="#/companies/${encodeURIComponent(company.company_key)}">${esc(company.name || job.company)}</a>`;
  };
  const salaryRange = (job) => {
    const parsed = salaryOf(job);
    return parsed ? `${salaryK(parsed.low)}–${salaryK(parsed.high)}` : "—";
  };
  const stageChip = (job) => {
    const rec = stageOf(job);
    if (!rec) return `<span class="jc-stage none"><i></i>未标记</span>`;
    const meta = stageMeta(rec.stage);
    const path = trackHistorySummary(rec);
    return `<span class="jc-stage ${esc(rec.stage)}"${path ? ` title="阶段轨迹：${esc(path)}"` : ""}><i></i>${esc(meta ? meta.label : rec.stage)}</span>`;
  };
  const stageEditor = (job) => {
    const rec = stageOf(job);
    const tip = stageTip(rec, job.id);
    return `<label class="stage-cell ${rec ? rec.stage : "none"}" title="${esc(tip)}">
      <span class="stage-dot"></span>
      <select data-compare-stage="${esc(job.id)}" data-compare-title="${esc(job.title)}"
              aria-label="更新投递进度：${esc(job.title)}">
        <option value="" ${rec ? "" : "selected"}>未标记</option>
        ${STAGES.map((s) => `<option value="${s.id}" ${rec && rec.stage === s.id ? "selected" : ""}>${s.label}</option>`).join("")}
      </select>
    </label>`;
  };
  const seedSalary = (job) => {
    const parsed = salaryOf(job);
    return parsed ? `${salaryK(parsed.mid)}/月` : (job.salary || "面议");
  };
  const seedOrder = (a, b) => {
    const rank = (job) => {
      const rec = stageOf(job);
      if (!rec || isTerminalStage(rec.stage)) return 5;
      return FOLLOWUP_ORDER[rec.stage] ?? 4;
    };
    const delta = rank(a) - rank(b);
    if (delta) return delta;
    const salaryA = (salaryOf(a) || {}).mid ?? -1;
    const salaryB = (salaryOf(b) || {}).mid ?? -1;
    if (salaryB !== salaryA) return salaryB - salaryA;
    return String(a.title).localeCompare(String(b.title), "zh-CN");
  };
  const seedCard = (job) => {
    const rec = stageOf(job);
    const fit = fitOf(job);
    const iconName = rec ? (FOLLOWUP_ICON[rec.stage] || "alert") : "briefcase";
    const meta = [
      job.company || "—",
      seedSalary(job),
      fit != null ? `${fitNeutral(job.fit) ? "≈" : ""}${fmt(fit, 1)} 适配` : "未适配",
      rec ? (stageMeta(rec.stage) || {}).label || rec.stage : "",
    ].filter(Boolean).join(" · ");
    return `<div class="action-item seed-item">
      <a class="action-link" href="#/jobs/${encodeURIComponent(job.id)}" title="${esc(job.title)}">
        <span class="action-ic ${rec ? rec.stage : "todo"}">${icon(iconName)}</span>
        <span class="action-main">
          <b>${esc(job.title)}</b>
          <em>${esc(meta)}</em>
        </span>
      </a>
      <button type="button" class="btn btn-ghost btn-sm seed-add"
        data-join-compare="${esc(job.id)}"
        aria-label="加入对比：${esc(job.title)}"
        title="关注并加入岗位对比">${icon("star")}加入对比</button>
    </div>`;
  };
  const cardHTML = (job, index) => {
    const parsed = salaryOf(job);
    const grade = (job.fit || {}).grade;
    return `<a class="compare-card" data-compare-key="${esc(job.id)}" href="#/jobs/${encodeURIComponent(job.id)}">
      <span class="compare-no">#${index + 1}</span>
      <span class="compare-main">
        <b title="${esc(job.title)}">${esc(job.title)}</b>
        <span class="chart-note">${esc(job.company || "—")} · ${esc(job.city || "—")}</span>
      </span>
      <span class="compare-score">
        <b class="jc-salary${parsed ? "" : " none"}">${parsed ? salaryK(parsed.mid) : "面议"}</b>
        ${grade ? gradeBadge(grade, true) : ""}
      </span>
    </a>`;
  };

  const subline = picked.length >= 2
    ? (watched.length > picked.length
      ? `关注 ${watched.length} 个 · ${neutralFits === picked.length ? "适配分均为中性，按薪资" : "按适配度"}对比前 ${picked.length} 个`
      : `关注清单中的 ${picked.length} 个岗位 · ${neutralFits === picked.length ? "适配分均为中性占位 · " : ""}薪资、适配、背调与进度并排`)
    : picked.length === 1
      ? "还差 1 个岗位即可并排比较 · 在岗位列表按 W 关注"
      : "从岗位列表关注 2–6 个岗位，并排比较薪资与背调";
  const head = `
    <div class="page-head">
      <div>
        <div class="page-title">岗位对比</div>
        <div class="page-sub">${subline}</div>
      </div>
      <div class="page-actions">
        ${picked.length >= 2 ? `<button class="btn btn-ghost btn-sm" id="btn-job-compare-copy">${icon("copy")}复制对比</button>` : ""}
        <a class="btn btn-ghost btn-sm" href="#/jobs?fit=watch">${icon("briefcase")}关注岗位</a>
      </div>
    </div>`;

  if (picked.length < 2) {
    const seeds = jobs.filter((job) => !watch.jobs.has(job.id)).sort(seedOrder).slice(0, 4);
    pageEl().innerHTML = `${head}
      ${watched.length === 1 ? `<div class="compare-cards">${cardHTML(watched[0], 0)}</div>` : ""}
      <div class="card section">
        <div class="card-head">${cardTitle(watched.length ? "再挑一个岗位" : "挑两个岗位开始对比", "star", true)}
          <div class="card-sub">${seeds.length ? "未关注候选 · 优先已跟进，其次按月薪" : "没有可加入的岗位"}</div></div>
        ${seeds.length ? `<div class="action-grid seed-grid">${seeds.map(seedCard).join("")}</div>
        <div class="table-foot">
          <span>至少 2 个、最多 6 个岗位 · 加入后仍可随时取消</span>
          <a class="link" href="#/jobs">浏览全部岗位 ${icon("chevron")}</a>
        </div>`
        : `<div class="empty">没有可加入的岗位
          <span class="chart-note">先去岗位列表关注 2 个岗位，再回来并排比较</span>
          <a class="link" href="#/jobs">去岗位列表 ${icon("chevron")}</a>
        </div>`}
      </div>`;
    $$("[data-join-compare]").forEach((btn) => btn.addEventListener("click", () => {
      const job = jobs.find((item) => item.id === btn.dataset.joinCompare);
      if (!job || !toggleWatch("job", job.id)) return;
      syncWatchLinks();
      document.dispatchEvent(new CustomEvent("watchchange", { detail: { kind: "job", id: job.id, on: true } }));
      toast(`已关注 ${job.title}`, "ok");
      router().then(() => {
        ($("#btn-job-compare-copy") || $("[data-join-compare]"))?.focus({ preventScroll: true });
      });
    }));
    return;
  }

  const leader = (fn) => {
    const values = picked
      .map((job) => ({ job, value: fn(job) }))
      .filter((entry) => entry.value != null && Number.isFinite(entry.value));
    if (!values.length) return null;
    const top = Math.max(...values.map((entry) => entry.value));
    return { value: top, jobs: values.filter((entry) => entry.value === top).map((entry) => entry.job) };
  };
  const bestSalary = leader((job) => (salaryOf(job) || {}).mid ?? null);
  const bestFit = neutralFits === picked.length
    ? null
    : leader((job) => (fitNeutral(job.fit) ? null : fitOf(job)));
  const bestScore = leader(scoreOf);
  const salaryMids = picked.map((job) => (salaryOf(job) || {}).mid).filter((value) => value != null);
  const salaryGap = salaryMids.length >= 2 ? Math.max(...salaryMids) - Math.min(...salaryMids) : null;
  const followed = picked.map((job) => ({ job, rec: stageOf(job) })).filter((entry) => entry.rec);
  const latest = followed
    .filter((entry) => Number.isFinite(Date.parse(entry.rec.at || "")))
    .sort((a, b) => Date.parse(b.rec.at) - Date.parse(a.rec.at))[0] || null;
  const winnerText = (result, format) => result
    ? `${result.jobs.map(jobLink).join(" / ")} · ${format(result.value)}`
    : "—";
  const bestCell = (result, job) => result && result.jobs.includes(job) ? "best-on" : "";

  const cards = picked.map((job, index) => cardHTML(job, index)).join("");
  const picker = `
    <div class="compare-picker">
      <span class="pick-label">对比中 ${picked.length}/6</span>
      ${picked.map((job) => `<span class="chip active compare-pick-chip" title="${esc(job.title)}">${esc(shortTitle(job.title))}<button type="button" class="pick-x"
        data-unwatch-job="${esc(job.id)}" data-unwatch-title="${esc(job.title)}"
        aria-label="取消关注 ${esc(job.title)}" title="取消关注">×</button></span>`).join("")}
      ${overflow > 0 ? `<span class="chart-note">另有 ${overflow} 个已关注岗位未进入对比</span>` : ""}
      <a class="link pick-reset" href="#/jobs?fit=watch">管理关注</a>
    </div>`;

  const mdCell = (value) => String(value ?? "—").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
  const mdWinner = (result, valueText) => result
    ? `${result.jobs.map((job) => job.title).join(" / ")}（${valueText}）`
    : "—";
  const compareInterviewText = (job) => {
    const rec = stageOf(job);
    if (!rec || rec.stage !== "interview") return "";
    if (!interviewTime(rec)) return "待安排";
    const round = interviewRound(rec);
    const phase = interviewPhase(rec);
    return `${round ? `${round} · ` : ""}${interviewStamp(rec)} · ${interviewCountdown(rec)}${phase === "live" ? " · 进行中" : phase === "past" ? " · 待反馈" : ""}`;
  };
  const compareOfferText = (job) => {
    const rec = stageOf(job);
    if (!rec || rec.stage !== "offer") return "";
    return offerDeadlineLabel(rec) || "未设置截止";
  };
  const hasInterview = picked.some((job) => compareInterviewText(job));
  const hasOffer = picked.some((job) => compareOfferText(job));
  const interviewCell = (job) => {
    const rec = stageOf(job);
    const text = compareInterviewText(job);
    if (!text) return `<td class="jc-muted">—</td>`;
    if (!interviewTime(rec)) return `<td class="jc-muted" title="面试时间待安排">待安排</td>`;
    const phase = interviewPhase(rec);
    return `<td class="jc-interview${phase === "live" ? " live" : ""}" title="${esc(text)}">
      <span>${esc(`${interviewRound(rec) ? `${interviewRound(rec)} · ` : ""}${interviewStamp(rec)}`)}</span>
      <em>${esc(`${interviewCountdown(rec)}${phase === "live" ? " · 进行中" : phase === "past" ? " · 待反馈" : ""}`)}</em>
    </td>`;
  };
  const offerCell = (job) => {
    const rec = stageOf(job);
    const text = compareOfferText(job);
    if (!text) return `<td class="jc-muted">—</td>`;
    const state = offerDeadlineState(rec);
    if (!state) return `<td class="jc-muted" title="尚未设置答复截止">未设置</td>`;
    return `<td class="jc-deadline${state.expired ? " expired" : state.soon ? " soon" : ""}" title="${esc(text)}">${esc(text)}</td>`;
  };
  const compareMarkdown = () => {
    const lines = [];
    const row = (label, values) => lines.push(`| ${mdCell(label)} | ${values.map(mdCell).join(" | ")} |`);
    lines.push(`## 岗位对比 · ${picked.length} 个`);
    lines.push(`> 导出 ${new Date().toLocaleDateString("zh-CN")} · SWARM 本地背调工作台`);
    lines.push("");
    lines.push(`| 指标 | ${picked.map((job) => mdCell(job.title)).join(" | ")} |`);
    lines.push(`| --- | ${picked.map(() => "---").join(" | ")} |`);
    row("公司", picked.map((job) => job.company || "—"));
    row("折算月薪", picked.map(salaryRange));
    row("原始薪资", picked.map((job) => job.salary || "—"));
    row("适配度", picked.map((job) => fitOf(job) != null
      ? `${fitNeutral(job.fit) ? "≈" : ""}${fmt(fitOf(job), 1)}` : "—"));
    row("等级", picked.map((job) => (job.fit || {}).grade || "—"));
    row("公司评分", picked.map((job) => scoreOf(job) != null ? fmt(scoreOf(job), 1) : "—"));
    row("城市", picked.map((job) => job.city || "—"));
    row("投递进度", picked.map((job) => {
      const rec = stageOf(job);
      return rec ? (stageMeta(rec.stage) || {}).label || rec.stage : "未标记";
    }));
    if (hasInterview) row("面试安排", picked.map((job) => compareInterviewText(job) || "—"));
    if (hasOffer) row("Offer 截止", picked.map((job) => compareOfferText(job) || "—"));
    row("阶段轨迹", picked.map((job) => trackHistorySummary(stageOf(job), 5) || "—"));
    row("跟进备注", picked.map((job) => (stageOf(job) || {}).note || "—"));
    row("最近更新", picked.map((job) => {
      const rec = stageOf(job);
      return (rec && stageTime(rec)) || "—";
    }));
    lines.push("");
    lines.push("### 选择参考");
    lines.push(`- 最高月薪：${mdWinner(bestSalary, bestSalary ? `${salaryK(bestSalary.value)}/月` : "")}`);
    lines.push(`- 适配度最高：${neutralFits === picked.length ? "全部为中性占位" : mdWinner(bestFit, bestFit ? fmt(bestFit.value, 1) : "")}`);
    lines.push(`- 公司评分最高：${mdWinner(bestScore, bestScore ? fmt(bestScore.value, 1) : "")}`);
    lines.push(`- 月薪差距：${salaryGap != null ? salaryK(salaryGap) + "/月" : "—"}`);
    lines.push(`- 跟进覆盖：${followed.length}/${picked.length}${latest ? ` · 最近 ${stageTime(latest.rec)}` : ""}`);
    lines.push("");
    if (neutralFits) lines.push(`> 有 ${neutralFits} 个适配分为中性占位（评分规则未定义），不代表真实匹配。`);
    lines.push("> 时薪按 174h/月、日薪按 21.75 天/月、年薪按 12 个月折算；只基于本机关注与跟进数据。");
    return lines.join("\n");
  };

  pageEl().innerHTML = `${head}
    ${picker}
    <div class="compare-cards">${cards}</div>

    <div class="card">
      <div class="card-head">${cardTitle("指标对比", "layers", true)}
        <div class="card-sub">薪资折算月薪 · 公司分来自背调 · 绿色为该行最高</div></div>
      <div class="compare-scroll">
        <table class="compare-table job-compare-table">
          <thead><tr><th>指标</th>${picked.map((job) => `<th data-compare-key="${esc(job.id)}">
            <span class="jc-th-title" title="${esc(job.title)}">${esc(job.title)}</span>
            <span class="jc-th-sub">${esc(job.company || "—")}</span>
          </th>`).join("")}</tr></thead>
          <tbody>
            <tr><td>公司</td>${picked.map((job) => `<td>${companyLink(job)}</td>`).join("")}</tr>
            <tr><td>折算月薪</td>${picked.map((job) => `<td class="${bestCell(bestSalary, job)}">
              <span class="jc-range">${salaryRange(job)}</span></td>`).join("")}</tr>
            <tr><td>原始薪资</td>${picked.map((job) => `<td>${esc(job.salary || "—")}</td>`).join("")}</tr>
            <tr><td>适配度</td>${picked.map((job) => {
              const neutral = fitNeutral(job.fit);
              return `<td class="${bestCell(bestFit, job)}">${fitOf(job) != null
                ? `<span class="${neutral ? "fit-approx" : ""}" title="${esc(fitTitle(job.fit))}">${neutral ? "≈" : ""}${fmt(fitOf(job), 1)}</span>`
                : "—"}</td>`;
            }).join("")}</tr>
            <tr><td>等级</td>${picked.map((job) => `<td>${(job.fit || {}).grade ? gradeBadge(job.fit.grade, true) : "—"}</td>`).join("")}</tr>
            <tr><td>公司评分</td>${picked.map((job) => {
              const company = companyOf(job);
              const score = scoreOf(job);
              return `<td class="${bestCell(bestScore, job)}">${score != null
                ? `${fmt(score, 1)} ${company && company.score && company.score.grade ? gradeBadge(company.score.grade, true) : ""}`
                : "—"}</td>`;
            }).join("")}</tr>
            <tr><td>城市</td>${picked.map((job) => `<td>${esc(job.city || "—")}</td>`).join("")}</tr>
            <tr><td>投递进度</td>${picked.map((job) => `<td class="jc-stage-td">${stageEditor(job)}</td>`).join("")}</tr>
            ${hasInterview ? `<tr><td>面试安排</td>${picked.map((job) => interviewCell(job)).join("")}</tr>` : ""}
            ${hasOffer ? `<tr><td>Offer 截止</td>${picked.map((job) => offerCell(job)).join("")}</tr>` : ""}
            <tr><td>最近更新</td>${picked.map((job) => {
              const rec = stageOf(job);
              return `<td>${rec ? esc(stageTime(rec) || "—") : "—"}</td>`;
            }).join("")}</tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="grid grid-2 section">
      <div class="card">
        <div class="card-head">${cardTitle("选择参考", "star", true)}
          <div class="card-sub">只列事实，不替你排序</div></div>
        <div class="spec-rows">
          ${specRow("最高月薪", winnerText(bestSalary, (value) => `${salaryK(value)}/月`))}
          ${specRow("适配度最高", neutralFits === picked.length ? "全部为中性占位" : winnerText(bestFit, (value) => fmt(value, 1)))}
          ${specRow("公司评分最高", winnerText(bestScore, (value) => fmt(value, 1)))}
          ${specRow("月薪差距", salaryGap != null ? `${salaryK(salaryGap)}/月` : "—")}
          ${specRow("跟进覆盖", `${followed.length}/${picked.length}${latest ? ` · 最近 ${esc(stageTime(latest.rec))}` : ""}`)}
        </div>
        ${neutralFits ? `<div class="chart-note left" style="margin-top:8px">${neutralFits} 个岗位的适配分为中性占位，不参与最高适配评选。</div>` : ""}
        <div class="chart-note" style="margin-top:12px">时薪按 174h/月、日薪按 21.75 天/月、年薪按 12 个月折算。</div>
      </div>
      <div class="card">
        <div class="card-head">${cardTitle("投递阶段", "clock", true)}
          <div class="card-sub">LOCAL · 仅本机</div></div>
        <div class="jc-stage-list">
          ${picked.map((job) => {
            const rec = stageOf(job);
            return `<a class="jc-stage-row" href="#/jobs/${encodeURIComponent(job.id)}">
              <span class="jc-stage-title" title="${esc(job.title)}">${esc(job.title)}</span>
              ${stageChip(job)}
              <em>${rec ? esc(stageTime(rec) || "—") : "未跟进"}</em>
            </a>`;
          }).join("")}
        </div>
        <div class="chart-note" style="margin-top:12px">点击行打开岗位详情，在右栏更新阶段与备注。</div>
      </div>
    </div>`;

  const cardsEls = $$(".compare-card");
  const compareCells = [...$$(".job-compare-table th"), ...$$(".job-compare-table td")];
  const setActive = (key) => {
    const index = key == null ? -1 : picked.findIndex((job) => String(job.id) === key);
    cardsEls.forEach((el) => el.classList.toggle("muted", index >= 0 && el.dataset.compareKey !== key));
    compareCells.forEach((el) => el.classList.toggle("col-hi", index >= 0 && el.cellIndex === index + 1));
  };
  cardsEls.forEach((el) => {
    el.addEventListener("mouseenter", () => setActive(el.dataset.compareKey));
    el.addEventListener("mouseleave", () => setActive(null));
    el.addEventListener("focus", () => setActive(el.dataset.compareKey));
    el.addEventListener("blur", () => setActive(null));
  });

  $$("[data-unwatch-job]").forEach((btn) => btn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const id = btn.dataset.unwatchJob;
    if (!watch.jobs.has(id)) return;
    watch.jobs.delete(id);
    saveWatch();
    syncWatchLinks();
    toast(`已取消关注 ${btn.dataset.unwatchTitle || ""}`);
    document.dispatchEvent(new CustomEvent("watchchange", { detail: { kind: "job", id, on: false } }));
    router();
  }));

  $$("[data-compare-stage]").forEach((select) => select.addEventListener("change", () => {
    const jobId = select.dataset.compareStage;
    if (!jobId) return;
    const before = snapshotTrack(jobId);
    if (select.value) setTrackStage(jobId, select.value); else clearTrack(jobId);
    const rec = trackOf(jobId);
    toast(`${rec ? `已标记「${(stageMeta(rec.stage) || {}).label || rec.stage}」` : "已清除跟进"} · ${select.dataset.compareTitle || ""}`, "ok", {
      label: "撤销",
      onClick: () => {
        restoreTrack(jobId, before);
        router();
        toast("已撤销阶段修改", "info");
      },
    });
    router();
  }));

  const copyCompare = $("#btn-job-compare-copy");
  if (copyCompare) copyCompare.addEventListener("click", async () => {
    try {
      await copyText(compareMarkdown());
      toast(`已复制 ${picked.length} 个岗位的对比为 Markdown`);
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
}

// ---------------------------------------------------------------- 公司对比
async function pageCompare() {
  pageEl().innerHTML = loadingPage("对比", "正在读取关注公司与评分…", skeletonListBody());
  if (!state.data) await loadBootstrap();
  const data = state.data || await call("data");
  if (!data) { pageEl().innerHTML = `<div class="empty">取数失败</div>`; return; }
  state.data = data;

  const scoreOf = (company) => (company.score && company.score.total != null ? Number(company.score.total) : -1);
  const negativeOf = (company) => Number((company.evidence || {}).negative || 0);
  const watched = (data.companies || []).filter((company) => watch.companies.has(company.company_key));
  const watchedByKey = new Map(watched.map((company) => [company.company_key, company]));
  const byScore = (a, b) => scoreOf(b) - scoreOf(a);
  const savedRaw = compareSelection();
  let savedKeys = savedRaw
    ? savedRaw.filter((key, index, arr) => arr.indexOf(key) === index && watchedByKey.has(key))
    : [];
  if (savedRaw && savedKeys.length < 2) {
    saveCompareSelection(null);
    savedKeys = [];
  }
  const defaultKeys = [...watched].sort(byScore).slice(0, 6).map((company) => company.company_key);
  let picked = (savedKeys.length ? savedKeys : defaultKeys).map((key) => watchedByKey.get(key)).filter(Boolean);
  if (picked.length < 2) {
    saveCompareSelection(null);
    savedKeys = [];
    picked = defaultKeys.map((key) => watchedByKey.get(key)).filter(Boolean);
  }

  const head = `
    <div class="page-head">
      <div>
        <div class="page-title">对比</div>
        <div class="page-sub">${watched.length > picked.length
          ? `关注 ${watched.length} 家 · 当前对比 ${picked.length} 家`
          : `关注清单中的 ${picked.length} 家 · 评分、五维与证据并排`}</div>
      </div>
      <div class="page-actions">
        ${picked.length >= 2 ? `<button class="btn btn-ghost btn-sm" id="btn-compare-copy">${icon("copy")}复制对比</button>` : ""}
        <a class="btn btn-ghost btn-sm" href="#/companies">${icon("building")}公司列表</a>
      </div>
    </div>`;

  if (picked.length < 2) {
    pageEl().innerHTML = `${head}
      <div class="card"><div class="empty">至少关注 2 家公司才能对比
        <span class="chart-note">当前关注 ${watch.companies.size} 家 · 在公司列表点击星标加入关注</span>
        <a class="link" href="#/companies">去公司列表 ${icon("chevron")}</a>
      </div></div>`;
    return;
  }
  const others = watched.filter((company) => !picked.some((item) => item.company_key === company.company_key))
    .sort(byScore);
  const showPicker = watched.length > 2;
  const picker = showPicker ? `
    <div class="compare-picker">
      <span class="pick-label">对比中 ${picked.length}/6</span>
      ${picked.map((company) => `<span class="chip active compare-pick-chip">${esc(company.name)}${picked.length > 2
        ? `<button type="button" class="pick-x" data-compare-remove="${esc(company.company_key)}"
             aria-label="将 ${esc(company.name)} 移出对比" title="移出对比">×</button>` : ""}</span>`).join("")}
      ${picked.length === 2 ? `<span class="chart-note">至少保留 2 家</span>` : ""}
      ${picked.length < 6 && others.length ? `<span class="pick-divider">+</span>
        ${others.map((company) => `<button type="button" class="chip" data-compare-add="${esc(company.company_key)}"
          title="加入对比">${esc(company.name)}</button>`).join("")}` : ""}
      ${savedKeys.length ? `<button type="button" class="link pick-reset" data-compare-reset>重置对比</button>` : ""}
    </div>` : "";

  const dims = Object.keys((picked.find((c) => c.score && c.score.dimensions) || {}).score?.dimensions || {});
  const best = picked.reduce((top, company) => scoreOf(company) > scoreOf(top) ? company : top, picked[0]);
  const mostJobs = picked.reduce((top, company) => Number(company.job_count || 0) > Number(top.job_count || 0) ? company : top, picked[0]);
  const cleanest = picked.reduce((top, company) => negativeOf(company) < negativeOf(top) ? company : top, picked[0]);
  const companyLink = (company) =>
    `<a class="link" href="#/companies/${encodeURIComponent(company.company_key)}">${esc(company.name)}</a>`;
  const dimValue = (company, name) => {
    const source = company.score && company.score.dimensions;
    const value = Array.isArray(source)
      ? (source.find((item) => item.name === name) || {}).score
      : (source || {})[name];
    return value == null ? null : Number(value);
  };
  const leads = dims.map((name) => {
    const values = picked
      .map((company) => ({ company, value: dimValue(company, name) }))
      .filter((entry) => entry.value != null && Number.isFinite(entry.value))
      .map((entry) => ({ ...entry, rounded: Math.round(entry.value) }));
    if (!values.length) return null;
    const best = Math.max(...values.map((entry) => entry.rounded));
    const winners = values.filter((entry) => entry.rounded === best).map((entry) => entry.company.name);
    return { name, best, winners, competitive: new Set(values.map((entry) => entry.rounded)).size > 1 };
  }).filter(Boolean);

  const mdCell = (value) => String(value ?? "—").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
  const mdScore = (company) => scoreOf(company) >= 0 ? fmt(scoreOf(company), 1) : "—";
  const mdDim = (company, name) => {
    const value = dimValue(company, name);
    return value != null && Number.isFinite(value) ? fmt(value, 0) : "—";
  };
  const mdDispatch = (company) => {
    const flag = (company.score || {}).is_labor_dispatch;
    return flag === true ? "疑似派遣" : flag === false ? "非派遣" : "未知";
  };
  const compareMarkdown = () => {
    const lines = [];
    const row = (label, values) => lines.push(`| ${mdCell(label)} | ${values.join(" | ")} |`);
    lines.push(`## 公司对比 · ${picked.length} 家`);
    lines.push(`> 导出 ${new Date().toLocaleDateString("zh-CN")} · SWARM 本地背调工作台`);
    lines.push("");
    lines.push(`| 指标 | ${picked.map((company) => mdCell(company.name)).join(" | ")} |`);
    lines.push(`| --- | ${picked.map(() => "---").join(" | ")} |`);
    row("总分", picked.map(mdScore));
    row("等级", picked.map((company) => mdCell((company.score || {}).grade || "—")));
    dims.forEach((name) => row(name, picked.map((company) => mdDim(company, name))));
    row("负面证据", picked.map((company) => negativeOf(company)));
    row("证据总量", picked.map((company) => Number((company.evidence || {}).total || 0)));
    row("岗位数", picked.map((company) => company.job_count ?? 0));
    row("派遣判断", picked.map(mdDispatch));
    lines.push("");
    lines.push("### 对比速览");
    lines.push(`- 最高总分：${best.name}（${mdScore(best)}）`);
    lines.push(`- 岗位最多：${mostJobs.name}（${mostJobs.job_count ?? 0} 个）`);
    lines.push(`- 负面证据最少：${cleanest.name}（${negativeOf(cleanest)} 条）`);
    if (leads.length) {
      lines.push("");
      lines.push("### 维度领先");
      leads.forEach((item) => lines.push(`- ${item.name}：${item.winners.join(" / ")}（${fmt(item.best, 0)}）`));
    }
    lines.push("");
    lines.push("> 分数只基于已采集证据，不构成求职建议。");
    return lines.join("\n");
  };

  const cards = picked.map((company, index) => {
    const score = company.score || {};
    const [tone] = score.total != null ? toneOf(score.total) : ["tone-low"];
    return `<a class="compare-card" data-compare-key="${esc(company.company_key)}" href="#/companies/${encodeURIComponent(company.company_key)}">
      <span class="compare-no">#${index + 1}</span>
      <span class="detail-logo" style="width:38px;height:38px;border-radius:9px;font-size:17px">${esc((company.name || "?").slice(0, 1))}</span>
      <span class="compare-main">
        <b>${esc(company.name)}</b>
        <span class="chart-note">${company.job_count ?? 0} 个岗位 · ${(company.evidence || {}).total ?? 0} 条证据</span>
      </span>
      <span class="compare-score">
        <b class="${tone}">${score.total != null ? fmt(score.total, 1) : "—"}</b>
        ${score.grade ? gradeBadge(score.grade, true) : ""}
      </span>
    </a>`;
  }).join("");

  const dimRows = dims.map((name) => {
    const lead = leads.find((item) => item.name === name);
    return `<tr>
    <td>${esc(name)}</td>
    ${picked.map((company) => {
      const value = dimValue(company, name);
      const leader = lead && lead.competitive && lead.winners.includes(company.name) ? "best-on" : "";
      return `<td class="${leader}">${value != null && Number.isFinite(value) ? fmt(value, 0) : "—"}</td>`;
    }).join("")}
  </tr>`;
  }).join("");

  pageEl().innerHTML = `${head}
    ${picker}
    <div class="compare-cards">${cards}</div>

    <div class="card">
      <div class="card-head">${cardTitle("维度对比", "layers", true)}
        <div class="card-sub">同一套背调口径 · 绿色为各维最高</div></div>
      <div class="compare-scroll">
        <table class="compare-table">
          <thead><tr><th>指标</th>${picked.map((company) => `<th data-compare-key="${esc(company.company_key)}">${esc(company.name)}</th>`).join("")}</tr></thead>
          <tbody>
            <tr><td>总分</td>${picked.map((company) => {
              const value = scoreOf(company);
              const [tone] = value >= 0 ? toneOf(value) : ["tone-low"];
              return `<td class="best-${company === best ? "on" : "off"}"><span class="score ${tone}">${value >= 0 ? fmt(value, 1) : "—"}</span></td>`;
            }).join("")}</tr>
            <tr><td>等级</td>${picked.map((company) => `<td>${company.score && company.score.grade ? gradeBadge(company.score.grade, true) : "—"}</td>`).join("")}</tr>
            ${dimRows}
            <tr><td>负面证据</td>${picked.map((company) => `<td class="${negativeOf(company) > 0 ? "tone-mid" : ""}">${negativeOf(company)}</td>`).join("")}</tr>
            <tr><td>证据总量</td>${picked.map((company) => `<td>${Number((company.evidence || {}).total || 0)}</td>`).join("")}</tr>
            <tr><td>岗位数</td>${picked.map((company) => `<td>${company.job_count ?? 0}</td>`).join("")}</tr>
            <tr><td>派遣判断</td>${picked.map((company) => `<td>${laborMini((company.score || {}).is_labor_dispatch, (company.score || {}).labor_dispatch_reason)}</td>`).join("")}</tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="grid grid-2 section">
      <div class="card">
        <div class="card-head">${cardTitle("五维雷达叠加", "layers", true)}
          <div class="card-sub">维度分越高越靠外</div></div>
        ${multiRadarSVG(picked)}
      </div>
      <div class="card">
        <div class="card-head">${cardTitle("对比速览", "star", true)}</div>
        <div class="spec-rows">
          ${specRow("最高总分", `${companyLink(best)} · ${fmt(scoreOf(best), 1)}`)}
          ${specRow("岗位最多", `${companyLink(mostJobs)} · ${mostJobs.job_count ?? 0} 个`)}
          ${specRow("负面证据最少", `${companyLink(cleanest)} · ${negativeOf(cleanest)} 条`)}
          ${specRow("对比范围", `${picked.length} 家关注公司`)}
        </div>
        ${leads.length ? `<div class="lead-title">维度领先</div>
          <div class="lead-list">
            ${leads.map((row) => `<div class="lead-row" title="${esc(row.winners.join(" / "))}">
              <span>${esc(row.name)}</span>
              <b>${esc(row.winners.join(" / "))}</b>
              <em>${fmt(row.best, 0)}</em>
            </div>`).join("")}
          </div>` : ""}
        <div class="chart-note" style="margin-top:12px">分数只基于已采集证据，不构成求职建议。</div>
      </div>
    </div>`;
  bindNav();

  const compareCards = $$(".compare-card");
  const compareLegends = $$(".radar-legend");
  const compareShapes = $$(".radar-shape");
  const compareCells = [...$$(".compare-table th"), ...$$(".compare-table td")];
  const setCompareActive = (key) => {
    const index = key == null ? -1 : picked.findIndex((company) => String(company.company_key) === key);
    compareCards.forEach((el) => el.classList.toggle("muted", index >= 0 && el.dataset.compareKey !== key));
    compareLegends.forEach((el) => el.classList.toggle("muted", index >= 0 && el.dataset.compareKey !== key));
    compareShapes.forEach((el) => el.classList.toggle("muted", index >= 0 && el.dataset.compareKey !== key));
    compareCells.forEach((el) => el.classList.toggle("col-hi", index >= 0 && el.cellIndex === index + 1));
  };
  [...compareCards, ...compareLegends].forEach((el) => {
    el.addEventListener("mouseenter", () => setCompareActive(el.dataset.compareKey));
    el.addEventListener("mouseleave", () => setCompareActive(null));
    el.addEventListener("focus", () => setCompareActive(el.dataset.compareKey));
    el.addEventListener("blur", () => setCompareActive(null));
  });

  $$("[data-compare-remove]").forEach((btn) => btn.addEventListener("click", () => {
    if (picked.length <= 2) return;
    const key = btn.dataset.compareRemove;
    const company = picked.find((item) => item.company_key === key);
    saveCompareSelection(picked.map((item) => item.company_key).filter((item) => item !== key));
    toast(`已移出对比 · ${company ? company.name : ""}`);
    router();
  }));
  $$("[data-compare-add]").forEach((btn) => btn.addEventListener("click", () => {
    if (picked.length >= 6) return;
    const key = btn.dataset.compareAdd;
    const company = watchedByKey.get(key);
    saveCompareSelection([...picked.map((item) => item.company_key), key]);
    toast(`已加入对比 · ${company ? company.name : ""}`);
    router();
  }));
  const reset = $("[data-compare-reset]");
  if (reset) reset.addEventListener("click", () => {
    saveCompareSelection(null);
    toast("已按总分恢复默认对比");
    router();
  });
  const copyCompare = $("#btn-compare-copy");
  if (copyCompare) copyCompare.addEventListener("click", async () => {
    try {
      await copyText(compareMarkdown());
      toast(`已复制 ${picked.length} 家公司的对比为 Markdown`);
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
}

// ---------------------------------------------------------------- 公司详情
async function updateSeriesCard(card, key, field) {
  const chips = [...card.querySelectorAll(".chip[data-series]")];
  chips.forEach((chip) => chip.classList.toggle("active", chip.dataset.series === field));
  const title = card.querySelector(".card-title");
  if (title) title.innerHTML = `${icon("clock", "ni ti")}${esc(field + " 历史趋势")}${icon("info", "ni info")}`;
  card.classList.add("is-loading");
  const series = await call("series", { company_key: key, field });
  card.classList.remove("is-loading");
  if (!card.isConnected) return;
  if (parseHash().params.series !== field) return;
  const chart = card.querySelector(".series-chart");
  if (chart) {
    chart.innerHTML = lineSVG(series ? series.points : []);
    chart.classList.remove("series-in");
    void chart.offsetWidth;
    chart.classList.add("series-in");
  }
}

function companySummaryText(detail) {
  const score = detail.score || {};
  const basic = detail.basic || {};
  const facts = [
    ["行业", basic.industry],
    ["规模", basic.staff_num],
    ["成立时间", basic.estiblish_time],
    ["注册资本", basic.reg_capital],
    ["法定代表人", basic.legal_person],
    ["注册地址", basic.reg_location],
    ["信用代码", basic.credit_code],
  ].filter(([, value]) => value);
  const dims = (score.dimensions || []).map((dim) => `${dim.name} ${fmt(dim.score, 0)}`).join(" · ");
  const risks = Object.entries(detail.risk?.counts || {}).map(([name, count]) => `${name} ${count}`).join(" · ");
  const lines = [`# ${detail.name}`, ""];
  const headline = [
    score.total != null ? `综合评分 ${fmt(score.total)} / 100` : "",
    score.grade || "",
    `负面证据 ${Number(detail.risk?.evidence_negative || 0)} 条`,
  ].filter(Boolean);
  lines.push(`> ${headline.join(" · ")}`, "");
  if (facts.length) {
    facts.forEach(([label, value]) => lines.push(`- ${label}：${value}`));
    lines.push("");
  }
  if (dims) lines.push("## 评分维度", dims, "");
  if (score.verdict) lines.push("## 结论", score.verdict, "");
  if ((score.advice || []).length) lines.push("## 建议", ...score.advice.map((item) => `- ${item}`), "");
  if (risks) lines.push("## 风险计数", risks, "");
  const jobs = (detail.jobs || []).slice(0, 5)
    .map((job) => `- ${job.title}${job.city ? ` · ${job.city}` : ""}${job.salary ? ` · ${job.salary}` : ""}`);
  if (jobs.length) lines.push("## 在招岗位", ...jobs, "");
  const reviews = Object.entries(detail.reviews || {})
    .flatMap(([source, items]) => (items || []).slice(0, 3).map((review) => `- [${source}] ${review.title || "无标题"}`));
  if (reviews.length) lines.push("## 外部评价", ...reviews, "");
  return lines.join("\n").trimEnd();
}

async function pageCompanyDetail(key, params) {
  const field = params.series;
  const existing = field ? document.getElementById("series-card") : null;
  if (existing && existing.dataset.companyKey === key) {
    await updateSeriesCard(existing, key, field);
    return;
  }
  pageEl().innerHTML = skeletonPage("detail");
  const detail = await cachedDetail("company", { company_key: key });
  if (!detail) {
    pageEl().innerHTML = emptyWithAction("公司背调取数失败", "#/companies", "返回公司列表");
    return;
  }

  const score = detail.score || {};
  const basic = detail.basic || {};
  const dispatch = detail.labor_dispatch || {};
  const dims = score.dimensions || [];
  crumb("公司", detail.name);

  let seriesCard = "";
  if (field) {
    const series = await call("series", { company_key: key, field });
    const chips = [...dims.map((d) => ({ name: d.name, key: d.name })), { name: "总分", key: "total" }]
      .map((c) => `<button class="chip ${c.key === field ? "active" : ""}"
        data-series="${esc(c.key)}" data-series-company="${esc(key)}">${esc(c.name)}</button>`).join("");
    seriesCard = `<div class="card section" id="series-card" data-company-key="${esc(key)}">
      <div class="card-head">${cardTitle(field + " 历史趋势", "clock", true)}
        <div class="chips">${chips}</div></div>
      <div class="series-chart">${lineSVG(series ? series.points : [])}</div>
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
          <span class="rank-num" style="width:auto;color:var(--fg)">${esc(count)}</span></div>`).join("")
    : `<div class="empty">无风险计数</div>`;

  const [scoreTone] = score.total != null ? toneOf(score.total) : ["tone-good"];
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
        <span class="big ${score.total != null ? scoreTone : ""}">${score.total != null ? fmt(score.total, 1) : "—"}</span>
        <span class="of">/100</span>
      </div>
      ${score.grade ? `<div class="grade-box g-${esc(score.grade)}">${esc(score.grade)}</div>` : ""}
      ${laborPill(dispatch.is_labor_dispatch, dispatch.reason)}
      ${watchButton("company", key, detail.name, { large: true, shortcut: "W" })}
      <button type="button" class="btn btn-ghost btn-sm" id="btn-copy-company"
        title="复制公司摘要：评分、工商信息、风险与在招岗位（C）">${icon("copy")}复制摘要</button>
      <a class="link" href="${esc(backHash("#/companies"))}" style="margin-left:4px">← 列表</a>
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
          ${(detail.jobs || []).length ? `<div style="margin-top:10px">
            <a class="link chart-note" id="company-all-jobs" href="#/jobs?q=${encodeURIComponent(detail.name)}"
              title="在岗位页查看全部 ${detail.jobs.length} 个在招岗位（J）">在岗位页查看全部 ${detail.jobs.length} 个 ${icon("chevron")}</a>
          </div>` : ""}
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
  const copyCompany = $("#btn-copy-company");
  if (copyCompany) copyCompany.addEventListener("click", async () => {
    try {
      await copyText(companySummaryText(detail));
      toast(`已复制 ${detail.name} 的公司摘要`);
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
  bindNav();
}

// ---------------------------------------------------------------- 岗位视图偏好
const JOB_VIEW_KEY = "swarm.jobs.view.v1";
const readJobViewPref = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(JOB_VIEW_KEY) || "null");
    return {
      mode: saved?.mode === "board" ? "board" : "list",
      size: saved?.size === 50 ? 50 : 25,
    };
  } catch {
    return { mode: "list", size: 25 };
  }
};
const saveJobViewPref = (mode, size) => writeLocal(JOB_VIEW_KEY, { mode, size });

// ---------------------------------------------------------------- 岗位
async function pageJobs(params = {}) {
  pageEl().innerHTML = loadingPage("岗位", "正在读取岗位与筛选项…", skeletonListBody());
  if (!state.data || !state.filters) await loadBootstrap();
  const [filters, data] = await Promise.all([
    loadFilters(),
    state.data ? Promise.resolve(state.data) : call("data"),
  ]);
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
  const companies = data.companies || [];
  const companyByKey = new Map(companies.map((company) => [company.company_key, company]));
  const companyByName = new Map(companies.map((company) => [company.name, company]));
  const employerOf = (job) => companyByKey.get(job.company_key) || companyByName.get(job.company) || null;
  const isWatchedCompany = (job) => watch.companies.has(job.company) || watch.companies.has(job.company_key);
  const companyScoreOf = (job) => {
    const score = (employerOf(job) || {}).score;
    return score && score.total != null ? Number(score.total) : null;
  };
  const cities = [...new Set(jobs.map((job) => job.city).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
  const counts = stageCounts(jobs);
  const dueCount = jobs.filter((job) => followupDue(trackOf(job.id))).length;
  const watchedCompanyJobs = jobs.filter(isWatchedCompany).length;
  let snoozeCount = jobs.filter((job) => !!snoozeEnd(trackOf(job.id))).length;
  const stageParam = String(params.stage || "");
  const sortParam = String(params.sort || (stageParam === "due" ? "urgency" : stageParam === "snoozed" ? "snooze" : stageParam === "tracked" ? "track" : "fit"));
  const sortDefaults = { fit: "desc", salary: "desc", employer: "desc", track: "desc", urgency: "asc", snooze: "asc", company: "asc", title: "asc" };
  const savedView = readJobViewPref();
  const viewParam = String(params.view || "");
  const boardMode = viewParam === "board" || (viewParam !== "list" && savedView.mode === "board");
  const sizeParam = Number(params.size);
  const view = {
    q: String(params.q || ""),
    city: String(params.city || ""),
    fit: String(params.fit || ""),
    salary: ["10", "20", "30"].includes(String(params.salary || "")) ? String(params.salary) : "",
    stage: boardMode ? "" : stageParam === "none" || stageParam === "tracked" || stageParam === "due" || stageParam === "snoozed" || STAGE_IDS.has(stageParam) ? stageParam : "",
    sort: sortDefaults[sortParam] ? sortParam : "fit",
    dir: "",
    size: sizeParam === 25 || sizeParam === 50 ? sizeParam : savedView.size,
    page: Math.max(1, Number(params.page) || 1),
    mode: boardMode ? "board" : "list",
  };
  view.dir = params.dir === "asc" || params.dir === "desc" ? params.dir : sortDefaults[view.sort];
  const lastCrawl = readLastCrawl();
  const lastNote = crawlLastNote(lastCrawl);

  pageEl().innerHTML = `
    <div class="page-head">
      <div>
        <div class="page-title">岗位</div>
        <div class="page-sub">${jobs.length} 条已入库 · BOSS直聘采集 · 背调与适配结果会写回岗位
          <span class="kbd-guide">↑↓ 浏览 · Enter 打开 · W 关注 · T 跟进 · C 公司 · V 视图 · / 搜索 · Esc 清空</span></div>
      </div>
      <div class="page-actions">
        <span class="pill pill-cyan">${icon("database")}${jobs.length} JOBS</span>
        <a class="btn btn-ghost btn-sm" href="#/job-compare" id="job-compare-link"
           title="并排对比已关注岗位">${icon("layers")}岗位对比<span id="job-compare-count">${watch.jobs.size ? ` ${watch.jobs.size}` : ""}</span></a>
        <button class="btn btn-sm" id="btn-open-crawl">${icon("play")}采集新岗位</button>
      </div>
    </div>

    <details class="card crawl-card" id="crawl-panel" ${jobs.length ? "" : "open"}>
      <summary class="crawl-summary">
        <span class="card-title">${icon("search")}采集参数<span class="info">${icon("info")}</span></span>
        <span class="crawl-summary-side">
          <span class="crawl-state" id="crawl-state" role="status" aria-live="polite">READY</span>
          ${lastNote
            ? `<span class="chart-note crawl-last ${esc(lastCrawl.status)}" id="crawl-last" title="${esc(crawlLastTitle(lastCrawl))}">${esc(lastNote)}</span>`
            : `<span class="chart-note">关键词 · 城市 · 平台</span>`}
          ${icon("chevron", "ni crawl-chev")}
        </span>
      </summary>
      <div class="crawl-body">
        <div class="crawl-grid">
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
        <div class="crawl-options">
          <span class="card-sub">背调平台</span>
          <div class="checkbox-row" id="f-platforms"></div>
          <span class="card-sub">开关</span>
          <div class="checkbox-row" id="f-toggles"></div>
        </div>
        <div class="form-error" id="f-error" hidden></div>
        <div class="crawl-actions">
          <button class="btn btn-ghost btn-sm" id="btn-nocrawl">只重算（不采集）</button>
          <button class="btn btn-danger btn-sm" id="btn-stop" disabled>停止</button>
          <span class="chart-note">采集完成后自动刷新下方列表，当前筛选条件会保留</span>
        </div>
      </div>
    </details>

    <div class="card section" id="job-table-card">
      <div class="card-head">${cardTitle("岗位列表", "briefcase", true)}
        <div class="card-sub">${icon("filter")}<span id="job-count" aria-live="polite">—</span><span id="job-fit-note" class="mini mini-warn" hidden></span><span id="job-salary-stat" title="当前筛选结果的月薪中位数（时薪、日薪、年薪已折算）"></span><span id="job-mode-note" class="mini" hidden></span></div></div>
      <div class="list-toolbar">
        <div class="field toolbar-search">
          <input type="search" id="l-job-q" placeholder="搜索岗位 / 公司 / 城市 / 备注…" autocomplete="off"
                 value="${esc(view.q)}" aria-label="搜索岗位、公司、城市或跟进备注">
          <button type="button" class="search-clear" data-search-clear="l-job-q"
                  aria-label="清除搜索" title="清除搜索（Esc）" ${view.q ? "" : "hidden"}>×</button>
        </div>
        <div class="field toolbar-select">
          <select id="l-job-city" aria-label="按城市筛选">
            <option value="">全部城市</option>
            ${cities.map((city) => `<option value="${esc(city)}" ${view.city === city ? "selected" : ""}>${esc(city)}</option>`).join("")}
          </select>
        </div>
        <div class="field toolbar-select">
          <select id="l-job-fit" aria-label="按关注或适配度筛选">
            <option value="">全部岗位</option>
            <option value="watch" ${view.fit === "watch" ? "selected" : ""}>已关注岗位（${watch.jobs.size}）</option>
            <option value="watch_company" ${view.fit === "watch_company" ? "selected" : ""}>已关注公司（${watchedCompanyJobs}）</option>
            <option value="fit" ${view.fit === "fit" ? "selected" : ""}>有适配分</option>
            <option value="unfit" ${view.fit === "unfit" ? "selected" : ""}>未适配</option>
            <option value="A" ${view.fit === "A" ? "selected" : ""}>A 级</option>
            <option value="B" ${view.fit === "B" ? "selected" : ""}>B 级</option>
            <option value="C" ${view.fit === "C" ? "selected" : ""}>C 级</option>
            <option value="D" ${view.fit === "D" ? "selected" : ""}>D 级</option>
          </select>
        </div>
        <div class="field toolbar-select">
          <select id="l-job-stage" aria-label="按投递进度筛选">
            <option value="">全部进度</option>
            <option value="tracked" ${view.stage === "tracked" ? "selected" : ""}>跟进中（${counts.total}）</option>
            <option value="due" ${view.stage === "due" ? "selected" : ""}>待行动（${dueCount}）</option>
            <option value="snoozed" ${view.stage === "snoozed" ? "selected" : ""}>延后中（${snoozeCount}）</option>
            <option value="none" ${view.stage === "none" ? "selected" : ""}>未标记（${counts.none}）</option>
            ${STAGES.map((s) => `<option value="${s.id}" ${view.stage === s.id ? "selected" : ""}>${s.label}（${counts[s.id]}）</option>`).join("")}
          </select>
        </div>
        <div class="field toolbar-select">
          <select id="l-job-salary" aria-label="按折算月薪筛选" title="时薪、日薪与年薪统一折算为月薪后筛选">
            <option value="">全部薪资</option>
            <option value="10" ${view.salary === "10" ? "selected" : ""}>月薪 ≥10K</option>
            <option value="20" ${view.salary === "20" ? "selected" : ""}>月薪 ≥20K</option>
            <option value="30" ${view.salary === "30" ? "selected" : ""}>月薪 ≥30K</option>
          </select>
        </div>
        <div class="field toolbar-select">
          <select id="l-job-sort" aria-label="排序方式">
            <option value="fit" ${view.sort === "fit" ? "selected" : ""}>适配度</option>
            <option value="salary" ${view.sort === "salary" ? "selected" : ""}>薪资</option>
            <option value="employer" ${view.sort === "employer" ? "selected" : ""}>公司评分</option>
            <option value="track" ${view.sort === "track" ? "selected" : ""}>跟进时间</option>
            <option value="urgency" ${view.sort === "urgency" ? "selected" : ""}>行动优先</option>
            <option value="snooze" ${view.sort === "snooze" ? "selected" : ""}>延后到期</option>
            <option value="company" ${view.sort === "company" ? "selected" : ""}>公司</option>
            <option value="title" ${view.sort === "title" ? "selected" : ""}>岗位</option>
          </select>
        </div>
        <div class="field toolbar-select toolbar-size">
          <select id="l-job-size" aria-label="每页数量">
            <option value="25" ${view.size === 25 ? "selected" : ""}>25 / 页</option>
            <option value="50" ${view.size === 50 ? "selected" : ""}>50 / 页</option>
          </select>
        </div>
        <button class="btn btn-ghost btn-sm" id="l-job-reset">${icon("refresh")}重置</button>
        <button class="btn btn-ghost btn-sm" id="l-job-copy">${icon("copy")}复制结果</button>
        <div class="view-toggle" role="group" aria-label="岗位视图">
          <button type="button" class="view-btn" data-job-view="list" aria-pressed="${view.mode === "list"}"
                  title="列表视图，适合筛选与排序">${icon("list")}列表</button>
          <button type="button" class="view-btn" data-job-view="board" aria-pressed="${view.mode === "board"}"
                  title="看板视图，按阶段分组，拖动卡片更新进度">${icon("grid")}看板</button>
        </div>
        <span class="toolbar-hint" id="job-hint">${watch.jobs.size} 关注 · ${cities.length} 个城市</span>
      </div>
      <table id="job-table">
        <thead><tr>
          <th data-sort="title"><button type="button" class="th-sort" title="按岗位名称排序">岗位</button></th>
          <th data-sort="company"><button type="button" class="th-sort" title="按公司名称排序">公司</button></th>
          <th class="num" data-sort="salary"><button type="button" class="th-sort" title="按折算月薪排序（时薪、日薪、年薪统一换算）">薪资</button></th><th>城市</th>
          <th class="num" data-sort="fit"><button type="button" class="th-sort" title="按适配度排序">适配度</button></th>
          <th class="center">等级</th>
          <th data-sort="track"><button type="button" class="th-sort" title="按最近跟进时间排序">进度</button></th>
        </tr></thead>
        <tbody id="job-rows"></tbody>
      </table>
      <div class="job-board" id="job-board" aria-label="岗位看板" hidden></div>
      <div id="job-foot"></div>
    </div>`;

  const fitOf = (job) => (job.fit && job.fit.total != null ? Number(job.fit.total) : -1);
  const stageCell = (job) => {
    const rec = trackOf(job.id);
    const due = followupDue(rec);
    const snoozed = !!snoozeEnd(rec);
    const soon = interviewSoon(rec);
    const clash = interviewClash(job.id, rec);
    const offer = offerDeadlineState(rec);
    const offerText = offer ? `，Offer ${offerDeadlineShort(rec)}` : "";
    const offerCls = offer ? (offer.expired ? " offer-expired" : offer.soon ? " offer-soon" : "") : "";
    const urgency = `${soon ? "，30 分钟内开始" : ""}${clash ? `，与「${interviewJobTitle(clash.id)}」面试时间冲突` : ""}${offerText}`;
    const tip = [stageTip(rec, job.id), rec && !isTerminalStage(rec.stage) ? "按 T 记录本次跟进" : ""].filter(Boolean).join(" · ");
    return `<td class="stage-td"><label class="stage-cell ${rec ? rec.stage : "none"}${due ? " due" : ""}${snoozed ? " snoozed" : ""}${soon ? " soon" : ""}${clash ? " clash" : ""}${offerCls}" title="${esc(tip)}">
      <span class="stage-dot"></span>
      <select data-stage-job="${esc(job.id)}" data-stage-title="${esc(job.title)}" aria-label="更新投递进度：${esc(job.title)}${due ? "，待跟进" : ""}${urgency}">
        <option value="" ${rec ? "" : "selected"}>未标记</option>
        ${STAGES.map((s) => `<option value="${s.id}" ${rec && rec.stage === s.id ? "selected" : ""}>${s.label}</option>`).join("")}
      </select>
    </label></td>`;
  };
  const salaryCell = (job) => {
    if (!job.salary) return `<td class="num">—</td>`;
    const parsed = salaryMonthly(job.salary);
    if (!parsed) return `<td class="num">${esc(job.salary)}</td>`;
    const title = `折算月薪 ${salaryK(parsed.low)}–${salaryK(parsed.high)} / 月`;
    const hint = /k|千/i.test(job.salary) ? "" : `<span class="salary-note">≈${salaryK(parsed.mid)}/月</span>`;
    return `<td class="num salary-cell" title="${esc(title)}">${esc(job.salary)}${hint}</td>`;
  };
  const rowHTML = (job) => {
    const note = String(trackOf(job.id)?.note || "").trim();
    const noteHit = note && view.q.trim() && note.toLowerCase().includes(view.q.trim().toLowerCase());
    const employer = employerOf(job);
    const employerKey = (employer && employer.company_key) || "";
    const employerScore = companyScoreOf(job);
    return `
    <tr class="clickable" tabindex="0" data-job="${esc(job.id)}">
      <td><span class="name-cell">${watchButton("job", job.id, job.title)}<span class="link">${markMatch(job.title, view.q)}</span>${noteHit
        ? `<span class="row-note" role="img" aria-label="命中跟进备注" title="${esc(`备注匹配：${note}`)}">${icon("chat")}</span>` : ""}</span></td>
      <td class="company-td" style="color:var(--dim)"><span class="company-cell">${employerKey
        ? `<a class="company-link" href="#/companies/${encodeURIComponent(employerKey)}" data-company="${esc(employerKey)}"
             title="打开「${esc(employer.name || job.company)}」的公司背调（C）">${markMatch(job.company || "—", view.q)}</a>`
        : `<span class="company-name">${markMatch(job.company || "—", view.q)}</span>`}${employerScore != null
        ? `<span class="company-score" title="公司评分 ${fmt(employerScore, 1)} / 100 · 打开公司页查看背调">${fmt(employerScore, 1)}</span>` : ""}</span></td>
      ${salaryCell(job)}
      <td class="city-cell" style="color:var(--dim)">${esc(job.city || "—")}</td>
      <td class="num">${job.fit ? `<span class="${fitNeutral(job.fit) ? "fit-approx" : ""}"
        title="${esc(fitTitle(job.fit))}">${fitNeutral(job.fit) ? "≈" : ""}${fmt(job.fit.total)}</span>${job.fit.resume_state === "stale"
        ? `<span class="fit-stale-dot" role="img" aria-label="适配度可能过期" title="母版已变化，建议重新适配"></span>` : ""}` : "—"}</td>
      <td class="center">${job.fit ? gradeBadge(job.fit.grade, true) : "—"}</td>
      ${stageCell(job)}
    </tr>`;
  };

  const boardStageSelect = (job) => {
    const rec = trackOf(job.id);
    const due = followupDue(rec);
    const snoozed = !!snoozeEnd(rec);
    const soon = interviewSoon(rec);
    const clash = interviewClash(job.id, rec);
    const offer = offerDeadlineState(rec);
    const offerCls = offer ? (offer.expired ? " offer-expired" : offer.soon ? " offer-soon" : "") : "";
    return `<label class="stage-cell board-stage ${rec ? rec.stage : "none"}${due ? " due" : ""}${snoozed ? " snoozed" : ""}${soon ? " soon" : ""}${clash ? " clash" : ""}${offerCls}" title="${esc(stageTip(rec, job.id))}">
      <span class="stage-dot"></span>
      <select data-stage-job="${esc(job.id)}" data-stage-title="${esc(job.title)}" aria-label="更新投递进度：${esc(job.title)}${soon ? "，30 分钟内开始" : ""}${clash ? `，与「${esc(interviewJobTitle(clash.id))}」面试时间冲突` : ""}${offer ? `，Offer ${esc(offerDeadlineShort(rec))}` : ""}">
        <option value="" ${rec ? "" : "selected"}>未标记</option>
        ${STAGES.map((s) => `<option value="${s.id}" ${rec && rec.stage === s.id ? "selected" : ""}>${s.label}</option>`).join("")}
      </select>
    </label>`;
  };
  const syncStageCell = (select, rec) => {
    const cell = select.closest(".stage-cell");
    if (!cell) return;
    const id = select.dataset.stageJob;
    const soon = interviewSoon(rec);
    const clash = interviewClash(id, rec);
    const offer = offerDeadlineState(rec);
    cell.classList.remove("none", "offer-expired", "offer-soon", ...STAGES.map((s) => s.id));
    cell.classList.add(rec ? rec.stage : "none");
    cell.classList.toggle("due", followupDue(rec));
    cell.classList.toggle("snoozed", !!snoozeEnd(rec));
    cell.classList.toggle("soon", soon);
    cell.classList.toggle("clash", !!clash);
    cell.classList.toggle("offer-expired", !!offer?.expired);
    cell.classList.toggle("offer-soon", !!offer && !offer.expired && offer.soon);
    cell.title = cell.classList.contains("board-stage")
      ? stageTip(rec, id)
      : [stageTip(rec, id), rec && !isTerminalStage(rec.stage) ? "按 T 记录本次跟进" : ""].filter(Boolean).join(" · ");
    select.setAttribute("aria-label", `更新投递进度：${select.dataset.stageTitle || ""}${followupDue(rec) ? "，待跟进" : ""}${soon ? "，30 分钟内开始" : ""}${clash ? `，与「${interviewJobTitle(clash.id)}」面试时间冲突` : ""}${offer ? `，Offer ${offerDeadlineShort(rec)}` : ""}`);
  };
  const syncAllStageCells = () => {
    document.querySelectorAll("select[data-stage-job]").forEach((select) => syncStageCell(select, trackOf(select.dataset.stageJob)));
  };
  const boardCardHTML = (job) => {
    const rec = trackOf(job.id);
    const due = followupDue(rec);
    const snoozedEnd = snoozeEnd(rec);
    const soon = interviewSoon(rec);
    const clash = interviewClash(job.id, rec);
    const clashText = interviewClashText(job.id, rec, clash);
    const offer = offerDeadlineState(rec);
    const employer = employerOf(job);
    const employerKey = (employer && employer.company_key) || "";
    const note = String(rec?.note || "").trim();
    const employerScore = companyScoreOf(job);
    return `<article class="board-card${due ? " due" : ""}${soon ? " soon" : ""}${clash ? " clash" : ""}" draggable="true" tabindex="0" data-job="${esc(job.id)}"
                 aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight"
                 aria-label="${esc(`${job.title}${job.company ? ` · ${job.company}` : ""}${due ? "，待跟进" : ""}${soon ? "，30 分钟内开始" : ""}${clash ? `，与「${interviewJobTitle(clash.id)}」时间冲突` : ""}，Alt 加左右方向键移动阶段`)}">
      <div class="board-top">
        <span class="board-company">${employerKey
          ? `<a class="company-link" href="#/companies/${encodeURIComponent(employerKey)}" data-company="${esc(employerKey)}" title="打开「${esc(employer.name || job.company)}」的公司背调">${esc(job.company || "—")}</a>`
          : esc(job.company || "—")}</span>
        ${watchButton("job", job.id, job.title)}
      </div>
      <div class="board-title link">${esc(job.title)}</div>
      <div class="board-meta">
        ${job.salary ? `<span>${esc(job.salary)}</span>` : ""}
        ${job.city ? `<span>${esc(job.city)}</span>` : ""}
        ${job.fit && job.fit.total != null ? `<span class="board-fit${fitNeutral(job.fit) ? " approx" : ""}" title="${esc(fitTitle(job.fit))}">${fitNeutral(job.fit) ? "≈" : ""}${fmt(job.fit.total)}</span>` : ""}
        ${employerScore != null ? `<span class="board-employer" title="公司评分 ${fmt(employerScore, 1)} / 100">${icon("building")}${fmt(employerScore, 1)}</span>` : ""}
        ${due ? `<span class="board-due${soon ? " soon" : ""}${offer?.expired ? " expired" : ""}">${icon("alert")}${esc(followupReason(rec).split(" · ")[0])}${soon ? " · 30 分钟内" : ""}</span>` : ""}
        ${clash ? `<span class="board-due clash" title="${esc(clashText)}">${icon("alert")}时间冲突</span>` : ""}
        ${snoozedEnd ? `<span class="board-due snoozed" title="延后至 ${esc(snoozeDay(rec))}">${icon("clock")}${esc(snoozeDay(rec))}</span>` : ""}
      </div>
      ${note ? `<div class="board-note" title="${esc(note)}">${icon("chat")}${esc(note)}</div>` : ""}
      <div class="board-foot">
        ${boardStageSelect(job)}
        ${job.fit && job.fit.resume_state === "stale" ? `<span class="board-stale" title="母版已变化，建议重新适配">${icon("refresh")}需重适配</span>` : ""}
      </div>
    </article>`;
  };
  const BOARD_STAGES = [{ id: "", label: "未标记" }, ...STAGES.map((s) => ({ id: s.id, label: s.label }))];
  const BOARD_INBOX_PREVIEW = 8;
  let inboxExpanded = false;
  const boardHTML = (rows) => BOARD_STAGES.map(({ id, label }) => {
    const items = rows.filter((job) => (trackOf(job.id)?.stage || "") === id);
    const collapsible = !id && items.length > BOARD_INBOX_PREVIEW;
    const shown = collapsible && !inboxExpanded ? items.slice(0, BOARD_INBOX_PREVIEW) : items;
    const more = items.length - shown.length;
    return `<section class="board-col ${id || "none"}${collapsible && inboxExpanded ? " expanded" : ""}" data-stage="${id}" aria-label="${esc(label)}，${items.length} 个岗位">
      <header class="board-col-head"><span class="stage-dot"></span><span>${esc(label)}</span><em>${items.length}</em>${collapsible
        ? `<button type="button" class="board-col-toggle" data-board-expand="none" aria-expanded="${inboxExpanded}"
             aria-controls="board-cards-none" title="${inboxExpanded ? "收起未标记列，只保留前 8 个" : `展开全部 ${items.length} 个未标记岗位，列内滚动查看`}">${inboxExpanded ? "收起" : "展开"}</button>` : ""}</header>
      <div class="board-cards" id="board-cards-${id || "none"}">${shown.map(boardCardHTML).join("") || `<div class="board-empty">拖动岗位到这里</div>`}${more
        ? `<button type="button" class="board-more" data-board-more="none">还有 ${more} 个 · 在列表中查看</button>` : ""}</div>
    </section>`;
  }).join("");

  const queryState = () => ({
    view: view.mode === "board" ? "board" : "",
    q: view.q.trim(),
    city: view.city,
    fit: view.fit,
    salary: view.salary,
    stage: view.stage,
    sort: view.sort === "fit" ? "" : view.sort,
    dir: view.dir === sortDefaults[view.sort] ? "" : view.dir,
    size: view.size === 25 ? "" : view.size,
    page: view.page === 1 ? "" : view.page,
  });

  const matchesStage = (job) => {
    const rec = trackOf(job.id);
    if (view.stage === "none") return !rec;
    if (view.stage === "tracked") return !!rec;
    if (view.stage === "due") return followupDue(rec);
    if (view.stage === "snoozed") return !!snoozeEnd(rec);
    if (view.stage) return !!rec && rec.stage === view.stage;
    return true;
  };

  const syncStageOptions = () => {
    const fresh = stageCounts(jobs);
    const freshDue = jobs.filter((job) => followupDue(trackOf(job.id))).length;
    const freshSnoozed = jobs.filter((job) => !!snoozeEnd(trackOf(job.id))).length;
    const select = $("#l-job-stage");
    if (select) {
      const setLabel = (value, text) => {
        const option = select.querySelector(`option[value="${value}"]`);
        if (option) option.textContent = text;
      };
      setLabel("tracked", `跟进中（${fresh.total}）`);
      setLabel("due", `待行动（${freshDue}）`);
      setLabel("snoozed", `延后中（${freshSnoozed}）`);
      setLabel("none", `未标记（${fresh.none}）`);
      STAGES.forEach((s) => setLabel(s.id, `${s.label}（${fresh[s.id]}）`));
    }
    const hint = $("#job-hint");
    if (hint) hint.textContent = `${watch.jobs.size} 关注 · ${fresh.total} 跟进 · ${freshDue} 待行动 · ${cities.length} 个城市`;
  };

  const bindStageCells = () => {
    $$("[data-stage-job]").forEach((select) => {
      select.addEventListener("click", (event) => event.stopPropagation());
      select.addEventListener("change", (event) => {
        event.stopPropagation();
        const id = select.dataset.stageJob;
        const stage = select.value;
        const before = snapshotTrack(id);
        if (stage) setTrackStage(id, stage); else clearTrack(id);
        const rec = trackOf(id);
        syncAllStageCells();
        const rawTitle = select.dataset.stageTitle || "";
        const title = rawTitle.length > 18 ? rawTitle.slice(0, 18) + "…" : rawTitle;
        toast(rec ? `已标记「${stageMeta(rec.stage).label}」 · ${title}` : `已清除跟进 · ${title}`, "ok", {
          label: "撤销",
          onClick: () => {
            restoreTrack(id, before);
            if ($("#job-rows")) paint();
            toast("已撤销阶段修改", "info");
          },
        });
        if (view.mode === "board") {
          paint();
          document.querySelector(`#job-board .board-card[data-job="${id}"]`)?.focus({ preventScroll: true });
        } else if (matchesStage({ id })) syncStageOptions();
        else paint();
      });
    });
  };

  let copyRows = [];
  const paint = () => {
    const needle = view.q.trim().toLowerCase();
    snoozeCount = jobs.filter((job) => !!snoozeEnd(trackOf(job.id))).length;
    const hit = (value) => String(value || "").toLowerCase().includes(needle);
    const visible = jobs.filter((job) => {
      if (needle && !hit(job.title) && !hit(job.company) && !hit(job.city) && !hit(trackOf(job.id)?.note)) return false;
      if (view.city && job.city !== view.city) return false;
      if (view.fit === "watch" && !watch.jobs.has(job.id)) return false;
      if (view.fit === "watch_company" && !isWatchedCompany(job)) return false;
      if (view.fit === "fit" && fitOf(job) < 0) return false;
      if (view.fit === "unfit" && fitOf(job) >= 0) return false;
      if (/^[A-D]$/.test(view.fit) && (!job.fit || job.fit.grade !== view.fit)) return false;
      if (view.salary) {
        const parsed = salaryMonthly(job.salary);
        if (!parsed || parsed.mid < Number(view.salary) * 1000) return false;
      }
      if (!matchesStage(job)) return false;
      return true;
    });
    const dir = view.dir === "asc" ? 1 : -1;
    const companyAsc = (a, b) => String(a.company || "").localeCompare(String(b.company || ""), "zh-CN");
    const titleAsc = (a, b) => String(a.title).localeCompare(String(b.title), "zh-CN");
    const compare = {
      fit: (a, b) => {
        const fa = a.fit && a.fit.total != null ? Number(a.fit.total) : null;
        const fb = b.fit && b.fit.total != null ? Number(b.fit.total) : null;
        if (fa == null && fb == null) return titleAsc(a, b);
        if (fa == null) return 1;
        if (fb == null) return -1;
        return dir * (fa - fb) || titleAsc(a, b);
      },
      salary: (a, b) => {
        const sa = salaryMonthly(a.salary);
        const sb = salaryMonthly(b.salary);
        if (!sa && !sb) return fitOf(b) - fitOf(a);
        if (!sa) return 1;
        if (!sb) return -1;
        return dir * (sa.mid - sb.mid) || fitOf(b) - fitOf(a);
      },
      employer: (a, b) => {
        const sa = companyScoreOf(a);
        const sb = companyScoreOf(b);
        if (sa == null && sb == null) return fitOf(b) - fitOf(a) || titleAsc(a, b);
        if (sa == null) return 1;
        if (sb == null) return -1;
        return dir * (sa - sb) || fitOf(b) - fitOf(a);
      },
      track: (a, b) => {
        const ta = (trackOf(a.id) || {}).at || "";
        const tb = (trackOf(b.id) || {}).at || "";
        if (ta && !tb) return -1;
        if (!ta && tb) return 1;
        return dir * tb.localeCompare(ta) || fitOf(b) - fitOf(a);
      },
      urgency: (a, b) => {
        const rank = (rec) => rec ? ({ offer: 0, interview: 1, applied: 2, todo: 3 }[rec.stage] ?? 4) : 4;
        const ra = trackOf(a.id);
        const rb = trackOf(b.id);
        const delta = rank(ra) - rank(rb);
        if (delta) return delta;
        if (ra?.stage === "offer" && rb?.stage === "offer") {
          const oa = offerDeadline(ra) || Infinity;
          const ob = offerDeadline(rb) || Infinity;
          if (oa !== ob) return oa - ob;
        }
        return (Date.parse(ra?.at) || 0) - (Date.parse(rb?.at) || 0) || titleAsc(a, b);
      },
      snooze: (a, b) => {
        const ua = snoozeEnd(trackOf(a.id));
        const ub = snoozeEnd(trackOf(b.id));
        if (ua && !ub) return -1;
        if (!ua && ub) return 1;
        return dir * ((ua || 0) - (ub || 0)) || fitOf(b) - fitOf(a);
      },
      company: (a, b) => dir * companyAsc(a, b) || fitOf(b) - fitOf(a),
      title: (a, b) => dir * titleAsc(a, b) || fitOf(b) - fitOf(a),
    }[view.sort] || ((a, b) => fitOf(b) - fitOf(a));
    visible.sort(compare);
    saveJobOrder(visible.map((job) => job.id));

    const pages = Math.max(1, Math.ceil(visible.length / view.size));
    view.page = Math.min(pages, Math.max(1, view.page));
    const pageRows = visible.slice((view.page - 1) * view.size, view.page * view.size);
    const emptyText = !jobs.length
      ? "还没有岗位数据<br><span class=\"chart-note\">上方采集面板已展开，填好关键词后点「开始采集」</span>"
      : view.fit === "watch" && !needle && !view.city && !view.stage && !view.salary
        ? "还没有关注的岗位<br><span class=\"chart-note\">点击列表或详情页的星标，把目标岗位加入关注</span>"
        : view.fit === "watch_company" && !needle && !view.city && !view.stage && !view.salary
          ? "关注的公司还没有在库岗位<br><span class=\"chart-note\">在公司页点星标关注雇主，这里会汇总它们的在招岗位</span>"
          : view.stage === "due" && !needle && !view.city && !view.fit && !view.salary
          ? `暂无待行动岗位<br><span class="chart-note">Offer、面试中的岗位，以及超 7 天未跟进的投递会出现在这里${snoozeCount ? `；另有 ${snoozeCount} 个岗位已延后` : ""}</span>`
          : view.stage === "snoozed" && !needle && !view.city && !view.fit && !view.salary
            ? "没有延后的岗位<br><span class=\"chart-note\">在岗位详情点「延后 3 天」，到期前不再计入待行动</span>"
            : view.stage && !needle && !view.city && !view.fit && !view.salary
              ? "这个阶段还没有岗位<br><span class=\"chart-note\">在「进度」列选择阶段即可开始跟进</span>"
              : "没有匹配的岗位<br><span class=\"chart-note\">调整关键词、城市、适配度、薪资或进度</span>";
    const emptyAction = !jobs.length
      ? `<div class="empty-action"><button type="button" class="btn btn-sm" data-open-crawl>${icon("play")}去填写关键词</button></div>`
      : view.stage === "due" && !needle && !view.city && !view.fit && !view.salary && snoozeCount
        ? `<div class="empty-action"><a class="btn btn-ghost btn-sm" href="#/jobs?stage=snoozed">${icon("clock")}查看已延后（${snoozeCount}）</a></div>`
        : (needle || view.city || view.fit || view.stage || view.salary)
          ? `<div class="empty-action"><button type="button" class="btn btn-ghost btn-sm" data-reset-filters="job">清除搜索与筛选</button></div>`
          : "";
    $("#job-rows").innerHTML = pageRows.map(rowHTML).join("")
      || `<tr><td colspan="7"><div class="empty">${emptyText}${emptyAction}</div></td></tr>`;
    $("#job-board").innerHTML = view.mode === "board"
      ? (visible.length ? boardHTML(visible) : `<div class="empty">${emptyText}${emptyAction}</div>`)
      : "";
    $("#job-table").hidden = view.mode === "board";
    $("#job-board").hidden = view.mode !== "board";
    $("#job-foot").hidden = view.mode === "board";
    $$("[data-job-view]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.jobView === view.mode));
    });
    const stageField = $("#l-job-stage")?.closest(".field");
    if (stageField) stageField.hidden = view.mode === "board";
    const sizeField = $("#l-job-size")?.closest(".field");
    if (sizeField) sizeField.hidden = view.mode === "board";
    const modeNote = $("#job-mode-note");
    if (modeNote) {
      modeNote.hidden = view.mode !== "board";
      modeNote.textContent = view.mode === "board" ? "看板 · 拖动卡片或 Alt + ←/→ 更新阶段" : "";
    }
    $("#job-count").textContent = visible.length === jobs.length
      ? `${jobs.length} 条`
      : `${visible.length} / ${jobs.length} 条`;
    const neutralCount = visible.filter((job) => fitNeutral(job.fit)).length;
    const fitNote = $("#job-fit-note");
    if (fitNote) {
      fitNote.hidden = !neutralCount;
      fitNote.textContent = neutralCount ? `${neutralCount}/${visible.length} 中性适配` : "";
      fitNote.title = "评分规则未定义或维度没有取到有效数据时，框架给出中性 60 分；它只是占位，不代表岗位真实匹配度";
    }
    const mids = visible.map((job) => salaryMonthly(job.salary)).filter(Boolean)
      .map((parsed) => parsed.mid).sort((a, b) => a - b);
    const median = mids.length
      ? (mids.length % 2
        ? mids[(mids.length - 1) / 2]
        : (mids[mids.length / 2 - 1] + mids[mids.length / 2]) / 2)
      : null;
    const salaryStat = $("#job-salary-stat");
    if (salaryStat) salaryStat.textContent = median == null ? "" : ` · 中位 ${salaryK(median)}/月`;
    copyRows = visible;
    const copyBtn = $("#l-job-copy");
    if (copyBtn) {
      copyBtn.disabled = !copyRows.length;
      copyBtn.title = copyRows.length ? `复制当前筛选的 ${copyRows.length} 个岗位（TSV，可粘贴到表格）` : "当前筛选没有可复制的岗位";
      copyBtn.setAttribute("aria-label", copyBtn.title);
    }
    const watchOpt = $("#l-job-fit").querySelector('option[value="watch"]');
    if (watchOpt) watchOpt.textContent = `已关注岗位（${watch.jobs.size}）`;
    const watchCompanyOpt = $("#l-job-fit").querySelector('option[value="watch_company"]');
    if (watchCompanyOpt) watchCompanyOpt.textContent = `已关注公司（${jobs.filter(isWatchedCompany).length}）`;
    const compareLink = $("#job-compare-link");
    if (compareLink) {
      compareLink.title = watch.jobs.size ? `并排对比已关注的 ${watch.jobs.size} 个岗位` : "并排对比已关注岗位";
      const compareCount = $("#job-compare-count");
      if (compareCount) compareCount.textContent = watch.jobs.size ? ` ${watch.jobs.size}` : "";
    }
    syncStageOptions();
    $("#job-foot").innerHTML = pager(visible.length, { page: view.page, size: view.size, id: "jobs" });
    bindPager("jobs", view.page, pages, (next) => {
      view.page = next;
      syncQuery("/jobs", queryState());
      paint();
      $("#job-table-card").scrollIntoView({ block: "start", behavior: "smooth" });
    });
    bindNav();
    bindStageCells();
    paintSortSelect($("#l-job-sort"), view.sort, view.dir, sortDefaults);
    paintSortHeaders($("#job-table-card"), view.sort, view.dir);
  };

  const apply = (resetPage) => {
    if (resetPage) view.page = 1;
    syncQuery("/jobs", queryState());
    paint();
  };

  $("#l-job-q").addEventListener("input", debounce((event) => {
    view.q = event.target.value;
    apply(true);
  }, 120));
  bindSearchClear($("#l-job-q"));
  $("#l-job-city").addEventListener("change", (event) => { view.city = event.target.value; apply(true); });
  $("#l-job-fit").addEventListener("change", (event) => { view.fit = event.target.value; apply(true); });
  $("#l-job-salary").addEventListener("change", (event) => { view.salary = event.target.value; apply(true); });
  $("#l-job-stage").addEventListener("change", (event) => { view.stage = event.target.value; apply(true); });
  $("#l-job-sort").addEventListener("change", (event) => {
    view.sort = event.target.value;
    view.dir = sortDefaults[view.sort];
    apply(true);
  });
  $("#l-job-size").addEventListener("change", (event) => {
    view.size = Number(event.target.value) === 50 ? 50 : 25;
    saveJobViewPref(view.mode, view.size);
    apply(true);
  });
  const resetFilters = () => {
    view.q = ""; view.city = ""; view.fit = ""; view.salary = ""; view.stage = ""; view.sort = "fit"; view.dir = sortDefaults.fit; view.size = 25; view.page = 1;
    saveJobViewPref(view.mode, view.size);
    $("#l-job-q").value = "";
    $("#l-job-city").value = "";
    $("#l-job-fit").value = "";
    $("#l-job-salary").value = "";
    $("#l-job-stage").value = "";
    $("#l-job-sort").value = "fit";
    $("#l-job-size").value = "25";
    apply(true);
  };
  $("#l-job-reset").addEventListener("click", resetFilters);
  $("#l-job-copy").addEventListener("click", async () => {
    if (!copyRows.length) return;
    const lines = ["岗位\t公司\t薪资\t城市\t适配度（≈中性占位）\t等级\t进度"];
    copyRows.forEach((job) => {
      const rec = trackOf(job.id);
      lines.push([
        job.title,
        job.company || "",
        job.salary || "",
        job.city || "",
        job.fit && job.fit.total != null ? `${fitNeutral(job.fit) ? "≈" : ""}${fmt(job.fit.total)}` : "",
        (job.fit && job.fit.grade) || "",
        rec ? stageMeta(rec.stage).label : "未标记",
      ].map(tsvCell).join("\t"));
    });
    try {
      await copyText(lines.join("\n"));
      toast(`已复制 ${copyRows.length} 个岗位，可直接粘贴到表格`);
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
  bindSortHeaders($("#job-table-card"), () => view, sortDefaults, (sort, dir) => {
    view.sort = sort;
    view.dir = dir;
    $("#l-job-sort").value = sort;
    apply(true);
  });
  $("#job-rows").addEventListener("click", (event) => {
    if (event.target.closest("[data-reset-filters]")) {
      resetFilters();
      $("#l-job-q").focus();
      return;
    }
    if (event.target.closest("[data-open-crawl]")) openCrawl();
  });

  $$("[data-job-view]").forEach((btn) => btn.addEventListener("click", () => {
    const mode = btn.dataset.jobView === "board" ? "board" : "list";
    if (mode === view.mode) return;
    view.mode = mode;
    if (mode === "board") {
      view.stage = "";
      const stageSelect = $("#l-job-stage");
      if (stageSelect) stageSelect.value = "";
    }
    saveJobViewPref(view.mode, view.size);
    apply(true);
    document.querySelector(`[data-job-view="${mode}"]`)?.focus();
    toast(mode === "board" ? "已切换到看板 · 拖动卡片或按 Alt + ←/→ 更新阶段" : "已切换到列表");
  }));

  const boardEl = $("#job-board");
  const focusBoardJob = (id) => {
    const card = [...boardEl.querySelectorAll(".board-card")].find((node) => node.dataset.job === id);
    if (!card) return;
    card.focus({ preventScroll: true });
    card.scrollIntoView({ block: "nearest", inline: "nearest" });
  };
  const moveBoardJob = (id, stage) => {
    const before = snapshotTrack(id);
    if (stage) setTrackStage(id, stage); else clearTrack(id);
    const rec = trackOf(id);
    const rawTitle = (jobs.find((job) => job.id === id) || {}).title || "";
    const title = rawTitle.length > 18 ? rawTitle.slice(0, 18) + "…" : rawTitle;
    toast(rec ? `已标记「${stageMeta(rec.stage).label}」 · ${title}` : `已清除跟进 · ${title}`, "ok", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        paint();
        focusBoardJob(id);
        toast("已撤销阶段修改", "info");
      },
    });
    paint();
    focusBoardJob(id);
  };
  boardEl.addEventListener("click", (event) => {
    if (event.target.closest("[data-board-expand]")) {
      inboxExpanded = !inboxExpanded;
      paint();
      boardEl.querySelector("[data-board-expand]")?.focus({ preventScroll: true });
      toast(inboxExpanded ? "已展开未标记列 · 列内滚动查看" : "已收起未标记列 · 保留前 8 个", "info");
      return;
    }
    if (event.target.closest("[data-board-more]")) {
      view.mode = "list";
      view.stage = "none";
      apply(true);
      const stageSelect = $("#l-job-stage");
      if (stageSelect) {
        stageSelect.value = "none";
        stageSelect.focus();
      }
      toast("已切到列表 · 仅看未标记岗位", "info");
      return;
    }
    if (event.target.closest("[data-reset-filters]")) {
      resetFilters();
      $("#l-job-q").focus();
      return;
    }
    if (event.target.closest("[data-open-crawl]")) {
      openCrawl();
      return;
    }
    const card = event.target.closest?.(".board-card");
    if (!card || event.target.closest("a, [data-watch], [data-stage-job]")) return;
    goJob(card.dataset.job);
  });
  boardEl.addEventListener("keydown", (event) => {
    const card = event.target.closest?.(".board-card");
    if (!card || event.target.closest("a, [data-watch], [data-stage-job]")) return;
    if (event.key === "Enter") {
      event.preventDefault();
      goJob(card.dataset.job);
      return;
    }
    if (event.altKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
      const order = BOARD_STAGES.map((step) => step.id);
      const current = trackOf(card.dataset.job)?.stage || "";
      const index = Math.max(0, order.indexOf(current));
      const next = Math.min(order.length - 1, Math.max(0, index + (event.key === "ArrowRight" ? 1 : -1)));
      event.preventDefault();
      event.stopPropagation();
      if (next === index) {
        toast(event.key === "ArrowRight" ? "已经是最后一列" : "已经是第一列", "info");
        return;
      }
      moveBoardJob(card.dataset.job, order[next]);
      return;
    }
    if (event.ctrlKey || event.metaKey || event.shiftKey || !/^Arrow(?:Left|Right|Up|Down)$/.test(event.key)) return;
    const column = card.closest(".board-col");
    if (!column) return;
    const columnCards = [...column.querySelectorAll(".board-card")];
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      event.stopPropagation();
      const index = columnCards.indexOf(card);
      const target = columnCards[index + (event.key === "ArrowDown" ? 1 : -1)];
      if (target) {
        target.focus({ preventScroll: true });
        target.scrollIntoView({ block: "nearest" });
      }
      return;
    }
    const columns = [...boardEl.querySelectorAll(".board-col")];
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const origin = card.getBoundingClientRect();
    const originY = origin.top + origin.height / 2;
    for (let index = columns.indexOf(column) + direction; index >= 0 && index < columns.length; index += direction) {
      const candidates = [...columns[index].querySelectorAll(".board-card")];
      if (!candidates.length) continue;
      const target = candidates.reduce((best, node) => {
        const rect = node.getBoundingClientRect();
        const distance = Math.abs(rect.top + rect.height / 2 - originY);
        return distance < best.distance ? { node, distance } : best;
      }, { node: null, distance: Infinity }).node;
      if (!target) return;
      event.preventDefault();
      event.stopPropagation();
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: "nearest", inline: "nearest" });
      return;
    }
  });
  boardEl.addEventListener("dragstart", (event) => {
    const card = event.target.closest?.(".board-card");
    if (!card || !event.dataTransfer) return;
    event.dataTransfer.setData("text/plain", card.dataset.job);
    event.dataTransfer.effectAllowed = "move";
    card.classList.add("dragging");
  });
  boardEl.addEventListener("dragend", () => {
    boardEl.querySelectorAll(".dragging, .drop-target").forEach((node) => {
      node.classList.remove("dragging", "drop-target");
    });
  });
  boardEl.addEventListener("dragover", (event) => {
    const col = event.target.closest?.(".board-col");
    if (!col) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    boardEl.querySelectorAll(".board-col.drop-target").forEach((node) => {
      if (node !== col) node.classList.remove("drop-target");
    });
    col.classList.add("drop-target");
  });
  boardEl.addEventListener("dragleave", (event) => {
    const col = event.target.closest?.(".board-col");
    if (col && !col.contains(event.relatedTarget)) col.classList.remove("drop-target");
  });
  boardEl.addEventListener("drop", (event) => {
    const col = event.target.closest?.(".board-col");
    if (!col) return;
    event.preventDefault();
    col.classList.remove("drop-target");
    const id = event.dataTransfer?.getData("text/plain") || "";
    const stage = col.dataset.stage || "";
    if (!id || (trackOf(id)?.stage || "") === stage) return;
    moveBoardJob(id, stage);
  });

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

  const savedCrawl = readCrawlForm();
  if (savedCrawl) {
    const setText = (selector, value) => {
      const node = $(selector);
      if (node && typeof value === "string") node.value = value;
    };
    setText("#f-query", savedCrawl.query);
    setText("#f-city", savedCrawl.city);
    setText("#f-pages", savedCrawl.pages);
    setText("#f-limit", savedCrawl.limit);
    $$("#crawl-panel select[data-filter]").forEach((node) => {
      const value = savedCrawl.filters?.[node.dataset.filter];
      if (typeof value === "string" && [...node.options].some((opt) => opt.value === value)) node.value = value;
    });
    if (Array.isArray(savedCrawl.platforms)) {
      $$("input[data-platform]").forEach((node) => {
        node.checked = savedCrawl.platforms.includes(node.dataset.platform);
      });
    }
    if (savedCrawl.toggles && typeof savedCrawl.toggles === "object") {
      $$("input[data-toggle]").forEach((node) => {
        const checked = savedCrawl.toggles[node.dataset.toggle];
        if (typeof checked === "boolean") node.checked = checked;
      });
    }
  }
  const runBtn = $("#btn-run"), stopBtn = $("#btn-stop"), noCrawlBtn = $("#btn-nocrawl");
  const crawlState = $("#crawl-state");
  const crawlPanel = $("#crawl-panel");
  const showError = (text) => {
    const box = $("#f-error");
    box.textContent = text || "";
    box.hidden = !text;
  };
  const crawlFormSnapshot = () => ({
    query: $("#f-query").value.trim(),
    city: $("#f-city").value.trim(),
    pages: $("#f-pages").value,
    limit: $("#f-limit") ? $("#f-limit").value : "",
    filters: Object.fromEntries($$("#crawl-panel select[data-filter]")
      .map((node) => [node.dataset.filter, node.value])),
    platforms: $$("input[data-platform]:checked").map((node) => node.dataset.platform),
    toggles: Object.fromEntries($$("input[data-toggle]")
      .map((node) => [node.dataset.toggle, node.checked])),
  });

  function paintCrawl() {
    const run = crawlRun;
    const active = !!run;
    runBtn.disabled = active;
    noCrawlBtn.disabled = active;
    stopBtn.disabled = !active || run.stopping;
    stopBtn.textContent = run?.stopping ? "正在停止…" : "停止";
    crawlState.textContent = active ? (run.stopping ? "STOPPING" : "RUNNING") : "READY";
    crawlState.classList.toggle("running", active && !run.stopping);
    crawlState.classList.toggle("stopping", !!run?.stopping);
    crawlState.title = active
      ? run.stopping
        ? `${run.label} · 已请求停止，等待进程退出`
        : `${run.label} · ${run.clock} 开始 · 切换页面不会中断`
      : "当前没有正在运行的流水线";
    runBtn.title = active ? `${run.label}正在运行，先停止再开始新的任务` : "";
  }
  // 回到岗位页时把仍在运行的采集重新挂到控件上，避免重复启动或丢失停止入口。
  paintCrawl();
  if (crawlRun) crawlPanel.open = true;
  document.addEventListener("crawlchange", () => {
    if (runBtn.isConnected) paintCrawl();
  }, { signal: pageAbort.signal });

  function openCrawl() {
    const panel = $("#crawl-panel");
    if (!panel) return;
    panel.open = true;
    panel.scrollIntoView({ block: "start", behavior: "smooth" });
    setTimeout(() => $("#f-query").focus(), 80);
  }
  $("#btn-open-crawl").addEventListener("click", openCrawl);

  async function finishCrawl(run, event) {
    if (crawlRun !== run) return;
    crawlRun = null;
    if (runBtn.isConnected) paintCrawl();
    crawlChange();
    chatLog("step", "流水线", run.stopping
      ? "已停止进程，正在刷新数据…"
      : event?.code === 0 ? "运行结束，正在刷新数据…" : `进程退出（退出码 ${event?.code}）`);
    state.data = null;
    state.cloud = null;
    state.filters = null;
    const fresh = await call("data");
    if (fresh) state.data = fresh;
    clearDetailCache();
    const backend = event?.outcome && typeof event.outcome === "object" ? event.outcome : null;
    const details = backend?.summary && typeof backend.summary === "object" ? backend.summary : null;
    const failed = !run.stopping && (event?.code !== 0 || backend?.ok === false);
    // 进程正常退出但后端标记 not ok：部分背调/打分任务失败，不算彻底中断。
    const partial = failed && backend?.ok === false && !details?.error;
    const summary = run.stopping ? "流水线已停止" : partial ? "流水线部分完成" : failed ? "流水线中断" : "流水线结束";
    const facts = crawlSummaryParts(details, state.data?.jobs?.length);
    const elapsed = crawlElapsed(run.startedAt);
    chatLog("step", "流水线", run.stopping
      ? `已停止 · 耗时 ${elapsed}`
      : `耗时 ${elapsed}${facts.length ? ` · ${facts.join(" · ")}` : ""}`);
    const jobTotal = Math.round(Number(state.data?.jobs?.length));
    writeLocal(CRAWL_LAST_KEY, {
      at: new Date().toISOString(),
      status: run.stopping ? "stopped" : partial ? "partial" : failed ? "failed" : "done",
      clock: nowTime().slice(0, 5),
      elapsed,
      jobs: Number.isFinite(jobTotal) ? jobTotal : null,
      summary: {
        companies: details?.companies ?? null,
        evidence: details?.evidence ?? null,
        fits: details?.fits ?? null,
        resume: details?.resume?.ok ? { ok: true, confirmed: !!details.resume.confirmed } : null,
      },
    });
    const path = parseHash().path;
    const livePage = path === "/" || path === "/overview" || path === "/jobs" || path === "/companies"
      || path.startsWith("/companies/") || path === "/compare" || path === "/job-compare"
      || path === "/skills" || path === "/modules";
    // 简历/设置页可能有未保存输入，后台任务结束不强制重绘，只提示可回岗位页查看。
    let message;
    if (livePage) {
      await router();
      const brief = facts.slice(0, 2).join(" · ");
      message = `${summary}${brief ? ` · ${brief}` : ""}，${path === "/jobs" ? "列表" : "数据"}已刷新`;
    } else {
      message = `${summary}${facts.length ? ` · ${facts[0]}` : ""}，回到岗位页可查看最新列表`;
    }
    // 用户主动停止时人就在窗口前，不再发系统通知；自然结束或中断才走桌面提醒。
    if (run.stopping) {
      if (document.visibilityState === "visible" && document.hasFocus()) toast(message);
    } else {
      deliverTimedReminder(message, failed ? "warn" : "ok", {
        title: summary,
        body: failed
          ? partial
            ? `部分任务未完成${facts.length ? `：${facts.join(" · ")}` : ""}，点击查看运行日志`
            : `进程退出（退出码 ${event?.code}），点击查看运行日志`
          : `${run.label}完成${facts.length ? `：${facts.join(" · ")}` : ""}，点击回到岗位列表`,
        href: "#/jobs",
      });
    }
  }

  function start(noCrawl) {
    if (crawlRun) {
      toast("流水线正在运行，请先停止", "warn");
      openCrawl();
      return;
    }
    const query = $("#f-query").value.trim();
    if (!query && !noCrawl) {
      showError("请先填写搜索关键词");
      $("#f-query").focus();
      return;
    }
    showError("");
    writeLocal(CRAWL_FORM_KEY, crawlFormSnapshot());
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
    // 薪资 / 经验 / 学历 / 行业四个下拉直接对应 BOSS 的筛选码，不能只渲染不提交。
    $$("#crawl-panel select[data-filter]").forEach((node) => {
      const value = node.value.trim();
      if (value) args[node.dataset.filter] = value;
    });
    const run = {
      id: null,
      label: noCrawl ? "只重算" : "采集",
      noCrawl: !!noCrawl,
      startedAt: Date.now(),
      clock: nowTime().slice(0, 5),
      stopping: false,
    };
    crawlRun = run;
    paintCrawl();
    crawlChange();
    try {
      run.id = streamRun(args, (event) => finishCrawl(run, event));
    } catch (exc) {
      crawlRun = null;
      paintCrawl();
      crawlChange();
      showError(`无法启动流水线：${exc?.message || "未知错误"}`);
      chatLog("err", "流水线", `启动失败：${exc?.message || "未知错误"}`);
      return;
    }
    // 停止请求可能早于 streamId 返回，拿到句柄后再补发取消。
    if (run.stopping && run.id) window.api.cancel(run.id);
    else if (crawlRun === run) paintCrawl();
  }

  runBtn.addEventListener("click", () => start(false));
  noCrawlBtn.addEventListener("click", () => start(true));
  stopBtn.addEventListener("click", () => {
    const run = crawlRun;
    if (!run || run.stopping) return;
    run.stopping = true;
    paintCrawl();
    crawlChange();
    if (run.id) window.api.cancel(run.id);
    chatLog("step", "流水线", "已请求停止，等待进程退出…");
  });

  paint();
  takeBackScroll();
  document.addEventListener("watchchange", paint, { signal: pageAbort.signal });
  document.addEventListener("trackchange", (event) => {
    if (!$("#job-rows")) return;
    const activeId = document.activeElement?.closest?.("tr[data-job], .board-card")?.dataset.job;
    const focusId = event.detail?.id || activeId || null;
    paint();
    const rowSelector = listKeyboardContext()?.row || "tr[data-job]";
    const rows = [...$("#job-table-card").querySelectorAll(rowSelector)];
    const same = focusId ? rows.find((row) => row.dataset.job === focusId) : null;
    const target = same || rows[0];
    if (target) {
      target.focus({ preventScroll: true });
      if (!same) target.scrollIntoView({ block: "nearest" });
    } else {
      $("#l-job-q")?.focus();
    }
  }, { signal: pageAbort.signal });
  const repaintListKeepingFocus = () => {
    if (!$("#job-rows")) return;
    const activeId = document.activeElement?.closest?.("tr[data-job], .board-card")?.dataset.job;
    paint();
    if (!activeId) return;
    const rowSelector = listKeyboardContext()?.row || "tr[data-job]";
    const row = [...$("#job-table-card").querySelectorAll(rowSelector)]
      .find((node) => node.dataset.job === activeId);
    row?.focus({ preventScroll: true });
  };
  document.addEventListener("snoozeexpired", repaintListKeepingFocus, { signal: pageAbort.signal });
  document.addEventListener("interviewchange", repaintListKeepingFocus, { signal: pageAbort.signal });
  document.addEventListener("offerchange", repaintListKeepingFocus, { signal: pageAbort.signal });
}

// ---------------------------------------------------------------- 岗位详情
async function pageJobDetail(id) {
  pageEl().innerHTML = skeletonPage("detail");
  const job = await cachedDetail("job", { job_id: id });
  if (!job) {
    pageEl().innerHTML = emptyWithAction("没有这个岗位，可能已下线或数据已刷新", "#/jobs", "返回岗位列表");
    return;
  }
  if (!state.resume) await loadBootstrap();
  crumb("岗位", job.title);

  const company = job.company || {};
  const fit = job.fit || {};
  const fitDims = fit.dimensions || {};
  const neutralFit = fitNeutral(fit);
  const [fitTone] = fit.total != null ? toneOf(fit.total) : ["tone-good"];
  const rec = trackOf(id);
  const dueReason = followupReason(rec);
  const snoozed = snoozedLabel(rec);
  const skills = job.skills || [];
  const coverage = skillCoverage(skills);
  const fromJobsList = /^#\/jobs(?:\?|$)/.test(backHash(""));
  const order = fromJobsList ? jobOrder() : [];
  const orderPos = order.indexOf(id);
  const prevId = orderPos > 0 ? order[orderPos - 1] : "";
  const nextId = orderPos >= 0 && orderPos < order.length - 1 ? order[orderPos + 1] : "";
  const jobTitles = new Map((state.data?.jobs || []).map((item) => [item.id, item.title]));
  const stepTip = (target, label) => target
    ? `${label}：${jobTitles.get(target) || target}（快捷键 ${label === "上一岗" ? "[" : "]"}）`
    : `已经是${label === "上一岗" ? "第一个" : "最后一个"}岗位`;
  const stepBar = orderPos >= 0 && order.length > 1 ? `
    <div class="detail-steps" aria-label="在当前筛选的岗位间切换">
      <button type="button" class="btn btn-ghost btn-sm" data-job-step="${esc(prevId)}"
        ${prevId ? "" : "disabled"} title="${esc(stepTip(prevId, "上一岗"))}"
        aria-label="${esc(stepTip(prevId, "上一岗"))}">← 上一岗<kbd class="kbd">[</kbd></button>
      <span class="chart-note">第 ${orderPos + 1} / ${order.length} 个 · 当前筛选</span>
      <button type="button" class="btn btn-ghost btn-sm" data-job-step="${esc(nextId)}"
        ${nextId ? "" : "disabled"} title="${esc(stepTip(nextId, "下一岗"))}"
        aria-label="${esc(stepTip(nextId, "下一岗"))}">下一岗<kbd class="kbd">]</kbd> →</button>
    </div>` : "";

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
        ${neutralFit ? `<span class="mini mini-warn" title="${esc(fit.verdict || "中性占位分")}">中性</span>` : ""}
        ${fit.resume_state === "stale" ? `<span class="mini mini-warn" title="适配度基于较早的简历版本，当前母版已变化">需重新适配</span>` : ""}
      </div>` : ""}
      ${watchButton("job", id, job.title, { large: true, shortcut: "W" })}
      ${watch.jobs.size >= 2 ? `<a class="btn btn-ghost btn-sm" href="#/job-compare" style="align-self:center">${icon("layers")}对比关注 ${watch.jobs.size}</a>` : ""}
      <a class="link" href="${esc(backHash("#/jobs"))}" style="align-self:center">← 列表</a>
    </div>
    ${stepBar}

    <div class="grid grid-21 jd-grid">
      <div class="jd-main">
        <div class="card jd-card-info">
          <div class="card-head">${cardTitle("岗位信息", "briefcase", true)}</div>
          <div class="spec-rows">
            ${specRow("薪资范围", esc(job.salary || "—"))}
            ${specRow("经验要求", esc(job.experience || "—"))}
            ${specRow("学历要求", esc(job.degree || "—"))}
            ${specRow("所属行业", esc(job.industry || "—"))}
            ${specRow("岗位来源", `${icon("external")} ${esc(job.source?.name || "—")}`)}
          </div>
          ${skills.length ? `<div style="margin-top:16px">
            <div class="spec-label skill-head">
              <span>技能要求</span>
              ${coverage ? `<span class="mini ${coverage.missing.length ? "mini-warn" : "mini-ok"}"
                title="按母版 skills[] 本地匹配">简历覆盖 ${coverage.covered.length}/${coverage.list.length}</span>` : ""}
            </div>
            ${skills.map((s) => {
              const hit = coverage ? coverage.covered.includes(s) : false;
              return `<span class="tag-outline skill-tag ${coverage ? (hit ? "hit" : "gap") : ""}"
                title="${coverage ? (hit ? "母版简历已覆盖" : "母版简历未覆盖") : ""}">${coverage ? `<i class="dot ${hit ? "dot-pos" : "dot-gap"}"></i>` : ""}${esc(s)}</span>`;
            }).join("")}
          </div>` : ""}
          ${(job.welfare || []).length ? `<div style="margin-top:16px">
            <div class="spec-label" style="margin-bottom:8px">福利</div>
            ${job.welfare.map((s) => `<span class="tag-outline">${esc(s)}</span>`).join("")}
          </div>` : ""}
        </div>

        <div class="card jd-card-jd">
          <div class="card-head">${cardTitle("职位描述", "file", true)}
            ${job.description ? `<button type="button" class="btn btn-ghost btn-sm" id="btn-copy-jd"
              title="复制岗位标题、来源链接与 JD 原文（C）">${icon("file")}复制 JD</button>` : `<span class="card-sub">未提供</span>`}</div>
          <div class="prose jd-wrap" id="jd-body">${formatJobDescription(job.description)}</div>
        </div>
      </div>

      <div class="jd-side">
        <div class="card jd-card-company">
          <div class="card-head">${cardTitle("招聘公司", "building", true)}</div>
          ${company.name ? `
            <div style="display:flex;align-items:center;gap:12px">
              <div class="detail-logo" style="width:44px;height:44px;border-radius:11px;font-size:19px">${esc(company.name.slice(0, 1))}</div>
              <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:center;gap:8px;min-width:0">
                  ${company.company_key
                    ? `<a class="link" style="font-size:14px;font-weight:600;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" href="#/companies/${encodeURIComponent(company.company_key)}" data-company="${esc(company.company_key)}">${esc(company.name)}</a>`
                    : `<div style="font-size:14px;font-weight:600">${esc(company.name)}</div>`}
                  ${company.company_key ? watchButton("company", company.company_key, company.name) : ""}
                </div>
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

        <div class="card jd-card-track">
          <div class="card-head">${cardTitle("投递跟进", "clock", true)}
            <div class="card-sub" id="track-meta" aria-live="polite">
              <span class="track-due ${!dueReason && snoozed ? "snoozed" : ""}" id="track-due"
                title="${dueReason ? "按最近一次跟进（改阶段或记录跟进）计算；编辑备注不会重置计时" : "延后期间不计入待行动；记录跟进或修改阶段会取消延后"}"
                ${dueReason || snoozed ? "" : "hidden"}>${icon(dueReason ? "alert" : "clock")}${esc(dueReason || snoozed)}</span>
              <span id="track-stamp">${esc(trackStampText(rec))}</span>
            </div></div>
          <div class="stage-picker" role="group" aria-label="投递阶段">
            ${STAGES.map((s, index) => `<button type="button" class="stage-btn ${s.id}${rec && rec.stage === s.id ? " on" : ""}"
              data-set-stage="${s.id}" aria-pressed="${rec && rec.stage === s.id}"
              aria-keyshortcuts="${index + 1}" title="标记为${s.label}（快捷键 ${index + 1}）">${icon(s.icon)}${s.label}</button>`).join("")}
          </div>
          <div class="interview-row" id="interview-row" ${rec && rec.stage === "interview" ? "" : "hidden"}>
            <label class="interview-field" for="interview-at">
              <span>${icon("clock")}面试时间</span>
              <input type="datetime-local" id="interview-at" step="60" value="${esc(interviewInputValue(rec))}"
                aria-label="面试时间" title="记录面试日期与时间；列表、看板和总览会显示倒计时">
            </label>
            <label class="interview-field interview-field-round" for="interview-round">
              <span>${icon("layers")}轮次</span>
              <select id="interview-round" aria-label="面试轮次"
                title="标记面试轮次：总览、反馈与导出的日历会带上轮次">
                <option value="" ${interviewRound(rec) ? "" : "selected"}>未标记</option>
                ${INTERVIEW_ROUNDS.map((round) => `<option value="${esc(round)}" ${interviewRound(rec) === round ? "selected" : ""}>${esc(round)}</option>`).join("")}
              </select>
            </label>
            <button type="button" class="btn btn-ghost btn-sm" id="btn-clear-interview" ${interviewTime(rec) ? "" : "hidden"}>清除</button>
          </div>
          <div class="interview-row offer-row" id="offer-row" ${rec && rec.stage === "offer" ? "" : "hidden"}>
            <label class="interview-field" for="offer-until">
              <span>${icon("star")}答复截止</span>
              <input type="datetime-local" id="offer-until" step="60" value="${esc(offerInputValue(rec))}"
                aria-label="Offer 答复截止时间" title="设置 Offer 答复截止时间；行动队列会按截止时间排序，并在截止前提醒">
            </label>
            <button type="button" class="chip offer-preset" data-offer-days="3" title="设为 3 天后 18:00">3 天</button>
            <button type="button" class="chip offer-preset" data-offer-days="7" title="设为 7 天后 18:00">1 周</button>
            <button type="button" class="btn btn-ghost btn-sm" id="btn-clear-offer" ${offerDeadline(rec) ? "" : "hidden"}>清除</button>
          </div>
          <div class="prep-block" id="interview-prep" ${rec && rec.stage === "interview" ? "" : "hidden"}>
            <div class="prep-head">
              <span class="prep-title">${icon("check")}面试准备</span>
              <span class="prep-progress" id="prep-progress" aria-live="polite">0/${PREP_TOTAL}</span>
            </div>
            <div class="prep-meter" id="prep-meter" role="progressbar" aria-label="面试准备进度"
              aria-valuemin="0" aria-valuemax="${PREP_TOTAL}" aria-valuenow="0"><i id="prep-meter-fill"></i></div>
            <div class="prep-list">
              ${PREP_ITEMS.map((label, index) => `<label class="prep-item" for="prep-${index}">
                <input type="checkbox" id="prep-${index}" data-prep-index="${index}">
                <span>${esc(label)}</span>
              </label>`).join("")}
            </div>
          </div>
          <div id="track-timeline">${trackTimelineHTML(rec)}</div>
          <textarea class="track-note" id="track-note" rows="3" maxlength="500"
            placeholder="备注：联系人、面试时间、薪资沟通…">${esc((rec && rec.note) || "")}</textarea>
          <div class="track-actions">
            <span class="chart-note" id="track-tip">${rec ? "修改后自动保存到本机" : "选择阶段后自动保存，不会上传"}</span>
            <div class="track-btns">
              <button type="button" class="btn btn-ghost btn-sm" id="btn-track-message"
                ${rec && isTerminalStage(rec.stage) ? "hidden" : ""}
                title="${esc(followupLabel(rec))}（M）">${icon("copy")}${esc(followupLabel(rec))}</button>
              <button type="button" class="btn btn-ghost btn-sm" id="btn-track-touch"
                ${rec && !isTerminalStage(rec.stage) ? "" : "hidden"}
                title="记录今天已跟进，重置提醒计时，不改阶段（T）">${icon("check")}记录跟进</button>
              <button type="button" class="btn btn-ghost btn-sm" id="btn-track-snooze"
                ${rec && !isTerminalStage(rec.stage) ? "" : "hidden"}
                title="${snoozed ? "取消延后，立即重新计入待行动（S）" : "延后 3 天提醒，期间不计入待行动（S）"}">${icon(snoozed ? "refresh" : "clock")}${snoozed ? "取消延后" : "延后 3 天"}</button>
              <button type="button" class="btn btn-ghost btn-sm snooze-caret" id="btn-track-snooze-menu"
                aria-haspopup="menu" aria-expanded="false"
                ${rec && !isTerminalStage(rec.stage) && !snoozed ? "" : "hidden"}
                title="选择延后时长：1 天 / 3 天 / 1 周 / 2 周"
                aria-label="选择延后时长">${icon("chevron")}</button>
              <button type="button" class="btn btn-ghost btn-sm" id="btn-clear-track" ${rec ? "" : "hidden"}>清除跟进</button>
            </div>
          </div>
        </div>

        <div class="card jd-card-brief">
          <div class="card-head">${cardTitle("面试简报", "file", true)}
            <div class="card-sub" id="brief-state">岗位 + 背调 + 跟进</div></div>
          <div class="brief-tools">
            <button type="button" class="btn btn-sm" id="btn-brief" title="生成面试简报（B）">${icon("file")}生成简报</button>
            <span class="chart-note">本地生成，可直接粘贴到笔记</span>
          </div>
          <div id="brief-box" hidden>
            <pre class="brief-preview" id="brief-preview"></pre>
            <div class="brief-tools">
              <button type="button" class="btn btn-ghost btn-sm" id="btn-copy-brief">${icon("file")}复制 Markdown</button>
              <span class="chart-note" id="brief-tip"></span>
            </div>
          </div>
        </div>

        <div class="card jd-card-source">
          <div class="card-head">${cardTitle("信息来源", "external", true)}</div>
          <div class="spec-rows">
            ${specRow("来源", esc(job.source?.name || "—"))}
            ${specRow("链接", job.source?.url
              ? `<span class="link" data-url="${esc(job.source.url)}">${icon("external")} ${esc(job.source.url.replace(/^https?:\/\//, "").slice(0, 30))}…</span>`
              : "—")}
          </div>
          <div style="display:flex;gap:9px;margin-top:14px;flex-wrap:wrap">
            ${job.source?.url ? `<button class="btn btn-sm" id="btn-open-source">${icon("external")}打开原帖</button>` : ""}
            <button class="btn btn-ghost btn-sm" id="btn-tailor">${icon("file")}按此岗位改简历${coverage && coverage.missing.length ? ` · 缺 ${coverage.missing.length} 项` : ""}</button>
          </div>
        </div>

        ${Object.keys(fitDims).length ? `<div class="card jd-card-fit">
          <div class="card-head">${cardTitle("适配度明细", "layers", true)}
            <div class="card-sub">${fit.grade || ""}${neutralFit ? " · 中性假设" : ""}</div></div>
          ${Object.entries(fitDims).map(([name, value]) => metricRow(name, value)).join("")}
          ${(fit.advice || []).length
            ? `<div style="margin-top:12px">${fit.advice.map((a) => `<span class="tag tag-cyan">${esc(a)}</span>`).join("")}</div>`
            : ""}
          ${fit.verdict ? `<div class="chart-note left" style="margin-top:10px">${esc(fit.verdict)}</div>` : ""}
          ${fitSourceHTML(fit)}
        </div>` : ""}
      </div>
    </div>`;

  bindNav();

  const stepTo = (target) => {
    if (!target) return;
    goJob(target);
    window.scrollTo(0, 0);
  };
  const warmStep = (btn) => {
    if (btn.dataset.jobStep) prefetchDetail("job", { job_id: btn.dataset.jobStep });
  };
  $$("[data-job-step]").forEach((btn) => {
    btn.addEventListener("click", () => stepTo(btn.dataset.jobStep));
    btn.addEventListener("pointerenter", () => warmStep(btn));
    btn.addEventListener("focus", () => warmStep(btn));
  });

  const stageButtons = $$("[data-set-stage]");
  const noteEl = $("#track-note");
  const stampEl = $("#track-stamp");
  const tipEl = $("#track-tip");
  const clearBtn = $("#btn-clear-track");
  const msgBtn = $("#btn-track-message");
  const touchBtn = $("#btn-track-touch");
  const snoozeBtn = $("#btn-track-snooze");
  const snoozeCaret = $("#btn-track-snooze-menu");
  const dueEl = $("#track-due");
  const interviewRow = $("#interview-row");
  const interviewInput = $("#interview-at");
  const interviewRoundEl = $("#interview-round");
  const clearInterviewBtn = $("#btn-clear-interview");
  const offerRow = $("#offer-row");
  const offerInput = $("#offer-until");
  const clearOfferBtn = $("#btn-clear-offer");
  const offerPresetBtns = $$("[data-offer-days]");
  const prepBlock = $("#interview-prep");
  const prepProgress = $("#prep-progress");
  const prepMeter = $("#prep-meter");
  const prepFill = $("#prep-meter-fill");
  const prepInputs = $$("[data-prep-index]");
  const syncPrepUI = (current) => {
    const prep = normalizePrep(current?.prep);
    const done = prep.filter(Boolean).length;
    if (prepBlock) {
      prepBlock.hidden = !current || current.stage !== "interview";
      prepBlock.classList.toggle("complete", done === PREP_TOTAL);
    }
    if (prepProgress) prepProgress.textContent = `${done}/${PREP_TOTAL}`;
    if (prepMeter) prepMeter.setAttribute("aria-valuenow", String(done));
    if (prepFill) prepFill.style.width = `${Math.round((done / PREP_TOTAL) * 100)}%`;
    prepInputs.forEach((input, index) => {
      input.checked = !!prep[index];
      input.closest(".prep-item")?.classList.toggle("done", !!prep[index]);
    });
  };
  const refreshTrackUI = () => {
    const current = trackOf(id);
    stageButtons.forEach((btn) => {
      const on = !!current && current.stage === btn.dataset.setStage;
      btn.classList.toggle("on", on);
      btn.setAttribute("aria-pressed", String(on));
    });
    const timelineEl = $("#track-timeline");
    if (timelineEl) timelineEl.innerHTML = trackTimelineHTML(current);
    stampEl.textContent = trackStampText(current);
    const reason = followupReason(current);
    const snoozed = snoozedLabel(current);
    const dueText = reason || snoozed;
    if (dueEl) {
      dueEl.hidden = !dueText;
      dueEl.classList.toggle("snoozed", !reason && !!snoozed);
      dueEl.innerHTML = dueText ? `${icon(reason ? "alert" : "clock")}${esc(dueText)}` : "";
      dueEl.title = reason
        ? "按最近一次跟进（改阶段或记录跟进）计算；编辑备注不会重置计时"
        : "延后期间不计入待行动；记录跟进或修改阶段会取消延后";
    }
    if (clearBtn) clearBtn.hidden = !current;
    if (touchBtn) {
      const canTouch = !!current && !isTerminalStage(current.stage);
      touchBtn.hidden = !canTouch;
      if (canTouch) {
        const feedbackMode = interviewStarted(current);
        touchBtn.dataset.feedback = feedbackMode ? "1" : "";
        touchBtn.innerHTML = feedbackMode ? `${icon("chat")}记反馈` : `${icon("check")}记录跟进`;
        touchBtn.title = feedbackMode
          ? "记录面试结果与复盘（T）"
          : "记录今天已跟进，重置提醒，不改阶段（T）";
      }
    }
    if (snoozeBtn) {
      const canSnooze = !!current && !isTerminalStage(current.stage);
      snoozeBtn.hidden = !canSnooze;
      if (canSnooze) {
        const until = snoozeDay(current);
        snoozeBtn.innerHTML = `${icon(until ? "refresh" : "clock")}${until ? "取消延后" : "延后 3 天"}`;
        snoozeBtn.title = until
          ? "取消延后，立即重新计入待行动（S）"
          : `延后 ${SNOOZE_DAYS} 天提醒，期间不计入待行动（S）`;
      }
    }
    if (snoozeCaret) {
      snoozeCaret.hidden = !current || isTerminalStage(current.stage) || !!snoozeEnd(current);
    }
    if (interviewRow) interviewRow.hidden = !current || current.stage !== "interview";
    if (interviewInput) interviewInput.value = interviewInputValue(current);
    if (interviewRoundEl) interviewRoundEl.value = interviewRound(current);
    if (clearInterviewBtn) clearInterviewBtn.hidden = !current || !interviewTime(current);
    if (offerRow) offerRow.hidden = !current || current.stage !== "offer";
    if (offerInput) offerInput.value = offerInputValue(current);
    if (clearOfferBtn) clearOfferBtn.hidden = !current || !offerDeadline(current);
    syncPrepUI(current);
    if (msgBtn) {
      const label = followupLabel(current);
      msgBtn.hidden = !label;
      if (label) {
        msgBtn.innerHTML = `${icon("copy")}${esc(label)}`;
        msgBtn.title = `${label}（M）`;
      }
    }
    if (tipEl) tipEl.textContent = storeHealth.failed
      ? "本机存储不可用 · 改动仅在当前窗口"
      : current ? "修改后自动保存到本机" : "选择阶段后自动保存，不会上传";
  };
  refreshTrackUI();
  const markStage = (stage) => {
    const before = snapshotTrack(id);
    setTrackStage(id, stage);
    refreshTrackUI();
    toast(`已标记「${stageMeta(stage).label}」`, "ok", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        refreshTrackUI();
        toast("已撤销阶段修改", "info");
      },
    });
  };
  stageButtons.forEach((btn) => btn.addEventListener("click", () => markStage(btn.dataset.setStage)));
  if (msgBtn) msgBtn.addEventListener("click", async () => {
    const current = trackOf(id);
    const kind = followupKind(current);
    if (!kind) return;
    try {
      await copyText(followupMessage(job, current));
      toast(`已复制${kind}`);
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });
  if (touchBtn) touchBtn.addEventListener("click", () => {
    const current = trackOf(id);
    if (!current || isTerminalStage(current.stage)) return;
    if (touchBtn.dataset.feedback === "1") {
      openInterviewFeedback(id, {
        anchor: touchBtn,
        focusAfterSave: () => {
          const stage = trackOf(id)?.stage || "interview";
          const target = document.querySelector(`[data-set-stage="${CSS.escape(stage)}"]`)
            || $("#btn-track-touch") || $("#interview-at");
          target?.focus({ preventScroll: true });
        },
      });
      return;
    }
    const before = snapshotTrack(id);
    if (!touchTrack(id)) return;
    refreshTrackUI();
    toast("已记录本次跟进", "ok", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        refreshTrackUI();
        toast("已撤销本次跟进", "info");
      },
    });
  });
  if (snoozeBtn) snoozeBtn.addEventListener("click", () => {
    const current = trackOf(id);
    if (!current || isTerminalStage(current.stage)) return;
    const before = snapshotTrack(id);
    if (snoozeEnd(current)) {
      if (!unsnoozeTrack(id)) return;
      refreshTrackUI();
      toast("已取消延后，重新计入待行动", "info", {
        label: "撤销",
        onClick: () => {
          restoreTrack(id, before);
          refreshTrackUI();
          toast("已恢复延后", "info");
        },
      });
      return;
    }
    if (!snoozeTrack(id)) return;
    refreshTrackUI();
    toast(`已延后 ${SNOOZE_DAYS} 天 · ${snoozeDay(trackOf(id))} 重新提醒`, "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        refreshTrackUI();
        toast("已撤销延后", "info");
      },
    });
  });
  if (snoozeCaret) snoozeCaret.addEventListener("click", () => {
    const current = trackOf(id);
    if (!current || isTerminalStage(current.stage) || snoozeEnd(current)) return;
    openSnoozeMenu(snoozeCaret, {
      jobId: id,
      title: job.title,
      onPick: (days) => {
        const latest = trackOf(id);
        if (!latest || isTerminalStage(latest.stage)) return;
        const before = snapshotTrack(id);
        if (!snoozeTrack(id, days)) return;
        refreshTrackUI();
        toast(`已延后 ${days} 天 · ${snoozeDay(trackOf(id))} 重新提醒`, "info", {
          label: "撤销",
          onClick: () => {
            restoreTrack(id, before);
            refreshTrackUI();
            $("#btn-track-snooze")?.focus({ preventScroll: true });
            toast("已撤销延后", "info");
          },
        });
        $("#btn-track-snooze")?.focus({ preventScroll: true });
      },
    });
  });
  document.addEventListener("snoozeexpired", (event) => {
    if (!event.detail?.ids?.includes(id)) return;
    refreshTrackUI();
  }, { signal: pageAbort.signal });
  document.addEventListener("interviewchange", () => refreshTrackUI(), { signal: pageAbort.signal });
  document.addEventListener("offerchange", () => refreshTrackUI(), { signal: pageAbort.signal });

  const saveInterview = (value) => {
    const current = trackOf(id);
    if (!current || current.stage !== "interview") return;
    const parsed = value ? new Date(value) : null;
    if (value && (!parsed || Number.isNaN(parsed.getTime()))) {
      toast("面试时间无效，请重新选择", "warn");
      if (interviewInput) interviewInput.value = interviewInputValue(current);
      return;
    }
    const next = parsed ? parsed.toISOString() : "";
    if ((current.interviewAt || "") === next) return;
    const before = snapshotTrack(id);
    if (next) current.interviewAt = next; else delete current.interviewAt;
    saveTrack();
    refreshTrackUI();
    if (!next && interviewInput) interviewInput.focus();
    toast(next ? `面试已安排 · ${interviewStamp(trackOf(id))}` : "已清除面试时间", "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        refreshTrackUI();
        toast("已恢复面试时间", "info");
      },
    });
  };
  if (interviewInput) interviewInput.addEventListener("change", () => saveInterview(interviewInput.value));
  if (clearInterviewBtn) clearInterviewBtn.addEventListener("click", () => saveInterview(""));

  const saveOffer = (value) => {
    const current = trackOf(id);
    if (!current || current.stage !== "offer") return;
    const parsed = value ? new Date(value) : null;
    if (value && (!parsed || Number.isNaN(parsed.getTime()))) {
      toast("Offer 截止时间无效，请重新选择", "warn");
      if (offerInput) offerInput.value = offerInputValue(current);
      return;
    }
    const next = parsed ? parsed.toISOString() : "";
    if ((current.offerUntil || "") === next) return;
    const before = snapshotTrack(id);
    if (next) current.offerUntil = next; else delete current.offerUntil;
    saveTrack();
    refreshTrackUI();
    document.dispatchEvent(new CustomEvent("offerchange"));
    if (!next && offerInput) offerInput.focus();
    toast(next ? `Offer 答复截止 · ${offerDeadlineLabel(trackOf(id))}` : "已清除 Offer 答复截止", "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        refreshTrackUI();
        document.dispatchEvent(new CustomEvent("offerchange"));
        toast("已恢复 Offer 答复截止", "info");
      },
    });
  };
  if (offerInput) offerInput.addEventListener("change", () => saveOffer(offerInput.value));
  if (clearOfferBtn) clearOfferBtn.addEventListener("click", () => saveOffer(""));
  offerPresetBtns.forEach((btn) => btn.addEventListener("click", () => {
    const current = trackOf(id);
    if (!current || current.stage !== "offer") return;
    if (offerInput) offerInput.value = localInputValue(offerPresetAt(Number(btn.dataset.offerDays)));
    saveOffer(offerInput ? offerInput.value : "");
  }));

  if (interviewRoundEl) interviewRoundEl.addEventListener("change", () => {
    const current = trackOf(id);
    if (!current || current.stage !== "interview") return;
    const value = interviewRoundEl.value;
    if (interviewRound(current) === value) return;
    const before = snapshotTrack(id);
    if (isInterviewRound(value)) current.round = value; else delete current.round;
    saveTrack();
    refreshTrackUI();
    document.dispatchEvent(new CustomEvent("interviewchange"));
    toast(value ? `面试轮次 · ${value}` : "已清除面试轮次", "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        refreshTrackUI();
        document.dispatchEvent(new CustomEvent("interviewchange"));
        interviewRoundEl.focus({ preventScroll: true });
        toast("已恢复面试轮次", "info");
      },
    });
  });

  prepInputs.forEach((input) => input.addEventListener("change", () => {
    const current = trackOf(id);
    if (!current || current.stage !== "interview") return;
    const index = Number(input.dataset.prepIndex);
    if (!Number.isInteger(index) || index < 0 || index >= PREP_TOTAL) return;
    const prep = normalizePrep(current.prep);
    prep[index] = input.checked;
    if (prep.some(Boolean)) current.prep = prep; else delete current.prep;
    saveTrack();
    syncPrepUI(current);
    const done = prep.filter(Boolean).length;
    toast(done === PREP_TOTAL ? "面试准备已全部完成" : `面试准备 · ${done}/${PREP_TOTAL}`, done === PREP_TOTAL ? "ok" : "info");
  }));

  let noteTimer = 0;
  const persistNote = () => {
    clearTimeout(noteTimer);
    const note = noteEl.value.trim();
    if (!note && !trackOf(id)) return;
    const saved = setTrackNote(id, note);
    refreshTrackUI();
    if (tipEl) tipEl.textContent = saved ? "已保存 · 仅存本机" : "保存失败 · 改动仅在当前窗口";
  };
  noteEl.addEventListener("input", () => {
    clearTimeout(noteTimer);
    noteTimer = setTimeout(persistNote, 450);
  });
  noteEl.addEventListener("blur", persistNote);

  let clearArmed = 0;
  const disarmClear = () => {
    clearTimeout(clearArmed);
    clearArmed = 0;
    clearBtn.textContent = "清除跟进";
    clearBtn.classList.remove("btn-danger");
  };
  if (clearBtn) clearBtn.addEventListener("click", () => {
    if (!clearArmed) {
      clearArmed = setTimeout(disarmClear, 3200);
      clearBtn.textContent = "再次点击确认";
      clearBtn.classList.add("btn-danger");
      return;
    }
    disarmClear();
    clearTimeout(noteTimer);
    const before = snapshotTrack(id);
    clearTrack(id);
    noteEl.value = "";
    refreshTrackUI();
    toast("已清除跟进记录", "info", {
      label: "撤销",
      onClick: () => {
        restoreTrack(id, before);
        noteEl.value = (before && before.note) || "";
        refreshTrackUI();
        toast("已恢复跟进记录", "ok");
      },
    });
  });

  const briefBtn = $("#btn-brief");
  const briefBox = $("#brief-box");
  const briefPreview = $("#brief-preview");
  const briefState = $("#brief-state");
  const briefTip = $("#brief-tip");
  let briefText = "";
  if (briefBtn) briefBtn.addEventListener("click", async () => {
    if (briefBtn.disabled) return;
    briefBtn.disabled = true;
    briefBtn.textContent = "生成中…";
    let detail = null;
    if (company.company_key) detail = await cachedDetail("company", { company_key: company.company_key });
    if (!document.body.contains(briefBox)) return;
    briefText = buildInterviewBrief(job, detail, trackOf(id));
    briefPreview.textContent = briefText;
    briefBox.hidden = false;
    briefState.textContent = `${briefText.length} 字 · 本地生成`;
    briefTip.textContent = detail ? "仅含已采集证据" : "未取到公司背调";
    briefBtn.innerHTML = `${icon("file")}重新生成`;
    briefBtn.disabled = false;
    if (company.company_key && !detail) toast("公司背调取数失败，已生成岗位与跟进部分", "warn");
  });
  const copyBrief = $("#btn-copy-brief");
  if (copyBrief) copyBrief.addEventListener("click", async () => {
    try {
      await copyText(briefText);
      toast("面试简报已复制为 Markdown");
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });

  const copyJd = $("#btn-copy-jd");
  if (copyJd) copyJd.addEventListener("click", async () => {
    const raw = String(job.description || "").trim();
    if (!raw) return;
    const head = [
      job.title,
      company.name,
      [job.salary, job.city].filter(Boolean).join(" · "),
      job.source?.url,
    ].filter(Boolean).join("\n");
    try {
      await copyText(`${head}\n\n${raw}`);
      toast("岗位与 JD 已复制");
    } catch {
      toast("复制失败，请检查剪贴板权限", "warn");
    }
  });

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

const SKILL_ALIASES = [
  [/\bnode\.?js\b/g, "nodejs"], [/\bnode\b/g, "nodejs"],
  [/\bnext\.?js\b/g, "nextjs"], [/\bnext\b/g, "nextjs"],
  [/\bvue\.?js\b/g, "vuejs"], [/\bvue\b/g, "vuejs"],
  [/\bnuxt\.?js\b/g, "nuxtjs"],
  [/\breact\.?js\b/g, "reactjs"], [/\breact\b/g, "reactjs"],
  [/c\+\+/g, "cpp"], [/\bc#/g, "csharp"], [/\.net\b/g, "dotnet"],
  [/\bpostgres(?:ql)?\b/g, "postgresql"],
  [/\bgolang\b/g, "go"], [/\bk8s\b/g, "kubernetes"],
  [/\bpy\b/g, "python"], [/\bts\b/g, "typescript"], [/\bjs\b/g, "javascript"],
  [/\bllm\b/g, "大语言模型"], [/\bml\b/g, "机器学习"],
];

// 把技能词压成可比较的 key：忽略大小写、分隔符、版本号与常见别名
function skillKey(raw) {
  let s = String(raw || "").toLowerCase();
  for (const [re, to] of SKILL_ALIASES) s = s.replace(re, to);
  s = s.replace(/[（(][^）)]*[）)]/g, " ");
  s = s.replace(/[^a-z0-9\u4e00-\u9fff]+/g, " ");
  s = s.replace(/\b(?:v|ver|version)\s*\d+(?:\.\d+)*\b/g, " ");
  s = s.replace(/\b\d+(?:\.\d+)*\b/g, " ");
  return s.trim().replace(/\s+/g, " ");
}

function skillHit(name, key) {
  const tokens = skillKey(name).split(" ").filter(Boolean);
  const want = key.split(" ").filter(Boolean);
  if (!tokens.length || !want.length) return false;
  if (tokens.join("") === want.join("")) return true;
  const [small, big] = want.length <= tokens.length ? [want, tokens] : [tokens, want];
  // 允许 "Docker Compose" 命中 "Docker"，也允许 "Linux" 命中 "Linux开发/部署经验"
  return small.every((t) => big.includes(t) || big.some((b) =>
    t.length > 1 && b.startsWith(t) && /[\u4e00-\u9fff]/.test(b.slice(t.length, t.length + 1))));
}

function resumeSkillNames(content) {
  const skills = content && Array.isArray(content.skills) ? content.skills : [];
  return skills
    .map((s) => (typeof s === "string" ? s.trim() : s && typeof s.name === "string" ? s.name.trim() : ""))
    .filter(Boolean);
}

function resumeKeysFromContent(content) {
  return resumeSkillNames(content).map(skillKey).filter(Boolean);
}

function resumeSkillKeys(payload) {
  if (!payload || !payload.ok || !payload.resume || !payload.resume.content) return [];
  return resumeKeysFromContent(payload.resume.content);
}

function skillCoverage(skills, keys = resumeSkillKeys(state.resume)) {
  const list = Array.isArray(skills)
    ? skills.filter((s) => typeof s === "string" && s.trim()) : [];
  if (!Array.isArray(keys) || !keys.length || !list.length) return null;
  const covered = list.filter((s) => keys.some((key) => skillHit(s, key)));
  return { list, covered, missing: list.filter((s) => !covered.includes(s)) };
}

// 市场技能云 vs 简历 skills[]：给总览和简历页一个共同的覆盖读数
function marketCoverage(keys = resumeSkillKeys(state.resume)) {
  const cloud = state.cloud;
  const words = cloud && Array.isArray(cloud.skills)
    ? cloud.skills.filter((s) => s && typeof s.name === "string" && s.name.trim()) : [];
  if (!keys.length || !words.length) return null;
  const covered = words.filter((w) => keys.some((key) => skillHit(w.name, key)));
  const missing = words.filter((w) => !covered.includes(w));
  missing.sort((a, b) => (b.count || 0) - (a.count || 0));
  return {
    total: words.length,
    covered: covered.length,
    missing,
    pct: Math.round((covered.length / words.length) * 100),
  };
}

// 定向版本 vs 生成前内容：只做本地比对，给审阅一个抓手
function skillDelta(before, after) {
  const beforeNames = resumeSkillNames(before);
  const afterNames = resumeSkillNames(after);
  const beforeKeys = new Set(beforeNames.map(skillKey).filter(Boolean));
  const afterKeys = new Set(afterNames.map(skillKey).filter(Boolean));
  return {
    added: afterNames.filter((s) => !beforeKeys.has(skillKey(s))),
    removed: beforeNames.filter((s) => !afterKeys.has(skillKey(s))),
    summaryChanged: String((before && before.summary) || "") !== String((after && after.summary) || ""),
  };
}

function tailorResultHTML(fresh, job, before) {
  if (!fresh || !fresh.ok || !fresh.resume) return "";
  const content = fresh.resume.content || {};
  const jobSkills = job && Array.isArray(job.skills)
    ? job.skills.filter((s) => typeof s === "string" && s.trim()) : [];
  const coverage = jobSkills.length ? skillCoverage(jobSkills, resumeKeysFromContent(content)) : null;
  const delta = skillDelta(before, content);
  const meta = job
    ? [job.company, job.salary, job.city].filter((s) => typeof s === "string" && s).join(" · ")
    : "";
  const changed = delta.added.length || delta.removed.length;
  return `<div class="card tailor-card" data-resume-id="${fresh.resume.id}">
    <div class="card-head">${cardTitle("版本 #" + fresh.resume.id, "file")}
      <div class="chips">
        <span class="pill ${fresh.resume.confirmed ? "pill-ok" : "pill-warn"}" data-tailor-pill>${fresh.resume.confirmed ? "已确认" : "草稿"}</span>
        ${fresh.resume.confirmed ? "" : `<button type="button" class="chip chip-ok" data-confirm-tailor title="确认后适配度与后续定向默认使用此版本">${icon("check")}确认生效</button>`}
        <button type="button" class="chip" data-copy-tailor title="复制定向版本的 JSON">${icon("file")}复制 JSON</button>
      </div></div>
    ${fresh.resume.confirmed ? "" : `<div class="tailor-draft-note chart-note" data-draft-note>${icon("info")} 草稿不会用于适配度或下一次定向，确认后才会生效。</div>`}
    ${job ? `<div class="tailor-target">
      <span>${icon("briefcase")}${esc(job.title)}</span>
      <span class="chart-note">${esc(meta || "—")}</span>
      ${coverage ? `<span class="mini ${coverage.missing.length ? "mini-warn" : "mini-ok"}">技能命中 ${coverage.covered.length}/${coverage.list.length}</span>` : ""}
    </div>` : ""}
    <div class="tailor-diff">
      <div class="skill-head">
        <span class="spec-label">技能变化 · 相对生成前</span>
        <span class="chart-note">${changed ? `新增 ${delta.added.length} · 移除 ${delta.removed.length}` : "无增删"}</span>
      </div>
      ${changed
        ? `<div class="tailor-tags">${delta.added.map((s) => `<span class="tag-outline skill-tag hit" title="新增技能">+ ${esc(s)}</span>`).join("")}${delta.removed.map((s) => `<span class="tag-outline skill-tag gap" title="移除技能">− ${esc(s)}</span>`).join("")}</div>`
        : `<span class="chart-note">技能列表没有变化${delta.summaryChanged ? "，但 summary 已改写" : ""}</span>`}
      ${changed && delta.summaryChanged ? `<div class="chart-note" style="margin-top:6px">summary 也已改写</div>` : ""}
    </div>
    ${coverage && coverage.missing.length ? `<div class="tailor-gap chart-note">
      ${icon("info")} 岗位技能缺口：${coverage.missing.slice(0, 6).map(esc).join("、")}${coverage.missing.length > 6 ? " 等" : ""}</div>` : ""}
    <details class="tailor-json">
      <summary>查看完整 JSON</summary>
      <pre>${esc(JSON.stringify(content, null, 2))}</pre>
    </details>
  </div>`;
}

async function pageSkills(params) {
  const cached = state.cloud;
  if (!cached) {
    pageEl().innerHTML = loadingPage("技能", "正在从已入库岗位 JD 中统计技能词…", `
      <div class="grid grid-rail">
        <div class="card"><div class="skel" style="width:150px;height:12px"></div><div class="skel-chart" style="height:470px"></div></div>
        <div class="card"><div class="skel" style="width:90px;height:12px"></div>${skelLines(10, 11)}</div>
      </div>`);
  }
  let cloud = cached;
  if (!cloud) {
    await loadBootstrap();
    cloud = state.cloud;
  }
  if (!cloud) cloud = await call("cloud");
  if (!cloud) {
    pageEl().innerHTML = loadingPage("技能", "技能词统计失败", `<div class="empty">取数失败</div>`);
    return;
  }
  state.cloud = cloud;

  const all = cloud.skills || [];
  const kind = params.kind || state.cloudKind || "all";
  state.cloudKind = kind;
  const filtered = kind === "all" ? all : all.filter((s) => (s.kind || "tech") === kind);
  const resumeKeys = resumeSkillKeys(state.resume);
  const compare = params.gap === "1" && resumeKeys.length > 0;
  const decorated = filtered.map((s) => ({
    ...s, hit: resumeKeys.length > 0 && resumeKeys.some((key) => skillHit(s.name, key)),
  }));
  // 只取前 56 个：词太多会挤成一堵字墙，失去"云"的呼吸感
  const items = decorated.slice(0, 56);
  const covered = decorated.filter((s) => s.hit).length;
  const missing = decorated.filter((s) => !s.hit);
  const coverage = decorated.length ? Math.round((covered / decorated.length) * 100) : 0;
  const max = Math.max(...items.map((s) => s.count), 1);
  const min = Math.min(...items.map((s) => s.count), 1);
  const total = filtered.reduce((n, s) => n + s.count, 0);
  const mentions = all.reduce((n, s) => n + s.count, 0);
  const grand = mentions || 1;
  const kindLabel = kind === "all" ? "全部技能与岗位标签" : kind === "tech" ? "技术栈" : "其他标签";

  // 先算好每个词的视觉参数，实际排布要等容器有了宽度再做（见 paintCloud）
  const prepared = items.map((item) => {
    const norm = max === min ? 1 : (item.count - min) / (max - min);
    const ratio = item.count / max;
    return {
      name: item.name,
      count: item.count,
      hit: item.hit,
      size: 11 + Math.pow(norm, 1.5) * 46,
      far: ratio < 0.16,
      opacity: ratio < 0.16 ? 0.45 : Math.min(1, 0.86 + ratio * 0.14),
    };
  });

  const railSource = compare ? missing : items;
  const rail = railSource.slice(0, 10).map((item) =>
    rankRow(item.name, compare ? `${item.count} 岗` : Math.round((item.count / grand) * 100) + "%",
            item.count / max, { labelWidth: 108 })).join("")
    || `<div class="empty">${compare ? "当前筛选已全部覆盖" : "暂无"}</div>`;

  pageEl().innerHTML = `
    <div class="page-head">
      <div>
        <div class="page-title">技能</div>
        <div class="page-sub">${all.length} 个技能词 · 共 ${mentions} 次提及 · 从已入库岗位 JD 中提取</div>
      </div>
      <div class="page-actions">
        <button class="chip ${compare ? "active" : ""}" id="btn-gap" aria-pressed="${compare}"
          title="${resumeKeys.length ? `用母版简历 skills[] 对照 ${filtered.length} 个词` : "母版简历暂无 skills[]，先在简历页补齐"}"
          ${resumeKeys.length ? "" : "disabled"}>${icon("check")}简历对照</button>
        <span class="pill pill-cyan">${icon("cloud")}${filtered.length} WORDS</span>
      </div>
    </div>

    ${compare ? `
    <div class="gap-strip ${coverage < 35 ? "is-low" : ""}">
      <div class="gap-score">
        <span class="gap-pct">${coverage}<small>%</small></span>
        <span class="gap-label">简历覆盖</span>
      </div>
      <div class="gap-body">
        <div class="gap-title"><b>${covered}</b> / ${filtered.length} 个技能已写进母版简历</div>
        <div class="gap-meter" role="progressbar" aria-valuemin="0" aria-valuemax="100"
             aria-valuenow="${coverage}" aria-label="简历技能覆盖率"><i style="--gap-w:${coverage}%"></i></div>
        <div class="gap-note">${missing.length} 个待补齐 · 口径：${esc(kindLabel)} · 匹配已忽略大小写、版本号与常见别名</div>
      </div>
      <div class="gap-actions">
        <span class="gap-legend"><span class="dot dot-pos"></span>已覆盖<span class="dot dot-gap"></span>待补齐</span>
        <button class="btn btn-ghost btn-sm" id="btn-copy-gap" ${missing.length ? "" : "disabled"}>${icon("copy")}复制缺口</button>
      </div>
    </div>` : ""}

    <div class="grid grid-rail">
      <div class="card">
        <div class="card-head">${cardTitle("技能词云", "cloud", true)}
          <div class="chips">
            <button class="chip" style="cursor:default">${icon("grid")}按频次</button>
            <button class="chip" id="btn-refresh-cloud" title="重新统计技能词">${icon("refresh")}刷新</button>
          </div></div>
        <div class="cloud" id="cloud-box"></div>
        <div style="display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--line);padding-top:14px;gap:12px;flex-wrap:wrap">
          <div class="chips">
            <button class="chip ${kind === "all" ? "active" : ""}" data-kind="all">${icon("layers")}全部 ${all.length}</button>
            <button class="chip ${kind === "tech" ? "active" : ""}" data-kind="tech">${icon("grid")}技术栈</button>
            <button class="chip ${kind === "tag" ? "active" : ""}" data-kind="tag">${icon("star")}其他标签</button>
          </div>
          <span class="card-sub">共 ${total} 次提及</span>
        </div>
      </div>

      <div class="card">
        <div class="card-head">${cardTitle(compare ? "待补齐 TOP 10" : "TOP 10", compare ? "alert" : "layers", true)}
          <div class="card-sub">${compare ? `${missing.length} 个缺口` : `${items.length} 个词`}</div></div>
        ${rail}
        <div style="border-top:1px solid var(--line);padding-top:12px;margin-top:6px">
          <span class="card-sub">${icon("info")}${compare ? "琥珀色词 = 简历未覆盖；优先补高频缺口" : "百分比 = 该词岗位数 / 全部提及"}</span>
        </div>
      </div>
    </div>`;

  $$("[data-kind]").forEach((chip) => chip.addEventListener("click", () => {
    go("#/skills?kind=" + chip.dataset.kind + (compare ? "&gap=1" : ""));
  }));
  const gapBtn = $("#btn-gap");
  if (gapBtn) gapBtn.addEventListener("click", () => {
    go("#/skills?kind=" + kind + (compare ? "" : "&gap=1"));
  });
  const copyGap = $("#btn-copy-gap");
  if (copyGap) copyGap.addEventListener("click", async () => {
    if (!missing.length) return;
    await copyText(missing.map((s) => s.name).join("、"));
    toast(`已复制 ${missing.length} 个缺口技能，可粘进母版 skills[]`);
  });
  const refreshCloud = $("#btn-refresh-cloud");
  if (refreshCloud) refreshCloud.addEventListener("click", () => {
    state.cloud = null;
    void router();
  });

  // 容器有了真实尺寸之后才排布，否则按错宽度算出来的位置会互相重叠
  const box = $("#cloud-box");
  const paint = () => {
    const W = box.clientWidth || 900;
    const H = box.clientHeight || 470;
    const laid = layoutCloud(prepared.map((p) => ({ ...p })), W, H);
    box.innerHTML = laid.map((item) => {
      const stateClass = compare ? (item.hit ? "hit" : "gap") : "";
      const tail = compare ? (item.hit ? " · 简历已覆盖" : " · 待补齐") : "";
      return `<span class="${item.far ? "far" : ""} ${stateClass}"
        style="left:${item.x.toFixed(2)}%;top:${item.y.toFixed(2)}%;font-size:${item.size.toFixed(0)}px;opacity:${item.opacity.toFixed(2)}"
        title="${esc(item.name)} · 出现在 ${item.count} 个岗位${tail}">${esc(item.name)}</span>`;
    }).join("") || `<div class="empty">没有符合条件的词</div>`;
  };
  paint();
  let resizeFrame = 0;
  const relayout = () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      if (document.body.contains(box)) paint();
    });
  };
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(relayout) : null;
  if (observer) observer.observe(box);
  else window.addEventListener("resize", relayout);
  pageAbort.signal.addEventListener("abort", () => {
    observer?.disconnect();
    cancelAnimationFrame(resizeFrame);
    window.removeEventListener("resize", relayout);
  }, { once: true });
}

// ---------------------------------------------------------------- 简历
async function pageResume(params) {
  const targetJob = params.job || "";
  const cached = state.resume;
  if (!cached) {
    pageEl().innerHTML = loadingPage("简历", "母版 → 按岗位定向；定向版本未经确认不会生效", `
      <div class="grid grid-2">
        <div class="card"><div class="skel" style="width:140px;height:12px"></div><div class="skel-chart" style="height:330px"></div></div>
        <div class="card"><div class="skel" style="width:110px;height:12px"></div>${skelLines(5)}<div class="skel" style="width:120px;height:30px;margin-top:16px"></div></div>
      </div>`);
  }
  let payload = cached;
  if (!payload) {
    await loadBootstrap();
    payload = state.resume;
  }
  if (!payload) payload = await call("resume");
  if (payload) state.resume = payload;
  const resume = payload && payload.ok ? payload.resume : null;
  const questions = (payload && payload.questions) || [];
  const versions = Array.isArray(payload?.versions) ? payload.versions : [];
  let hasHistory = Array.isArray(payload?.versions);
  const historyRows = versions.slice(0, 12);
  let activeVersion = versions.find((row) => row && row.confirmed) || null;
  let editorVersionId = resume && resume.id;
  let savedSignature = resume ? JSON.stringify(resume.content) : null;

  const sample = `{
  "name": "张三",
  "summary": "3 年后端开发，熟悉高并发订单系统",
  "skills": ["Python", "MySQL", "Redis"],
  "experience": [
    {"title": "后端工程师", "org": "某公司",
     "highlights": ["日订单百万级", "接口 P99 80ms"]}
  ]
}`;

  const jobPool = (state.data?.jobs || []).filter((job) => job && job.id);
  const jobById = new Map(jobPool.map((job) => [job.id, job]));
  const watchJobs = [...watch.jobs].map((jobId) => jobById.get(jobId)).filter(Boolean);
  const watchedIds = new Set(watchJobs.map((job) => job.id));
  const recentJobs = recentItems().filter((entry) => entry.kind === "job" && !watchedIds.has(entry.id))
    .map((entry) => jobById.get(entry.id)).filter(Boolean);
  const grouped = new Set([...watchJobs, ...recentJobs].map((job) => job.id));
  const restJobs = jobPool.filter((job) => !grouped.has(job.id))
    .sort((a, b) => ((b.fit?.total ?? -1) - (a.fit?.total ?? -1))
      || String(a.title || "").localeCompare(String(b.title || ""), "zh-CN"));
  const jobOption = (job) => `<option value="${esc(job.id)}"${job.id === targetJob ? " selected" : ""}>${esc(job.title)} · ${esc(job.company || "—")}</option>`;
  const jobGroups = [
    watchJobs.length ? `<optgroup label="关注岗位">${watchJobs.map(jobOption).join("")}</optgroup>` : "",
    recentJobs.length ? `<optgroup label="最近查看">${recentJobs.map(jobOption).join("")}</optgroup>` : "",
    restJobs.length ? `<optgroup label="全部岗位">${restJobs.map(jobOption).join("")}</optgroup>` : "",
  ].join("");
  const targetMeta = jobById.get(targetJob);
  const targetHint = targetMeta
    ? `${targetMeta.title} · ${targetMeta.company || "—"} · ${[targetMeta.salary, targetMeta.city].filter(Boolean).join(" · ")}`
    : "在岗位详情页点「按此岗位改简历」可自动带入";

  function activePillHTML() {
    if (!hasHistory) return "";
    if (activeVersion && editorVersionId === activeVersion.id) return "";
    return activeVersion
      ? `<span class="pill pill-cyan" id="resume-active-pill" title="适配度与后续定向默认使用的已确认版本">生效 #${activeVersion.id}</span>`
      : `<span class="pill pill-warn" id="resume-active-pill" title="还没有已确认版本，适配度会跳过">无生效版本</span>`;
  }

  function historyHTML() {
    if (!historyRows.length) return "";
    return `<div class="card-head">${cardTitle("版本历史", "clock", true)}
        <div class="card-sub">${versions.length > historyRows.length ? `最近 ${historyRows.length} / 共 ${versions.length} 个` : `共 ${versions.length} 个`} · 载入只改编辑器，不写库</div>
      </div>
      <div class="history-list">${historyRows.map((row) => {
        const kind = row.id === activeVersion?.id
          ? `<span class="pill pill-ok">生效中</span>`
          : row.confirmed
            ? `<span class="pill pill-cyan">已确认</span>`
            : `<span class="pill pill-warn">草稿</span>`;
        const targetJob = row.job_id ? jobById.get(row.job_id) : null;
        const target = targetJob ? targetJob.title
          : row.job_id ? `岗位 ${String(row.job_id).slice(0, 8)}…`
            : (row.target || "通用");
        const at = String(row.created_at || "").replace("T", " ").slice(5, 16);
        const answerText = row.question_count
          ? `${row.answer_count || 0}/${row.question_count} 答` : "未提问";
        return `<div class="history-row" data-version-id="${row.id}">
          <div class="history-main">
            <div class="history-title">#${row.id}
              <span class="history-name">${esc(row.name || "简历")}</span>
              ${row.id === editorVersionId ? `<span class="mini">编辑中</span>` : ""}
            </div>
            <div class="history-meta">${kind}<span>${esc(target)}</span>
              <span>${Number(row.skill_count || 0)} 技能</span>
              <span>${esc(answerText)}</span>
              <span>${esc(at)}</span>
            </div>
          </div>
          <div class="history-actions">
            <button type="button" class="chip" data-load-version="${row.id}" title="把此版本内容载入上方编辑器，岗位目标不变">载入</button>
            ${row.confirmed ? "" : `<button type="button" class="chip chip-ok" data-confirm-version="${row.id}" title="确认后适配度与后续定向默认使用此版本">确认</button>`}
          </div>
        </div>`;
      }).join("")}</div>`;
  }

  pageEl().innerHTML = `
    <div class="page-head">
      <div>
        <div class="page-title">简历</div>
        <div class="page-sub">母版 → 按岗位定向；定向版本未经确认不会生效</div>
      </div>
      <div class="page-actions">
        <a class="btn btn-ghost btn-sm" href="#/skills?gap=1" title="用母版 skills[] 对照市场技能词">${icon("check")}技能对照</a>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head">${cardTitle("母版简历", "file", true)}
          <div class="chips">
            ${resume ? `<span class="pill ${resume.confirmed ? "pill-ok" : "pill-warn"}" id="resume-master-pill" data-resume-id="${resume.id}">#${resume.id} ${resume.confirmed ? "已确认" : "草稿"}</span>` : ""}
            ${resume && hasHistory ? activePillHTML() : ""}
            ${resume && !resume.confirmed ? `<button class="chip chip-ok" id="btn-confirm-master" title="确认库内版本 #${resume.id}；确认后适配度与后续定向默认使用它">${icon("check")}确认生效</button>` : ""}
            <button class="chip" id="btn-refresh-resume" title="重新读取简历与待答问题">${icon("refresh")}刷新</button>
          </div></div>
        <div class="field">
          <label>JSON：name / summary / skills[] / experience[] / projects[]</label>
          <textarea id="resume-content" style="min-height:320px;font-family:Consolas,monospace;font-size:12px">${esc(resume ? JSON.stringify(resume.content, null, 2) : sample)}</textarea>
        </div>
        <div class="resume-live" id="resume-live"></div>
        <span class="sr-only" id="resume-live-status" role="status"></span>
        <div style="display:flex;gap:10px;align-items:center;margin-top:12px">
          <button class="btn btn-sm" id="btn-save-resume" title="把编辑器内容保存为新版本并立即生效（Ctrl+S）">${icon("check")}保存母版</button>
          <span class="chart-note" id="save-hint"></span>
        </div>
      </div>

      <div class="card">
        <div class="card-head">${cardTitle("定向到岗位", "briefcase", true)}</div>
        <div class="field">
          <label for="resume-job-pick">从岗位库选择${watchJobs.length ? "（关注优先）" : ""}</label>
          <select id="resume-job-pick">
            <option value="">— 选择岗位 —</option>
            ${jobGroups}
          </select>
        </div>
        <div class="field" style="margin-top:12px">
          <label for="resume-job">或粘贴岗位 ID（岗位详情页可一键带入）</label>
          <input type="text" id="resume-job" value="${esc(targetJob)}" placeholder="job_id">
        </div>
        <div class="chart-note left job-pick-hint" id="resume-job-hint">${esc(targetHint)}</div>
        <div class="job-focus" id="resume-job-focus" aria-label="目标岗位与技能命中"></div>
        <div style="display:flex;gap:9px;margin-top:12px">
          <button class="btn btn-sm" id="btn-tailor-run">生成定向版本</button>
        </div>
        ${questions.length ? `<div class="chart-note left" style="margin-top:12px">
          ${icon("info")} 生成时会先问你 ${questions.length} 个问题（在底部对话里回答）</div>` : ""}
        <div id="tailor-result" role="region" aria-label="定向版本结果" style="margin-top:14px"></div>
      </div>
    </div>

    <div class="card section resume-history" id="resume-history" ${historyRows.length ? "" : "hidden"}>${historyHTML()}</div>`;

  async function readResume() {
    let parsed;
    try { parsed = JSON.parse($("#resume-content").value); }
    catch (exc) { chatLog("err", "校验", "简历 JSON 不合法：" + exc.message); openDrawer(); return null; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      chatLog("err", "校验", "简历 JSON 必须是对象，例如 { \"name\": \"张三\", \"skills\": [] }");
      openDrawer();
      return null;
    }
    return parsed;
  }

  function setResumeLiveStatus(text) {
    const status = $("#resume-live-status");
    if (status) status.textContent = text;
  }

  let livePainted = false;
  function paintResumeLive(content) {
    const box = $("#resume-live");
    if (!box) return;
    if (!content) {
      box.innerHTML = `<span class="chart-note">${icon("info")} 读取母版后显示市场技能覆盖</span>`;
      setResumeLiveStatus("读取母版后显示市场技能覆盖");
      return;
    }
    const keys = resumeKeysFromContent(content);
    const market = marketCoverage(keys);
    if (!market) {
      const text = keys.length ? "市场技能词尚未加载，稍后刷新再看" : "母版 skills[] 为空，补上技能后自动计算覆盖";
      box.innerHTML = `<span class="chart-note">${icon("info")} ${text}</span>`;
      setResumeLiveStatus(text);
      return;
    }
    box.innerHTML = `<div class="live-cov ${market.pct < 35 ? "is-low" : ""} ${livePainted ? "is-updating" : ""}">
      <b>${market.pct}<small>%</small><em>覆盖</em></b>
      <div class="live-cov-body">
        <span class="live-cov-title">当前内容命中 <b>${market.covered}</b> / ${market.total} 个市场技能词 · 还缺 ${market.missing.length} 个</span>
        <div class="gap-meter" role="progressbar" aria-valuemin="0" aria-valuemax="100"
             aria-valuenow="${market.pct}" aria-label="当前简历内容的技能覆盖率"><i style="--gap-w:${market.pct}%"></i></div>
        <span class="live-cov-note">${market.missing.length
          ? `高频缺口：${market.missing.slice(0, 4).map((w) => `${esc(w.name)} ${w.count || 0} 岗`).join("、")}`
          : "市场高频词已全部覆盖"}</span>
      </div>
      <a class="link" href="#/skills?gap=1">技能对照 ${icon("chevron")}</a>
    </div>`;
    livePainted = true;
    setResumeLiveStatus(`简历技能覆盖 ${market.pct}%，缺口 ${market.missing.length} 个`);
  }

  paintResumeLive(resume ? resume.content : null);

  const resumeBox = $("#resume-content");
  const jobPick = $("#resume-job-pick");
  const jobInput = $("#resume-job");
  const jobHint = $("#resume-job-hint");
  const editorResume = () => {
    let parsed = null;
    try { parsed = JSON.parse(resumeBox.value); } catch {
      return { value: null, why: "JSON 不完整" };
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: null, why: "顶层需要一个 JSON 对象" };
    }
    return { value: parsed, why: "", signature: JSON.stringify(parsed) };
  };
  const editorSignature = () => {
    try { return JSON.stringify(JSON.parse(resumeBox.value)); } catch { return null; }
  };
  const isDirty = () => {
    const current = editorSignature();
    return current === null || current !== savedSignature;
  };
  let ownHash = location.hash;
  const describeJob = (jobId) => {
    if (!jobId) return "从岗位库选择，或粘贴岗位 ID（详情页可一键带入）";
    if (!jobById.has(jobId)) return `未在岗位库找到 ${jobId}，仍可尝试生成`;
    // 命中岗位后由下方焦点面板展示完整上下文，这里不再重复
    return "";
  };
  function jobFocusHTML(job, detail, tried = false) {
    const source = detail || job;
    const company = typeof job.company === "string" && job.company
      ? job.company : (detail?.company?.name || "");
    const meta = [company, source.salary, source.city, source.experience, source.degree]
      .filter((s) => typeof s === "string" && s).join(" · ");
    const jobSkills = detail && Array.isArray(detail.skills)
      ? detail.skills.filter((s) => typeof s === "string" && s.trim()) : [];
    const editor = editorResume();
    const keys = editor.value ? resumeKeysFromContent(editor.value) : null;
    const covered = keys && keys.length && jobSkills.length ? skillCoverage(jobSkills, keys) : null;
    let note = "";
    if (keys === null) note = `${editor.why}，技能命中暂不计算`;
    else if (detail && !jobSkills.length) note = "该岗位未提取到技能词";
    else if (!detail) note = tried ? "岗位详情暂不可用，仅显示摘要" : "正在读取岗位技能要求…";
    else if (!keys.length) note = "母版 skills[] 为空，补上技能后显示命中";
    return `<div class="job-focus-head">
        <div style="min-width:0">
          <div class="job-focus-title">${esc(job.title)}</div>
          <div class="chart-note">${esc(meta || "—")}</div>
        </div>
        <a class="link" href="#/jobs/${encodeURIComponent(job.id)}" title="打开岗位详情">岗位详情 ${icon("chevron")}</a>
      </div>
      ${jobSkills.length ? `<div class="job-focus-skills">
        <div class="skill-head"><span class="spec-label">技能要求</span>
          ${covered ? `<span class="mini ${covered.missing.length ? "mini-warn" : "mini-ok"}">当前内容命中 ${covered.covered.length}/${covered.list.length}</span>` : ""}
        </div>
        <div>${jobSkills.map((s) => {
          const hit = covered ? covered.covered.includes(s) : false;
          return `<span class="tag-outline skill-tag ${covered ? (hit ? "hit" : "gap") : ""}"
            title="${covered ? (hit ? "当前编辑内容已覆盖" : "当前编辑内容未覆盖") : ""}">${covered ? `<i class="dot ${hit ? "dot-pos" : "dot-gap"}"></i>` : ""}${esc(s)}</span>`;
        }).join("")}</div>
      </div>` : ""}
      ${note ? `<div class="chart-note" style="margin-top:8px">${icon("info")} ${note}</div>` : ""}`;
  }
  const focusState = { id: "", detail: null, seq: 0, tried: false };
  async function paintJobFocus() {
    const box = $("#resume-job-focus");
    if (!box) return;
    const id = jobInput.value.trim();
    const job = jobById.get(id);
    if (!job) {
      focusState.id = ""; focusState.detail = null; focusState.tried = false; focusState.seq += 1;
      box.innerHTML = "";
      return;
    }
    if (focusState.id === id) {
      const html = jobFocusHTML(job, focusState.detail, focusState.tried);
      if (html !== box.innerHTML) box.innerHTML = html;
      return;
    }
    const seq = ++focusState.seq;
    focusState.id = id;
    focusState.detail = null;
    focusState.tried = false;
    box.innerHTML = jobFocusHTML(job, null);
    const detail = await cachedDetail("job", { job_id: id }).catch(() => null);
    if (seq !== focusState.seq) return;
    focusState.detail = detail;
    focusState.tried = true;
    box.innerHTML = jobFocusHTML(job, detail, true);
  }
  function syncResumeHash(value) {
    const next = value ? `#/resume?job=${encodeURIComponent(value)}` : "#/resume";
    ownHash = next;
    if (location.hash === next) return;
    // 只改地址不重渲染，刷新或从历史回来仍带着目标岗位
    try { history.replaceState(null, "", next); } catch { /* 忽略不支持的环境 */ }
  }
  const syncJobPick = () => {
    const value = jobInput.value.trim();
    if (jobHint) jobHint.textContent = describeJob(value);
    if (jobPick) jobPick.value = jobById.has(value) ? value : "";
    paintJobFocus();
    syncResumeHash(value);
  };
  if (jobPick) jobPick.addEventListener("change", () => {
    if (jobPick.value) jobInput.value = jobPick.value;
    syncJobPick();
  });
  jobInput.addEventListener("input", syncJobPick);
  syncJobPick();

  let liveTimer = null;
  resumeBox.addEventListener("input", () => {
    const hint = $("#save-hint");
    if (hint) hint.textContent = "未保存修改";
    clearTimeout(liveTimer);
    // 停止输入后再算，避免大段粘贴时每个按键都跑一遍全量匹配
    liveTimer = setTimeout(() => {
      const editor = editorResume();
      if (editor.value) {
        if (hint) hint.textContent = editor.signature === savedSignature
          ? "内容与已保存版本一致" : "未保存修改";
        paintResumeLive(editor.value);
      } else {
        if (hint) hint.textContent = `${editor.why} · 修正后才能保存`;
        const box = $("#resume-live");
        if (box) box.innerHTML = `<span class="chart-note">${icon("info")} ${editor.why}，暂时无法计算覆盖</span>`;
        setResumeLiveStatus(`简历 ${editor.why}，覆盖暂不可计算`);
      }
      paintJobFocus();
    }, 220);
  });
  pageAbort.signal.addEventListener("abort", () => clearTimeout(liveTimer), { once: true });

  const pageGuard = {
    check: async () => {
      if (!isDirty()) return true;
      return askConfirm({
        title: "离开简历页？",
        body: "编辑器里还有未保存的修改，离开后会丢失。",
        confirmText: "丢弃并离开",
        danger: true,
      });
    },
    hash: () => ownHash,
  };
  leaveGuard = pageGuard;
  pageAbort.signal.addEventListener("abort", () => {
    if (leaveGuard === pageGuard) leaveGuard = null;
  }, { once: true });

  function paintHistory() {
    const box = $("#resume-history");
    if (!box) return;
    if (!historyRows.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = historyHTML();
  }

  function refreshActivePill() {
    const current = $("#resume-active-pill");
    const html = activePillHTML();
    if (!html) { current?.remove(); return; }
    if (current) { current.outerHTML = html; return; }
    $("#resume-master-pill")?.insertAdjacentHTML("afterend", html);
  }

  function mutateVersionConfirmed(versionId) {
    const row = versions.find((item) => item.id === versionId);
    if (row) row.confirmed = true;
    if (resume && resume.id === versionId) resume.confirmed = true;
    if (state.resume?.resume?.id === versionId) state.resume.resume.confirmed = true;
    activeVersion = versions.find((item) => item.confirmed) || null;
  }

  function setMasterPill(text, tone, versionId) {
    let pill = $("#resume-master-pill");
    if (!pill) {
      pill = document.createElement("span");
      pill.id = "resume-master-pill";
      $("#btn-refresh-resume")?.insertAdjacentElement("beforebegin", pill);
    }
    pill.className = `pill ${tone}`;
    pill.textContent = text;
    if (versionId) pill.dataset.resumeId = String(versionId);
    return pill;
  }

  function applyConfirmedUI(versionId) {
    if (editorVersionId === versionId) {
      setMasterPill(`#${versionId} 已确认`, "pill-ok", versionId);
      $("#btn-confirm-master")?.remove();
    }
    const card = document.querySelector(`.tailor-card[data-resume-id="${versionId}"]`);
    if (card) {
      const cardPill = card.querySelector("[data-tailor-pill]");
      if (cardPill) { cardPill.className = "pill pill-ok"; cardPill.textContent = "已确认"; }
      card.querySelector("[data-confirm-tailor]")?.remove();
      card.querySelector("[data-draft-note]")?.remove();
    }
  }

  async function confirmVersion(versionId) {
    const saved = await call("resume-confirm", { resume_id: versionId });
    if (!saved) return false;
    mutateVersionConfirmed(versionId);
    applyConfirmedUI(versionId);
    paintHistory();
    refreshActivePill();
    return true;
  }

  function syncResumeHistory(fresh) {
    if (!Array.isArray(fresh?.versions)) return;
    versions.splice(0, versions.length, ...fresh.versions);
    historyRows.splice(0, historyRows.length, ...versions.slice(0, 12));
    activeVersion = versions.find((row) => row && row.confirmed) || null;
    hasHistory = true;
    paintHistory();
    refreshActivePill();
  }

  async function loadVersion(versionId, btn) {
    if (isDirty() && !(await askConfirm({
      title: `载入版本 #${versionId}？`,
      body: "编辑器里还有未保存的修改，载入后会丢失。",
      confirmText: "丢弃并载入",
      danger: true,
    }))) return;
    btn.disabled = true;
    const data = await call("resume-version", { resume_id: versionId });
    btn.disabled = false;
    if (!data || !data.resume) {
      toast("读取版本失败，详情见运行日志", "warn");
      return;
    }
    const content = data.resume.content || {};
    clearTimeout(liveTimer);
    resumeBox.value = JSON.stringify(content, null, 2);
    paintResumeLive(content);
    paintJobFocus();
    editorVersionId = versionId;
    savedSignature = JSON.stringify(content);
    const hint = $("#save-hint");
    if (hint) hint.textContent = `已载入 #${versionId}（尚未生成新版本）`;
    setMasterPill(`#${versionId} 已载入`, "pill-cyan", versionId);
    $("#btn-confirm-master")?.remove();
    paintHistory();
    refreshActivePill();
    toast(`已载入版本 #${versionId} 到编辑器`);
    const rect = resumeBox.getBoundingClientRect();
    if (rect.top < 0 || rect.bottom > window.innerHeight) {
      resumeBox.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  $("#resume-history")?.addEventListener("click", (event) => {
    const loadBtn = event.target.closest("[data-load-version]");
    if (loadBtn) {
      void loadVersion(Number(loadBtn.dataset.loadVersion), loadBtn);
      return;
    }
    const confirmBtn = event.target.closest("[data-confirm-version]");
    if (confirmBtn) {
      confirmBtn.disabled = true;
      void confirmVersion(Number(confirmBtn.dataset.confirmVersion)).then((ok) => {
        if (!ok) {
          confirmBtn.disabled = false;
          toast("确认失败，详情见运行日志", "warn");
          return;
        }
        toast(`版本 #${confirmBtn.dataset.confirmVersion} 已确认生效`);
      });
    }
  });

  $("#btn-save-resume").addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    const content = await readResume();
    if (!content) return;
    clearTimeout(liveTimer);
    paintResumeLive(content);
    paintJobFocus();
    const hint = $("#save-hint");
    const signature = JSON.stringify(content);
    if (savedSignature === signature) {
      const loadedRow = versions.find((row) => row.id === editorVersionId);
      const label = editorVersionId ? `#${editorVersionId}` : "当前版本";
      if (hint) {
        hint.textContent = loadedRow && !loadedRow.confirmed
          ? `内容与草稿 ${label} 一致；在版本历史点「确认」即可生效`
          : `内容与 ${label} 一致，未创建新版本`;
      }
      toast("内容没有修改，未创建新版本", "info");
      return;
    }
    btn.disabled = true;
    if (hint) hint.textContent = "正在保存为母版版本…";
    try {
      const tmp = await window.api.writeTemp("resume_master.json", JSON.stringify(content, null, 2));
      if (!tmp?.ok || !tmp.path) {
        if (hint) hint.textContent = "临时文件写入失败，详情见运行日志";
        toast("保存失败，详情见运行日志", "warn");
        return;
      }
      const fresh = await call("resume-save", { resume: tmp.path });
      if (!fresh || !fresh.resume_id) {
        if (hint) hint.textContent = "保存失败，详情见运行日志";
        toast("保存失败，详情见运行日志", "warn");
        return;
      }
      state.resume = fresh;
      editorVersionId = fresh.resume_id;
      syncResumeHistory(fresh);
      savedSignature = signature;
      setMasterPill(`#${fresh.resume_id} 已确认`, "pill-ok", fresh.resume_id);
      $("#btn-confirm-master")?.remove();
      refreshActivePill();
      if (hint) hint.textContent = `已保存为版本 #${fresh.resume_id} 并生效`;
      toast(`母版已保存为版本 #${fresh.resume_id} 并生效`);
    } finally {
      btn.disabled = false;
    }
  });

  const saveShortcut = (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      if (!document.body.contains(resumeBox)) return;
      event.preventDefault();
      $("#btn-save-resume")?.click();
    }
  };
  document.addEventListener("keydown", saveShortcut);
  pageAbort.signal.addEventListener("abort", () => {
    document.removeEventListener("keydown", saveShortcut);
  }, { once: true });

  $("#btn-refresh-resume").addEventListener("click", async () => {
    if (isDirty() && !(await askConfirm({
      title: "刷新简历？",
      body: "编辑器里还有未保存的修改，刷新后会丢失。",
      confirmText: "丢弃并刷新",
      danger: true,
    }))) return;
    leaveGuard = null;
    state.resume = null;
    void router();
  });

  $("#btn-confirm-master")?.addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    const resumeId = editorVersionId || (resume && resume.id);
    if (!resumeId) return;
    btn.disabled = true;
    const ok = await confirmVersion(resumeId);
    if (!ok) {
      btn.disabled = false;
      toast("确认失败，详情见运行日志", "warn");
      return;
    }
    toast(`版本 #${resumeId} 已确认生效`);
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
        if (fresh) state.resume = fresh;
        syncResumeHistory(fresh);
        const box = $("#tailor-result");
        if (!box) return;
        const target = jobById.get(jobId);
        const skills = focusState.id === jobId && Array.isArray(focusState.detail?.skills)
          ? focusState.detail.skills : [];
        box.innerHTML = tailorResultHTML(fresh, target ? { ...target, skills } : null, content);
        if (!box.innerHTML) {
          box.innerHTML = `<div class="chart-note">${icon("alert")} 没有读到新版本，详情见底部运行日志</div>`;
          return;
        }
        const copyBtn = box.querySelector("[data-copy-tailor]");
        copyBtn?.addEventListener("click", async () => {
          try {
            await copyText(JSON.stringify(fresh.resume.content, null, 2));
            toast("定向简历 JSON 已复制");
          } catch {
            toast("复制失败，请检查剪贴板权限", "warn");
          }
        });
        const confirmBtn = box.querySelector("[data-confirm-tailor]");
        confirmBtn?.addEventListener("click", async () => {
          confirmBtn.disabled = true;
          const ok = await confirmVersion(fresh.resume.id);
          if (!ok) {
            confirmBtn.disabled = false;
            toast("确认失败，详情见运行日志", "warn");
            return;
          }
          toast(`版本 #${fresh.resume.id} 已确认生效`);
        });
      });
    });
    chatLog("step", "简历", "请在下方回答问题（可留空直接提交）");
  });
}

// ---------------------------------------------------------------- 模块面板
async function pageModules() {
  const cachedShell = !!(state.status && state.models);
  if (!cachedShell) {
    pageEl().innerHTML = loadingPage("模块", "正在读取模块清单…", `
      <div class="grid grid-4">${Array.from({ length: 4 }, () => `<div class="card skel-kpi"></div>`).join("")}</div>
      <div class="card skel-stage"></div>`);
    await loadBootstrap();
  }
  const status = state.status;
  if (!status) { pageEl().innerHTML = `<div class="empty">自检失败，无法读取模块清单</div>`; return; }

  const agents = status.agents || [];
  const backduty = agents.filter((a) => a.kind === "backduty");
  const processing = agents.filter((a) => a.kind !== "backduty");
  const withModels = agents.filter((a) => (a.requires_models || []).length);
  const enabled = agents.filter((a) => a.enabled !== false).length;
  const configured = agents.filter((a) => a.configured).length;
  const tools = new Set();
  agents.forEach((a) => {
    (a.tools || []).forEach((t) => tools.add(t));
    (a.mandatory_tools || []).forEach((t) => tools.add(t));
  });
  const sources = status.sources || [];
  const implemented = sources.filter((s) => s.implemented);
  const standalone = processing.filter((a) => a.name === "resume_score");

  pageEl().innerHTML = `
    <div class="page-head">
      <div>
        <div class="page-title">模块</div>
        <div class="page-sub">${agents.length} 个独立模块 · ${configured} 个有自定义配置 · 点击任意模块进入它的模型配置</div>
      </div>
      <div class="page-actions">
        <a class="btn btn-ghost btn-sm" href="#/settings">${icon("cog")}配置中心</a>
      </div>
    </div>

    <div class="grid grid-4">
      ${kpi(intText(agents.length), "模块总数", `${backduty.length} 背调 / ${processing.length} 加工`, "orange", "MODULES")}
      ${kpi(`${enabled}/${agents.length}`, "已启用", `${agents.length - enabled} 个停用后会被跳过`, "teal", "ACTIVE")}
      ${kpi(intText(withModels.length), "调用模型", "按能力独立覆盖", "purple", "MODEL")}
      ${kpi(intText(tools.size), "工具依赖", "HTTP / 浏览器 / CLI / 日志", "cyan", "TOOLS")}
    </div>

    <div class="card">
      <div class="card-head">
        ${cardTitle("模块流水线", "layers", true)}
        <div class="card-sub">采集 → 背调 → 公司评分 → 岗位适配 → 简历定制</div>
      </div>
      ${pipelineHTML()}
      <div class="chart-note left" style="margin-top:10px">
        流水线按阶段串联；每个模块只声明自己的工具与模型能力，停用任意模块不会影响其他模块。
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        ${cardTitle("背调模块", "building", true)}
        <div class="card-sub">BACKDUTY · ${backduty.length} 个 · 独立取证</div>
      </div>
      <div class="module-grid">
        ${backduty.map((a, i) => moduleCard(a, i + 1)).join("") || `<div class="empty">没有注册背调模块</div>`}
      </div>
    </div>

    <div class="card">
      <div class="card-head">
        ${cardTitle("加工模块", "cog", true)}
        <div class="card-sub">SCORING / TAILORING · ${processing.length} 个</div>
      </div>
      <div class="module-grid">
        ${processing.map((a, i) => moduleCard(a, backduty.length + i + 1)).join("") || `<div class="empty">没有注册加工模块</div>`}
      </div>
      ${standalone.length ? `<div class="chart-note left" style="margin-top:10px">
        ${standalone.map((a) => esc(a.name)).join("、")} 是独立评估模块，不在主流水线上，可从「简历」页单独运行。
      </div>` : ""}
    </div>

    <div class="card">
      <div class="card-head">
        ${cardTitle("数据源适配器", "database", true)}
        <div class="card-sub">SOURCE · ${implemented.length}/${sources.length} 已接入</div>
      </div>
      <div class="grid grid-2">
        ${sources.map((s) => `
          <div class="rank-row">
            <span class="dot" style="background:${s.implemented ? "var(--pink)" : "var(--faint)"}"></span>
            <span class="rank-label" style="width:auto;flex:1">${esc(s.label)}
              <span class="chart-note"> ${esc(s.name)}</span></span>
            ${s.implemented ? `<span class="pill pill-ok">已接入</span>` : `<span class="pill pill-dim">预留插槽</span>`}
          </div>`).join("") || `<div class="empty">没有数据源</div>`}
      </div>
      <div class="chart-note left" style="margin-top:10px">
        预留插槽只需实现 build_steps 即可接入新平台；采集阶段与背调阶段彼此独立。
      </div>
    </div>`;
}

// ---------------------------------------------------------------- 设置
const CAP_LABELS = {
  chat: ["对话能力", "CHAT"],
  embedding: ["向量能力", "EMBEDDING"],
  rerank: ["重排能力", "RERANK"],
};

function capLabel(kind) {
  return (CAP_LABELS[kind] || [kind, String(kind).toUpperCase()])[0];
}

function settingsAgentList(agents, selected) {
  const groups = [
    ["背调 · BACKDUTY", agents.filter((a) => a.kind === "backduty")],
    ["加工 · SCORING", agents.filter((a) => a.kind !== "backduty")],
  ];
  return groups.map(([label, list]) => `
    <div class="cfg-group-label">${esc(label)} · ${list.length}</div>
    ${list.map((a) => {
      const caps = a.requires_models || [];
      const alert = a.enabled !== false && agentModelAlert(a);
      return `<button class="agent-row ${a.name === selected ? "active" : ""} ${a.enabled === false ? "off" : ""}"
          data-agent-pick="${esc(a.name)}" title="${esc(a.description || a.name)}">
        <span class="dot"></span>
        <span class="agent-row-main">
          <span class="agent-row-name">${esc(a.name)}</span>
          <span class="agent-row-meta">${esc(caps.length ? agentModelLabel(a) : "规则模块")}${alert ? " · 模型不可用" : ""}</span>
        </span>
        <span class="agent-row-state">${a.enabled === false ? "OFF" : "ON"}</span>
      </button>`;
    }).join("")}`).join("");
}

function capRow(agent, kind) {
  const specs = ((state.models && state.models.models) || []).filter((m) => m.kind === kind);
  const enabledSpecs = specs.filter((m) => m.enabled);
  const override = (agent.model || {})[kind] || "";
  const def = defaultSpecName(kind);
  const defSpec = specOf(def);
  const shown = enabledSpecs.slice();
  if (override) {
    const current = specOf(override);
    if (current && !shown.some((m) => m.name === override)) shown.push(current);
  }
  const options = shown.map((m) => {
    const flags = [m.enabled ? "" : "已停用", m.has_key ? "" : "缺密钥"].filter(Boolean).join(" · ");
    return `<option value="${esc(m.name)}" ${m.name === override ? "selected" : ""}>${esc(m.name)}${m.model_id ? " · " + esc(m.model_id) : ""}${flags ? " · " + esc(flags) : ""}</option>`;
  }).join("");
  const chosen = override || def;
  const chosenSpec = specOf(chosen);
  const bad = !chosen || !chosenSpec || !chosenSpec.enabled || !chosenSpec.has_key;
  let note;
  if (override) {
    note = chosenSpec
      ? `自定义覆盖：${chosenSpec.enabled ? "已启用" : "规格已停用"}${chosenSpec.has_key ? " · 密钥就绪" : " · 缺少密钥"}`
      : "该覆盖指向未知规格，请恢复默认";
  } else if (def) {
    note = `跟随默认 → ${def}${defSpec && defSpec.has_key ? "（密钥就绪）" : "（缺少密钥，运行时会回退）"}`;
  } else {
    note = `没有已启用的 ${kind} 规格${specs.length ? "" : "（尚未注册）"}；先在下方「模型规格」启用一个，再回来选择。运行时会退回规则逻辑。`;
  }
  return `<div class="cap-row">
    <div class="cap-head">
      <span class="cap-name">${capLabel(kind)}</span>
      <span class="cap-en">${esc(kind)}</span>
      <span class="cap-tag" ${bad ? 'style="color:var(--amber);border-color:rgba(240,192,96,.35)"' : ""}>
        ${override ? `OVERRIDE · ${esc(override)}` : "FOLLOW DEFAULT"}</span>
    </div>
    <div class="cap-controls">
      <select class="cap-select" data-agent-model="${esc(agent.name)}" data-cap="${esc(kind)}" ${shown.length ? "" : "disabled"}>
        <option value="">跟随默认${def ? ` · ${esc(def)}` : ""}</option>
        ${options}
      </select>
      <button class="btn btn-ghost btn-sm" data-agent-model-reset="${esc(agent.name)}"
        data-cap="${esc(kind)}" ${override ? "" : "disabled"}>恢复默认</button>
    </div>
    <div class="cap-note">${esc(note)}</div>
  </div>`;
}

function agentDetailHTML(agent) {
  if (!agent) return `<div class="card"><div class="empty">没有可配置的模块</div></div>`;
  const enabled = agent.enabled !== false;
  const caps = agent.requires_models || [];
  const tools = [...new Set([...(agent.tools || []), ...(agent.mandatory_tools || [])])];
  const overrides = Object.keys(agent.model || {});
  const body = caps.length
    ? `<div class="cap-list">${caps.map((cap) => capRow(agent, cap)).join("")}</div>`
    : `<div class="agent-no-model">
        <b>规则模块 · 不调用模型</b>
        <p>这个模块由工具与规则驱动，当前没有模型能力需要选择。以后在代码里声明 requires_models，这里会自动出现按能力选择模型的控件。</p>
      </div>`;
  return `<div class="card agent-detail">
    <div class="agent-detail-head">
      <span class="agent-avatar">${icon("layers")}</span>
      <div class="agent-heading">
        <h2>${esc(agent.name)}</h2>
        <p>${esc(agent.description || "未填写描述")}</p>
      </div>
      <div class="agent-actions">
        <span class="pill ${enabled ? "pill-ok" : "pill-bad"}">${enabled ? "已启用" : "已停用"}</span>
        <label class="switch"><input type="checkbox" data-agent-enabled="${esc(agent.name)}" ${enabled ? "checked" : ""}> 参与流水线</label>
      </div>
    </div>
    <div class="agent-facts">
      ${fact("kind", agent.kind || "—")}
      ${fact("version", agent.version || "—")}
      ${fact("tools", tools.join(", ") || "无")}
      ${fact("models", caps.length ? caps.join(", ") : "不调用模型")}
      ${fact("overrides", overrides.length ? overrides.map((k) => `${k}=${agent.model[k]}`).join(", ") : "跟随默认")}
      ${fact("produces", (agent.produces || []).join(", ") || "—")}
    </div>
    <div class="agent-body">${body}</div>
  </div>`;
}

function modelCardsHTML() {
  const models = (state.models && state.models.models) || [];
  const agents = (state.status && state.status.agents) || [];
  if (!models.length) return `<div class="empty">没有模型规格</div>`;
  return `<div class="model-grid">${models.map((m) => {
    const users = agents.filter((a) => Object.values(a.model || {}).includes(m.name));
    return `<div class="model-card ${m.enabled ? "" : "is-off"}">
      <div class="model-head">
        <b>${esc(m.name)}</b>
        <span class="pill ${m.has_key ? "pill-ok" : "pill-warn"}">${m.has_key ? "KEY" : "NO KEY"}</span>
        <label><input type="checkbox" data-model-enabled="${esc(m.name)}" ${m.enabled ? "checked" : ""}>启用</label>
      </div>
      <div class="model-body">
        <label class="model-field">MODEL ID
          <input type="text" data-model-id="${esc(m.name)}" value="${esc(m.model_id || "")}" title="供应商侧模型 id，回车生效">
        </label>
        <div class="model-meta">
          <span>${esc(m.kind)} · ${esc(m.provider)}</span>
          <span>${m.dimension ? "dim " + esc(m.dimension) : "—"}</span>
        </div>
        ${m.note ? `<p class="model-note">${esc(m.note)}</p>` : ""}
        <div class="model-users">模块覆盖：${users.length
          ? users.map((u) => `<b>${esc(u.name)}</b>`).join("、") : "—"}</div>
      </div>
    </div>`;
  }).join("")}</div>`;
}

async function pageSettings(params) {
  if (!state.status || !state.models) {
    pageEl().innerHTML = loadingPage("配置中心", "每个模块独立启停与选择模型 · 写回 config/agents.json 与 config/models.json · 立即生效", `
      <div class="cfg-layout">
        <div class="card cfg-side"><div class="skel" style="width:100px;height:12px"></div><div class="skel-lines" style="margin-top:18px">${Array.from({ length: 7 }, () => `<div class="skel" style="width:88%;height:22px"></div>`).join("")}</div></div>
        <div class="cfg-main"><div class="card"><div class="skel" style="width:120px;height:12px"></div><div class="skel-chart" style="height:280px"></div></div></div>
      </div>`);
    await loadBootstrap();
  }
  const status = state.status;
  const models = state.models;
  if (!status) {
    pageEl().innerHTML = loadingPage("配置中心", "自检失败", `<div class="empty">自检失败，无法读取配置</div>`);
    return;
  }

  const agents = status.agents || [];
  if (params && params.agent && agents.some((a) => a.name === params.agent)) {
    state.cfgAgent = params.agent;
  }
  if (!agents.some((a) => a.name === state.cfgAgent)) state.cfgAgent = (agents[0] || {}).name || "";
  const selected = agents.find((a) => a.name === state.cfgAgent) || null;
  const db = status.db || {};
  const login = status.login || {};
  const enabled = agents.filter((a) => a.enabled !== false).length;
  const configured = agents.filter((a) => a.configured).length;
  const modelList = (state.models && state.models.models) || [];

  pageEl().innerHTML = `
    <div class="page-head">
      <div>
        <div class="page-title">配置中心</div>
        <div class="page-sub">每个模块独立启停与选择模型 · 写回 config/agents.json 与 config/models.json · 立即生效</div>
      </div>
      <div class="page-actions">
        <span class="pill pill-ok">${enabled}/${agents.length} 启用</span>
        <span class="pill ${configured ? "pill-cyan" : "pill-dim"}">${configured} 个自定义</span>
      </div>
    </div>

    <div class="cfg-layout">
      <aside class="card cfg-side">
        <div class="card-head">
          ${cardTitle("模块清单", "layers", true)}
          <div class="card-sub">${agents.length} 个</div>
        </div>
        <div id="agent-list">${settingsAgentList(agents, state.cfgAgent)}</div>
        <div class="chart-note left" style="padding:10px 17px 4px">
          规则模块不调用模型；声明了 requires_models 的模块会在这里按能力选择模型。
        </div>
      </aside>

      <div class="cfg-main">
        <div id="agent-detail-host">${agentDetailHTML(selected)}</div>

        <div class="card">
          <div class="card-head">
            ${cardTitle("模型规格", "layers", true)}
            <div class="card-sub">${modelList.length} 个 · 全局可用性</div>
          </div>
          <div id="model-grid-host">${modelCardsHTML()}</div>
          <div class="chart-note left" style="margin-top:10px">
            密钥来自环境变量或 .state/ark_key.txt，仓库与配置文件中不保存密钥。
          </div>
        </div>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <div class="card-head">
          ${cardTitle("数据库", "database", true)}
          ${db.ok ? `<span class="pill pill-ok">${icon("check")}正常</span>` : `<span class="pill pill-bad">异常</span>`}
        </div>
        <dl class="kv">
          <dt>岗位</dt><dd>${intText(db.jobs)}</dd>
          <dt>公司</dt><dd>${intText(db.companies)}</dd>
          <dt>打分记录</dt><dd>${intText(db.company_score)}</dd>
          <dt>背调证据</dt><dd>${intText(db.backduty_evidence)}</dd>
          <dt>天眼查原文</dt><dd>${intText(db.backduty_raw)}</dd>
          <dt>适配度</dt><dd>${intText(db.job_fit)}</dd>
          <dt>简历版本</dt><dd>${intText(db.resume_version)}</dd>
          <dt>报错日志</dt><dd>${intText(db.agent_error)}</dd>
        </dl>
        <div style="display:flex;gap:9px;margin-top:14px;flex-wrap:wrap">
          <button class="btn btn-sm" id="btn-init">${icon("refresh")}初始化 / 建表</button>
          <button class="btn btn-ghost btn-sm" id="btn-refresh-settings">刷新</button>
        </div>
      </div>

      <div class="card">
        <div class="card-head">${cardTitle("数据源", "briefcase", true)}
          <div class="card-sub">SOURCE ADAPTERS</div></div>
        ${(status.sources || []).map((s) => `
          <div class="rank-row">
            <span class="dot" style="background:${s.implemented ? "var(--pink)" : "var(--faint)"}"></span>
            <span class="rank-label" style="width:auto;flex:1">${esc(s.label)}
              <span class="chart-note"> ${esc(s.name)}</span></span>
            ${s.implemented ? `<span class="pill pill-ok">已接入</span>` : `<span class="pill pill-dim">预留</span>`}
          </div>`).join("")}
        <div class="chart-note left" style="margin-top:10px">预留插槽：实现 build_steps 即可接入新平台</div>
      </div>
    </div>

    <div class="card" id="backup-card">
      <div class="card-head">${cardTitle("本地数据", "database", true)}
        <div class="card-sub">只存本机 · 不含数据库、登录态与密钥</div></div>
      <div class="backup-body">
        <div class="backup-stats">
          <div class="backup-stat"><b>${watch.companies.size}</b><span>关注公司</span></div>
          <div class="backup-stat"><b>${watch.jobs.size}</b><span>关注岗位</span></div>
          <div class="backup-stat"><b>${Object.keys(track).length}</b><span>跟进记录</span></div>
        </div>
        <div class="backup-actions">
          <button type="button" class="btn btn-sm" id="btn-backup-export">${icon("download")}导出备份</button>
          <button type="button" class="btn btn-ghost btn-sm" id="btn-backup-import">${icon("upload")}导入备份</button>
        </div>
      </div>
      <div class="backup-status chart-note left" id="backup-status" role="status">
        关注、对比选择与投递跟进会随备份迁移；也可把 JSON 备份拖到本卡片导入。
      </div>
      <div class="backup-panel" id="backup-panel" hidden></div>
    </div>

    <div class="card" id="notify-card">
      <div class="card-head">${cardTitle("桌面提醒", "alert", true)}
        <div class="card-sub">窗口失焦或最小化时 · 仅本机</div></div>
      <label class="notify-row" for="notify-desktop">
        <input type="checkbox" id="notify-desktop" ${notifyPref ? "checked" : ""}>
        <span class="notify-copy">
          <b>面试、Offer 与流水线通知</b>
          <em>30 分钟面试提醒、面试开始 / 结束、Offer 截止前 24 小时与截止时刻；采集在后台结束或中断时也会提醒。点击通知可回到对应页面。</em>
        </span>
        <span class="pill pill-dim" id="notify-state" role="status">检查中</span>
      </label>
      <div class="notify-foot">
        <button type="button" class="btn btn-ghost btn-sm" id="btn-notify-test">${icon("alert")}发送测试通知</button>
        <span class="chart-note">需要系统允许 JobsDesktop 通知；窗口在前台时仍用页内提示。</span>
      </div>
    </div>

    <div class="card">
      <div class="card-head">${cardTitle("平台登录", "check", true)}
        <div class="card-sub">会弹出真实浏览器窗口 · 登录态存 .state/login</div></div>
      <div style="display:flex;align-items:flex-start;gap:24px;flex-wrap:wrap">
        <div style="flex:1;min-width:260px">
          <div class="checkbox-row" id="login-platforms">
            ${(status.platforms || []).map((p) =>
              `<label title="${esc(p.note || "")}"><input type="checkbox" data-login="${esc(p.key)}"> ${esc(p.label)}</label>`).join("")}
          </div>
          <div style="display:flex;gap:12px;align-items:center;margin-top:14px;flex-wrap:wrap">
            <button class="btn btn-sm" id="btn-login">${icon("check")}登录所选</button>
            <span class="chart-note">背调时自动带上登录态</span>
          </div>
        </div>
        <div style="flex:1;min-width:220px">
          ${Object.entries(login).length
            ? Object.entries(login).map(([platform, v]) => `
              <div class="rank-row"><span class="rank-label" style="width:auto;flex:1">${esc(platform)}</span>
                <span class="pill ${(v === "ok" || (v && v.status === "ok")) ? "pill-ok" : "pill-dim"}">
                  ${esc(typeof v === "string" ? v : (v && v.status) || "未知")}</span></div>`).join("")
            : `<div class="chart-note left">还没有登录记录</div>`}
        </div>
      </div>
    </div>`;

  renderHud();
  renderTopbar();
  bindSettings();

  if (pendingBackupFocus) {
    pendingBackupFocus = false;
    $("#backup-card")?.scrollIntoView({ block: "center" });
    $("#btn-backup-export")?.focus({ preventScroll: true });
  }
  if (params && params.agent) {
    const row = $(".agent-row.active");
    if (row) row.scrollIntoView({ block: "nearest" });
  }
}

function bindSettings() {
  pendingBackup = null;
  bindAgentPicks();
  bindAgentControls();
  bindModelSpecs();

  const backupExport = $("#btn-backup-export");
  if (backupExport) backupExport.addEventListener("click", exportBackup);
  const backupImport = $("#btn-backup-import");
  if (backupImport) backupImport.addEventListener("click", importBackup);

  const notifyToggle = $("#notify-desktop");
  const notifyState = $("#notify-state");
  const notifyTest = $("#btn-notify-test");
  const setNotifyState = (label, cls) => {
    if (!notifyState) return;
    notifyState.textContent = label;
    notifyState.className = `pill ${cls}`;
  };
  const syncNotifyState = async () => {
    if (!notifySupported()) {
      setNotifyState("仅窗口内", "pill-dim");
      if (notifyToggle) notifyToggle.disabled = true;
      if (notifyTest) notifyTest.disabled = true;
      return;
    }
    let probe = null;
    try {
      probe = await window.api.notifyProbe();
    } catch {
      probe = null;
    }
    const supported = !!probe?.supported;
    if (notifyToggle) notifyToggle.disabled = !supported;
    if (notifyTest) notifyTest.disabled = !supported || !notifyPref;
    setNotifyState(supported ? (notifyPref ? "已开启" : "已关闭") : "系统不支持",
      supported ? (notifyPref ? "pill-ok" : "pill-dim") : "pill-bad");
  };
  notifyToggle?.addEventListener("change", () => {
    notifyPref = notifyToggle.checked;
    saveNotifyPref();
    if (notifyTest) notifyTest.disabled = !notifyPref;
    setNotifyState(notifyPref ? "已开启" : "已关闭", notifyPref ? "pill-ok" : "pill-dim");
    toast(notifyPref ? "桌面提醒已开启 · 窗口不在前台时发送系统通知" : "桌面提醒已关闭", notifyPref ? "ok" : "info");
  });
  notifyTest?.addEventListener("click", async () => {
    if (!notifyPref) {
      toast("先开启桌面提醒", "warn");
      return;
    }
    const ok = await sendDesktopNotification("桌面提醒测试", "如果你看到这条通知，面试与 Offer 提醒可以正常送达。");
    toast(ok ? "测试通知已发送 · 请查看系统通知中心" : "系统通知发送失败，请检查系统通知权限", ok ? "ok" : "warn");
  });
  void syncNotifyState();

  const backupCard = $("#backup-card");
  if (backupCard) {
    let dragDepth = 0;
    const settle = () => {
      dragDepth = 0;
      backupCard.classList.remove("is-dragover");
    };
    backupCard.addEventListener("dragenter", (event) => {
      if (!event.dataTransfer || ![...event.dataTransfer.types].includes("Files")) return;
      event.preventDefault();
      dragDepth += 1;
      backupCard.classList.add("is-dragover");
    });
    backupCard.addEventListener("dragover", (event) => {
      if (!event.dataTransfer || ![...event.dataTransfer.types].includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    });
    backupCard.addEventListener("dragleave", (event) => {
      if (!backupCard.contains(event.relatedTarget)) settle();
    });
    backupCard.addEventListener("drop", (event) => {
      event.preventDefault();
      settle();
      importDroppedBackup(event.dataTransfer?.files?.[0]);
    });
    if (droppedBackupFile) {
      const file = droppedBackupFile;
      droppedBackupFile = null;
      backupCard.scrollIntoView({ block: "center" });
      importDroppedBackup(file);
    }
  }

  const initBtn = $("#btn-init");
  if (initBtn) initBtn.addEventListener("click", async () => {
    chatLog("step", "初始化", "开始建表…");
    openDrawer();
    const result = await call("init");
    chatLog("step", "初始化", result ? "完成" : "失败");
    await pageSettings({ agent: state.cfgAgent });
  });

  const refreshBtn = $("#btn-refresh-settings");
  if (refreshBtn) refreshBtn.addEventListener("click", () => pageSettings({ agent: state.cfgAgent }));

  const loginBtn = $("#btn-login");
  if (loginBtn) loginBtn.addEventListener("click", async () => {
    const platforms = $$("input[data-login]:checked").map((node) => node.dataset.login);
    if (!platforms.length) { chatLog("err", "校验", "请选择平台"); openDrawer(); return; }
    openDrawer();
    chatLog("step", "登录", `将为 ${platforms.join("、")} 弹出浏览器`);
    await window.api.stream("login", { platforms: platforms.join(",") }, (event) => {
      if (event.type === "login") chatLog("step", "登录", `${event.platform}: ${event.message}`);
      else if (event.type === "step") chatLog("step", "登录", `${event.name} ${event.detail || ""}`);
      else if (event.type === "error") chatLog("err", "登录", event.message || "");
      else if (event.type === "__done__") {
        chatLog("step", "登录", "流程结束");
        pageSettings({ agent: state.cfgAgent });
      }
    });
  });
}

function bindAgentPicks() {
  $$("[data-agent-pick]").forEach((row) => row.addEventListener("click", () => {
    state.cfgAgent = row.dataset.agentPick;
    history.replaceState(null, "", `#/settings?agent=${encodeURIComponent(state.cfgAgent)}`);
    paintAgentArea();
  }));
}

function bindAgentControls() {
  const enableBox = $("[data-agent-enabled]");
  if (enableBox) enableBox.addEventListener("change", async () => {
    const name = enableBox.dataset.agentEnabled;
    const enable = enableBox.checked;
    const res = await window.api.call("agent-set",
      enable ? { name, enable: true } : { name, disable: true });
    if (res.code !== 0) {
      chatLog("err", "配置", `${name} 写入失败：${(res.stderr || res.stdout || "").trim() || res.code}`);
      openDrawer();
      enableBox.checked = !enable;
      return;
    }
    chatLog("step", "配置", `${name} 已${enable ? "启用" : "停用"}`);
    await reloadStatus();
    paintAgentArea();
  });

  $$("[data-agent-model]").forEach((select) => select.addEventListener("change", async () => {
    const name = select.dataset.agentModel;
    const cap = select.dataset.cap;
    const value = select.value;
    const res = await window.api.call("agent-set", value
      ? { name, model: `${cap}=${value}` }
      : { name, "model-default": cap });
    if (res.code !== 0) {
      chatLog("err", "配置", `${name} 的 ${cap} 模型写入失败：${(res.stderr || res.stdout || "").trim() || res.code}`);
      openDrawer();
      return;
    }
    chatLog("step", "配置", `${name} · ${cap} → ${value || "跟随默认"}`);
    await reloadStatus();
    paintAgentArea();
  }));

  $$("[data-agent-model-reset]").forEach((btn) => btn.addEventListener("click", async () => {
    const name = btn.dataset.agentModelReset;
    const cap = btn.dataset.cap;
    const res = await window.api.call("agent-set", { name, "model-default": cap });
    if (res.code !== 0) {
      chatLog("err", "配置", `${name} 的 ${cap} 恢复默认失败：${(res.stderr || res.stdout || "").trim() || res.code}`);
      openDrawer();
      return;
    }
    chatLog("step", "配置", `${name} · ${cap} 已恢复默认`);
    await reloadStatus();
    paintAgentArea();
  }));
}

function bindModelSpecs() {
  $$("[data-model-enabled]").forEach((box) => box.addEventListener("change", async () => {
    const name = box.dataset.modelEnabled;
    const enable = box.checked;
    const res = await window.api.call("model-set", enable
      ? { spec: name, enable: true }
      : { spec: name, disable: true });
    if (res.code !== 0) {
      chatLog("err", "配置", `${name} 写入失败：${(res.stderr || res.stdout || "").trim() || res.code}`);
      openDrawer();
      box.checked = !enable;
      return;
    }
    chatLog("step", "配置", `${name} 已${enable ? "启用" : "停用"}`);
    await reloadModels();
    paintAgentArea();
  }));

  $$("[data-model-id]").forEach((input) => input.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    const name = input.dataset.modelId;
    const value = input.value.trim();
    if (!value) return;
    const res = await window.api.call("model-set", { spec: name, "model-id": value });
    if (res.code !== 0) {
      chatLog("err", "配置", `${name} 的模型 id 写入失败：${(res.stderr || res.stdout || "").trim() || res.code}`);
      openDrawer();
      return;
    }
    chatLog("step", "配置", `${name} 模型 id 改为 ${value}`);
    await reloadModels();
    paintAgentArea();
  }));
}

async function reloadStatus() {
  const fresh = await call("status");
  if (fresh) state.status = fresh;
  return fresh;
}

async function reloadModels() {
  const fresh = await call("models");
  if (fresh) state.models = fresh;
  return fresh;
}

function paintAgentArea() {
  const agents = (state.status && state.status.agents) || [];
  if (!agents.some((a) => a.name === state.cfgAgent)) state.cfgAgent = (agents[0] || {}).name || "";
  const selected = agents.find((a) => a.name === state.cfgAgent) || null;
  const list = $("#agent-list");
  const detail = $("#agent-detail-host");
  if (list) list.innerHTML = settingsAgentList(agents, state.cfgAgent);
  if (detail) detail.innerHTML = agentDetailHTML(selected);
  const host = $("#model-grid-host");
  if (host) host.innerHTML = modelCardsHTML();
  bindAgentPicks();
  bindAgentControls();
  bindModelSpecs();
  renderHud();
  renderTopbar();
}

// ---------------------------------------------------------------- 启动
(function boot() {
  window.api?.onNotifyOpen?.((href) => {
    if (typeof href === "string" && href.startsWith("#/")) go(href);
  });
  initStorageGuard();
  renderHud();
  renderTopbar();
  scheduleSnoozeWake();
  scheduleInterviewWake();
  scheduleOfferWake();
  void loadBootstrap();
  void router();
})();
