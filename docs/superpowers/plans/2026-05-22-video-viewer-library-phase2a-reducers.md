# Video-Viewer Library — Phase 2a (base reducers) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the pure, DOM-free orchestration logic that the `VideoViewer` base class (Phase 2b) will be assembled from — tile layout, frame-locked seek planning, zoom-fit sizing, and control mapping — into node-testable `.mjs` modules.

**Architecture:** Phase 2 is split per the agreed testing strategy: push as much base-class orchestration as possible into pure reducers (this plan, unit-tested with `node:test` exactly like Phase 1), so the Phase 2b DOM shell is a thin assembler verified by code review now and by the existing E2E suites when a consumer is migrated (Phase 4). These reducers have NO DOM, fetch, timers, or globals.

**Tech Stack:** Vanilla ES modules (`.mjs`), Node 16 `node:test` + `node:assert/strict`.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.3 base class).

**Source of truth for the ported logic (file:line in current forks):**
- Tile layout / sibling decision: `dlc-3D/src/static/viewer_3d.js` Controller `loadVideo`/`_ensureSiblingTile` (~141-256); sibling probe response `{ sibling_video_path }` (~178).
- Seek orchestration (clamp + parallel tile loads + sibling-skip in frames mode): `viewer_3d.js` `Controller.seek` (271-293), `_vaLoadFrame` clamp (757).
- Zoom-fit math: `viewer_3d.js` `_vaFitViewer` (645-658).
- Control clamps + keys: `viewer_3d.js` `_vaPlayStep`/`_vaPlaybackFps` (1918-1929), keydown handler arrows/space (2507-2615).

**Run a unit test (Node 16 — explicit file path required):**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/<file>.mjs
```

These modules live alongside the Phase 1 modules in `dlc-3D/src/static/components/viewer/internal/`. Phase 2a touches NO consumer/origin file.

---

## Task 1: `tile_layout.mjs` — ordered tile descriptors

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/tile_layout.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_tile_layout.mjs`

Pure version of the "tile 0 always exists; tile 1 only if a sibling video was discovered"
decision from `viewer_3d.js` Controller. Given the primary + optional sibling video paths,
return the ordered tile descriptors the DOM shell will instantiate.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_tile_layout.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { planTiles } from "../../src/static/components/viewer/internal/tile_layout.mjs";

test("primary only → single main tile (cam 0)", () => {
  assert.deepEqual(planTiles({ primaryVideoRel: "a.avi", siblingVideoRel: null }),
    [{ cam: 0, videoRel: "a.avi", label: "main" }]);
});

test("primary + sibling → two tiles", () => {
  assert.deepEqual(planTiles({ primaryVideoRel: "a.avi", siblingVideoRel: "b.avi" }),
    [{ cam: 0, videoRel: "a.avi", label: "main" },
     { cam: 1, videoRel: "b.avi", label: "sibling" }]);
});

test("empty-string sibling is treated as no sibling", () => {
  assert.equal(planTiles({ primaryVideoRel: "a.avi", siblingVideoRel: "" }).length, 1);
});

test("custom labels are honored", () => {
  const tiles = planTiles({ primaryVideoRel: "a", siblingVideoRel: "b",
    primaryLabel: "cam0", siblingLabel: "cam1" });
  assert.equal(tiles[0].label, "cam0");
  assert.equal(tiles[1].label, "cam1");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_tile_layout.mjs`
Expected: FAIL — cannot find module `tile_layout.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/tile_layout.mjs`:

```js
// Pure tile-layout planning: primary tile (cam 0) always present; sibling tile (cam 1)
// only when a sibling video was discovered. Mirrors viewer_3d.js Controller tile decision.

export function planTiles({
  primaryVideoRel,
  siblingVideoRel,
  primaryLabel = "main",
  siblingLabel = "sibling",
}) {
  const tiles = [{ cam: 0, videoRel: primaryVideoRel, label: primaryLabel }];
  if (siblingVideoRel) {
    tiles.push({ cam: 1, videoRel: siblingVideoRel, label: siblingLabel });
  }
  return tiles;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_tile_layout.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/tile_layout.mjs dlc-3D/tests/unit/test_viewer_tile_layout.mjs
git commit -m "feat(dlc-3d viewer-lib): tile_layout.mjs (planTiles) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `seek_plan.mjs` — frame-locked seek planning

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/seek_plan.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_seek_plan.mjs`

Pure version of `Controller.seek`: clamp the target frame into `[0, frameCount-1]`, then list
which `(cam, videoRel, frame)` loads the DOM shell must fire in parallel. Tiles without a
`videoRel` are skipped; the sibling tile (cam ≠ 0) is skipped in `frames` mode (the sibling
has no labeled-frame folder). Reuses `clampFrame` from Phase 1.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_seek_plan.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { planSeek } from "../../src/static/components/viewer/internal/seek_plan.mjs";

const TILES = [
  { cam: 0, videoRel: "a.avi" },
  { cam: 1, videoRel: "b.avi" },
];

test("clamps n into [0, frameCount-1] and loads both tiles at that frame", () => {
  assert.deepEqual(planSeek({ n: 5, frameCount: 100, tiles: TILES }), {
    frame: 5,
    loads: [{ cam: 0, videoRel: "a.avi", frame: 5 },
            { cam: 1, videoRel: "b.avi", frame: 5 }],
  });
  assert.equal(planSeek({ n: -10, frameCount: 100, tiles: TILES }).frame, 0);
  assert.equal(planSeek({ n: 999, frameCount: 100, tiles: TILES }).frame, 99);
});

test("frameCount 0 clamps to frame 0", () => {
  assert.equal(planSeek({ n: 3, frameCount: 0, tiles: TILES }).frame, 0);
});

test("sibling tile is skipped in frames mode", () => {
  const plan = planSeek({ n: 2, frameCount: 100, tiles: TILES, framesMode: true });
  assert.deepEqual(plan.loads, [{ cam: 0, videoRel: "a.avi", frame: 2 }]);
});

test("tiles without a videoRel are skipped", () => {
  const plan = planSeek({ n: 2, frameCount: 100,
    tiles: [{ cam: 0, videoRel: "a.avi" }, { cam: 1, videoRel: null }] });
  assert.equal(plan.loads.length, 1);
  assert.equal(plan.loads[0].cam, 0);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_seek_plan.mjs`
Expected: FAIL — cannot find module `seek_plan.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/seek_plan.mjs`:

```js
// Pure seek planning: clamp the target frame and list the parallel tile loads.
// Mirrors viewer_3d.js Controller.seek (clamp + Promise.all over tiles, sibling skipped
// in frames mode). The DOM shell turns each load into an <img>.src assignment.

import { clampFrame } from "./frame_pacer.mjs";

export function planSeek({ n, frameCount, tiles, framesMode = false }) {
  const frame = clampFrame(n, 0, Math.max(frameCount - 1, 0));
  const loads = [];
  for (const t of tiles) {
    if (!t.videoRel) continue;
    if (t.cam !== 0 && framesMode) continue; // sibling has no labeled-frame folder
    loads.push({ cam: t.cam, videoRel: t.videoRel, frame });
  }
  return { frame, loads };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_seek_plan.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/seek_plan.mjs dlc-3D/tests/unit/test_viewer_seek_plan.mjs
git commit -m "feat(dlc-3d viewer-lib): seek_plan.mjs (planSeek) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `fit_viewer.mjs` — zoom→width/margin sizing

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/fit_viewer.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_fit_viewer.mjs`

Pure version of `_vaFitViewer` (645-658): given the base content width, the maximum allowed
width, and a zoom percentage, compute the tile-row pixel width and the centering margin.
Returns numeric `marginLeft` (the DOM shell formats it as `"-Npx"` or `""`).

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_fit_viewer.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { fitViewerSize } from "../../src/static/components/viewer/internal/fit_viewer.mjs";

test("100% zoom: width == baseW, no centering margin", () => {
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 1200, zoom: 100 }),
    { width: 800, marginLeft: 0 });
});

test("150% zoom within maxW: overflow centered by negative half-margin", () => {
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 2000, zoom: 150 }),
    { width: 1200, marginLeft: -200 });
});

test("zoom clamped by maxW (floored)", () => {
  // round(800*1.5)=1200 but maxW floor is 1000 → width 1000, extra 200 → margin -100
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 1000.9, zoom: 150 }),
    { width: 1000, marginLeft: -100 });
});

test("zoom below 100% never produces a positive margin", () => {
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 2000, zoom: 50 }),
    { width: 400, marginLeft: 0 });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_fit_viewer.mjs`
Expected: FAIL — cannot find module `fit_viewer.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/fit_viewer.mjs`:

```js
// Pure zoom-fit sizing for the tile row. Mirrors viewer_3d.js _vaFitViewer:
//   targetW = min(round(baseW * zoom/100), floor(maxW))
//   marginLeft = overflow ? -extra/2 : 0   (centers content wider than baseW)

export function fitViewerSize({ baseW, maxW, zoom }) {
  const targetW = Math.min(Math.round(baseW * (zoom / 100)), Math.floor(maxW));
  const extra = targetW - baseW;
  return { width: targetW, marginLeft: extra > 0 ? -extra / 2 : 0 };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_fit_viewer.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/fit_viewer.mjs dlc-3D/tests/unit/test_viewer_fit_viewer.mjs
git commit -m "feat(dlc-3d viewer-lib): fit_viewer.mjs (fitViewerSize) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `controls.mjs` — key→intent mapping + play-param clamps

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/controls.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_controls.mjs`

Pure mapping of keyboard events to **base** navigation intents (space=play/pause,
arrows=±1 frame, Ctrl+arrows=±skipN), plus the play-step (1-100, default 1) and fps
(1-120, default 5) clamps. Feature-specific keys (Tab/WASD/Delete for marker editing)
are NOT handled here — they belong to the MarkerEditor feature in Phase 3.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_controls.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { resolveKey, clampPlayStep, clampFps }
  from "../../src/static/components/viewer/internal/controls.mjs";

test("space → playPause", () => {
  assert.deepEqual(resolveKey({ key: " " }), { type: "playPause" });
});

test("arrows → single step; ctrl+arrows → skip step", () => {
  assert.deepEqual(resolveKey({ key: "ArrowLeft" }),  { type: "step", delta: -1 });
  assert.deepEqual(resolveKey({ key: "ArrowRight" }), { type: "step", delta: 1 });
  assert.deepEqual(resolveKey({ key: "ArrowLeft", ctrlKey: true }),  { type: "stepSkip", dir: -1 });
  assert.deepEqual(resolveKey({ key: "ArrowRight", ctrlKey: true }), { type: "stepSkip", dir: 1 });
});

test("unhandled keys → null", () => {
  assert.equal(resolveKey({ key: "x" }), null);
  assert.equal(resolveKey({ key: "Tab" }), null);
});

test("clampPlayStep: 1..100, default 1 on NaN", () => {
  assert.equal(clampPlayStep("3"), 3);
  assert.equal(clampPlayStep("0"), 1);
  assert.equal(clampPlayStep("500"), 100);
  assert.equal(clampPlayStep("abc"), 1);
});

test("clampFps: 1..120, default 5 on NaN", () => {
  assert.equal(clampFps("30"), 30);
  assert.equal(clampFps("0"), 1);
  assert.equal(clampFps("999"), 120);
  assert.equal(clampFps(""), 5);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_controls.mjs`
Expected: FAIL — cannot find module `controls.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/controls.mjs`:

```js
// Pure control mapping for the base viewer. Mirrors viewer_3d.js keydown handler
// (space / arrows / ctrl+arrows) and _vaPlayStep / _vaPlaybackFps clamps.
// Feature keys (Tab, WASD, Delete) are intentionally NOT handled here.

export function resolveKey({ key, ctrlKey = false }) {
  if (key === " " || key === "Spacebar") return { type: "playPause" };
  if (key === "ArrowLeft") {
    return ctrlKey ? { type: "stepSkip", dir: -1 } : { type: "step", delta: -1 };
  }
  if (key === "ArrowRight") {
    return ctrlKey ? { type: "stepSkip", dir: 1 } : { type: "step", delta: 1 };
  }
  return null;
}

export function clampPlayStep(v, def = 1) {
  const n = parseInt(v, 10);
  return Math.max(1, Math.min(100, isNaN(n) ? def : n));
}

export function clampFps(v, def = 5) {
  const n = parseInt(v, 10);
  return Math.max(1, Math.min(120, isNaN(n) ? def : n));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_controls.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/controls.mjs dlc-3D/tests/unit/test_viewer_controls.mjs
git commit -m "feat(dlc-3d viewer-lib): controls.mjs (resolveKey + play-param clamps) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Phase-2a wrap-up — full unit suite green, no consumer touched

**Files:** none (verification only)

- [ ] **Step 1: Run the entire viewer unit suite (Phase 1 + Phase 2a + pair_map)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs \
  tests/unit/test_viewer_frame_pacer.mjs tests/unit/test_viewer_clip_naming.mjs \
  tests/unit/test_viewer_tile_layout.mjs tests/unit/test_viewer_seek_plan.mjs \
  tests/unit/test_viewer_fit_viewer.mjs tests/unit/test_viewer_controls.mjs \
  tests/unit/test_pair_map.mjs
```
Expected: `# fail 0`.

- [ ] **Step 2: Confirm no consumer/origin file was modified**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~5 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js clip-cutter/`
Expected: empty output.

---

## Phase-2a exit criteria

- `internal/` contains `tile_layout.mjs`, `seek_plan.mjs`, `fit_viewer.mjs`, `controls.mjs`, each with a passing `tests/unit/test_viewer_*.mjs`.
- Whole viewer unit suite green; no consumer/origin file modified.
- Four commits landed (one per module).

**Next:** Phase 2b — the `VideoViewer` DOM shell class that imports these reducers + Phase 1's `frame_pacer`/`palette`/`shapes`, owns tile DOM creation, frame fetch (`<img>.src` + load-token race guard + prefetch + rAF paint barrier), the play loop, zoom, keyboard listener, and the `onVideoLoad/onFrameChange/onDrawTile/onTeardown` hook bus. Verified by code review (no DOM test runner) and exercised for real when the first consumer is migrated in Phase 4.
