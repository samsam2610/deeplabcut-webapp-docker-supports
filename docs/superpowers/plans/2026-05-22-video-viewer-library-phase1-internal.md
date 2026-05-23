# Video-Viewer Library — Phase 1 (internal pure-logic modules) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the pure, DOM-free logic that the future `VideoViewer` and its feature modules will share into four unit-tested `.mjs` modules under `dlc-3D/src/static/components/viewer/internal/`.

**Architecture:** These are leaf modules with no DOM, no fetch, no globals — just functions over plain values. They are imported later by `video_viewer.js` and the feature modules. Each ships with a Node `node:test` unit-test file mirroring the existing `tests/unit/test_pair_map.mjs` precedent. No consumer (clip-cutter, viewer_3d, inline_analysis_3d) is touched in this phase, so there is zero behavior risk.

**Tech Stack:** Vanilla ES modules (`.mjs`), Node 16 built-in `node:test` runner + `node:assert/strict`.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.1 layout, §3.4 features).

**Source of truth for the ported logic:**
- Palette + shapes: `dlc-3D/src/static/viewer_3d.js:1084-1133`
- Frame pacing / clamp / wrap: `clip-cutter/static/enhanced_player.js:171-229`
- Clip geometry + naming: `clip-cutter/static/enhanced_player.js:60-61,350-352`, `clip-cutter/static/clip_cutter.js:1794`, `clip-cutter/routes.py:1173-1184`

**How to run a unit test (Node 16, explicit file path required):**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/<file>.mjs
```
(`node --test <dir>` does NOT discover `test_*.mjs` names on Node 16 — always pass the file.)

---

## Task 1: `palette.mjs` — HSV→RGB layer colors

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/palette.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_palette.mjs`

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_palette.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { hsvToRgb, paletteColor } from "../../src/static/components/viewer/internal/palette.mjs";

test("hsvToRgb black and pure red", () => {
  assert.equal(hsvToRgb(0, 0, 0), "rgb(0,0,0)");
  assert.equal(hsvToRgb(0, 1, 1), "rgb(255,0,0)");
});

test("hsvToRgb pure green and blue hues", () => {
  // h=1/3 → green sector, h=2/3 → blue sector, full sat/val
  assert.equal(hsvToRgb(1 / 3, 1, 1), "rgb(0,255,0)");
  assert.equal(hsvToRgb(2 / 3, 1, 1), "rgb(0,0,255)");
});

test("paletteColor uses 0.9 sat / 0.95 val and clamps total to >=1", () => {
  // idx 0 → hue 0 → r=v=0.95(242), g=b=v*(1-s)=0.095(24)
  assert.equal(paletteColor(0, 4), "rgb(242,24,24)");
  // total 0 must not divide by zero
  assert.equal(paletteColor(0, 0), "rgb(242,24,24)");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_palette.mjs`
Expected: FAIL — cannot find module `palette.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/palette.mjs` (faithful port of `viewer_3d.js:1084-1098`):

```js
// Pure HSV→RGB palette used for multi-layer overlay marker colors.
// Ported verbatim from the original viewer_3d.js (_vaHsvToRgb / _vaPaletteColor).

export function hsvToRgb(h, s, v) {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  let r, g, b;
  switch (((i % 6) + 6) % 6) {
    case 0: r = v; g = t; b = p; break;
    case 1: r = q; g = v; b = p; break;
    case 2: r = p; g = v; b = t; break;
    case 3: r = p; g = q; b = v; break;
    case 4: r = t; g = p; b = v; break;
    default: r = v; g = p; b = q;
  }
  return `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
}

export function paletteColor(idx, total) {
  return hsvToRgb(idx / Math.max(total, 1), 0.9, 0.95);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_palette.mjs`
Expected: PASS — `# pass 3`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/palette.mjs dlc-3D/tests/unit/test_viewer_palette.mjs
git commit -m "feat(dlc-3d viewer-lib): palette.mjs (hsvToRgb/paletteColor) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `shapes.mjs` — marker shape draw primitives

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/shapes.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_shapes.mjs`

These functions draw onto a Canvas 2D context. Node has no canvas, so the test uses a
recording stub `ctx` that captures method calls and property writes.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_shapes.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  SHAPE_ORDER, SHAPE_FN, drawShape, shapeForLayer,
} from "../../src/static/components/viewer/internal/shapes.mjs";

// Recording stub for a CanvasRenderingContext2D.
function makeCtx() {
  const calls = [];
  const props = {};
  const rec = (name) => (...args) => calls.push({ name, args });
  return {
    calls, props,
    set fillStyle(v) { props.fillStyle = v; },
    set strokeStyle(v) { props.strokeStyle = v; },
    set lineWidth(v) { props.lineWidth = v; },
    beginPath: rec("beginPath"), closePath: rec("closePath"),
    moveTo: rec("moveTo"), lineTo: rec("lineTo"), arc: rec("arc"),
    fill: rec("fill"), stroke: rec("stroke"), strokeRect: rec("strokeRect"),
  };
}
const names = (ctx) => ctx.calls.map((c) => c.name);

test("SHAPE_ORDER and shapeForLayer mapping", () => {
  assert.deepEqual(SHAPE_ORDER, ["circle-filled", "diamond", "square", "triangle"]);
  assert.equal(shapeForLayer(0), "circle-filled");
  assert.equal(shapeForLayer(2), "square");
  assert.equal(shapeForLayer(99), "triangle"); // clamps to last
});

test("circle-filled fills an arc with the color", () => {
  const ctx = makeCtx();
  drawShape("circle-filled", ctx, 10, 20, 5, "rgb(1,2,3)");
  assert.equal(ctx.props.fillStyle, "rgb(1,2,3)");
  assert.deepEqual(ctx.calls.find((c) => c.name === "arc").args, [10, 20, 5, 0, 2 * Math.PI]);
  assert.ok(names(ctx).includes("fill"));
});

test("square strokes a rect; triangle strokes a 3-point path", () => {
  const sq = makeCtx();
  drawShape("square", sq, 10, 20, 5, "red");
  assert.deepEqual(sq.calls.find((c) => c.name === "strokeRect").args, [5, 15, 10, 10]);

  const tri = makeCtx();
  drawShape("triangle", tri, 10, 20, 5, "red");
  assert.equal(names(tri).filter((n) => n === "lineTo").length, 2);
  assert.ok(names(tri).includes("stroke"));
});

test("unknown shape falls back to circle-filled", () => {
  const ctx = makeCtx();
  drawShape("nope", ctx, 0, 0, 1, "x");
  assert.ok(names(ctx).includes("arc"));
  assert.ok(names(ctx).includes("fill"));
});

test("SHAPE_FN has an entry for every SHAPE_ORDER name", () => {
  for (const n of SHAPE_ORDER) assert.equal(typeof SHAPE_FN[n], "function");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_shapes.mjs`
Expected: FAIL — cannot find module `shapes.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/shapes.mjs` (faithful port of `viewer_3d.js:1101-1133`):

```js
// Marker shape draw primitives for multi-layer overlay rendering.
// Ported verbatim from the original viewer_3d.js draw helpers.

export function drawCircleFilled(ctx, x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fill();
}

export function drawDiamond(ctx, x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x + r, y);
  ctx.lineTo(x, y + r);
  ctx.lineTo(x - r, y);
  ctx.closePath();
  ctx.fill();
}

export function drawSquare(ctx, x, y, r, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(x - r, y - r, 2 * r, 2 * r);
}

export function drawTriangle(ctx, x, y, r, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x + r, y + r);
  ctx.lineTo(x - r, y + r);
  ctx.closePath();
  ctx.stroke();
}

export const SHAPE_ORDER = ["circle-filled", "diamond", "square", "triangle"];

export const SHAPE_FN = {
  "circle-filled": drawCircleFilled,
  "diamond": drawDiamond,
  "square": drawSquare,
  "triangle": drawTriangle,
};

export function drawShape(name, ctx, x, y, r, color) {
  (SHAPE_FN[name] || drawCircleFilled)(ctx, x, y, r, color);
}

// Layer index → shape name (clamped to the last shape), matching
// viewer_3d.js _SHAPE_ORDER[Math.min(i, _SHAPE_ORDER.length - 1)].
export function shapeForLayer(i) {
  return SHAPE_ORDER[Math.min(i, SHAPE_ORDER.length - 1)];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_shapes.mjs`
Expected: PASS — `# pass 5`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/shapes.mjs dlc-3D/tests/unit/test_viewer_shapes.mjs
git commit -m "feat(dlc-3d viewer-lib): shapes.mjs (marker draw primitives) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `frame_pacer.mjs` — clamp, next-frame, playback delay

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/frame_pacer.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_frame_pacer.mjs`

Captures the frame-stepping math from `enhanced_player.js:171-229` as pure functions:
clamp into `[lo,hi]`, compute the next frame honoring direction/step/loop, and the
remaining inter-frame delay.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_frame_pacer.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  clampFrame, nextFrame, frameDelayMs, frameRange,
} from "../../src/static/components/viewer/internal/frame_pacer.mjs";

test("clampFrame bounds n into [lo,hi]", () => {
  assert.equal(clampFrame(5, 0, 10), 5);
  assert.equal(clampFrame(-3, 0, 10), 0);
  assert.equal(clampFrame(20, 0, 10), 10);
});

test("nextFrame advances forward by playN*playDir within range", () => {
  assert.deepEqual(nextFrame({ current: 4, playN: 2, playDir: 1, lo: 0, hi: 10, looping: false }),
    { frame: 6, stop: false });
  assert.deepEqual(nextFrame({ current: 6, playN: 1, playDir: -1, lo: 0, hi: 10, looping: false }),
    { frame: 5, stop: false });
});

test("nextFrame wraps when looping, stops when not", () => {
  // forward past hi
  assert.deepEqual(nextFrame({ current: 10, playN: 1, playDir: 1, lo: 2, hi: 10, looping: true }),
    { frame: 2, stop: false });
  assert.deepEqual(nextFrame({ current: 10, playN: 1, playDir: 1, lo: 2, hi: 10, looping: false }),
    { frame: 10, stop: true });
  // backward past lo
  assert.deepEqual(nextFrame({ current: 2, playN: 1, playDir: -1, lo: 2, hi: 10, looping: true }),
    { frame: 10, stop: false });
  assert.deepEqual(nextFrame({ current: 2, playN: 1, playDir: -1, lo: 2, hi: 10, looping: false }),
    { frame: 2, stop: true });
});

test("frameDelayMs subtracts elapsed from the per-frame budget, never negative", () => {
  assert.equal(frameDelayMs(15, 10), Math.round(1000 / 15) - 10); // 67 - 10 = 57
  assert.equal(frameDelayMs(15, 10000), 0);
});

test("frameRange picks full range when unlocked, clip range otherwise", () => {
  assert.deepEqual(frameRange({ frameCount: 100, unlocked: true, clipStart: 10, clipEnd: 20 }),
    { lo: 0, hi: 99 });
  assert.deepEqual(frameRange({ frameCount: 100, unlocked: false, clipStart: 10, clipEnd: 20 }),
    { lo: 10, hi: 20 });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_frame_pacer.mjs`
Expected: FAIL — cannot find module `frame_pacer.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/frame_pacer.mjs`:

```js
// Pure frame-stepping math extracted from enhanced_player.js (_epLoadFrame clamp,
// _epLoop wrap/stop logic). No DOM, no timers — callers own setTimeout/fetch.

export function clampFrame(n, lo, hi) {
  return Math.max(lo, Math.min(n, hi));
}

// Decide the next frame for a playback tick.
// Returns { frame, stop }: stop=true means playback should halt (no-loop boundary).
export function nextFrame({ current, playN, playDir, lo, hi, looping }) {
  const next = current + playN * playDir;
  if (playDir > 0 && next > hi) {
    return looping ? { frame: lo, stop: false } : { frame: current, stop: true };
  }
  if (playDir < 0 && next < lo) {
    return looping ? { frame: hi, stop: false } : { frame: current, stop: true };
  }
  return { frame: next, stop: false };
}

// Remaining delay (ms) for a target fps after a frame took elapsedMs to load.
export function frameDelayMs(fps, elapsedMs) {
  return Math.max(0, Math.round(1000 / fps) - elapsedMs);
}

// The active [lo,hi] frame bounds: full video when unlocked, clip window otherwise.
export function frameRange({ frameCount, unlocked, clipStart, clipEnd }) {
  return unlocked ? { lo: 0, hi: frameCount - 1 } : { lo: clipStart, hi: clipEnd };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_frame_pacer.mjs`
Expected: PASS — `# pass 5`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/frame_pacer.mjs dlc-3D/tests/unit/test_viewer_frame_pacer.mjs
git commit -m "feat(dlc-3d viewer-lib): frame_pacer.mjs (clamp/nextFrame/delay) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `clip_naming.mjs` — clip window + extract filename parse/build

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/clip_naming.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_clip_naming.mjs`

Captures the clip geometry (`enhanced_player.js:60-61` → ±200/+599 window),
the start/length→end math (`enhanced_player.js:352`), and the extract filename
convention `{stem}_{start}_{end}[_{postfix}]` with the postfix sanitizer from
`routes.py:1182` (alphanumeric + `-_`, max 64 chars).

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_clip_naming.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  PRE_WINDOW, POST_WINDOW, clipWindow, computeEnd,
  sanitizePostfix, buildClipStem, parseClipStem,
} from "../../src/static/components/viewer/internal/clip_naming.mjs";

test("clipWindow centers on the keyframe and clamps to [0, frameCount-1]", () => {
  assert.deepEqual(clipWindow(500, 2000), { start: 500 - PRE_WINDOW, end: 500 + POST_WINDOW });
  assert.deepEqual(clipWindow(50, 2000), { start: 0, end: 649 });          // clamp low
  assert.deepEqual(clipWindow(1950, 2000), { start: 1750, end: 1999 });    // clamp high
});

test("computeEnd is 1-based length: start + frames - 1", () => {
  assert.equal(computeEnd(1, 800), 800);
  assert.equal(computeEnd(301, 800), 1100);
});

test("sanitizePostfix keeps [A-Za-z0-9_-] and truncates to 64", () => {
  assert.equal(sanitizePostfix("ab!c d#e"), "abcde"); // drops ! space #
  assert.equal(sanitizePostfix("multi_word-1"), "multi_word-1");
  assert.equal(sanitizePostfix(null), "");
  assert.equal(sanitizePostfix("x".repeat(100)).length, 64);
});

test("buildClipStem appends sanitized postfix only when non-empty", () => {
  assert.equal(buildClipStem("vid", 300, 1099, "good"), "vid_300_1099_good");
  assert.equal(buildClipStem("vid", 300, 1099, ""), "vid_300_1099");
  assert.equal(buildClipStem("vid", 300, 1099, "  "), "vid_300_1099");
});

test("parseClipStem extracts start/end/postfix, null on garbage", () => {
  assert.deepEqual(parseClipStem("vid", "vid_300_1099_good"), { start: 300, end: 1099, postfix: "good" });
  assert.deepEqual(parseClipStem("vid", "vid_300_1099"), { start: 300, end: 1099, postfix: "" });
  assert.deepEqual(parseClipStem("vid", "vid_300_1099_multi_word"), { start: 300, end: 1099, postfix: "multi_word" });
  assert.equal(parseClipStem("vid", "vid_garbage"), null);
});

test("build/parse round-trip", () => {
  const stem = buildClipStem("OM-2_cam0_x", 12, 811, "ok");
  assert.deepEqual(parseClipStem("OM-2_cam0_x", stem), { start: 12, end: 811, postfix: "ok" });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_clip_naming.mjs`
Expected: FAIL — cannot find module `clip_naming.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/clip_naming.mjs`:

```js
// Clip geometry + extract filename convention, mirrored from the clip-cutter
// frontend (enhanced_player.js clip window / end math) and backend
// (routes.py rename_extract: {stem}_{start}_{end}[_postfix], postfix sanitizer).

export const PRE_WINDOW = 200;
export const POST_WINDOW = 599;

// 0-based clip bounds around a 0-based keyframe, clamped to the video.
export function clipWindow(keyFrame0, frameCount, pre = PRE_WINDOW, post = POST_WINDOW) {
  return {
    start: Math.max(0, keyFrame0 - pre),
    end: Math.min(frameCount - 1, keyFrame0 + post),
  };
}

// 1-based length semantics: a clip of `frames` frames starting at `start` ends here.
export function computeEnd(start, frames) {
  return start + frames - 1;
}

// Keep only [A-Za-z0-9_-], cap at 64 chars (matches routes.py:1182).
export function sanitizePostfix(s) {
  return [...(s || "")].filter((c) => /[A-Za-z0-9_-]/.test(c)).join("").slice(0, 64);
}

export function buildClipStem(videoStem, start, end, postfix) {
  let stem = `${videoStem}_${start}_${end}`;
  const safe = sanitizePostfix(postfix);
  if (safe) stem += `_${safe}`;
  return stem;
}

// Parse "{videoStem}_{start}_{end}[_{postfix}]" → { start, end, postfix } or null.
export function parseClipStem(videoStem, stem) {
  const suffix = stem.slice(videoStem.length); // "_start_end[_postfix]"
  const m = suffix.match(/^_(\d+)_(\d+)(?:_(.+))?$/);
  if (!m) return null;
  return { start: parseInt(m[1], 10), end: parseInt(m[2], 10), postfix: m[3] || "" };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_clip_naming.mjs`
Expected: PASS — `# pass 6`, `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/clip_naming.mjs dlc-3D/tests/unit/test_viewer_clip_naming.mjs
git commit -m "feat(dlc-3d viewer-lib): clip_naming.mjs (clip window + filename parse/build) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Phase-1 wrap-up — run the whole unit suite green

**Files:** none (verification only)

- [ ] **Step 1: Run all four new unit-test files together**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs \
  tests/unit/test_viewer_frame_pacer.mjs tests/unit/test_viewer_clip_naming.mjs \
  tests/unit/test_pair_map.mjs
```
Expected: all pass — `# fail 0`. (The existing `test_pair_map.mjs` is included to confirm
no regression in the shared `tests/unit/` directory.)

- [ ] **Step 2: Confirm no consumer files were touched**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~4 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js clip-cutter/`
Expected: empty output — Phase 1 adds only new `internal/*.mjs` + test files; no fork or clip-cutter file changed.

---

## Phase-1 exit criteria

- `dlc-3D/src/static/components/viewer/internal/` contains `palette.mjs`, `shapes.mjs`, `frame_pacer.mjs`, `clip_naming.mjs`.
- Each has a passing `tests/unit/test_viewer_*.mjs`.
- No consumer/origin file modified.
- Four commits landed (one per module).

**Next phase:** Phase 2 (`VideoViewer` base class + hook bus + tile/frame-locked seek) gets its own plan, written once Phase 1 lands. It will import `frame_pacer.mjs` for stepping and expose the `onVideoLoad/onFrameChange/onDrawTile/onTeardown` hook bus the feature modules subscribe to.
