const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { readWindowState, fitWindowBounds, writeWindowState } = require("./window-state");

const MIN = { width: 1100, height: 700 };
const PRIMARY = { x: 0, y: 0, width: 1440, height: 860 };
const SECONDARY = { x: 1440, y: 0, width: 1920, height: 1080 };
const dirs = [];

function tempFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "jobs-window-"));
  dirs.push(dir);
  return path.join(dir, "window-state.json");
}

test.after(() => {
  dirs.forEach((dir) => fs.rmSync(dir, { recursive: true, force: true }));
});

test("writes and reads bounds without leaving a temp file", () => {
  const file = tempFile();
  assert.equal(writeWindowState(file, { x: 120, y: 80, width: 1280, height: 820 }, false), true);
  assert.deepEqual(readWindowState(file), {
    bounds: { x: 120, y: 80, width: 1280, height: 820 },
    maximized: false,
  });
  assert.equal(fs.existsSync(`${file}.tmp`), false);
});

test("only a literal true restores the maximized flag", () => {
  const file = tempFile();
  writeWindowState(file, { x: 0, y: 0, width: 1200, height: 800 }, "yes");
  assert.equal(readWindowState(file).maximized, false);
  writeWindowState(file, { x: 0, y: 0, width: 1200, height: 800 }, true);
  assert.equal(readWindowState(file).maximized, true);
});

test("rounds fractional bounds on the way in and out", () => {
  const file = tempFile();
  writeWindowState(file, { x: 10.4, y: 20.6, width: 1200.5, height: 800.5 }, false);
  assert.deepEqual(readWindowState(file).bounds, { x: 10, y: 21, width: 1201, height: 801 });
});

test("rejects missing, malformed, and unsupported state files", () => {
  assert.equal(readWindowState(tempFile()), null);
  const broken = tempFile();
  fs.writeFileSync(broken, "{not json");
  assert.equal(readWindowState(broken), null);
  const old = tempFile();
  fs.writeFileSync(old, JSON.stringify({ version: 0, bounds: { x: 0, y: 0, width: 1200, height: 800 } }));
  assert.equal(readWindowState(old), null);
  const badBounds = tempFile();
  fs.writeFileSync(badBounds, JSON.stringify({ version: 1, bounds: { x: "12", y: 0, width: 1200, height: 800 } }));
  assert.equal(readWindowState(badBounds), null);
});

test("does not write invalid bounds", () => {
  const file = tempFile();
  assert.equal(writeWindowState(file, { x: NaN, y: 0, width: 1200, height: 800 }, false), false);
  assert.equal(fs.existsSync(file), false);
});

test("keeps bounds that already fit the work area", () => {
  assert.deepEqual(
    fitWindowBounds({ x: 100, y: 40, width: 1200, height: 800 }, [PRIMARY], PRIMARY, MIN),
    { x: 100, y: 40, width: 1200, height: 800 },
  );
});

test("raises undersized windows to the minimum size", () => {
  assert.deepEqual(
    fitWindowBounds({ x: 20, y: 30, width: 900, height: 500 }, [PRIMARY], PRIMARY, MIN),
    { x: 20, y: 30, width: 1100, height: 700 },
  );
});

test("shrinks oversized windows into the work area", () => {
  assert.deepEqual(
    fitWindowBounds({ x: 100, y: 100, width: 2000, height: 1200 }, [PRIMARY], PRIMARY, MIN),
    { x: 0, y: 0, width: 1440, height: 860 },
  );
});

test("keeps a window on the display it mostly occupies", () => {
  assert.deepEqual(
    fitWindowBounds({ x: 1600, y: 100, width: 1200, height: 800 }, [PRIMARY, SECONDARY], PRIMARY, MIN),
    { x: 1600, y: 100, width: 1200, height: 800 },
  );
});

test("follows the larger overlap when a window straddles two displays", () => {
  assert.deepEqual(
    fitWindowBounds({ x: 1200, y: 100, width: 1200, height: 800 }, [PRIMARY, SECONDARY], PRIMARY, MIN),
    { x: 1440, y: 100, width: 1200, height: 800 },
  );
});

test("keeps negative coordinates on a monitor placed to the left", () => {
  const left = { x: -1920, y: 0, width: 1920, height: 1080 };
  assert.deepEqual(
    fitWindowBounds({ x: -1600, y: 100, width: 1200, height: 800 }, [PRIMARY, left], PRIMARY, MIN),
    { x: -1600, y: 100, width: 1200, height: 800 },
  );
});

test("pulls a window back after its display disappears", () => {
  assert.deepEqual(
    fitWindowBounds({ x: 3000, y: 200, width: 1200, height: 800 }, [PRIMARY], PRIMARY, MIN),
    { x: 240, y: 60, width: 1200, height: 800 },
  );
});

test("rejects invalid geometry inputs", () => {
  assert.equal(fitWindowBounds(null, [PRIMARY], PRIMARY, MIN), null);
  assert.equal(fitWindowBounds({ x: 0, y: 0, width: 1200, height: 800 }, [], PRIMARY, MIN), null);
  assert.equal(fitWindowBounds({ x: 0, y: 0, width: 1200, height: 800 }, undefined, PRIMARY, MIN), null);
});
