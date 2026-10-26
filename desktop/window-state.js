const fs = require("fs");
const path = require("path");

const VERSION = 1;

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

function validBounds(bounds) {
  return !!bounds && ["x", "y", "width", "height"].every((key) => Number.isFinite(bounds[key]));
}

function overlapArea(bounds, area) {
  const width = Math.max(0, Math.min(bounds.x + bounds.width, area.x + area.width) - Math.max(bounds.x, area.x));
  const height = Math.max(0, Math.min(bounds.y + bounds.height, area.y + area.height) - Math.max(bounds.y, area.y));
  return width * height;
}

function readWindowState(file) {
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8"));
    if (raw?.version !== VERSION || !validBounds(raw.bounds)) return null;
    return {
      bounds: {
        x: Math.round(raw.bounds.x),
        y: Math.round(raw.bounds.y),
        width: Math.round(raw.bounds.width),
        height: Math.round(raw.bounds.height),
      },
      maximized: raw.maximized === true,
    };
  } catch {
    return null;
  }
}

// 屏幕被拔掉或分辨率变小后，把窗口夹回可见工作区；跨屏窗口优先跟随重叠面积最大的屏。
function fitWindowBounds(bounds, areas, fallbackArea, minSize) {
  if (!validBounds(bounds) || !Array.isArray(areas) || !areas.length) return null;
  const primary = fallbackArea || areas[0];
  let area = primary;
  let best = overlapArea(bounds, primary);
  areas.forEach((candidate) => {
    const score = overlapArea(bounds, candidate);
    if (score > best) {
      best = score;
      area = candidate;
    }
  });
  const width = Math.round(clamp(bounds.width, minSize.width, Math.max(minSize.width, area.width)));
  const height = Math.round(clamp(bounds.height, minSize.height, Math.max(minSize.height, area.height)));
  return {
    x: Math.round(clamp(bounds.x, area.x, area.x + Math.max(0, area.width - width))),
    y: Math.round(clamp(bounds.y, area.y, area.y + Math.max(0, area.height - height))),
    width,
    height,
  };
}

function writeWindowState(file, bounds, maximized) {
  if (!validBounds(bounds)) return false;
  const temp = `${file}.tmp`;
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(temp, JSON.stringify({
      version: VERSION,
      bounds: {
        x: Math.round(bounds.x),
        y: Math.round(bounds.y),
        width: Math.round(bounds.width),
        height: Math.round(bounds.height),
      },
      maximized: maximized === true,
    }, null, 2));
    fs.renameSync(temp, file);
    return true;
  } catch {
    try { fs.rmSync(temp, { force: true }); } catch { /* 保留原状态文件 */ }
    return false;
  }
}

module.exports = { readWindowState, fitWindowBounds, writeWindowState };
