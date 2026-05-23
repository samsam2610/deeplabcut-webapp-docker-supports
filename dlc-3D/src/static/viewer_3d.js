// viewer_3d.js — "View Analyzed" card consumer module.
//
// Phase 4b Step 2a (CORE only): thin consumer that composes the shared
// VideoViewer library (player + multi-tile frame-locked seek + sync-cam),
// plus the launcher (content list, Project/Browse tabs, folder browser, the
// three open functions covering the 3 frame modes).
//
// The overlay panel, CSV annotation timeline, and dataset-curation tools are
// STUBBED here — see the TODO(4b-2b/2c/2d) markers below; their DOM stays inert
// until later steps wire markerEditor / statusNoteTimeline / curation glue.
//
// Mirrors the dlc_3d.js (4a) pattern: a VideoViewer instance with injected
// endpoints, an _ensureViewer() builder, a _wireViewerChrome() binder, and a
// sync-cam toggle that reloads with/without the sibling tile while preserving
// the current frame.
"use strict";

import { VideoViewer } from "./components/viewer/video_viewer.js";
import { statusNoteTimeline } from "./components/viewer/features/status_notes.js";
import { markerEditor } from "./components/viewer/features/marker_editor.js";
import { state } from "/static/js/state.js";

// ── Module state ────────────────────────────────────────────────────────────

let _viewer = null;
let _markerEditor = null; // overlay/marker-editing feature (composed in _ensureViewer)
let _overlayPrimaryH5 = null; // the primary .h5 path currently driving the overlay (for Save)

// Frame-mode dispatch state (drives endpoints.frame for the primary tile).
let _vaMode = null; // "video" | "frames" | "browse-video"
let _videoName = null; // video mode: project labeled-video basename
let _frameStem = null; // frames mode: labeled-frame-folder stem
let _frameFiles = []; // frames mode: sorted list of frame filenames
let _browsePath = null; // browse-video mode: absolute video path
let _primaryRel = null; // the videoRel passed to VideoViewer.load() for the primary tile

let _fps = 30;
let _frameCount = 0;
let _siblingAvailable = false; // true once a sibling tile has been discovered for the current selection

// Browse-tab folder navigator state.
let _vaBrowsePath = null;
const _VA_VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg"]);

// ── Element helpers ───────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function _setStatus(msg, isErr = false) {
  const el = $("va3d-status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "fe-extract-status" + (isErr ? " err" : "");
}

// Primary-tile frame URL, dispatched by the current mode — mirrors the old
// _vaFrameUrl exactly (video / browse-video / frames).
function _vaPrimaryFrameUrl(n) {
  if (_vaMode === "browse-video") {
    return `/dlc/project/video-frame-ext/${n}?path=${encodeURIComponent(_browsePath)}`;
  }
  if (_vaMode === "video") {
    return `/dlc/project/video-frame/${encodeURIComponent(_videoName)}/${n}`;
  }
  // frames mode: index into _frameFiles
  return `/dlc/project/frame-image/${encodeURIComponent(_frameStem)}/${encodeURIComponent(_frameFiles[n])}`;
}

// ── VideoViewer composition ─────────────────────────────────────────────────

function _ensureViewer() {
  if (_viewer) return _viewer;
  const mount = $("va3d-viewer-mount");
  if (!mount) return null;

  _viewer = new VideoViewer({
    mount,
    perTileSize: true,
    fps: 30,
    storagePrefix: "va3d",
    endpoints: {
      // Dispatch by primary vs sibling. The primary tile's videoRel equals
      // _primaryRel; for it we return the mode-based URL (matching the old
      // _vaFrameUrl). Any other tile is a sibling camera → the dlc-3d frame
      // endpoint keyed off the sibling's videoRel.
      frame: (videoRel, n) =>
        videoRel === _primaryRel
          ? _vaPrimaryFrameUrl(n)
          : `/dlc-3d/frame?video=${encodeURIComponent(videoRel)}&n=${n}`,
      // Sibling-camera discovery (video / browse-video modes auto-enable sync
      // when a sibling exists — load() probes this when siblingPath===undefined).
      sibling: (videoRel) => `/dlc-3d/sibling-camera?video=${encodeURIComponent(videoRel)}`,
    },
  });

  // Overlay panel — kinematic pose overlay + marker editing (Phase 4b Step 2c).
  // markerEditor renders all visible layers per tile via the viewer's drawTile
  // hook (cam0 editable, cam1 read-only sibling) and flushes each edit to the
  // server edit-cache via saveMarker. Consumer glue below wires the card chrome
  // (toggle, h5 pickers, threshold) to its public API.
  _markerEditor = markerEditor({
    endpoints: {
      poses:      (h5, frame, thr) =>
        `/dlc/viewer/frame-poses/${frame}?h5=${encodeURIComponent(h5)}&threshold=${thr}`,
      posesBatch: (h5, start, count, thr) =>
        `/dlc/viewer/frame-poses-batch?h5=${encodeURIComponent(h5)}&start=${start}&count=${count}&threshold=${thr}`,
      layerInfo:  (h5) => `/dlc/viewer/h5-info?h5=${encodeURIComponent(h5)}`,
      saveMarker: (payload) => fetch("/dlc/viewer/marker-edit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
      editCache:  (h5) => `/dlc/viewer/edit-cache?h5=${encodeURIComponent(h5)}`,
    },
    els: {
      bpChips:   $("va3d-bp-chips"),
      editBanner: $("va3d-marker-edit-banner"),
      editCount:  $("va3d-marker-edit-count"),
    },
    markerSize: 6,
    globalThreshold: 0.6,
    poseWindow: 30,
  });
  _viewer.use(_markerEditor);

  // Overlay consumer glue (toggle, h5 pickers, threshold, save). The bp-chip
  // selection is handled inside markerEditor; the controls below are
  // consumer-owned and persist across viewer rebuilds via _ensureViewer.
  _wireOverlayChrome();

  // CSV status/note timeline (save variant — unlike dlc_3d.js's browse-only use,
  // this card wires saveRow so the status/note inputs can write back). The
  // timeline reads the companion CSV for the current primary video; frame_number
  // maps 1:1 to viewer seek-frames (frameBase 0).
  _viewer.use(statusNoteTimeline({
    endpoints: {
      csv: (videoPath) => `/annotate/csv?path=${encodeURIComponent(videoPath)}`,
      saveRow: (payload) => fetch("/annotate/save-row", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    },
    els: {
      statusCanvas:  $("va3d-status-canvas"),
      noteCanvas:    $("va3d-note-canvas"),
      statusChips:   $("va3d-status-chips"),
      noteChips:     $("va3d-note-chips"),
      statusWrap:    $("va3d-status-bar-wrap"),
      noteWrap:      $("va3d-note-bar-wrap"),
      statusPrev:    $("va3d-status-prev-btn"),
      statusNext:    $("va3d-status-next-btn"),
      notePrev:      $("va3d-note-prev-btn"),
      noteNext:      $("va3d-note-next-btn"),
      statusInput:   $("va3d-status-input"),
      noteInput:     $("va3d-note-input"),
      saveStatusBtn: $("va3d-save-status-btn"),
      saveNoteBtn:   $("va3d-save-note-btn"),
      saveFeedback:  $("va3d-annot-save-status"),
      statusBadge:   $("va3d-meta-frame-status"),
      noteBadge:     $("va3d-meta-frame-note"),
    },
    fps: _fps,
    frameBase: 0,
  }));

  // Metadata-strip reveal glue (consumer-owned — not part of statusNoteTimeline).
  // statusNoteTimeline toggles #va3d-status-bar-wrap / #va3d-note-bar-wrap by
  // content once its async CSV load resolves. There's no "csv-loaded" event, so
  // poll the wrap visibility a few times after videoLoad (covers the fetch
  // latency) to reveal the metadata frame row + update the CSV-info text.
  // Also refresh on frameChange so the per-frame badges stay paired with a
  // visible row.
  _viewer.on("videoLoad", () => {
    _scheduleMetaStripRefresh();
    _refreshOverlayH5Variants();
  });
  _viewer.on("frameChange", () => _updateMetaStrip());

  // TODO(4b-2d): dataset curation — compose curation glue here
  //   (#va3d-curation-*, #va3d-extract-frame-btn, batch add, both-cams,
  //    Finalize toggle).

  _wireViewerChrome(_viewer);
  return _viewer;
}

function _wireViewerChrome(v) {
  const skipN = () => Math.max(1, parseInt($("va3d-skip-n")?.value, 10) || 10);

  // Initialise viewer state from the card's control defaults.
  v.setSkipN(skipN());
  v.setPlayStep($("va3d-play-step")?.value || 1);
  v.setFps($("va3d-play-fps")?.value || 5);

  // Play / pause (with icon swap).
  $("va3d-btn-play")?.addEventListener("click", () => v.togglePlay());
  // Step ∓1.
  $("va3d-btn-prev")?.addEventListener("click", () => v.step(-1));
  $("va3d-btn-next")?.addEventListener("click", () => v.step(1));
  // Multi-frame skip ∓N.
  $("va3d-btn-skip-back")?.addEventListener("click", () => v.step(-skipN()));
  $("va3d-btn-skip-fwd")?.addEventListener("click", () => v.step(skipN()));
  $("va3d-skip-n")?.addEventListener("input", () => v.setSkipN(skipN()));
  // Prevent arrow keys in the skip-N field from bubbling to viewer keynav.
  $("va3d-skip-n")?.addEventListener("keydown", (e) => e.stopPropagation());

  // Playback rate + step.
  $("va3d-play-fps")?.addEventListener("input", (e) => v.setFps(e.target.value));
  $("va3d-play-step")?.addEventListener("input", (e) => v.setPlayStep(e.target.value));

  // Seek slider (1000-step normalized → frame index, matching the old player).
  const seek = $("va3d-seek");
  let _seekDragging = false;
  seek?.addEventListener("mousedown", () => { _seekDragging = true; });
  seek?.addEventListener("touchstart", () => { _seekDragging = true; });
  seek?.addEventListener("input", () => {
    const fc = v.frameCount();
    const n = Math.round((seek.value / 1000) * Math.max(fc - 1, 0));
    v.seek(n);
  });
  seek?.addEventListener("change", () => { _seekDragging = false; });

  // Zoom.
  const zoom = $("va3d-zoom");
  zoom?.addEventListener("input", () => {
    v.setZoom(parseInt(zoom.value, 10) || 100);
    const val = $("va3d-zoom-val");
    if (val) val.textContent = zoom.value + " %";
  });

  // Equalize per-tile sizes.
  $("va3d-equalize-btn")?.addEventListener("click", () => v.equalizeTiles());

  // Sync-cam toggle: reload with/without the sibling tile, preserving the
  // current frame (mirrors dlc_3d.js _setupSyncCamToggle).
  const sync = $("va3d-sync-cam");
  sync?.addEventListener("change", async () => {
    const keepFrame = v.currentFrame();
    // frames mode never has a usable sibling (n is an index, not a video frame).
    const framesMode = _vaMode === "frames";
    await v.load({
      videoPath: _primaryRel,
      frameCount: _frameCount,
      framesMode,
      siblingPath: sync.checked && !framesMode ? undefined : null,
    });
    if (keepFrame > 0) v.seek(keepFrame);
    _applyCamLabels();
  });

  // ── Frame-driven UI updates ──────────────────────────────────────────────
  v.on("videoLoad", ({ frameCount }) => {
    if (seek) { seek.min = 0; seek.max = 1000; seek.value = 0; }
    _updateCounters(0, frameCount);
    _applyCamLabels();
    _updateSyncRow();
  });

  v.on("frameChange", (n) => {
    if (seek && !_seekDragging) {
      seek.value = String(Math.round((n / Math.max(v.frameCount() - 1, 1)) * 1000));
    }
    _updateCounters(n, v.frameCount());
    _swapPlayIcon(v.isPlaying());
  });

  // Keep the play/pause icon in sync even when playback stops on its own (loop end).
  // VideoViewer doesn't emit a dedicated play-state event, so poll on frameChange
  // above and also right after a togglePlay click via a microtask.
  $("va3d-btn-play")?.addEventListener("click", () =>
    Promise.resolve().then(() => _swapPlayIcon(v.isPlaying())),
  );
}

function _updateCounters(n, frameCount) {
  const counter = $("va3d-frame-counter");
  if (counter) counter.textContent = `Frame ${n} / ${frameCount}`;
  const time = $("va3d-time-display");
  if (time) {
    if (_vaMode === "video" || _vaMode === "browse-video") {
      time.textContent = `${(n / Math.max(_fps, 1)).toFixed(3)} s`;
    } else {
      time.textContent = _frameFiles[n] || "";
    }
  }
}

// Metadata-strip reveal glue. statusNoteTimeline reveals the status/note
// bar-wraps by content; mirror that here on the metadata strip: when either
// wrap is visible (CSV had interesting rows), show the per-frame note/status
// row and label the strip "companion CSV loaded"; otherwise hide the row and
// label it "No companion CSV". Consumer-owned (not part of statusNoteTimeline).
function _updateMetaStrip() {
  const statusWrap = $("va3d-status-bar-wrap");
  const noteWrap = $("va3d-note-bar-wrap");
  const visible = (el) => el && el.style.display !== "none";
  const hasCsv = visible(statusWrap) || visible(noteWrap);
  const row = $("va3d-meta-frame-row");
  if (row) row.style.display = hasCsv ? "flex" : "none";
  const info = $("va3d-meta-csv-info");
  if (info) info.textContent = hasCsv ? "companion CSV loaded" : "No companion CSV";
}

// Poll the meta strip a few times after a load() to catch statusNoteTimeline's
// async CSV resolution (it has no completion event). Cheap + idempotent.
function _scheduleMetaStripRefresh() {
  [0, 150, 400, 900].forEach((ms) => setTimeout(_updateMetaStrip, ms));
}

// Re-run the viewer's CSV load for the current selection. statusNoteTimeline
// loads the CSV off the "videoLoad" event, so a frame-preserving reload re-pulls
// it (used by the create-CSV glue once a fresh CSV is written server-side).
async function _reloadCsv() {
  if (!_viewer || !_primaryRel) return;
  const keepFrame = _viewer.currentFrame();
  const framesMode = _vaMode === "frames";
  const sync = $("va3d-sync-cam");
  await _viewer.load({
    videoPath: _primaryRel,
    frameCount: _frameCount,
    framesMode,
    siblingPath: sync?.checked && !framesMode ? undefined : null,
  });
  if (keepFrame > 0) _viewer.seek(keepFrame);
  _applyCamLabels();
}

// Create-CSV glue (consumer-owned — not part of statusNoteTimeline). POSTs a
// new companion CSV for the current primary video, then re-pulls it via the
// viewer reload. Guarded: needs a loaded video (frames mode has no real video
// path, so it's excluded).
async function _vaCreateCsv() {
  const btn = $("va3d-create-csv-btn");
  const fb = $("va3d-csv-create-status");
  if (!_primaryRel || _vaMode === "frames") {
    if (fb) fb.textContent = "Open a video first.";
    return;
  }
  if (btn) btn.disabled = true;
  if (fb) fb.textContent = "Creating…";
  try {
    const resp = await fetch("/annotate/create-csv", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_path: _primaryRel, fps: _fps, frame_count: _frameCount }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || `status ${resp.status}`);
    if (fb) fb.textContent = "Created";
    await _reloadCsv();
  } catch (err) {
    if (fb) fb.textContent = `Error: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function _swapPlayIcon(playing) {
  const play = $("va3d-play-icon");
  const pause = $("va3d-pause-icon");
  if (play) play.classList.toggle("hidden", playing);
  if (pause) pause.classList.toggle("hidden", !playing);
}

// Re-label the viewer's generated tiles with the camera indices (parity with
// the old "Camera N (primary)" / "Camera N (sibling)" labels). Tiles are
// rebuilt on every load(), so this runs after each load.
function _applyCamLabels() {
  if (!_viewer) return;
  const t0 = _viewer.getTile(0);
  if (t0 && t0.labelEl) {
    const idx = (_primaryRel || _videoName || "").match(/_cam(\d+)_/)?.[1];
    t0.labelEl.textContent = idx != null ? `Camera ${idx} (primary)` : "main";
  }
  const t1 = _viewer.getTile(1);
  if (t1 && t1.labelEl) {
    const idx = (t1.videoRel || "").match(/_cam(\d+)_/)?.[1];
    t1.labelEl.textContent = idx != null ? `Camera ${idx} (sibling)` : "sibling";
  }
}

// Reveal the sync-cam label + Equalize button based on whether a sibling tile
// exists, and reflect the checkbox state. Mirrors the old _renderSiblingTile
// visibility behaviour: checkbox checked+enabled when a sibling is present;
// unchecked+disabled (with hint) when none.
function _updateSyncRow() {
  if (!_viewer) return;
  const lbl = $("va3d-sync-cam-label");
  const cb = $("va3d-sync-cam");
  const eq = $("va3d-equalize-btn");
  // VideoViewer.load() auto-mounts the 2nd tile when endpoints.sibling discovers
  // one (video/browse modes; frames mode forces siblingPath null). Latch
  // availability so a user-driven sync-off (which drops the tile) doesn't make
  // us re-disable the checkbox and trap them in the off state.
  const tilesShowSibling = _viewer.tiles.length > 1;
  if (tilesShowSibling) _siblingAvailable = true;
  if (lbl) lbl.style.display = "inline-flex";
  if (_siblingAvailable) {
    if (cb) { cb.checked = tilesShowSibling; cb.disabled = false; }
    if (lbl) lbl.title = "";
    if (eq) eq.classList.toggle("hidden", !tilesShowSibling);
  } else {
    // No sibling discovered for this selection — match the old player: the
    // checkbox is unchecked + disabled with a hint, Equalize hidden.
    if (cb) { cb.checked = false; cb.disabled = true; }
    if (lbl) lbl.title = "no sibling cam detected";
    if (eq) eq.classList.add("hidden");
  }
}

// ── Overlay panel consumer glue (markerEditor chrome) ────────────────────────
//
// markerEditor owns the per-tile rendering (via drawTile), the bp chips, the
// edit banner/count, and per-edit server flush. The controls below are
// consumer-owned: the enable toggle, the primary/comparison h5 pickers, the
// likelihood threshold, and the cache→h5 "Save Adjustments" POST. Wired once in
// _ensureViewer (the controls live in the static card markup and persist across
// viewer rebuilds, so a guard avoids double-binding).

let _overlayChromeWired = false;

function _wireOverlayChrome() {
  if (_overlayChromeWired) return;
  _overlayChromeWired = true;

  // Overlay enable toggle → markerEditor.setOverlayEnabled + reveal controls.
  const toggle = $("va3d-overlay-toggle");
  toggle?.addEventListener("change", () => {
    const on = !!toggle.checked;
    _markerEditor?.setOverlayEnabled(on);
    $("va3d-overlay-controls")?.classList.toggle("hidden", !on);
    $("va3d-bp-list-wrap")?.classList.toggle("hidden", !on);
    const st = $("va3d-overlay-status");
    if (st) st.textContent = on ? "overlay on" : "overlay off";
  });

  // Primary h5 picker → setPrimary + per-cam sibling resolution.
  $("va3d-overlay-primary-select")?.addEventListener("change", (e) => {
    _applyOverlayPrimary(e.target.value);
  });

  // Add comparison → addCompare, then reset the select to its placeholder.
  const addCompare = $("va3d-overlay-add-compare");
  addCompare?.addEventListener("change", () => {
    const val = addCompare.value;
    if (val) _markerEditor?.addCompare(val);
    addCompare.value = "";
  });

  // Likelihood threshold → setThreshold + label.
  const thr = $("va3d-overlay-threshold");
  thr?.addEventListener("input", () => {
    const v = parseFloat(thr.value);
    _markerEditor?.setThreshold(v);
    const lbl = $("va3d-overlay-threshold-val");
    if (lbl) lbl.textContent = v.toFixed(2);
  });

  // Marker size: markerEditor has no setMarkerSize API → update the label only.
  // TODO: needs markerEditor.setMarkerSize to take effect on the rendered markers.
  const ms = $("va3d-overlay-marker-size");
  ms?.addEventListener("input", () => {
    const lbl = $("va3d-overlay-marker-size-val");
    if (lbl) lbl.textContent = ms.value;
  });

  // Show-all / hide-all: markerEditor has no show/hide-all API (visibility is
  // per-chip via double-click). Leave as no-ops to avoid faking the behavior.
  // TODO: needs markerEditor show/hide-all API.
  $("va3d-overlay-parts-all"); // no-op
  $("va3d-overlay-parts-none"); // no-op

  // Save Adjustments: markerEditor flushes each edit to the server edit-cache as
  // it happens; this commits the cache → primary .h5/.csv. Guard on a loaded
  // primary with pending edits.
  $("va3d-save-adjustments-btn")?.addEventListener("click", _vaSaveAdjustments);

  // Discard / Clear Frame: markerEditor exposes no discard or clear-frame API,
  // so leave these as no-ops for now (don't fake a partial reset).
  // TODO: needs markerEditor discard / clear-frame API.
  $("va3d-discard-adjustments-btn"); // no-op
  $("va3d-clear-frame-btn"); // no-op
}

// Populate the primary + add-comparison h5 selects for the current primary
// video, then auto-pick when exactly one variant exists. Called off videoLoad.
async function _refreshOverlayH5Variants() {
  const primarySel = $("va3d-overlay-primary-select");
  const compareSel = $("va3d-overlay-add-compare");
  if (!primarySel || !_primaryRel) return;
  let variants = [];
  try {
    const data = await (await fetch(
      `/dlc/viewer/h5-variants?video=${encodeURIComponent(_primaryRel)}`,
    )).json();
    variants = data.variants || [];
  } catch (_) {
    variants = [];
  }

  // Primary select: placeholder + one option per variant (value=path, text=label).
  primarySel.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = variants.length
    ? "(select primary .h5…)"
    : "(no h5 detected — use Browse)";
  primarySel.appendChild(placeholder);
  variants.forEach((vr) => {
    const opt = document.createElement("option");
    opt.value = vr.path;
    opt.textContent = vr.label;
    primarySel.appendChild(opt);
  });

  // Auto-pick when exactly one variant exists.
  if (variants.length === 1) {
    primarySel.value = variants[0].path;
    await _applyOverlayPrimary(variants[0].path);
  } else {
    _overlayPrimaryH5 = null;
    _repopulateCompareOptions(variants, "");
  }
}

// Repopulate #va3d-overlay-add-compare with every variant except the active
// primary. Placeholder option is always first.
function _repopulateCompareOptions(variants, primaryPath) {
  const compareSel = $("va3d-overlay-add-compare");
  if (!compareSel) return;
  compareSel.innerHTML = "";
  const ph = document.createElement("option");
  ph.value = "";
  ph.textContent = "+ add comparison…";
  compareSel.appendChild(ph);
  (variants || [])
    .filter((vr) => vr.path !== primaryPath)
    .forEach((vr) => {
      const opt = document.createElement("option");
      opt.value = vr.path;
      opt.textContent = vr.label;
      compareSel.appendChild(opt);
    });
}

// Set the markerEditor primary layer, resolve + set the per-cam sibling (cam1),
// and refresh the comparison-options list (excluding the new primary).
async function _applyOverlayPrimary(h5) {
  if (!_markerEditor) return;
  if (!h5) {
    _overlayPrimaryH5 = null;
    return;
  }
  _overlayPrimaryH5 = h5;
  await _markerEditor.setPrimary(h5);

  // Per-cam sibling resolution: ask the dlc-3d analyzed endpoint for the cam1
  // counterpart of this primary h5; set it as the read-only sibling layer.
  try {
    const data = await (await fetch(
      `/dlc-3d/analyzed/sibling-h5?primary_h5=${encodeURIComponent(h5)}&cam=1`,
    )).json();
    _markerEditor.setSibling(data && data.path ? data.path : null);
  } catch (_) {
    _markerEditor.setSibling(null);
  }

  // Refresh the comparison options to exclude the just-selected primary. Re-fetch
  // variants (cheap, cached server-side) so the list stays correct after a
  // primary change.
  try {
    const data = await (await fetch(
      `/dlc/viewer/h5-variants?video=${encodeURIComponent(_primaryRel)}`,
    )).json();
    _repopulateCompareOptions(data.variants || [], h5);
  } catch (_) {
    _repopulateCompareOptions([], h5);
  }
}

// Save Adjustments (consumer glue). markerEditor has written each edit to the
// server edit-cache via saveMarker; this commits the cache → the primary .h5/.csv
// via /dlc/viewer/save-marker-edits. Guarded: needs a primary + pending edits.
async function _vaSaveAdjustments() {
  const btn = $("va3d-save-adjustments-btn");
  if (!_markerEditor || !_overlayPrimaryH5) return;
  if (_markerEditor.getEditCount() === 0) return;
  if (btn) btn.disabled = true;
  try {
    const resp = await fetch("/dlc/viewer/save-marker-edits", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ h5: _overlayPrimaryH5 }),
    });
    const data = await resp.json().catch(() => ({}));
    const st = $("va3d-overlay-status");
    if (!resp.ok || data.error) {
      if (st) st.textContent = `Save failed: ${data.error || resp.status}`;
    } else if (st) {
      st.textContent = "Adjustments saved";
    }
  } catch (err) {
    const st = $("va3d-overlay-status");
    if (st) st.textContent = `Save failed: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Three open functions (mode + state + load) ──────────────────────────────

async function _vaOpenVideo(name) {
  _resetForOpen();
  _vaMode = "video";
  _videoName = name;
  _primaryRel = name;
  const nameEl = $("va3d-selected-name");
  if (nameEl) nameEl.textContent = name;
  try {
    const info = await (await fetch(`/dlc/project/video-info/${encodeURIComponent(name)}`)).json();
    _fps = info.fps || 30;
    _frameCount = info.frame_count || 0;
    // Prefer the absolute path as the primary videoRel so the sibling probe +
    // /dlc-3d/frame endpoint resolve correctly (the old Controller.loadVideo
    // passed _vaCurrentVideoPath || name).
    if (info.abs_path) _primaryRel = info.abs_path;
  } catch (_) {
    _fps = 30; _frameCount = 0;
  }
  // Note: when abs_path is used for _primaryRel, the primary frame URL still
  // dispatches on the "video" mode (basename) since endpoints.frame checks
  // videoRel === _primaryRel — so _vaPrimaryFrameUrl uses _videoName regardless.
  $("va3d-player-section")?.classList.remove("hidden");
  const v = _ensureViewer();
  if (!v) return;
  await v.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode: false, siblingPath: undefined });
}

function _vaOpenFrameFolder(stem, frames) {
  _resetForOpen();
  _vaMode = "frames";
  _frameStem = stem;
  _frameFiles = frames;
  _frameCount = frames.length;
  _fps = 5; // slow playback for sparse labeled frames
  _primaryRel = stem; // frames mode has no real video path; stem identifies the primary
  const nameEl = $("va3d-selected-name");
  if (nameEl) nameEl.textContent = `${stem}/ (${frames.length} labeled frames)`;
  $("va3d-player-section")?.classList.remove("hidden");
  const v = _ensureViewer();
  if (!v) return;
  // frames mode: no sibling (siblingPath: null), framesMode: true.
  return v.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode: true, siblingPath: null });
}

async function _vaOpenBrowseVideo(absPath, name) {
  _resetForOpen();
  _vaMode = "browse-video";
  _browsePath = absPath;
  _primaryRel = absPath;
  const nameEl = $("va3d-selected-name");
  if (nameEl) nameEl.textContent = name;
  try {
    const info = await (await fetch(`/annotate/video-info?path=${encodeURIComponent(absPath)}`)).json();
    _fps = info.fps || 30;
    _frameCount = info.frame_count || 0;
  } catch (_) {
    _fps = 30; _frameCount = 0;
  }
  $("va3d-player-section")?.classList.remove("hidden");
  const v = _ensureViewer();
  if (!v) return;
  await v.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode: false, siblingPath: undefined });
}

// Reset module mode state before opening a new selection. (The VideoViewer
// rebuilds its tiles on each load(), so we only clear our own mode bookkeeping
// and the per-feature panels — STUBBED for now.)
function _resetForOpen() {
  _vaMode = null;
  _videoName = null;
  _frameStem = null;
  _frameFiles = [];
  _browsePath = null;
  _primaryRel = null;
  _fps = 30;
  _frameCount = 0;
  _siblingAvailable = false;
  _setStatus("");
  // CSV meta-strip reset (consumer glue). statusNoteTimeline resets its own
  // chips/bars/badges off each load()'s "videoLoad", so we only clear the
  // consumer-owned metadata strip here.
  const metaRow = $("va3d-meta-frame-row");
  if (metaRow) metaRow.style.display = "none";
  const metaInfo = $("va3d-meta-csv-info");
  if (metaInfo) metaInfo.textContent = "No companion CSV";
  const createFb = $("va3d-csv-create-status");
  if (createFb) createFb.textContent = "";
  // Overlay panel reset (consumer glue). markerEditor re-derives its layers on
  // the next setPrimary, but the consumer-owned chrome (toggle, controls
  // visibility, primary ref, status) must be cleared between selections. The h5
  // selects are repopulated off the next videoLoad via _refreshOverlayH5Variants.
  _overlayPrimaryH5 = null;
  const ovToggle = $("va3d-overlay-toggle");
  if (ovToggle) ovToggle.checked = false;
  _markerEditor?.setOverlayEnabled(false);
  $("va3d-overlay-controls")?.classList.add("hidden");
  $("va3d-bp-list-wrap")?.classList.add("hidden");
  const ovStatus = $("va3d-overlay-status");
  if (ovStatus) ovStatus.textContent = "";
  // TODO(4b-2d): reset curation panel here when wired.
}

// Back button: tear down the viewer and hide the player section, returning to
// the launcher list.
function _vaBack() {
  _viewer?.destroy();
  _viewer = null;
  _markerEditor = null; // torn down with the viewer; _ensureViewer composes a fresh one
  _resetForOpen();
  $("va3d-player-section")?.classList.add("hidden");
  const nameEl = $("va3d-selected-name");
  if (nameEl) nameEl.textContent = "";
}

// ── Launcher: content list ──────────────────────────────────────────────────

async function _vaLoadContent() {
  const list = $("va3d-content-list");
  if (!list) return;
  list.innerHTML = '<p class="explorer-empty">Loading…</p>';
  try {
    const data = await (await fetch("/dlc/project/labeled-content")).json();
    if (data.error) {
      list.innerHTML = `<p class="explorer-empty">${data.error}</p>`;
      return;
    }
    const hasVideos = data.videos && data.videos.length > 0;
    const hasFolders = data.frame_folders && data.frame_folders.length > 0;
    if (!hasVideos && !hasFolders) {
      list.innerHTML =
        '<p class="explorer-empty">No labeled videos or frame folders found. Run "Analyze Video / Frames" with "Create labeled video / frame" enabled.</p>';
      return;
    }
    list.innerHTML = "";

    function _makeItem(svgHtml, name, subtitle, onClick) {
      const item = document.createElement("div");
      item.className = "fe-video-item";
      item.innerHTML = `${svgHtml}<div style="display:flex;flex-direction:column;min-width:0;flex:1"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${name}</span>${subtitle ? `<span style="font-size:.7rem;color:var(--text-dim)">${subtitle}</span>` : ""}</div>`;
      item.addEventListener("click", onClick);
      return item;
    }

    if (hasVideos) {
      const hdr = document.createElement("div");
      hdr.style.cssText =
        "font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);padding:.25rem .3rem .1rem";
      hdr.textContent = "Labeled Videos";
      list.appendChild(hdr);
      data.videos.forEach((v) => {
        const sub = v.size ? Math.round(v.size / 1024 / 1024) + " MB" : "";
        const svg = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><rect x="2" y="2" width="20" height="20" rx="3"/><polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none"/></svg>`;
        list.appendChild(_makeItem(svg, v.name, sub, () => _vaOpenVideo(v.name)));
      });
    }

    if (hasFolders) {
      const hdr = document.createElement("div");
      hdr.style.cssText =
        "font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);padding:.35rem .3rem .1rem";
      hdr.textContent = "Labeled Frame Folders";
      list.appendChild(hdr);
      data.frame_folders.forEach((f) => {
        const sub = f.frame_count + " labeled frames";
        const svg = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
        list.appendChild(_makeItem(svg, f.stem + "/", sub, () => _vaOpenFrameFolder(f.stem, f.frames)));
      });
    }
  } catch (err) {
    list.innerHTML = `<p class="explorer-empty">Error: ${err.message}</p>`;
  }
}

// ── Launcher: Browse-tab folder navigator ────────────────────────────────────

async function _vaRefreshBrowse(path) {
  _vaBrowsePath = path;
  const breadcrumb = $("va3d-browse-breadcrumb");
  const browseList = $("va3d-browse-list");
  if (breadcrumb) breadcrumb.value = path;
  if (!browseList) return;
  browseList.innerHTML = '<p class="explorer-empty">Loading…</p>';

  // Try the dir-with-h5 endpoint; fall back to /fs/ls on failure.
  let data;
  try {
    const res = await fetch(`/dlc/viewer/dir-with-h5?path=${encodeURIComponent(path)}`);
    if (!res.ok) throw new Error(`status ${res.status}`);
    data = await res.json();
    if (data.error) throw new Error(data.error);
  } catch (_newRouteErr) {
    try {
      const d2 = await (await fetch(`/fs/ls?path=${encodeURIComponent(path)}`)).json();
      if (d2.error) { browseList.innerHTML = `<p class="explorer-empty">${d2.error}</p>`; return; }
      const entries = d2.entries || [];
      data = {
        path,
        dirs: entries.filter((e) => e.type === "dir").map((e) => ({ name: e.name })),
        videos: entries
          .filter((e) => e.type === "file" && _VA_VIDEO_EXTS.has(e.name.slice(e.name.lastIndexOf(".")).toLowerCase()))
          .map((e) => ({ name: e.name, has_h5: false, h5_count: 0 })),
      };
    } catch (fbErr) {
      browseList.innerHTML = `<p class="explorer-empty">Error: ${fbErr.message}</p>`;
      return;
    }
  }

  const dirs = data.dirs || [];
  const videos = data.videos || [];
  const hideNoH5 = !!state.vaBrowseHideNoH5;
  const visibleVideos = hideNoH5 ? videos.filter((v) => v.has_h5) : videos;

  if (!dirs.length && !visibleVideos.length) {
    browseList.innerHTML = hideNoH5
      ? '<p class="explorer-empty">No videos with analyzed h5 here. Untick "Hide videos without h5" to show all.</p>'
      : '<p class="explorer-empty">No folders or videos found here.</p>';
    return;
  }

  browseList.innerHTML = "";

  dirs.forEach((d) => {
    const row = document.createElement("div");
    row.className = "fe-video-item";
    row.style.cursor = "pointer";
    row.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>`;
    row.querySelector("span").textContent = d.name + "/";
    row.addEventListener("click", () => _vaRefreshBrowse(path + "/" + d.name));
    browseList.appendChild(row);
  });

  visibleVideos.forEach((v) => {
    const fullPath = path + "/" + v.name;
    const row = document.createElement("div");
    row.className = "fe-video-item";
    row.style.cursor = "pointer";
    row.dataset.hasH5 = v.has_h5 ? "true" : "false";
    const iconOpacity = v.has_h5 ? "1" : "0.45";
    const badge = v.has_h5
      ? `<span style="font-size:.68rem;color:var(--text-dim);margin-left:auto;padding:.05rem .35rem;background:var(--surface);border:1px solid var(--border);border-radius:8px">${v.h5_count} h5</span>`
      : `<span style="font-size:.68rem;color:var(--text-dim);margin-left:auto;font-style:italic">no h5</span>`;
    row.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:${iconOpacity}"><rect x="2" y="2" width="20" height="20" rx="3"/><polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none"/></svg><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;opacity:${iconOpacity === "1" ? "1" : "0.7"}"></span>${badge}`;
    row.querySelector("span").textContent = v.name;
    row.addEventListener("click", () => _vaOpenBrowseVideo(fullPath, v.name));
    browseList.appendChild(row);
  });
}

// Editable address bar: navigate to a dir, or open a pasted video path.
async function _vaNavigateTo(raw) {
  const p = raw.trim();
  if (!p) return;
  const ext = p.slice(p.lastIndexOf(".")).toLowerCase();
  if (_VA_VIDEO_EXTS.has(ext)) {
    const dir = p.substring(0, p.lastIndexOf("/")) || "/";
    const name = p.substring(p.lastIndexOf("/") + 1);
    await _vaRefreshBrowse(dir);
    _vaOpenBrowseVideo(p, name);
  } else {
    _vaRefreshBrowse(p);
  }
}

// ── Launcher wiring (tabs, browse, refresh, back, card open/close) ────────────

function _wireLauncher() {
  // Tab switching.
  const tabProject = $("va3d-tab-project");
  const tabBrowse = $("va3d-tab-browse");
  const tabProjectPanel = $("va3d-tab-project-panel");
  const tabBrowsePanel = $("va3d-tab-browse-panel");

  tabProject?.addEventListener("click", () => {
    tabProject.classList.add("active");
    tabBrowse?.classList.remove("active");
    tabProjectPanel?.classList.remove("hidden");
    tabBrowsePanel?.classList.add("hidden");
  });
  tabBrowse?.addEventListener("click", () => {
    tabBrowse.classList.add("active");
    tabProject?.classList.remove("active");
    tabBrowsePanel?.classList.remove("hidden");
    tabProjectPanel?.classList.add("hidden");
    if (!_vaBrowsePath) {
      const startPath = state.userDataDir || state.dataDir || "/";
      _vaRefreshBrowse(startPath);
    }
  });

  // Browse "up".
  $("va3d-browse-up")?.addEventListener("click", () => {
    if (!_vaBrowsePath) return;
    const parent = _vaBrowsePath.split("/").slice(0, -1).join("/") || "/";
    if (parent !== _vaBrowsePath) _vaRefreshBrowse(parent);
  });

  // Hide-no-h5 toggle.
  const hideNoH5 = $("va3d-browse-hide-no-h5");
  hideNoH5?.addEventListener("change", () => {
    state.vaBrowseHideNoH5 = !!hideNoH5.checked;
    if (_vaBrowsePath) _vaRefreshBrowse(_vaBrowsePath);
  });
  if (hideNoH5) hideNoH5.checked = !!state.vaBrowseHideNoH5;

  // Editable breadcrumb.
  const breadcrumb = $("va3d-browse-breadcrumb");
  breadcrumb?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); _vaNavigateTo(breadcrumb.value); }
    if (e.key === "Escape") { breadcrumb.value = _vaBrowsePath || ""; breadcrumb.blur(); }
  });
  breadcrumb?.addEventListener("paste", () => {
    setTimeout(() => _vaNavigateTo(breadcrumb.value), 0);
  });

  // Back + refresh.
  $("va3d-btn-back")?.addEventListener("click", _vaBack);
  $("va3d-refresh-btn")?.addEventListener("click", _vaLoadContent);

  // Create-CSV (consumer glue). Static listener — the button lives in the card
  // markup and persists across viewer rebuilds; _vaCreateCsv guards when no
  // video is loaded.
  $("va3d-create-csv-btn")?.addEventListener("click", _vaCreateCsv);

  // Card open / close. The #btn-open-view-analyzed trigger is shared with the
  // upstream viewer.js; only wire ours when the va3d card is present.
  const card = $("view-analyzed-3d-card");
  const openBtn = $("btn-open-view-analyzed");
  if (openBtn && card) {
    openBtn.addEventListener("click", () => {
      card.classList.remove("hidden");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      _vaLoadContent();
    });
  }
  $("btn-close-view-analyzed-3d")?.addEventListener("click", () => {
    card?.classList.add("hidden");
    _vaBack();
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  _wireLauncher();
});

// Expose the VideoViewer instance for the co-evolved E2E tests (replaces the
// old window.__va3dController). Resolved lazily — the viewer is created on the
// first open. A getter keeps it current across destroy/rebuild cycles.
Object.defineProperty(window, "__vaViewer", {
  configurable: true,
  get() { return _viewer; },
});
