/* 概览页「模块集群」动画：粒子云 + 阶段巡航。
   动画语言取自 prompt-crawler/index.html，数据来自真实模块清单。 */
"use strict";

window.SwarmMap = (() => {
  const ACCENT = {
    pink: [255, 92, 138],
    cyan: [92, 184, 240],
    teal: [95, 211, 176],
    amber: [240, 192, 96],
    purple: [177, 140, 255],
    orange: [255, 154, 98],
  };
  const GREY = [116, 118, 136];
  const TEAL = ACCENT.teal;
  const PINK = ACCENT.pink;
  const MONO = '"Cascadia Mono","Cascadia Code",Consolas,"Microsoft YaHei",monospace';
  const DISPLAY = '"Bahnschrift","Segoe UI","Microsoft YaHei",sans-serif';
  const BA = [0.3, 0.52, 0.82];

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const mix = (a, b, t) => [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ];
  const rgba = (c, a) => `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${a})`;

  function rng(seed) {
    let s = seed >>> 0;
    return () => {
      s = (s * 1664525 + 1013904223) >>> 0;
      return s / 4294967296;
    };
  }
  function gauss(r) {
    let u = 0;
    let v = 0;
    while (!u) u = r();
    while (!v) v = r();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  function makeCloud(cx, cy, n, seed, scale) {
    const r = rng(seed);
    const lobes = [];
    const k = 4 + Math.floor(r() * 2);
    for (let i = 0; i < k; i++) {
      lobes.push({
        x: cx + gauss(r) * 36 * scale,
        y: cy + gauss(r) * 17 * scale,
        sx: (20 + r() * 22) * scale,
        sy: (12 + r() * 14) * scale,
        w: 0.5 + r(),
      });
    }
    const wsum = lobes.reduce((sum, l) => sum + l.w, 0);
    const buckets = [[], [], []];
    const tw = [];
    for (let i = 0; i < n; i++) {
      let pick = r() * wsum;
      let lobe = lobes[0];
      for (const item of lobes) {
        pick -= item.w;
        if (pick <= 0) { lobe = item; break; }
      }
      const p = {
        x: lobe.x + gauss(r) * lobe.sx,
        y: lobe.y + gauss(r) * lobe.sy,
        s: r() < 0.08 ? 2.1 : 0.9 + r() * 1.1,
        ph: r() * 6.283,
        f: 0.6 + r() * 1.5,
      };
      if (r() < 0.07) tw.push(p);
      else buckets[r() < 0.55 ? 0 : r() < 0.7 ? 1 : 2].push(p);
    }
    return { buckets, tw };
  }

  function create(canvas, stages) {
    const ctx = canvas.getContext("2d");
    const ac = new AbortController();
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reduce = mq.matches;
    let disposed = false;
    let raf = 0;
    let visible = true;
    let last = 0;
    let now = 0;
    let world = null;
    let hover = -1;
    const textCache = new Map();

    const state = {
      idx: 0,
      mode: "travel",
      t: 0,
      readAt: 0,
      readCount: 0,
      linkT: -10,
      pulses: [],
      crawler: { x: 0, y: 0, vx: 0, vy: 0, ang: -Math.PI / 2 },
    };

    function measure(c, font, text) {
      const key = font + "|" + text;
      let width = textCache.get(key);
      if (width === undefined) {
        c.font = font;
        width = c.measureText(text).width;
        textCache.set(key, width);
      }
      return width;
    }

    function build() {
      const W = Math.max(1, canvas.clientWidth);
      const H = Math.max(1, canvas.clientHeight);
      const pad = clamp(W * 0.072, 42, 96);
      const baseY = H - 66;
      const nodeY = baseY - 46;
      const spacing = stages.length > 1 ? (W - pad * 2) / (stages.length - 1) : 0;
      const scale = clamp(W / 1250, 0.7, 1.05);
      const cloudN = Math.round(clamp(W / 8.5, 70, 200));
      const nodes = stages.map((stage, i) => {
        const accent = ACCENT[stage.accent] || GREY;
        const x = stages.length > 1 ? pad + i * spacing : W / 2;
        const count = Math.max(1, Math.min(8, stage.modules.length || 1));
        const spread = Math.min(Math.PI * 1.5, 0.7 + count * 0.26);
        const points = Array.from({ length: count }, (_, k) => {
          const ratio = count === 1 ? 0 : k / (count - 1) - 0.5;
          const angle = -Math.PI / 2 + ratio * spread;
          const rad = (31 + (k % 3) * 12) * scale;
          return {
            x: x + Math.cos(angle) * rad,
            y: nodeY + Math.sin(angle) * rad * 0.9,
            module: stage.modules[k] || { name: "module", enabled: true },
            readT: -1,
          };
        });
        return { stage, accent, x, points, cloud: makeCloud(x, nodeY, cloudN, 2711 + i * 7919, scale), heat: 0.34 };
      });
      const r = rng(4242);
      const dust = Array.from({ length: Math.round(clamp(W / 2.2, 110, 360)) }, () => ({
        x: r() * W,
        y: r() * H,
        s: 0.6 + r() * 0.8,
        a: 0.1 + r() * 0.3,
      }));
      world = { W, H, pad, baseY, nodeY, spacing, scale, nodes, dust };
      if (state.idx >= nodes.length) state.idx = 0;
      state.crawler.x = nodes[state.idx].x;
      state.crawler.y = nodeY - 6;
      state.crawler.vx = 0;
      state.crawler.vy = 0;
      state.mode = "travel";
      state.t = 0;
      state.readCount = 0;
      nodes.forEach((n) => n.points.forEach((p) => { p.readT = -1; }));
    }

    function size() {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(1, Math.round(rect.width));
      const h = Math.max(1, Math.round(rect.height));
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      build();
      if (reduce) drawStatic();
      else draw();
    }

    function update(dt) {
      if (!world) return;
      const w = world;
      const node = w.nodes[state.idx];
      const cr = state.crawler;
      const tx = node.x;
      const ty = w.nodeY - 6;
      const K = 46;
      const C = 2 * Math.sqrt(K);
      const sdt = Math.min(dt, 0.033);
      cr.vx += (K * (tx - cr.x) - C * cr.vx) * sdt;
      cr.vy += (K * (ty - cr.y) - C * cr.vy) * sdt;
      cr.x += cr.vx * sdt;
      cr.y += cr.vy * sdt;
      const speed = Math.hypot(cr.vx, cr.vy);
      if (speed > 14) {
        const target = Math.atan2(cr.vy, cr.vx) + Math.PI / 2;
        let d = target - cr.ang;
        while (d > Math.PI) d -= Math.PI * 2;
        while (d < -Math.PI) d += Math.PI * 2;
        cr.ang += d * (1 - Math.exp(-dt * 5));
      }

      state.t += dt;
      if (state.mode === "travel") {
        if ((Math.abs(tx - cr.x) < 7 && Math.abs(ty - cr.y) < 12) || state.t > 1.9) {
          state.mode = "read";
          state.t = 0;
          state.readAt = 0;
          state.readCount = 0;
          state.linkT = now;
          node.points.forEach((p) => { p.readT = -1; });
        }
      } else {
        state.readAt += dt;
        if (state.readCount < node.points.length && state.readAt > 0.34) {
          state.readAt = 0;
          const point = node.points[state.readCount++];
          point.readT = now;
          state.pulses.push({ x: point.x, y: point.y, t: now, c: node.accent });
        }
        if (state.readCount >= node.points.length && state.t > node.points.length * 0.34 + 1.05) {
          state.idx = (state.idx + 1) % w.nodes.length;
          state.mode = "travel";
          state.t = 0;
        }
      }

      state.pulses = state.pulses.filter((p) => now - p.t < 0.75);
      w.nodes.forEach((n, i) => {
        const tgt = i === state.idx ? (state.mode === "read" ? 1 : 0.74) : 0.34;
        n.heat += (tgt - n.heat) * (1 - Math.exp(-dt * 3.5));
      });
    }

    function drawCloud(c, node) {
      const h = node.heat;
      const col = mix(GREY, node.accent, 0.52 + h * 0.48);
      const am = 0.58 + 0.42 * h;
      for (let b = 0; b < 3; b++) {
        c.fillStyle = rgba(col, BA[b] * am);
        for (const p of node.cloud.buckets[b]) {
          c.fillRect(p.x - p.s / 2, p.y - p.s / 2, p.s, p.s);
        }
      }
      c.fillStyle = rgba(mix(col, [255, 255, 255], 0.45), 1);
      for (const p of node.cloud.tw) {
        c.globalAlpha = am * (0.2 + 0.8 * (0.5 + 0.5 * Math.sin(now * p.f * 1.7 + p.ph)));
        c.fillRect(p.x - 0.7, p.y - 0.7, 1.4, 1.4);
      }
      c.globalAlpha = 1;
    }

    function drawLeg(c, point, bx, by, bs, fresh) {
      const dx = point.x - bx;
      const dy = point.y - by;
      const len = Math.hypot(dx, dy);
      if (len < 4) return;
      const ux = dx / len;
      const uy = dy / len;
      const sx = bx + ux * 14 * bs;
      const sy = by + uy * 18 * bs;
      const bend = len * 0.16;
      const mx = (sx + point.x) / 2 - uy * bend;
      const my = (sy + point.y) / 2 + ux * bend;
      const reach = point.readT < 0 ? 0 : Math.min(1, (now - point.readT) * 3.2 + 0.2);
      const n = Math.max(5, Math.floor(len / 5));
      const upto = Math.floor(n * reach);
      c.fillStyle = fresh ? "rgba(255,92,138,0.92)" : "rgba(195,240,228,0.5)";
      for (let k = 0; k <= upto; k++) {
        const t = k / n;
        const it = 1 - t;
        c.fillRect(
          it * it * sx + 2 * it * t * mx + t * t * point.x - 0.8,
          it * it * sy + 2 * it * t * my + t * t * point.y - 0.8,
          1.6, 1.6,
        );
      }
      if (reach >= 1) {
        c.beginPath();
        c.arc(point.x, point.y, fresh ? 2.4 : 1.4, 0, 6.283);
        c.fill();
      }
    }

    function drawCrawler(c) {
      const w = world;
      const node = w.nodes[state.idx];
      const cr = state.crawler;
      const bs = w.scale;
      const rx = 15 * bs;
      const ry = 20 * bs;

      c.globalCompositeOperation = "lighter";
      node.points.forEach((p, i) => {
        if (p.readT < 0) return;
        drawLeg(c, p, cr.x, cr.y, bs, state.mode === "read" && i === state.readCount - 1);
      });

      c.strokeStyle = "rgba(170,240,225,0.36)";
      c.lineWidth = 1;
      c.beginPath();
      const tentacles = 18;
      for (let i = 0; i < tentacles; i++) {
        const a = (i / tentacles) * 6.283 + Math.sin(now * 1.2 + i) * 0.1 + cr.ang;
        const ex = Math.cos(a);
        const ey = Math.sin(a);
        const x0 = cr.x + ex * rx;
        const y0 = cr.y + ey * ry;
        const len = (9 + 10 * (0.5 + 0.5 * Math.sin(now * 2 + i * 1.7))) * bs;
        c.moveTo(x0, y0);
        c.lineTo(x0 + ex * len + Math.sin(now * 3 + i) * 2, y0 + ey * len + Math.cos(now * 2.6 + i) * 2);
      }
      c.stroke();

      c.save();
      c.translate(cr.x, cr.y);
      c.rotate(cr.ang);
      const halo = c.createRadialGradient(0, 0, 0, 0, 0, ry * 2.7);
      halo.addColorStop(0, "rgba(95,211,176,0.22)");
      halo.addColorStop(1, "rgba(95,211,176,0)");
      c.fillStyle = halo;
      c.beginPath();
      c.arc(0, 0, ry * 2.7, 0, 6.283);
      c.fill();
      c.globalCompositeOperation = "source-over";
      c.fillStyle = "rgba(6,26,28,0.94)";
      c.beginPath();
      c.ellipse(0, 0, rx, ry, 0, 0, 6.283);
      c.fill();
      c.globalCompositeOperation = "lighter";
      c.strokeStyle = "rgba(95,211,176,0.95)";
      c.lineWidth = 1.4;
      c.stroke();
      c.lineWidth = 0.8;
      c.strokeStyle = "rgba(95,211,176,0.3)";
      for (const k of [0.35, 0.7]) {
        c.beginPath();
        c.ellipse(0, 0, rx * k, ry, 0, 0, 6.283);
        c.stroke();
        c.beginPath();
        c.ellipse(0, 0, rx, ry * k, 0, 0, 6.283);
        c.stroke();
      }
      const pulse = state.mode === "read" ? 0.5 + 0.5 * Math.sin(now * 6) : 0;
      const cr0 = (4.2 + pulse * 2) * bs;
      const core = c.createRadialGradient(0, 0, 0, 0, 0, cr0 * 3);
      core.addColorStop(0, "rgba(255,92,138,0.9)");
      core.addColorStop(1, "rgba(255,92,138,0)");
      c.fillStyle = core;
      c.beginPath();
      c.arc(0, 0, cr0 * 3, 0, 6.283);
      c.fill();
      c.fillStyle = "#ff7aa0";
      c.beginPath();
      c.arc(0, 0, cr0, 0, 6.283);
      c.fill();
      c.restore();
      c.globalCompositeOperation = "source-over";
    }

    function drawTags(c, node) {
      const active = state.mode === "read" ? node.points.filter((p) => p.readT >= 0) : [];
      if (!active.length) return;
      const w = world;
      const small = w.W < 720;
      const max = small ? 3 : 4;
      const font = `${small ? 8 : 9}px ${MONO}`;
      const th = small ? 12 : 14;
      c.font = font;
      c.textAlign = "left";
      c.textBaseline = "middle";

      const ordered = active.slice().sort((a, b) => {
        const ea = a.module.enabled !== false ? 0 : 1;
        const eb = b.module.enabled !== false ? 0 : 1;
        return ea - eb;
      }).slice(0, max);
      const sorted = ordered.slice().sort((a, b) => a.x - b.x);
      const half = Math.ceil(sorted.length / 2);
      const groups = [
        { points: sorted.slice(0, half).slice(0, 2), side: -1 },
        { points: sorted.slice(half).slice(0, 2), side: 1 },
      ];
      const topY = Math.max(30, w.nodeY - 92);
      const bottomY = Math.max(topY + th + 8, w.nodeY - 56);

      groups.forEach((group) => {
        group.points.forEach((p, index) => {
          const label = String(p.module.name || p.module.label || "module");
          const enabled = p.module.enabled !== false;
          const text = enabled ? label : label + " · off";
          const tw = measure(c, font, text) + 14;
          if (tw > w.W * 0.38) return;
          let x = group.side < 0 ? node.x - 62 - tw : node.x + 62;
          if (x < 4 || x + tw > w.W - 4) x = group.side < 0 ? node.x + 62 : node.x - 62 - tw;
          if (x < 4 || x + tw > w.W - 4) return;
          const y = group.points.length > 1 && index === 1 ? bottomY : topY;
          if (y + th > w.H - 46) return;

          const age = now - p.readT;
          c.globalAlpha = clamp(age * 4 + 0.2, 0, 1);
          const edgeX = group.side < 0 ? x + tw : x;
          c.strokeStyle = rgba(enabled ? node.accent : GREY, 0.46);
          c.lineWidth = 1;
          c.beginPath();
          c.moveTo(p.x, p.y);
          c.lineTo(edgeX, y + th / 2);
          c.stroke();
          c.fillStyle = "rgba(6,6,10,0.92)";
          c.fillRect(x, y, tw, th);
          c.strokeStyle = rgba(enabled ? node.accent : GREY, 0.55);
          c.strokeRect(x + 0.5, y + 0.5, tw - 1, th - 1);
          c.fillStyle = rgba(enabled ? mix(node.accent, [255, 255, 255], 0.4) : GREY, 1);
          c.fillRect(x + 5, y + th / 2 - 1.5, 3, 3);
          c.fillStyle = enabled ? "rgba(222,221,232,0.92)" : "rgba(138,138,158,0.8)";
          c.fillText(text, x + 11, y + th / 2 + 0.5);
          c.globalAlpha = 1;
        });
      });
    }

    function draw() {
      if (!world) return;
      const c = ctx;
      const w = world;
      c.clearRect(0, 0, w.W, w.H);

      // 氛围光 + 背景尘
      c.globalCompositeOperation = "lighter";
      w.nodes.forEach((node) => {
        const gr = 168 * w.scale;
        const g = c.createRadialGradient(node.x, w.nodeY, 0, node.x, w.nodeY, gr);
        g.addColorStop(0, rgba(node.accent, 0.045 + 0.15 * node.heat));
        g.addColorStop(0.55, rgba(node.accent, 0.014 + 0.05 * node.heat));
        g.addColorStop(1, rgba(node.accent, 0));
        c.fillStyle = g;
        c.fillRect(node.x - gr, w.nodeY - gr, gr * 2, gr * 2);
      });
      for (const p of w.dust) {
        c.fillStyle = `rgba(126,128,148,${p.a})`;
        c.fillRect(p.x, p.y, p.s, p.s);
      }

      // 主链路：基线 + 流动数据点
      c.strokeStyle = "rgba(255,255,255,0.08)";
      c.lineWidth = 1;
      c.beginPath();
      c.moveTo(w.nodes[0].x, w.baseY);
      c.lineTo(w.nodes[w.nodes.length - 1].x, w.baseY);
      c.stroke();
      c.setLineDash([2, 5]);
      c.lineDashOffset = -now * 18;
      c.strokeStyle = "rgba(140,144,170,0.16)";
      c.beginPath();
      c.moveTo(w.nodes[0].x, w.baseY);
      c.lineTo(w.nodes[w.nodes.length - 1].x, w.baseY);
      c.stroke();
      c.setLineDash([]);
      const packets = 14;
      for (let k = 0; k < packets; k++) {
        const u = (now * 0.055 + k / packets) % 1;
        const x = w.nodes[0].x + u * (w.nodes[w.nodes.length - 1].x - w.nodes[0].x);
        const seg = Math.min(w.nodes.length - 2, Math.floor(u * (w.nodes.length - 1)));
        const col = w.nodes[seg].accent;
        c.fillStyle = rgba(col, 0.35 + 0.5 * Math.sin(u * Math.PI));
        c.fillRect(x - 1, w.baseY - 1, 2, 2);
      }

      // 颗粒云
      w.nodes.forEach((node) => drawCloud(c, node));

      // 阶段切换的新鲜连线
      if (state.mode === "read" && state.idx > 0 && now - state.linkT < 1.8) {
        const a = w.nodes[state.idx - 1].x;
        const b = w.nodes[state.idx].x;
        const fresh = 1 - (now - state.linkT) / 1.8;
        c.strokeStyle = rgba(mix([200, 205, 220], PINK, fresh), 0.15 + 0.55 * fresh);
        c.lineWidth = 1;
        c.beginPath();
        c.moveTo(a, w.baseY);
        c.lineTo(b, w.baseY);
        c.stroke();
      }

      // 模块读取点
      w.nodes.forEach((node) => {
        node.points.forEach((p) => {
          if (p.readT < 0) {
            c.fillStyle = rgba(node.accent, 0.22);
            c.fillRect(p.x - 1, p.y - 1, 2, 2);
            return;
          }
          c.fillStyle = rgba(p.module.enabled !== false ? node.accent : GREY, 0.95);
          c.fillRect(p.x - 1.4, p.y - 1.4, 2.8, 2.8);
        });
      });

      // 读取脉冲
      for (const p of state.pulses) {
        const k = (now - p.t) / 0.75;
        c.strokeStyle = rgba(p.c, 0.7 * (1 - k));
        c.beginPath();
        c.arc(p.x, p.y, 2 + k * 18, 0, 6.283);
        c.stroke();
      }

      drawCrawler(c);

      // 阶段节点
      c.globalCompositeOperation = "lighter";
      w.nodes.forEach((node, i) => {
        const act = i === state.idx;
        const pulse = act && state.mode === "read" ? 0.5 + 0.5 * Math.sin(now * 5) : 0;
        c.fillStyle = rgba(node.accent, act ? 0.95 : 0.4);
        c.fillRect(node.x - 2, w.baseY - 2, 4, 4);
        c.strokeStyle = rgba(node.accent, act ? 0.5 + 0.3 * pulse : 0.18);
        c.beginPath();
        c.arc(node.x, w.baseY, act ? 7 + pulse * 3 : 4, 0, 6.283);
        c.stroke();
      });
      c.globalCompositeOperation = "source-over";

      drawTags(c, w.nodes[state.idx]);

      // 阶段标签
      w.nodes.forEach((node, i) => {
        const act = i === state.idx;
        const enabled = node.stage.modules.filter((m) => m.enabled !== false).length;
        const total = node.stage.modules.length;
        c.textAlign = "center";
        c.textBaseline = "alphabetic";
        c.font = act ? `600 11px ${DISPLAY}` : `11px ${DISPLAY}`;
        c.fillStyle = act ? rgba(node.accent, 1) : "rgba(222,221,232,0.86)";
        c.fillText(`${node.stage.no} ${node.stage.name}`, node.x, w.baseY + 24);
        c.font = `8px ${MONO}`;
        c.fillStyle = act ? "rgba(200,202,220,0.82)" : "rgba(148,148,168,0.76)";
        const meta = w.W < 640 ? `${enabled}/${total}` : `${node.stage.en} · ${enabled}/${total}`;
        c.fillText(meta, node.x, w.baseY + 36);
      });

      // 顶部读数
      const node = w.nodes[state.idx];
      c.textAlign = "left";
      c.font = `8px ${MONO}`;
      c.fillStyle = "rgba(138,138,158,0.68)";
      const head = "// SWARM MAP · LIVE";
      c.fillText(head, 18, 18);
      if (!reduce && (now % 1) < 0.55) {
        c.fillStyle = rgba(PINK, 0.9);
        c.fillRect(18 + c.measureText(head).width + 5, 12, 4, 7);
      }
      if (w.W >= 720) {
        const enabled = w.nodes.reduce((sum, n) => sum + n.stage.modules.filter((m) => m.enabled !== false).length, 0);
        const total = w.nodes.reduce((sum, n) => sum + n.stage.modules.length, 0);
        const status = state.mode === "read"
          ? `SCANNING ${node.stage.no} ${node.stage.name} · ${state.readCount}/${node.points.length}`
          : `ROUTING → ${node.stage.no} ${node.stage.name}`;
        c.textAlign = "right";
        c.fillStyle = "rgba(138,138,158,0.62)";
        c.fillText(`${status}   ${enabled}/${total} MODULES`, w.W - 18, 18);
      }
    }

    function drawStatic() {
      if (!world) return;
      now = 3.2;
      state.mode = "read";
      state.idx = Math.min(2, world.nodes.length - 1);
      state.readCount = world.nodes[state.idx].points.length;
      world.nodes.forEach((n, i) => { n.heat = i === state.idx ? 1 : 0.62; });
      world.nodes[state.idx].points.forEach((p) => { p.readT = 0; });
      const node = world.nodes[state.idx];
      state.crawler.x = node.x;
      state.crawler.y = world.nodeY - 6;
      state.crawler.vx = 0;
      state.crawler.vy = 0;
      state.linkT = -10;
      state.pulses = [];
      draw();
    }

    function frame(t) {
      if (disposed || reduce) return;
      raf = requestAnimationFrame(frame);
      if (!visible || document.hidden) { last = t; return; }
      const dt = clamp((t - last) / 1000, 0, 0.05);
      last = t;
      now = t / 1000;
      update(dt);
      draw();
    }

    function start() {
      size();
      if (reduce) return;
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }

    function onMotionChange() {
      reduce = mq.matches;
      cancelAnimationFrame(raf);
      if (reduce) {
        drawStatic();
      } else {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    }

    canvas.addEventListener("pointermove", (event) => {
      if (!world) return;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      let found = -1;
      if (y > 28 && y < world.H - 6) {
        const reach = world.spacing ? world.spacing * 0.5 : world.W;
        found = world.nodes.findIndex((n) => Math.abs(n.x - x) < reach);
      }
      if (found !== hover) {
        hover = found;
        canvas.style.cursor = found >= 0 && stages[found].href ? "pointer" : "default";
      }
    }, { signal: ac.signal });

    canvas.addEventListener("pointerleave", () => {
      hover = -1;
      canvas.style.cursor = "default";
    }, { signal: ac.signal });

    canvas.addEventListener("click", () => {
      if (hover >= 0 && stages[hover].href) location.hash = stages[hover].href;
    }, { signal: ac.signal });

    const ro = new ResizeObserver(() => size());
    ro.observe(canvas);

    let io = null;
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver((entries) => {
        visible = entries[0].isIntersecting;
        if (visible) last = performance.now();
      }, { threshold: 0 });
      io.observe(canvas);
    }

    if (typeof mq.addEventListener === "function") mq.addEventListener("change", onMotionChange);

    return {
      start,
      destroy() {
        disposed = true;
        cancelAnimationFrame(raf);
        ro.disconnect();
        if (io) io.disconnect();
        ac.abort();
        if (typeof mq.removeEventListener === "function") mq.removeEventListener("change", onMotionChange);
      },
    };
  }

  let current = null;

  function mount(canvas, stages) {
    stop();
    if (!canvas || !Array.isArray(stages) || !stages.length) return;
    current = create(canvas, stages);
    current.start();
  }

  function stop() {
    if (current) {
      current.destroy();
      current = null;
    }
  }

  return { mount, stop };
})();
