// 主进程：窗口 + 调 Python CLI + IPC 桥。
// 所有与后端的交互都集中在这里，渲染进程只发动作名和参数。
const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

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
const streams = new Map(); // streamId -> child process

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: "#0b1220",
    title: "求职背调工作台",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.on("closed", () => { win = null; });
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
ipcMain.handle("app:call", async (_e, action, args) => {
  const argv = [action];
  for (const [k, v] of Object.entries(args || {})) {
    if (v === undefined || v === null || v === "") continue;
    if (typeof v === "boolean") { if (v) argv.push(`--${k.replace(/_/g, "-")}`); }
    else argv.push(`--${k.replace(/_/g, "-")}`, String(v));
  }
  return runOnce(argv);
});

ipcMain.handle("app:stream:start", (event, streamId, action, args) => {
  const argv = [action];
  for (const [k, v] of Object.entries(args || {})) {
    if (v === undefined || v === null || v === "") continue;
    if (typeof v === "boolean") { if (v) argv.push(`--${k.replace(/_/g, "-")}`); }
    else argv.push(`--${k.replace(/_/g, "-")}`, String(v));
  }
  runStream(streamId, argv, event);
  return { ok: true };
});

ipcMain.handle("app:stream:cancel", (_e, streamId) => {
  const child = streams.get(streamId);
  if (child) { child.kill(); streams.delete(streamId); }
  return { ok: true };
});

ipcMain.handle("app:open-external", (_e, url) => {
  if (/^https?:\/\//.test(url)) shell.openExternal(url);
  return { ok: true };
});

// 把渲染进程要传的 JSON 写到临时文件，避免命令行长度/转义问题
ipcMain.handle("app:write-temp", (_e, name, content) => {
  const dir = path.join(STATE_ROOT, "tmp");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, name);
  fs.writeFileSync(file, content, "utf8");
  return { ok: true, path: file };
});

// ---------------------------------------------------------------- 生命周期
app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  for (const child of streams.values()) child.kill();
  streams.clear();
  if (process.platform !== "darwin") app.quit();
});
