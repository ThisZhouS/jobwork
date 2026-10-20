"""把 desktop/renderer 静态托管出来，并把 window.api mock 成调真实 CLI。

用途：不等 Electron 下载完，就能在普通浏览器里先看界面、调数据。

用法：
    python tools/serve_renderer.py
然后浏览器打开 http://127.0.0.1:8137/
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / "desktop" / "renderer"
PORT = 8137

MOCK_JS = """
// 浏览器 mock：把 window.api 桥到 /api/*，由 Python 调真实 CLI
window.api = {
  call: async (action, args) => {
    const res = await fetch("/api/call", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action, args: args || {}}),
    });
    return res.json();
  },
  stream: async (action, args, onEvent) => {
    const id = "mock-" + Date.now();
    // 简化：流式也走一次性调用，把进度行逐条喂给 onEvent
    const res = await fetch("/api/stream", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action, args: args || {}}),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        try { onEvent(JSON.parse(line)); } catch (e) {}
      }
    }
    onEvent({type: "__done__", code: 0});
    return id;
  },
  cancel: async () => ({ok: true}),
  openExternal: (url) => window.open(url, "_blank"),
  writeTemp: async (name, content) => {
    const res = await fetch("/api/write-temp", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name, content}),
    });
    return res.json();
  },
};
"""


def _run_cli(argv: list[str]) -> subprocess.Popen:
    # 注意：不能用 dict(**os.environ)，Windows 上存在 "ProgramFiles(x86)"、
    # "=C:" 这类非法标识符名，** 展开会直接抛 TypeError。
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return subprocess.Popen(
        [sys.executable, "-m", "boss_crawler", "app", *argv, "--json"],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静默
        pass

    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8", code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 开发预览：绝不让浏览器缓存，否则改完 JS 看不到效果
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---------------------------------------------------------- 静态
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/__mock_api__.js":
            return self._send(MOCK_JS.encode("utf-8"), "application/javascript; charset=utf-8")
        if path in ("/", "/index.html"):
            html = (RENDERER / "index.html").read_text(encoding="utf-8")
            # 在 app.js 之前注入 mock
            html = html.replace('<script src="app.js"></script>',
                                '<script src="/__mock_api__.js"></script>\n<script src="app.js"></script>')
            return self._send(html.encode("utf-8"))
        target = (RENDERER / path.lstrip("/")).resolve()
        if target.is_file() and RENDERER in target.parents:
            ctype = {"js": "application/javascript", "css": "text/css"}.get(
                target.suffix.lstrip("."), "application/octet-stream")
            return self._send(target.read_bytes(), f"{ctype}; charset=utf-8")
        self._send(b"not found", "text/plain", 404)

    # ---------------------------------------------------------- API
    def do_POST(self):
        # 兜底：任何异常都返回 JSON，而不是把连接掐断（排查时看不到原因）
        try:
            self._handle_post()
        except Exception as exc:  # noqa: BLE001
            payload = {"code": -1, "data": None, "stdout": "",
                       "stderr": f"{type(exc).__name__}: {exc}"}
            try:
                self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except Exception:  # noqa: BLE001
                pass

    def _handle_post(self):
        path = urlparse(self.path).path
        data = self._body()
        if path == "/api/call":
            argv = [data.get("action", "status")]
            for k, v in (data.get("args") or {}).items():
                if v in (None, ""): continue
                flag = "--" + k.replace("_", "-")
                if isinstance(v, bool):
                    if v: argv.append(flag)
                else:
                    argv += [flag, str(v)]
            proc = _run_cli(argv)
            out, err = proc.communicate(timeout=300)
            lines = [l for l in out.splitlines() if l.strip()]
            payload = None
            for line in reversed(lines):
                try:
                    payload = json.loads(line)
                    break
                except Exception:
                    continue
            return self._send(json.dumps(
                {"code": proc.returncode, "data": payload, "stdout": out, "stderr": err}
            ).encode("utf-8"), "application/json; charset=utf-8")

        if path == "/api/stream":
            argv = [data.get("action", "run")]
            for k, v in (data.get("args") or {}).items():
                if v in (None, ""): continue
                flag = "--" + k.replace("_", "-")
                if isinstance(v, bool):
                    if v: argv.append(flag)
                else:
                    argv += [flag, str(v)]
            proc = _run_cli(argv)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.end_headers()
            assert proc.stdout is not None
            for line in proc.stdout:
                try:
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    break
            proc.wait(timeout=10)
            return

        if path == "/api/write-temp":
            tmp = ROOT / ".state" / "tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            file = tmp / data.get("name", "input.json")
            file.write_text(data.get("content", ""), encoding="utf-8")
            return self._send(json.dumps({"ok": True, "path": str(file)}).encode("utf-8"),
                              "application/json; charset=utf-8")

        self._send(b"{}", "application/json", 404)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"渲染层预览：http://127.0.0.1:{PORT}/")
    print("（这是浏览器 mock 版，调的是真实 CLI；Electron 装好后界面一致）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
