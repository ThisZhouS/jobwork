// 主进程：窗口 + 调 Python CLI + IPC 桥。
// 所有与后端的交互都集中在这里，渲染进程只发动作名和参数。
const { app, BrowserWindow, ipcMain, shell, dialog, clipboard, Notification, screen } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const { readWindowState, fitWindowBounds, writeWindowState } = require("./window-state");
const { killProcessTree } = require("./process-tree");

const ROOT = app.isPackaged
  ? path.join(process.resourcesPath, "backend")
  : path.resolve(__dirname, "..");
const STATE_ROOT = app.isPackaged
  ? path.join(app.getPath("userData"), ".state")
  : path.join(ROOT, ".state");
const CONFIG_ROOT = app.isPackaged
  ? path.join(app.getPath("userData"), "config")
  : path.join(ROOT, "config");
const PY = process.env.PYTHON || "python";

// 首次运行时把只读的默认配置复制到用户目录；之后设置页可以正常写回。
function ensureConfig() {
  fs.mkdirSync(STATE_ROOT, { recursive: true });
  fs.mkdirSync(CONFIG_ROOT, { recursive: true });
  const source = path.join(ROOT, "config");
  if (!fs.existsSync(source)) return;
  for (const name of fs.readdirSync(source)) {
    const target = path.join(CONFIG_ROOT, name);
    if (!fs.existsSync(target)) {
      fs.cpSync(path.join(source, name), target, { recursive: true });
    }
  }
}
ensureConfig();

const ENV = {
  ...process.env,
  PYTHONPATH: ROOT,
  PYTHONIOENCODING: "utf-8",
  PYTHONUTF8: "1",
  BOSS_STATE_DIR: STATE_ROOT,
  BOSS_CONFIG_DIR: CONFIG_ROOT,
};

let win = null;
let windowStateTimer = 0;
const streams = new Map(); // streamId -> child process
const WINDOW_STATE_FILE = path.join(STATE_ROOT, "window-state.json");
const MIN_WINDOW = { width: 1100, height: 700 };
const DEFAULT_WINDOW = { width: 1440, height: 900 };

function savedWindowState() {
  const saved = readWindowState(WINDOW_STATE_FILE);
  if (!saved) return null;
  const areas = screen.getAllDisplays().map((display) => display.workArea);
  const bounds = fitWindowBounds(saved.bounds, areas, screen.getPrimaryDisplay().workArea, MIN_WINDOW);
  return bounds ? { bounds, maximized: saved.maximized } : null;
}

function persistWindowState() {
  if (!win || win.isDestroyed() || win.isMinimized()) return;
  writeWindowState(WINDOW_STATE_FILE, win.getNormalBounds(), win.isMaximized());
}

function scheduleWindowStateSave() {
  clearTimeout(windowStateTimer);
  windowStateTimer = setTimeout(persistWindowState, 450);
}

function createWindow() {
  const saved = savedWindowState();
  win = new BrowserWindow({
    ...(saved?.bounds || DEFAULT_WINDOW),
    minWidth: MIN_WINDOW.width,
    minHeight: MIN_WINDOW.height,
    backgroundColor: "#040406",
    title: "求职背调工作台",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // 提醒依赖渲染进程的 setTimeout；后台节流会让面试/Offer 提醒迟到。
      backgroundThrottling: false,
    },
  });
  // 不允许页面自己开新窗口或导航到外部站点；外链统一走 openExternal。
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (event, url) => {
    if (url !== win.webContents.getURL()) event.preventDefault();
  });
  win.webContents.session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  if (saved?.maximized) win.maximize();
  win.on("resize", scheduleWindowStateSave);
  win.on("move", scheduleWindowStateSave);
  win.on("maximize", persistWindowState);
  win.on("unmaximize", persistWindowState);
  win.on("close", () => {
    clearTimeout(windowStateTimer);
    persistWindowState();
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.on("closed", () => {
    clearTimeout(windowStateTimer);
    win = null;
  });
}

// ---------------------------------------------------------------- 调用
// 一次性命令：收集 stdout 按 JSON 解析
function runOnce(args) {
  return new Promise((resolve) => {
    const argv = ["-m", "boss_crawler", "app", ...args, "--json"];
    const child = spawn(PY, argv, { cwd: ROOT, env: ENV, windowsHide: true });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => { stdout += d.toString("utf8"); });
    child.stderr.on("data", (d) => { stderr += d.toString("utf8"); });
    child.on("close", (code) => {
      const text = stdout.trim();
      let data = null;
      try {
        data = JSON.parse(text.split("\n").filter(Boolean).pop() || "null");
      } catch (e) {
        // 有些命令会输出多行 JSONL，取最后一行
      }
      resolve({ code, data, stdout: text, stderr: stderr.trim() });
    });
    child.on("error", (err) => {
      resolve({ code: -1, data: null, stdout: "", stderr: String(err) });
    });
  });
}

// 流式命令：逐行解析 JSONL，事件推给渲染进程
function runStream(streamId, args, event) {
  const argv = ["-m", "boss_crawler", "app", ...args, "--json"];
  const child = spawn(PY, argv, { cwd: ROOT, env: ENV, windowsHide: true });
  streams.set(streamId, child);
  let buffer = "";
  child.stdout.on("data", (d) => {
    buffer += d.toString("utf8");
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const text = line.trim();
      if (!text) continue;
      try {
        event.reply("app:stream:event", streamId, JSON.parse(text));
      } catch (e) { /* 忽略非 JSON 行 */ }
    }
  });
  child.stderr.on("data", (d) => {
    event.reply("app:stream:stderr", streamId, d.toString("utf8"));
  });
  child.on("close", (code) => {
    streams.delete(streamId);
    event.reply("app:stream:done", streamId, code);
  });
  child.on("error", (err) => {
    streams.delete(streamId);
    event.reply("app:stream:done", streamId, -1, String(err));
  });
}

// ---------------------------------------------------------------- IPC
// 只接受普通动作名/参数名，避免渲染层把任意参数拼进命令行。
function buildArgv(action, args) {
  if (typeof action !== "string" || !/^[a-z][a-z0-9-]{0,31}$/.test(action)) return null;
  const argv = [action];
  for (const [k, v] of Object.entries(args || {})) {
    if (!/^[a-z][a-z0-9_]*$/i.test(k)) return null;
    if (v === undefined || v === null || v === "") continue;
    if (typeof v === "boolean") { if (v) argv.push(`--${k.replace(/_/g, "-")}`); }
    else argv.push(`--${k.replace(/_/g, "-")}`, String(v));
  }
  return argv;
}

ipcMain.handle("app:call", async (_e, action, args) => {
  const argv = buildArgv(action, args);
  if (!argv) return { code: -1, data: null, stdout: "", stderr: "非法命令参数" };
  return runOnce(argv);
});

ipcMain.handle("app:stream:start", (event, streamId, action, args) => {
  if (typeof streamId !== "string" || !/^s[0-9-]+$/.test(streamId)) {
    return { ok: false, error: "非法 streamId" };
  }
  const argv = buildArgv(action, args);
  if (!argv) return { ok: false, error: "非法命令参数" };
  runStream(streamId, argv, event);
  return { ok: true };
});

ipcMain.handle("app:stream:cancel", (_e, streamId) => {
  const child = streams.get(streamId);
  if (child) { killProcessTree(child); streams.delete(streamId); }
  return { ok: true };
});

ipcMain.handle("app:open-external", async (_e, url) => {
  if (typeof url !== "string" || !/^https?:\/\//i.test(url)) return { ok: false };
  try {
    await shell.openExternal(url);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
});

// 把渲染进程要传的 JSON 写到临时文件，避免命令行长度/转义问题。
// 文件名必须落在 tmp 目录内，防止 ../ 路径穿越。
const TEMP_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
ipcMain.handle("app:write-temp", (_e, name, content) => {
  if (typeof name !== "string" || !TEMP_NAME.test(name)) {
    return { ok: false, error: "非法文件名" };
  }
  if (typeof content !== "string") {
    return { ok: false, error: "内容必须是文本" };
  }
  const dir = path.join(STATE_ROOT, "tmp");
  const file = path.join(dir, name);
  if (path.dirname(file) !== dir) return { ok: false, error: "非法路径" };
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(file, content, "utf8");
  return { ok: true, path: file };
});

// ---------------------------------------------------------------- 桌面通知
// 渲染进程只传纯文本与站内 hash 路由；点击通知由主进程聚焦窗口并跳到对应岗位。
const NOTIFY_TITLE_MAX = 80;
const NOTIFY_BODY_MAX = 240;
const NOTIFY_HREF = /^#\/[A-Za-z0-9/_?=&%.-]{1,200}$/;
const liveNotes = new Set();

ipcMain.handle("notify:probe", () => ({ supported: Notification.isSupported() }));

ipcMain.handle("notify:show", (_event, payload) => {
  if (!Notification.isSupported()) return { ok: false, supported: false };
  const title = typeof payload?.title === "string" ? payload.title.trim().slice(0, NOTIFY_TITLE_MAX) : "";
  const body = typeof payload?.body === "string" ? payload.body.trim().slice(0, NOTIFY_BODY_MAX) : "";
  if (!title) return { ok: false, supported: true, error: "通知标题为空" };
  const href = typeof payload?.href === "string" && NOTIFY_HREF.test(payload.href) ? payload.href : "";
  try {
    const note = new Notification({ title, body, silent: payload?.silent === true });
    liveNotes.add(note);
    note.on("close", () => liveNotes.delete(note));
    note.on("failed", () => liveNotes.delete(note));
    note.on("click", () => {
      if (!win || win.isDestroyed()) return;
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
      if (href) win.webContents.send("notify:open", href);
    });
    note.show();
    return { ok: true, supported: true };
  } catch (err) {
    return { ok: false, supported: true, error: String(err) };
  }
});

// ---------------------------------------------------------------- 剪贴板
// file:// 页面没有 clipboard 写权限，统一走主进程。
const CLIPBOARD_MAX = 2 * 1024 * 1024;
ipcMain.handle("clipboard:write", (_event, text) => {
  if (typeof text !== "string" || !text || text.length > CLIPBOARD_MAX) return { ok: false };
  clipboard.writeText(text);
  return { ok: true };
});

// ---------------------------------------------------------------- 本地备份
// 只通过系统对话框选择路径，渲染进程无法指定任意路径。
const BACKUP_MAX = 4 * 1024 * 1024;

ipcMain.handle("backup:save", async (event, payload) => {
  const { name, text } = payload || {};
  if (typeof text !== "string" || Buffer.byteLength(text, "utf8") > BACKUP_MAX) {
    return { ok: false, error: "备份内容为空或超过 4 MB" };
  }
  const safeName = typeof name === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(name)
    ? name : `swarm-backup-${new Date().toISOString().slice(0, 10)}.json`;
  const owner = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showSaveDialog(owner, {
    title: "导出本地关注与跟进数据",
    defaultPath: path.join(app.getPath("documents"), safeName),
    filters: [{ name: "SWARM 备份", extensions: ["json"] }],
  });
  if (result.canceled || !result.filePath) return { ok: false, canceled: true };
  try {
    await fs.promises.writeFile(result.filePath, text, "utf8");
    return { ok: true, filePath: result.filePath };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
});

ipcMain.handle("backup:open", async (event) => {
  const owner = BrowserWindow.fromWebContents(event.sender);
  const result = await dialog.showOpenDialog(owner, {
    title: "导入本地关注与跟进数据",
    properties: ["openFile"],
    filters: [{ name: "SWARM 备份", extensions: ["json"] }],
  });
  if (result.canceled || !result.filePaths.length) return { ok: false, canceled: true };
  const filePath = result.filePaths[0];
  try {
    const stat = await fs.promises.stat(filePath);
    if (!stat.isFile() || stat.size > BACKUP_MAX) {
      return { ok: false, error: "文件超过 4 MB，不像是 SWARM 备份" };
    }
    const text = await fs.promises.readFile(filePath, "utf8");
    return { ok: true, filePath, text };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
});

// ---------------------------------------------------------------- 生命周期
// 本地状态与窗口状态只允许一个实例写入；再次启动时唤醒已有窗口。
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!win || win.isDestroyed()) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });
  app.whenReady().then(() => {
    // Windows 通知需要稳定的 AppUserModelID，与 electron-builder 的 appId 一致。
    if (process.platform === "win32") app.setAppUserModelId("com.thiszhous.jobsdesktop");
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}

app.on("window-all-closed", () => {
  for (const child of streams.values()) killProcessTree(child);
  streams.clear();
  if (process.platform !== "darwin") app.quit();
});
