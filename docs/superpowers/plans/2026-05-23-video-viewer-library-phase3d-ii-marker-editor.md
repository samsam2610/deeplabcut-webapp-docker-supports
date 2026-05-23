# Video-Viewer Library — Phase 3d-ii (MarkerEditor feature) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `MarkerEditor` feature module — multi-layer pose overlay + marker editing — that attaches to a `VideoViewer`. It fetches poses (single + batch prefetch), renders all visible layers per tile, and supports drag/place/right-click-delete/WASD editing of the primary layer (gated to single-layer; editing OFF when comparison layers are active).

**Architecture:** This is the DOM half of MarkerEditor; the pure math/state lives in the node-tested `internal/marker_overlay.mjs` (Phase 3d-i). The feature imports that reducer plus `internal/palette.mjs` + `internal/shapes.mjs` for drawing, and is verified by a pytest static-analysis contract + code review (browser ESM can't run under Node). All endpoints/elements injected; follows the feature-teardown pattern (capture disposers + AbortController, dispose on `"teardown"`).

**Scope (faithful but bounded):** primary tile (cam 0) gets full overlay + editing + comparison layers; sibling tile (cam 1) renders read-only when a sibling layer is set. The dataset-**curation** block and **frame-source-mode** routing (video/frames/browse) are NOT part of MarkerEditor — curation is a later `CurationModule`, mode routing is the consumer's injected `endpoints`.

**Tech Stack:** Vanilla ES modules; pytest regex contract.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.4 MarkerEditor).

**Source of truth (`viewer_3d.js`):** layer model (620-634), pose fetch/cache (1681-1697), batch prefetch (1723-1770), draw (842-872, 1152-1194), hit-test (1240-1253/1335-1353), edit handlers (1413-1522), WASD/Tab/Delete (2561-2613), flush (1356-1381) endpoint `/dlc/viewer/marker-edit` payload `{h5,frame,bp,x,y}`, edit-cache load (1384-1396), edit banner + gate (1295-1320, `_vaIsEditable` = single layer), bp chips (1871-1903). Pose shape `{bp,x,y,lh,color_idx}`; endpoint returns `{poses, n_bodyparts}`.

**Command:**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_marker_editor_feature.py -q   # static; launches no app
```

---

## Task 1: contract test, then the feature module

**Files:**
- Create: `dlc-3D/src/static/components/viewer/features/marker_editor.js`
- Test: `dlc-3D/tests/test_marker_editor_feature.py`

- [ ] **Step 1: Write the failing contract test**

Create `dlc-3D/tests/test_marker_editor_feature.py`:

```python
"""Static-analysis contract for the MarkerEditor feature module (Phase 3d-ii).

Browser ESM cannot import under Node; enforced by regex over source + code review.
The pure overlay/edit math is node-tested separately (test_viewer_marker_overlay.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
ME = ROOT / "src" / "static" / "components" / "viewer" / "features" / "marker_editor.js"


def _src():
    assert ME.is_file(), f"missing marker_editor feature at {ME}"
    return ME.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+markerEditor\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bmarkerEditor\b[^}]*\}", _src()), \
        "must export `markerEditor`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name", [
    "hitTest", "resolvePose", "setEdit", "deleteEdit", "buildMarkerEditPayload",
    "layerThreshold", "poseCacheKey", "prefetchWindow", "allCached", "nudge",
    "nextBodypart", "scaleFor", "markerRadius", "canvasToVideo",
])
def test_imports_overlay_reducer(name):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*marker_overlay\.mjs[\"']", _src()), \
        f"must import {name} from internal/marker_overlay.mjs (no re-implementation)"


def test_imports_palette_and_shapes():
    src = _src()
    assert re.search(r"import\s*\{[^}]*\bpaletteColor\b[^}]*\}\s*from\s*[\"'][^\"']*palette\.mjs[\"']", src), \
        "must import paletteColor from internal/palette.mjs"
    assert re.search(r"import\s*\{[^}]*\b(drawShape|shapeForLayer)\b[^}]*\}\s*from\s*[\"'][^\"']*shapes\.mjs[\"']", src), \
        "must import draw helpers from internal/shapes.mjs"


@pytest.mark.parametrize("event", ["videoLoad", "frameChange", "drawTile"])
def test_subscribes_hook(event):
    src = _src()
    assert f'"{event}"' in src or f"'{event}'" in src, f'must subscribe to the "{event}" hook'


def test_gates_editing_on_single_layer():
    # editing must be disabled when comparison layers are present
    assert re.search(r"isEditable", _src()), "must gate editing via an isEditable() check"


def test_disposes_on_teardown():
    src = _src()
    assert '"teardown"' in src or "'teardown'" in src, "must subscribe to the viewer 'teardown' hook"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/", "/dlc/viewer/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q`
Expected: FAIL — `missing marker_editor feature at ...`.

- [ ] **Step 3: Write the feature module**

Create `dlc-3D/src/static/components/viewer/features/marker_editor.js`:

```js
// MarkerEditor — feature module for VideoViewer.
// Multi-layer pose overlay + marker editing. Fetches poses (single + batch prefetch),
// renders all visible layers per tile (comparison layers under the editable primary;
// sibling tile read-only), and supports drag/place/right-click-delete/WASD editing of the
// primary layer — gated to single-layer (editing is OFF when comparison layers are active).
// Pure math/state lives in marker_overlay.mjs; drawing reuses palette.mjs + shapes.mjs.
// All endpoints/elements injected; follows the feature-teardown pattern.
//
// Usage:
//   const me = markerEditor({
//     endpoints: {
//       poses:      (h5, frame, thr) => url,       // → { poses:[{bp,x,y,lh,color_idx}], n_bodyparts }
//       posesBatch: (h5, start, count, thr) => url,// → { frames: { "<n>": { poses, n_bodyparts } } }
//       layerInfo?: (h5) => url,                    // → { bodyparts:[...] }
//       saveMarker: (payload) => fetchPromise,
//       editCache?: (h5) => url,                    // → { cache: { "frame_<n>": { bp:{x,y} } } }
//     },
//     els: { bpChips?, editBanner?, editCount? },
//     markerSize?: 6, globalThreshold?: 0.6, poseWindow?: 30,
//   });
//   viewer.use(me);
//   me.setOverlayEnabled(true); await me.setPrimary(h5path);  // (consumer drives layer choice)

import {
  scaleFor, canvasToVideo, markerRadius, hitTest, resolvePose,
  setEdit, deleteEdit, frameEditsOf, editedFrameCount, nudge, nextBodypart,
  prefetchWindow, allCached, layerThreshold, poseCacheKey, buildMarkerEditPayload,
} from "../internal/marker_overlay.mjs";
import { paletteColor } from "../internal/palette.mjs";
import { drawShape, shapeForLayer } from "../internal/shapes.mjs";

export function markerEditor(config = {}) {
  const els = config.els || {};
  const endpoints = config.endpoints || {};
  const markerSize = config.markerSize || 6;
  const poseWindow = config.poseWindow || 30;
  const perLayer = false; // v1: single global threshold
  let globalThreshold = config.globalThreshold ?? 0.6;

  let viewer = null;
  let overlayEnabled = false;
  let layers = [];          // cam-0 layers; [0] = editable primary, [1+] = read-only comparisons
  let siblingLayers = [];   // cam-1 read-only layers
  let allBodyParts = [];
  let selectedBp = null;
  const hiddenParts = new Set();
  let editsObj = {};        // { [frame]: { [bp]: {x,y} } }; x===null,y===null = deleted
  let currentFrame = 0;
  let layerId = 0;
  let prefetchCtrl = null;
  let dragging = false;
  let dragBp = null;
  let didDrag = false;

  const isEditable = () => layers.length === 1;             // editing only without comparisons
  const primary = () => layers[0] || null;
  const thrOf = (layer) => layerThreshold(layer, globalThreshold, perLayer);
  const curPoses = () => {
    const p = primary();
    const c = p && p.posesCache.get(currentFrame);
    return c ? c.poses : [];
  };

  function makeLayer(path, label) {
    return { id: "layer_" + layerId++, path, label, posesCache: new Map(), bodyparts: [], errored: false };
  }

  // ── pose fetch + cache + prefetch ──
  async function fetchLayerFrame(layer, frame) {
    if (!endpoints.poses) return null;
    const key = poseCacheKey(layer.path, thrOf(layer));
    const cached = layer.posesCache.get(frame);
    if (cached && cached.key === key) return cached;
    try {
      const data = await (await fetch(endpoints.poses(layer.path, frame, thrOf(layer)))).json();
      if (data.error) { layer.errored = true; return null; }
      const entry = { key, poses: data.poses || [], n_bodyparts: data.n_bodyparts || 1 };
      layer.posesCache.set(frame, entry);
      return entry;
    } catch (_) { layer.errored = true; return null; }
  }

  function visibleLayers(cam) {
    return (cam === 0 ? layers : siblingLayers).filter((l) => !l.errored);
  }

  async function fetchAllForFrame(frame) {
    const jobs = [];
    for (const l of visibleLayers(0)) jobs.push(fetchLayerFrame(l, frame));
    for (const l of visibleLayers(1)) jobs.push(fetchLayerFrame(l, frame));
    await Promise.all(jobs);
  }

  async function prefetch(frame) {
    const p = primary();
    if (prefetchCtrl || !p || !endpoints.posesBatch || !viewer) return;
    const total = viewer.frameCount();
    const key = poseCacheKey(p.path, thrOf(p));
    if (allCached(p.posesCache, frame, poseWindow, total, key)) return;
    const { start, count } = prefetchWindow(frame, poseWindow, total);
    if (count <= 0) return;
    prefetchCtrl = new AbortController();
    try {
      const data = await (await fetch(endpoints.posesBatch(p.path, start, count, thrOf(p)),
        { signal: prefetchCtrl.signal })).json();
      for (const [fnStr, fd] of Object.entries(data.frames || {})) {
        p.posesCache.set(parseInt(fnStr, 10), { key, poses: fd.poses || [], n_bodyparts: fd.n_bodyparts || 1 });
      }
    } catch (_) { /* abort/network — non-critical */ } finally {
      prefetchCtrl = null;
    }
  }

  // ── rendering ──
  function tileScale(tile) {
    return scaleFor(tile.imgEl.naturalWidth, tile.imgEl.naturalHeight, tile.canvasEl.width, tile.canvasEl.height);
  }

  function ring(ctx, cx, cy, r, color, lw) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.stroke();
  }

  function renderTile(tile, frame) {
    if (!tile || !tile.canvasEl || !tile.imgEl) return;
    const canvas = tile.canvasEl;
    const img = tile.imgEl;
    const w = img.clientWidth || img.naturalWidth;
    const h = img.clientHeight || img.naturalHeight;
    if (w) canvas.width = w;
    if (h) canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!overlayEnabled) return;
    const scale = scaleFor(img.naturalWidth, img.naturalHeight, canvas.width, canvas.height);
    const r = markerRadius(markerSize, scale);
    const tileLayers = tile.cam === 0 ? layers : siblingLayers;
    const editableTile = tile.cam === 0 && isEditable();
    const fEdits = editableTile ? frameEditsOf(editsObj, frame) : {};
    // draw comparison layers first (high index → 0) so the primary lands on top
    for (let idx = tileLayers.length - 1; idx >= 0; idx--) {
      const layer = tileLayers[idx];
      if (layer.errored) continue;
      const cached = layer.posesCache.get(frame);
      if (!cached) continue;
      const shape = shapeForLayer(idx);
      const isPrimaryLayer = idx === 0;
      for (const pose of cached.poses) {
        if (hiddenParts.has(pose.bp)) continue;
        let px = pose.x;
        let py = pose.y;
        let edited = false;
        if (isPrimaryLayer && editableTile) {
          const rp = resolvePose(pose, fEdits);
          if (rp.deleted) continue;
          px = rp.x; py = rp.y; edited = rp.edited;
        }
        const cx = Math.round(px * scale.sx);
        const cy = Math.round(py * scale.sy);
        const color = paletteColor(pose.color_idx, cached.n_bodyparts);
        drawShape(shape, ctx, cx, cy, r, color);
        if (isPrimaryLayer && editableTile && edited) ring(ctx, cx, cy, r + 3, "#fff", 1.5);
        if (isPrimaryLayer && editableTile && pose.bp === selectedBp) {
          ring(ctx, cx, cy, r + (edited ? 6 : 3), "#facc15", 2);
        }
      }
    }
  }

  function renderAll() {
    if (!viewer) return;
    for (let i = 0; ; i++) {
      const t = viewer.getTile(i);
      if (!t) break;
      renderTile(t, currentFrame);
    }
  }

  // ── bodypart chips + selection ──
  function recomputeBodyparts() {
    const set = [];
    const seen = new Set();
    for (const l of layers) for (const bp of l.bodyparts) if (!seen.has(bp)) { seen.add(bp); set.push(bp); }
    allBodyParts = set;
    if (!selectedBp && allBodyParts.length) selectedBp = allBodyParts[0];
  }

  function rebuildBpChips() {
    const c = els.bpChips;
    if (!c) return;
    c.innerHTML = "";
    allBodyParts.forEach((bp, idx) => {
      const chip = c.ownerDocument.createElement("button");
      chip.className = "vv-bp-chip";
      chip.dataset.bp = bp;
      chip.textContent = bp;
      chip.style.setProperty("--bp-color", paletteColor(idx, allBodyParts.length));
      chip.addEventListener("click", () => selectBp(bp));
      chip.addEventListener("dblclick", (e) => {
        e.preventDefault();
        if (hiddenParts.has(bp)) hiddenParts.delete(bp); else hiddenParts.add(bp);
        renderAll();
        updateBpChips();
      });
      c.appendChild(chip);
    });
    updateBpChips();
  }

  function updateBpChips() {
    const c = els.bpChips;
    if (!c) return;
    const posed = new Set(curPoses().map((p) => p.bp));
    c.querySelectorAll(".vv-bp-chip").forEach((chip) => {
      const bp = chip.dataset.bp;
      chip.classList.toggle("active", bp === selectedBp);
      chip.classList.toggle("labeled", posed.has(bp));
      chip.classList.toggle("vis-hidden", hiddenParts.has(bp));
    });
  }

  function selectBp(bp) {
    selectedBp = bp;
    const t = viewer && viewer.getTile(0);
    if (t && t.canvasEl) t.canvasEl.style.cursor = bp ? "crosshair" : "default";
    updateBpChips();
    renderAll();
  }

  // ── edit banner ──
  function updateEditBanner() {
    if (!els.editBanner) return;
    if (layers.length > 1) { els.editBanner.classList.add("hidden"); return; } // disabled w/ comparisons
    const n = editedFrameCount(editsObj);
    els.editBanner.classList.toggle("hidden", n === 0);
    if (els.editCount) els.editCount.textContent = `${n} frame${n !== 1 ? "s" : ""} edited`;
  }

  // ── server flush ──
  async function flushEdit(frame, bp, x, y) {
    if (!isEditable() || !primary() || !endpoints.saveMarker) return;
    try { await endpoints.saveMarker(buildMarkerEditPayload(primary().path, frame, bp, x, y)); } catch (_) { /* edit lives locally */ }
  }
  const flushDelete = (frame, bp) => flushEdit(frame, bp, null, null);

  async function loadEditCache(h5Path) {
    if (!endpoints.editCache) return;
    try {
      const data = await (await fetch(endpoints.editCache(h5Path))).json();
      editsObj = {};
      for (const [k, bpEdits] of Object.entries(data.cache || {})) {
        const fn = parseInt(String(k).split("_")[1], 10);
        if (!Number.isNaN(fn)) editsObj[fn] = bpEdits;
      }
      updateEditBanner();
    } catch (_) { /* non-critical */ }
  }

  async function loadLayerInfo(layer) {
    if (!endpoints.layerInfo) return;
    try {
      const data = await (await fetch(endpoints.layerInfo(layer.path))).json();
      layer.bodyparts = data.bodyparts || [];
    } catch (_) { layer.bodyparts = []; }
  }

  // ── frame lifecycle ──
  async function onFrame(frame) {
    currentFrame = frame;
    if (!overlayEnabled) { renderAll(); return; }
    await fetchAllForFrame(frame);
    renderAll();
    updateBpChips();
    prefetch(frame);
  }

  // ── canvas editing (primary tile only) ──
  function canvasPos(canvas, e) {
    const rect = canvas.getBoundingClientRect();
    return { cx: e.clientX - rect.left, cy: e.clientY - rect.top };
  }

  function wirePrimaryCanvas(sig) {
    const tile = viewer.getTile(0);
    if (!tile || !tile.canvasEl) return;
    const canvas = tile.canvasEl;
    canvas.style.pointerEvents = "auto"; // base sets the overlay canvas to pointer-events:none
    canvas.addEventListener("mousedown", (e) => {
      if (!overlayEnabled || !isEditable()) return;
      const { cx, cy } = canvasPos(canvas, e);
      const hit = hitTest(curPoses(), cx, cy, tileScale(tile), markerSize, frameEditsOf(editsObj, currentFrame), 8);
      if (hit) { dragging = true; dragBp = hit; didDrag = false; selectBp(hit); }
    }, sig);
    canvas.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      didDrag = true;
      const { cx, cy } = canvasPos(canvas, e);
      const { x, y } = canvasToVideo(cx, cy, tileScale(tile));
      editsObj = setEdit(editsObj, currentFrame, dragBp, x, y);
      renderTile(tile, currentFrame);
    }, sig);
    canvas.addEventListener("mouseup", () => {
      if (!dragging) return;
      dragging = false;
      const fe = frameEditsOf(editsObj, currentFrame)[dragBp];
      if (fe) flushEdit(currentFrame, dragBp, fe.x, fe.y);
      dragBp = null;
      updateEditBanner();
      updateBpChips();
    }, sig);
    canvas.addEventListener("click", (e) => {
      if (!overlayEnabled || !isEditable() || !selectedBp) return;
      if (didDrag) { didDrag = false; return; }
      const { cx, cy } = canvasPos(canvas, e);
      const hit = hitTest(curPoses(), cx, cy, tileScale(tile), markerSize, frameEditsOf(editsObj, currentFrame), 8);
      if (hit) return; // clicking an existing marker selects via mousedown, not place
      const { x, y } = canvasToVideo(cx, cy, tileScale(tile));
      editsObj = setEdit(editsObj, currentFrame, selectedBp, x, y);
      flushEdit(currentFrame, selectedBp, x, y);
      renderTile(tile, currentFrame);
      updateEditBanner();
      updateBpChips();
    }, sig);
    canvas.addEventListener("contextmenu", (e) => {
      if (!overlayEnabled || !isEditable() || !selectedBp) return;
      e.preventDefault();
      editsObj = deleteEdit(editsObj, currentFrame, selectedBp);
      flushDelete(currentFrame, selectedBp);
      renderTile(tile, currentFrame);
      updateEditBanner();
      updateBpChips();
    }, sig);
  }

  function onKeyDown(e) {
    if (!overlayEnabled) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    if (e.key === "Tab") {
      if (!allBodyParts.length) return;
      e.preventDefault();
      selectBp(nextBodypart(allBodyParts, selectedBp, e.shiftKey));
      return;
    }
    if (!isEditable() || !selectedBp) return;
    if (e.key === "Backspace" || e.key === "Delete") {
      e.preventDefault();
      editsObj = deleteEdit(editsObj, currentFrame, selectedBp);
      flushDelete(currentFrame, selectedBp);
      renderAll();
      updateEditBanner();
      updateBpChips();
      return;
    }
    const pose = curPoses().find((p) => p.bp === selectedBp);
    const base = frameEditsOf(editsObj, currentFrame)[selectedBp] || (pose ? { x: pose.x, y: pose.y } : null);
    if (!base) return;
    const moved = nudge(base, e.key, e.shiftKey);
    if (moved) {
      e.preventDefault();
      editsObj = setEdit(editsObj, currentFrame, selectedBp, moved.x, moved.y);
      flushEdit(currentFrame, selectedBp, moved.x, moved.y);
      renderAll();
      updateEditBanner();
    }
  }

  return {
    attach(v) {
      viewer = v;
      const ac = new AbortController();
      const sig = { signal: ac.signal };
      const disposers = [
        v.on("videoLoad", () => {
          // tiles are freshly recreated on load — re-wire the (new) primary canvas
          wirePrimaryCanvas(sig);
        }),
        v.on("frameChange", (frame) => { onFrame(frame); }),
        v.on("drawTile", (tile, frame) => { renderTile(tile, frame); }),
      ];
      v.mount.addEventListener("keydown", onKeyDown, sig);
      v.on("teardown", () => { for (const d of disposers) d(); ac.abort(); });
    },

    setOverlayEnabled(on) {
      overlayEnabled = !!on;
      if (overlayEnabled) onFrame(currentFrame); else renderAll();
      updateEditBanner();
    },

    async setPrimary(h5Path) {
      layers = [makeLayer(h5Path, "main")];
      await loadLayerInfo(layers[0]);
      recomputeBodyparts();
      rebuildBpChips();
      await loadEditCache(h5Path);
      updateEditBanner();
      onFrame(currentFrame);
    },

    async addCompare(h5Path, label) {
      const layer = makeLayer(h5Path, label || `compare ${layers.length}`);
      layers.push(layer);
      await loadLayerInfo(layer);
      recomputeBodyparts();
      rebuildBpChips();
      updateEditBanner(); // editing now disabled (comparisons present)
      onFrame(currentFrame);
    },

    clearCompare() {
      layers = layers.slice(0, 1);
      recomputeBodyparts();
      rebuildBpChips();
      updateEditBanner();
      onFrame(currentFrame);
    },

    async setSibling(h5Path) {
      siblingLayers = h5Path ? [makeLayer(h5Path, "sibling")] : [];
      if (h5Path) await loadLayerInfo(siblingLayers[0]);
      onFrame(currentFrame);
    },

    setThreshold(v) {
      globalThreshold = Number(v);
      for (const l of layers) l.posesCache.clear();
      for (const l of siblingLayers) l.posesCache.clear();
      onFrame(currentFrame);
    },

    selectBp,
    getEditCount: () => editedFrameCount(editsObj),
  };
}
```

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q`
Expected: PASS — all cases green.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/features/marker_editor.js dlc-3D/tests/test_marker_editor_feature.py
git commit -m "feat(dlc-3d viewer-lib): MarkerEditor feature module + contract test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Phase-3d-ii wrap-up — suites green, no consumer touched

**Files:** none (verification only)

- [ ] **Step 1: Full node unit suite (unchanged — confirm no regression)**

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

- [ ] **Step 2: All contract tests (base + 4 features)**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_base.py tests/test_status_notes_feature.py tests/test_frame_extractor_feature.py tests/test_clip_extractor_feature.py tests/test_marker_editor_feature.py -q`
Expected: all green.

- [ ] **Step 3: Confirm no consumer/origin file modified**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~1 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js dlc-3D/src/static/dlc_3d.js clip-cutter/`
Expected: empty output.

---

## Phase-3d-ii exit criteria

- `features/marker_editor.js` exports `markerEditor`, imports the overlay reducer + palette + shapes (no re-implementation), subscribes to `videoLoad`/`frameChange`/`drawTile`, gates editing via `isEditable()` (single layer), disposes on `teardown`, and hardcodes no endpoint paths.
- `tests/test_marker_editor_feature.py` passes; node unit suite still green.
- No consumer/origin file modified.

**Next:** `CurationModule` (per-frame good/bad judgments + bulk per-camera apply; the inline-analysis curation block). Then Phase 4 — migrate the three forks onto `VideoViewer` + features (smallest-first: 3D-Extract card, then viewer_3d, then inline_analysis_3d), guarded by the existing E2E suites. Phase 5 — policy doc + enforcement test generalizing the per-feature contracts.
