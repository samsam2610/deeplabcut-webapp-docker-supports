# Video-Viewer Library — Phase 2b (VideoViewer base class) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `VideoViewer` base class — the thin DOM shell that assembles the Phase 1/2a pure reducers into a frame-by-frame, N-tile, frame-locked video player with a hook bus that feature modules subscribe to.

**Architecture:** The class owns only DOM-bound work (tile creation, `<img>.src` frame fetch with a per-tile load-token race guard + prefetch + rAF paint barrier, the play loop, zoom application, keyboard listener). All orchestration math is delegated to the already-tested reducers. The hook bus is its own pure `event_bus.mjs` module (node-tested). Because a browser ESM `.js` cannot be imported under Node (no `package.json` `type:module`), the class is verified by a pytest static-analysis contract test (like `file_browser.js`) plus code review; it is exercised for real when the first consumer is migrated in Phase 4.

**Tech Stack:** Vanilla ES modules; `node:test` for `event_bus.mjs`; pytest regex contract test for the class.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.3).

**Source of truth (current forks):** `viewer_3d.js` Tile class (~5-42), Controller/seek (~129-293), `_vaLoadFrame` (~754-813), play loop (~2446-2466), `_vaFitViewer` (~645-658), keydown (~2507-2615). Frame fetch uses an off-DOM `Image()` preload then atomic `img.src` swap; per-tile `_loadToken` guards stale loads; primary tile prefetches `n+1` and awaits one `requestAnimationFrame` as a paint barrier.

**Commands:**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_event_bus.mjs          # Task 1
python -m pytest tests/test_video_viewer_base.py -q        # Task 2 (static; launches no app)
```

---

## Task 1: `event_bus.mjs` — synchronous pub/sub for the hook bus

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/event_bus.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_event_bus.mjs`

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_event_bus.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { makeEventBus } from "../../src/static/components/viewer/internal/event_bus.mjs";

test("on/emit delivers args to listener", () => {
  const bus = makeEventBus();
  let got = null;
  bus.on("frame", (n, extra) => { got = [n, extra]; });
  bus.emit("frame", 7, "x");
  assert.deepEqual(got, [7, "x"]);
});

test("multiple listeners on one event all fire", () => {
  const bus = makeEventBus();
  let a = 0, b = 0;
  bus.on("e", () => a++);
  bus.on("e", () => b++);
  bus.emit("e");
  assert.equal(a, 1);
  assert.equal(b, 1);
});

test("emit with no listeners is a no-op", () => {
  const bus = makeEventBus();
  assert.doesNotThrow(() => bus.emit("nope", 1));
});

test("the function returned by on() unsubscribes", () => {
  const bus = makeEventBus();
  let n = 0;
  const off = bus.on("e", () => n++);
  bus.emit("e");
  off();
  bus.emit("e");
  assert.equal(n, 1);
});

test("a listener unsubscribing itself mid-emit does not break iteration", () => {
  const bus = makeEventBus();
  const calls = [];
  const off = bus.on("e", () => { calls.push("a"); off(); });
  bus.on("e", () => calls.push("b"));
  bus.emit("e");
  bus.emit("e");
  assert.deepEqual(calls, ["a", "b", "b"]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_event_bus.mjs`
Expected: FAIL — cannot find module `event_bus.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/event_bus.mjs`:

```js
// Tiny synchronous pub/sub powering VideoViewer's hook bus. Pure, no DOM.
// emit() snapshots its listener set so a callback may unsubscribe during dispatch.

export function makeEventBus() {
  const listeners = new Map(); // event -> Set<cb>
  return {
    on(event, cb) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(cb);
      return () => {
        const set = listeners.get(event);
        if (set) set.delete(cb);
      };
    },
    emit(event, ...args) {
      const set = listeners.get(event);
      if (!set) return;
      for (const cb of [...set]) cb(...args);
    },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_event_bus.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/event_bus.mjs dlc-3D/tests/unit/test_viewer_event_bus.mjs
git commit -m "feat(dlc-3d viewer-lib): event_bus.mjs (hook-bus pub/sub) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `video_viewer.js` — the VideoViewer base class

**Files:**
- Create: `dlc-3D/src/static/components/viewer/video_viewer.js`
- Test: `dlc-3D/tests/test_video_viewer_base.py`

TDD here uses a **static-analysis contract test** (the class can't run under Node): write
the pytest contract first (it fails — file missing), then write the class to satisfy it.

- [ ] **Step 1: Write the failing contract test**

Create `dlc-3D/tests/test_video_viewer_base.py`:

```python
"""Static-analysis contract for the VideoViewer base class (Phase 2b).

The browser ESM component cannot be imported under Node (a `.js` file with no
package.json `type:module` is parsed as CommonJS), so — like file_browser.js — its
contract is enforced by regex over source plus code review. These checks catch a
future refactor that drops a reducer import, a public method, or a hook event.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VV = ROOT / "src" / "static" / "components" / "viewer" / "video_viewer.js"


def _src():
    assert VV.is_file(), f"missing VideoViewer at {VV}"
    return VV.read_text()


def test_exists_and_exports_class():
    assert re.search(r"export\s+class\s+VideoViewer\b", _src()), \
        "video_viewer.js must export `class VideoViewer`"


@pytest.mark.parametrize("name,module", [
    ("makeEventBus", "event_bus"),
    ("planTiles", "tile_layout"),
    ("planSeek", "seek_plan"),
    ("fitViewerSize", "fit_viewer"),
    ("resolveKey", "controls"),
])
def test_imports_reducer(name, module):
    src = _src()
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*{module}\.mjs[\"']", src), \
        f"VideoViewer must import {name} from internal/{module}.mjs (no re-implementation)"


@pytest.mark.parametrize("method", ["load", "seek", "step", "play", "pause", "use", "on", "destroy"])
def test_public_method_present(method):
    assert re.search(rf"\b{method}\s*\(", _src()), f"VideoViewer must define `{method}(`"


@pytest.mark.parametrize("event", ["videoLoad", "frameChange", "drawTile", "teardown"])
def test_hook_event_emitted(event):
    src = _src()
    assert f'"{event}"' in src or f"'{event}'" in src, f'VideoViewer must emit the "{event}" hook event'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_base.py -q`
Expected: FAIL — `missing VideoViewer at .../video_viewer.js`.

- [ ] **Step 3: Write the class**

Create `dlc-3D/src/static/components/viewer/video_viewer.js`:

```js
// VideoViewer — reusable base video player (DOM shell).
// Assembles the pure reducers in ./internal/ into a frame-by-frame, N-tile,
// frame-locked viewer with a hook bus that feature modules subscribe to.
//
// All coupling is injected via config — no hardcoded endpoints, DOM ids, or
// localStorage keys. Frames are fetched as images and swapped onto <img> elements
// (no <video> element), matching the clip-cutter / viewer_3d players this is
// extracted from.
//
// Hook-bus events (subscribe via viewer.on(event, cb)):
//   "videoLoad"  ({ videoPath, frameCount, tiles })   after a video is loaded
//   "frameChange"(frame)                               after every seek
//   "drawTile"   (tile, frame)                         per tile after a seek
//   "teardown"   ()                                    on destroy()

import { makeEventBus } from "./internal/event_bus.mjs";
import { planTiles } from "./internal/tile_layout.mjs";
import { planSeek } from "./internal/seek_plan.mjs";
import { fitViewerSize } from "./internal/fit_viewer.mjs";
import { resolveKey, clampPlayStep, clampFps } from "./internal/controls.mjs";
import { nextFrame, frameDelayMs } from "./internal/frame_pacer.mjs";

const TILE_HTML = `
  <div class="vv-tile-canvas-wrap" style="position:relative;display:inline-block;">
    <img class="vv-frame-img" style="display:block;max-width:100%;">
    <canvas class="vv-overlay-canvas" style="position:absolute;top:0;left:0;pointer-events:none;"></canvas>
    <div class="vv-frame-spinner hidden"></div>
    <div class="vv-tile-label"></div>
  </div>`;

class Tile {
  constructor(cam, videoRel, label, rootEl) {
    this.cam = cam;
    this.videoRel = videoRel;
    this.label = label;
    this.rootEl = rootEl;
    this.imgEl = rootEl.querySelector(".vv-frame-img");
    this.canvasEl = rootEl.querySelector(".vv-overlay-canvas");
    this.labelEl = rootEl.querySelector(".vv-tile-label");
    this.spinnerEl = rootEl.querySelector(".vv-frame-spinner");
    this._loadToken = 0;
    if (this.labelEl) this.labelEl.textContent = label || "";
  }
}

export class VideoViewer {
  constructor({ mount, endpoints, fps = 15, storagePrefix = "vv", keymap = resolveKey } = {}) {
    if (!mount) throw new Error("VideoViewer: `mount` element is required");
    if (!endpoints || typeof endpoints.frame !== "function") {
      throw new Error("VideoViewer: `endpoints.frame(videoPath, n)` is required");
    }
    this.mount = mount;
    this.endpoints = endpoints;
    this.storagePrefix = storagePrefix;
    this._resolveKey = keymap;
    this._bus = makeEventBus();
    this._features = [];

    // playback / view state
    this._currentFrame = 0;
    this._frameCount = 0;
    this._fps = fps;
    this._playN = 1;
    this._playDir = 1;
    this._looping = false;
    this._playing = false;
    this._playTimer = null;
    this._zoom = 100;
    this._skipN = 10;
    this.framesMode = false;

    this.tiles = [];
    this._videoPath = null;

    const doc = mount.ownerDocument;
    this.rowEl = doc.createElement("div");
    this.rowEl.className = "vv-tile-row";
    this.rowEl.style.display = "flex";
    this.rowEl.style.gap = "8px";
    mount.appendChild(this.rowEl);

    if (!mount.getAttribute("tabindex")) mount.setAttribute("tabindex", "0");
    this._onKeyDown = (e) => this._handleKeyDown(e);
    mount.addEventListener("keydown", this._onKeyDown);
  }

  // ── hook bus ──────────────────────────────────────────────
  on(event, cb) { return this._bus.on(event, cb); }
  _emit(event, ...args) { this._bus.emit(event, ...args); }

  // ── feature composition ───────────────────────────────────
  use(feature) {
    if (feature && typeof feature.attach === "function") feature.attach(this);
    this._features.push(feature);
    return this;
  }

  // ── getters ───────────────────────────────────────────────
  currentFrame() { return this._currentFrame; }
  frameCount() { return this._frameCount; }
  getTile(i) { return this.tiles[i] || null; }
  videoPath() { return this._videoPath; }
  isPlaying() { return this._playing; }

  // ── loading ───────────────────────────────────────────────
  async load({ videoPath, siblingPath, frameCount, framesMode = false } = {}) {
    this._stop();
    this._clearTiles();
    this._videoPath = videoPath;
    this.framesMode = framesMode;

    if (frameCount != null) {
      this._frameCount = frameCount;
    } else if (this.endpoints.videoInfo) {
      try {
        const info = await (await fetch(this.endpoints.videoInfo(videoPath))).json();
        this._frameCount = info.frame_count || 0;
        if (info.fps) this._fps = info.fps;
      } catch (_) { this._frameCount = 0; }
    }

    if (siblingPath === undefined && this.endpoints.sibling && !framesMode) {
      try {
        const j = await (await fetch(this.endpoints.sibling(videoPath))).json();
        siblingPath = j.sibling_video_path || null;
      } catch (_) { siblingPath = null; }
    }

    const descs = planTiles({ primaryVideoRel: videoPath, siblingVideoRel: siblingPath || null });
    this.tiles = descs.map((d) => this._createTile(d));

    this._emit("videoLoad", { videoPath, frameCount: this._frameCount, tiles: this.tiles });
    await this.seek(0);
  }

  _createTile(desc) {
    const wrap = this.mount.ownerDocument.createElement("div");
    wrap.className = "vv-tile";
    wrap.dataset.cam = String(desc.cam);
    wrap.innerHTML = TILE_HTML;
    this.rowEl.appendChild(wrap);
    return new Tile(desc.cam, desc.videoRel, desc.label, wrap);
  }

  _clearTiles() {
    this.rowEl.innerHTML = "";
    this.tiles = [];
  }

  // ── seeking (frame-locked across tiles) ───────────────────
  async seek(n) {
    const { frame, loads } = planSeek({
      n, frameCount: this._frameCount, tiles: this.tiles, framesMode: this.framesMode,
    });
    const loadCams = new Set(loads.map((l) => l.cam));
    await Promise.all(
      this.tiles
        .filter((t) => loadCams.has(t.cam))
        .map((t) => this._loadTileFrame(t, frame, t.cam === 0)),
    );
    this._currentFrame = frame;
    this._emit("frameChange", frame);
    for (const tile of this.tiles) this._emit("drawTile", tile, frame);
  }

  async _loadTileFrame(tile, frame, isPrimary) {
    if (!tile.videoRel || !tile.imgEl) return;
    const token = ++tile._loadToken;
    if (tile.spinnerEl) tile.spinnerEl.classList.remove("hidden");
    try {
      const url = this.endpoints.frame(tile.videoRel, frame);
      const img = new Image();
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = url;
      });
      if (token !== tile._loadToken) return;        // superseded by a newer seek
      tile.imgEl.src = img.src;
      if (isPrimary) {
        if (frame + 1 < this._frameCount) {
          const pre = new Image();
          pre.src = this.endpoints.frame(tile.videoRel, frame + 1);
        }
        await new Promise(requestAnimationFrame);   // paint barrier for honest pacing
      }
    } catch (_) {
      /* keep the previous frame on error */
    } finally {
      if (token === tile._loadToken && tile.spinnerEl) tile.spinnerEl.classList.add("hidden");
    }
  }

  // ── stepping ──────────────────────────────────────────────
  step(delta) { return this.seek(this._currentFrame + delta); }
  stepSkip(dir) { return this.seek(this._currentFrame + dir * this._skipN); }
  setSkipN(n) { this._skipN = Math.max(1, parseInt(n, 10) || 1); }

  // ── playback ──────────────────────────────────────────────
  setFps(v) { this._fps = clampFps(v, this._fps); }
  setPlayStep(v) { this._playN = clampPlayStep(v, this._playN); }
  setLooping(on) { this._looping = !!on; }
  setPlayDir(dir) { this._playDir = dir < 0 ? -1 : 1; }

  play() {
    if (this._playing) return;
    this._playing = true;
    this._playLoop();
  }
  pause() { this._stop(); }
  togglePlay() { if (this._playing) this.pause(); else this.play(); }

  _stop() {
    if (this._playTimer !== null) { clearTimeout(this._playTimer); this._playTimer = null; }
    this._playing = false;
  }

  async _playLoop() {
    if (!this._playing) return;
    const { frame, stop } = nextFrame({
      current: this._currentFrame, playN: this._playN, playDir: this._playDir,
      lo: 0, hi: Math.max(this._frameCount - 1, 0), looping: this._looping,
    });
    if (stop) { this._stop(); return; }
    const t0 = performance.now();
    await this.seek(frame);
    if (!this._playing) return;
    const elapsed = performance.now() - t0;
    this._playTimer = setTimeout(() => this._playLoop(), frameDelayMs(this._fps, elapsed));
  }

  // ── zoom ──────────────────────────────────────────────────
  setZoom(pct) {
    this._zoom = pct;
    const primary = this.getTile(0);
    if (!primary || !primary.imgEl || !primary.imgEl.naturalWidth) return;
    const baseW = this.mount.clientWidth || primary.imgEl.naturalWidth;
    const view = this.mount.ownerDocument.defaultView || window;
    const maxW = Math.max(baseW, (view.innerWidth || baseW) - 32);
    const { width, marginLeft } = fitViewerSize({ baseW, maxW, zoom: pct });
    this.rowEl.style.width = width + "px";
    this.rowEl.style.marginLeft = marginLeft < 0 ? `${marginLeft}px` : "";
  }

  // ── keyboard ──────────────────────────────────────────────
  _handleKeyDown(e) {
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    const intent = this._resolveKey({ key: e.key, ctrlKey: e.ctrlKey });
    if (!intent) return;
    e.preventDefault();
    if (intent.type === "playPause") this.togglePlay();
    else if (intent.type === "step") this.step(intent.delta);
    else if (intent.type === "stepSkip") this.stepSkip(intent.dir);
  }

  // ── teardown ──────────────────────────────────────────────
  destroy() {
    this._stop();
    this.mount.removeEventListener("keydown", this._onKeyDown);
    this._emit("teardown");
    this._clearTiles();
  }
}
```

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_base.py -q`
Expected: PASS — all parametrized cases green.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/video_viewer.js dlc-3D/tests/test_video_viewer_base.py
git commit -m "feat(dlc-3d viewer-lib): VideoViewer base class (DOM shell over reducers) + contract test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Phase-2b wrap-up — suites green, no consumer touched

**Files:** none (verification only)

- [ ] **Step 1: Run the full viewer unit suite (now incl. event_bus)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs \
  tests/unit/test_viewer_frame_pacer.mjs tests/unit/test_viewer_clip_naming.mjs \
  tests/unit/test_viewer_tile_layout.mjs tests/unit/test_viewer_seek_plan.mjs \
  tests/unit/test_viewer_fit_viewer.mjs tests/unit/test_viewer_controls.mjs \
  tests/unit/test_viewer_event_bus.mjs tests/unit/test_pair_map.mjs
```
Expected: `# fail 0`.

- [ ] **Step 2: Run the VideoViewer contract test**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_base.py -q`
Expected: all green.

- [ ] **Step 3: Confirm no consumer/origin file modified**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~2 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js clip-cutter/`
Expected: empty output.

---

## Phase-2b exit criteria

- `dlc-3D/src/static/components/viewer/video_viewer.js` exports `class VideoViewer` and imports every reducer (no re-implementation).
- `internal/event_bus.mjs` added with passing node tests; full viewer unit suite green.
- `tests/test_video_viewer_base.py` passes (contract).
- No consumer/origin file modified.

**Next:** Phase 3 — feature modules (`StatusNoteTimeline`, `ExtractModule`, `MarkerEditor`, `CurationModule`) that `attach(viewer)` and subscribe to the hook bus. Each gets its own plan when reached. Phase 4 migrates dlc-3D's three forks onto `VideoViewer` + features (smallest-first), guarded by the existing E2E suites. Phase 5 adds the policy doc + enforcement test (generalizing `test_video_viewer_base.py`).
