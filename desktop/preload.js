// 预加载：只暴露最小接口，渲染进程拿不到 Node 能力。
const { contextBridge, ipcRenderer } = require("electron");

let streamSeq = 0;
const listeners = new Map();

contextBridge.exposeInMainWorld("api", {
  // 一次性命令：window.api.call("data") -> {code, data, stdout, stderr}
  call: (action, args) => ipcRenderer.invoke("app:call", action, args),

  // 流式命令：const id = await window.api.stream("run", {...}, (event) => {...})
  stream: (action, args, onEvent) => {
    const streamId = `s${Date.now()}-${streamSeq++}`;
    const handler = (_e, id, event) => { if (id === streamId) onEvent(event); };
    const doneHandler = (_e, id, code, err) => {
      if (id !== streamId) return;
      cleanup();
      onEvent({ type: "__done__", code, error: err });
    };
    const stderrHandler = (_e, id, text) => { if (id === streamId) onEvent({ type: "__stderr__", text }); };
    function cleanup() {
      ipcRenderer.removeListener("app:stream:event", handler);
      ipcRenderer.removeListener("app:stream:done", doneHandler);
      ipcRenderer.removeListener("app:stream:stderr", stderrHandler);
      listeners.delete(streamId);
    }
    ipcRenderer.on("app:stream:event", handler);
    ipcRenderer.on("app:stream:done", doneHandler);
    ipcRenderer.on("app:stream:stderr", stderrHandler);
    listeners.set(streamId, cleanup);
    ipcRenderer.invoke("app:stream:start", streamId, action, args);
    return streamId;
  },

  cancel: (streamId) => {
    const cleanup = listeners.get(streamId);
    if (cleanup) cleanup();
    return ipcRenderer.invoke("app:stream:cancel", streamId);
  },

  openExternal: (url) => ipcRenderer.invoke("app:open-external", url),
  writeTemp: (name, content) => ipcRenderer.invoke("app:write-temp", name, content),
});
