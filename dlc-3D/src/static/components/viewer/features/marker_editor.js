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
  let frameToken = 0;

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
    const fe = frameEditsOf(editsObj, currentFrame)[dragBp];
    if (fe) flushEdit(currentFrame, dragBp, fe.x, fe.y);
    dragBp = null;
    updateEditBanner();
    updateBpChips();
  }

  function wirePrimaryCanvas(sig) {
    const tile = viewer.getTile(0);
    if (!tile || !tile.canvasEl) return;
    const canvas = tile.canvasEl;
    canvas.style.pointerEvents = "auto"; // base sets the overlay canvas to pointer-events:none
    canvas.addEventListener("mousedown", (e) => {
      if (!overlayEnabled || !isEditable() || e.button !== 0) return;
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
    canvas.addEventListener("mouseup", endDrag, sig);
    canvas.addEventListener("mouseleave", endDrag, sig);
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
      v.on("teardown", () => { for (const d of disposers) d(); ac.abort(); abortPrefetch(); viewer = null; });
    },

    setOverlayEnabled(on) {
      overlayEnabled = !!on;
      if (overlayEnabled) onFrame(currentFrame); else renderAll();
      updateEditBanner();
    },

    async setPrimary(h5Path) {
      abortPrefetch();
      editsObj = {}; // drop prior primary's edits; loadEditCache repopulates when available
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
      abortPrefetch();
      globalThreshold = Number(v);
      for (const l of layers) l.posesCache.clear();
      for (const l of siblingLayers) l.posesCache.clear();
      onFrame(currentFrame);
    },

    selectBp,
    getEditCount: () => editedFrameCount(editsObj),
  };
}
