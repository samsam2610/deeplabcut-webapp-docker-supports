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
import { makePose3dViewer } from "./pose3d_viewer.js";
import { clampToBounds } from "./internal/clamp_bounds.mjs";
import { addTag, removeTag } from "./internal/tag_list.mjs";
import { tagKeyframes, mergeWindows } from "./components/viewer/internal/tag_batch.mjs";
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

// Triangulate (Phase 2) — 3D coverage bar presence buckets (0..1), null until fetched.
let _triCoverageBuckets = null;
let _redrawTriangulateCoverage = () => {};

// 3D pose viewer (three.js spike) — isolated handle; null until the panel is opened.
let _pose3d = null;
let _pose3dChromeWired = false;
let _pose3dLoaded = false;   // true once load(data) has real data (guards showFrame no-op).
let _mirrorRaf = null;       // single rAF handle for the mini-cam mirror loop (never leaks).
let _mirrorLastTs = 0;       // last mirror timestamp — throttles the loop to ~30fps.
let _bgSaveTimer = null;     // debounce handle for the 3D background-colour ui-setting save.
let _viewPrefsSaveTimer = null;  // debounce handle for the 3D view-prefs (size + flips) ui-setting save.
let _savedCamState = null;       // persisted 3D camera (zoom/rotation), restored after each load.
let _snTimeline = null;   // statusNoteTimeline feature handle (for .redraw() on resize)
let _pendingTagRestore = null;  // active status/note tags stashed across a post-analysis reload

// Task 4: likelihood-filtered coverage cache + debounce timer.
const _coverageCache = new Map(); // keyed by "<h5>:<threshold.toFixed(2)>:<width>"
let _coverageTimer = null;        // debounce handle for threshold changes

// Browse-tab folder navigator state.
let _iaBrowsePath = null;
const _IA_VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg"]);

// ── Element helpers ───────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function _setStatus(msg, isErr = false) {
  const el = $("ia3dr-status");
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
  const mount = $("ia3dr-viewer-mount");
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
      bpChips:   $("ia3dr-bp-chips"),
      editBanner: $("ia3dr-marker-edit-controls"),
      editCount:  $("ia3dr-marker-edit-count"),
    },
    markerSize: 4, // Fix D (#3): labeler-parity default (slider still adjusts)
    globalThreshold: 0.6,
    poseWindow: 30,
    autoAdvance: true, // B2: advance to next unlabeled bp after a place (labeler feel)
  });
  _viewer.use(_markerEditor);

  // Editing is OFF by default in this card (the OLD card gated editing on the
  // Finalize toggle: _iaIsEditable() = layers===1 && _ia3drFinalizeEnabled). The
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
      statusCanvas:  $("ia3dr-status-canvas"),
      noteCanvas:    $("ia3dr-note-canvas"),
      statusChips:   $("ia3dr-status-chips"),
      noteChips:     $("ia3dr-note-chips"),
      statusWrap:    $("ia3dr-status-bar-wrap"),
      noteWrap:      $("ia3dr-note-bar-wrap"),
      statusPrev:    $("ia3dr-status-prev-btn"),
      statusNext:    $("ia3dr-status-next-btn"),
      notePrev:      $("ia3dr-note-prev-btn"),
      noteNext:      $("ia3dr-note-next-btn"),
      statusInput:   $("ia3dr-status-input"),
      noteInput:     $("ia3dr-note-input"),
      saveStatusBtn: $("ia3dr-save-status-btn"),
      saveNoteBtn:   $("ia3dr-save-note-btn"),
      saveFeedback:  $("ia3dr-annot-save-status"),
      statusBadge:   $("ia3dr-meta-frame-status"),
      noteBadge:     $("ia3dr-meta-frame-note"),
    },
    fps: _fps,
    frameBase: 0,
    // Recompute tag-lock enablement whenever the user toggles a note/status chip.
    onActiveTagsChange: () => _refreshTagLockEnablement(),
    // Fires at the END of loadCsv (after it clears + rebuilds the tag chips). The
    // post-analysis _viewer.load() triggers a same-video loadCsv that would wipe the
    // user's active status/note filters; restore them here from the pre-load snapshot.
    onCsv: () => {
      if (_pendingTagRestore) {
        _snTimeline?.setActiveTags(_pendingTagRestore);
        _pendingTagRestore = null;
      }
      // A CSV (re)load clears the active-note set (or restores it above); refresh the
      // tag-lock so a video switch drops the lock and a same-video reload keeps it.
      _refreshTagLockEnablement();
    },
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
      enable: $("ia3dr-clip-enable"), panel: $("ia3dr-clip-panel"),
      startInput: $("ia3dr-clip-start"), framesInput: $("ia3dr-clip-frames"),
      endDisplay: $("ia3dr-clip-end"), postfixInput: $("ia3dr-clip-postfix"),
      extractBtn: $("ia3dr-clip-extract-btn"), renameBtn: $("ia3dr-clip-rename-btn"),
      deleteBtn: $("ia3dr-clip-delete-btn"), extractSibling: $("ia3dr-clip-sibling"),
      statusDisplay: $("ia3dr-clip-status"),
    },
  }));
  // Load clip_window persisted setting when the panel is first enabled.
  $("ia3dr-clip-enable")?.addEventListener("change", (ev) => { if (ev.target.checked) _clipKW?.load(); });

  // Metadata-strip reveal glue (consumer-owned — not part of statusNoteTimeline).
  // Poll the wrap visibility a few times after videoLoad (covers the CSV fetch
  // latency) to reveal the metadata frame row + update the CSV-info text. Also
  // refresh on frameChange so the per-frame badges stay paired with a visible
  // row. videoLoad also refreshes the overlay h5 variants AND re-resolves the
  // sibling for analyze-gating (replaces the old #ia3dr-frame-counter observer).
  _viewer.on("videoLoad", () => {
    _scheduleMetaStripRefresh();
    _refreshOverlayH5Variants();
    _refreshSibling();
    _refreshInitFileBtn();
    // Repaint the "Finalized frames" timeline from this video's _analyzed file.
    // _resetForOpen cleared it, and the finalize-toggle change handler (which would
    // refresh it) doesn't fire on open (the toggle is set checked without dispatching
    // change) — so a previously-finalized video would otherwise show an empty bar.
    _refreshFinalizeCoverage();
    // The 3D-coverage bar now lives under the viewer (always visible), so populate
    // it on video load too — not only when the Triangulate panel is opened.
    _refreshTriangulateCoverage();
  });
  _viewer.on("frameChange", (n) => {
    _updateMetaStrip();
    // Drive the 3D pose viewer in lock-step with the 2D player. Guarded: no-op
    // until the 3D panel has loaded triangulated data (_pose3dLoaded). Also mirror
    // the main viewer's current-frame tiles into the composite mini-cams.
    if (_pose3d && _pose3dLoaded) {
      _pose3d.showFrame(n);
      _mirrorPose3dCams();
    }
  });

  // Dataset-curation consumer glue: master toggle + Extract Frame / Add to
  // Dataset / Batch Add, with both-cams fan-out in sync mode.
  _wireCurationChrome();
  _wireTriangulateChrome();
  _wireParamsChrome();
  _wirePose3dChrome();

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
  const locked = !!$("ia3dr-finalize-lock")?.checked && !!$("ia3dr-finalize-toggle")?.checked;
  _lockActive = locked;
  if (locked && _finalizeKW) {
    const r = _finalizeKW.getRange();
    _lockRange = { start: r.start, end: r.end };
  }
  // Red flag above cam0 (normal flow). Hidden unless locked.
  const flag = $("ia3dr-lock-flag");
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
  const range = $("ia3dr-lock-range");
  const dimL = $("ia3dr-lock-dim-left");
  const dimR = $("ia3dr-lock-dim-right");
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
  for (const id of ["ia3dr-seek-canvas", "ia3dr-status-canvas", "ia3dr-note-canvas", "ia3dr-finalize-coverage", "ia3dr-triangulate-coverage"]) {
    const c = $(id);
    if (!c) continue;
    // Restore the template's inline width:100% on reset (clearing to "" would
    // erase that inline declaration → canvas falls back to its backing-store px).
    c.style.width = overflowing ? g.width + "px" : "100%";
    c.style.marginLeft = overflowing ? g.marginLeft + "px" : "";
  }
  _redrawSeekTimeline();
  _redrawFinalizeCoverage();
  _redrawTriangulateCoverage();
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
  const skipN = () => Math.max(1, parseInt($("ia3dr-skip-n")?.value, 10) || 10);

  // Initialise viewer state from the card's control defaults.
  v.setSkipN(skipN());
  v.setPlayStep($("ia3dr-play-step")?.value || 1);
  v.setFps($("ia3dr-play-fps")?.value || 5);

  // Play/pause forward: pause if already playing forward; otherwise play forward
  // (switching direction if currently playing backward). The button shows pause
  // only while playing forward (see _swapPlayIcon).
  $("ia3dr-btn-play")?.addEventListener("click", () => {
    if (v.isPlaying() && v.playDir() > 0) v.pause();
    else { v.setPlayDir(1); v.play(); }
  });
  // Play/pause backward: pause if already playing backward; otherwise play
  // backward (switching direction if currently playing forward). The back button
  // shows pause only while playing backward.
  $("ia3dr-btn-play-back")?.addEventListener("click", () => {
    if (v.isPlaying() && v.playDir() < 0) v.pause();
    else { v.setPlayDir(-1); v.play(); }
    Promise.resolve().then(() => _swapPlayIcon(v.isPlaying()));
  });
  // Step ∓1 / multi-frame skip ∓N. When the keyframe is locked, compute the
  // confined target and seek directly (step is unconfined).
  const _confine = (target) => (_lockActive ? clampToBounds(target, _lockRange.start, _lockRange.end) : target);
  $("ia3dr-btn-prev")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() - 1)));
  $("ia3dr-btn-next")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() + 1)));
  $("ia3dr-btn-skip-back")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() - skipN())));
  $("ia3dr-btn-skip-fwd")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() + skipN())));
  $("ia3dr-skip-n")?.addEventListener("input", () => v.setSkipN(skipN()));
  // Prevent arrow keys in the skip-N field from bubbling to viewer keynav.
  $("ia3dr-skip-n")?.addEventListener("keydown", (e) => e.stopPropagation());

  // Skip-size presets (clip-cutter's quick step levels): set skip-N + mark active.
  const _syncSkipPresets = () => {
    const n = skipN();
    document.querySelectorAll("#inline-analysis-3d-reprojection-card .ia3dr-skip-preset").forEach((b) => {
      b.classList.toggle("active", parseInt(b.dataset.n, 10) === n);
    });
  };
  document.querySelectorAll("#inline-analysis-3d-reprojection-card .ia3dr-skip-preset").forEach((b) => {
    b.addEventListener("click", () => {
      const skip = $("ia3dr-skip-n");
      if (skip) skip.value = b.dataset.n;
      v.setSkipN(parseInt(b.dataset.n, 10));
      _syncSkipPresets();
    });
  });
  $("ia3dr-skip-n")?.addEventListener("input", _syncSkipPresets);
  _syncSkipPresets();

  // Playback rate + step.
  $("ia3dr-play-fps")?.addEventListener("input", (e) => v.setFps(e.target.value));
  $("ia3dr-play-step")?.addEventListener("input", (e) => v.setPlayStep(e.target.value));

  // Main timeline canvas: dark track + marker-coverage marks + playhead; click/drag to seek.
  const seekCanvas = $("ia3dr-seek-canvas");
  _wireSeekCanvas(seekCanvas, () => ({ buckets: _coverageBuckets, frames: _coverageFrames }));
  _redrawSeekTimeline = () => _drawCoverageBar(seekCanvas, _coverageBuckets, _coverageFrames, _accentColor());

  // Finalize coverage canvas: presence-mode coverage of the _analyzed file (amber).
  const finalizeCanvas = $("ia3dr-finalize-coverage");
  _wireSeekCanvas(finalizeCanvas, () => ({ buckets: _finalizeCoverageBuckets, frames: _finalizeCoverageFrames }));
  _redrawFinalizeCoverage = () => {
    _drawCoverageBar(finalizeCanvas, _finalizeCoverageBuckets, _finalizeCoverageFrames, "#fbbf24");
    const has = !!(_finalizeCoverageBuckets && _finalizeCoverageBuckets.length);
    const pv = $("ia3dr-finalize-prev"), nx = $("ia3dr-finalize-next");
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
  $("ia3dr-finalize-prev")?.addEventListener("click", () => _finalizeNav(-1));
  $("ia3dr-finalize-next")?.addEventListener("click", () => _finalizeNav(1));
  v.on("frameChange", () => _redrawFinalizeCoverage());

  // 3D-coverage bar (triangulate): click/drag-seek + playhead sync, mirroring the
  // finalize bar. The endpoint supplies only buckets (no per-bucket frames), but
  // they're scaled to the full video, so xToFrame click-seek and the playhead land
  // consistently. Redraw is gated on the 3D panel being open (cheap no-op closed).
  const triCoverageCanvas = $("ia3dr-triangulate-coverage");
  _wireSeekCanvas(triCoverageCanvas, () => ({ buckets: _triCoverageBuckets, frames: null }));
  // Always-visible bar (relocated out of the collapsible Triangulate panel), so it
  // redraws whenever there's data — like _redrawFinalizeCoverage (no toggle gate).
  _redrawTriangulateCoverage = () => {
    _drawCoverageBar(triCoverageCanvas, _triCoverageBuckets, null, "#60a5fa");
    const has = !!(_triCoverageBuckets && _triCoverageBuckets.length);
    const pv = $("ia3dr-triangulate-prev"), nx = $("ia3dr-triangulate-next");
    if (pv) pv.disabled = !has;
    if (nx) nx.disabled = !has;
  };
  const _triangulateNav = (dir) => {
    if (!_viewer || !_triCoverageBuckets || !_triCoverageBuckets.length) return;
    const nB = _triCoverageBuckets.length;
    const fc = _viewer.frameCount();
    const b = nextCoveredBucket(_triCoverageBuckets, frameToBucket(_viewer.currentFrame(), fc, nB), dir);
    if (b == null) return;
    _viewer.pause();
    // The 3D coverage endpoint returns buckets only (no per-bucket frames), so seek
    // to the bucket centre — the SAME target the bar's click-seek already lands on.
    _viewer.seek(bucketToFrame(b, nB, fc));
  };
  $("ia3dr-triangulate-prev")?.addEventListener("click", () => _triangulateNav(-1));
  $("ia3dr-triangulate-next")?.addEventListener("click", () => _triangulateNav(1));
  v.on("frameChange", () => _redrawTriangulateCoverage());

  _finalizeKW = makeKeyframeWindow({
    viewer: v,
    panelEl: $("ia3dr-finalize-controls"),
    settingKey: "finalize_window",
    els: {
      keyframe: $("ia3dr-finalize-keyframe"), lock: $("ia3dr-finalize-lock"),
      before: $("ia3dr-finalize-before"), after: $("ia3dr-finalize-after"),
      length: $("ia3dr-finalize-length"), range: $("ia3dr-finalize-range"),
    },
    onChange: () => {
      _refreshAnalyzeEnablement();
      if (_lockActive && _finalizeKW) {
        const r = _finalizeKW.getRange();
        _lockRange = { start: r.start, end: r.end };
        _drawLockOverlays();
      }
    },
    // Single lock-propagation path: fires for checkbox click, keyframe typing
    // auto-lock, AND the 'l' shortcut (which sets .checked programmatically and so
    // never emits a native 'change'). Replaces the old direct 'change' listener.
    onLockChange: () => _applyLockState(),
  });

  _clipKW = makeKeyframeWindow({
    viewer: v,
    panelEl: $("ia3dr-clip-panel"),
    settingKey: "clip_window",
    els: {
      keyframe: $("ia3dr-clip-keyframe"), lock: $("ia3dr-clip-lock"),
      before: $("ia3dr-clip-before"), after: $("ia3dr-clip-after"),
      length: $("ia3dr-clip-length"), range: $("ia3dr-clip-range"),
    },
    onChange: (r) => {
      const s = $("ia3dr-clip-start"), f = $("ia3dr-clip-frames"), e = $("ia3dr-clip-end");
      if (s) s.value = r.start;
      if (f) f.value = r.n;
      if (e) e.value = r.end;
    },
  });

  // Frame-jump: click the counter to type an exact frame and Enter to jump
  // (granular seek, mirrors clip-cutter's clickable frame number).
  const counter = $("ia3dr-frame-counter");
  const jump = $("ia3dr-frame-jump");
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
  const zoom = $("ia3dr-zoom");
  zoom?.addEventListener("input", () => {
    const g = v.setZoom(parseInt(zoom.value, 10) || 100);
    _applyTimelineWidth(g);
    _drawLockOverlays();
    _refreshCoverageForZoom();   // re-fetch coverage at the new width (1px-precise marks)
    const val = $("ia3dr-zoom-val");
    if (val) val.textContent = zoom.value + " %";
  });

  // Equalize per-tile sizes.
  $("ia3dr-equalize-btn")?.addEventListener("click", () => v.equalizeTiles());

  // Sync-cam toggle: reload with/without the sibling tile, preserving the
  // current frame (mirrors dlc_3d.js _setupSyncCamToggle).
  const sync = $("ia3dr-sync-cam");
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
  $("ia3dr-btn-play")?.addEventListener("click", () =>
    Promise.resolve().then(() => _swapPlayIcon(v.isPlaying())),
  );

  const help = $("ia3dr-help-btn"), helpTip = $("ia3dr-help-tooltip");
  help?.addEventListener("click", (e) => { e.stopPropagation(); helpTip?.classList.toggle("hidden"); });
  document.addEventListener("click", () => helpTip?.classList.add("hidden"));
}

function _updateCounters(n, frameCount) {
  const counter = $("ia3dr-frame-counter");
  if (counter) counter.textContent = `Frame ${n} / ${frameCount}`;
  const time = $("ia3dr-time-display");
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
  const statusWrap = $("ia3dr-status-bar-wrap");
  const noteWrap = $("ia3dr-note-bar-wrap");
  const visible = (el) => el && el.style.display !== "none";
  const hasCsv = visible(statusWrap) || visible(noteWrap);
  const row = $("ia3dr-meta-frame-row");
  if (row) row.style.display = hasCsv ? "flex" : "none";
  const info = $("ia3dr-meta-csv-info");
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
  const sync = $("ia3dr-sync-cam");
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
  const btn = $("ia3dr-create-csv-btn");
  const fb = $("ia3dr-csv-create-status");
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
// direction (forward → #ia3dr-btn-play, backward → #ia3dr-btn-play-back); both
// show their play icon when stopped. Previously the pause icon was always the
// forward button's, so playing backward wrongly flipped the forward button.
function _swapPlayIcon(playing) {
  const dir = _viewer ? _viewer.playDir() : 1;
  const fwd = playing && dir > 0;
  const back = playing && dir < 0;
  $("ia3dr-play-icon")?.classList.toggle("hidden", fwd);
  $("ia3dr-pause-icon")?.classList.toggle("hidden", !fwd);
  $("ia3dr-play-back-icon")?.classList.toggle("hidden", back);
  $("ia3dr-pause-back-icon")?.classList.toggle("hidden", !back);
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
  const lbl = $("ia3dr-sync-cam-label");
  const cb = $("ia3dr-sync-cam");
  const eq = $("ia3dr-equalize-btn");
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
  const toggle = $("ia3dr-overlay-toggle");
  toggle?.addEventListener("change", async () => {
    const on = !!toggle.checked;
    _markerEditor?.setOverlayEnabled(on);
    $("ia3dr-overlay-controls")?.classList.toggle("hidden", !on);
    $("ia3dr-bp-list-wrap")?.classList.toggle("hidden", !on);
    const st = $("ia3dr-overlay-status");
    if (st) st.textContent = on ? "overlay on" : "overlay off";
    if (on && !_overlayPrimaryH5) {
      const variants = await _fetchOverlayH5Variants();
      const latest = _pickLatestKinematic(variants);   // latest non-_analyzed model (fallback to _analyzed if sole)
      if (latest && latest.path) {
        const sel = $("ia3dr-overlay-primary-select");
        if (sel) sel.value = latest.path;
        await _applyOverlayPrimary(latest.path);   // sets primary + sibling + arms editing + coverage
      }
    }
    _refreshCoverage();
  });

  // Primary h5 picker → setPrimary + per-cam sibling resolution.
  $("ia3dr-overlay-primary-select")?.addEventListener("change", (e) => {
    _applyOverlayPrimary(e.target.value);
  });

  // Likelihood threshold → setThreshold + label + coverage refresh (debounced).
  const thr = $("ia3dr-overlay-threshold");
  thr?.addEventListener("input", () => {
    const v = parseFloat(thr.value);
    _markerEditor?.setThreshold(v);
    const lbl = $("ia3dr-overlay-threshold-val");
    if (lbl) lbl.textContent = v.toFixed(2);
    _refreshCoverageDebounced();
  });

  // Marker size → markerEditor.setMarkerSize (re-renders) + label.
  const ms = $("ia3dr-overlay-marker-size");
  ms?.addEventListener("input", () => {
    _markerEditor?.setMarkerSize(parseInt(ms.value, 10));
    const lbl = $("ia3dr-overlay-marker-size-val");
    if (lbl) lbl.textContent = ms.value;
  });

  // Show names → markerEditor.setShowNames (all names vs hover-only).
  const showNames = $("ia3dr-overlay-show-names");
  showNames?.addEventListener("change", () => _markerEditor?.setShowNames(!!showNames.checked));

  // Show-all / hide-all: markerEditor has no show/hide-all API. No-ops.
  $("ia3dr-overlay-parts-all"); // no-op
  $("ia3dr-overlay-parts-none"); // no-op

  // Save Adjustments: markerEditor flushes each edit to the server edit-cache as
  // it happens; this commits the cache → primary .h5/.csv for BOTH cams.
  $("ia3dr-save-adjustments-btn")?.addEventListener("click", _iaSaveAdjustments);

  // Lock-BP checkbox → markerEditor.setLockBp. When checked, placing re-places the
  // same bodypart (no auto-advance) — used to correct a marker. (`L` is the keyframe
  // range-lock, so this is a checkbox, not a shortcut.)
  const lockBp = $("ia3dr-lock-bp");
  lockBp?.addEventListener("change", () => _markerEditor?.setLockBp(!!lockBp.checked));

  // Discard / Clear Frame: markerEditor exposes no discard/clear-frame API. No-ops.
  $("ia3dr-discard-adjustments-btn"); // no-op
  $("ia3dr-clear-frame-btn"); // no-op
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
  const primarySel = $("ia3dr-overlay-primary-select");
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
async function _reloadPrimaryAfterAnalysis(scorer) {
  _coverageCache.clear();
  const variants = await _fetchOverlayH5Variants();
  // Prefer the EXACT file the analysis just wrote: the output is the raw companion
  // `<stem><scorer>.h5` (ts=null). Selecting by scorer avoids _pickLatestKinematic
  // jumping to a pre-existing postproc run (which carries a newer `ts` and would
  // otherwise outrank the fresh companion). Fall back to the latest kinematic model
  // only when the scorer is missing or no variant matches.
  let target = null;
  if (scorer) target = variants.find((v) => (v.path || "").endsWith(scorer + ".h5")) || null;
  if (!target) target = _pickLatestKinematic(variants);
  const sel = $("ia3dr-overlay-primary-select");
  if (target && sel) {
    sel.value = target.path;
    await _applyOverlayPrimary(target.path);   // fresh setPrimary + sibling + arms editing + _refreshCoverage
  } else {
    _markerEditor?.invalidatePoses();
    _refreshCoverage();
  }
}

// Reserve the bp chip list's MAX height so per-frame checkmark toggles (which
// change chip width → re-wrap) can't reflow the layout and jump everything below.
// Measure with all checkmarks forced visible (widest), then pin min-height.
function _reserveBpChipHeight() {
  const c = $("ia3dr-bp-chips");
  if (!c) return;
  c.style.minHeight = "";              // reset to measure the natural tallest wrap
  c.classList.add("ia3dr-measuring");   // all checkmarks shown → widest chips
  const h = c.offsetHeight;
  c.classList.remove("ia3dr-measuring");
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
  if ($("ia3dr-finalize-toggle")?.checked) {
    _markerEditor.setEditable(true);
  }
  _refreshCoverage();
}

// Fetch likelihood-filtered marker-coverage for the active primary h5 + current
// threshold, cache by (h5, threshold), and redraw the main timeline. No-op unless
// the overlay is on with a primary h5.
async function _refreshCoverage() {
  const on = $("ia3dr-overlay-toggle")?.checked;
  if (!on || !_overlayPrimaryH5) { _coverageBuckets = null; _coverageFrames = null; _redrawSeekTimeline(); return; }
  const thr = parseFloat($("ia3dr-overlay-threshold")?.value ?? "0.6");
  const w = Math.max(200, Math.round($("ia3dr-seek-canvas")?.getBoundingClientRect().width || 600));
  // Pass the VIDEO frame count so coverage is bucketed in seek-bar space — the h5
  // may have fewer rows than the video has frames (DLC analyzed a prefix), so
  // marks must be placed by absolute frame, not compressed into the h5 length.
  const nf = _frameCount > 0 ? `&nframes=${_frameCount}` : "";
  const key = `${_overlayPrimaryH5}:${thr.toFixed(2)}:${w}:${_frameCount}`;
  if (_coverageCache.has(key)) {
    const c = _coverageCache.get(key);
    _coverageBuckets = c.buckets; _coverageFrames = c.frames; _redrawSeekTimeline(); return;
  }
  try {
    const data = await (await fetch(
      `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(_overlayPrimaryH5)}&threshold=${thr}&buckets=${w}${nf}`,
    )).json();
    const entry = { buckets: data.buckets || [], frames: data.frames || [] };
    _coverageCache.set(key, entry);
    // still the active request? (h5 + threshold + width + frame count unchanged)
    const curThr = parseFloat($("ia3dr-overlay-threshold")?.value ?? "0.6");
    const curW = Math.max(200, Math.round($("ia3dr-seek-canvas")?.getBoundingClientRect().width || 600));
    if (`${_overlayPrimaryH5}:${curThr.toFixed(2)}:${curW}:${_frameCount}` === key) {
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
  const on = $("ia3dr-finalize-toggle")?.checked;
  const cam0Video = _cam0Path();
  const _clear = () => { _finalizeCoverageBuckets = null; _finalizeCoverageFrames = null; _redrawFinalizeCoverage(); };
  if (!on || !cam0Video) { _clear(); return; }
  try {
    const st = await (await fetch(`/dlc/project/analysis-file/status?video_path=${encodeURIComponent(cam0Video)}`)).json();
    if (!st.initialized || !st.h5_path) { _clear(); return; }
    const w = Math.max(200, Math.round($("ia3dr-finalize-coverage")?.getBoundingClientRect().width || 600));
    // Bucket in seek-bar (video-frame) space so the finalize bar aligns with the
    // seek + 3D timelines even if the analyzed h5 is shorter than the video.
    const nf = _frameCount > 0 ? `&nframes=${_frameCount}` : "";
    const data = await (await fetch(
      `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(st.h5_path)}&mode=presence&buckets=${w}${nf}`,
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
  const btn = $("ia3dr-save-adjustments-btn");
  if (!_markerEditor || !_overlayPrimaryH5) return;
  const n0 = _markerEditor.getEditCount(0);
  const n1 = _markerEditor.getEditCount(1);
  if (n0 === 0 && n1 === 0) return;
  if (btn) btn.disabled = true;
  const st = $("ia3dr-overlay-status");
  try {
    // Send each cam's IN-MEMORY edits in the request body — the server applies
    // those directly, so Save no longer races the async marker-edit mirror.
    const targets = [];
    if (n0 > 0 && _overlayPrimaryH5) targets.push([0, _overlayPrimaryH5]);
    if (n1 > 0 && _siblingPrimaryH5) targets.push([1, _siblingPrimaryH5]);
    let anyErr = false;
    for (const [cam, h5] of targets) {
      const resp = await fetch("/dlc/viewer/save-marker-edits", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ h5, edits: _markerEditor.getEditsForSave(cam) }),
      });
      const data = await resp.json().catch(() => ({}));
      // We sent non-empty edits for this cam, so 0 frames applied means nothing
      // was written — surface it as a failure instead of a false "saved".
      if (!resp.ok || data.error || !data.frames_edited) anyErr = true;
    }
    // The save rewrote the h5 in place; the pose cache is version-less, so drop it
    // and re-render from the saved h5. Without this the edit visually snaps back to
    // the raw pose on the non-focused tile after a camera switch (looks "lost").
    if (!anyErr) _markerEditor.invalidatePoses();
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
  const el = $("ia3dr-curation-status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "fe-extract-status" + (isErr ? " err" : "");
  if (_curationMsgTimer) clearTimeout(_curationMsgTimer);
  if (msg && !isErr) {
    _curationMsgTimer = setTimeout(() => { el.textContent = ""; }, 4000);
  }
}

// Reveal #ia3dr-both-cams-label only when a sibling tile is mounted and curation
// is enabled.
function _updateBothCamsVisibility() {
  const both = $("ia3dr-both-cams-label");
  if (!both) return;
  const curationOn = !!$("ia3dr-curation-toggle")?.checked;
  const syncOn = !!_viewer && _viewer.tiles.length > 1;
  both.style.display = (syncOn && curationOn) ? "inline-flex" : "none";
}

// True when extraction should fan out to both cams: "both cams" ticked + sibling.
function _shouldDoubleUp() {
  const cb = $("ia3dr-both-cams");
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
  const toggle = $("ia3dr-curation-toggle");
  toggle?.addEventListener("change", () => {
    $("ia3dr-curation-controls")?.classList.toggle("hidden", !toggle.checked);
    _updateBothCamsVisibility();
  });

  // Extract Frame: raw PNG(s) into labeled-data (no CSV entry).
  // Extract the current raw frame as a PNG into labeled-data/ (no markers, no CSV
  // entry). Shared by the Dataset-Curation "Extract Frame" button and the finalize
  // panel's "Add current frame to labeled-data" button (each passes its own button +
  // status sink so feedback lands in the right place).
  async function _extractCurrentFrameToLabeledData(btn, status, forceBoth = false) {
    if (!_iaMode || _iaMode === "frames") {
      status("No video loaded — open a video first.", true);
      return;
    }
    if (btn) btn.disabled = true;
    status("Extracting…");
    // forceBoth: extract from BOTH videos whenever a sibling tile is mounted,
    // regardless of the "Extract from both cams" checkbox (single-cam falls back to one).
    const bothCams = (forceBoth && _viewer && _viewer.tiles.length > 1) || _shouldDoubleUp();
    if (bothCams) {
      const res = await _saveFramePair(_viewer.currentFrame());
      if (res.ok) status(_pairSavedMsg(res.body || {}));
      else status(`Extract failed: ${res.error || "unknown"}`, true);
    } else {
      try {
        const r = await fetch("/dlc/curator/extract-frame", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(_curatorBody()),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
        status(data.duplicate
          ? `Already extracted: ${data.saved}`
          : `Saved ${data.saved} (${data.folder}, #${data.frame_count})`);
      } catch (err) {
        status(`Extract failed: ${err.message}`, true);
      }
    }
    if (btn) btn.disabled = false;
  }
  const extractBtn = $("ia3dr-extract-frame-btn");
  extractBtn?.addEventListener("click", () => _extractCurrentFrameToLabeledData(extractBtn, _curStatus));
  // Finalize-panel twin: same action, forced to BOTH videos, feedback in #ia3dr-status.
  const addFrameBtn = $("ia3dr-add-frame-nomarkers-btn");
  addFrameBtn?.addEventListener("click", () => _extractCurrentFrameToLabeledData(addFrameBtn, _setStatus, true));

  // Add to Dataset.
  const addBtn = $("ia3dr-add-to-dataset-btn");
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
  const batchBtn = $("ia3dr-batch-add-btn");
  batchBtn?.addEventListener("click", async () => {
    if (!_iaMode || _iaMode === "frames") {
      _curStatus("No video loaded — open a video first.", true);
      return;
    }
    const count = Math.max(1, parseInt($("ia3dr-batch-count")?.value, 10) || 10);
    const step = Math.max(1, parseInt($("ia3dr-batch-step")?.value, 10) || 30);
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

// ── Triangulate (anipose init) consumer glue ─────────────────────────────────

let _triangulateChromeWired = false;

// Wire the Triangulate toggle (reveal/hide controls) and the anipose-init button.
// Phase 1: the button POSTs the selected cam0 path to /dlc-3d/anipose/init, which
// scaffolds the anipose calibration/ + pose-2d/ folders. Idempotent per module load.
function _wireTriangulateChrome() {
  if (_triangulateChromeWired) return;
  _triangulateChromeWired = true;

  const toggle = $("ia3dr-triangulate-toggle");
  toggle?.addEventListener("change", () => {
    $("ia3dr-triangulate-controls")?.classList.toggle("hidden", !toggle.checked);
    // Paint any already-triangulated coverage when the panel is opened.
    if (toggle.checked) _refreshTriangulateCoverage();
  });

  const btn = $("ia3dr-anipose-init-btn");
  btn?.addEventListener("click", async () => {
    const status = $("ia3dr-anipose-init-status");
    const setStatus = (msg, isErr = false) => {
      if (!status) return;
      status.textContent = msg || "";
      status.className = "fe-extract-status" + (isErr ? " err" : "");
    };
    const cam0Video = _cam0Path();
    if (!cam0Video) { setStatus("Pick a cam0 video first.", true); return; }

    btn.disabled = true;
    setStatus("Initializing anipose format…");
    try {
      const r = await fetch("/dlc-3d/anipose/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cam0_video: cam0Video }),
      });
      let data;
      try { data = await r.json(); } catch { data = null; }
      if (!r.ok) {
        setStatus(`Error: ${(data && data.error) || `HTTP ${r.status}`}`, true);
        return;
      }
      const p = data.pose_2d || {};
      const mark = (arr) => (arr && arr.length) ? "✓" : "—";
      let msg = `calibration/ ✓ · pose-2d: cam0 ${mark(p.cam0)}, cam1 ${mark(p.cam1)}`;
      if (data.warnings && data.warnings.length) {
        msg += " · " + data.warnings.join("; ");
      }
      setStatus(msg, !!(data.warnings && data.warnings.length));
    } catch (err) {
      setStatus(`Error: ${err.message}`, true);
    } finally {
      btn.disabled = false;
    }
  });

  // Phase 2: triangulate the current finalize keyframe window. Reads the SAME range
  // source as #ia3dr-btn-analyze-range-confined (_finalizeKW.getRange()), POSTs to
  // /dlc/project/triangulate/range, polls …/range/status to terminal, then refetches
  // /dlc/project/triangulate/coverage to draw the 3D bar. Gated on keyframe lock via
  // _refreshAnalyzeEnablement (same rangeOk condition as the confined analyze button).
  const rangeBtn = $("ia3dr-triangulate-range-btn");
  rangeBtn?.addEventListener("click", async () => {
    const status = $("ia3dr-triangulate-range-status");
    const setStatus = (msg, isErr = false) => {
      if (!status) return;
      status.textContent = msg || "";
      status.className = "fe-extract-status" + (isErr ? " err" : "");
    };
    const cam0Video = _cam0Path();
    if (!cam0Video) { setStatus("Pick a cam0 video first.", true); return; }
    const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
    const startFrame = rng.start, nFrames = rng.n;
    if (!(nFrames >= 1)) { setStatus("Lock a valid keyframe range first.", true); return; }

    rangeBtn.disabled = true;
    setStatus(`Triangulating ${nFrames} frames from ${startFrame}…`);
    // One-range = a batch of 1: register ONE aggregate row up-front, finalize below.
    const batchId = crypto.randomUUID();
    _batchJob("start", batchId, { total: 1, video: cam0Video, done: 0, stage: "0/1" });
    try {
      const enq = await _enqueueTriangulateRange(cam0Video, startFrame, nFrames);
      if (!enq.req_id) {
        setStatus(`Error: ${enq.error}`, true);
        _batchJob("done", batchId, { done: 0, skipped: 0, stage: `error — ${enq.error}` });
        return;
      }
      const done = await _pollTriangulateReq(enq.req_id, (d) => {
        const pct = (d && typeof d.progress === "number") ? ` ${d.progress}%` : "";
        setStatus(`${(d && d.stage) || "working"}…${pct}`);
      });
      if (done.state === "SUCCESS") {
        const res = done.result || {};
        const end = startFrame + nFrames - 1;
        if (res.skipped) {
          // Range lies beyond the analyzed 2D data — nothing to triangulate.
          setStatus(`No 2D data in frames ${startFrame}–${end} — skipped.`);
        } else {
          setStatus(`3D ✓ frames ${startFrame}–${end}${res.pair_name ? ` → ${res.pair_name}` : ""}`);
          await _refreshTriangulateCoverage();
          // Newly-triangulated frames → refetch + reload the 3D pose viewer (no-op
          // until its panel has been opened at least once).
          if (_pose3d && _pose3dLoaded) await _loadPose3d();
        }
        _batchJob("done", batchId, {
          done: res.skipped ? 0 : 1, skipped: res.skipped ? 1 : 0,
          stage: res.skipped ? "skipped — no 2D data" : "3D ✓",
        });
      } else {
        setStatus(`Error: ${(done && done.error) || "triangulation failed"}`, true);
        _batchJob("done", batchId, { done: 0, skipped: 0, stage: `error — ${(done && done.error) || "triangulation failed"}` });
      }
    } catch (err) {
      setStatus(`Error: ${err.message}`, true);
    } finally {
      // Restore the gated disabled-state (locked → enabled, else disabled).
      _refreshAnalyzeEnablement();
    }
  });
}

// ── Anipose Parameters editor (config.toml) ──────────────────────────────────
//
// Mirrors _wireTriangulateChrome's idempotent-wire pattern. The panel exposes the
// numeric/toggle params of [triangulation], [filter] (2D) and [filter3d]. On first
// open (with a cam0 selected) we GET the persisted params and populate the fields;
// Save POSTs them back. Backed by the frozen GET/POST /dlc/project/triangulate/config
// contract (routes built in the main repo).

// Field descriptors: DOM id-suffix → {section, key, type}. Only fields whose input
// exists in the DOM are ever read/written, so this stays in lockstep with the markup.
const _PARAM_FIELDS = [
  // [triangulation]
  { id: "ia3dr-param-tri-cam_regex",             section: "triangulation", key: "cam_regex",              type: "str"  },
  { id: "ia3dr-param-tri-ransac",                section: "triangulation", key: "ransac",                 type: "bool" },
  { id: "ia3dr-param-tri-optim",                 section: "triangulation", key: "optim",                  type: "bool" },
  { id: "ia3dr-param-tri-optim_chunking",        section: "triangulation", key: "optim_chunking",         type: "bool" },
  { id: "ia3dr-param-tri-scale_smooth",          section: "triangulation", key: "scale_smooth",           type: "num"  },
  { id: "ia3dr-param-tri-scale_length",          section: "triangulation", key: "scale_length",           type: "num"  },
  { id: "ia3dr-param-tri-scale_length_weak",     section: "triangulation", key: "scale_length_weak",      type: "num"  },
  { id: "ia3dr-param-tri-reproj_error_threshold",section: "triangulation", key: "reproj_error_threshold", type: "num"  },
  { id: "ia3dr-param-tri-score_threshold",       section: "triangulation", key: "score_threshold",        type: "num"  },
  { id: "ia3dr-param-tri-n_deriv_smooth",        section: "triangulation", key: "n_deriv_smooth",         type: "num"  },
  { id: "ia3dr-param-tri-optim_chunking_size",   section: "triangulation", key: "optim_chunking_size",    type: "num"  },
  { id: "ia3dr-param-tri-constraints",           section: "triangulation", key: "constraints",            type: "list" },
  // [filter] (2D)
  { id: "ia3dr-param-filter-enabled",            section: "filter", key: "enabled",           type: "bool" },
  { id: "ia3dr-param-filter-spline",             section: "filter", key: "spline",            type: "bool" },
  { id: "ia3dr-param-filter-multiprocessing",    section: "filter", key: "multiprocessing",   type: "bool" },
  { id: "ia3dr-param-filter-type",               section: "filter", key: "type",              type: "str"  },
  { id: "ia3dr-param-filter-medfilt",            section: "filter", key: "medfilt",           type: "num"  },
  { id: "ia3dr-param-filter-offset_threshold",   section: "filter", key: "offset_threshold",  type: "num"  },
  { id: "ia3dr-param-filter-score_threshold",    section: "filter", key: "score_threshold",   type: "num"  },
  { id: "ia3dr-param-filter-n_back",             section: "filter", key: "n_back",            type: "num"  },
  // [filter3d]
  { id: "ia3dr-param-f3d-enabled",               section: "filter3d", key: "enabled",          type: "bool" },
  { id: "ia3dr-param-f3d-medfilt",               section: "filter3d", key: "medfilt",          type: "num"  },
  { id: "ia3dr-param-f3d-offset_threshold",      section: "filter3d", key: "offset_threshold", type: "num"  },
];

// constraints (skeleton) <-> textarea: one "A, B" pair per line.
function _constraintsToText(list) {
  return (Array.isArray(list) ? list : [])
    .filter((p) => Array.isArray(p) && p.length === 2)
    .map((p) => `${p[0]}, ${p[1]}`).join("\n");
}
function _textToConstraints(text) {
  return String(text || "").split("\n")
    .map((line) => line.split(",").map((s) => s.trim()).filter(Boolean))
    .filter((pair) => pair.length === 2);
}

// Populate the fields from a {triangulation,filter,filter3d} params object.
function _populateParamFields(params) {
  params = params || {};
  for (const f of _PARAM_FIELDS) {
    const el = $(f.id);
    if (!el) continue;
    const sect = params[f.section];
    if (!sect || !(f.key in sect)) continue;
    const v = sect[f.key];
    if (f.type === "bool") el.checked = !!v;
    else if (f.type === "list") el.value = _constraintsToText(v);
    else el.value = (v == null) ? "" : String(v);
  }
}

// Read the fields back into {triangulation,filter,filter3d} with correct JS types.
// A field is included only if its input exists in the DOM.
function _readParamFields() {
  const out = { triangulation: {}, filter: {}, filter3d: {} };
  for (const f of _PARAM_FIELDS) {
    const el = $(f.id);
    if (!el) continue;
    if (f.type === "bool") out[f.section][f.key] = !!el.checked;
    else if (f.type === "num") out[f.section][f.key] = Number(el.value);
    else if (f.type === "list") out[f.section][f.key] = _textToConstraints(el.value);
    else out[f.section][f.key] = String(el.value);
  }
  return out;
}

let _paramsChromeWired = false;
let _paramsPrefilled = false;   // GET-prefill runs once, on first open with a cam0

function _wireParamsChrome() {
  if (_paramsChromeWired) return;
  _paramsChromeWired = true;

  const status = $("ia3dr-params-status");
  const saveBtn = $("ia3dr-params-save");
  let _cSuggestion = [];   // skeleton pairs from the last GET (Fill-from-skeleton)
  const setStatus = (msg, isErr = false) => {
    if (!status) return;
    status.textContent = msg || "";
    status.className = "fe-extract-status" + (isErr ? " err" : "");
  };

  // "Fill from skeleton" → drop the backend-suggested finger-chain pairs into the
  // constraints textarea (user still needs to tick `optim` + Save to enforce them).
  $("ia3dr-param-tri-constraints-fill")?.addEventListener("click", () => {
    const ta = $("ia3dr-param-tri-constraints");
    if (!ta) return;
    if (!_cSuggestion.length) {
      setStatus("No skeleton suggestion — no Wrist/MCP/PIP/DIP bodyparts found.", true);
      return;
    }
    ta.value = _constraintsToText(_cSuggestion);
    setStatus(`Filled ${_cSuggestion.length} skeleton pairs — enable "optim" then Save.`);
  });

  // GET the persisted params and populate the fields. Guards when config/cam0 is
  // absent (400) → disable Save + show the error in status.
  async function _prefill() {
    const cam0Video = _cam0Path();
    if (!cam0Video) { if (saveBtn) saveBtn.disabled = true; setStatus("Pick a cam0 video first.", true); return; }
    try {
      const r = await fetch(`/dlc/project/triangulate/config?cam0_video=${encodeURIComponent(cam0Video)}`);
      let data;
      try { data = await r.json(); } catch { data = null; }
      if (!r.ok) {
        if (saveBtn) saveBtn.disabled = true;
        setStatus(`${(data && data.error) || `HTTP ${r.status}`}`, true);
        return;
      }
      _populateParamFields(data);
      _cSuggestion = Array.isArray(data.constraints_suggestion) ? data.constraints_suggestion : [];
      _paramsPrefilled = true;
      if (saveBtn) saveBtn.disabled = false;
      setStatus("");
    } catch (err) {
      if (saveBtn) saveBtn.disabled = true;
      setStatus(`Error: ${err.message}`, true);
    }
  }

  const toggle = $("ia3dr-params-toggle");
  toggle?.addEventListener("change", () => {
    const on = !!toggle.checked;
    $("ia3dr-params-controls")?.classList.toggle("hidden", !on);
    // Prefill on first open (and whenever a cam0 is selected but we haven't yet).
    if (on && !_paramsPrefilled) _prefill();
  });

  saveBtn?.addEventListener("click", async () => {
    const cam0Video = _cam0Path();
    if (!cam0Video) { setStatus("Pick a cam0 video first.", true); return; }
    const params = _readParamFields();
    saveBtn.disabled = true;
    setStatus("Saving…");
    try {
      const r = await fetch("/dlc/project/triangulate/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cam0_video: cam0Video, params }),
      });
      let data;
      try { data = await r.json(); } catch { data = null; }
      if (!r.ok) {
        setStatus(`${(data && data.error) || `HTTP ${r.status}`}`, true);
        return;
      }
      // Re-populate from the persisted echo so the UI reflects what was written.
      if (data && data.params) _populateParamFields(data.params);
      setStatus("saved ✓");
    } catch (err) {
      setStatus(`Error: ${err.message}`, true);
    } finally {
      saveBtn.disabled = false;
    }
  });
}

// ── 3D pose viewer (three.js spike) ──────────────────────────────────────────
//
// Mirrors _wireTriangulateChrome's idempotent-wire pattern. On first check of the
// #ia3dr-pose3d-toggle we reveal the controls, lazily create + init() the isolated
// pose3d_viewer, fetch the frozen /dlc/project/triangulate/poses-3d contract,
// load() it, and showFrame(currentFrame). All three.js stays inside pose3d_viewer.js.
function _wirePose3dChrome() {
  if (_pose3dChromeWired) return;
  _pose3dChromeWired = true;

  const toggle = $("ia3dr-pose3d-toggle");
  toggle?.addEventListener("change", async () => {
    const on = !!toggle.checked;
    $("ia3dr-pose3d-controls")?.classList.toggle("hidden", !on);
    if (!on) { _stopMirrorLoop(); return; }

    // Lazily create + init the viewer once.
    if (!_pose3d) {
      const canvas = $("ia3dr-pose3d-canvas");
      const statusEl = $("ia3dr-pose3d-status");
      if (!canvas) return;
      _pose3d = makePose3dViewer({ canvas, statusEl, onViewChange: () => _savePose3dViewPrefs() });
      _pose3d.init();
      // Apply the per-project persisted background colour (if any) once inited.
      await _loadPose3dBgColor();
      // Apply the per-project persisted view prefs (canvas size + axis flips).
      await _loadPose3dViewPrefs();
    }
    await _loadPose3d();
  });

  // Reset view re-fits, then persists the fitted camera so a later reload doesn't
  // restore the pre-reset view over it.
  const _resetAndPersist = () => { _pose3d?.resetView(); _savePose3dViewPrefs(); };
  const resetBtn = $("ia3dr-pose3d-reset");
  resetBtn?.addEventListener("click", _resetAndPersist);

  // ── Part 2: on-screen 3D controls → viewer methods ─────────────────────────
  const ORBIT_STEP = Math.PI / 12;   // 15° per press
  const ZOOM_FACTOR = 1.2;
  $("ia3dr-pose3d-home")?.addEventListener("click", _resetAndPersist);
  // On-screen zoom/orbit change the camera programmatically (no OrbitControls
  // 'end'), so persist the view after each press.
  const _nudge = (fn) => { fn(); _savePose3dViewPrefs(); };
  $("ia3dr-pose3d-zoom-in")?.addEventListener("click", () => _nudge(() => _pose3d?.zoomBy(1 / ZOOM_FACTOR)));
  $("ia3dr-pose3d-zoom-out")?.addEventListener("click", () => _nudge(() => _pose3d?.zoomBy(ZOOM_FACTOR)));
  $("ia3dr-pose3d-orbit-left")?.addEventListener("click", () => _nudge(() => _pose3d?.orbit(-ORBIT_STEP, 0)));
  $("ia3dr-pose3d-orbit-right")?.addEventListener("click", () => _nudge(() => _pose3d?.orbit(ORBIT_STEP, 0)));
  $("ia3dr-pose3d-orbit-up")?.addEventListener("click", () => _nudge(() => _pose3d?.orbit(0, -ORBIT_STEP)));
  $("ia3dr-pose3d-orbit-down")?.addEventListener("click", () => _nudge(() => _pose3d?.orbit(0, ORBIT_STEP)));

  // ── Part 3: quality-threshold number fields → setThresholds (live, no reload) ─
  const scoreThr = $("ia3dr-pose3d-score-thr");
  scoreThr?.addEventListener("input", () => {
    _pose3d?.setThresholds({ score: parseFloat(scoreThr.value) });
  });
  const errThr = $("ia3dr-pose3d-error-thr");
  errThr?.addEventListener("input", () => {
    _pose3d?.setThresholds({ error: parseFloat(errThr.value) });
  });

  // ── 3D marker size → setMarkerSize (scales the spheres live, no reload) ─────
  const markerSize = $("ia3dr-pose3d-marker-size");
  markerSize?.addEventListener("input", () => {
    _pose3d?.setMarkerSize(parseFloat(markerSize.value));
  });

  // ── Background colour → setBackground (live) + debounced per-project save ────
  const bg = $("ia3dr-pose3d-bg");
  bg?.addEventListener("input", () => {
    _pose3d?.setBackground(bg.value);
    if (_bgSaveTimer) clearTimeout(_bgSaveTimer);
    _bgSaveTimer = setTimeout(() => {
      fetch("/dlc/project/ui-setting", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "pose3d_bg_color", value: bg.value }),
      }).catch(() => {});
    }, 400);
  });

  // ── View width/height → size the canvas box live (ResizeObserver repaints) ──
  // + debounced per-project save under the consolidated pose3d_view_prefs key.
  const viewW = $("ia3dr-pose3d-view-w");
  const viewH = $("ia3dr-pose3d-view-h");
  const onViewSize = () => { _applyPose3dViewSize(); _savePose3dViewPrefs(); };
  viewW?.addEventListener("input", onViewSize);
  viewH?.addEventListener("input", onViewSize);

  // ── Flip X/Y/Z → setFlip (live) + debounced per-project save ────────────────
  const onFlip = () => {
    _pose3d?.setFlip(
      !!$("ia3dr-pose3d-flip-x")?.checked,
      !!$("ia3dr-pose3d-flip-y")?.checked,
      !!$("ia3dr-pose3d-flip-z")?.checked,
    );
    _savePose3dViewPrefs();
  };
  $("ia3dr-pose3d-flip-x")?.addEventListener("change", onFlip);
  $("ia3dr-pose3d-flip-y")?.addEventListener("change", onFlip);
  $("ia3dr-pose3d-flip-z")?.addEventListener("change", onFlip);

  // ── Grid / origin helpers → show-hide (live) + debounced per-project save ───
  const onHelpers = () => {
    _pose3d?.setGrid(!!$("ia3dr-pose3d-grid")?.checked);
    _pose3d?.setOrigin(!!$("ia3dr-pose3d-origin")?.checked);
    _savePose3dViewPrefs();
  };
  $("ia3dr-pose3d-grid")?.addEventListener("change", onHelpers);
  $("ia3dr-pose3d-origin")?.addEventListener("change", onHelpers);

  // ── Part 4: median re-filter → POST /dlc/project/triangulate/refilter ──────
  $("ia3dr-pose3d-apply")?.addEventListener("click", _applyPose3dRefilter);
}

// Clamp + apply the width/height inputs to the canvas box inline size (px). The
// canvas is width/height:100% and pose3d_viewer observes it via ResizeObserver,
// so the renderer repaints automatically — no viewer method needed here.
function _applyPose3dViewSize() {
  const box = $("ia3dr-pose3d-canvas-box");
  if (!box) return;
  const w = Math.min(1600, Math.max(200, parseInt($("ia3dr-pose3d-view-w")?.value, 10) || 460));
  const h = Math.min(1200, Math.max(200, parseInt($("ia3dr-pose3d-view-h")?.value, 10) || 520));
  box.style.width = w + "px";
  box.style.height = h + "px";
}

// Serialize the current {w,h,flipX,flipY,flipZ} and save (debounced) under the
// consolidated pose3d_view_prefs ui-setting key. Best-effort — a failed POST is
// swallowed (mirrors the background-colour save flow).
function _savePose3dViewPrefs() {
  const prefs = {
    w: Math.min(1600, Math.max(200, parseInt($("ia3dr-pose3d-view-w")?.value, 10) || 460)),
    h: Math.min(1200, Math.max(200, parseInt($("ia3dr-pose3d-view-h")?.value, 10) || 520)),
    flipX: !!$("ia3dr-pose3d-flip-x")?.checked,
    flipY: !!$("ia3dr-pose3d-flip-y")?.checked,
    flipZ: !!$("ia3dr-pose3d-flip-z")?.checked,
    gridOn: !!$("ia3dr-pose3d-grid")?.checked,
    originOn: !!$("ia3dr-pose3d-origin")?.checked,
    cam: (_pose3d && _pose3d.getCameraState) ? _pose3d.getCameraState() : null,
  };
  // Keep the in-memory camera current so a subsequent pose reload restores THIS view.
  if (prefs.cam) _savedCamState = prefs.cam;
  if (_viewPrefsSaveTimer) clearTimeout(_viewPrefsSaveTimer);
  _viewPrefsSaveTimer = setTimeout(() => {
    fetch("/dlc/project/ui-setting", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: "pose3d_view_prefs", value: JSON.stringify(prefs) }),
    }).catch(() => {});
  }, 400);
}

// Load the persisted 3D background colour (per project) and apply it to the viewer
// + sync the color input. Called on pose3d load; absent/invalid → keep the #12141a
// default. Best-effort: a fetch failure leaves the default untouched.
async function _loadPose3dBgColor() {
  if (!_pose3d) return;
  try {
    const data = await (await fetch("/dlc/project/ui-setting?key=pose3d_bg_color")).json();
    const hex = data && data.value;
    if (!hex) return;
    _pose3d.setBackground(hex);
    const bg = $("ia3dr-pose3d-bg");
    if (bg) bg.value = hex;
  } catch (_) { /* keep the default background */ }
}

// Load the persisted 3D view prefs (per project) — canvas size + axis flips — and
// apply them to the canvas box + viewer, syncing the number inputs + checkboxes.
// Called on pose3d load; absent/invalid → keep the 460×520 / no-flip defaults.
// Best-effort: a fetch/parse failure leaves the defaults untouched.
async function _loadPose3dViewPrefs() {
  if (!_pose3d) return;
  try {
    const data = await (await fetch("/dlc/project/ui-setting?key=pose3d_view_prefs")).json();
    if (!data || !data.value) return;
    const prefs = JSON.parse(data.value);
    if (!prefs || typeof prefs !== "object") return;
    // Size: sync the inputs (clamped by _applyPose3dViewSize) then apply.
    const w = Number(prefs.w), h = Number(prefs.h);
    const viewW = $("ia3dr-pose3d-view-w");
    const viewH = $("ia3dr-pose3d-view-h");
    if (viewW && Number.isFinite(w) && w > 0) viewW.value = String(w);
    if (viewH && Number.isFinite(h) && h > 0) viewH.value = String(h);
    _applyPose3dViewSize();
    // Flips: sync the checkboxes then push to the viewer.
    const fx = !!prefs.flipX, fy = !!prefs.flipY, fz = !!prefs.flipZ;
    const cbX = $("ia3dr-pose3d-flip-x");
    const cbY = $("ia3dr-pose3d-flip-y");
    const cbZ = $("ia3dr-pose3d-flip-z");
    if (cbX) cbX.checked = fx;
    if (cbY) cbY.checked = fy;
    if (cbZ) cbZ.checked = fz;
    _pose3d.setFlip(fx, fy, fz);
    // Helpers: sync the checkboxes then push to the viewer (absent → default off).
    const gridOn = !!prefs.gridOn, originOn = !!prefs.originOn;
    const cbGrid = $("ia3dr-pose3d-grid");
    const cbOrigin = $("ia3dr-pose3d-origin");
    if (cbGrid) cbGrid.checked = gridOn;
    if (cbOrigin) cbOrigin.checked = originOn;
    _pose3d.setGrid(gridOn);
    _pose3d.setOrigin(originOn);
    // Camera (zoom/rotation): stash it — applied after the first pose load()
    // (which auto-fits), and after every reload, via _loadPose3d.
    _savedCamState = (prefs.cam && Array.isArray(prefs.cam.pos)) ? prefs.cam : null;
  } catch (_) { /* keep the default view prefs */ }
}

// Composite the MAIN viewer's current-frame tiles into the mini-cam <canvas>es
// (read-only). Per cam we draw the frame image (tile.imgEl) then the marker
// overlay canvas (tile.canvasEl) on top, scaled proportionally into the smaller
// mini rect. The overlay canvas already reflects every original adjustment
// (threshold / marker-size / overlay on-off / bodypart visibility), so the mirror
// reproduces the original exactly for free. Each wrapper hides when its tile /
// frame img is absent (single-cam). No-op when the 3D panel is closed.
function _mirrorPose3dCams() {
  if (!_viewer || !$("ia3dr-pose3d-toggle")?.checked) return;
  const draw = (canvasId, wrapId, tileIdx) => {
    const canvas = $(canvasId);
    if (!canvas) return;
    const wrap = $(wrapId);
    const tile = _viewer.getTile(tileIdx);
    const img = tile && tile.imgEl;
    // Frame not loaded (single-cam, or naturalWidth still 0) → hide + skip.
    if (!img || !img.naturalWidth) { wrap?.classList.add("hidden"); return; }
    // DISPLAY size = the ORIGINAL tile's current rendered size, so the duplicate
    // tracks the Viewer-size zoom (#ia3dr-zoom) 1:1. Fall back to natural size if
    // the original isn't laid out yet.
    const rect = img.getBoundingClientRect();
    const dispW = Math.max(1, Math.round(rect.width || img.clientWidth || img.naturalWidth));
    const dispH = Math.max(1, Math.round(rect.height || dispW * img.naturalHeight / img.naturalWidth));
    if (canvas.style.width !== dispW + "px") canvas.style.width = dispW + "px";
    if (canvas.style.height !== dispH + "px") canvas.style.height = dispH + "px";
    // Backing store: cap to the frame's native resolution for sharpness without
    // allocating a huge canvas when the original is zoomed way up.
    const bw = Math.max(1, Math.min(dispW, img.naturalWidth));
    const bh = Math.max(1, Math.round(bw * img.naturalHeight / img.naturalWidth));
    if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, bw, bh);
    // Guarded: an overlay canvas of size 0 (transient mid-resize) makes drawImage
    // throw — swallow so a bad frame doesn't kill the loop.
    try {
      ctx.drawImage(img, 0, 0, bw, bh);
      if (tile.canvasEl) ctx.drawImage(tile.canvasEl, 0, 0, bw, bh);
    } catch (_) { /* transient bad size — skip this frame */ }
    wrap?.classList.remove("hidden");
  };
  draw("ia3dr-pose3d-cam0", "ia3dr-pose3d-cam0-wrap", 0);
  draw("ia3dr-pose3d-cam1", "ia3dr-pose3d-cam1-wrap", 1);
  // NOTE: the 3D viewport size is now driven explicitly by the view width/height
  // inputs (_applyPose3dViewSize → #ia3dr-pose3d-canvas-box). The old auto-cap that
  // pinned the container to a single camera's width was removed — it clobbered the
  // width control every mirror tick (height was unaffected, so only width "stuck").
}

// Lightweight requestAnimationFrame loop that keeps the mini-cams composited
// while the 3D panel is open. The main frame image + overlay canvas both update
// async, so a one-shot mirror can catch a stale frame/overlay; the continuous
// loop is the source of truth. Throttled to ~30fps; a single handle guarantees it
// never leaks (start is idempotent, stop cancels). No-op body while the panel is
// closed or 3D isn't loaded.
function _startMirrorLoop() {
  if (_mirrorRaf != null) return;
  const tick = (ts) => {
    _mirrorRaf = requestAnimationFrame(tick);
    if (ts - _mirrorLastTs < 33) return;   // ~30fps throttle
    _mirrorLastTs = ts;
    if (_pose3dLoaded && $("ia3dr-pose3d-toggle")?.checked) _mirrorPose3dCams();
  };
  _mirrorRaf = requestAnimationFrame(tick);
}

function _stopMirrorLoop() {
  if (_mirrorRaf != null) { cancelAnimationFrame(_mirrorRaf); _mirrorRaf = null; }
}

// After a load(), configure the error slider's upper bound + default from the
// viewer's error_max (show-all = max), then sync both thresholds into the viewer.
function _configurePose3dErrorSlider() {
  if (!_pose3d) return;
  const em = _pose3d.getErrorMax ? _pose3d.getErrorMax() : null;
  const slider = $("ia3dr-pose3d-error-thr");   // now a number field
  if (slider && em != null && Number.isFinite(em) && em > 0) {
    slider.max = String(em);
    slider.step = String(Math.max(em / 100, 1e-6));
    slider.value = String(em);
  }
  // Push the current slider values into the viewer so the gate matches the UI.
  const sv = parseFloat($("ia3dr-pose3d-score-thr")?.value ?? "0");
  const ev = parseFloat(slider?.value);
  _pose3d.setThresholds({
    score: Number.isFinite(sv) ? sv : 0,
    error: Number.isFinite(ev) ? ev : undefined,
  });
}

// Part 4 — Apply the median re-filter: POST the current medfilt/offset, then on
// success refetch the filtered poses-3d + reload the viewer (which reconfigures
// the error slider + jumps to the current frame). Errors go to the status span.
async function _applyPose3dRefilter() {
  const btn = $("ia3dr-pose3d-apply");
  const statusEl = $("ia3dr-pose3d-refilter-status");
  const cam0Video = _cam0Path();
  if (!cam0Video) {
    if (statusEl) statusEl.textContent = "Pick a cam0 video first.";
    return;
  }
  const medfilt = parseInt($("ia3dr-pose3d-medfilt")?.value, 10) || 17;
  const offset = parseFloat($("ia3dr-pose3d-offset")?.value);
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.textContent = "Filtering…";
  try {
    const r = await fetch("/dlc/project/triangulate/refilter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cam0_video: cam0Video,
        medfilt,
        offset_threshold: Number.isFinite(offset) ? offset : 15,
      }),
    });
    let data;
    try { data = await r.json(); } catch { data = null; }
    if (!r.ok || !data || data.error) {
      if (statusEl) statusEl.textContent = `Error: ${(data && data.error) || `HTTP ${r.status}`}`;
      return;
    }
    if (statusEl) statusEl.textContent = `Filtered ✓ (medfilt ${data.medfilt ?? medfilt})`;
    // Refetch source=filtered + reload → reconfigures the error slider + showFrame.
    await _loadPose3d();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Fetch the poses-3d contract for the current cam0 video (filtered source),
// load() it into the viewer, then jump it to the player's current frame. Sets
// _pose3dLoaded so the frameChange subscription starts driving showFrame.
async function _loadPose3d() {
  if (!_pose3d) return;
  const statusEl = $("ia3dr-pose3d-status");
  const cam0Video = _cam0Path();
  if (!cam0Video) {
    if (statusEl) statusEl.textContent = "Pick a cam0 video first.";
    return;
  }
  if (statusEl) statusEl.textContent = "Loading 3D…";
  try {
    const url = `/dlc/project/triangulate/poses-3d?cam0_video=${encodeURIComponent(cam0Video)}&source=filtered`;
    const r = await fetch(url);
    let data;
    try { data = await r.json(); } catch { data = null; }
    if (!r.ok || !data) {
      if (statusEl) statusEl.textContent = `Error: ${(data && data.error) || `HTTP ${r.status}`}`;
      return;
    }
    _pose3d.load(data);
    _pose3dLoaded = true;
    // Restore the persisted camera (zoom/rotation) over the auto-fit that load()
    // just did; if none saved, the fit stands.
    if (_savedCamState && _pose3d.setCameraState) _pose3d.setCameraState(_savedCamState);
    // Configure the error slider (max/default) from the freshly-loaded data and
    // sync both thresholds into the viewer's gate.
    _configurePose3dErrorSlider();
    // Seek the 3D pose to whatever frame the 2D player is on.
    if (_viewer) _pose3d.showFrame(_viewer.currentFrame());
    // Mirror the mini-cams immediately so the composite shows without waiting for
    // the next frameChange, then start the continuous rAF mirror loop (source of
    // truth — idempotent, so a refilter reload won't spawn a second loop).
    _mirrorPose3dCams();
    _startMirrorLoop();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
  }
}

// Enqueue ONE triangulate-range req with retry on TRANSIENT failures. A gunicorn
// worker recycling mid-request returns 502; a long tag batch (100+ ranges) must not
// abort on a single hiccup. Retries on 5xx / network errors with linear backoff; a
// 4xx (real client error) stops immediately. Re-submitting a range is idempotent
// (same frames → same 3D overwrite), so a duplicate from a lost-response retry is
// harmless. Returns { req_id } on success or { error } after exhausting tries.
async function _enqueueTriangulateRange(cam0Video, startFrame, nFrames, tries = 4) {
  let lastErr = "";
  for (let attempt = 0; attempt < tries; attempt++) {
    if (attempt > 0) await new Promise((res) => setTimeout(res, 1000 * attempt));  // 1s,2s,3s
    try {
      const resp = await fetch("/dlc/project/triangulate/range", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cam0_video: cam0Video, start_frame: startFrame, n_frames: nFrames }),
      });
      let data = null;
      try { data = await resp.json(); } catch { data = null; }
      if (resp.status === 202 && data && data.req_id) return { req_id: data.req_id };
      if (resp.status >= 500 || resp.status === 202) {   // 5xx or a 202 w/o req_id → transient, retry
        lastErr = (data && data.error) || `HTTP ${resp.status}`;
        continue;
      }
      return { error: (data && data.error) || `HTTP ${resp.status}` };   // 4xx → real error, stop
    } catch (e) {
      lastErr = e.message || "network error";   // network failure → retry
    }
  }
  return { error: lastErr || "request failed after retries" };
}

// Poll one triangulate-range req_id to terminal state, per the
// /dlc/project/triangulate/range/status contract: { state, progress, stage, error,
// result }. Mirrors _pollReq's setInterval + _activePolls pattern but resolves on the
// contract's SUCCESS/FAILURE states. `onProgress(d)` fires on each non-terminal tick.
function _pollTriangulateReq(reqId, onProgress) {
  return new Promise((resolve) => {
    let elapsedMs = 0;
    const MAX_MS = 10 * 60 * 1000;   // 10 min hard cap → treat as failed
    const t = setInterval(async () => {
      elapsedMs += 500;
      if (elapsedMs >= MAX_MS) {
        clearInterval(t); _activePolls.delete(t);
        resolve({ state: "FAILURE", error: "timed out waiting for triangulation" });
        return;
      }
      try {
        const r = await fetch(`/dlc/project/triangulate/range/status?req_id=${reqId}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d.state === "SUCCESS" || d.state === "FAILURE") {
          clearInterval(t); _activePolls.delete(t); resolve(d);
        } else if (onProgress) {
          onProgress(d);
        }
      } catch (e) { /* keep polling */ }
    }, 500);
    _activePolls.add(t);
  });
}

// Fetch the 3D coverage buckets for the current cam0 video and draw them onto the
// #ia3dr-triangulate-coverage canvas (reuses _drawCoverageBar; the endpoint returns no
// per-bucket frames, so it falls back to bucket-space rects). Absent canonical → all
// zeros → an empty bar (not an error).
async function _refreshTriangulateCoverage() {
  const canvas = $("ia3dr-triangulate-coverage");
  const cam0Video = _cam0Path();
  if (!canvas || !cam0Video) { _triCoverageBuckets = null; return; }
  const w = Math.max(200, Math.round(canvas.getBoundingClientRect().width || 600));
  // Pass the video frame count (seek-bar scale) so the 3D bar spans the whole
  // video and aligns with the seek / finalized timelines — the canonical only
  // extends to the last-triangulated frame.
  const nf = _frameCount > 0 ? `&nframes=${_frameCount}` : "";
  try {
    const data = await (await fetch(
      `/dlc/project/triangulate/coverage?cam0_video=${encodeURIComponent(cam0Video)}&buckets=${w}${nf}`,
    )).json();
    _triCoverageBuckets = data.buckets || [];
    _redrawTriangulateCoverage();
  } catch (_) { /* leave the 3D bar empty */ }
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
      pill.className = "ia3dr-ptag";
      pill.appendChild(document.createTextNode(t + " "));
      const x = document.createElement("span");
      x.className = "x"; x.textContent = "×";
      x.addEventListener("click", (ev) => { ev.stopPropagation(); tags = removeTag(tags, t); render(); save(); });
      pill.appendChild(x);
      pill.addEventListener("click", () => { const el = input(); if (el) { el.value = t; el.dispatchEvent(new Event("input", { bubbles: true })); } });
      c.appendChild(pill);
    }
    const add = document.createElement("span");
    add.className = "ia3dr-ptag ia3dr-ptag-add"; add.textContent = "+ tag";
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
  _postfixTags = _makeQuickTags({ settingKey: "postfix_tags", containerId: "ia3dr-postfix-tags", inputId: "ia3dr-finalize-clip-postfix" });
  _statusTags  = _makeQuickTags({ settingKey: "status_tags",  containerId: "ia3dr-status-tags",  inputId: "ia3dr-status-input" });
  _noteTags    = _makeQuickTags({ settingKey: "note_tags",    containerId: "ia3dr-note-tags",    inputId: "ia3dr-note-input" });
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
  const nameEl = $("ia3dr-selected-name");
  if (nameEl) nameEl.textContent = name;
  try {
    const info = await (await fetch(`/dlc/project/video-info/${encodeURIComponent(name)}`)).json();
    _fps = info.fps || 30;
    _frameCount = info.frame_count || 0;
    if (info.abs_path) _primaryRel = info.abs_path;
  } catch (_) {
    _fps = 30; _frameCount = 0;
  }
  $("ia3dr-player-section")?.classList.remove("hidden");
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
  const nameEl = $("ia3dr-selected-name");
  if (nameEl) nameEl.textContent = `${stem}/ (${frames.length} labeled frames)`;
  $("ia3dr-player-section")?.classList.remove("hidden");
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
  const nameEl = $("ia3dr-selected-name");
  if (nameEl) nameEl.textContent = name;
  try {
    const info = await (await fetch(`/annotate/video-info?path=${encodeURIComponent(absPath)}`)).json();
    _fps = info.fps || 30;
    _frameCount = info.frame_count || 0;
  } catch (_) {
    _fps = 30; _frameCount = 0;
  }
  $("ia3dr-player-section")?.classList.remove("hidden");
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
  const metaRow = $("ia3dr-meta-frame-row");
  if (metaRow) metaRow.style.display = "none";
  const metaInfo = $("ia3dr-meta-csv-info");
  if (metaInfo) metaInfo.textContent = "No companion CSV";
  const createFb = $("ia3dr-csv-create-status");
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
  const ovToggle = $("ia3dr-overlay-toggle");
  if (ovToggle) ovToggle.checked = false;
  _markerEditor?.setOverlayEnabled(false);
  // Bug-1 clean switch: drop the previous video's markerEditor layer + sibling so a
  // switch never leaves the prior layer's poses live (setPrimary(null) empties the
  // layers + chips + re-renders nothing). Overlay off + no primary ⇒ nothing draws
  // even though editing is armed (no cached poses to draw, no chips).
  _markerEditor?.setPrimary(null);
  const ovPrimarySel = $("ia3dr-overlay-primary-select");
  if (ovPrimarySel) ovPrimarySel.value = "";   // back to the placeholder
  $("ia3dr-overlay-controls")?.classList.add("hidden");
  $("ia3dr-bp-list-wrap")?.classList.add("hidden");
  const _bc = $("ia3dr-bp-chips"); if (_bc) _bc.style.minHeight = "";
  const ovStatus = $("ia3dr-overlay-status");
  if (ovStatus) ovStatus.textContent = "";
  // Curation panel reset.
  const curToggle = $("ia3dr-curation-toggle");
  if (curToggle) curToggle.checked = false;
  $("ia3dr-curation-controls")?.classList.add("hidden");
  const bothLabel = $("ia3dr-both-cams-label");
  if (bothLabel) bothLabel.style.display = "none";
  _curStatus("");
  // Finalize panel reset (inline-only). Finalize is ON by default (spec): re-check
  // the toggle + reveal controls + enable editing. setEditable(true) here mirrors
  // what the toggle change handler would do; we do NOT fire the change event because
  // there is no viewer frame yet and overlay auto-enable is premature.
  const finToggle = $("ia3dr-finalize-toggle");
  if (finToggle) finToggle.checked = true;   // Finalize is on by default (spec)
  $("ia3dr-finalize-controls")?.classList.remove("hidden");
  $("ia3dr-finalize-outputs")?.classList.remove("hidden");
  const finStatus = $("ia3dr-finalize-status");
  if (finStatus) { finStatus.textContent = ""; finStatus.className = "fe-extract-status"; }
  _markerEditor?.setEditable(true);
  _lastFinalizeClip = null;
  _finalizeClipBtnsEnabled(false);
  _refreshAnalyzeEnablement();
  // Clip panel reset: collapse on new video selection.
  const clipEnable = $("ia3dr-clip-enable");
  if (clipEnable) clipEnable.checked = false;
  $("ia3dr-clip-panel")?.classList.add("hidden");
  // Keyframe-lock reset: a new video is never range-locked. The lock checkbox is
  // unlocked by _finalizeKW.load() (setLock(false)); mirror that into the inline
  // confine state + hide the flag/overlays.
  _lockActive = false;
  _applyLockState();
}

// Back button: tear down the viewer and hide the player section.
function _iaBack() {
  // Stop the mini-cam mirror rAF loop (dispose path) so it never outlives the
  // viewer it reads tiles from.
  _stopMirrorLoop();
  _pose3dLoaded = false;
  // Unwire the keyframe windows first: their document-keydown + checkbox listeners
  // live on persistent nodes and would otherwise accumulate across open → Back →
  // reopen cycles. _ensureViewer composes fresh ones on the next open.
  _finalizeKW?.destroy();
  _finalizeKW = null;
  const _tagLock = $("ia3dr-tag-lock");
  if (_tagLock) { _tagLock.checked = false; _tagLock.disabled = true; }
  _snTimeline?.setNoteChipsLocked(false);
  _clipKW?.destroy();
  _clipKW = null;
  _viewer?.destroy();
  _viewer = null;
  _markerEditor = null; // torn down with the viewer; _ensureViewer composes a fresh one
  _resetForOpen();
  $("ia3dr-player-section")?.classList.add("hidden");
  const nameEl = $("ia3dr-selected-name");
  if (nameEl) nameEl.textContent = "";
}

// ── Launcher: content list ──────────────────────────────────────────────────

async function _iaLoadContent() {
  const list = $("ia3dr-content-list");
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
  const breadcrumb = $("ia3dr-browse-breadcrumb");
  const browseList = $("ia3dr-browse-list");
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
  const tabProject = $("ia3dr-tab-project");
  const tabBrowse = $("ia3dr-tab-browse");
  const tabProjectPanel = $("ia3dr-tab-project-panel");
  const tabBrowsePanel = $("ia3dr-tab-browse-panel");

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
  $("ia3dr-browse-up")?.addEventListener("click", () => {
    if (!_iaBrowsePath) return;
    const parent = _iaBrowsePath.split("/").slice(0, -1).join("/") || "/";
    if (parent !== _iaBrowsePath) _iaRefreshBrowse(parent);
  });

  // Hide-no-h5 toggle.
  const hideNoH5 = $("ia3dr-browse-hide-no-h5");
  hideNoH5?.addEventListener("change", () => {
    state.iaBrowseHideNoH5 = !!hideNoH5.checked;
    if (_iaBrowsePath) _iaRefreshBrowse(_iaBrowsePath);
  });
  if (hideNoH5) hideNoH5.checked = !!state.iaBrowseHideNoH5;

  // Editable breadcrumb.
  const breadcrumb = $("ia3dr-browse-breadcrumb");
  breadcrumb?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); _iaNavigateTo(breadcrumb.value); }
    if (e.key === "Escape") { breadcrumb.value = _iaBrowsePath || ""; breadcrumb.blur(); }
  });
  breadcrumb?.addEventListener("paste", () => {
    setTimeout(() => _iaNavigateTo(breadcrumb.value), 0);
  });

  // Back + refresh.
  $("ia3dr-btn-back")?.addEventListener("click", _iaBack);
  $("ia3dr-refresh-btn")?.addEventListener("click", _iaLoadContent);

  // Create-CSV (consumer glue). Static listener.
  $("ia3dr-create-csv-btn")?.addEventListener("click", _iaCreateCsv);

  // Card open / close.
  const card = $("inline-analysis-3d-reprojection-card");
  const openBtn = $("btn-open-inline-analysis-3d-reprojection");
  if (openBtn && card) {
    openBtn.addEventListener("click", () => {
      card.classList.remove("hidden");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      _iaLoadContent();
    });
  }
  $("btn-close-inline-analysis-3d-reprojection")?.addEventListener("click", () => {
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

const _ia3drEl = {
  snapSel:    () => $("ia3dr-snapshot"),
  shuffle:    () => $("ia3dr-shuffle"),
  tsi:        () => $("ia3dr-trainingsetindex"),
  batch:      () => $("ia3dr-batch-size"),
  frames:     () => $("ia3dr-frames-per-click"),
  keepWarm:   () => $("ia3dr-keep-warm-seconds"),
  saveCsv:    () => $("ia3dr-save-csv"),
  analyzeBtn: () => $("ia3dr-btn-analyze-range"),
  lastRun:    () => $("ia3dr-last-run-status"),
  warmInd:    () => $("ia3dr-warm-indicator"),
  refreshSnap:() => $("ia3dr-refresh-snapshots"),
  siblingEl:  () => $("ia3dr-sibling-status"),
};

// ── Snapshot loader (main webapp API; needs same active project) ──
async function _loadSnapshots() {
  const snapSel = _ia3drEl.snapSel();
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
// event (wired in _ensureViewer) instead of the old #ia3dr-frame-counter
// MutationObserver.
async function _refreshSibling() {
  const siblingEl = _ia3drEl.siblingEl();
  const analyzeBtn = _ia3drEl.analyzeBtn();
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
  const lastRun = _ia3drEl.lastRun();
  const snapshot = _ia3drEl.snapSel()?.value;
  if (!snapshot) { if (lastRun) lastRun.textContent = "Pick a snapshot first."; return null; }
  const r = await fetch("/dlc/project/inline-analysis/session/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      snapshot_path: snapshot,
      shuffle:       parseInt(_ia3drEl.shuffle()?.value, 10) || 1,
      ttl_seconds:   parseInt(_ia3drEl.keepWarm()?.value, 10) || 300,
      batch_size:    parseInt(_ia3drEl.batch()?.value, 10) || 8,
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
      const warmInd = _ia3drEl.warmInd();
      if (warmInd) warmInd.textContent =
        s === "ready" ? `● warm · ${mm}:${ss}` : s === "warming" ? "… warming" : `○ ${s}`;
    } catch (e) { /* keep polling */ }
  }, 2000);
}

function _stopStatusPoll() { if (_statusPoll) { clearInterval(_statusPoll); _statusPoll = null; } }

// ── Submit one /range, return req_id (or null) ───────────────────
async function _submitRange(sk, videoPath, startFrame, nFrames, overwrite = false, ignoreAnalyzed = false) {
  const lastRun = _ia3drEl.lastRun();
  const r = await fetch("/dlc/project/inline-analysis/range", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      snap_key: sk, video_path: videoPath,
      start_frame: startFrame, n_frames: nFrames,
      batch_size: parseInt(_ia3drEl.batch()?.value, 10) || 8,
      save_as_csv: !!(_ia3drEl.saveCsv() && _ia3drEl.saveCsv().checked),
      snapshot_path: _ia3drEl.snapSel()?.value || "",
      shuffle: parseInt(_ia3drEl.shuffle()?.value, 10) || 1,
      trainingsetindex: parseInt(_ia3drEl.tsi()?.value, 10) || 0,
      overwrite: !!overwrite,
      ignore_analyzed: !!ignoreAnalyzed,
    }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { if (lastRun) { lastRun.textContent = `Error: ${d.error || r.status}`; lastRun.className = "fe-extract-status err"; } return null; }
  // Surface this dispatched run in the dlc-3D Jobs card. One row per submitted
  // req (dual-cam runs produce two rows) — funnels every analyze path through
  // here. Fire-and-forget: a registry failure must never break the analysis run.
  _registerInlineJob(d.req_id, videoPath, startFrame, nFrames);
  return d.req_id;
}

// Register a dispatched inline-analysis req in the Jobs card's registry so its
// progress is visible alongside LP / EKS / predict / train jobs. Best-effort.
function _registerInlineJob(reqId, videoPath, startFrame, nFrames) {
  if (!reqId) return;
  try {
    fetch("/dlc-3d/lp/register-inline", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        req_id: reqId, video: videoPath,
        start_frame: startFrame, n_frames: nFrames,
      }),
    }).catch(() => {});
  } catch (e) { /* ignore — registration is non-critical */ }
}

// Post one aggregate-batch triangulate update to BOTH Jobs surfaces. ONE row per
// batch (not per range): the frontend owns a crypto.randomUUID batch_id and drives
// both backends — MAIN /dlc/project/triangulate/batch (surfaces on the main /jobs
// page) and dlc-3D /dlc-3d/lp/register-inline (upserts the dlc-3D Jobs card row).
// Both fetches are best-effort; a registry failure must never break the run.
function _batchJob(action, batchId, fields = {}) {
  if (!batchId) return;
  try {
    fetch("/dlc/project/triangulate/batch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch_id: batchId, action, ...fields }),
    }).catch(() => {});
  } catch (e) { /* ignore — registration is non-critical */ }
  try {
    fetch("/dlc-3d/lp/register-inline", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "triangulate", req_id: batchId, batch: true, ...fields }),
    }).catch(() => {});
  } catch (e) { /* ignore — registration is non-critical */ }
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
  const lastRun = _ia3drEl.lastRun();
  const analyzeBtn = _ia3drEl.analyzeBtn();
  const cam0 = _cam0Path();
  if (!cam0)        { if (lastRun) lastRun.textContent = "Pick a cam0 video first."; return; }
  if (!_siblingPath) { if (lastRun) lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
  const sk = await _ensureSession();
  if (!sk) return;
  const startFrame = (_viewer ? _viewer.currentFrame() : 0) || 0;
  const nFrames    = parseInt(_ia3drEl.frames()?.value, 10) || 500;
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
  _ia3drPopulateFinalizeFields();
  // Trigger the shared viewer's render path: re-discover the cam0 h5 variants
  // (auto-picks the freshly-written primary + resolves the cam1 sibling), turn
  // the overlay on, then do a frame-preserving viewer reload so markers paint
  // deterministically. Replaces the old _iaDiscoverVariants + _iaLoadFrame path.
  await _iaDiscoverVariants(cam0);
  const ov = $("ia3dr-overlay-toggle");
  if (ov && !ov.checked) {
    ov.checked = true;
    ov.dispatchEvent(new Event("change", { bubbles: true }));
  } else {
    _markerEditor?.setOverlayEnabled(true);
  }
  // Frame-preserving viewer reload so the overlay repaints over the same frame.
  if (_viewer && _primaryRel) {
    // Snapshot the active status/note tag filters: the reload below re-fires loadCsv
    // for the SAME video, which clears them — the _snTimeline onCsv hook restores this.
    _pendingTagRestore = _snTimeline?.getActiveTags() || null;
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3dr-sync-cam");
    await _viewer.load({
      videoPath: _primaryRel,
      frameCount: _frameCount,
      framesMode,
      siblingPath: sync?.checked && !framesMode ? undefined : null,
    });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  // Re-establish the primary to the just-written variant. Pass the analysis scorer so
  // we land on the exact model just used (<stem><scorer>.h5), not a pre-existing
  // postproc run. Also cache-busts + repaints the markers + coverage timeline (the
  // in-place h5 overwrite otherwise serves stale).
  await _reloadPrimaryAfterAnalysis(d0.scorer);
}

// ── Left-region start buttons ────────────────────────────────────────────────

// Analyze BOTH cameras over the LOCKED finalize range (start = range.start,
// n = range.n). Gated by the UI (button only enabled when finalize-on && locked
// && sibling). Reuses the same session + dual-cam submit/poll as _onAnalyzeClick.
async function _onAnalyzeRangeConfinedClick() {
  const lastRun = _ia3drEl.lastRun();
  const cam0 = _cam0Path();
  if (!cam0) { if (lastRun) lastRun.textContent = "Pick a cam0 video first."; return; }
  if (!_siblingPath) { if (lastRun) lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
  const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
  const startFrame = rng.start, nFrames = rng.n;
  if (!(nFrames >= 1)) { if (lastRun) lastRun.textContent = "Lock a valid keyframe range first."; return; }
  const sk = await _ensureSession();
  if (!sk) return;
  const btn = $("ia3dr-btn-analyze-range-confined");
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
  _ia3drPopulateFinalizeFields();
  await _iaDiscoverVariants(cam0);
  const ov = $("ia3dr-overlay-toggle");
  if (ov && !ov.checked) { ov.checked = true; ov.dispatchEvent(new Event("change", { bubbles: true })); }
  else { _markerEditor?.setOverlayEnabled(true); }
  if (_viewer && _primaryRel) {
    // See _onAnalyzeClick: snapshot active tag filters across the same-video reload.
    _pendingTagRestore = _snTimeline?.getActiveTags() || null;
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3dr-sync-cam");
    await _viewer.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode, siblingPath: sync?.checked && !framesMode ? undefined : null });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  // Re-establish the primary to the model just used (by scorer) + cache-bust + repaint
  // markers + coverage (see _onAnalyzeClick / _reloadPrimaryAfterAnalysis).
  await _reloadPrimaryAfterAnalysis(d0.scorer);
  _refreshAnalyzeEnablement();
}

// Frames carrying ANY of the active note tags (1 or 2), deduped + sorted — the
// union tagged-frame set for a batch analyze/triangulate.
function _framesForActiveNoteTags(activeNotes) {
  const rows = _snTimeline ? _snTimeline.getRows() : [];
  const set = new Set();
  for (const t of activeNotes) for (const f of tagKeyframes(rows, t)) set.add(f);
  return [...set].sort((a, b) => a - b);
}
// Human label for 1–2 active tags: "foo" or "foo" + "bar".
function _noteTagLabel(activeNotes) {
  return activeNotes.map((t) => `"${t}"`).join(" + ");
}

// Analyze BOTH cameras over every frame carrying ANY of the (up to 2) locked note
// tags. Each tagged frame expands to the finalize before/after window; overlapping
// windows are merged (deduped) into minimal ranges. Gated by the UI (finalize on &&
// tag-lock && sibling). Reuses the same session + dual-cam submit/poll as for-range.
async function _onAnalyzeTagClick() {
  const lastRun = _ia3drEl.lastRun();
  const cam0 = _cam0Path();
  if (!cam0) { if (lastRun) lastRun.textContent = "Pick a cam0 video first."; return; }
  if (!_siblingPath) { if (lastRun) lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
  const activeNotes = _snTimeline ? _snTimeline.getActiveTags().note : [];
  if (activeNotes.length < 1 || activeNotes.length > 2) { if (lastRun) lastRun.textContent = "Activate one or two note tags first."; return; }
  const tagLabel = _noteTagLabel(activeNotes);
  const overwrite = !!$("ia3dr-override-labels")?.checked;
  const ignoreAnalyzed = !!$("ia3dr-ignore-analyzed")?.checked;
  const frames = _framesForActiveNoteTags(activeNotes);
  const before = parseInt($("ia3dr-finalize-before")?.value, 10) || 0;
  const after  = parseInt($("ia3dr-finalize-after")?.value, 10) || 0;
  const frameCount = _viewer ? _viewer.frameCount() : 0;
  const ranges = mergeWindows(frames, before, after, frameCount);
  const totalFrames = ranges.reduce((s, r) => s + r.n, 0);
  if (!frames.length || !ranges.length || totalFrames < 1) {
    if (lastRun) lastRun.textContent = `Note tag(s) ${tagLabel} have no frames to analyze.`;
    return;
  }
  const ok = window.confirm(
    `Analyze note tag(s) ${tagLabel}:\n` +
    `${frames.length} tagged frame(s) → ${ranges.length} range(s) → ${totalFrames} frames × 2 cameras.` +
    (overwrite
      ? `\n\n⚠️ Override is ON: this will OVERWRITE existing predictions AND human corrections` +
        (ignoreAnalyzed ? ` (except frames already finalized in _analyzed, which stay protected).` : `.`)
      : ``) +
    `\n\nProceed?`
  );
  if (!ok) return;
  const sk = await _ensureSession();
  if (!sk) return;
  const btn = $("ia3dr-btn-analyze-tag");
  if (btn) btn.disabled = true;
  if (lastRun) { lastRun.textContent = `Analyzing note tag(s) ${tagLabel} (${ranges.length} ranges)…`; lastRun.className = "fe-extract-status"; }
  const reqIds = [];
  let submitFailed = false;
  for (const r of ranges) {
    const [q0, q1] = await Promise.all([
      _submitRange(sk, cam0, r.start, r.n, overwrite, ignoreAnalyzed),
      _submitRange(sk, _siblingPath, r.start, r.n, overwrite, ignoreAnalyzed),
    ]);
    if (!q0 || !q1) { submitFailed = true; break; }
    reqIds.push(q0, q1);
  }
  if (submitFailed) { _refreshAnalyzeEnablement(); return; }
  const results = await Promise.all(reqIds.map((id) => _pollReq(id)));
  const errs = results.filter((d) => d.status === "error");
  const lastDone = results.find((d) => d.status === "done");
  if (lastRun) {
    lastRun.textContent = errs.length === results.length
      ? `All ranges failed: ${errs[0]?.error || "unknown"}`
      : `Note tag(s) ${tagLabel} done: ${results.length - errs.length}/${results.length} submits ok.`;
    if (errs.length === results.length) { lastRun.className = "fe-extract-status err"; _refreshAnalyzeEnablement(); return; }
  }
  // Post-analysis refresh — run ONCE (mirrors _onAnalyzeRangeConfinedClick).
  _ia3drPopulateFinalizeFields();
  await _iaDiscoverVariants(cam0);
  const ov = $("ia3dr-overlay-toggle");
  if (ov && !ov.checked) { ov.checked = true; ov.dispatchEvent(new Event("change", { bubbles: true })); }
  else { _markerEditor?.setOverlayEnabled(true); }
  if (_viewer && _primaryRel) {
    _pendingTagRestore = _snTimeline?.getActiveTags() || null;
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3dr-sync-cam");
    await _viewer.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode, siblingPath: sync?.checked && !framesMode ? undefined : null });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  if (lastDone) await _reloadPrimaryAfterAnalysis(lastDone.scorer);
  _refreshTagLockEnablement();
}

// Triangulate every frame carrying the single locked note tag, over the SAME
// before/after windows as "Analyze for tag". Mirrors _onAnalyzeTagClick's guards +
// mergeWindows range collection, but POSTs each merged range to
// /dlc/project/triangulate/range (ONE call per range, cam0 only — the route handles
// the sibling cam server-side). Progress goes to the Triangulate panel's status line.
async function _onTriangulateTagClick() {
  const status = $("ia3dr-triangulate-range-status");
  const setStatus = (msg, isErr = false) => {
    if (!status) return;
    status.textContent = msg || "";
    status.className = "fe-extract-status" + (isErr ? " err" : "");
  };
  const cam0 = _cam0Path();
  if (!cam0) { setStatus("Pick a cam0 video first.", true); return; }
  if (!_siblingPath) { setStatus("No sibling camera — cannot triangulate.", true); return; }
  const activeNotes = _snTimeline ? _snTimeline.getActiveTags().note : [];
  if (activeNotes.length < 1 || activeNotes.length > 2) { setStatus("Activate one or two note tags first.", true); return; }
  const tagLabel = _noteTagLabel(activeNotes);
  const frames = _framesForActiveNoteTags(activeNotes);
  const before = parseInt($("ia3dr-finalize-before")?.value, 10) || 0;
  const after  = parseInt($("ia3dr-finalize-after")?.value, 10) || 0;
  const frameCount = _viewer ? _viewer.frameCount() : 0;
  const ranges = mergeWindows(frames, before, after, frameCount);
  const totalFrames = ranges.reduce((s, r) => s + r.n, 0);
  if (!frames.length || !ranges.length || totalFrames < 1) {
    setStatus(`Note tag(s) ${tagLabel} have no frames to triangulate.`, true);
    return;
  }
  const ok = window.confirm(
    `Triangulate note tag(s) ${tagLabel}:\n` +
    `${frames.length} tagged frame(s) → ${ranges.length} range(s) → ${totalFrames} frames.` +
    `\n\nProceed?`
  );
  if (!ok) return;
  const btn = $("ia3dr-btn-triangulate-tag");
  if (btn) btn.disabled = true;
  // ONE aggregate row for the whole batch — a frontend-owned batch_id drives both
  // Jobs surfaces (see _batchJob). Registered at start, upserted per range, finalized.
  const batchId = crypto.randomUUID();
  _batchJob("start", batchId, { total: ranges.length, video: cam0, done: 0, stage: `0/${ranges.length}` });
  try {
    let doneCount = 0, skipCount = 0;
    for (let i = 0; i < ranges.length; i++) {
      const r = ranges[i];
      setStatus(`Triangulating range ${i + 1}/${ranges.length} (${r.n} frames from ${r.start})…`);
      const enq = await _enqueueTriangulateRange(cam0, r.start, r.n);
      if (!enq.req_id) {
        setStatus(`Error: ${enq.error}`, true);
        _batchJob("done", batchId, { done: doneCount, skipped: skipCount, stage: `error — ${enq.error}` });
        return;
      }
      // Track the last poll stage/pct so the per-range aggregate update carries a
      // short human progress string (coarse per-range granularity is fine).
      let lastStage = "", lastPct = "";
      const done = await _pollTriangulateReq(enq.req_id, (d) => {
        const pct = (d && typeof d.progress === "number") ? ` ${d.progress}%` : "";
        lastStage = (d && d.stage) || lastStage;
        lastPct = pct;
        setStatus(`Range ${i + 1}/${ranges.length}: ${(d && d.stage) || "working"}…${pct}`);
      });
      if (done.state !== "SUCCESS") {
        setStatus(`Error: ${(done && done.error) || "triangulation failed"}`, true);
        _batchJob("done", batchId, { done: doneCount, skipped: skipCount, stage: `error — ${(done && done.error) || "triangulation failed"}` });
        return;
      }
      // A range entirely beyond the analyzed 2D data is skipped server-side
      // (no crash) — a tag on a never-finalized frame has no poses to triangulate.
      if (done.result && done.result.skipped) skipCount += 1;
      else doneCount += 1;
      // Upsert the aggregate row once per completed range.
      const stage = `${doneCount + skipCount}/${ranges.length} · ${lastStage || "triangulated"}${lastPct}`;
      _batchJob("progress", batchId, { done: doneCount, skipped: skipCount, stage });
    }
    const skipMsg = skipCount ? ` (${skipCount} skipped — no 2D data)` : "";
    setStatus(`3D ✓ note tag "${tagValue}": ${doneCount}/${ranges.length} ranges triangulated${skipMsg}.`);
    _batchJob("done", batchId, {
      done: doneCount, skipped: skipCount,
      stage: `${doneCount}/${ranges.length} done${skipCount ? ` · ${skipCount} skipped` : ""}`,
    });
    // Only touch the coverage bar / 3D viewer if something was actually written.
    if (doneCount > 0) {
      await _refreshTriangulateCoverage();
      // Newly-triangulated frames → refetch + reload the 3D pose viewer (no-op until
      // its panel has been opened at least once).
      if (_pose3d && _pose3dLoaded) await _loadPose3d();
    }
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  } finally {
    // Restore the gated disabled-state (same rules as Analyze-for-tag).
    _refreshAnalyzeEnablement();
  }
}

// Enable the Lock-tag checkbox only when exactly one note tag is active. If the
// active-note count drifts off 1 (e.g. a video switch clears it), drop the lock and
// unfreeze the chips. Called on chip toggles (onActiveTagsChange) and CSV reloads.
function _refreshTagLockEnablement() {
  const lock = $("ia3dr-tag-lock");
  if (!lock) return;
  const activeNotes = _snTimeline ? _snTimeline.getActiveTags().note : [];
  const oneOrTwo = activeNotes.length >= 1 && activeNotes.length <= 2;
  lock.disabled = !oneOrTwo;
  if (!oneOrTwo && lock.checked) {
    lock.checked = false;
    _snTimeline?.setNoteChipsLocked(false);
  }
  _updateTagHint();
  _refreshAnalyzeEnablement();
}

// Mirror #ia3dr-start-hint's wording for the tag path.
function _updateTagHint() {
  const hint = $("ia3dr-tag-hint");
  if (!hint) return;
  const activeNotes = _snTimeline ? _snTimeline.getActiveTags().note : [];
  const locked = !!$("ia3dr-tag-lock")?.checked;
  const nt = activeNotes.length;
  if (locked && (nt === 1 || nt === 2)) {
    const n = _framesForActiveNoteTags(activeNotes).length;
    hint.textContent = `${nt} note tag${nt === 1 ? "" : "s"} locked → ${n} tagged frame${n === 1 ? "" : "s"}. Unlock to disable.`;
  } else if (nt === 1 || nt === 2) {
    hint.textContent = 'check "Lock tag" to enable "Analyze for tag".';
  } else {
    hint.textContent = 'activate one or two note tags to enable "Analyze for tag".';
  }
}

// Drive the two left-region start buttons + the count/hint line. "From current
// frame" mirrors the top analyze button's sibling-gating. "For range" needs
// finalize-on AND the keyframe locked AND a sibling.
function _refreshAnalyzeEnablement() {
  const cur = $("ia3dr-btn-analyze-current");
  const rng = $("ia3dr-btn-analyze-range-confined");
  const n = parseInt(_ia3drEl.frames()?.value, 10) || 500;
  const countN = $("ia3dr-start-count-n");
  if (countN) countN.textContent = n.toLocaleString();
  const hasSibling = !!_siblingPath;
  if (cur) cur.disabled = !hasSibling;
  const finOn = !!$("ia3dr-finalize-toggle")?.checked;
  const locked = !!$("ia3dr-finalize-lock")?.checked;
  const rangeOk = finOn && locked && hasSibling;
  if (rng) rng.disabled = !rangeOk;
  // Triangulate-keyframe-range (Phase 2) is gated identically to the confined analyze
  // button — enabled only when the finalize keyframe is locked (stereo needs a sibling).
  const triRng = $("ia3dr-triangulate-range-btn");
  if (triRng) triRng.disabled = !rangeOk;
  // Analyze-for-tag mirrors the for-range gate but keys on the tag-lock.
  const tagBtn = $("ia3dr-btn-analyze-tag");
  const tagLocked = !!$("ia3dr-tag-lock")?.checked;
  if (tagBtn) tagBtn.disabled = !(finOn && tagLocked && hasSibling);
  // Triangulate-all-for-tag shares the tag-lock gate with Analyze-for-tag.
  const triTagBtn = $("ia3dr-btn-triangulate-tag");
  if (triTagBtn) triTagBtn.disabled = !(finOn && tagLocked && hasSibling);
  const hint = $("ia3dr-start-hint");
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

function _ia3drPopulateFinalizeFields() {
  _finalizeKW?.load();   // keyframe=current frame, before/after from the per-project setting
}

async function _ia3drSaveLayer(h5) {
  try {
    const r = await fetch("/dlc/viewer/save-marker-edits", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ h5 }),
    });
    return r.ok;
  } catch (_) { return false; }
}

async function _ia3drFinalizeOne(videoPath, sourceH5, startFrame, nFrames) {
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

// Number of frames actually FINALIZED in the _analyzed file (0 when the file is
// absent OR exists-but-empty). Used to gate the overwrite prompt: an empty
// _analyzed has nothing to overwrite, so it must never warn.
async function _finalizedCount(v) {
  try { return (await (await fetch(`/dlc/project/analysis-file/status?video_path=${encodeURIComponent(v)}`)).json()).n_analyzed || 0; }
  catch (e) { return 0; }
}

// Does [startFrame, endFrame] overlap any finalized frame per the amber "_analyzed"
// coverage bar (the same buckets it draws from — each covered bucket = ≥1 finalized
// frame)? Returns true/false, or null when the coverage isn't loaded yet (caller then
// treats "unknown" as a reason to still prompt, so we never silently overwrite).
function _rangeOverlapsFinalized(startFrame, endFrame) {
  const buckets = _finalizeCoverageBuckets;
  if (!buckets || !buckets.length || !_viewer) return null;
  const fc = _viewer.frameCount();
  if (!fc) return null;
  const nB = buckets.length;
  for (let b = 0; b < nB; b++) {
    if (!buckets[b]) continue;                          // uncovered bucket → skip
    const bStart = Math.floor((b * fc) / nB);
    const bEnd = Math.floor(((b + 1) * fc) / nB) - 1;   // this bucket's frame span
    if (bStart <= endFrame && bEnd >= startFrame) return true;
  }
  return false;
}

// Finalize the current keyframe-window range into both cams' _analyzed.
// Returns { ok, start, n }. Shared by the Add-range and Finalize-and-extract
// buttons; callers manage their own button disabled-state.
async function _doFinalizeAdd() {
  const st = $("ia3dr-finalize-status");
  const cam0H5 = _overlayPrimaryH5, cam0Video = _cam0Path();
  if (!cam0H5 || !cam0Video) {
    if (st) { st.textContent = "Select a video/layer first."; st.className = "fe-extract-status err"; }
    return { ok: false, start: 0, n: 0 };
  }
  const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
  const startFrame = rng.start, nFrames = rng.n;
  const cam1Layer = _siblingPrimaryH5;
  try {
    // Gate on the number of FINALIZED frames, not merely file-existence: an empty
    // _analyzed (file present but 0 finalized) has nothing to overwrite → no prompt,
    // even before the amber coverage bar has loaded (overlap would be "unknown").
    const n0 = await _finalizedCount(cam0Video);
    const n1 = (_siblingPath && cam1Layer) ? await _finalizedCount(_siblingPath) : 0;
    const e0 = n0 > 0, e1 = n1 > 0;
    // Among cams with finalized data, only warn when the range actually overlaps it
    // (per the amber coverage bar). overlap === false → skip; true/null → prompt.
    const overlap = _rangeOverlapsFinalized(startFrame, startFrame + nFrames - 1);
    if ((e0 || e1) && overlap !== false && !window.confirm(
        `Overwrite frames ${startFrame}–${startFrame + nFrames - 1} in the existing _analyzed file(s)` +
        `${e0 && e1 ? " on both cameras" : (e0 ? " on cam0" : " on cam1")}?\n\nThis replaces any curated values already saved for those frames.`)) {
      if (st) { st.textContent = "Cancelled."; st.className = "fe-extract-status"; }
      return { ok: false, start: startFrame, n: nFrames };
    }
  } catch (_) { /* status check failed — proceed */ }
  if (st) { st.textContent = "Finalizing…"; st.className = "fe-extract-status"; }
  try {
    const sv0 = await _ia3drSaveLayer(cam0H5);
    const sv1 = cam1Layer ? await _ia3drSaveLayer(cam1Layer) : true;
    if (!sv0 || !sv1) {
      if (st) { st.textContent = `Could not save edits (${!sv0 ? "cam0" : "cam1"}) — finalize aborted`; st.className = "fe-extract-status err"; }
      return { ok: false, start: startFrame, n: nFrames };
    }
    const r0 = await _ia3drFinalizeOne(cam0Video, cam0H5, startFrame, nFrames);
    let r1 = null;
    if (_siblingPath && cam1Layer) r1 = await _ia3drFinalizeOne(_siblingPath, cam1Layer, startFrame, nFrames);
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
  const btn = $("ia3dr-finalize-add-btn");
  if (btn) btn.disabled = true;
  try { await _doFinalizeAdd(); }
  finally { if (btn) btn.disabled = false; }
}

function _finalizeClipBtnsEnabled(on) {
  const r = $("ia3dr-finalize-clip-rename-btn"), d = $("ia3dr-finalize-clip-delete-btn");
  if (r) r.disabled = !on;
  if (d) d.disabled = !on;
}

async function _onFinalizeAndExtractClick() {
  const st = $("ia3dr-finalize-status"), btn = $("ia3dr-finalize-clip-btn");
  if (btn) btn.disabled = true;
  try {
    const r = await _doFinalizeAdd();
    if (!r.ok) return;
    const postfix = $("ia3dr-finalize-clip-postfix")?.value || "";
    const both = $("ia3dr-finalize-clip-sibling")?.checked;
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
  const st = $("ia3dr-finalize-status");
  const postfix = $("ia3dr-finalize-clip-postfix")?.value || "";
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
  const st = $("ia3dr-finalize-status");
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
  const initFileBtn = $("ia3dr-init-analysis-file");
  const initFileStatus = $("ia3dr-init-file-status");
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
  const initFileBtn = $("ia3dr-init-analysis-file");
  const initFileStatus = $("ia3dr-init-file-status");
  const cam0 = _cam0Path(); if (!cam0) return;
  if (initFileBtn) { initFileBtn.disabled = true; initFileBtn.textContent = "…"; }
  const okCam0 = await _initOne(cam0);
  const okCam1 = _siblingPath ? await _initOne(_siblingPath) : true;
  if (initFileStatus) initFileStatus.textContent = `cam0 ${okCam0 ? "✓" : "⚠"}` + (_siblingPath ? ` · cam1 ${okCam1 ? "✓" : "⚠"}` : "");
  await _refreshInitFileBtn();
}

// Wire the stereo-analysis chrome (static controls; persist across rebuilds).
function _wireStereoDispatch() {
  const analyzeBtn = _ia3drEl.analyzeBtn();
  if (!analyzeBtn) return;   // markup missing — bail silently

  _ia3drEl.refreshSnap()?.addEventListener("click", _loadSnapshots);
  _ia3drEl.shuffle()?.addEventListener("change", _loadSnapshots);
  $("btn-open-inline-analysis-3d-reprojection")?.addEventListener("click", _loadSnapshots);

  analyzeBtn.addEventListener("click", _onAnalyzeClick);

  // Left-region start buttons (mirror the top analyze button + gated for-range).
  $("ia3dr-btn-analyze-current")?.addEventListener("click", _onAnalyzeClick);
  $("ia3dr-btn-analyze-range-confined")?.addEventListener("click", _onAnalyzeRangeConfinedClick);
  $("ia3dr-frames-per-click")?.addEventListener("input", _refreshAnalyzeEnablement);
  $("ia3dr-finalize-lock")?.addEventListener("change", _refreshAnalyzeEnablement);
  // Analyze-for-tag: Lock-tag freezes the note chips + gates the batch button.
  $("ia3dr-tag-lock")?.addEventListener("change", () => {
    const on = !!$("ia3dr-tag-lock").checked;
    _snTimeline?.setNoteChipsLocked(on);
    _updateTagHint();
    _refreshAnalyzeEnablement();
  });
  $("ia3dr-btn-analyze-tag")?.addEventListener("click", _onAnalyzeTagClick);
  $("ia3dr-btn-triangulate-tag")?.addEventListener("click", _onTriangulateTagClick);
  // NOTE: the finalize keyframe-lock is now driven exclusively through the keyframe
  // window's onLockChange callback (see makeKeyframeWindow above). A direct DOM
  // change-listener that called _applyLockState would miss the 'l' shortcut
  // (programmatic .checked fires no native change event) — that was Bug 1. Do NOT
  // re-add such a listener here; route lock changes through onLockChange instead.

  // Per-project quick-tags (postfix / status / note). Static containers + inputs
  // — wired once here; loaded per-project on each video open.
  _wireQuickTags();

  // Finalize toggle: gates marker editing via the markerEditor master gate
  // (replaces the old _ia3drFinalizeEnabled gate), reveals the controls, force-
  // enables the overlay, and populates the range fields.
  const ia3dFinalizeToggle = $("ia3dr-finalize-toggle");
  ia3dFinalizeToggle?.addEventListener("change", () => {
    const on = !!ia3dFinalizeToggle.checked;
    _markerEditor?.setEditable(on);
    // Two gated groups around the always-visible analyze block: keyframe group +
    // finalize-outputs group. Toggle both with the finalize checkbox.
    $("ia3dr-finalize-controls")?.classList.toggle("hidden", !on);
    $("ia3dr-finalize-outputs")?.classList.toggle("hidden", !on);
    const ov = $("ia3dr-overlay-toggle");
    if (on&&ov&&!ov.checked){ov.checked=true;ov.dispatchEvent(new Event("change"));}
    if (on) _ia3drPopulateFinalizeFields();
    _refreshFinalizeCoverage();
    _refreshAnalyzeEnablement();
    _applyLockState();
  });

  $("ia3dr-finalize-add-btn")?.addEventListener("click", _onFinalizeAddClick);
  $("ia3dr-finalize-clip-btn")?.addEventListener("click", _onFinalizeAndExtractClick);
  $("ia3dr-finalize-clip-rename-btn")?.addEventListener("click", _onFinalizeClipRename);
  $("ia3dr-finalize-clip-delete-btn")?.addEventListener("click", _onFinalizeClipDelete);

  $("ia3dr-init-analysis-file")?.addEventListener("click", _onInitFileClick);

  // Session cleanup on card close.
  $("btn-close-inline-analysis-3d-reprojection")?.addEventListener("click", () => {
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
function _ia3drPlaceNavButton() {
  const nav = $("dlc-frame-extract-launch");
  const btn = $("btn-open-inline-analysis-3d-reprojection");
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
  _ia3drPlaceNavButton();
});
if (document.readyState !== "loading") {
  // Module evaluated after DOMContentLoaded — run the nav placement now too
  // (the DOMContentLoaded listener above won't fire). Idempotent.
  _ia3drPlaceNavButton();
}

// Expose the VideoViewer instance for the co-evolved static/E2E tests (replaces
// the old window.__ia3dr-controller getter). Resolved lazily — the viewer is
// created on the first open. A getter keeps it current across rebuild cycles.
Object.defineProperty(window, "__iaViewerReproj", {
  configurable: true,
  get() { return _viewer; },
});
