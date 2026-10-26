const test = require("node:test");
const assert = require("node:assert/strict");
const { spawn } = require("child_process");
const { killProcessTree } = require("./process-tree");

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitDead(pid, timeout = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (!alive(pid)) return true;
    await sleep(80);
  }
  return false;
}

test("kills a parent together with its grandchild", { skip: process.platform !== "win32" }, async () => {
  // 父进程再拉一个孙进程，模拟 app run → crawl 的进程树。
  const script = `
    const { spawn } = require("child_process");
    const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" });
    console.log(child.pid);
    setInterval(() => {}, 1000);
  `;
  const parent = spawn(process.execPath, ["-e", script], { stdio: ["ignore", "pipe", "ignore"] });
  let buffer = "";
  parent.stdout.on("data", (data) => { buffer += data.toString(); });
  const started = Date.now();
  while (!buffer.trim() && Date.now() - started < 5000) await sleep(50);
  const grandchild = Number(buffer.trim());
  assert.ok(parent.pid > 0 && grandchild > 0, "process tree should start");
  assert.equal(alive(grandchild), true);

  assert.equal(killProcessTree(parent), true);
  assert.equal(await waitDead(grandchild), true, "grandchild should be terminated");
  assert.equal(await waitDead(parent.pid), true, "parent should be terminated");
});

test("ignores missing or already killed children", () => {
  assert.equal(killProcessTree(null), false);
  assert.equal(killProcessTree({ pid: 0, killed: false }), false);
  assert.equal(killProcessTree({ pid: 1234, killed: true }), false);
});
