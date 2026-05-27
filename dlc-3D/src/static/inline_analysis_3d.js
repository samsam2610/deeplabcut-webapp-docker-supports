// inline_analysis_3d.js — "3D Inline Analysis" card consumer module.
//
// Thin consumer that composes the shared VideoViewer library (player + multi-
// tile frame-locked seek + sync-cam) with three feature modules — markerEditor
// (kinematic pose overlay + marker editing), statusNoteTimeline (companion-CSV
// status/note bars), plus consumer-owned dataset-curation glue (Extract Frame /
// Add to Dataset / Batch Add) — and the launcher (content list, Project/Browse
// tabs, folder browser, the three open functions covering the 3 frame modes).
//
// Phase 4c: adapted from viewer_3d.js (the structurally-identical "View
// Analyzed" card, Phase 4b) with the card's DOM-id + fn-name renames, PLUS the
// inline-only stereo-analysis glue ported from the old fork: snapshot picker,
// warm session, analyze submit/poll across BOTH cameras, sibling resolution +
// analyze-gating, the Finalize-analysis toggle (gates marker editing via the
// markerEditor master gate) + both-cams range copy, Initialize-file button,
// session cleanup, and nav-button placement.
"use strict";

import { VideoViewer } from "./components/viewer/video_viewer.js";
import { statusNoteTimeline } from "./components/viewer/features/status_notes.js";
import { markerEditor } from "./components/viewer/features/marker_editor.js";
import { clipExtractor } from "./components/viewer/features/clip_extractor.js";
import { coverageRects, coverageFrameRects, nearestCoveredFrame, xToFrame, nextCoveredBucket, bucketToFrame, frameToBucket } from "./components/viewer/internal/coverage_timeline.mjs";
import { pickLatestVariant } from "./components/viewer/internal/pick_latest_variant.mjs";
import { makeKeyframeWindow } from "./keyframe_window_ui.js";
import { clampToBounds } from "./internal/clamp_bounds.mjs";
import { addTag, removeTag } from "./internal/tag_list.mjs";
import { state } from "/static/js/state.js";

// ── Module state ────────────────────────────────────────────────────────────

let _viewer = null;
let _markerEditor = null; // overlay/marker-editing feature (composed in _ensureViewer)
let _overlayPrimaryH5 = null; // the primary .h5 path currently driving the overlay (for Save/Finalize cam0)
let _siblingPrimaryH5 = null; // the resolved cam1 sibling .h5 path (for Finalize cam1)

// Frame-mode dispatch state (drives endpoints.frame for the primary tile).
let _iaMode = null; // "video" | "frames" | "browse-video"
let _videoName = null; // video mode: project labeled-video basename
let _frameStem = null; // frames mode: labeled-frame-folder stem
let _frameFiles = []; // frames mode: sorted list of frame filenames
let _browsePath = null; // browse-video mode: absolute video path
let _primaryRel = null; // the videoRel passed to VideoViewer.load() for the primary tile

let _fps = 30;
let _frameCount = 0;
let _siblingAvailable = false; // true once a sibling tile has been discovered for the current selection

// Finalize-window keyframe state.
let _finalizeKW = null;        // shared keyframe-window controller for the finalize panel
let _clipKW = null;            // shared keyframe-window controller for the clip panel
let _lastFinalizeClip = null;  // { start, n, cams:[{video,avi}] } from the last Finalize-and-extract

let _lockActive = false;          // true while the finalize keyframe is locked (range-confine on)
let _lockRange = { start: 0, end: 0 };  // the confined range mirrored from _finalizeKW.getRange()

// Main timeline canvas state (Task 3: canvas-based seek).
let _coverageBuckets = null;   // 0/1 array; null until Task 4 fetches coverage data
let _coverageFrames = null;    // first covered frame per bucket (-1 = none); for click-to-real-frame
let _redrawSeekTimeline = () => {};  // replaced in _wireViewerChrome with the real draw fn

// Finalize coverage bar state — presence-mode coverage of the _analyzed file.
let _finalizeCoverageBuckets = null;
let _finalizeCoverageFrames = null;
let _redrawFinalizeCoverage = () => {};
let _snTimeline = null;   // statusNoteTimeline feature handle (for .redraw() on resize)

// Task 4: likelihood-filtered coverage cache + debounce timer.
const _coverageCache = new Map(); // keyed by "<h5>:<threshold.toFixed(2)>:<width>"
let _coverageTimer = null;        // debounce handle for threshold changes

// Browse-tab folder navigator state.
let _iaBrowsePath = null;
const _IA_VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg"]);

// ── Element helpers ───────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function _setStatus(msg, isErr = false) {
  const el = $("ia3d-status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "fe-extract-status" + (isErr ? " err" : "");
}

// The cam0 absolute path for the current selection — used by the stereo-analysis
// glue (sibling resolution, analyze submit, init-file). Mirrors the old
// _cam0Path() = _iaCurrentVideoPath || _iaBrowseVideoPath, adapted to the new
// module vars: in video/browse modes _primaryRel is the absolute path.
function _cam0Path() {
  return _primaryRel || _browsePath || null;
}

// Primary-tile frame URL, dispatched by the current mode — mirrors the old
// _iaFrameUrl exactly (video / browse-video / frames).
function _iaPrimaryFrameUrl(n) {
  if (_iaMode === "browse-video") {
    return `/dlc/project/video-frame-ext/${n}?path=${encodeURIComponent(_browsePath)}`;
  }
  if (_iaMode === "video") {
    return `/dlc/project/video-frame/${encodeURIComponent(_videoName)}/${n}`;
  }
  // frames mode: index into _frameFiles
  return `/dlc/project/frame-image/${encodeURIComponent(_frameStem)}/${encodeURIComponent(_frameFiles[n])}`;
}

// ── VideoViewer composition ─────────────────────────────────────────────────

function _ensureViewer() {
  if (_viewer) return _viewer;
  const mount = $("ia3d-viewer-mount");
  if (!mount) return null;

  _viewer = new VideoViewer({
    mount,
    // Document-scoped so shortcuts work whenever this card is open, regardless of
    // which element has focus (the base gates on viewer visibility). Card-scoped
    // would die the moment focus left the card (e.g. clicking the page body).
    keyboardTarget: document,
    perTileSize: true,
    fps: 30,
    storagePrefix: "ia3d",
    endpoints: {
      // Dispatch by primary vs sibling. The primary tile's videoRel equals
      // _primaryRel; for it we return the mode-based URL (matching the old
      // _iaFrameUrl). Any other tile is a sibling camera → the dlc-3d frame
      // endpoint keyed off the sibling's videoRel.
      frame: (videoRel, n) =>
        videoRel === _primaryRel
          ? _iaPrimaryFrameUrl(n)
          : `/dlc-3d/frame?video=${encodeURIComponent(videoRel)}&n=${n}`,
      // Sibling-camera discovery (video / browse-video modes auto-enable sync
      // when a sibling exists — load() probes this when siblingPath===undefined).
      sibling: (videoRel) => `/dlc-3d/sibling-camera?video=${encodeURIComponent(videoRel)}`,
    },
  });

  // Overlay panel — kinematic pose overlay + marker editing. markerEditor
  // renders all visible layers per tile via the viewer's drawTile hook (cam0
  // editable, cam1 read-only sibling unless focused) and flushes each edit to
  // the server edit-cache via saveMarker. Consumer glue below wires the card
  // chrome (toggle, h5 pickers, threshold) to its public API. Editing is gated
  // by the Finalize toggle via setEditable() — default OFF for this card.
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
      bpChips:   $("ia3d-bp-chips"),
      editBanner: $("ia3d-marker-edit-controls"),
      editCount:  $("ia3d-marker-edit-count"),
    },
    markerSize: 4, // Fix D (#3): labeler-parity default (slider still adjusts)
    globalThreshold: 0.6,
    poseWindow: 30,
    autoAdvance: true, // B2: advance to next unlabeled bp after a place (labeler feel)
  });
  _viewer.use(_markerEditor);

  // Editing is OFF by default in this card (the OLD card gated editing on the
  // Finalize toggle: _iaIsEditable() = layers===1 && _ia3dFinalizeEnabled). The
  // Finalize toggle flips setEditable(true).
  _markerEditor.setEditable(false);

  // Overlay consumer glue (toggle, h5 pickers, threshold, save). The bp-chip
  // selection is handled inside markerEditor; the controls below are
  // consumer-owned and persist across viewer rebuilds via _ensureViewer.
  _wireOverlayChrome();

  // CSV status/note timeline (save variant). The timeline reads the companion
  // CSV for the current primary video; frame_number maps 1:1 to viewer
  // seek-frames (frameBase 0).
  _snTimeline = statusNoteTimeline({
    endpoints: {
      csv: (videoPath) => `/annotate/csv?path=${encodeURIComponent(videoPath)}`,
      saveRow: (payload) => fetch("/annotate/save-row", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    },
    els: {
      statusCanvas:  $("ia3d-status-canvas"),
      noteCanvas:    $("ia3d-note-canvas"),
      statusChips:   $("ia3d-status-chips"),
      noteChips:     $("ia3d-note-chips"),
      statusWrap:    $("ia3d-status-bar-wrap"),
      noteWrap:      $("ia3d-note-bar-wrap"),
      statusPrev:    $("ia3d-status-prev-btn"),
      statusNext:    $("ia3d-status-next-btn"),
      notePrev:      $("ia3d-note-prev-btn"),
      noteNext:      $("ia3d-note-next-btn"),
      statusInput:   $("ia3d-status-input"),
      noteInput:     $("ia3d-note-input"),
      saveStatusBtn: $("ia3d-save-status-btn"),
      saveNoteBtn:   $("ia3d-save-note-btn"),
      saveFeedback:  $("ia3d-annot-save-status"),
      statusBadge:   $("ia3d-meta-frame-status"),
      noteBadge:     $("ia3d-meta-frame-note"),
    },
    fps: _fps,
    frameBase: 0,
  });
  _viewer.use(_snTimeline);

  // Clip creation: trim the current frame range → <stem>/clip folder via the
  // dlc-3d backend. The library feature calls extractClip once per cam; remap its
  // payload (start_fn/end_fn) to the backend's (start_frame/n_frames). Enable
  // checkbox is unchecked by default; the panel stays hidden until enabled.
  _viewer.use(clipExtractor({
    storagePrefix: "ia3d",
    defaultFrames: 800,
    endpoints: {
      extractClip: (p) => fetch("/dlc-3d/extract-clip", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          video_path: p.video_path, start_frame: p.start_fn,
          n_frames: (p.end_fn - p.start_fn + 1), postfix: p.postfix,
        }),
      }),
      rename: (p) => fetch("/dlc-3d/extract-clip/rename", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p),
      }),
      del: (p) => fetch("/dlc-3d/extract-clip/delete", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p),
      }),
    },
    els: {
      enable: $("ia3d-clip-enable"), panel: $("ia3d-clip-panel"),
      startInput: $("ia3d-clip-start"), framesInput: $("ia3d-clip-frames"),
      endDisplay: $("ia3d-clip-end"), postfixInput: $("ia3d-clip-postfix"),
      extractBtn: $("ia3d-clip-extract-btn"), renameBtn: $("ia3d-clip-rename-btn"),
      deleteBtn: $("ia3d-clip-delete-btn"), extractSibling: $("ia3d-clip-sibling"),
      statusDisplay: $("ia3d-clip-status"),
    },
  }));
  // Load clip_window persisted setting when the panel is first enabled.
  $("ia3d-clip-enable")?.addEventListener("change", (ev) => { if (ev.target.checked) _clipKW?.load(); });

  // Metadata-strip reveal glue (consumer-owned — not part of statusNoteTimeline).
  // Poll the wrap visibility a few times after videoLoad (covers the CSV fetch
  // latency) to reveal the metadata frame row + update the CSV-info text. Also
  // refresh on frameChange so the per-frame badges stay paired with a visible
  // row. videoLoad also refreshes the overlay h5 variants AND re-resolves the
  // sibling for analyze-gating (replaces the old #ia3d-frame-counter observer).
  _viewer.on("videoLoad", () => {
    _scheduleMetaStripRefresh();
    _refreshOverlayH5Variants();
    _refreshSibling();
    _refreshInitFileBtn();
  });
  _viewer.on("frameChange", () => _updateMetaStrip());

  // Dataset-curation consumer glue: master toggle + Extract Frame / Add to
  // Dataset / Batch Add, with both-cams fan-out in sync mode.
  _wireCurationChrome();

  _wireViewerChrome(_viewer);
  return _viewer;
}

// Draw a coverage bar onto `canvas`: paint covered buckets in markColor, then the
// playhead at the viewer's current frame. (Track bg comes from CSS.)
function _drawCoverageBar(canvas, buckets, frames, markColor) {
  if (!canvas || !_viewer) return;
  const w = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = w;
  const h = canvas.height || 14;
  const fc = _viewer.frameCount();
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  if (buckets && buckets.length) {
    ctx.fillStyle = markColor;
    // Draw marks in FRAME space (positioned by frames[]) so each mark sits exactly
    // where clicking it seeks + where the playhead lands. Fall back to bucket space
    // only if the endpoint didn't supply per-bucket frames.
    const rects = (frames && frames.length)
      ? coverageFrameRects(buckets, frames, fc, w)
      : coverageRects(buckets, w);
    for (const r of rects) ctx.fillRect(r.x, 0, r.w, h);
  }
  if (fc > 0) {
    const x = Math.round((_viewer.currentFrame() / Math.max(fc - 1, 1)) * w);
    ctx.save(); ctx.globalAlpha = 0.85; ctx.fillStyle = "#fff"; ctx.fillRect(x, 0, 2, h); ctx.restore();
  }
}

// Mirror the finalize keyframe-lock into the inline range-confine + red visuals.
// Called whenever the lock checkbox or the range changes.
function _applyLockState() {
  const locked = !!$("ia3d-finalize-lock")?.checked && !!$("ia3d-finalize-toggle")?.checked;
  _lockActive = locked;
  if (locked && _finalizeKW) {
    const r = _finalizeKW.getRange();
    _lockRange = { start: r.start, end: r.end };
  }
  // Red flag above cam0 (normal flow). Hidden unless locked.
  const flag = $("ia3d-lock-flag");
  if (flag) {
    flag.classList.toggle("hidden", !locked);
    if (locked) flag.textContent = `🔒 range-locked · ${_lockRange.start.toLocaleString()}–${_lockRange.end.toLocaleString()}`;
  }
  _drawLockOverlays();
  _refreshAnalyzeEnablement();
}

// Position the red range block + the two dimmed-outside overlays over the seek
// canvas, in fraction-of-width space (matches the playhead math in _drawCoverageBar).
function _drawLockOverlays() {
  const range = $("ia3d-lock-range");
  const dimL = $("ia3d-lock-dim-left");
  const dimR = $("ia3d-lock-dim-right");
  const show = _lockActive && _viewer && _viewer.frameCount() > 1;
  for (const el of [range, dimL, dimR]) if (el) el.classList.toggle("hidden", !show);
  if (!show) return;
  const fc = _viewer.frameCount();
  const last = Math.max(fc - 1, 1);
  const sPct = (_lockRange.start / last) * 100;
  const ePct = (_lockRange.end / last) * 100;
  if (dimL) { dimL.style.left = "0"; dimL.style.width = sPct + "%"; }
  if (dimR) { dimR.style.left = ePct + "%"; dimR.style.right = "0"; dimR.style.width = "auto"; }
  if (range) { range.style.left = sPct + "%"; range.style.width = (ePct - sPct) + "%"; }
}
// Mirror the zoomed video-row geometry (from VideoViewer.setZoom) onto every
// timeline canvas, so the bars span the videos exactly → more pixels/frame =
// finer click precision. Only pin when the row overflows the card (marginLeft<0,
// i.e. zoom>100%); at 100% (or null geometry) reset to the responsive card width.
function _applyTimelineWidth(g) {
  const overflowing = !!(g && g.marginLeft < 0);
  for (const id of ["ia3d-seek-canvas", "ia3d-status-canvas", "ia3d-note-canvas", "ia3d-finalize-coverage"]) {
    const c = $(id);
    if (!c) continue;
    // Restore the template's inline width:100% on reset (clearing to "" would
    // erase that inline declaration → canvas falls back to its backing-store px).
    c.style.width = overflowing ? g.width + "px" : "100%";
    c.style.marginLeft = overflowing ? g.marginLeft + "px" : "";
  }
  _redrawSeekTimeline();
  _redrawFinalizeCoverage();
  if (_snTimeline) _snTimeline.redraw();
  _drawLockOverlays();
}
// Wire click + drag-to-seek on a coverage/seek canvas.
// Wire a coverage canvas for seeking. `getCoverage()` returns {buckets, frames} for
// this canvas (or null). A CLICK on a covered bucket snaps to that bucket's real
// covered frame (frames[bucket]) — the bar is bucket-downsampled, so a single
// labeled frame paints a multi-frame bucket and a raw pixel→frame seek would miss
// it. Dragging stays free-scrub (pixel→frame) for smooth scrubbing.
function _wireSeekCanvas(canvas, getCoverage) {
  if (!canvas) return;
  let dragging = false;
  const free = (e) => {
    const r = canvas.getBoundingClientRect();
    let F = xToFrame(e.clientX - r.left, r.width, _viewer.frameCount());
    if (_lockActive) F = clampToBounds(F, _lockRange.start, _lockRange.end);
    _viewer?.seek(F);
  };
  const snap = (e) => {
    if (!_viewer) return;
    const r = canvas.getBoundingClientRect();
    const fc = _viewer.frameCount();
    let F = xToFrame(e.clientX - r.left, r.width, fc);
    if (_lockActive) F = clampToBounds(F, _lockRange.start, _lockRange.end);
    const cov = getCoverage && getCoverage();
    const buckets = cov && cov.buckets, frames = cov && cov.frames;
    if (buckets && buckets.length && frames && frames.length) {
      // Snap to the nearest real covered frame when the click lands on/near a mark
      // (within ~one bucket); otherwise free-seek so the rest of the bar still scrubs.
      const cf = nearestCoveredFrame(frames, F);
      const bucketFrames = Math.ceil(fc / buckets.length);
      const cfc = _lockActive ? clampToBounds(cf, _lockRange.start, _lockRange.end) : cf;
      if (cf != null && Math.abs(cf - F) <= bucketFrames) { _viewer.seek(cfc); return; }
    }
    _viewer.seek(F);
  };
  canvas.addEventListener("mousedown", (e) => { dragging = true; _viewer?.pause(); snap(e); });
  document.addEventListener("mousemove", (e) => { if (dragging) free(e); });
  document.addEventListener("mouseup", () => { dragging = false; });
}
const _accentColor = () => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#6ee7b7";

function _wireViewerChrome(v) {
  const skipN = () => Math.max(1, parseInt($("ia3d-skip-n")?.value, 10) || 10);

  // Initialise viewer state from the card's control defaults.
  v.setSkipN(skipN());
  v.setPlayStep($("ia3d-play-step")?.value || 1);
  v.setFps($("ia3d-play-fps")?.value || 5);

  // Play/pause forward: pause if already playing forward; otherwise play forward
  // (switching direction if currently playing backward). The button shows pause
  // only while playing forward (see _swapPlayIcon).
  $("ia3d-btn-play")?.addEventListener("click", () => {
    if (v.isPlaying() && v.playDir() > 0) v.pause();
    else { v.setPlayDir(1); v.play(); }
  });
  // Play/pause backward: pause if already playing backward; otherwise play
  // backward (switching direction if currently playing forward). The back button
  // shows pause only while playing backward.
  $("ia3d-btn-play-back")?.addEventListener("click", () => {
    if (v.isPlaying() && v.playDir() < 0) v.pause();
    else { v.setPlayDir(-1); v.play(); }
    Promise.resolve().then(() => _swapPlayIcon(v.isPlaying()));
  });
  // Step ∓1 / multi-frame skip ∓N. When the keyframe is locked, compute the
  // confined target and seek directly (step is unconfined).
  const _confine = (target) => (_lockActive ? clampToBounds(target, _lockRange.start, _lockRange.end) : target);
  $("ia3d-btn-prev")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() - 1)));
  $("ia3d-btn-next")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() + 1)));
  $("ia3d-btn-skip-back")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() - skipN())));
  $("ia3d-btn-skip-fwd")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() + skipN())));
  $("ia3d-skip-n")?.addEventListener("input", () => v.setSkipN(skipN()));
  // Prevent arrow keys in the skip-N field from bubbling to viewer keynav.
  $("ia3d-skip-n")?.addEventListener("keydown", (e) => e.stopPropagation());

  // Skip-size presets (clip-cutter's quick step levels): set skip-N + mark active.
  const _syncSkipPresets = () => {
    const n = skipN();
    document.querySelectorAll("#inline-analysis-3d-card .ia3d-skip-preset").forEach((b) => {
      b.classList.toggle("active", parseInt(b.dataset.n, 10) === n);
    });
  };
  document.querySelectorAll("#inline-analysis-3d-card .ia3d-skip-preset").forEach((b) => {
    b.addEventListener("click", () => {
      const skip = $("ia3d-skip-n");
      if (skip) skip.value = b.dataset.n;
      v.setSkipN(parseInt(b.dataset.n, 10));
      _syncSkipPresets();
    });
  });
  $("ia3d-skip-n")?.addEventListener("input", _syncSkipPresets);
  _syncSkipPresets();

  // Playback rate + step.
  $("ia3d-play-fps")?.addEventListener("input", (e) => v.setFps(e.target.value));
  $("ia3d-play-step")?.addEventListener("input", (e) => v.setPlayStep(e.target.value));

  // Main timeline canvas: dark track + marker-coverage marks + playhead; click/drag to seek.
  const seekCanvas = $("ia3d-seek-canvas");
  _wireSeekCanvas(seekCanvas, () => ({ buckets: _coverageBuckets, frames: _coverageFrames }));
  _redrawSeekTimeline = () => _drawCoverageBar(seekCanvas, _coverageBuckets, _coverageFrames, _accentColor());

  // Finalize coverage canvas: presence-mode coverage of the _analyzed file (amber).
  const finalizeCanvas = $("ia3d-finalize-coverage");
  _wireSeekCanvas(finalizeCanvas, () => ({ buckets: _finalizeCoverageBuckets, frames: _finalizeCoverageFrames }));
  _redrawFinalizeCoverage = () => {
    _drawCoverageBar(finalizeCanvas, _finalizeCoverageBuckets, _finalizeCoverageFrames, "#fbbf24");
    const has = !!(_finalizeCoverageBuckets && _finalizeCoverageBuckets.length);
    const pv = $("ia3d-finalize-prev"), nx = $("ia3d-finalize-next");
    if (pv) pv.disabled = !has;
    if (nx) nx.disabled = !has;
  };
  const _finalizeNav = (dir) => {
    if (!_viewer || !_finalizeCoverageBuckets || !_finalizeCoverageBuckets.length) return;
    const nB = _finalizeCoverageBuckets.length;
    const fc = _viewer.frameCount();
    const b = nextCoveredBucket(_finalizeCoverageBuckets, frameToBucket(_viewer.currentFrame(), fc, nB), dir);
    if (b == null) return;
    _viewer.pause();
    // Seek to the bucket's REAL covered frame; fall back to the centre only if the
    // backend didn't supply per-bucket frames (older response shape).
    const f = (_finalizeCoverageFrames && _finalizeCoverageFrames[b] >= 0)
      ? _finalizeCoverageFrames[b] : bucketToFrame(b, nB, fc);
    _viewer.seek(f);
  };
  $("ia3d-finalize-prev")?.addEventListener("click", () => _finalizeNav(-1));
  $("ia3d-finalize-next")?.addEventListener("click", () => _finalizeNav(1));
  v.on("frameChange", () => _redrawFinalizeCoverage());

  _finalizeKW = makeKeyframeWindow({
    viewer: v,
    panelEl: $("ia3d-finalize-controls"),
    settingKey: "finalize_window",
    els: {
      keyframe: $("ia3d-finalize-keyframe"), lock: $("ia3d-finalize-lock"),
      before: $("ia3d-finalize-before"), after: $("ia3d-finalize-after"),
      length: $("ia3d-finalize-length"), range: $("ia3d-finalize-range"),
    },
    onChange: () => {
      _refreshAnalyzeEnablement();
      if (_lockActive && _finalizeKW) {
        const r = _finalizeKW.getRange();
        _lockRange = { start: r.start, end: r.end };
        _drawLockOverlays();
      }
    },
  });

  _clipKW = makeKeyframeWindow({
    viewer: v,
    panelEl: $("ia3d-clip-panel"),
    settingKey: "clip_window",
    els: {
      keyframe: $("ia3d-clip-keyframe"), lock: $("ia3d-clip-lock"),
      before: $("ia3d-clip-before"), after: $("ia3d-clip-after"),
      length: $("ia3d-clip-length"), range: $("ia3d-clip-range"),
    },
    onChange: (r) => {
      const s = $("ia3d-clip-start"), f = $("ia3d-clip-frames"), e = $("ia3d-clip-end");
      if (s) s.value = r.start;
      if (f) f.value = r.n;
      if (e) e.value = r.end;
    },
  });

  // Frame-jump: click the counter to type an exact frame and Enter to jump
  // (granular seek, mirrors clip-cutter's clickable frame number).
  const counter = $("ia3d-frame-counter");
  const jump = $("ia3d-frame-jump");
  const _closeJump = (doSeek) => {
    if (!jump || jump.classList.contains("hidden")) return;
    if (doSeek) {
      const n = Math.max(0, Math.min(parseInt(jump.value, 10) || 0, Math.max(v.frameCount() - 1, 0)));
      v.seek(n);
    }
    jump.classList.add("hidden");
    if (counter) counter.classList.remove("hidden");
  };
  counter?.addEventListener("click", () => {
    if (!jump || !v.frameCount()) return;
    jump.value = String(v.currentFrame());
    jump.classList.remove("hidden");
    counter.classList.add("hidden");
    jump.focus(); jump.select();
  });
  jump?.addEventListener("keydown", (e) => {
    e.stopPropagation(); // don't let arrows/space reach viewer keynav
    if (e.key === "Enter") _closeJump(true);
    else if (e.key === "Escape") _closeJump(false);
  });
  jump?.addEventListener("blur", () => _closeJump(true));

  // Zoom.
  const zoom = $("ia3d-zoom");
  zoom?.addEventListener("input", () => {
    const g = v.setZoom(parseInt(zoom.value, 10) || 100);
    _applyTimelineWidth(g);
    _drawLockOverlays();
    _refreshCoverageForZoom();   // re-fetch coverage at the new width (1px-precise marks)
    const val = $("ia3d-zoom-val");
    if (val) val.textContent = zoom.value + " %";
  });

  // Equalize per-tile sizes.
  $("ia3d-equalize-btn")?.addEventListener("click", () => v.equalizeTiles());

  // Sync-cam toggle: reload with/without the sibling tile, preserving the
  // current frame (mirrors dlc_3d.js _setupSyncCamToggle).
  const sync = $("ia3d-sync-cam");
  sync?.addEventListener("change", async () => {
    const keepFrame = v.currentFrame();
    // frames mode never has a usable sibling (n is an index, not a video frame).
    const framesMode = _iaMode === "frames";
    await v.load({
      videoPath: _primaryRel,
      frameCount: _frameCount,
      framesMode,
      siblingPath: sync.checked && !framesMode ? undefined : null,
    });
    if (keepFrame > 0) v.seek(keepFrame);
    _applyCamLabels();
    _updateBothCamsVisibility();
  });

  // ── Frame-driven UI updates ──────────────────────────────────────────────
  v.on("videoLoad", ({ frameCount }) => {
    _redrawSeekTimeline();
    _updateCounters(0, frameCount);
    _applyCamLabels();
    _updateSyncRow();
    _updateBothCamsVisibility();
  });

  v.on("frameChange", (n) => {
    if (_lockActive && (n < _lockRange.start || n > _lockRange.end)) {
      v.pause();
      const c = clampToBounds(n, _lockRange.start, _lockRange.end);
      if (c !== n) { v.seek(c); return; }   // re-enters frameChange at the clamped frame
    }
    _redrawSeekTimeline();
    _drawLockOverlays();
    _updateCounters(n, v.frameCount());
    _swapPlayIcon(v.isPlaying());
  });

  // Keep the play/pause icon in sync even when playback stops on its own.
  $("ia3d-btn-play")?.addEventListener("click", () =>
    Promise.resolve().then(() => _swapPlayIcon(v.isPlaying())),
  );

  const help = $("ia3d-help-btn"), helpTip = $("ia3d-help-tooltip");
  help?.addEventListener("click", (e) => { e.stopPropagation(); helpTip?.classList.toggle("hidden"); });
  document.addEventListener("click", () => helpTip?.classList.add("hidden"));
}

function _updateCounters(n, frameCount) {
  const counter = $("ia3d-frame-counter");
  if (counter) counter.textContent = `Frame ${n} / ${frameCount}`;
  const time = $("ia3d-time-display");
  if (time) {
    if (_iaMode === "video" || _iaMode === "browse-video") {
      time.textContent = `${(n / Math.max(_fps, 1)).toFixed(3)} s`;
    } else {
      time.textContent = _frameFiles[n] || "";
    }
  }
}

// Metadata-strip reveal glue. statusNoteTimeline reveals the status/note
// bar-wraps by content; mirror that here on the metadata strip. Consumer-owned.
function _updateMetaStrip() {
  const statusWrap = $("ia3d-status-bar-wrap");
  const noteWrap = $("ia3d-note-bar-wrap");
  const visible = (el) => el && el.style.display !== "none";
  const hasCsv = visible(statusWrap) || visible(noteWrap);
  const row = $("ia3d-meta-frame-row");
  if (row) row.style.display = hasCsv ? "flex" : "none";
  const info = $("ia3d-meta-csv-info");
  if (info) info.textContent = hasCsv ? "companion CSV loaded" : "No companion CSV";
}

// Poll the meta strip a few times after a load() to catch statusNoteTimeline's
// async CSV resolution (it has no completion event). Cheap + idempotent.
function _scheduleMetaStripRefresh() {
  [0, 150, 400, 900].forEach((ms) => setTimeout(_updateMetaStrip, ms));
}

// Re-run the viewer's CSV load for the current selection (used by the create-CSV
// glue once a fresh CSV is written server-side).
async function _reloadCsv() {
  if (!_viewer || !_primaryRel) return;
  const keepFrame = _viewer.currentFrame();
  const framesMode = _iaMode === "frames";
  const sync = $("ia3d-sync-cam");
  await _viewer.load({
    videoPath: _primaryRel,
    frameCount: _frameCount,
    framesMode,
    siblingPath: sync?.checked && !framesMode ? undefined : null,
  });
  if (keepFrame > 0) _viewer.seek(keepFrame);
  _applyCamLabels();
}

// Create-CSV glue (consumer-owned). POSTs a new companion CSV for the current
// primary video, then re-pulls it via the viewer reload.
async function _iaCreateCsv() {
  const btn = $("ia3d-create-csv-btn");
  const fb = $("ia3d-csv-create-status");
  if (!_primaryRel || _iaMode === "frames") {
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

// Show the pause icon on whichever play button matches the current play
// direction (forward → #ia3d-btn-play, backward → #ia3d-btn-play-back); both
// show their play icon when stopped. Previously the pause icon was always the
// forward button's, so playing backward wrongly flipped the forward button.
function _swapPlayIcon(playing) {
  const dir = _viewer ? _viewer.playDir() : 1;
  const fwd = playing && dir > 0;
  const back = playing && dir < 0;
  $("ia3d-play-icon")?.classList.toggle("hidden", fwd);
  $("ia3d-pause-icon")?.classList.toggle("hidden", !fwd);
  $("ia3d-play-back-icon")?.classList.toggle("hidden", back);
  $("ia3d-pause-back-icon")?.classList.toggle("hidden", !back);
}

// Re-label the viewer's generated tiles with the camera indices. Tiles are
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
// exists, and reflect the checkbox state.
function _updateSyncRow() {
  if (!_viewer) return;
  const lbl = $("ia3d-sync-cam-label");
  const cb = $("ia3d-sync-cam");
  const eq = $("ia3d-equalize-btn");
  const tilesShowSibling = _viewer.tiles.length > 1;
  if (tilesShowSibling) _siblingAvailable = true;
  if (lbl) lbl.style.display = "inline-flex";
  if (_siblingAvailable) {
    if (cb) { cb.checked = tilesShowSibling; cb.disabled = false; }
    if (lbl) lbl.title = "";
    if (eq) eq.classList.toggle("hidden", !tilesShowSibling);
  } else {
    if (cb) { cb.checked = false; cb.disabled = true; }
    if (lbl) lbl.title = "no sibling cam detected";
    if (eq) eq.classList.add("hidden");
  }
}

// ── Overlay panel consumer glue (markerEditor chrome) ────────────────────────

let _overlayChromeWired = false;

function _wireOverlayChrome() {
  if (_overlayChromeWired) return;
  _overlayChromeWired = true;

  // Overlay enable toggle → markerEditor.setOverlayEnabled + reveal controls + coverage.
  // B2 (Bug-1): on turning the view ON, if no primary is selected yet, auto-pick the
  // LATEST h5 variant (pickLatestVariant over the current dropdown options) and render.
  const toggle = $("ia3d-overlay-toggle");
  toggle?.addEventListener("change", async () => {
    const on = !!toggle.checked;
    _markerEditor?.setOverlayEnabled(on);
    $("ia3d-overlay-controls")?.classList.toggle("hidden", !on);
    $("ia3d-bp-list-wrap")?.classList.toggle("hidden", !on);
    const st = $("ia3d-overlay-status");
    if (st) st.textContent = on ? "overlay on" : "overlay off";
    if (on && !_overlayPrimaryH5) {
      const variants = await _fetchOverlayH5Variants();
      const latest = _pickLatestKinematic(variants);   // latest non-_analyzed model (fallback to _analyzed if sole)
      if (latest && latest.path) {
        const sel = $("ia3d-overlay-primary-select");
        if (sel) sel.value = latest.path;
        await _applyOverlayPrimary(latest.path);   // sets primary + sibling + arms editing + coverage
      }
    }
    _refreshCoverage();
  });

  // Primary h5 picker → setPrimary + per-cam sibling resolution.
  $("ia3d-overlay-primary-select")?.addEventListener("change", (e) => {
    _applyOverlayPrimary(e.target.value);
  });

  // Likelihood threshold → setThreshold + label + coverage refresh (debounced).
  const thr = $("ia3d-overlay-threshold");
  thr?.addEventListener("input", () => {
    const v = parseFloat(thr.value);
    _markerEditor?.setThreshold(v);
    const lbl = $("ia3d-overlay-threshold-val");
    if (lbl) lbl.textContent = v.toFixed(2);
    _refreshCoverageDebounced();
  });

  // Marker size → markerEditor.setMarkerSize (re-renders) + label.
  const ms = $("ia3d-overlay-marker-size");
  ms?.addEventListener("input", () => {
    _markerEditor?.setMarkerSize(parseInt(ms.value, 10));
    const lbl = $("ia3d-overlay-marker-size-val");
    if (lbl) lbl.textContent = ms.value;
  });

  // Show names → markerEditor.setShowNames (all names vs hover-only).
  const showNames = $("ia3d-overlay-show-names");
  showNames?.addEventListener("change", () => _markerEditor?.setShowNames(!!showNames.checked));

  // Show-all / hide-all: markerEditor has no show/hide-all API. No-ops.
  $("ia3d-overlay-parts-all"); // no-op
  $("ia3d-overlay-parts-none"); // no-op

  // Save Adjustments: markerEditor flushes each edit to the server edit-cache as
  // it happens; this commits the cache → primary .h5/.csv for BOTH cams.
  $("ia3d-save-adjustments-btn")?.addEventListener("click", _iaSaveAdjustments);

  // Lock-BP checkbox → markerEditor.setLockBp. When checked, placing re-places the
  // same bodypart (no auto-advance) — used to correct a marker. (`L` is the keyframe
  // range-lock, so this is a checkbox, not a shortcut.)
  const lockBp = $("ia3d-lock-bp");
  lockBp?.addEventListener("change", () => _markerEditor?.setLockBp(!!lockBp.checked));

  // Discard / Clear Frame: markerEditor exposes no discard/clear-frame API. No-ops.
  $("ia3d-discard-adjustments-btn"); // no-op
  $("ia3d-clear-frame-btn"); // no-op
}

// Fetch the current primary video's h5 variants (array; [] on error / no video).
// Returns ALL variants — including the `<stem>_analyzed.h5` curated output — so it
// stays SELECTABLE in the dropdown (a video whose only h5 is `_analyzed` must still be
// viewable). The `_analyzed` exclusion happens only in the AUTO-PICK (_pickLatestKinematic),
// per #1: don't auto-pick `_analyzed` as the "latest kinematic model".
async function _fetchOverlayH5Variants() {
  if (!_primaryRel) return [];
  try {
    const data = await (await fetch(
      `/dlc/viewer/h5-variants?video=${encodeURIComponent(_primaryRel)}`,
    )).json();
    return data.variants || [];
  } catch (_) {
    return [];
  }
}

// Auto-pick the latest KINEMATIC model (#1): the `_analyzed` curated output is the
// Finalize destination, not a model, so prefer the latest non-`_analyzed` variant —
// but fall back to `_analyzed` when it's the only h5, so the view still shows markers
// instead of nothing (the prior "exclude from the list" approach left an empty dropdown
// → no primary → no bodypart chips).
function _pickLatestKinematic(variants) {
  const all = variants || [];
  const kinematic = all.filter((vr) => !/_analyzed\.h5$/i.test(vr.path || ""));
  return pickLatestVariant(kinematic.length ? kinematic : all);
}

// Populate the primary h5 select for the current primary video (placeholder + one
// option per variant). Called off videoLoad. Does NOT auto-pick — the overlay-toggle
// ON handler picks the latest variant when the user turns the kinematics view on
// (Bug-1 clean switch). This card has no add-comparison dropdown (removed 2026-05-21).
async function _refreshOverlayH5Variants() {
  const primarySel = $("ia3d-overlay-primary-select");
  if (!primarySel || !_primaryRel) return;
  // Source the dropdown options through the fetch-only helper so the `_analyzed`
  // curated output (filtered there — Fix A #1) never appears as a kinematic model.
  const variants = await _fetchOverlayH5Variants();

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

  // Bug-1 clean switch: populate the dropdown ONLY — do NOT auto-pick on videoLoad.
  // The user turns the kinematics view on (overlay toggle) to load + render the
  // latest variant. Leave the selection on the placeholder + clear the active primary.
  primarySel.value = "";
  _overlayPrimaryH5 = null;
}

// Stereo-analysis render refresh (ported from the old analyzeBtn handler's
// _iaDiscoverVariants call). After an analysis completes, re-pull the h5
// variants for the cam0 video — this auto-picks the freshly-written primary and
// resolves the cam1 sibling via _applyOverlayPrimary.
async function _iaDiscoverVariants(_cam0) {
  await _refreshOverlayH5Variants();
}

// After an analysis run, re-establish the overlay primary to the just-written LATEST
// variant. The clean-switch repopulate (via _iaDiscoverVariants AND the _viewer.load
// videoLoad) clears the dropdown selection + _overlayPrimaryH5, and the overlay is
// already on during analysis so the toggle-change auto-pick won't fire — without this
// the model is left "unloaded" (markers linger on the stale layer; coverage no-ops on
// the null primary). Cache-bust first so the fresh setPrimary + coverage re-fetch the
// new poses + timeline. Call at the END of the analyze done-handlers, after the reload.
async function _reloadPrimaryAfterAnalysis() {
  _coverageCache.clear();
  const latest = _pickLatestKinematic(await _fetchOverlayH5Variants());
  const sel = $("ia3d-overlay-primary-select");
  if (latest && sel) {
    sel.value = latest.path;
    await _applyOverlayPrimary(latest.path);   // fresh setPrimary + sibling + arms editing + _refreshCoverage
  } else {
    _markerEditor?.invalidatePoses();
    _refreshCoverage();
  }
}

// Reserve the bp chip list's MAX height so per-frame checkmark toggles (which
// change chip width → re-wrap) can't reflow the layout and jump everything below.
// Measure with all checkmarks forced visible (widest), then pin min-height.
function _reserveBpChipHeight() {
  const c = $("ia3d-bp-chips");
  if (!c) return;
  c.style.minHeight = "";              // reset to measure the natural tallest wrap
  c.classList.add("ia3d-measuring");   // all checkmarks shown → widest chips
  const h = c.offsetHeight;
  c.classList.remove("ia3d-measuring");
  if (h > 0) c.style.minHeight = h + "px";
}

// Set the markerEditor primary layer (cam0), resolve + set the per-cam sibling
// (cam1), and stash both resolved paths for Save / Finalize.
async function _applyOverlayPrimary(h5) {
  if (!_markerEditor) return;
  if (!h5) {
    _overlayPrimaryH5 = null;
    _siblingPrimaryH5 = null;
    _markerEditor.setSibling(null);
    return;
  }
  _overlayPrimaryH5 = h5;
  await _markerEditor.setPrimary(h5);
  _reserveBpChipHeight();

  // Per-cam sibling resolution: ask the dlc-3d analyzed endpoint for the cam1
  // counterpart of this primary h5; set it as the (editable-when-focused)
  // sibling layer. Stash the resolved path for the Finalize cam1 source.
  try {
    const data = await (await fetch(
      `/dlc-3d/analyzed/sibling-h5?primary_h5=${encodeURIComponent(h5)}&cam=1`,
    )).json();
    _siblingPrimaryH5 = data && data.path ? data.path : null;
    _markerEditor.setSibling(_siblingPrimaryH5);
  } catch (_) {
    _siblingPrimaryH5 = null;
    _markerEditor.setSibling(null);
  }
  // B1 (2026-05-24): marker editing no longer hard-gates on the overlay being
  // enabled — setEditable(true) makes markers render + edits live on its own. So
  // when a primary h5 + bodypart are resolved and Finalize is checked, just re-arm
  // the edit master gate (this also handles the first-open race where _ensureViewer's
  // setEditable(false) ran after _resetForOpen's setEditable(true)). The overlay
  // toggle stays a manual show/hide convenience.
  if ($("ia3d-finalize-toggle")?.checked) {
    _markerEditor.setEditable(true);
  }
  _refreshCoverage();
}

// Fetch likelihood-filtered marker-coverage for the active primary h5 + current
// threshold, cache by (h5, threshold), and redraw the main timeline. No-op unless
// the overlay is on with a primary h5.
async function _refreshCoverage() {
  const on = $("ia3d-overlay-toggle")?.checked;
  if (!on || !_overlayPrimaryH5) { _coverageBuckets = null; _coverageFrames = null; _redrawSeekTimeline(); return; }
  const thr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
  const w = Math.max(200, Math.round($("ia3d-seek-canvas")?.getBoundingClientRect().width || 600));
  const key = `${_overlayPrimaryH5}:${thr.toFixed(2)}:${w}`;
  if (_coverageCache.has(key)) {
    const c = _coverageCache.get(key);
    _coverageBuckets = c.buckets; _coverageFrames = c.frames; _redrawSeekTimeline(); return;
  }
  try {
    const data = await (await fetch(
      `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(_overlayPrimaryH5)}&threshold=${thr}&buckets=${w}`,
    )).json();
    const entry = { buckets: data.buckets || [], frames: data.frames || [] };
    _coverageCache.set(key, entry);
    // still the active request? (h5 + threshold + width all unchanged)
    const curThr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
    const curW = Math.max(200, Math.round($("ia3d-seek-canvas")?.getBoundingClientRect().width || 600));
    if (`${_overlayPrimaryH5}:${curThr.toFixed(2)}:${curW}` === key) {
      _coverageBuckets = entry.buckets; _coverageFrames = entry.frames; _redrawSeekTimeline();
    }
  } catch (_) { /* leave timeline without coverage */ }
}

function _refreshCoverageDebounced() {
  if (_coverageTimer) clearTimeout(_coverageTimer);
  _coverageTimer = setTimeout(_refreshCoverage, 200);
}

let _zoomCovTimer = null;
// On zoom the canvases resize; re-fetch BOTH coverage bars at the new (wider)
// width so the bucket resolution tracks the displayed width → marks stay 1px and
// stop bleeding onto unlabeled frames. Debounced to coalesce slider drags.
function _refreshCoverageForZoom() {
  if (_zoomCovTimer) clearTimeout(_zoomCovTimer);
  _zoomCovTimer = setTimeout(() => { _refreshCoverage(); _refreshFinalizeCoverage(); }, 200);
}

// Coverage of the canonical _analyzed file (presence, no threshold) for the
// finalize bar. Resolves the _analyzed h5 via analysis-file/status; always
// refetches on its triggers (toggle-on, after each finalize-add) — the file
// changes and the backend cache is mtime-keyed.
async function _refreshFinalizeCoverage() {
  const on = $("ia3d-finalize-toggle")?.checked;
  const cam0Video = _cam0Path();
  const _clear = () => { _finalizeCoverageBuckets = null; _finalizeCoverageFrames = null; _redrawFinalizeCoverage(); };
  if (!on || !cam0Video) { _clear(); return; }
  try {
    const st = await (await fetch(`/dlc/project/analysis-file/status?video_path=${encodeURIComponent(cam0Video)}`)).json();
    if (!st.initialized || !st.h5_path) { _clear(); return; }
    const w = Math.max(200, Math.round($("ia3d-finalize-coverage")?.getBoundingClientRect().width || 600));
    const data = await (await fetch(
      `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(st.h5_path)}&mode=presence&buckets=${w}`,
    )).json();
    _finalizeCoverageBuckets = data.buckets || [];
    _finalizeCoverageFrames = data.frames || [];
    _redrawFinalizeCoverage();
  } catch (_) { _clear(); }
}

// Save Adjustments (consumer glue). markerEditor has written each edit to the
// server edit-cache via saveMarker; this commits the cache → the primary .h5/.csv
// for BOTH cams (cam0 = _overlayPrimaryH5, cam1 = _siblingPrimaryH5) via
// /dlc/viewer/save-marker-edits. Guarded: needs a primary + pending edits.
async function _iaSaveAdjustments() {
  const btn = $("ia3d-save-adjustments-btn");
  if (!_markerEditor || !_overlayPrimaryH5) return;
  const n0 = _markerEditor.getEditCount(0);
  const n1 = _markerEditor.getEditCount(1);
  if (n0 === 0 && n1 === 0) return;
  if (btn) btn.disabled = true;
  const st = $("ia3d-overlay-status");
  try {
    const targets = [];
    if (n0 > 0 && _overlayPrimaryH5) targets.push(_overlayPrimaryH5);
    if (n1 > 0 && _siblingPrimaryH5) targets.push(_siblingPrimaryH5);
    let anyErr = false;
    for (const h5 of targets) {
      const resp = await fetch("/dlc/viewer/save-marker-edits", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ h5 }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.error) anyErr = true;
    }
    if (st) st.textContent = anyErr ? "Save failed (one or more cams)" : "Adjustments saved";
  } catch (err) {
    if (st) st.textContent = `Save failed: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Dataset-curation consumer glue ───────────────────────────────────────────

let _curationChromeWired = false;
let _curationMsgTimer = null;

function _curStatus(msg, isErr = false) {
  const el = $("ia3d-curation-status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "fe-extract-status" + (isErr ? " err" : "");
  if (_curationMsgTimer) clearTimeout(_curationMsgTimer);
  if (msg && !isErr) {
    _curationMsgTimer = setTimeout(() => { el.textContent = ""; }, 4000);
  }
}

// Reveal #ia3d-both-cams-label only when a sibling tile is mounted and curation
// is enabled.
function _updateBothCamsVisibility() {
  const both = $("ia3d-both-cams-label");
  if (!both) return;
  const curationOn = !!$("ia3d-curation-toggle")?.checked;
  const syncOn = !!_viewer && _viewer.tiles.length > 1;
  both.style.display = (syncOn && curationOn) ? "inline-flex" : "none";
}

// True when extraction should fan out to both cams: "both cams" ticked + sibling.
function _shouldDoubleUp() {
  const cb = $("ia3d-both-cams");
  return !!(cb && cb.checked && _viewer && _viewer.tiles.length > 1);
}

// Per-mode single-cam curator body: browse mode sends the absolute video_path,
// project-video mode sends the basename.
function _curatorBody(frameNum) {
  const n = (frameNum !== undefined) ? frameNum : _viewer.currentFrame();
  const body = { frame_number: n };
  if (_iaMode === "browse-video" && _browsePath) body.video_path = _browsePath;
  else if (_iaMode === "video" && _videoName) body.video_name = _videoName;
  return body;
}

// Atomic both-cams extraction → /dlc-3d/save-frame.
async function _saveFramePair(frameNum) {
  const t0 = _viewer?.getTile(0);
  const t1 = _viewer?.getTile(1);
  if (!t0?.videoRel || !t1?.videoRel) return { ok: false, error: "missing tile videoRel" };
  try {
    const r = await fetch("/dlc-3d/save-frame", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        primary_video: t0.videoRel,
        primary_frame_number: frameNum,
        extract_sibling: true,
        sibling_video: t1.videoRel,
        sibling_frame_number: frameNum,
      }),
    });
    if (!r.ok) {
      let err;
      try { err = (await r.clone().json()).error; } catch { err = await r.text(); }
      return { ok: false, error: err || `HTTP ${r.status}` };
    }
    return { ok: true, body: await r.json() };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

// Format a /dlc-3d/save-frame response body into a user status line.
function _pairSavedMsg(data) {
  const saved = (data.saved || []).join(", ");
  const skipped = (data.skipped || []).length;
  const folder = data.session_folder || "";
  const calNote = data.calibration_copied ? " + calibration" : "";
  const dup = (n) => `${n} duplicate${n !== 1 ? "s" : ""}`;
  if (saved && skipped) return `Saved ${saved} (${folder}${calNote}); ${dup(skipped)} skipped`;
  if (saved) return `Saved ${saved} (${folder}${calNote})`;
  return `All frames already extracted (${dup(skipped)})`;
}

function _wireCurationChrome() {
  if (_curationChromeWired) return;
  _curationChromeWired = true;

  // Master toggle → reveal controls + sync the both-cams label.
  const toggle = $("ia3d-curation-toggle");
  toggle?.addEventListener("change", () => {
    $("ia3d-curation-controls")?.classList.toggle("hidden", !toggle.checked);
    _updateBothCamsVisibility();
  });

  // Extract Frame: raw PNG(s) into labeled-data (no CSV entry).
  const extractBtn = $("ia3d-extract-frame-btn");
  extractBtn?.addEventListener("click", async () => {
    if (!_iaMode || _iaMode === "frames") {
      _curStatus("No video loaded — open a video first.", true);
      return;
    }
    extractBtn.disabled = true;
    _curStatus("Extracting…");
    if (_shouldDoubleUp()) {
      const res = await _saveFramePair(_viewer.currentFrame());
      if (res.ok) _curStatus(_pairSavedMsg(res.body || {}));
      else _curStatus(`Extract failed: ${res.error || "unknown"}`, true);
    } else {
      try {
        const r = await fetch("/dlc/curator/extract-frame", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(_curatorBody()),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
        _curStatus(data.duplicate
          ? `Already extracted: ${data.saved}`
          : `Saved ${data.saved} (${data.folder}, #${data.frame_count})`);
      } catch (err) {
        _curStatus(`Extract failed: ${err.message}`, true);
      }
    }
    extractBtn.disabled = false;
  });

  // Add to Dataset.
  const addBtn = $("ia3d-add-to-dataset-btn");
  addBtn?.addEventListener("click", async () => {
    if (!_iaMode || _iaMode === "frames") {
      _curStatus("No video loaded — open a video first.", true);
      return;
    }
    addBtn.disabled = true;
    if (_shouldDoubleUp()) {
      _curStatus("Saving frame pair…");
      const res = await _saveFramePair(_viewer.currentFrame());
      if (res.ok) _curStatus(_pairSavedMsg(res.body || {}));
      else _curStatus(`Save failed: ${res.error || "unknown"}`, true);
    } else {
      _curStatus("Adding to dataset…");
      try {
        const r = await fetch("/dlc/curator/add-to-dataset", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(_curatorBody()),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
        const h5note = data.h5_updated ? " + H5" : "";
        _curStatus(data.duplicate
          ? `Already in dataset: ${data.saved}`
          : `Added ${data.saved} to CSV${h5note} (${data.frame_count} frames)`);
      } catch (err) {
        _curStatus(`Failed: ${err.message}`, true);
      }
    }
    addBtn.disabled = false;
  });

  // Batch Add.
  const batchBtn = $("ia3d-batch-add-btn");
  batchBtn?.addEventListener("click", async () => {
    if (!_iaMode || _iaMode === "frames") {
      _curStatus("No video loaded — open a video first.", true);
      return;
    }
    const count = Math.max(1, parseInt($("ia3d-batch-count")?.value, 10) || 10);
    const step = Math.max(1, parseInt($("ia3d-batch-step")?.value, 10) || 30);
    batchBtn.disabled = true;
    const doubleUp = _shouldDoubleUp();
    let added = 0, dupes = 0, errors = 0;
    const start = _viewer.currentFrame();
    let lastFrame = start, aborted = false;
    for (let i = 0; i < count; i++) {
      const frameNum = start + i * step;
      if (frameNum >= _frameCount) break;
      lastFrame = frameNum;
      _curStatus(`Batch adding… ${i + 1}/${count} (frame ${frameNum})`);
      await _viewer.seek(frameNum);
      if (doubleUp) {
        const res = await _saveFramePair(frameNum);
        if (!res.ok) {
          errors++;
          _curStatus(`Batch aborted at frame ${frameNum}: ${res.error || ""}`, true);
          aborted = true;
          break;
        }
        const data = res.body || {};
        added += (data.saved || []).length;
        dupes += (data.skipped || []).length;
      } else {
        try {
          const r = await fetch("/dlc/curator/add-to-dataset", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(_curatorBody(frameNum)),
          });
          const data = await r.json();
          if (!r.ok) { errors++; continue; }
          if (data.duplicate) dupes++; else added++;
        } catch (_) { errors++; }
      }
    }
    if (lastFrame !== _viewer.currentFrame()) await _viewer.seek(lastFrame);
    batchBtn.disabled = false;
    if (!aborted) {
      const parts = [];
      if (added) parts.push(`${added} added`);
      if (dupes) parts.push(`${dupes} duplicate${dupes !== 1 ? "s" : ""}`);
      if (errors) parts.push(`${errors} error${errors !== 1 ? "s" : ""}`);
      _curStatus(`Batch done: ${parts.join(", ") || "nothing to add"}.`, errors > 0 && added === 0);
    }
  });
}

// ── Per-project quick-tags (postfix / status / note) ─────────────────────────

// Per-project quick-tags controller. Three independent lists (postfix/status/note),
// each persisted under its own ui-setting key. Click a pill → REPLACE the bound
// input's value. × removes; "+ tag" adds the input's current value (or a prompt).
function _makeQuickTags({ settingKey, containerId, inputId }) {
  let tags = [];
  let saveTimer = null;
  const container = () => $(containerId);
  const input = () => $(inputId);

  const save = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      fetch("/dlc/project/ui-setting", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: settingKey, value: JSON.stringify(tags) }),
      }).catch(() => {});   // best-effort; in-memory list stays intact on failure
    }, 400);
  };

  const render = () => {
    const c = container();
    if (!c) return;
    c.innerHTML = "";
    for (const t of tags) {
      const pill = document.createElement("span");
      pill.className = "ia3d-ptag";
      pill.appendChild(document.createTextNode(t + " "));
      const x = document.createElement("span");
      x.className = "x"; x.textContent = "×";
      x.addEventListener("click", (ev) => { ev.stopPropagation(); tags = removeTag(tags, t); render(); save(); });
      pill.appendChild(x);
      pill.addEventListener("click", () => { const el = input(); if (el) { el.value = t; el.dispatchEvent(new Event("input", { bubbles: true })); } });
      c.appendChild(pill);
    }
    const add = document.createElement("span");
    add.className = "ia3d-ptag ia3d-ptag-add"; add.textContent = "+ tag";
    add.addEventListener("click", () => {
      const el = input();
      const cur = el && el.value.trim();
      const raw = cur || window.prompt("New tag:");
      const next = addTag(tags, raw);
      if (next.length !== tags.length) { tags = next; render(); save(); }
    });
    c.appendChild(add);
  };

  const load = async () => {
    try {
      const d = await (await fetch(`/dlc/project/ui-setting?key=${encodeURIComponent(settingKey)}`)).json();
      const parsed = d && d.value ? JSON.parse(d.value) : [];
      tags = Array.isArray(parsed) ? parsed : [];
    } catch (_) { tags = []; }
    render();
  };

  return { load, render };
}

let _postfixTags = null, _statusTags = null, _noteTags = null;
function _wireQuickTags() {
  _postfixTags = _makeQuickTags({ settingKey: "postfix_tags", containerId: "ia3d-postfix-tags", inputId: "ia3d-finalize-clip-postfix" });
  _statusTags  = _makeQuickTags({ settingKey: "status_tags",  containerId: "ia3d-status-tags",  inputId: "ia3d-status-input" });
  _noteTags    = _makeQuickTags({ settingKey: "note_tags",    containerId: "ia3d-note-tags",    inputId: "ia3d-note-input" });
}

// Load + render all three per-project tag lists. Called on each video open.
function _loadAllQuickTags() {
  _postfixTags?.load();
  _statusTags?.load();
  _noteTags?.load();
}

// ── Three open functions (mode + state + load) ──────────────────────────────

async function _iaOpenVideo(name) {
  _resetForOpen();
  _iaMode = "video";
  _videoName = name;
  _primaryRel = name;
  const nameEl = $("ia3d-selected-name");
  if (nameEl) nameEl.textContent = name;
  try {
    const info = await (await fetch(`/dlc/project/video-info/${encodeURIComponent(name)}`)).json();
    _fps = info.fps || 30;
    _frameCount = info.frame_count || 0;
    if (info.abs_path) _primaryRel = info.abs_path;
  } catch (_) {
    _fps = 30; _frameCount = 0;
  }
  $("ia3d-player-section")?.classList.remove("hidden");
  const v = _ensureViewer();
  if (!v) return;
  _loadAllQuickTags();
  await v.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode: false, siblingPath: undefined });
}

function _iaOpenFrameFolder(stem, frames) {
  _resetForOpen();
  _iaMode = "frames";
  _frameStem = stem;
  _frameFiles = frames;
  _frameCount = frames.length;
  _fps = 5; // slow playback for sparse labeled frames
  _primaryRel = stem; // frames mode has no real video path; stem identifies the primary
  const nameEl = $("ia3d-selected-name");
  if (nameEl) nameEl.textContent = `${stem}/ (${frames.length} labeled frames)`;
  $("ia3d-player-section")?.classList.remove("hidden");
  const v = _ensureViewer();
  if (!v) return;
  _loadAllQuickTags();
  return v.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode: true, siblingPath: null });
}

async function _iaOpenBrowseVideo(absPath, name) {
  _resetForOpen();
  _iaMode = "browse-video";
  _browsePath = absPath;
  _primaryRel = absPath;
  const nameEl = $("ia3d-selected-name");
  if (nameEl) nameEl.textContent = name;
  try {
    const info = await (await fetch(`/annotate/video-info?path=${encodeURIComponent(absPath)}`)).json();
    _fps = info.fps || 30;
    _frameCount = info.frame_count || 0;
  } catch (_) {
    _fps = 30; _frameCount = 0;
  }
  $("ia3d-player-section")?.classList.remove("hidden");
  const v = _ensureViewer();
  if (!v) return;
  _loadAllQuickTags();
  await v.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode: false, siblingPath: undefined });
}

// Reset module mode state before opening a new selection.
function _resetForOpen() {
  _iaMode = null;
  _videoName = null;
  _frameStem = null;
  _frameFiles = [];
  _browsePath = null;
  _primaryRel = null;
  _fps = 30;
  _frameCount = 0;
  _siblingAvailable = false;
  _setStatus("");
  // CSV meta-strip reset.
  const metaRow = $("ia3d-meta-frame-row");
  if (metaRow) metaRow.style.display = "none";
  const metaInfo = $("ia3d-meta-csv-info");
  if (metaInfo) metaInfo.textContent = "No companion CSV";
  const createFb = $("ia3d-csv-create-status");
  if (createFb) createFb.textContent = "";
  // Overlay panel reset (Task 4: also clear coverage cache + buckets on video switch).
  _coverageBuckets = null;
  _coverageFrames = null;
  _finalizeCoverageBuckets = null;
  _finalizeCoverageFrames = null;
  _applyTimelineWidth(null);   // reset any pinned timeline widths from a prior zoom
  _coverageCache.clear();
  _overlayPrimaryH5 = null;
  _siblingPrimaryH5 = null;
  const ovToggle = $("ia3d-overlay-toggle");
  if (ovToggle) ovToggle.checked = false;
  _markerEditor?.setOverlayEnabled(false);
  // Bug-1 clean switch: drop the previous video's markerEditor layer + sibling so a
  // switch never leaves the prior layer's poses live (setPrimary(null) empties the
  // layers + chips + re-renders nothing). Overlay off + no primary ⇒ nothing draws
  // even though editing is armed (no cached poses to draw, no chips).
  _markerEditor?.setPrimary(null);
  const ovPrimarySel = $("ia3d-overlay-primary-select");
  if (ovPrimarySel) ovPrimarySel.value = "";   // back to the placeholder
  $("ia3d-overlay-controls")?.classList.add("hidden");
  $("ia3d-bp-list-wrap")?.classList.add("hidden");
  const _bc = $("ia3d-bp-chips"); if (_bc) _bc.style.minHeight = "";
  const ovStatus = $("ia3d-overlay-status");
  if (ovStatus) ovStatus.textContent = "";
  // Curation panel reset.
  const curToggle = $("ia3d-curation-toggle");
  if (curToggle) curToggle.checked = false;
  $("ia3d-curation-controls")?.classList.add("hidden");
  const bothLabel = $("ia3d-both-cams-label");
  if (bothLabel) bothLabel.style.display = "none";
  _curStatus("");
  // Finalize panel reset (inline-only). Finalize is ON by default (spec): re-check
  // the toggle + reveal controls + enable editing. setEditable(true) here mirrors
  // what the toggle change handler would do; we do NOT fire the change event because
  // there is no viewer frame yet and overlay auto-enable is premature.
  const finToggle = $("ia3d-finalize-toggle");
  if (finToggle) finToggle.checked = true;   // Finalize is on by default (spec)
  $("ia3d-finalize-controls")?.classList.remove("hidden");
  const finStatus = $("ia3d-finalize-status");
  if (finStatus) { finStatus.textContent = ""; finStatus.className = "fe-extract-status"; }
  _markerEditor?.setEditable(true);
  _lastFinalizeClip = null;
  _finalizeClipBtnsEnabled(false);
  _refreshAnalyzeEnablement();
  // Clip panel reset: collapse on new video selection.
  const clipEnable = $("ia3d-clip-enable");
  if (clipEnable) clipEnable.checked = false;
  $("ia3d-clip-panel")?.classList.add("hidden");
  // Keyframe-lock reset: a new video is never range-locked. The lock checkbox is
  // unlocked by _finalizeKW.load() (setLock(false)); mirror that into the inline
  // confine state + hide the flag/overlays.
  _lockActive = false;
  _applyLockState();
}

// Back button: tear down the viewer and hide the player section.
function _iaBack() {
  _viewer?.destroy();
  _viewer = null;
  _markerEditor = null; // torn down with the viewer; _ensureViewer composes a fresh one
  _resetForOpen();
  $("ia3d-player-section")?.classList.add("hidden");
  const nameEl = $("ia3d-selected-name");
  if (nameEl) nameEl.textContent = "";
}

// ── Launcher: content list ──────────────────────────────────────────────────

async function _iaLoadContent() {
  const list = $("ia3d-content-list");
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
        list.appendChild(_makeItem(svg, v.name, sub, () => _iaOpenVideo(v.name)));
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
        list.appendChild(_makeItem(svg, f.stem + "/", sub, () => _iaOpenFrameFolder(f.stem, f.frames)));
      });
    }
  } catch (err) {
    list.innerHTML = `<p class="explorer-empty">Error: ${err.message}</p>`;
  }
}

// ── Launcher: Browse-tab folder navigator ────────────────────────────────────

async function _iaRefreshBrowse(path) {
  _iaBrowsePath = path;
  const breadcrumb = $("ia3d-browse-breadcrumb");
  const browseList = $("ia3d-browse-list");
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
          .filter((e) => e.type === "file" && _IA_VIDEO_EXTS.has(e.name.slice(e.name.lastIndexOf(".")).toLowerCase()))
          .map((e) => ({ name: e.name, has_h5: false, h5_count: 0 })),
      };
    } catch (fbErr) {
      browseList.innerHTML = `<p class="explorer-empty">Error: ${fbErr.message}</p>`;
      return;
    }
  }

  const dirs = data.dirs || [];
  const videos = data.videos || [];
  const hideNoH5 = !!state.iaBrowseHideNoH5;
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
    row.addEventListener("click", () => _iaRefreshBrowse(path + "/" + d.name));
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
    row.addEventListener("click", () => _iaOpenBrowseVideo(fullPath, v.name));
    browseList.appendChild(row);
  });
}

// Editable address bar: navigate to a dir, or open a pasted video path.
async function _iaNavigateTo(raw) {
  const p = raw.trim();
  if (!p) return;
  const ext = p.slice(p.lastIndexOf(".")).toLowerCase();
  if (_IA_VIDEO_EXTS.has(ext)) {
    const dir = p.substring(0, p.lastIndexOf("/")) || "/";
    const name = p.substring(p.lastIndexOf("/") + 1);
    await _iaRefreshBrowse(dir);
    _iaOpenBrowseVideo(p, name);
  } else {
    _iaRefreshBrowse(p);
  }
}

// ── Launcher wiring (tabs, browse, refresh, back, card open/close) ────────────

function _wireLauncher() {
  // Tab switching.
  const tabProject = $("ia3d-tab-project");
  const tabBrowse = $("ia3d-tab-browse");
  const tabProjectPanel = $("ia3d-tab-project-panel");
  const tabBrowsePanel = $("ia3d-tab-browse-panel");

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
    if (!_iaBrowsePath) {
      const startPath = state.userDataDir || state.dataDir || "/";
      _iaRefreshBrowse(startPath);
    }
  });

  // Browse "up".
  $("ia3d-browse-up")?.addEventListener("click", () => {
    if (!_iaBrowsePath) return;
    const parent = _iaBrowsePath.split("/").slice(0, -1).join("/") || "/";
    if (parent !== _iaBrowsePath) _iaRefreshBrowse(parent);
  });

  // Hide-no-h5 toggle.
  const hideNoH5 = $("ia3d-browse-hide-no-h5");
  hideNoH5?.addEventListener("change", () => {
    state.iaBrowseHideNoH5 = !!hideNoH5.checked;
    if (_iaBrowsePath) _iaRefreshBrowse(_iaBrowsePath);
  });
  if (hideNoH5) hideNoH5.checked = !!state.iaBrowseHideNoH5;

  // Editable breadcrumb.
  const breadcrumb = $("ia3d-browse-breadcrumb");
  breadcrumb?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); _iaNavigateTo(breadcrumb.value); }
    if (e.key === "Escape") { breadcrumb.value = _iaBrowsePath || ""; breadcrumb.blur(); }
  });
  breadcrumb?.addEventListener("paste", () => {
    setTimeout(() => _iaNavigateTo(breadcrumb.value), 0);
  });

  // Back + refresh.
  $("ia3d-btn-back")?.addEventListener("click", _iaBack);
  $("ia3d-refresh-btn")?.addEventListener("click", _iaLoadContent);

  // Create-CSV (consumer glue). Static listener.
  $("ia3d-create-csv-btn")?.addEventListener("click", _iaCreateCsv);

  // Card open / close.
  const card = $("inline-analysis-3d-card");
  const openBtn = $("btn-open-inline-analysis-3d");
  if (openBtn && card) {
    openBtn.addEventListener("click", () => {
      card.classList.remove("hidden");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      _iaLoadContent();
    });
  }
  $("btn-close-inline-analysis-3d")?.addEventListener("click", () => {
    card?.classList.add("hidden");
    _iaBack();
  });
}

// ════════════════════════════════════════════════════════════════════════════
//  STEREO ANALYSIS DISPATCH (inline-only glue, ported from the old fork) —
//  run DLC on BOTH cameras (cam0 + cam1) over the same [start, n] range via the
//  main webapp's warm inline-analysis worker, then re-discover + render via the
//  shared viewer's overlay path. Module-level fns (not an IIFE) so the
//  viewer-chrome videoLoad hook can call _refreshSibling / _refreshInitFileBtn.
// ════════════════════════════════════════════════════════════════════════════

let _snapKey = null;     // warm-session key
let _siblingPath = null; // resolved cam1 absolute path (or null) for analyze
let _statusPoll = null;  // session warm-status poll interval

const _ia3dEl = {
  snapSel:    () => $("ia3d-snapshot"),
  shuffle:    () => $("ia3d-shuffle"),
  tsi:        () => $("ia3d-trainingsetindex"),
  batch:      () => $("ia3d-batch-size"),
  frames:     () => $("ia3d-frames-per-click"),
  keepWarm:   () => $("ia3d-keep-warm-seconds"),
  saveCsv:    () => $("ia3d-save-csv"),
  analyzeBtn: () => $("ia3d-btn-analyze-range"),
  lastRun:    () => $("ia3d-last-run-status"),
  warmInd:    () => $("ia3d-warm-indicator"),
  refreshSnap:() => $("ia3d-refresh-snapshots"),
  siblingEl:  () => $("ia3d-sibling-status"),
};

// ── Snapshot loader (main webapp API; needs same active project) ──
async function _loadSnapshots() {
  const snapSel = _ia3dEl.snapSel();
  try {
    const r = await fetch("/dlc/project/snapshots");
    const data = await r.json();
    if (!snapSel) return;
    snapSel.innerHTML = "";
    if (data.error) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "(activate the DLC project in the main webapp)";
      snapSel.appendChild(o); return;
    }
    const latest = document.createElement("option");
    latest.value = data.latest_rel_path || "-1";
    latest.textContent = data.latest_label ? `Latest — ${data.latest_label}` : "Latest (from config)";
    snapSel.appendChild(latest);
    (data.snapshots || []).forEach((s) => {
      const o = document.createElement("option");
      o.value = s.rel_path;
      const it = s.iteration != null ? `  ·  iter ${s.iteration.toLocaleString()}` : "";
      const sh = s.shuffle   != null ? `  ·  sh${s.shuffle}` : "";
      o.textContent = `${s.label}${it}${sh}`;
      snapSel.appendChild(o);
    });
  } catch (e) { /* silent */ }
}

// ── Sibling resolution + Analyze-button gating ───────────────────
// Ported from the old _refreshSibling. Reads the current cam0 path from
// _primaryRel/_browsePath (via _cam0Path). Driven by the viewer's "videoLoad"
// event (wired in _ensureViewer) instead of the old #ia3d-frame-counter
// MutationObserver.
async function _refreshSibling() {
  const siblingEl = _ia3dEl.siblingEl();
  const analyzeBtn = _ia3dEl.analyzeBtn();
  if (!siblingEl || !analyzeBtn) return;
  const cam0 = _cam0Path();
  _siblingPath = null;
  if (!cam0) {
    siblingEl.textContent = "Pick a cam0 video to resolve its sibling.";
    analyzeBtn.disabled = true;
    return;
  }
  try {
    const r = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(cam0)}`);
    const d = await r.json();
    if (d.sibling_video_path) {
      _siblingPath = d.sibling_video_path;
      siblingEl.textContent = `Sibling: ${_siblingPath.split("/").pop()}`;
      siblingEl.style.color = "var(--text-dim)";
      analyzeBtn.disabled = false;
    } else {
      siblingEl.textContent = "No sibling camera found — 3D analysis disabled for this video.";
      siblingEl.style.color = "var(--danger, #e66)";
      analyzeBtn.disabled = true;
    }
  } catch (e) {
    siblingEl.textContent = "Could not resolve sibling camera.";
    analyzeBtn.disabled = true;
  }
  _refreshAnalyzeEnablement();
}

// ── Warm-worker session ──────────────────────────────────────────
async function _ensureSession() {
  const lastRun = _ia3dEl.lastRun();
  const snapshot = _ia3dEl.snapSel()?.value;
  if (!snapshot) { if (lastRun) lastRun.textContent = "Pick a snapshot first."; return null; }
  const r = await fetch("/dlc/project/inline-analysis/session/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      snapshot_path: snapshot,
      shuffle:       parseInt(_ia3dEl.shuffle()?.value, 10) || 1,
      ttl_seconds:   parseInt(_ia3dEl.keepWarm()?.value, 10) || 300,
      batch_size:    parseInt(_ia3dEl.batch()?.value, 10) || 8,
    }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    if (lastRun) {
      lastRun.textContent = d.error || `Could not start session (HTTP ${r.status})`;
      lastRun.className = "fe-extract-status err";
    }
    return null;
  }
  _snapKey = (await r.json()).snap_key;
  _startStatusPoll();
  return _snapKey;
}

function _startStatusPoll() {
  if (_statusPoll) return;
  _statusPoll = setInterval(async () => {
    if (!_snapKey) return;
    try {
      const r = await fetch(`/dlc/project/inline-analysis/session/status?snap_key=${_snapKey}`);
      const d = await r.json();
      const s = d.status || "absent";
      const rem = d.idle_remaining_s || 0;
      const mm = Math.floor(rem / 60), ss = String(rem % 60).padStart(2, "0");
      const warmInd = _ia3dEl.warmInd();
      if (warmInd) warmInd.textContent =
        s === "ready" ? `● warm · ${mm}:${ss}` : s === "warming" ? "… warming" : `○ ${s}`;
    } catch (e) { /* keep polling */ }
  }, 2000);
}

function _stopStatusPoll() { if (_statusPoll) { clearInterval(_statusPoll); _statusPoll = null; } }

// ── Submit one /range, return req_id (or null) ───────────────────
async function _submitRange(sk, videoPath, startFrame, nFrames) {
  const lastRun = _ia3dEl.lastRun();
  const r = await fetch("/dlc/project/inline-analysis/range", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      snap_key: sk, video_path: videoPath,
      start_frame: startFrame, n_frames: nFrames,
      batch_size: parseInt(_ia3dEl.batch()?.value, 10) || 8,
      save_as_csv: !!(_ia3dEl.saveCsv() && _ia3dEl.saveCsv().checked),
      snapshot_path: _ia3dEl.snapSel()?.value || "",
      shuffle: parseInt(_ia3dEl.shuffle()?.value, 10) || 1,
      trainingsetindex: parseInt(_ia3dEl.tsi()?.value, 10) || 0,
    }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { if (lastRun) { lastRun.textContent = `Error: ${d.error || r.status}`; lastRun.className = "fe-extract-status err"; } return null; }
  return d.req_id;
}

// ── Poll one req_id to terminal state ─
const _activePolls = new Set();
function _stopAllPolls() {
  for (const t of _activePolls) clearInterval(t);
  _activePolls.clear();
}
function _pollReq(reqId) {
  return new Promise((resolve) => {
    let elapsedMs = 0;
    const MAX_MS = 5 * 60 * 1000;   // 5 min hard cap → treat as failed
    const t = setInterval(async () => {
      elapsedMs += 500;
      if (elapsedMs >= MAX_MS) {
        clearInterval(t); _activePolls.delete(t);
        resolve({ status: "error", error: "timed out waiting for range result" });
        return;
      }
      try {
        const r = await fetch(`/dlc/project/inline-analysis/range/status?req_id=${reqId}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d.status === "done" || d.status === "error") {
          clearInterval(t); _activePolls.delete(t); resolve(d);
        }
      } catch (e) { /* keep polling */ }
    }, 500);
    _activePolls.add(t);
  });
}

// ── Analyze BOTH cameras (handler) ─────────────────────────────────────────
async function _onAnalyzeClick() {
  const lastRun = _ia3dEl.lastRun();
  const analyzeBtn = _ia3dEl.analyzeBtn();
  const cam0 = _cam0Path();
  if (!cam0)        { if (lastRun) lastRun.textContent = "Pick a cam0 video first."; return; }
  if (!_siblingPath) { if (lastRun) lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
  const sk = await _ensureSession();
  if (!sk) return;
  const startFrame = (_viewer ? _viewer.currentFrame() : 0) || 0;
  const nFrames    = parseInt(_ia3dEl.frames()?.value, 10) || 500;
  if (lastRun) {
    lastRun.textContent = `Running both cameras (${nFrames} frames from ${startFrame})…`;
    lastRun.className = "fe-extract-status";
  }
  if (analyzeBtn) analyzeBtn.disabled = true;
  const [req0, req1] = await Promise.all([
    _submitRange(sk, cam0, startFrame, nFrames),
    _submitRange(sk, _siblingPath, startFrame, nFrames),
  ]);
  if (!req0 || !req1) { if (analyzeBtn) analyzeBtn.disabled = false; return; }
  const [d0, d1] = await Promise.all([_pollReq(req0), _pollReq(req1)]);
  if (analyzeBtn) analyzeBtn.disabled = false;
  const errs = [d0, d1].filter(d => d.status === "error");
  if (errs.length === 2) {
    if (lastRun) { lastRun.textContent = `Both cameras failed: ${errs[0].error || "unknown"}`; lastRun.className = "fe-extract-status err"; }
    return;
  }
  if (lastRun) {
    lastRun.textContent = errs.length === 1
      ? `One camera failed (${errs[0].error || "unknown"}); other: ${(d0.status==='done'?d0:d1).n_analyzed} analyzed`
      : `Last run: cam0 ${d0.n_analyzed} analyzed/${d0.n_skipped} skipped · cam1 ${d1.n_analyzed}/${d1.n_skipped}`;
  }
  _ia3dPopulateFinalizeFields();
  // Trigger the shared viewer's render path: re-discover the cam0 h5 variants
  // (auto-picks the freshly-written primary + resolves the cam1 sibling), turn
  // the overlay on, then do a frame-preserving viewer reload so markers paint
  // deterministically. Replaces the old _iaDiscoverVariants + _iaLoadFrame path.
  await _iaDiscoverVariants(cam0);
  const ov = $("ia3d-overlay-toggle");
  if (ov && !ov.checked) {
    ov.checked = true;
    ov.dispatchEvent(new Event("change", { bubbles: true }));
  } else {
    _markerEditor?.setOverlayEnabled(true);
  }
  // Frame-preserving viewer reload so the overlay repaints over the same frame.
  if (_viewer && _primaryRel) {
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3d-sync-cam");
    await _viewer.load({
      videoPath: _primaryRel,
      frameCount: _frameCount,
      framesMode,
      siblingPath: sync?.checked && !framesMode ? undefined : null,
    });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  // Re-establish the primary to the just-written latest variant (the discover + the
  // reload above both clear the selection per the clean-switch rule; the overlay was
  // already on so the toggle auto-pick won't fire). Also cache-busts + repaints the
  // markers + coverage timeline (the in-place h5 overwrite otherwise serves stale).
  await _reloadPrimaryAfterAnalysis();
}

// ── Left-region start buttons ────────────────────────────────────────────────

// Analyze BOTH cameras over the LOCKED finalize range (start = range.start,
// n = range.n). Gated by the UI (button only enabled when finalize-on && locked
// && sibling). Reuses the same session + dual-cam submit/poll as _onAnalyzeClick.
async function _onAnalyzeRangeConfinedClick() {
  const lastRun = _ia3dEl.lastRun();
  const cam0 = _cam0Path();
  if (!cam0) { if (lastRun) lastRun.textContent = "Pick a cam0 video first."; return; }
  if (!_siblingPath) { if (lastRun) lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
  const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
  const startFrame = rng.start, nFrames = rng.n;
  if (!(nFrames >= 1)) { if (lastRun) lastRun.textContent = "Lock a valid keyframe range first."; return; }
  const sk = await _ensureSession();
  if (!sk) return;
  const btn = $("ia3d-btn-analyze-range-confined");
  if (lastRun) { lastRun.textContent = `Running both cameras (${nFrames} frames from ${startFrame})…`; lastRun.className = "fe-extract-status"; }
  if (btn) btn.disabled = true;
  const [req0, req1] = await Promise.all([
    _submitRange(sk, cam0, startFrame, nFrames),
    _submitRange(sk, _siblingPath, startFrame, nFrames),
  ]);
  if (!req0 || !req1) { _refreshAnalyzeEnablement(); return; }
  const [d0, d1] = await Promise.all([_pollReq(req0), _pollReq(req1)]);
  const errs = [d0, d1].filter((d) => d.status === "error");
  if (lastRun) {
    lastRun.textContent = errs.length === 2
      ? `Both cameras failed: ${errs[0].error || "unknown"}`
      : `Last run: cam0 ${d0.n_analyzed}/${d0.n_skipped} · cam1 ${d1.n_analyzed}/${d1.n_skipped}`;
    if (errs.length === 2) lastRun.className = "fe-extract-status err";
  }
  _ia3dPopulateFinalizeFields();
  await _iaDiscoverVariants(cam0);
  const ov = $("ia3d-overlay-toggle");
  if (ov && !ov.checked) { ov.checked = true; ov.dispatchEvent(new Event("change", { bubbles: true })); }
  else { _markerEditor?.setOverlayEnabled(true); }
  if (_viewer && _primaryRel) {
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3d-sync-cam");
    await _viewer.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode, siblingPath: sync?.checked && !framesMode ? undefined : null });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  // Re-establish the primary to the latest variant + cache-bust + repaint markers +
  // coverage (see _onAnalyzeClick / _reloadPrimaryAfterAnalysis).
  await _reloadPrimaryAfterAnalysis();
  _refreshAnalyzeEnablement();
}

// Drive the two left-region start buttons + the count/hint line. "From current
// frame" mirrors the top analyze button's sibling-gating. "For range" needs
// finalize-on AND the keyframe locked AND a sibling.
function _refreshAnalyzeEnablement() {
  const cur = $("ia3d-btn-analyze-current");
  const rng = $("ia3d-btn-analyze-range-confined");
  const n = parseInt(_ia3dEl.frames()?.value, 10) || 500;
  const countN = $("ia3d-start-count-n");
  if (countN) countN.textContent = n.toLocaleString();
  const hasSibling = !!_siblingPath;
  if (cur) cur.disabled = !hasSibling;
  const finOn = !!$("ia3d-finalize-toggle")?.checked;
  const locked = !!$("ia3d-finalize-lock")?.checked;
  const rangeOk = finOn && locked && hasSibling;
  if (rng) rng.disabled = !rangeOk;
  const hint = $("ia3d-start-hint");
  if (hint) {
    if (rangeOk) {
      const r = _finalizeKW ? _finalizeKW.getRange() : { start: 0, end: 0 };
      hint.textContent = `keyframe is locked → "for range" analyzes ${r.start}–${r.end}. Unlock to disable.`;
    } else if (!hasSibling) {
      hint.textContent = "no sibling camera detected.";
    } else {
      hint.textContent = "lock the finalize keyframe to enable \"for range\".";
    }
  }
}

// ── Finalize Analysis: toggle (gates editing) + both-cams range copy ──

function _ia3dPopulateFinalizeFields() {
  _finalizeKW?.load();   // keyframe=current frame, before/after from the per-project setting
}

async function _ia3dSaveLayer(h5) {
  try {
    const r = await fetch("/dlc/viewer/save-marker-edits", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ h5 }),
    });
    return r.ok;
  } catch (_) { return false; }
}

async function _ia3dFinalizeOne(videoPath, sourceH5, startFrame, nFrames) {
  const r = await fetch("/dlc/project/inline-analysis/finalize-range", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath, source_h5: sourceH5, start_frame: startFrame, n_frames: nFrames }),
  });
  const d = await r.json().catch(() => ({}));
  return r.ok ? { ok: true, n: d.n_frames_written } : { ok: false, err: d.error || r.status };
}

// ── Initialize / finalize analysis-file helpers ──────────────────
// Check whether the _analyzed file exists for a given video path.
async function _initStatus(v) {
  try { return (await (await fetch(`/dlc/project/analysis-file/status?video_path=${encodeURIComponent(v)}`)).json()).initialized; }
  catch (e) { return false; }
}

// Finalize the current keyframe-window range into both cams' _analyzed.
// Returns { ok, start, n }. Shared by the Add-range and Finalize-and-extract
// buttons; callers manage their own button disabled-state.
async function _doFinalizeAdd() {
  const st = $("ia3d-finalize-status");
  const cam0H5 = _overlayPrimaryH5, cam0Video = _cam0Path();
  if (!cam0H5 || !cam0Video) {
    if (st) { st.textContent = "Select a video/layer first."; st.className = "fe-extract-status err"; }
    return { ok: false, start: 0, n: 0 };
  }
  const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
  const startFrame = rng.start, nFrames = rng.n;
  const cam1Layer = _siblingPrimaryH5;
  try {
    const e0 = await _initStatus(cam0Video);
    const e1 = (_siblingPath && cam1Layer) ? await _initStatus(_siblingPath) : false;
    if ((e0 || e1) && !window.confirm(
        `Overwrite frames ${startFrame}–${startFrame + nFrames - 1} in the existing _analyzed file(s)` +
        `${e0 && e1 ? " on both cameras" : (e0 ? " on cam0" : " on cam1")}?\n\nThis replaces any curated values already saved for those frames.`)) {
      if (st) { st.textContent = "Cancelled."; st.className = "fe-extract-status"; }
      return { ok: false, start: startFrame, n: nFrames };
    }
  } catch (_) { /* status check failed — proceed */ }
  if (st) { st.textContent = "Finalizing…"; st.className = "fe-extract-status"; }
  try {
    const sv0 = await _ia3dSaveLayer(cam0H5);
    const sv1 = cam1Layer ? await _ia3dSaveLayer(cam1Layer) : true;
    if (!sv0 || !sv1) {
      if (st) { st.textContent = `Could not save edits (${!sv0 ? "cam0" : "cam1"}) — finalize aborted`; st.className = "fe-extract-status err"; }
      return { ok: false, start: startFrame, n: nFrames };
    }
    const r0 = await _ia3dFinalizeOne(cam0Video, cam0H5, startFrame, nFrames);
    let r1 = null;
    if (_siblingPath && cam1Layer) r1 = await _ia3dFinalizeOne(_siblingPath, cam1Layer, startFrame, nFrames);
    if (st) {
      // Surface written/requested: the working h5 is sparse, so finalize copies only
      // the range frames that actually have analysis rows — show "697/800" + the gap
      // so the user knows N frames in the range weren't analyzed (run "for range" to
      // fill them). A gap is informative, not an error.
      const p0 = r0.ok ? `cam0 ✓ ${r0.n}/${nFrames}` : `cam0 ⚠ ${r0.err}`;
      const p1 = r1 ? (r1.ok ? ` · cam1 ✓ ${r1.n}/${nFrames}` : ` · cam1 ⚠ ${r1.err}`) : "";
      const gap = Math.max(r0.ok ? nFrames - r0.n : 0, (r1 && r1.ok) ? nFrames - r1.n : 0);
      const gapNote = gap > 0 ? ` (${gap} frame${gap !== 1 ? "s" : ""} in range not yet analyzed)` : "";
      st.textContent = `${p0}${p1}${gapNote}`;
      st.className = (r0.ok && (!r1 || r1.ok)) ? "fe-extract-status" : "fe-extract-status err";
    }
    _refreshFinalizeCoverage();
    return { ok: !!(r0.ok && (!r1 || r1.ok)), start: startFrame, n: nFrames };
  } catch (e) {
    if (st) { st.textContent = `Error: ${e}`; st.className = "fe-extract-status err"; }
    return { ok: false, start: startFrame, n: nFrames };
  }
}

async function _onFinalizeAddClick() {
  const btn = $("ia3d-finalize-add-btn");
  if (btn) btn.disabled = true;
  try { await _doFinalizeAdd(); }
  finally { if (btn) btn.disabled = false; }
}

function _finalizeClipBtnsEnabled(on) {
  const r = $("ia3d-finalize-clip-rename-btn"), d = $("ia3d-finalize-clip-delete-btn");
  if (r) r.disabled = !on;
  if (d) d.disabled = !on;
}

async function _onFinalizeAndExtractClick() {
  const st = $("ia3d-finalize-status"), btn = $("ia3d-finalize-clip-btn");
  if (btn) btn.disabled = true;
  try {
    const r = await _doFinalizeAdd();
    if (!r.ok) return;
    const postfix = $("ia3d-finalize-clip-postfix")?.value || "";
    const both = $("ia3d-finalize-clip-sibling")?.checked;
    const cams = [{ video: _cam0Path() }];
    if (both && _siblingPath) cams.push({ video: _siblingPath });
    let okCount = 0;
    for (const c of cams) {
      try {
        const resp = await (await fetch("/dlc-3d/extract-clip", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_path: c.video, start_frame: r.start, n_frames: r.n, postfix }),
        })).json();
        c.avi = resp.avi_path || null;
        if (c.avi) okCount++;
      } catch (_) { c.avi = null; }
    }
    if (okCount > 0) {
      _lastFinalizeClip = { start: r.start, n: r.n, cams };
      _finalizeClipBtnsEnabled(true);
      if (st) st.textContent = `${st.textContent} · clip ✓ (${okCount} cam${okCount !== 1 ? "s" : ""})`;
    } else if (st) {
      st.textContent = `${st.textContent} · clip ⚠ failed`;
      st.className = "fe-extract-status err";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _onFinalizeClipRename() {
  if (!_lastFinalizeClip) return;
  const st = $("ia3d-finalize-status");
  const postfix = $("ia3d-finalize-clip-postfix")?.value || "";
  for (const c of _lastFinalizeClip.cams) {
    if (!c.avi) continue;
    try {
      const resp = await (await fetch("/dlc-3d/extract-clip/rename", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avi_path: c.avi, postfix }),
      })).json();
      if (resp.avi_path) c.avi = resp.avi_path;
    } catch (_) { /* best effort */ }
  }
  if (st) { st.textContent = "Clip renamed."; st.className = "fe-extract-status"; }
}

async function _onFinalizeClipDelete() {
  if (!_lastFinalizeClip) return;
  const { start, n, cams } = _lastFinalizeClip;
  if (!window.confirm(
      `Delete the extracted clip and REMOVE frames ${start}–${start + n - 1} from the _analyzed file(s)?\n\nThis un-finalizes those frames (sets them back to no-data).`)) return;
  const st = $("ia3d-finalize-status");
  let unfinalizeOk = true;
  for (const c of cams) {
    if (c.avi) {
      try { await fetch("/dlc-3d/extract-clip/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ avi_path: c.avi }) }); } catch (_) { /* best effort */ }
    }
    try {
      const ur = await fetch("/dlc/project/inline-analysis/unfinalize-range", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_path: c.video, start_frame: start, n_frames: n }) });
      if (!ur.ok) unfinalizeOk = false;
    } catch (_) { unfinalizeOk = false; }
  }
  _refreshFinalizeCoverage();
  _lastFinalizeClip = null;
  _finalizeClipBtnsEnabled(false);
  if (st) {
    if (unfinalizeOk) { st.textContent = "Clip deleted; frames un-finalized."; st.className = "fe-extract-status"; }
    else { st.textContent = "Clip deleted, but un-finalize FAILED — _analyzed may still contain those frames."; st.className = "fe-extract-status err"; }
  }
}

async function _refreshInitFileBtn() {
  const initFileBtn = $("ia3d-init-analysis-file");
  const initFileStatus = $("ia3d-init-file-status");
  if (!initFileBtn) return;
  const cam0 = _cam0Path();
  if (!cam0) {
    initFileBtn.disabled = true;
    if (initFileStatus) initFileStatus.textContent = "";
    return;
  }
  const a = await _initStatus(cam0);
  const hasSibling = !!_siblingPath;
  const b = hasSibling ? await _initStatus(_siblingPath) : true;

  if (a && b) {
    // both cameras already have analysis files
    initFileBtn.textContent = "Analysis files exist";
    initFileBtn.disabled = true;
    if (initFileStatus) initFileStatus.textContent = "";
  } else if (hasSibling && (a !== b)) {
    // exactly one camera has a file — generate only the missing one
    initFileBtn.disabled = false;
    if (a) {
      // cam0 exists, cam1 is missing
      initFileBtn.textContent = "○ Initialize cam1 analysis file";
      if (initFileStatus)
        initFileStatus.textContent =
          "cam0 already has an analysis file — Initialize will generate cam1 only.";
    } else {
      // cam1 exists, cam0 is missing
      initFileBtn.textContent = "○ Initialize cam0 analysis file";
      if (initFileStatus)
        initFileStatus.textContent =
          "cam1 already has an analysis file — Initialize will generate cam0 only.";
    }
  } else {
    // neither camera has a file
    initFileBtn.textContent = "○ Initialize analysis files (both cameras)";
    initFileBtn.disabled = false;
    if (initFileStatus) initFileStatus.textContent = "";
  }
}

async function _initOne(v) {
  try {
    const r = await fetch("/dlc/project/analysis-file/initialize", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_path: v }),
    });
    return r.ok || r.status === 409;   // 409 = already initialized = fine
  } catch (err) {
    return false;   // network reject → _refreshInitFileBtn re-enables the button
  }
}

async function _onInitFileClick() {
  const initFileBtn = $("ia3d-init-analysis-file");
  const initFileStatus = $("ia3d-init-file-status");
  const cam0 = _cam0Path(); if (!cam0) return;
  if (initFileBtn) { initFileBtn.disabled = true; initFileBtn.textContent = "…"; }
  const okCam0 = await _initOne(cam0);
  const okCam1 = _siblingPath ? await _initOne(_siblingPath) : true;
  if (initFileStatus) initFileStatus.textContent = `cam0 ${okCam0 ? "✓" : "⚠"}` + (_siblingPath ? ` · cam1 ${okCam1 ? "✓" : "⚠"}` : "");
  await _refreshInitFileBtn();
}

// Wire the stereo-analysis chrome (static controls; persist across rebuilds).
function _wireStereoDispatch() {
  const analyzeBtn = _ia3dEl.analyzeBtn();
  if (!analyzeBtn) return;   // markup missing — bail silently

  _ia3dEl.refreshSnap()?.addEventListener("click", _loadSnapshots);
  _ia3dEl.shuffle()?.addEventListener("change", _loadSnapshots);
  $("btn-open-inline-analysis-3d")?.addEventListener("click", _loadSnapshots);

  analyzeBtn.addEventListener("click", _onAnalyzeClick);

  // Left-region start buttons (mirror the top analyze button + gated for-range).
  $("ia3d-btn-analyze-current")?.addEventListener("click", _onAnalyzeClick);
  $("ia3d-btn-analyze-range-confined")?.addEventListener("click", _onAnalyzeRangeConfinedClick);
  $("ia3d-frames-per-click")?.addEventListener("input", _refreshAnalyzeEnablement);
  $("ia3d-finalize-lock")?.addEventListener("change", _refreshAnalyzeEnablement);
  $("ia3d-finalize-lock")?.addEventListener("change", _applyLockState);

  // Per-project quick-tags (postfix / status / note). Static containers + inputs
  // — wired once here; loaded per-project on each video open.
  _wireQuickTags();

  // Finalize toggle: gates marker editing via the markerEditor master gate
  // (replaces the old _ia3dFinalizeEnabled gate), reveals the controls, force-
  // enables the overlay, and populates the range fields.
  const ia3dFinalizeToggle = $("ia3d-finalize-toggle");
  ia3dFinalizeToggle?.addEventListener("change", () => {
    const on = !!ia3dFinalizeToggle.checked;
    _markerEditor?.setEditable(on);
    $("ia3d-finalize-controls")?.classList.toggle("hidden", !on);
    const ov = $("ia3d-overlay-toggle");
    if (on&&ov&&!ov.checked){ov.checked=true;ov.dispatchEvent(new Event("change"));}
    if (on) _ia3dPopulateFinalizeFields();
    _refreshFinalizeCoverage();
    _refreshAnalyzeEnablement();
    _applyLockState();
  });

  $("ia3d-finalize-add-btn")?.addEventListener("click", _onFinalizeAddClick);
  $("ia3d-finalize-clip-btn")?.addEventListener("click", _onFinalizeAndExtractClick);
  $("ia3d-finalize-clip-rename-btn")?.addEventListener("click", _onFinalizeClipRename);
  $("ia3d-finalize-clip-delete-btn")?.addEventListener("click", _onFinalizeClipDelete);

  $("ia3d-init-analysis-file")?.addEventListener("click", _onInitFileClick);

  // Session cleanup on card close.
  $("btn-close-inline-analysis-3d")?.addEventListener("click", () => {
    _stopAllPolls();
    _stopStatusPoll();
    if (_snapKey) {
      try {
        fetch("/dlc/project/inline-analysis/session/stop", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ snap_key: _snapKey }),
        });
      } catch (e) { /* ignore */ }
      _snapKey = null;
    }
  });

  // beforeunload: stop polls + release the warm session via sendBeacon.
  window.addEventListener("beforeunload", () => {
    if (_snapKey) navigator.sendBeacon?.(
      "/dlc/project/inline-analysis/session/stop",
      new Blob([JSON.stringify({ snap_key: _snapKey })], { type: "application/json" }),
    );
  });
}

// ── NAV PLACEMENT — relocate the open button into the shared launcher list ───
// (#dlc-frame-extract-launch). That list is rendered by a main-webapp partial
// baked into the dlc-3d image, so we move the node (preserving its click
// listeners) instead of adding it at the template level.
function _ia3dPlaceNavButton() {
  const nav = $("dlc-frame-extract-launch");
  const btn = $("btn-open-inline-analysis-3d");
  if (!nav || !btn) return;
  if (btn.parentElement !== nav) {
    const anchor = $("btn-open-view-analyzed");
    if (anchor && anchor.parentElement === nav) anchor.insertAdjacentElement("afterend", btn);
    else nav.appendChild(btn);
  }
  btn.style.display = "";   // reveal now that it sits in the nav list
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  _wireLauncher();
  _wireStereoDispatch();
  _ia3dPlaceNavButton();
});
if (document.readyState !== "loading") {
  // Module evaluated after DOMContentLoaded — run the nav placement now too
  // (the DOMContentLoaded listener above won't fire). Idempotent.
  _ia3dPlaceNavButton();
}

// Expose the VideoViewer instance for the co-evolved static/E2E tests (replaces
// the old window.__ia3d-controller getter). Resolved lazily — the viewer is
// created on the first open. A getter keeps it current across rebuild cycles.
Object.defineProperty(window, "__iaViewer", {
  configurable: true,
  get() { return _viewer; },
});
