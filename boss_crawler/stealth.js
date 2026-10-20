/*
 * boss_crawler — 反检测初始化脚本 (init script)
 *
 * 由 scrapling StealthySession(init_script=...) 在**任何页面脚本之前**注入。
 * scrapling 0.4.x 的 StealthySession 底层是 patchright，已经处理了绝大多数
 * CDP / Runtime.enable / navigator.webdriver 指纹；这里只补两处 BOSS直聘
 * 实际使用的反爬手法：
 *
 *   1) 控制台检测 (console / devtools timing oracle)
 *      站点会周期性 console.table / console.log 大对象，并用「打印耗时」判断
 *      控制台是否被打开、是否挂了 CDP。CDP 已连接时序列化大对象同样很慢，
 *      所以必须把这些调用变成 O(1) 的空操作。
 *
 *   2) 会话页面销毁 (self-destroy)
 *      命中风控后页面会 window.close() 或 location.replace('about:blank')，
 *      表现为空白页 / Target closed。这里把关闭与 about:blank 跳转变成空操作，
 *      crawler 侧另有心跳与重建兜底。
 *
 * 刻意**不**改 navigator/webgl/canvas 等指纹：patchright 已经处理，重复打补丁
 * 反而会制造不一致特征。
 */
(() => {
  'use strict';
  const w = window;

  /* ---------- 1. console probe neutralisation ---------- */
  try {
    const native = {};
    const KEYS = [
      'log', 'info', 'warn', 'error', 'debug', 'trace', 'dir', 'dirxml', 'table',
      'clear', 'group', 'groupCollapsed', 'groupEnd', 'count', 'countReset',
      'assert', 'time', 'timeEnd', 'profile', 'profileEnd', 'timeStamp',
    ];
    for (const k of KEYS) {
      if (typeof console[k] === 'function') native[k] = console[k].bind(console);
    }
    Object.defineProperty(w, '__bc_native_console', {
      value: native, enumerable: false, configurable: false, writable: false,
    });

    const noop = () => {};
    for (const k of [
      'table', 'trace', 'dir', 'dirxml', 'clear', 'group', 'groupCollapsed',
      'groupEnd', 'count', 'countReset', 'assert', 'time', 'timeEnd', 'profile',
      'profileEnd', 'timeStamp',
    ]) {
      try { console[k] = noop; } catch (e) { /* non-writable in some shells */ }
    }

    // 保留 log/info/warn/error，但丢弃大对象，避免 CDP 序列化耗时成为检测信号
    for (const k of ['log', 'info', 'warn', 'error', 'debug']) {
      const orig = native[k];
      if (!orig) continue;
      try {
        console[k] = function (...args) {
          if (args.length > 3) return;
          try { return orig.apply(console, args); } catch (e) { return; }
        };
      } catch (e) { /* ignore */ }
    }
  } catch (e) { /* ignore */ }

  /* ---------- 2. self-destruction guard ---------- */
  try { w.close = function () {}; } catch (e) { /* ignore */ }

  const isBlank = (u) => {
    try { return /^\s*about:blank/i.test(String(u)); } catch (e) { return false; }
  };

  try {
    const proto = Location.prototype;
    const _assign = proto.assign;
    const _replace = proto.replace;
    proto.assign = function (u) { if (isBlank(u)) return; return _assign.call(this, u); };
    proto.replace = function (u) { if (isBlank(u)) return; return _replace.call(this, u); };
  } catch (e) { /* ignore */ }

  try {
    const _open = w.open;
    w.open = function (u, ...rest) {
      if (!u || isBlank(u)) return null;
      return _open.call(w, u, ...rest);
    };
  } catch (e) { /* ignore */ }

  /* ---------- 3. breadcrumbs for the outer watchdog ---------- */
  w.__bc_heartbeat = Date.now();
  w.__bc_alive = true;
  try {
    setInterval(() => { w.__bc_heartbeat = Date.now(); w.__bc_alive = true; }, 1500);
  } catch (e) { /* ignore */ }

  try {
    Object.defineProperty(w, '__bc_stealth__', {
      value: 'v1', enumerable: false, configurable: false,
    });
  } catch (e) { /* ignore */ }
})();
