# Video-Viewer Library — Phase 3d-i (marker_overlay reducer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the pure overlay/edit logic the `MarkerEditor` feature is built from — scale + coordinate transforms, hit-testing, pose↔edit merging, prefetch-window math, layer threshold/cache-key, WASD nudge, tab cycling, and the save-marker payload — into one node-testable `internal/marker_overlay.mjs`.

**Architecture:** MarkerEditor is the largest feature (overlay + multi-layer poses + marker editing), so it splits like the base class: this phase (3d-i) builds the pure reducer; the next phase (3d-ii) builds the DOM `features/marker_editor.js` that fetches poses, renders to a canvas (reusing the existing `palette.mjs` + `shapes.mjs`), and wires mouse/keyboard editing — calling into this reducer for all the math. No DOM/fetch here.

**Tech Stack:** Vanilla ES modules; `node:test` + `node:assert/strict`.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.4 MarkerEditor).

**Source of truth (current fork, `viewer_3d.js`):** scale `sx=canvasW/naturalW` (842-848), `markerRadius = max(1, round(markerSize*min(sx,sy)))` (848), hit-test (1240-1253) pad 6 / hit-test-with-edits (1335-1353) pad 8, canvasToVideo (1326-1332), pose-edit merge in `_vaDrawPoseMarkers` (1163-1194; deleted = `x==null||y==null` → not drawn), local edits `Map<frame,{bp:{x,y}}>` (1259), WASD nudge ±1/±10 (2587-2613), Tab cycle (2561-2570), `_POSE_WINDOW=30` + cached-check (1740-1755), `layerThreshold` (606-610), `poseCacheKey = path:threshold.toFixed(2)` (1681), save-marker payload `{h5, frame, bp, x, y}` (1364; delete = x:null,y:null). Pose shape: `{bp, x, y, lh, color_idx}`.

**Run a unit test:**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_marker_overlay.mjs
```

---

## Task 1: `marker_overlay.mjs` — pure overlay/edit logic

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/marker_overlay.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_marker_overlay.mjs`

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_marker_overlay.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  scaleFor, videoToCanvas, canvasToVideo, markerRadius,
  hitTest, resolvePose, setEdit, deleteEdit, frameEditsOf, editedFrameCount,
  nudge, nextBodypart, prefetchWindow, allCached, layerThreshold,
  poseCacheKey, buildMarkerEditPayload,
} from "../../src/static/components/viewer/internal/marker_overlay.mjs";

const HALF = { sx: 0.5, sy: 0.5 };

test("scale + coordinate transforms", () => {
  assert.deepEqual(scaleFor(800, 600, 400, 300), { sx: 0.5, sy: 0.5 });
  assert.deepEqual(scaleFor(0, 0, 400, 300), { sx: 400, sy: 300 }); // guards /0
  assert.deepEqual(videoToCanvas(100, 50, HALF), { cx: 50, cy: 25 });
  assert.deepEqual(canvasToVideo(50, 25, HALF), { x: 100, y: 50 });
  assert.equal(markerRadius(6, HALF), 3);
  assert.equal(markerRadius(1, { sx: 0.1, sy: 0.1 }), 1); // floor at 1
});

test("hitTest: nearest bp within radius (video coords scaled to canvas)", () => {
  const poses = [{ bp: "a", x: 100, y: 50 }, { bp: "b", x: 300, y: 300 }];
  assert.equal(hitTest(poses, 50, 25, HALF, 6), "a");   // on top of a
  assert.equal(hitTest(poses, 50, 200, HALF, 6), null); // far from both
});

test("hitTest: edits override position; deleted edits are skipped", () => {
  const poses = [{ bp: "a", x: 100, y: 50 }];
  const moved = { a: { x: 200, y: 100 } };
  assert.equal(hitTest(poses, 100, 50, HALF, 6, moved, 8), "a"); // hits moved location
  assert.equal(hitTest(poses, 50, 25, HALF, 6, moved, 8), null); // original spot now empty
  const deleted = { a: { x: null, y: null } };
  assert.equal(hitTest(poses, 50, 25, HALF, 6, deleted, 8), null);
});

test("resolvePose merges an edit over a pose", () => {
  const pose = { bp: "a", x: 100, y: 50 };
  assert.deepEqual(resolvePose(pose, {}), { x: 100, y: 50, edited: false, deleted: false });
  assert.deepEqual(resolvePose(pose, { a: { x: 7, y: 8 } }), { x: 7, y: 8, edited: true, deleted: false });
  assert.deepEqual(resolvePose(pose, { a: { x: null, y: null } }), { x: null, y: null, edited: true, deleted: true });
});

test("setEdit / deleteEdit are immutable; frameEditsOf + editedFrameCount", () => {
  const e0 = {};
  const e1 = setEdit(e0, 5, "a", 10, 20);
  assert.deepEqual(e0, {});                                   // not mutated
  assert.deepEqual(e1, { 5: { a: { x: 10, y: 20 } } });
  const e2 = setEdit(e1, 5, "b", 1, 2);
  assert.deepEqual(e2[5], { a: { x: 10, y: 20 }, b: { x: 1, y: 2 } });
  const e3 = deleteEdit(e2, 5, "a");
  assert.deepEqual(e3[5].a, { x: null, y: null });
  assert.deepEqual(frameEditsOf(e3, 5), e3[5]);
  assert.deepEqual(frameEditsOf(e3, 99), {});
  assert.equal(editedFrameCount({ 5: {}, 7: {} }), 2);
});

test("nudge: WASD ±1 / ±10, null for other keys", () => {
  const b = { x: 10, y: 20 };
  assert.deepEqual(nudge(b, "a", false), { x: 9, y: 20 });
  assert.deepEqual(nudge(b, "d", false), { x: 11, y: 20 });
  assert.deepEqual(nudge(b, "w", false), { x: 10, y: 19 });
  assert.deepEqual(nudge(b, "s", false), { x: 10, y: 21 });
  assert.deepEqual(nudge(b, "D", true), { x: 20, y: 20 });   // shift = 10, case-insensitive
  assert.equal(nudge(b, "x", false), null);
});

test("nextBodypart cycles forward/backward and handles edges", () => {
  const l = ["a", "b", "c"];
  assert.equal(nextBodypart(l, "a"), "b");
  assert.equal(nextBodypart(l, "c"), "a");                   // wrap
  assert.equal(nextBodypart(l, "b", true), "a");
  assert.equal(nextBodypart(l, "a", true), "c");             // wrap backward
  assert.equal(nextBodypart(l, "missing"), "a");             // not found → first
  assert.equal(nextBodypart([], "a"), null);
});

test("prefetchWindow clamps to frameCount", () => {
  assert.deepEqual(prefetchWindow(10, 30, 100), { start: 10, count: 30 });
  assert.deepEqual(prefetchWindow(90, 30, 100), { start: 90, count: 10 });
  assert.deepEqual(prefetchWindow(100, 30, 100), { start: 100, count: 0 });
});

test("allCached: every frame in the window present with matching key", () => {
  const cache = new Map();
  for (let i = 10; i < 40; i++) cache.set(i, { key: "k", poses: [] });
  assert.equal(allCached(cache, 10, 30, 100, "k"), true);
  assert.equal(allCached(cache, 10, 30, 100, "other"), false); // key changed
  cache.delete(25);
  assert.equal(allCached(cache, 10, 30, 100, "k"), false);     // a gap
});

test("layerThreshold + poseCacheKey + payload", () => {
  assert.equal(layerThreshold({ threshold: 0.8 }, 0.6, true), 0.8);
  assert.equal(layerThreshold({ threshold: 0.8 }, 0.6, false), 0.6); // per-layer off
  assert.equal(layerThreshold({ threshold: null }, 0.6, true), 0.6); // null falls back
  assert.equal(poseCacheKey("/x.h5", 0.6), "/x.h5:0.60");
  assert.deepEqual(buildMarkerEditPayload("/x.h5", 5, "a", 10, 20),
    { h5: "/x.h5", frame: 5, bp: "a", x: 10, y: 20 });
  assert.deepEqual(buildMarkerEditPayload("/x.h5", 5, "a", null, null),
    { h5: "/x.h5", frame: 5, bp: "a", x: null, y: null });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_marker_overlay.mjs`
Expected: FAIL — cannot find module `marker_overlay.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/marker_overlay.mjs`:

```js
// Pure overlay/edit logic for the MarkerEditor feature: scale + coordinate transforms,
// hit-testing, pose↔edit merge, prefetch-window math, layer threshold/cache-key, WASD
// nudge, tab cycling, and the save-marker payload. No DOM, no fetch.
// Marker drawing reuses palette.mjs + shapes.mjs (Phase 1). Edits are a plain object
// keyed by frame: { [frame]: { [bp]: { x, y } } }, where x===null,y===null means deleted.

// ── scale + coordinate transforms ──
export function scaleFor(naturalW, naturalH, canvasW, canvasH) {
  return { sx: canvasW / (naturalW || 1), sy: canvasH / (naturalH || 1) };
}

export function videoToCanvas(x, y, scale) {
  return { cx: Math.round(x * scale.sx), cy: Math.round(y * scale.sy) };
}

export function canvasToVideo(cx, cy, scale) {
  return { x: cx / scale.sx, y: cy / scale.sy };
}

export function markerRadius(markerSize, scale) {
  return Math.max(1, Math.round(markerSize * Math.min(scale.sx, scale.sy)));
}

// ── hit-testing ──
// poses: [{ bp, x, y }]; frameEdits: { [bp]: { x, y } } overrides position (null = deleted);
// pad widens the hit radius (6 for plain, 8 when accounting for edits). Returns bp or null.
export function hitTest(poses, cx, cy, scale, markerSize, frameEdits = {}, pad = 6) {
  const hitR = (markerSize + pad) * Math.max(scale.sx, scale.sy);
  for (const pose of poses) {
    const e = frameEdits[pose.bp];
    if (e && (e.x == null || e.y == null)) continue; // deleted marker
    const px = (e ? e.x : pose.x) * scale.sx;
    const py = (e ? e.y : pose.y) * scale.sy;
    const dx = px - cx;
    const dy = py - cy;
    if (Math.sqrt(dx * dx + dy * dy) <= hitR) return pose.bp;
  }
  return null;
}

// ── pose↔edit merge (for rendering) ──
export function resolvePose(pose, frameEdits = {}) {
  const e = frameEdits[pose.bp];
  if (!e) return { x: pose.x, y: pose.y, edited: false, deleted: false };
  if (e.x == null || e.y == null) return { x: null, y: null, edited: true, deleted: true };
  return { x: e.x, y: e.y, edited: true, deleted: false };
}

// ── local edits (immutable plain-object ops) ──
export function setEdit(edits, frame, bp, x, y) {
  return { ...edits, [frame]: { ...(edits[frame] || {}), [bp]: { x, y } } };
}

export function deleteEdit(edits, frame, bp) {
  return setEdit(edits, frame, bp, null, null);
}

export function frameEditsOf(edits, frame) {
  return edits[frame] || {};
}

export function editedFrameCount(edits) {
  return Object.keys(edits).length;
}

// ── WASD nudge ──
export function nudge(base, key, shift) {
  const step = shift ? 10 : 1;
  let dx = 0;
  let dy = 0;
  switch (key.toLowerCase()) {
    case "a": dx = -step; break;
    case "d": dx = step; break;
    case "w": dy = -step; break;
    case "s": dy = step; break;
    default: return null;
  }
  return { x: base.x + dx, y: base.y + dy };
}

// ── tab cycling ──
export function nextBodypart(list, current, backward = false) {
  if (!list.length) return null;
  const idx = list.indexOf(current);
  if (idx < 0) return list[0];
  const n = backward ? (list.length + idx - 1) % list.length : (idx + 1) % list.length;
  return list[n];
}

// ── prefetch window ──
export function prefetchWindow(fromFrame, windowSize, frameCount) {
  const end = Math.min(fromFrame + windowSize, frameCount);
  return { start: fromFrame, count: Math.max(0, end - fromFrame) };
}

// allCached: true iff every frame in [fromFrame, fromFrame+windowSize) (clamped to
// frameCount) is present in the cache Map with a matching `key`.
export function allCached(cache, fromFrame, windowSize, frameCount, key) {
  for (let i = fromFrame; i < fromFrame + windowSize && i < frameCount; i++) {
    const c = cache.get(i);
    if (!c || c.key !== key) return false;
  }
  return true;
}

// ── layer threshold + cache key ──
export function layerThreshold(layer, globalThreshold, perLayer) {
  return (perLayer && layer.threshold != null) ? layer.threshold : globalThreshold;
}

export function poseCacheKey(h5Path, threshold) {
  return `${h5Path}:${threshold.toFixed(2)}`;
}

// ── save-marker payload (x===null,y===null for delete) ──
export function buildMarkerEditPayload(h5Path, frame, bp, x, y) {
  return { h5: h5Path, frame, bp, x, y };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_marker_overlay.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/marker_overlay.mjs dlc-3D/tests/unit/test_viewer_marker_overlay.mjs
git commit -m "feat(dlc-3d viewer-lib): marker_overlay.mjs (overlay/edit pure logic) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Phase-3d-i wrap-up — suites green, no consumer touched

**Files:** none (verification only)

- [ ] **Step 1: Full viewer unit suite (now incl. marker_overlay)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs \
  tests/unit/test_viewer_frame_pacer.mjs tests/unit/test_viewer_clip_naming.mjs \
  tests/unit/test_viewer_tile_layout.mjs tests/unit/test_viewer_seek_plan.mjs \
  tests/unit/test_viewer_fit_viewer.mjs tests/unit/test_viewer_controls.mjs \
  tests/unit/test_viewer_event_bus.mjs tests/unit/test_viewer_csv_annotations.mjs \
  tests/unit/test_viewer_frame_extract.mjs tests/unit/test_viewer_clip_extract.mjs \
  tests/unit/test_viewer_marker_overlay.mjs tests/unit/test_pair_map.mjs
```
Expected: `# fail 0`.

- [ ] **Step 2: Confirm no consumer/origin file modified**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~1 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js clip-cutter/`
Expected: empty output.

---

## Phase-3d-i exit criteria

- `internal/marker_overlay.mjs` added with passing node tests; full viewer unit suite green (13 viewer modules + pair_map).
- No consumer/origin file modified.

**Next:** Phase 3d-ii — `features/marker_editor.js`: the DOM feature that imports `marker_overlay.mjs` + `palette.mjs` + `shapes.mjs`, fetches poses (single + batch prefetch via AbortController), renders all visible layers per tile via the viewer's `onDrawTile` hook (comparison layers under the editable primary), wires hit-test/hover + drag/place/right-click-delete + WASD editing (gated to single-layer-only via `isEditable`), the bodypart chips, and the edit banner; flushes edits to an injected `saveMarker` endpoint. Then `CurationModule`. Phase 4 migrates the forks; Phase 5 adds the policy doc + enforcement test.
