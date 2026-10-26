"use strict";
const { spawn } = require("child_process");

function directKill(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  try { child.kill(); } catch { /* 已经退出 */ }
}

// Windows 的 child.kill() 只结束直接子进程；采集派生的 crawl / 浏览器进程会变成孤儿继续跑。
function killProcessTree(child) {
  if (!child || !child.pid || child.killed) return false;
  if (process.platform === "win32") {
    const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });
    killer.on("error", () => directKill(child));
    killer.on("close", (code) => {
      if (code !== 0) directKill(child);
    });
    return true;
  }
  try {
    child.kill("SIGTERM");
  } catch {
    return false;
  }
  return true;
}

module.exports = { killProcessTree };
