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
  parsePoseJson, posedBodyparts,
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
  let siblingLayers = [];   // cam-1 layers; [0] = editable primary (when focused), [1+] = comparisons
  let allBodyParts = [];
  let selectedBp = null;
  const hiddenParts = new Set();
  // Per-cam edit store (frame-labeler focused-tile model): edits for the focused
  // cam land in editsByCam[cam] and flush to that cam's own primary .h5.
  const editsByCam = { 0: {}, 1: {} }; // { [cam]: { [frame]: { [bp]: {x,y} } } }; x===null,y===null = deleted
  let focusedCam = 0;       // which cam tile accepts edit input (default cam0 → identical to pre-focus behavior)
  let editingAllowed = true; // master edit gate (consumers may gate editing, e.g. inline's Finalize toggle); default on
  let currentFrame = 0;
  let layerId = 0;
  let prefetchCtrl = null;
  let dragging = false;
  let dragBp = null;
  let dragCam = 0;          // cam whose marker is being dragged
  let didDrag = false;
  let frameToken = 0;

  // ── per-cam accessors (cam0 = layers, cam1 = siblingLayers) ──
  const layersFor = (cam) => (cam === 0 ? layers : siblingLayers);
  const primaryForCam = (cam) => layersFor(cam)[0] || null;
  // A cam is editable when editing is allowed globally and that cam has no
  // comparison layers (parity with the single-cam rule, applied per side).
  const isEditableCam = (cam) => editingAllowed && layersFor(cam).length === 1;
  const editsFor = (cam) => (editsByCam[cam] || (editsByCam[cam] = {}));

  const isEditable = () => isEditableCam(focusedCam);
  const primary = () => layers[0] || null;  // cam0 primary — timeline/prefetch anchor
  const thrOf = (layer) => layerThreshold(layer, globalThreshold, perLayer);
  const curPosesForCam = (cam) => {
    const p = primaryForCam(cam);
    const c = p && p.posesCache.get(currentFrame);
    return c ? c.poses : [];
  };
  const curPoses = () => curPosesForCam(focusedCam);

  function makeLayer(path, label) {
    return { id: "layer_" + layerId++, path, label, posesCache: new Map(), bodyparts: [], errored: false };
  }

  // ── pose fetch + cache + prefetch ──
  // The frame-poses endpoints emit non-finite JSON literals (NaN / Infinity, from
  // numpy) for frames with no/low-confidence detections. The browser's response.json()
  // REJECTS those (invalid JSON), so parse leniently — otherwise one NaN frame would
  // throw and permanently mark the whole layer errored (disabling all rendering).
  async function fetchPosesJson(url, opts) {
    const text = await (await fetch(url, opts)).text();
    return parsePoseJson(text);
  }

  async function fetchLayerFrame(layer, frame) {
    if (!endpoints.poses) return null;
    const key = poseCacheKey(layer.path, thrOf(layer));
    const cached = layer.posesCache.get(frame);
    if (cached && cached.key === key) return cached;
    try {
      const data = await fetchPosesJson(endpoints.poses(layer.path, frame, thrOf(layer)));
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
      const data = await fetchPosesJson(endpoints.posesBatch(p.path, start, count, thrOf(p)),
        { signal: prefetchCtrl.signal });
      for (const [fnStr, fd] of Object.entries(data.frames || {})) {
        p.posesCache.set(parseInt(fnStr, 10), { key, poses: fd.poses || [], n_bodyparts: fd.n_bodyparts || 1 });
      }
    } catch (_) { /* abort/network — non-critical */ } finally {
      prefetchCtrl = null;
    }
  }

  function abortPrefetch() {
    if (prefetchCtrl) { prefetchCtrl.abort(); prefetchCtrl = null; }
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
    // Size the backing store to the img's RENDERED (border-box) size — what the
    // canvas is displayed at (100% of the wrap). offsetWidth/Height (not
    // clientWidth/Height) so backing == displayed exactly: clientWidth excludes
    // the 1px frame border, which would otherwise scale every marker ~1%.
    const w = img.offsetWidth || img.naturalWidth;
    const h = img.offsetHeight || img.naturalHeight;
    if (w) canvas.width = w;
    if (h) canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!overlayEnabled) return;
    const scale = scaleFor(img.naturalWidth, img.naturalHeight, canvas.width, canvas.height);
    const r = markerRadius(markerSize, scale);
    const tileLayers = layersFor(tile.cam);
    // Only the focused tile shows edit overlays + selection ring (frame-labeler
    // focused-tile pattern); each tile reads its OWN cam's edits.
    const editableTile = tile.cam === focusedCam && isEditableCam(tile.cam);
    const fEdits = editableTile ? frameEditsOf(editsFor(tile.cam), frame) : {};
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
        // Non-finite coords (NaN/null from undetected frames) → no marker.
        if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
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
    for (const l of [...layers, ...siblingLayers]) {
      for (const bp of l.bodyparts) if (!seen.has(bp)) { seen.add(bp); set.push(bp); }
    }
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
      chip.innerHTML =
        '<span class="vv-bp-dot"></span>' +
        '<span class="vv-bp-name"></span>' +
        '<svg class="vv-bp-check" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>' +
        '<svg class="vv-bp-eye-slash" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
      chip.querySelector(".vv-bp-name").textContent = bp;
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
    // 'labeled' must mirror what renderTile draws: a bp is labeled only if it has a
    // finite marker at this frame. Undetected bps leak in with NaN→null coords.
    const posed = posedBodyparts(curPoses());
    c.querySelectorAll(".vv-bp-chip").forEach((chip) => {
      const bp = chip.dataset.bp;
      chip.classList.toggle("active", bp === selectedBp);
      chip.classList.toggle("labeled", posed.has(bp));
      chip.classList.toggle("vis-hidden", hiddenParts.has(bp));
    });
  }

  function selectBp(bp) {
    selectedBp = bp;
    const t = viewer && viewer.getTile(focusedCam);
    if (t && t.canvasEl) t.canvasEl.style.cursor = bp ? "crosshair" : "default";
    updateBpChips();
    renderAll();
  }

  // ── edit banner ──
  // Reflects the FOCUSED cam's edits (hidden when that cam has comparison layers,
  // since editing is disabled while comparing).
  function updateEditBanner() {
    if (!els.editBanner) return;
    if (!isEditableCam(focusedCam)) { els.editBanner.classList.add("hidden"); return; }
    const n = editedFrameCount(editsFor(focusedCam));
    els.editBanner.classList.toggle("hidden", n === 0);
    if (els.editCount) els.editCount.textContent = `${n} frame${n !== 1 ? "s" : ""} edited`;
  }

  // ── server flush (per-cam: edits flush to that cam's own primary .h5) ──
  async function flushEdit(cam, frame, bp, x, y) {
    const p = primaryForCam(cam);
    if (!isEditableCam(cam) || !p || !endpoints.saveMarker) return;
    try { await endpoints.saveMarker(buildMarkerEditPayload(p.path, frame, bp, x, y)); } catch (_) { /* edit lives locally */ }
  }
  const flushDelete = (cam, frame, bp) => flushEdit(cam, frame, bp, null, null);

  async function loadEditCache(cam, h5Path) {
    if (!endpoints.editCache) return;
    try {
      const data = await (await fetch(endpoints.editCache(h5Path))).json();
      const obj = {};
      for (const [k, bpEdits] of Object.entries(data.cache || {})) {
        const fn = parseInt(String(k).split("_")[1], 10);
        if (!Number.isNaN(fn)) obj[fn] = bpEdits;
      }
      editsByCam[cam] = obj;
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
    const my = ++frameToken;
    if (!overlayEnabled) { renderAll(); return; }
    await fetchAllForFrame(frame);
    if (my !== frameToken) return; // superseded by a newer seek
    renderAll();
    updateBpChips();
    prefetch(frame);
  }

  // ── canvas editing (primary tile only) ──
  function canvasPos(canvas, e) {
    const rect = canvas.getBoundingClientRect();
    return { cx: e.clientX - rect.left, cy: e.clientY - rect.top };
  }

  function endDrag() {
    if (!dragging) return;
    dragging = false;
    const fe = frameEditsOf(editsFor(dragCam), currentFrame)[dragBp];
    if (fe) flushEdit(dragCam, currentFrame, dragBp, fe.x, fe.y);
    dragBp = null;
    updateEditBanner();
    updateBpChips();
  }

  // Switch which cam tile accepts edit input. Moves the edit cursor, retoggles the
  // .vv-tile-focused class, and redraws so the selection ring + edit overlays follow.
  function setFocusedCam(cam) {
    if (!viewer || cam === focusedCam) return;
    const old = viewer.getTile(focusedCam);
    if (old && old.canvasEl) old.canvasEl.style.cursor = "default";
    focusedCam = cam;
    for (let i = 0; ; i++) {
      const t = viewer.getTile(i);
      if (!t) break;
      if (t.rootEl) t.rootEl.classList.toggle("vv-tile-focused", t.cam === focusedCam);
      if (t.canvasEl && t.cam === focusedCam) {
        t.canvasEl.style.cursor = selectedBp && isEditableCam(cam) ? "crosshair" : "default";
      }
    }
    updateEditBanner();
    updateBpChips();
    renderAll();
  }

  // Wire one tile's overlay canvas for editing. Attached to EVERY tile on each
  // videoLoad; the handlers self-gate on `cam === focusedCam`, so only the focused
  // tile mutates — and each operates on its OWN cam's poses + edits + primary .h5
  // (frame-labeler focused-tile pattern). Clicking an unfocused tile focuses it via
  // the tile-root listener, which (by bubbling) runs AFTER this canvas click's gate
  // returns — so the first click only focuses, the next edits.
  function wireTileCanvas(tile, sig) {
    if (!tile || !tile.canvasEl) return;
    const cam = tile.cam;
    const canvas = tile.canvasEl;
    canvas.style.pointerEvents = "auto"; // base sets the overlay canvas to pointer-events:none

    canvas.addEventListener("mousedown", (e) => {
      if (!overlayEnabled || e.button !== 0 || cam !== focusedCam || !isEditableCam(cam)) return;
      const { cx, cy } = canvasPos(canvas, e);
      const hit = hitTest(curPosesForCam(cam), cx, cy, tileScale(tile), markerSize, frameEditsOf(editsFor(cam), currentFrame), 8);
      if (hit) { dragging = true; dragBp = hit; dragCam = cam; didDrag = false; selectBp(hit); }
    }, sig);
    canvas.addEventListener("mousemove", (e) => {
      if (!dragging || dragCam !== cam) return;
      didDrag = true;
      const { cx, cy } = canvasPos(canvas, e);
      const { x, y } = canvasToVideo(cx, cy, tileScale(tile));
      editsByCam[cam] = setEdit(editsFor(cam), currentFrame, dragBp, x, y);
      renderTile(tile, currentFrame);
    }, sig);
    canvas.addEventListener("mouseup", endDrag, sig);
    canvas.addEventListener("mouseleave", endDrag, sig);
    canvas.addEventListener("click", (e) => {
      if (!overlayEnabled || cam !== focusedCam || !isEditableCam(cam) || !selectedBp) return;
      if (didDrag) { didDrag = false; return; }
      const { cx, cy } = canvasPos(canvas, e);
      const hit = hitTest(curPosesForCam(cam), cx, cy, tileScale(tile), markerSize, frameEditsOf(editsFor(cam), currentFrame), 8);
      if (hit) return; // clicking an existing marker selects via mousedown, not place
      const { x, y } = canvasToVideo(cx, cy, tileScale(tile));
      editsByCam[cam] = setEdit(editsFor(cam), currentFrame, selectedBp, x, y);
      flushEdit(cam, currentFrame, selectedBp, x, y);
      renderTile(tile, currentFrame);
      updateEditBanner();
      updateBpChips();
    }, sig);
    canvas.addEventListener("contextmenu", (e) => {
      if (!overlayEnabled || cam !== focusedCam || !isEditableCam(cam) || !selectedBp) return;
      e.preventDefault();
      editsByCam[cam] = deleteEdit(editsFor(cam), currentFrame, selectedBp);
      flushDelete(cam, currentFrame, selectedBp);
      renderTile(tile, currentFrame);
      updateEditBanner();
      updateBpChips();
    }, sig);

    // Focus-on-click: runs after the canvas click bubbles up (so the first click
    // on an unfocused tile only focuses, it does not place a marker).
    if (tile.rootEl) {
      tile.rootEl.addEventListener("click", () => { if (cam !== focusedCam) setFocusedCam(cam); }, sig);
    }
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
    if (!isEditableCam(focusedCam) || !selectedBp) return;
    const cam = focusedCam;
    if (e.key === "Backspace" || e.key === "Delete") {
      e.preventDefault();
      editsByCam[cam] = deleteEdit(editsFor(cam), currentFrame, selectedBp);
      flushDelete(cam, currentFrame, selectedBp);
      renderAll();
      updateEditBanner();
      updateBpChips();
      return;
    }
    const pose = curPosesForCam(cam).find((p) => p.bp === selectedBp);
    const base = frameEditsOf(editsFor(cam), currentFrame)[selectedBp] || (pose ? { x: pose.x, y: pose.y } : null);
    if (!base) return;
    const moved = nudge(base, e.key, e.shiftKey);
    if (moved) {
      e.preventDefault();
      editsByCam[cam] = setEdit(editsFor(cam), currentFrame, selectedBp, moved.x, moved.y);
      flushEdit(cam, currentFrame, selectedBp, moved.x, moved.y);
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
          // tiles are freshly recreated on load — reset focus to cam0 + re-wire ALL tiles'
          // canvases (each self-gates on focusedCam, so only the focused tile edits)
          focusedCam = 0;
          for (let i = 0; ; i++) {
            const t = v.getTile(i);
            if (!t) break;
            wireTileCanvas(t, sig);
            if (t.rootEl) t.rootEl.classList.toggle("vv-tile-focused", t.cam === focusedCam);
          }
        }),
        v.on("frameChange", (frame) => { onFrame(frame); }),
        v.on("drawTile", (tile, frame) => { renderTile(tile, frame); }),
      ];
      v.mount.addEventListener("keydown", onKeyDown, sig);
      v.on("teardown", () => { for (const d of disposers) d(); ac.abort(); abortPrefetch(); viewer = null; });
    },

    setOverlayEnabled(on) {
      overlayEnabled = !!on;
      if (overlayEnabled) onFrame(currentFrame); else renderAll();
      updateEditBanner();
    },

    async setPrimary(h5Path) {
      abortPrefetch();
      editsByCam[0] = {}; // drop prior cam0 edits; loadEditCache repopulates when available
      layers = [makeLayer(h5Path, "main")];
      await loadLayerInfo(layers[0]);
      recomputeBodyparts();
      rebuildBpChips();
      await loadEditCache(0, h5Path);
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
      editsByCam[1] = {}; // drop prior cam1 edits; loadEditCache repopulates when available
      siblingLayers = h5Path ? [makeLayer(h5Path, "sibling")] : [];
      if (h5Path) {
        await loadLayerInfo(siblingLayers[0]);
        await loadEditCache(1, h5Path); // cam1 is editable when focused → load its edit-cache
      }
      recomputeBodyparts(); // surface cam1's bodyparts for focused-cam editing
      rebuildBpChips();
      updateEditBanner();
      onFrame(currentFrame);
    },

    setFocusedCam,
    getFocusedCam: () => focusedCam,

    // Master edit gate. When off, markers still display (read-only) — no edit
    // overlays, selection ring, or input. Consumers use this for gated-editing
    // workflows (e.g. the inline card's Finalize toggle). Defaults on.
    setEditable(on) {
      editingAllowed = !!on;
      const t = viewer && viewer.getTile(focusedCam);
      if (t && t.canvasEl) {
        t.canvasEl.style.cursor = editingAllowed && selectedBp && isEditableCam(focusedCam) ? "crosshair" : "default";
      }
      updateEditBanner();
      renderAll();
    },
    isEditable: () => isEditableCam(focusedCam),

    setThreshold(v) {
      abortPrefetch();
      globalThreshold = Number(v);
      for (const l of layers) l.posesCache.clear();
      for (const l of siblingLayers) l.posesCache.clear();
      onFrame(currentFrame);
    },

    selectBp,
    // Edit count for a cam (defaults to the focused cam). cam0 default keeps the
    // pre-focus single-cam consumers (viewer_3d) unchanged.
    getEditCount: (cam) => editedFrameCount(editsFor(cam ?? focusedCam)),
  };
}
