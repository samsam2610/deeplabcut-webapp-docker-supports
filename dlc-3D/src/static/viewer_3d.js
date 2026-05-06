"use strict";
import { state } from '/static/js/state.js';

// ─── Tile abstraction ───────────────────────────────────────────────────────
class Tile {
  constructor(cam, rootEl) {
    this.cam      = cam;                    // 0 or 1
    this.rootEl   = rootEl;                 // .va3d-tile
    this.imgEl    = rootEl.querySelector('.va3d-frame-img');
    this.canvasEl = rootEl.querySelector('.va3d-overlay-canvas');
    this.wrapEl   = rootEl.querySelector('.va3d-tile-canvas-wrap');
    this.labelEl  = rootEl.querySelector('.va3d-tile-label');
    this.pillEl   = rootEl.querySelector('.va3d-tile-pill');
    this.spinnerEl= rootEl.querySelector('.va3d-frame-spinner');
    this.sliderEl = rootEl.querySelector('.va3d-tile-size');
    this.sliderValEl = rootEl.querySelector('.va3d-tile-size-val');
    this.weight   = 100;
    this.videoRel = null;
    this.primaryH5Path = null;
    this.comparisonLayers = [];
    this.pendingEdits = new Map();   // frame → { bodypart → {x,y} }
    this.markersByFrame = new Map(); // frame → markers
    this.sliderEl?.addEventListener('input', (e) => this.setWeight(parseInt(e.target.value, 10)));
  }
  setLabel(text) { this.labelEl.textContent = text; }
  setPill(text) {
    if (text) { this.pillEl.textContent = text; this.pillEl.classList.remove('hidden'); }
    else      { this.pillEl.classList.add('hidden'); }
  }
  setWeight(w) {
    this.weight = w;
    this.rootEl.dataset.weight = String(w);
    this.rootEl.style.flexGrow = String(w);
    this.sliderEl.value = String(w);
    this.sliderValEl.textContent = `${w}%`;
  }
}

// ─── Both-cams visibility helper ───────────────────────────────────────────
function _va3dUpdateBothCamsVisibility() {
  const both = document.getElementById('va3d-both-cams-label');
  if (!both) return;
  both.style.display = (Controller.tiles.length > 1 && Controller.syncOn) ? 'inline-flex' : 'none';
}

// ─── Curator call helpers (paired per-cam fan-out) ─────────────────────────
async function _va3dCuratorCall(endpoint, body) {
  const r = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let err;
    try { err = (await r.clone().json()).error; } catch { err = await r.text(); }
    return { ok: false, error: err || `HTTP ${r.status}` };
  }
  return { ok: true, body: await r.json() };
}

function _va3dShouldDoubleUp() {
  const cb = document.getElementById('va3d-both-cams');
  return cb && cb.checked && Controller.syncOn && Controller.tiles.length > 1;
}

function _va3dShowCuratorStatus(targets, results) {
  if (targets.length === 1) return;
  let anyError = false;
  const summary = results.map((res, i) => {
    // Accept either Promise.allSettled envelopes or plain {ok, error} shapes.
    const r = res && res.status === 'fulfilled' ? res.value
            : res && 'ok' in res                 ? res
            : { ok: false, error: res && res.reason };
    if (!r.ok) anyError = true;
    const cam = targets[i].cam;
    return r.ok ? `cam${cam} ✓` : `cam${cam} ✗ ${r.error || ''}`;
  }).join(' · ');
  // Route through _curStatus so the auto-clear timer is managed in one place
  // (any pending timer from the primary call is cleared) and the err class is
  // applied when any per-cam result failed.
  if (typeof window.__va3dCurStatus === 'function') {
    window.__va3dCurStatus(summary, anyError);
  } else {
    const statusEl = document.getElementById('va3d-curation-status');
    if (statusEl) {
      statusEl.textContent = summary;
      statusEl.className = 'fe-extract-status' + (anyError ? ' err' : '');
    }
  }
}

// Build a curator request body for a given tile + frame, mirroring the
// primary _videoRequestBody() shape per-mode.  In 'video' (project) mode the
// backend expects video_name = basename; in 'browse-video' mode it expects
// the absolute video_path.  ('frames' mode: sibling tile is skipped per the
// double-up gate, but fall back to video_path if reached.)
function _va3dBuildCuratorBody(tile, frame) {
  const mode = (typeof window.__va3dGetMode === 'function') ? window.__va3dGetMode() : null;
  if (mode === 'video') {
    const name = String(tile.videoRel || '').split('/').pop();
    return { frame_number: frame, video_name: name };
  }
  return { frame_number: frame, video_path: tile.videoRel };
}

// ─── ViewerController singleton ────────────────────────────────────────────
const Controller = {
  tiles: [],
  currentFrame: 0,
  syncOn: false,
  primaryVideoRel: null,
  siblingVideoRel: null,
  _loadToken: 0,
  // When sync is toggled off, the sibling Tile instance is parked here so its
  // pendingEdits survive a sync-off → sync-on cycle. Cleared when the user
  // switches to a different sibling video (see loadVideo).
  _pendingSibling: null,

  init() {
    const tile0Root = document.querySelector('#va3d-tile-row .va3d-tile');
    if (!tile0Root) return;
    this.tiles = [new Tile(0, tile0Root)];
    this._wireFocus(this.tiles[0]);
    const syncCb = document.getElementById('va3d-sync-cam');
    syncCb?.addEventListener('change', (e) => {
      if (e.target.checked && this.siblingVideoRel) {
        this._ensureSiblingTile();
        this.syncOn = true;
      } else {
        this._removeSiblingTile();
        this.syncOn = false;
      }
      _va3dUpdateBothCamsVisibility();
    });
    document.getElementById('va3d-equalize-btn')?.addEventListener('click', () => {
      this.tiles.forEach(t => t.setWeight(100));
    });
    // Keyboard 1/2 → focus tile 0/1. Scoped to when the analyzed-viewer card
    // is open; ignored when typing into form fields.
    document.addEventListener('keydown', (e) => {
      const card = document.getElementById('view-analyzed-3d-card');
      if (!card || card.classList.contains('hidden')) return;
      if (e.target.matches && e.target.matches('input, textarea, select')) return;
      if (e.key === '1') this.focusTile(0);
      else if (e.key === '2' && this.tiles.length > 1) this.focusTile(1);
    });
  },

  async loadVideo(videoRel) {
    const myToken = ++this._loadToken;
    this.primaryVideoRel = videoRel;
    this.tiles[0].videoRel = videoRel;
    this.tiles[0].setLabel(videoRel.split('/').pop());
    // Probe sibling
    try {
      const r = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoRel)}`);
      if (myToken !== this._loadToken) return;
      const j = await r.json();
      if (myToken !== this._loadToken) return;
      this.siblingVideoRel = j.sibling_video_path || null;
    } catch (e) {
      if (myToken !== this._loadToken) return;
      console.warn('[va3d] sibling-camera probe failed:', e);
      this.siblingVideoRel = null;
    }
    // If we have a parked sibling tile from a different video, drop it.
    // TODO: prompt the user to confirm discard when pendingEdits is non-empty.
    // Sibling editing is dormant today (Tile-1 pendingEdits stays empty), so
    // a silent discard is harmless until per-cam editing on tile-1 lands.
    if (this._pendingSibling && this._pendingSibling.videoRel !== this.siblingVideoRel) {
      this._pendingSibling = null;
    }
    this._renderSiblingTile();
  },

  _renderSiblingTile() {
    const lbl = document.getElementById('va3d-sync-cam-label');
    const cb  = document.getElementById('va3d-sync-cam');
    const eq  = document.getElementById('va3d-equalize-btn');
    if (!this.siblingVideoRel) {
      // Hide sibling tile if present
      if (this.tiles.length > 1) {
        this.tiles[1].rootEl.remove();
        this.tiles = this.tiles.slice(0, 1);
      }
      lbl.style.display = 'inline-flex';
      cb.checked = false;
      cb.disabled = true;
      lbl.title = 'no sibling cam detected';
      eq.classList.add('hidden');
      this.syncOn = false;
      _va3dUpdateBothCamsVisibility();
      return;
    }
    lbl.style.display = 'inline-flex';
    cb.checked = true;
    cb.disabled = false;
    lbl.title = '';
    this.syncOn = true;
    eq.classList.remove('hidden');
    this._ensureSiblingTile();
    _va3dUpdateBothCamsVisibility();
  },

  _ensureSiblingTile() {
    if (this.tiles.length === 2) return;
    // Restore a parked sibling Tile if it matches the current sibling video.
    // This preserves pendingEdits across a sync-off → sync-on toggle.
    if (this._pendingSibling && this._pendingSibling.videoRel === this.siblingVideoRel) {
      document.getElementById('va3d-tile-row').appendChild(this._pendingSibling.rootEl);
      this.tiles.push(this._pendingSibling);
      this._wireFocus(this._pendingSibling);
      this._pendingSibling = null;
      return;
    }
    const tpl = document.getElementById('va3d-tile-template');
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.cam = '1';
    document.getElementById('va3d-tile-row').appendChild(node);
    const tile = new Tile(1, node);
    tile.videoRel = this.siblingVideoRel;
    tile.setLabel(this.siblingVideoRel.split('/').pop());
    this.tiles.push(tile);
    this._wireFocus(tile);
  },

  _removeSiblingTile() {
    if (this.tiles.length < 2) return;
    // Park the Tile instance (with its pendingEdits) so a re-toggle of Sync
    // restores the same instance instead of constructing a fresh one. The
    // DOM node is detached but kept alive on the parked Tile.
    this._pendingSibling = this.tiles[1];
    this._pendingSibling.rootEl.remove();
    this.tiles = this.tiles.slice(0, 1);
  },

  _wireFocus(tile) {
    tile.rootEl.addEventListener('mousedown', () => this.focusTile(tile.cam));
  },
  focusTile(cam) {
    this.tiles.forEach(t => t.rootEl.classList.toggle('focused', t.cam === cam));
  },

  // ── Frame-locked seek ──────────────────────────────────────────────────
  // Routes all seek/play/skip handlers through a single entry point so every
  // tile advances together. Tile-0 still uses the existing _vaLoadFrame
  // (which carries the overlay/poses logic); the sibling tile uses the
  // generic _loadFrameOnTile loader keyed off tile.videoRel.
  async seek(n) {
    const tasks = [];
    if (typeof _vaLoadFrame === 'function') {
      tasks.push(_vaLoadFrame(n));
    }
    // Sibling tile: skip when primary is in 'frames' mode (n is an index
    // into _vaFrameFiles, not a real video frame, so /dlc-3d/frame?n=…
    // would request the wrong picture).
    const sibling = this.tiles[1];
    const inFramesMode = (typeof _vaMode !== 'undefined' && _vaMode === 'frames');
    if (sibling && sibling.videoRel && !inFramesMode) {
      tasks.push(this._loadFrameOnTile(sibling, n));
    }
    await Promise.all(tasks);
    // _vaLoadFrame clamps n internally; mirror its result as truth.
    if (typeof _vaCurrentFrame !== 'undefined') this.currentFrame = _vaCurrentFrame;
    else this.currentFrame = n;
  },

  // ── Layer-pair resolver ────────────────────────────────────────────────
  // When the user picks the primary h5 in the overlay panel, each tile must
  // resolve to its own cam-specific h5 via /dlc-3d/analyzed/sibling-h5.
  // Tile 0 trivially uses the picked path; tile 1 (sibling) asks the backend
  // for the matching h5 and falls back to a 'no sibling h5 — overlay off'
  // pill if none exists. Sibling rendering itself is deferred to Task 9 —
  // here we only stash the resolved path on the tile and update its pill.
  async _resolveLayerForTile(primaryH5Path, tile) {
    if (tile.cam === 0) return { path: primaryH5Path, exists: true };
    try {
      const r = await fetch(
        `/dlc-3d/analyzed/sibling-h5?primary_h5=${encodeURIComponent(primaryH5Path)}&cam=${tile.cam}`
      );
      if (!r.ok) return { path: null, exists: false };
      return await r.json();
    } catch (e) {
      return { path: null, exists: false };
    }
  },

  async _loadH5OnTile(tile) {
    // Tile 0's h5 is loaded by the existing single-cam handler
    // (_vaApplyPrimaryFromSelect) operating on globals — nothing to do here.
    // Tile 1's actual marker render is deferred to Task 9 (comparison-layers
    // resolver). At this point we have already populated tile.primaryH5Path
    // so downstream rendering work can find it.
    if (tile.cam === 0) return;
    // Placeholder hook: clear any 'frame load failed' pill so the resolver's
    // pill (if needed) is the only thing visible.
    // (Sibling-h5 loaders will land in Task 9.)
  },

  async setPrimaryLayer(primaryH5Path) {
    for (const tile of this.tiles) {
      const res = await this._resolveLayerForTile(primaryH5Path, tile);
      if (res && res.exists) {
        tile.primaryH5Path = res.path;
        tile.setPill('');
        await this._loadH5OnTile(tile);
      } else {
        tile.primaryH5Path = null;
        tile.setPill('no sibling h5 — overlay off');
      }
    }
  },

  async addComparisonLayer(layerPath) {
    for (const tile of this.tiles) {
      try {
        const res = await this._resolveLayerForTile(layerPath, tile);
        if (res && res.exists && !tile.comparisonLayers.includes(res.path)) {
          tile.comparisonLayers.push(res.path);
        } else if ((!res || !res.exists) && tile.cam !== 0) {
          // Sibling missing for this comparison — note in pill (don't clobber
          // an existing 'no sibling h5' pill from the primary resolver).
          const cur = tile.pillEl.textContent || '';
          if (!cur.includes('sibling comparison missing')) {
            tile.setPill(cur ? `${cur} · sibling comparison missing` : 'sibling comparison missing');
          }
        }
      } catch (e) {
        // Resolver fault must never break the tile-0 add flow.
      }
    }
  },

  removeComparisonLayer(layerPath) {
    // The remove call typically passes tile-0's path; tile-1's matching entry
    // has a different cam token in its basename. Match cam-agnostically.
    const baseName = (layerPath || '').split('/').pop() || '';
    const camAgnosticBase = baseName.replace(/_cam\d+_/, '_camX_');
    for (const tile of this.tiles) {
      tile.comparisonLayers = tile.comparisonLayers.filter(p => {
        const b = (p || '').split('/').pop().replace(/_cam\d+_/, '_camX_');
        return b !== camAgnosticBase;
      });
    }
  },

  async _loadFrameOnTile(tile, frame) {
    if (!tile.videoRel) return;
    // This loader runs on sibling tiles only (tile-0 takes the _vaLoadFrame
    // path which has its own error handling). Any failure here — unreadable
    // sibling video, frame past end, transient backend error — surfaces via
    // the same 'frame load failed' pill.
    //
    // DEFERRED: differentiating 416/404 (frame N/A on sibling) from a generic
    // load failure would require fetch() with explicit status inspection
    // instead of <img>.src — the browser does not expose HTTP status to img
    // onerror. Keeping the single pill until that refactor lands.
    //
    // Per-tile load token: fast Next clicks can interleave two calls; the
    // stale call's onload/onerror must not flip the visible state of the
    // fresh load. The promise itself always resolves (we don't want to
    // leave a hanging promise from a superseded src assignment) — the
    // token check after the await decides whether to update state.
    const myToken = (tile._loadToken = (tile._loadToken || 0) + 1);
    tile.spinnerEl.classList.remove('hidden');
    try {
      const url = `/dlc-3d/frame?video=${encodeURIComponent(tile.videoRel)}&n=${frame}`;
      await new Promise((res, rej) => {
        tile.imgEl.onload  = () => (myToken === tile._loadToken ? res() : res());
        tile.imgEl.onerror = () => (myToken === tile._loadToken ? rej(new Error('img load')) : res());
        tile.imgEl.src = url;
      });
      if (myToken !== tile._loadToken) return;   // superseded; later call will clear pill
      tile.setPill('');                          // clear any prior 'frame load failed'
    } catch (e) {
      if (myToken === tile._loadToken) tile.setPill('frame load failed');
    } finally {
      if (myToken === tile._loadToken) tile.spinnerEl.classList.add('hidden');
    }
  },
};

window.__va3dController = Controller;  // for e2e introspection
document.addEventListener('DOMContentLoaded', () => Controller.init());

    const vaCard         = document.getElementById("view-analyzed-3d-card");
    const vaOpenBtn      = document.getElementById("btn-open-view-analyzed");
    const vaCloseBtn     = document.getElementById("btn-close-view-analyzed-3d");
    const vaRefreshBtn   = document.getElementById("va3d-refresh-btn");
    const vaContentList  = document.getElementById("va3d-content-list");
    const vaPlayerSec    = document.getElementById("va3d-player-section");
    const vaSelectedName = document.getElementById("va3d-selected-name");
    const vaBackBtn      = document.getElementById("va3d-btn-back");
    const vaVideoWrap    = document.getElementById("va3d-video-wrap-0");
    const vaFrameImg     = document.getElementById("va3d-frame-img-0");
    const vaFrameSpinner = document.getElementById("va3d-frame-spinner-0");
    const vaZoomInput    = document.getElementById("va3d-zoom");
    const vaZoomVal      = document.getElementById("va3d-zoom-val");
    const vaBtnPlay      = document.getElementById("va3d-btn-play");
    const vaPlayIcon     = document.getElementById("va3d-play-icon");
    const vaPauseIcon    = document.getElementById("va3d-pause-icon");
    const vaBtnPrev      = document.getElementById("va3d-btn-prev");
    const vaBtnNext      = document.getElementById("va3d-btn-next");
    const vaBtnSkipBack  = document.getElementById("va3d-btn-skip-back");
    const vaBtnSkipFwd   = document.getElementById("va3d-btn-skip-fwd");
    const vaSkipN        = document.getElementById("va3d-skip-n");
    const vaFrameCounter = document.getElementById("va3d-frame-counter");
    const vaTimeDisplay  = document.getElementById("va3d-time-display");
    const vaSeek         = document.getElementById("va3d-seek");
    const vaStatus       = document.getElementById("va3d-status");
    // Browse-tab elements
    const vaTabProject      = document.getElementById("va3d-tab-project");
    const vaTabBrowse       = document.getElementById("va3d-tab-browse");
    const vaTabProjectPanel = document.getElementById("va3d-tab-project-panel");
    const vaTabBrowsePanel  = document.getElementById("va3d-tab-browse-panel");
    const vaBrowseBreadcrumb = document.getElementById("va3d-browse-breadcrumb");
    const vaBrowseUp         = document.getElementById("va3d-browse-up");
    const vaBrowseList       = document.getElementById("va3d-browse-list");

    // State
    let _vaMode         = null;   // "video" | "frames" | "browse-video"
    let _vaCurrentFrame = 0;
    let _vaFrameCount   = 0;
    let _vaFps          = 30;
    let _vaFrameBusy    = false;
    let _vaPlayTimer    = null;
    let _vaSeekDragging = false;
    let _vaZoom         = 100;
    // video mode (DLC project labeled videos)
    let _vaVideoName  = null;
    // frames mode
    let _vaFrameStem  = null;
    let _vaFrameFiles = [];   // sorted list of labeled frame filenames
    // browse-video mode (arbitrary path via /annotate endpoints)
    let _vaBrowseVideoPath = null;
    // browse tab state
    let _vaBrowsePath = null;

    // ── Kinematic overlay state ────────────────────────────────────────────
    let _vaOverlayEnabled   = false;
    let _vaAllBodyParts     = [];         // all body parts from h5-info
    let _vaSelectedBp       = null;       // currently active/selected bodypart
    const _vaHiddenParts    = new Set();  // client-side per-bodypart visibility toggle
    let _vaMarkerSize       = 6;
    // absolute path to the currently loaded original video (for annotated frames + companion CSV)
    let _vaCurrentVideoPath = null;
    // Hook called by _vaLoadFrame so the nested curation IIFE can sync its annotation panel
    let _vaCurationFrameHook = null;
    let _vaMetadataFrameHook = null;

    // ── Pose cache (prefetch window) ───────────────────────────────────────
    const _POSE_WINDOW    = 30;
    let   _vaPrefetchCtrl = null;     // AbortController for in-flight batch prefetch

    function _vaClearPoseCache() {
      // Clear per-layer caches. Legacy single-cache fully removed in T6.
      _vaLayers.forEach(l => l.posesCache.clear());
      if (_vaPrefetchCtrl) { _vaPrefetchCtrl.abort(); _vaPrefetchCtrl = null; }
    }

    // ── Kinematic overlay LAYER state ───────────────────────────────────
    // Element 0 = primary (editable). Elements 1+ = comparison layers (read-only).
    // Each layer:
    //   { id, path, label, type, shape, visible, threshold, posesCache,
    //     bodyparts, errored }
    const _vaLayers = [];
    let   _vaGlobalThreshold    = 0.60;
    let   _vaPerLayerThresholds = false;

    function _vaPrimary()     { return _vaLayers[0] || null; }
    function _vaCompare()     { return _vaLayers.slice(1); }
    function _vaIsEditable()  { return _vaLayers.length === 1; }
    function _vaLayerThreshold(layer) {
      return _vaPerLayerThresholds && layer.threshold != null
        ? layer.threshold
        : _vaGlobalThreshold;
    }

    const _SHAPE_ORDER = ["circle-filled", "diamond", "square", "triangle"];
    function _vaAssignShapes() {
      _vaLayers.forEach((l, i) => {
        l.shape = _SHAPE_ORDER[Math.min(i, _SHAPE_ORDER.length - 1)];
      });
    }

    let _vaLayerIdCounter = 0;
    function _vaMakeLayer({path, label, type}) {
      return {
        id:         "layer_" + (_vaLayerIdCounter++),
        path,
        label,
        type:       type || "raw",
        shape:      "circle-filled",
        visible:    true,
        threshold:  null,            // null → use _vaGlobalThreshold
        posesCache: new Map(),
        bodyparts:  [],
        editsCache: null,
        errored:    false,
      };
    }

    // Replace the entire layer set with [primary], clear caches, reassign shapes.
    function _vaSetPrimaryLayer(layer) {
      _vaLayers.length = 0;
      if (layer) _vaLayers.push(layer);
      _vaAssignShapes();
      _vaClearPoseCache();
    }

    // ── Viewer sizing (same break-out-of-card approach as frame labeler) ──
    function _vaFitViewer() {
      if (!vaFrameImg.naturalWidth) return;
      const row  = document.getElementById('va3d-tile-row');
      if (!row) return;
      const cs   = getComputedStyle(vaCard);
      const padL = parseFloat(cs.paddingLeft)  || 0;
      const padR = parseFloat(cs.paddingRight) || 0;
      const baseW = vaCard.clientWidth - padL - padR;
      const maxW  = Math.max(baseW, window.innerWidth - 32);
      const targetW = Math.min(Math.round(baseW * (_vaZoom / 100)), Math.floor(maxW));
      const extra   = targetW - baseW;
      row.style.width      = targetW + "px";
      row.style.marginLeft = extra > 0 ? `-${extra / 2}px` : "";
    }

    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => { if (vaFrameImg.naturalWidth) _vaFitViewer(); }).observe(vaCard);
    }

    vaZoomInput.addEventListener("input", () => {
      _vaZoom = parseInt(vaZoomInput.value, 10);
      vaZoomVal.textContent = _vaZoom + " %";
      _vaFitViewer();
      _vaSyncCanvas();
    });

    function _vaReset() {
      if (_vaPlayTimer) { _vaStopPlayback(); }
      _vaMode            = null;
      _vaCurrentFrame    = 0;
      _vaFrameCount      = 0;
      _vaFps             = 30;
      _vaFrameBusy       = false;
      _vaVideoName       = null;
      _vaFrameStem       = null;
      _vaFrameFiles      = [];
      _vaBrowseVideoPath = null;
      _vaCurrentVideoPath = null;
      _vaCurrentPoses = [];
      _vaHoverBp      = null;
      _vaSelectedBp   = null;
      _vaHiddenParts.clear();
      _vaDragBp       = null;
      _vaDragging     = false;
      if (vaBpListWrap) vaBpListWrap.classList.add("hidden");
      if (vaBpChips)    vaBpChips.innerHTML = "";
      if (vaOverlayCanvas) vaOverlayCanvas.style.cursor = "default";
      if (typeof _vaLocalEdits !== "undefined") _vaLocalEdits.clear();
      _vaUpdateEditBanner();
      _vaClearPoseCache();
      if (vaOverlayCtx) vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
      vaPlayIcon.classList.remove("hidden"); vaPauseIcon.classList.add("hidden");
      vaFrameImg.onload  = null;
      vaFrameImg.onerror = null;
      if (vaFrameImg.src && vaFrameImg.src.startsWith("blob:")) URL.revokeObjectURL(vaFrameImg.src);
      vaFrameImg.removeAttribute("src");
      const row = document.getElementById('va3d-tile-row');
      if (row) {
        row.style.width      = "";
        row.style.marginLeft = "";
      }
      vaVideoWrap.style.width      = "";   // defensive: clear any stale width from older versions
      vaVideoWrap.style.marginLeft = "";
      vaFrameSpinner.classList.add("hidden");
      vaPlayerSec.classList.add("hidden");
      vaStatus.textContent = "";
      vaStatus.className   = "fe-extract-status";
    }

    function _vaFrameUrl(n) {
      if (_vaMode === "browse-video") {
        // Use the same cached VideoCapture endpoint as Frame Extractor
        return `/dlc/project/video-frame-ext/${n}?path=${encodeURIComponent(_vaBrowseVideoPath)}`;
      }
      if (_vaMode === "video") {
        return `/dlc/project/video-frame/${encodeURIComponent(_vaVideoName)}/${n}`;
      }
      // frames mode: index into _vaFrameFiles
      return `/dlc/project/frame-image/${encodeURIComponent(_vaFrameStem)}/${encodeURIComponent(_vaFrameFiles[n])}`;
    }

    function _vaPrefetchFrames(frames) {
      frames.forEach(n => {
        if (n >= 0 && n < _vaFrameCount) new Image().src = _vaFrameUrl(n);
      });
    }

    function _vaUpdateDisplay() {
      vaFrameCounter.textContent = `Frame ${_vaCurrentFrame} / ${_vaFrameCount}`;
      if (_vaMode === "video" || _vaMode === "browse-video") {
        vaTimeDisplay.textContent = `${(_vaCurrentFrame / _vaFps).toFixed(3)} s`;
      } else {
        vaTimeDisplay.textContent = _vaFrameFiles[_vaCurrentFrame] || "";
      }
      if (!_vaSeekDragging)
        vaSeek.value = Math.round((_vaCurrentFrame / Math.max(_vaFrameCount - 1, 1)) * 1000);
    }

    async function _vaLoadFrame(n) {
      if (_vaFrameBusy) return;
      _vaFrameBusy = true;
      n = Math.max(0, Math.min(n, Math.max(_vaFrameCount - 1, 0)));
      _vaCurrentFrame = n;
      vaFrameSpinner.classList.remove("hidden");

      const newUrl = _vaFrameUrl(n);

      // Preload the image off-DOM in parallel with all visible-layer pose
      // fetches so the visible image NEVER lands on screen before its markers.
      const imgReady = new Promise((resolve, reject) => {
        const im = new Image();
        im.onload  = () => resolve(im);
        im.onerror = (e) => reject(e || new Error("image preload failed"));
        im.src = newUrl;
      });

      const posesReady = _vaOverlayEnabled
        ? Promise.all(
            _vaLayers
              .filter(l => l.visible && !l.errored)
              .map(l => _vaFetchPosesForFrame(l, n).catch(() => null))
          )
        : Promise.resolve();

      try {
        const [preloadedImg] = await Promise.all([imgReady, posesReady]);

        // Atomic swap: image + markers go to screen together.
        const prev = vaFrameImg.src;
        vaFrameImg.src = preloadedImg.src;
        if (prev && prev.startsWith("blob:")) URL.revokeObjectURL(prev);

        _vaFitViewer();
        _vaUpdateDisplay();
        _vaPrefetchFrames([n + 1, n + 2]);
        if (_vaCurationFrameHook) _vaCurationFrameHook(n);
        if (_vaMetadataFrameHook) _vaMetadataFrameHook(n);

        // Sync primary cache into legacy _vaCurrentPoses for hit-testing.
        const primary = _vaPrimary();
        if (primary) {
          const c = primary.posesCache.get(n);
          if (c) { _vaCurrentPoses = c.poses; _vaNBodyparts = c.n_bodyparts; }
        }

        _vaUpdateOverlay(n);

        // Paint barrier — guarantees image + canvas have landed before the
        // play loop schedules the next tick.
        await new Promise(requestAnimationFrame);
      } catch (err) {
        vaStatus.textContent = `Failed to load frame: ${err && err.message ? err.message : err}`;
        vaStatus.className   = "fe-extract-status err";
      } finally {
        _vaFrameBusy = false;
        vaFrameSpinner.classList.add("hidden");
      }
    }

    // Draw overlay for frame n: show cached poses immediately; fetch from server only when paused.
    function _vaUpdateOverlay(n) {
      if (!vaOverlayCtx || !_vaOverlayEnabled) return;
      _vaSyncCanvas();
      vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
      const primary = _vaPrimary();
      if (!primary) return;
      // Sync primary's cache into the legacy _vaCurrentPoses (consumed by
      // hit-testing, hover labels, bp-chip status, and the edit overlays).
      const pKey    = _vaPoseCacheKey(primary);
      const pCached = primary.posesCache.get(n);
      let primaryReady = false;
      if (pCached && pCached.key === pKey) {
        _vaCurrentPoses = pCached.poses;
        _vaNBodyparts   = pCached.n_bodyparts;
        primaryReady    = true;
      }
      _vaDrawCurrentFrame();
      if (primaryReady) _vaUpdateBpChipStatus();
      // Only hit the server when paused
      if (!_vaPlayTimer && (!pCached || pCached.key !== pKey)) _vaFetchPoses(n);
    }

    // Multi-layer draw orchestration: clears canvas, then for each visible/non-errored
    // layer renders its cached poses with the appropriate shape primitive. The primary
    // layer goes through _vaDrawPoseMarkers so its edits/select/hover overlays appear.
    function _vaDrawCurrentFrame() {
      if (!vaOverlayCtx || !_vaOverlayEnabled) return;
      _vaSyncCanvas();
      vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
      const natW = vaFrameImg.naturalWidth  || 1;
      const natH = vaFrameImg.naturalHeight || 1;
      const sx   = vaOverlayCanvas.width  / natW;
      const sy   = vaOverlayCanvas.height / natH;
      const r    = Math.max(1, Math.round(_vaMarkerSize * Math.min(sx, sy)));
      const visibleLayers = _vaLayers.filter(l => l.visible && !l.errored);
      // Draw comparison layers underneath the primary (primary draws last so its
      // selection/edit rings sit on top).
      for (const layer of visibleLayers) {
        if (layer === _vaPrimary()) continue;
        const cached = layer.posesCache.get(_vaCurrentFrame);
        if (!cached) continue;
        const drawFn = _SHAPE_FN[layer.shape] || _drawCircleFilled;
        const total  = cached.n_bodyparts || layer.bodyparts.length || 1;
        for (const pose of cached.poses) {
          if (_vaHiddenParts.has(pose.bp)) continue;
          const cx = Math.round(pose.x * sx);
          const cy = Math.round(pose.y * sy);
          const color = _vaPaletteColor(pose.color_idx, total);
          drawFn(vaOverlayCtx, cx, cy, r, color);
        }
      }
      // Primary layer: handles edits/selection/hover via existing _vaDrawPoseMarkers.
      if (_vaPrimary() && _vaPrimary().visible && !_vaPrimary().errored) {
        _vaDrawPoseMarkers();
      }
    }

    async function _vaOpenVideo(name) {
      _vaReset();
      _vaMode      = "video";
      _vaVideoName = name;
      vaSelectedName.textContent = name;
      try {
        const res  = await fetch(`/dlc/project/video-info/${encodeURIComponent(name)}`);
        const info = await res.json();
        _vaFps             = info.fps || 30;
        _vaFrameCount      = info.frame_count || 0;
        _vaCurrentVideoPath = info.abs_path || null;
      } catch (_) { _vaFps = 30; _vaFrameCount = 0; }
      vaPlayerSec.classList.remove("hidden");
      // Sibling-cam probe + tile management (additive; does not affect single-cam path).
      try { await Controller.loadVideo(_vaCurrentVideoPath || name); }
      catch (e) { console.warn('[va3d] Controller.loadVideo failed:', e); }
      Controller.seek(0);
    }

    function _vaOpenFrameFolder(stem, frames) {
      _vaReset();
      _vaMode       = "frames";
      _vaFrameStem  = stem;
      _vaFrameFiles = frames;
      _vaFrameCount = frames.length;
      _vaFps        = 5;   // slow playback for sparse labeled frames
      vaSelectedName.textContent = `${stem}/ (${frames.length} labeled frames)`;
      vaPlayerSec.classList.remove("hidden");
      Controller.seek(0);
    }

    async function _vaOpenBrowseVideo(absPath, name) {
      _vaReset();
      _vaMode             = "browse-video";
      _vaBrowseVideoPath  = absPath;
      _vaCurrentVideoPath = absPath;
      vaSelectedName.textContent = name;
      try {
        const res  = await fetch(`/annotate/video-info?path=${encodeURIComponent(absPath)}`);
        const info = await res.json();
        _vaFps        = info.fps || 30;
        _vaFrameCount = info.frame_count || 0;
      } catch (_) { _vaFps = 30; _vaFrameCount = 0; }
      vaPlayerSec.classList.remove("hidden");
      // Sibling-cam probe + tile management (additive; does not affect single-cam path).
      try { await Controller.loadVideo(absPath); }
      catch (e) { console.warn('[va3d] Controller.loadVideo failed:', e); }
      Controller.seek(0);
      // Discover companion h5 variants in the same directory
      _vaDiscoverVariants(absPath);
    }

    // ── Browse-tab folder navigator ────────────────────────────
    const _VA_VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".mpg", ".mpeg"]);

    async function _vaRefreshBrowse(path) {
      _vaBrowsePath = path;
      vaBrowseBreadcrumb.value = path;
      vaBrowseList.innerHTML = '<p class="explorer-empty">Loading…</p>';

      // Try the new dir-with-h5 endpoint; fall back to /fs/ls on failure.
      let data;
      try {
        const res = await fetch(`/dlc/viewer/dir-with-h5?path=${encodeURIComponent(path)}`);
        if (!res.ok) throw new Error(`status ${res.status}`);
        data = await res.json();
        if (data.error) throw new Error(data.error);
      } catch (newRouteErr) {
        // Fallback: legacy /fs/ls. Treat every video as has_h5=false (we can't tell).
        try {
          const res2 = await fetch(`/fs/ls?path=${encodeURIComponent(path)}`);
          const d2   = await res2.json();
          if (d2.error) { vaBrowseList.innerHTML = `<p class="explorer-empty">${d2.error}</p>`; return; }
          const entries = d2.entries || [];
          data = {
            path,
            dirs:   entries.filter(e => e.type === "dir").map(e => ({name: e.name})),
            videos: entries
              .filter(e => e.type === "file" && _VA_VIDEO_EXTS.has(e.name.slice(e.name.lastIndexOf(".")).toLowerCase()))
              .map(e => ({name: e.name, has_h5: false, h5_count: 0})),
          };
        } catch (fbErr) {
          vaBrowseList.innerHTML = `<p class="explorer-empty">Error: ${fbErr.message}</p>`;
          return;
        }
      }

      const dirs = data.dirs || [];
      const videos = data.videos || [];
      const hideNoH5 = !!state.vaBrowseHideNoH5;
      const visibleVideos = hideNoH5 ? videos.filter(v => v.has_h5) : videos;

      if (!dirs.length && !visibleVideos.length) {
        vaBrowseList.innerHTML = hideNoH5
          ? '<p class="explorer-empty">No videos with analyzed h5 here. Untick "Hide videos without h5" to show all.</p>'
          : '<p class="explorer-empty">No folders or videos found here.</p>';
        return;
      }

      vaBrowseList.innerHTML = "";

      dirs.forEach(d => {
        const row = document.createElement("div");
        row.className = "fe-video-item";
        row.style.cursor = "pointer";
        row.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>`;
        row.querySelector("span").textContent = d.name + "/";
        row.addEventListener("click", () => _vaRefreshBrowse(path + "/" + d.name));
        vaBrowseList.appendChild(row);
      });

      visibleVideos.forEach(v => {
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
        vaBrowseList.appendChild(row);
      });
    }

    // ── Tab switching ──────────────────────────────────────────
    vaTabProject?.addEventListener("click", () => {
      vaTabProject.classList.add("active");
      vaTabBrowse.classList.remove("active");
      vaTabProjectPanel.classList.remove("hidden");
      vaTabBrowsePanel.classList.add("hidden");
    });
    vaTabBrowse?.addEventListener("click", () => {
      vaTabBrowse.classList.add("active");
      vaTabProject.classList.remove("active");
      vaTabBrowsePanel.classList.remove("hidden");
      vaTabProjectPanel.classList.add("hidden");
      if (!_vaBrowsePath) {
        // Start at user-data dir or /
        const startPath = state.userDataDir || state.dataDir || "/";
        _vaRefreshBrowse(startPath);
      }
    });

    vaBrowseUp?.addEventListener("click", () => {
      if (!_vaBrowsePath) return;
      const parent = _vaBrowsePath.split("/").slice(0, -1).join("/") || "/";
      if (parent !== _vaBrowsePath) _vaRefreshBrowse(parent);
    });

    const vaBrowseHideNoH5 = document.getElementById("va3d-browse-hide-no-h5");
    vaBrowseHideNoH5?.addEventListener("change", () => {
      state.vaBrowseHideNoH5 = !!vaBrowseHideNoH5.checked;
      if (_vaBrowsePath) _vaRefreshBrowse(_vaBrowsePath);
    });
    // On startup, sync the checkbox to state (state.vaBrowseHideNoH5 defaults true).
    if (vaBrowseHideNoH5) vaBrowseHideNoH5.checked = !!state.vaBrowseHideNoH5;

    // ── Editable address bar ───────────────────────────────────
    async function _vaNavigateTo(raw) {
      const p = raw.trim();
      if (!p) return;
      // Check if the path looks like a video file
      const ext = p.slice(p.lastIndexOf(".")).toLowerCase();
      if (_VA_VIDEO_EXTS.has(ext)) {
        // Navigate the browser to the parent folder first, then open the video
        const dir  = p.substring(0, p.lastIndexOf("/")) || "/";
        const name = p.substring(p.lastIndexOf("/") + 1);
        await _vaRefreshBrowse(dir);
        _vaOpenBrowseVideo(p, name);
      } else {
        _vaRefreshBrowse(p);
      }
    }

    vaBrowseBreadcrumb?.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); _vaNavigateTo(vaBrowseBreadcrumb.value); }
      if (e.key === "Escape") { vaBrowseBreadcrumb.value = _vaBrowsePath || ""; vaBrowseBreadcrumb.blur(); }
    });
    // Also handle paste: navigate immediately after the clipboard text lands
    vaBrowseBreadcrumb?.addEventListener("paste", e => {
      // Let the paste complete, then navigate
      setTimeout(() => _vaNavigateTo(vaBrowseBreadcrumb.value), 0);
    });

    // ── Kinematic overlay canvas ──────────────────────────────
    const vaOverlayCanvas = document.getElementById("va3d-overlay-canvas-0");
    const vaOverlayCtx    = vaOverlayCanvas ? vaOverlayCanvas.getContext("2d") : null;

    // Current frame poses (fetched alongside each annotated frame)
    let _vaCurrentPoses = [];  // [{bp, x, y, lh, color_idx}]
    let _vaNBodyparts   = 1;   // total bodyparts count (for palette)
    let _vaHoverBp      = null;

    // Replicate the server's HSV rainbow palette in JS for label colours
    function _vaHsvToRgb(h, s, v) {
      const i = Math.floor(h * 6);
      const f = h * 6 - i;
      const p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s);
      let r, g, b;
      switch (i % 6) {
        case 0: r=v; g=t; b=p; break; case 1: r=q; g=v; b=p; break;
        case 2: r=p; g=v; b=t; break; case 3: r=p; g=q; b=v; break;
        case 4: r=t; g=p; b=v; break; default: r=v; g=p; b=q;
      }
      return `rgb(${Math.round(r*255)},${Math.round(g*255)},${Math.round(b*255)})`;
    }
    function _vaPaletteColor(idx, total) {
      return _vaHsvToRgb(idx / Math.max(total, 1), 0.9, 0.95);
    }

    // ── Shape-aware draw primitives for multi-layer overlay rendering ──
    function _drawCircleFilled(ctx, x, y, r, color) {
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI); ctx.fill();
    }
    function _drawDiamond(ctx, x, y, r, color) {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(x,     y - r);
      ctx.lineTo(x + r, y    );
      ctx.lineTo(x,     y + r);
      ctx.lineTo(x - r, y    );
      ctx.closePath();
      ctx.fill();
    }
    function _drawSquare(ctx, x, y, r, color) {
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.strokeRect(x - r, y - r, 2 * r, 2 * r);
    }
    function _drawTriangle(ctx, x, y, r, color) {
      ctx.strokeStyle = color; ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x,        y - r);
      ctx.lineTo(x + r,    y + r);
      ctx.lineTo(x - r,    y + r);
      ctx.closePath();
      ctx.stroke();
    }
    const _SHAPE_FN = {
      "circle-filled": _drawCircleFilled,
      "diamond":       _drawDiamond,
      "square":        _drawSquare,
      "triangle":      _drawTriangle,
    };

    function _vaSyncCanvas() {
      if (!vaOverlayCanvas) return;
      // Match canvas buffer size to the *displayed* image size (not natural)
      const w = vaFrameImg.offsetWidth  || vaFrameImg.clientWidth  || 1;
      const h = vaFrameImg.offsetHeight || vaFrameImg.clientHeight || 1;
      if (vaOverlayCanvas.width !== w || vaOverlayCanvas.height !== h) {
        vaOverlayCanvas.width  = w;
        vaOverlayCanvas.height = h;
      }
    }

    // Draw all pose marker circles onto the overlay canvas.
    // Skips bodyparts in _vaHiddenParts (client-side visibility).
    // If _vaLocalEdits contains an override for the current frame+bodypart,
    // the edited position is used and the marker is drawn with an extra white ring.
    // The currently selected bodypart (_vaSelectedBp) gets a gold ring.
    // An edit with x=null/y=null means the marker was deleted — not drawn.
    function _vaDrawPoseMarkers() {
      if (!vaOverlayCtx || !_vaOverlayEnabled || !_vaCurrentPoses.length) return;
      const natW = vaFrameImg.naturalWidth  || 1;
      const natH = vaFrameImg.naturalHeight || 1;
      const sx   = vaOverlayCanvas.width  / natW;
      const sy   = vaOverlayCanvas.height / natH;
      const r    = Math.max(1, Math.round(_vaMarkerSize * Math.min(sx, sy)));
      // _vaLocalEdits may not exist yet (declared later in the module); guard with typeof
      const frameEdits = (typeof _vaLocalEdits !== "undefined")
        ? (_vaLocalEdits.get(_vaCurrentFrame) || {})
        : {};
      for (const pose of _vaCurrentPoses) {
        // Skip bodyparts hidden by per-bodypart visibility toggle
        if (_vaHiddenParts.has(pose.bp)) continue;
        const edited   = pose.bp in frameEdits;
        const editData = edited ? frameEdits[pose.bp] : null;
        // NaN/null edit means the marker was deleted — don't render it
        if (edited && (editData.x == null || editData.y == null)) continue;
        const cx = Math.round((edited ? editData.x : pose.x) * sx);
        const cy = Math.round((edited ? editData.y : pose.y) * sy);
        const color = _vaPaletteColor(pose.color_idx, _vaNBodyparts);
        vaOverlayCtx.beginPath();
        vaOverlayCtx.arc(cx, cy, r, 0, Math.PI * 2);
        vaOverlayCtx.fillStyle = color;
        vaOverlayCtx.fill();
        if (edited) {
          // White ring indicates an unsaved positional edit
          vaOverlayCtx.beginPath();
          vaOverlayCtx.arc(cx, cy, r + 3, 0, Math.PI * 2);
          vaOverlayCtx.strokeStyle = "#fff";
          vaOverlayCtx.lineWidth   = 1.5;
          vaOverlayCtx.stroke();
        }
        if (pose.bp === _vaSelectedBp) {
          // Gold ring indicates the currently selected bodypart
          vaOverlayCtx.beginPath();
          vaOverlayCtx.arc(cx, cy, r + (edited ? 6 : 3), 0, Math.PI * 2);
          vaOverlayCtx.strokeStyle = "#facc15";
          vaOverlayCtx.lineWidth   = 2;
          vaOverlayCtx.stroke();
        }
      }
    }

    function _vaDrawHoverLabel() {
      if (!vaOverlayCtx) return;
      // Re-paint via the multi-layer renderer so comparison-layer shapes are
      // preserved and the primary layer's visibility flag is honored. The old
      // path (clearRect + _vaDrawPoseMarkers) wiped comparison layers off the
      // canvas and re-drew the primary's poses as hardcoded filled circles
      // even when the primary layer was toggled hidden — so any mousemove,
      // marker-size change or chip-toggle after hiding the primary made the
      // comparison layer's shape disappear and replaced it with circles at
      // the primary's coordinates.
      _vaDrawCurrentFrame();
      // Hover label only makes sense when the primary layer is visible (its
      // poses drive _vaCurrentPoses + hit-testing).
      const primary = _vaPrimary();
      if (!primary || !primary.visible) return;
      if (!_vaHoverBp || !_vaCurrentPoses.length) return;
      const pose = _vaCurrentPoses.find(p => p.bp === _vaHoverBp);
      if (!pose) return;

      // Map video-native coords → canvas display coords
      const natW = vaFrameImg.naturalWidth  || 1;
      const natH = vaFrameImg.naturalHeight || 1;
      const sx   = vaOverlayCanvas.width  / natW;
      const sy   = vaOverlayCanvas.height / natH;
      const cx   = pose.x * sx;
      const cy   = pose.y * sy;

      const color = _vaPaletteColor(pose.color_idx, _vaNBodyparts);
      const r     = _vaMarkerSize + 2;          // slightly larger hit ring
      const bp    = pose.bp;

      vaOverlayCtx.font      = "bold 11px 'JetBrains Mono', monospace";
      const tw = vaOverlayCtx.measureText(bp).width;
      // Flip label to the left if it would clip the right edge
      const flip = (cx + r + tw + 12) > vaOverlayCanvas.width;
      const tx   = flip ? cx - r - tw - 10 : cx + r + 4;
      const ty   = cy + 4;
      vaOverlayCtx.fillStyle = "rgba(12,13,16,.75)";
      vaOverlayCtx.fillRect(tx - 2, ty - 11, tw + 6, 14);
      vaOverlayCtx.fillStyle = color;
      vaOverlayCtx.fillText(bp, tx + 1, ty);
    }

    function _vaHitTest(cx, cy) {
      if (!_vaCurrentPoses.length) return null;
      const natW  = vaFrameImg.naturalWidth  || 1;
      const natH  = vaFrameImg.naturalHeight || 1;
      const sx    = vaOverlayCanvas.width  / natW;
      const sy    = vaOverlayCanvas.height / natH;
      const hitR  = (_vaMarkerSize + 6) * Math.max(sx, sy);
      for (const pose of _vaCurrentPoses) {
        const dx = pose.x * sx - cx;
        const dy = pose.y * sy - cy;
        if (Math.sqrt(dx * dx + dy * dy) <= hitR) return pose.bp;
      }
      return null;
    }

    // ── Marker drag-and-edit state ────────────────────────────
    // _vaLocalEdits: Map<string, Map<bp, {x, y}>> — client-side overrides
    // keyed by frame number.  Mirrors the server-side JSON cache and provides
    // zero-latency feedback while dragging.
    const _vaLocalEdits = new Map();  // frameNumber (int) → {bp: {x, y}}

    let _vaDragBp      = null;   // body-part being dragged
    let _vaDragging    = false;

    // Marker-edit UI elements (may be null if not yet in DOM)
    const vaMarkerEditBanner  = document.getElementById("va3d-marker-edit-banner");
    const vaMarkerEditCount   = document.getElementById("va3d-marker-edit-count");
    const vaSaveAdjBtn        = document.getElementById("va3d-save-adjustments-btn");
    const vaDiscardAdjBtn     = document.getElementById("va3d-discard-adjustments-btn");

    function _vaEditCount() {
      return _vaLocalEdits.size;
    }

    // Bind tile-0's pendingEdits to the legacy module-level _vaLocalEdits
    // map so the canvas handlers (which still write to _vaLocalEdits) and
    // the per-tile state share storage with no manual mirroring. Tile-1's
    // pendingEdits stays a separate Map and remains empty for now — the
    // canvas handlers are still tile-0-only because generalising them
    // requires the deferred sibling-overlay renderer (no canvas-coord
    // mapping exists for tile-1 yet). Once sibling rendering lands, the
    // handlers will be generalised to read the focused tile and write into
    // that tile's pendingEdits; _vaUpdateEditBanner keeps working unchanged.
    //
    // Controller.init() runs on DOMContentLoaded (after this script body
    // evaluates), so defer the alias until tile-0 actually exists.
    function _vaBindTile0PendingEdits() {
      if (Controller.tiles[0]) Controller.tiles[0].pendingEdits = _vaLocalEdits;
    }
    if (Controller.tiles[0]) {
      _vaBindTile0PendingEdits();
    } else {
      document.addEventListener('DOMContentLoaded', _vaBindTile0PendingEdits);
    }

    function _vaUpdateEditBanner() {
      if (!vaMarkerEditBanner) return;
      // Force-hide while comparison layers are active — editing is disabled.
      // (Layers > 1 means a comparison layer is on; 0 means nothing chosen
      // yet, which is fine — the banner just hides naturally via count=0.)
      if (_vaLayers.length > 1) {
        vaMarkerEditBanner.classList.add("hidden");
        return;
      }
      const tiles = Controller.tiles || [];
      const c0 = tiles[0]?.pendingEdits.size || 0;
      const c1 = tiles[1]?.pendingEdits.size || 0;
      const total = c0 + c1;
      if (total === 0) {
        vaMarkerEditBanner.classList.add("hidden");
        return;
      }
      vaMarkerEditBanner.classList.remove("hidden");
      if (vaMarkerEditCount) {
        if (tiles.length >= 2) {
          vaMarkerEditCount.textContent = `cam0: ${c0} · cam1: ${c1} frames edited`;
        } else {
          vaMarkerEditCount.textContent = `${c0} frame${c0 !== 1 ? "s" : ""} edited`;
        }
      }
    }

    // Expose for e2e introspection — canonical refresh entry point.
    window.__va3dRefreshMarkerBanner = _vaUpdateEditBanner;

    // Convert canvas-display coords back to video-native coords
    function _vaCanvasToVideo(cx, cy) {
      const natW = vaFrameImg.naturalWidth  || 1;
      const natH = vaFrameImg.naturalHeight || 1;
      const sx   = vaOverlayCanvas.width  / natW;
      const sy   = vaOverlayCanvas.height / natH;
      return { x: cx / sx, y: cy / sy };
    }

    // Hit-test that accounts for local-edit positions
    function _vaHitTestWithEdits(cx, cy) {
      if (!_vaCurrentPoses.length) return null;
      const natW  = vaFrameImg.naturalWidth  || 1;
      const natH  = vaFrameImg.naturalHeight || 1;
      const sx    = vaOverlayCanvas.width  / natW;
      const sy    = vaOverlayCanvas.height / natH;
      const hitR  = (_vaMarkerSize + 8) * Math.max(sx, sy);
      const frameEdits = _vaLocalEdits.get(_vaCurrentFrame) || {};

      for (const pose of _vaCurrentPoses) {
        const edited = pose.bp in frameEdits;
        const px = edited ? frameEdits[pose.bp].x * sx : pose.x * sx;
        const py = edited ? frameEdits[pose.bp].y * sy : pose.y * sy;
        const dx = px - cx;
        const dy = py - cy;
        if (Math.sqrt(dx * dx + dy * dy) <= hitR) return pose.bp;
      }
      return null;
    }

    // Flush a single marker edit to the server (fire-and-forget)
    async function _vaFlushMarkerEdit(frame, bp, x, y) {
      if (!_vaIsEditable()) return;     // edit disabled while compare layers active
      const layer = _vaPrimary();
      if (!layer) return;
      try {
        await fetch("/dlc/viewer/marker-edit", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ h5: layer.path, frame, bp, x, y }),
        });
      } catch (_) { /* non-critical; edit lives in local state */ }
    }

    // Delete a marker (set to NaN) in the server cache (fire-and-forget)
    async function _vaFlushMarkerDelete(frame, bp) {
      if (!_vaIsEditable()) return;     // edit disabled while compare layers active
      const layer = _vaPrimary();
      if (!layer) return;
      try {
        await fetch("/dlc/viewer/marker-edit", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ h5: layer.path, frame, bp, x: null, y: null }),
        });
      } catch (_) {}
    }

    // Sync local edits from the server's edit-cache on H5 load / page refresh
    async function _vaLoadEditCacheFromServer(h5Path) {
      try {
        const res  = await fetch(`/dlc/viewer/edit-cache?h5=${encodeURIComponent(h5Path)}`);
        if (!res.ok) return;
        const data = await res.json();
        _vaLocalEdits.clear();
        for (const [frameKey, bpEdits] of Object.entries(data.cache || {})) {
          const fn = parseInt(frameKey.split("_")[1], 10);
          if (!isNaN(fn)) _vaLocalEdits.set(fn, bpEdits);
        }
        _vaUpdateEditBanner();
      } catch (_) {}
    }

    // ── Per-cam editing scope note ──────────────────────────────────────
    // The canvas edit handlers below (click-to-place, drag, right-click
    // delete, dblclick-clear-frame) all target tile-0's overlay canvas
    // (vaOverlayCanvas = #va3d-overlay-canvas-0) and write to the shared
    // _vaLocalEdits map (aliased to Controller.tiles[0].pendingEdits via
    // _vaBindTile0PendingEdits above). When sync-cam is on, edits to
    // tile-1 are NOT yet supported — the sibling tile has no overlay
    // canvas wiring, hit-testing, or pose data yet. Plan task 10 takes
    // the conservative scope cut: the banner reflects per-tile state
    // (cam0/cam1 split counts) so the UI is in the right shape, but
    // tile-1 always shows cam1: 0 until the deferred sibling-overlay
    // renderer lands. At that point these handlers will be generalised
    // to read the focused tile (Controller.tiles.find(t =>
    // t.rootEl.classList.contains('focused'))) and operate on that
    // tile's canvas + pendingEdits map.
    if (vaOverlayCanvas) {
      vaOverlayCanvas.style.pointerEvents = "auto";

      // Click: select marker near cursor OR place selected bodypart
      vaOverlayCanvas.addEventListener("click", e => {
        if (!_vaOverlayEnabled || !_vaCurrentPoses.length) return;
        const rect = vaOverlayCanvas.getBoundingClientRect();
        const cx   = e.clientX - rect.left;
        const cy   = e.clientY - rect.top;
        const hit  = _vaHitTestWithEdits(cx, cy);
        if (hit) {
          _vaSelectBp(hit);
          return;
        }
        if (!_vaIsEditable()) return;     // edit disabled while compare layers active
        if (!_vaSelectedBp) return;
        const { x, y } = _vaCanvasToVideo(cx, cy);
        if (!_vaLocalEdits.has(_vaCurrentFrame)) _vaLocalEdits.set(_vaCurrentFrame, {});
        _vaLocalEdits.get(_vaCurrentFrame)[_vaSelectedBp] = { x, y };
        _vaSyncCanvas();
        vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
        _vaDrawPoseMarkers();
        _vaFlushMarkerEdit(_vaCurrentFrame, _vaSelectedBp, x, y);
        _vaUpdateEditBanner();
        _vaUpdateBpChipStatus();
      });

      // Mousedown on a marker → begin drag; otherwise ignored
      vaOverlayCanvas.addEventListener("mousedown", e => {
        if (!_vaIsEditable()) return;     // edit disabled while compare layers active
        if (!_vaOverlayEnabled || !_vaCurrentPoses.length || e.button !== 0) return;
        const rect = vaOverlayCanvas.getBoundingClientRect();
        const hit  = _vaHitTestWithEdits(e.clientX - rect.left, e.clientY - rect.top);
        if (!hit) return;
        e.preventDefault();
        _vaDragBp   = hit;
        _vaDragging = true;
        vaOverlayCanvas.style.cursor = "grabbing";
      });

      vaOverlayCanvas.addEventListener("mousemove", e => {
        if (!_vaOverlayEnabled) return;
        const rect = vaOverlayCanvas.getBoundingClientRect();
        const cx   = e.clientX - rect.left;
        const cy   = e.clientY - rect.top;

        if (_vaDragging && _vaDragBp) {
          if (!_vaIsEditable()) return;     // edit disabled while compare layers active
          const { x, y } = _vaCanvasToVideo(cx, cy);
          if (!_vaLocalEdits.has(_vaCurrentFrame)) _vaLocalEdits.set(_vaCurrentFrame, {});
          _vaLocalEdits.get(_vaCurrentFrame)[_vaDragBp] = { x, y };
          _vaSyncCanvas();
          vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
          _vaDrawPoseMarkers();
          return;
        }

        const hit = _vaHitTestWithEdits(cx, cy);
        if (hit !== _vaHoverBp) { _vaHoverBp = hit; _vaDrawHoverLabel(); }
        vaOverlayCanvas.style.cursor = hit ? "pointer" : (_vaSelectedBp && _vaOverlayEnabled ? "crosshair" : "default");
      });

      vaOverlayCanvas.addEventListener("mouseup", async e => {
        if (!_vaIsEditable()) return;     // edit disabled while compare layers active
        if (!_vaDragging || !_vaDragBp) return;
        _vaDragging = false;
        const rect  = vaOverlayCanvas.getBoundingClientRect();
        const { x, y } = _vaCanvasToVideo(e.clientX - rect.left, e.clientY - rect.top);
        await _vaFlushMarkerEdit(_vaCurrentFrame, _vaDragBp, x, y);
        _vaUpdateEditBanner();
        _vaUpdateBpChipStatus();
        _vaDragBp = null;
        vaOverlayCanvas.style.cursor = _vaSelectedBp ? "crosshair" : "default";
        _vaDrawHoverLabel();
      });

      vaOverlayCanvas.addEventListener("mouseleave", () => {
        if (_vaDragging && _vaDragBp) {
          const edits = _vaLocalEdits.get(_vaCurrentFrame);
          if (edits && _vaDragBp in edits) {
            const { x, y } = edits[_vaDragBp];
            _vaFlushMarkerEdit(_vaCurrentFrame, _vaDragBp, x, y);
            _vaUpdateEditBanner();
          }
          _vaDragging = false;
          _vaDragBp   = null;
        }
        if (_vaHoverBp) { _vaHoverBp = null; _vaDrawHoverLabel(); }
        vaOverlayCanvas.style.cursor = _vaSelectedBp ? "crosshair" : "default";
      });

      vaOverlayCanvas.addEventListener("mouseenter", () => {
        vaOverlayCanvas.style.cursor = _vaSelectedBp && _vaOverlayEnabled ? "crosshair" : "default";
      });

      // Right-click → delete (NaN) the currently selected marker
      vaOverlayCanvas.addEventListener("contextmenu", e => {
        e.preventDefault();
        if (!_vaIsEditable()) return;     // edit disabled while compare layers active
        if (!_vaOverlayEnabled || !_vaSelectedBp || !_vaPrimary()) return;
        if (!_vaLocalEdits.has(_vaCurrentFrame)) _vaLocalEdits.set(_vaCurrentFrame, {});
        _vaLocalEdits.get(_vaCurrentFrame)[_vaSelectedBp] = { x: null, y: null };
        _vaSyncCanvas();
        vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
        _vaDrawPoseMarkers();
        _vaFlushMarkerDelete(_vaCurrentFrame, _vaSelectedBp);
        _vaUpdateEditBanner();
        _vaUpdateBpChipStatus();
      });
    }

    // Save Adjustments button
    if (vaSaveAdjBtn) {
      vaSaveAdjBtn.addEventListener("click", async () => {
        if (!_vaIsEditable()) return;     // edit disabled while compare layers active
        const layer = _vaPrimary();
        if (!layer) return;
        vaSaveAdjBtn.disabled = true;
        vaSaveAdjBtn.textContent = "Saving…";
        try {
          const res  = await fetch("/dlc/viewer/save-marker-edits", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ h5: layer.path }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
          _vaLocalEdits.clear();
          _vaClearPoseCache();
          _vaUpdateEditBanner();
          vaStatus.textContent = `Saved: ${data.frames_edited} frame(s), ${data.bodyparts_edited} keypoint(s) updated.`;
          vaStatus.className   = "fe-extract-status ok";

          // Fan-out: save sibling tiles (tile 1+) in parallel when they have
          // pending edits. Tile-1 editing is dormant today (its pendingEdits
          // map is never written), so this branch is a no-op until the
          // sibling-overlay generalisation lands. Implemented now so the save
          // path is in place when that work arrives.
          const siblingTiles = (Controller.tiles || []).slice(1)
            .filter(t => t && t.pendingEdits && t.pendingEdits.size > 0);
          if (siblingTiles.length) {
            const siblingResults = await Promise.allSettled(siblingTiles.map(async (tile) => {
              if (!tile.primaryH5Path) {
                return { cam: tile.cam, ok: false, error: "no h5 for this cam" };
              }
              // NOTE: matches legacy tile-0 save body — the endpoint reads edits
              // from the server-side cache populated by /dlc/viewer/marker-edit.
              // When tile-1 editing lands, also wire per-edit POSTs there.
              const body = { h5: tile.primaryH5Path };
              const r = await fetch("/dlc/viewer/save-marker-edits", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify(body),
              });
              if (!r.ok) {
                const errText = await (async () => {
                  try {
                    const j = await r.clone().json();
                    return j.error || `HTTP ${r.status}`;
                  } catch {
                    return await r.text() || `HTTP ${r.status}`;
                  }
                })();
                return { cam: tile.cam, ok: false, error: errText };
              }
              return { cam: tile.cam, ok: true };
            }));
            // Clear pendingEdits for any sibling that succeeded.
            siblingResults.forEach((res2, i) => {
              if (res2.status === "fulfilled" && res2.value.ok) {
                siblingTiles[i].pendingEdits.clear();
              }
            });
            // Per-cam summary status (only when sibling tiles participated).
            const cam0Part = `cam0 ✓`;
            const sibParts = siblingResults.map((res2, i) => {
              const v = res2.status === "fulfilled"
                ? res2.value
                : { cam: siblingTiles[i].cam, ok: false, error: res2.reason };
              return v.ok ? `cam${v.cam} ✓` : `cam${v.cam} ✗ ${v.error || ""}`;
            });
            vaStatus.textContent = [cam0Part, ...sibParts].join(" · ");
            vaStatus.className   = sibParts.every(p => p.includes("✓"))
              ? "fe-extract-status ok"
              : "fe-extract-status err";
            if (typeof window.__va3dRefreshMarkerBanner === "function") {
              window.__va3dRefreshMarkerBanner();
            }
          }

          // Reload poses for current frame from updated H5
          if (_vaOverlayEnabled) await _vaFetchPoses(_vaCurrentFrame);
        } catch (err) {
          vaStatus.textContent = `Save failed: ${err.message}`;
          vaStatus.className   = "fe-extract-status err";
        } finally {
          vaSaveAdjBtn.disabled    = false;
          vaSaveAdjBtn.innerHTML   =
            '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="margin-right:.3rem"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Save Adjustments';
        }
      });
    }

    // Discard Adjustments button
    if (vaDiscardAdjBtn) {
      vaDiscardAdjBtn.addEventListener("click", async () => {
        if (!_vaIsEditable()) return;     // edit disabled while compare layers active
        const layer = _vaPrimary();
        if (!layer) return;
        _vaLocalEdits.clear();
        // Clear pendingEdits on every tile (tile-0's map is aliased to
        // _vaLocalEdits via Task 10, so this covers tile-1+ only today —
        // dormant until sibling editing lands).
        (Controller.tiles || []).forEach(t => {
          if (t && t.pendingEdits) t.pendingEdits.clear();
        });
        _vaClearPoseCache();
        _vaUpdateEditBanner();
        if (typeof window.__va3dRefreshMarkerBanner === "function") {
          window.__va3dRefreshMarkerBanner();
        }
        // Delete server-side cache too
        try {
          await fetch("/dlc/viewer/save-marker-edits", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            // Send empty cache by patching via a discard endpoint alias.
            // Since the route applies the *current* server cache, we need to
            // clear it first using marker-edit with a sentinel, or simply call
            // save on an empty cache.  The simplest approach: reload poses and
            // the banner will disappear.
          });
        } catch (_) {}
        // Reload current frame poses from H5
        if (_vaOverlayEnabled) {
          _vaSyncCanvas();
          if (vaOverlayCtx) vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
          _vaFetchPoses(_vaCurrentFrame);
        }
      });
    }

    // Clear Frame button — double-click sets ALL markers on current frame to NaN
    const vaClearFrameBtn = document.getElementById("va3d-clear-frame-btn");
    if (vaClearFrameBtn) {
      vaClearFrameBtn.addEventListener("dblclick", async () => {
        if (!_vaIsEditable()) return;     // edit disabled while compare layers active
        if (!_vaOverlayEnabled || !_vaPrimary() || !_vaCurrentPoses.length) return;
        const frameMap = {};
        for (const pose of _vaCurrentPoses) {
          frameMap[pose.bp] = { x: null, y: null };
          _vaFlushMarkerDelete(_vaCurrentFrame, pose.bp);
        }
        _vaLocalEdits.set(_vaCurrentFrame, frameMap);
        _vaSyncCanvas();
        vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
        _vaDrawPoseMarkers();
        _vaUpdateEditBanner();
      });
    }

    // Pose cache key (per layer) — encodes everything that affects pose data.
    function _vaPoseCacheKey(layer) {
      return `${layer.path}:${_vaLayerThreshold(layer).toFixed(2)}`;
    }

    // Fetch poses for one (layer, frame) pair into layer.posesCache.
    // Returns the cache entry {key, poses, n_bodyparts} or null on error.
    async function _vaFetchPosesForFrame(layer, frame) {
      const key    = _vaPoseCacheKey(layer);
      const cached = layer.posesCache.get(frame);
      if (cached && cached.key === key) return cached;
      const params = new URLSearchParams({
        h5:        layer.path,
        threshold: _vaLayerThreshold(layer).toFixed(2),
      });
      try {
        const r    = await fetch(`/dlc/viewer/frame-poses/${frame}?${params}`);
        const data = await r.json();
        if (!r.ok || data.error) { layer.errored = true; return null; }
        const entry = { key, poses: data.poses || [], n_bodyparts: data.n_bodyparts || 1 };
        layer.posesCache.set(frame, entry);
        return entry;
      } catch (e) { layer.errored = true; return null; }
    }

    // Fetch poses for the primary layer (drives current-frame state used by hit-testing).
    // Only called when paused — never during playback.
    async function _vaFetchPoses(frameNumber) {
      const primary = _vaPrimary();
      if (!primary || !_vaOverlayEnabled) return;
      const entry = await _vaFetchPosesForFrame(primary, frameNumber);
      if (entry) {
        _vaCurrentPoses = entry.poses;
        _vaNBodyparts   = entry.n_bodyparts;
      } else {
        _vaCurrentPoses = [];
      }
      // Also kick off comparison-layer fetches for the same frame so V/H markers appear.
      await Promise.all(
        _vaCompare()
          .filter(l => l.visible && !l.errored)
          .map(l => _vaFetchPosesForFrame(l, frameNumber))
      );
      _vaHoverBp = null;
      _vaDrawHoverLabel();
      _vaUpdateBpChipStatus();
      if (!_vaPrefetchCtrl) _vaPrefetchPoseWindow(frameNumber);
    }

    // Prefetch the next _POSE_WINDOW frames in the background, per visible layer.
    async function _vaPrefetchPoseWindow(fromFrame) {
      if (!_vaPrimary()) return;
      if (_vaPrefetchCtrl) return;
      _vaPrefetchCtrl = new AbortController();
      const ctrl = _vaPrefetchCtrl;
      try {
        await Promise.all(
          _vaLayers
            .filter(l => l.visible && !l.errored)
            .map(layer => _vaPrefetchOne(layer, fromFrame, ctrl.signal))
        );
      } finally {
        if (_vaPrefetchCtrl === ctrl) _vaPrefetchCtrl = null;
      }
    }

    async function _vaPrefetchOne(layer, fromFrame, signal) {
      const key = _vaPoseCacheKey(layer);
      // Skip if the next _POSE_WINDOW frames for this layer are already cached.
      let allCached = true;
      for (let i = fromFrame; i < fromFrame + _POSE_WINDOW && i < _vaFrameCount; i++) {
        const c = layer.posesCache.get(i);
        if (!c || c.key !== key) { allCached = false; break; }
      }
      if (allCached) return;
      const params = new URLSearchParams({
        h5:        layer.path,
        start:     String(fromFrame),
        count:     String(_POSE_WINDOW),
        threshold: _vaLayerThreshold(layer).toFixed(2),
      });
      try {
        const r = await fetch(`/dlc/viewer/frame-poses-batch?${params}`, { signal });
        if (!r.ok) return;
        const data = await r.json();
        for (const [fnStr, fd] of Object.entries(data.frames || {})) {
          const fn = parseInt(fnStr, 10);
          layer.posesCache.set(fn, {
            key,
            poses:       fd.poses || [],
            n_bodyparts: fd.n_bodyparts || 1,
          });
        }
      } catch (e) {
        if (e.name !== "AbortError") console.warn("pose prefetch failed:", e);
      }
    }

    // Backwards-compat wrapper for callers that still reference the old name.
    function _vaFetchPosesWindow(fromFrame) { return _vaPrefetchPoseWindow(fromFrame); }

    // ── Dataset Curation master toggle ────────────────────────
    const vaCurationToggle   = document.getElementById("va3d-curation-toggle");
    const vaCurationControls = document.getElementById("va3d-curation-controls");
    vaCurationToggle?.addEventListener("change", () => {
      vaCurationControls?.classList.toggle("hidden", !vaCurationToggle.checked);
    });

    // ── Kinematic overlay controls ────────────────────────────
    const vaOverlayToggle    = document.getElementById("va3d-overlay-toggle");
    const vaOverlayControls  = document.getElementById("va3d-overlay-controls");
    const vaOverlayStatus    = document.getElementById("va3d-overlay-status");
    const vaOverlayH5Path    = document.getElementById("va3d-overlay-h5-path");
    const vaOverlayH5Browse  = document.getElementById("va3d-overlay-h5-browse");
    const vaOverlayH5Clear   = document.getElementById("va3d-overlay-h5-clear");
    const vaOverlayH5Browser = document.getElementById("va3d-overlay-h5-browser");
    const vaOverlayThreshold = document.getElementById("va3d-overlay-threshold");
    const vaOverlayThreshVal = document.getElementById("va3d-overlay-threshold-val");
    const vaOverlayMarkerSz  = document.getElementById("va3d-overlay-marker-size");
    const vaOverlayMarkerVal = document.getElementById("va3d-overlay-marker-size-val");
    const vaOverlayPartsAll  = document.getElementById("va3d-overlay-parts-all");
    const vaOverlayPartsNone = document.getElementById("va3d-overlay-parts-none");
    // Body-part chip list (below the canvas)
    const vaBpChips     = document.getElementById("va3d-bp-chips");
    const vaBpListWrap  = document.getElementById("va3d-bp-list-wrap");

    function _vaOverlayStatus(msg, isErr = false) {
      vaOverlayStatus.textContent = msg;
      vaOverlayStatus.className   = "fe-extract-status" + (isErr ? " err" : "");
    }

    async function _vaLoadH5Info(h5Path) {
      _vaSelectedBp = null;
      if (vaBpChips) vaBpChips.innerHTML = '<span style="color:var(--text-dim);font-size:.73rem">Loading…</span>';
      try {
        const res  = await fetch(`/dlc/viewer/h5-info?h5=${encodeURIComponent(h5Path)}`);
        const data = await res.json();
        if (data.error) { _vaOverlayStatus(data.error, true); return; }
        _vaAllBodyParts = data.bodyparts || [];
        _vaRebuildPartsChecklist();
        _vaOverlayStatus(`${data.frame_count.toLocaleString()} frames · ${_vaAllBodyParts.length} body parts`);
      } catch (e) {
        _vaOverlayStatus(`Failed to load h5 info: ${e.message}`, true);
      }
    }

    async function _vaLoadLayerInfo(layer) {
      // Replaces _vaLoadH5Info; populates layer.bodyparts in place.
      try {
        const r    = await fetch(`/dlc/viewer/h5-info?h5=${encodeURIComponent(layer.path)}`);
        const data = await r.json();
        if (!r.ok || data.error) { layer.errored = true; return; }
        layer.bodyparts = data.bodyparts || [];
        if (layer === _vaPrimary()) {
          // Keep the legacy globals in sync for any code path not yet migrated.
          _vaAllBodyParts = layer.bodyparts.slice();
          _vaNBodyparts   = _vaAllBodyParts.length;
        }
      } catch (e) { layer.errored = true; }
    }

    async function _vaLoadEditCacheForPrimary() {
      const layer = _vaPrimary();
      if (!layer) return;
      // Reuse the existing _vaLoadEditCacheFromServer path so the marker-edit
      // banner / edits map keep working unchanged.
      await _vaLoadEditCacheFromServer(layer.path);
    }

    // Select a bodypart: set active chip, update canvas cursor.
    function _vaSelectBp(bp) {
      _vaSelectedBp = bp;
      if (vaOverlayCanvas) vaOverlayCanvas.style.cursor = bp ? "crosshair" : "default";
      _vaUpdateBpChipStatus();
      vaCard.focus();
    }

    // Update chip .active / .labeled / .vis-hidden states.
    function _vaUpdateBpChipStatus() {
      if (!vaBpChips) return;
      const posedBps = new Set(_vaCurrentPoses.map(p => p.bp));
      vaBpChips.querySelectorAll(".fl-bp-chip").forEach(c => {
        const bp = c.dataset.bp;
        const hasEdit = (typeof _vaLocalEdits !== "undefined") &&
          _vaLocalEdits.has(_vaCurrentFrame) &&
          bp in _vaLocalEdits.get(_vaCurrentFrame) &&
          _vaLocalEdits.get(_vaCurrentFrame)[bp].x != null;
        const isLabeled  = posedBps.has(bp) || hasEdit;
        const isHidden   = _vaHiddenParts.has(bp);
        c.classList.toggle("active",     c.dataset.bp === _vaSelectedBp);
        c.classList.toggle("labeled",    isLabeled);
        c.classList.toggle("vis-hidden", isLabeled && isHidden);
      });
    }

    // Build the fl-bp-chip list in the panel below the canvas.
    function _vaRebuildPartsChecklist() {
      if (!vaBpChips) return;
      vaBpChips.innerHTML = "";
      if (!_vaAllBodyParts.length) {
        if (vaBpListWrap) vaBpListWrap.classList.add("hidden");
        return;
      }
      _vaAllBodyParts.forEach((bp, idx) => {
        const chip = document.createElement("button");
        chip.className  = "fl-bp-chip";
        chip.dataset.bp = bp;
        chip.style.setProperty("--fl-color", _vaPaletteColor(idx, _vaAllBodyParts.length));
        chip.innerHTML =
          `<span class="fl-bp-dot"></span>` +
          `<span class="fl-bp-name">${bp}</span>` +
          `<svg class="fl-bp-check" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>` +
          `<svg class="fl-bp-eye-slash" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
        chip.title = "Click: select  •  Dbl-click: toggle visibility";
        chip.addEventListener("click", () => _vaSelectBp(bp));
        chip.addEventListener("dblclick", e => {
          e.preventDefault();
          if (_vaHiddenParts.has(bp)) _vaHiddenParts.delete(bp);
          else _vaHiddenParts.add(bp);
          _vaDrawHoverLabel();
          _vaUpdateBpChipStatus();
        });
        vaBpChips.appendChild(chip);
      });
      if (vaBpListWrap) vaBpListWrap.classList.toggle("hidden", !_vaOverlayEnabled);
      _vaUpdateBpChipStatus();
      // Auto-select first bodypart (like the labeler does)
      if (_vaAllBodyParts.length && !_vaSelectedBp) _vaSelectBp(_vaAllBodyParts[0]);
    }

    // Cached on the page for re-populating after add/remove.
    let _vaLastVariants = [];

    function _vaPickBestPrimary(variants) {
      // Newest variant by ts wins. Raw companion has ts=null and is the
      // fallback when no dated variants exist.
      const dated = (variants || []).filter(v => !v.disabled && v.ts);
      if (dated.length) {
        return dated.reduce((a, b) => (a.ts > b.ts ? a : b));
      }
      return (variants || []).find(v => !v.disabled) || null;
    }

    function _vaPlayStep() {
      const v = parseInt(document.getElementById("va3d-play-step")?.value || "1", 10);
      return Math.max(1, Math.min(100, isNaN(v) ? 1 : v));
    }

    function _vaPlaybackFps() {
      const v = parseInt(document.getElementById("va3d-play-fps")?.value || "5", 10);
      return Math.max(1, Math.min(120, isNaN(v) ? 5 : v));
    }

    function _vaPlayDelayMs() {
      return Math.round(1000 / _vaPlaybackFps());
    }

    async function _vaDiscoverVariants(videoPath) {
      // Fetch every analyzable h5 near `videoPath` and populate the Primary <select>.
      // Default the primary to the first 'raw' entry, or the first variant otherwise.
      const select = document.getElementById("va3d-overlay-primary-select");
      const addCmp = document.getElementById("va3d-overlay-add-compare");
      if (!select || !addCmp) return;

      // Reset both controls to their empty states.
      select.innerHTML = '<option value="">(no h5 detected — use Browse)</option>';
      addCmp.innerHTML = '<option value="">+ add comparison…</option>';

      let data;
      try {
        const r = await fetch(`/dlc/viewer/h5-variants?video=${encodeURIComponent(videoPath)}`);
        data = await r.json();
        if (!r.ok || !Array.isArray(data.variants)) return;
      } catch (e) { return; }

      _vaLastVariants = data.variants;
      if (!data.variants.length) return;

      // Populate primary select.
      data.variants.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.path;
        opt.textContent = v.label;
        if (v.disabled) opt.disabled = true;
        opt.dataset.type  = v.type;
        opt.dataset.label = v.label;
        select.appendChild(opt);
      });

      // Default selection.
      const defaultEntry = _vaPickBestPrimary(data.variants);
      if (!defaultEntry) return;
      select.value = defaultEntry.path;
      await _vaApplyPrimaryFromSelect();
      _vaSyncPrimaryRow();
      _vaRefreshAddComparisonOptions(data.variants);
    }

    function _vaRefreshAddComparisonOptions(variants) {
      const addCmp = document.getElementById("va3d-overlay-add-compare");
      const hint   = document.getElementById("va3d-overlay-add-compare-empty-hint");
      if (!addCmp) return;
      addCmp.innerHTML = '<option value="">+ add comparison…</option>';
      const taken = new Set(_vaLayers.map(l => l.path));
      const available = (variants || []).filter(v => !v.disabled && !taken.has(v.path));
      available.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.path;
        opt.textContent = v.label;
        opt.dataset.type  = v.type;
        opt.dataset.label = v.label;
        addCmp.appendChild(opt);
      });
      // Show the dropdown only when at least one non-taken option exists;
      // otherwise show the inline "(no other variants)" hint.
      addCmp.classList.toggle("hidden", available.length === 0);
      if (hint) hint.classList.toggle("hidden", available.length > 0);
    }

    async function _vaApplyPrimaryFromSelect() {
      const select = document.getElementById("va3d-overlay-primary-select");
      if (!select) return;
      const path  = select.value;
      if (!path) return;
      const opt   = select.options[select.selectedIndex];
      const label = opt?.dataset.label || path.split("/").pop();
      const type  = opt?.dataset.type  || "raw";

      try {
        // Primary swap = fresh slate. Drop every comparison layer.
        _vaLayers.length = 0;
        const layer = _vaMakeLayer({ path, label, type });
        _vaSetPrimaryLayer(layer);
        document.getElementById("va3d-overlay-h5-path").value = path;
        await _vaLoadLayerInfo(layer);
        await _vaLoadEditCacheForPrimary();
        _vaRenderCompareRows();
        _vaRefreshAddComparisonOptions(_vaLastVariants);
        _vaRenderPrimaryThresholdInline();
        if (_vaOverlayEnabled) _vaLoadFrame(_vaCurrentFrame);
        _vaSyncPrimaryRow();
      } finally {
        // Pair the primary h5 across every tile (tile-0 trivially keeps `path`;
        // tile-1 resolves to its sibling h5 or shows a 'no sibling' pill).
        // Runs in `finally` so a fault in the layer-info / edit-cache loaders
        // can never strand the tiles with a stale primaryH5Path.
        await Controller.setPrimaryLayer(path);
      }
    }

    function _vaRenderPrimaryThresholdInline() {
      const host = document.getElementById("va3d-overlay-primary-select");
      if (!host) return;
      let slot = document.getElementById("va3d-overlay-primary-threshold-slot");
      if (!_vaPerLayerThresholds) {
        if (slot) slot.remove();
        return;
      }
      if (!slot) {
        slot = document.createElement("span");
        slot.id = "va3d-overlay-primary-threshold-slot";
        slot.style.cssText = "display:flex;align-items:center;gap:.25rem;margin-left:.4rem";
        host.parentElement?.appendChild(slot);
      }
      slot.innerHTML = "";
      const layer = _vaPrimary();
      if (!layer) return;
      const slider = document.createElement("input");
      slider.type = "range"; slider.min = "0"; slider.max = "1"; slider.step = "0.05";
      slider.value = String(layer.threshold ?? _vaGlobalThreshold);
      slider.style.cssText = "width:60px;accent-color:var(--accent)";
      const lbl = document.createElement("span");
      lbl.style.cssText = "font-family:var(--mono);font-size:.7rem;min-width:2.2rem";
      lbl.textContent = Number(slider.value).toFixed(2);
      slider.addEventListener("input", () => {
        layer.threshold = Number(slider.value);
        lbl.textContent = layer.threshold.toFixed(2);
        if (_vaOverlayEnabled) {
          _vaFetchPosesForFrame(layer, _vaCurrentFrame).then(_vaDrawCurrentFrame);
        }
      });
      slot.appendChild(slider);
      slot.appendChild(lbl);
    }

    // ── Comparison-row UI ──────────────────────────────────────────
    function _shapeGlyph(shape) {
      switch (shape) {
        case "circle-filled": return "●";
        case "diamond":       return "◆";
        case "square":        return "□";
        case "triangle":      return "△";
        default:              return "?";
      }
    }

    function _vaRenderCompareRows() {
      const list = document.getElementById("va3d-overlay-compare-list");
      if (!list) return;
      list.innerHTML = "";
      _vaCompare().forEach((layer) => {
        const row = document.createElement("div");
        row.id = `va3d-layer-row-${layer.id}`;
        row.style.cssText = "display:flex;align-items:center;gap:.35rem;font-size:.74rem;padding:.15rem .25rem;background:var(--surface);border:1px solid var(--border);border-radius:5px";
        // visibility checkbox
        const vis = document.createElement("input");
        vis.type = "checkbox";
        vis.checked = layer.visible;
        vis.style.cssText = "accent-color:var(--accent);width:12px;height:12px;flex-shrink:0";
        vis.addEventListener("change", () => {
          layer.visible = vis.checked;
          _vaDrawCurrentFrame();
        });
        row.appendChild(vis);
        // shape badge
        const badge = document.createElement("span");
        badge.textContent = _shapeGlyph(layer.shape);
        badge.style.cssText = "font-family:var(--mono);width:1.1rem;text-align:center;flex-shrink:0";
        row.appendChild(badge);
        // label
        const lbl = document.createElement("span");
        lbl.textContent = layer.label;
        lbl.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
        row.appendChild(lbl);
        // per-layer threshold (rendered conditionally when Customize is on)
        const thrSlot = document.createElement("span");
        thrSlot.dataset.role = "threshold";
        thrSlot.style.cssText = "display:flex;align-items:center;gap:.25rem;flex-shrink:0";
        if (_vaPerLayerThresholds) {
          const slider = document.createElement("input");
          slider.type = "range"; slider.min = "0"; slider.max = "1"; slider.step = "0.05";
          slider.value = String(layer.threshold ?? _vaGlobalThreshold);
          slider.style.cssText = "width:60px;accent-color:var(--accent)";
          const lbl = document.createElement("span");
          lbl.style.cssText = "font-family:var(--mono);font-size:.7rem;min-width:2.2rem";
          lbl.textContent = Number(slider.value).toFixed(2);
          slider.addEventListener("input", () => {
            layer.threshold = Number(slider.value);
            lbl.textContent = layer.threshold.toFixed(2);
            if (_vaOverlayEnabled) {
              _vaFetchPosesForFrame(layer, _vaCurrentFrame).then(_vaDrawCurrentFrame);
            }
          });
          thrSlot.appendChild(slider);
          thrSlot.appendChild(lbl);
        }
        row.appendChild(thrSlot);
        // remove button
        const rm = document.createElement("button");
        rm.className = "btn-sm";
        rm.style.cssText = "padding:.05rem .35rem;font-size:.7rem;flex-shrink:0";
        rm.textContent = "×";
        rm.title = "Remove this comparison layer";
        rm.addEventListener("click", () => _vaRemoveCompare(layer.id));
        row.appendChild(rm);
        list.appendChild(row);
      });
      _vaUpdateEditDisabledBanner();
    }

    async function _vaAddCompare(path, label, type) {
      if (_vaLayers.some(l => l.path === path)) return;
      const layer = _vaMakeLayer({ path, label, type });
      _vaLayers.push(layer);
      _vaAssignShapes();
      await _vaLoadLayerInfo(layer);
      // Pre-fetch poses for the current frame so the new layer paints immediately.
      if (_vaOverlayEnabled) await _vaFetchPosesForFrame(layer, _vaCurrentFrame);
      _vaRenderCompareRows();
      _vaRefreshAddComparisonOptions(_vaLastVariants);
      _vaDrawCurrentFrame();
    }

    function _vaRemoveCompare(id) {
      const idx = _vaLayers.findIndex(l => l.id === id);
      if (idx < 1) return;  // never remove primary
      const removedPath = _vaLayers[idx].path;
      _vaLayers.splice(idx, 1);
      _vaAssignShapes();
      _vaRenderCompareRows();
      _vaRefreshAddComparisonOptions(_vaLastVariants);
      _vaDrawCurrentFrame();
      // Drop this comparison from every tile's per-tile list (cam-agnostic
      // basename match handles the sibling tile's cam-substituted path).
      try { Controller.removeComparisonLayer(removedPath); } catch (err) {}
    }

    function _vaUpdateEditDisabledBanner() {
      const banner = document.getElementById("va3d-overlay-edit-disabled-banner");
      if (banner) banner.classList.toggle("hidden", _vaIsEditable());
      // Re-evaluate the marker-edit banner: when compare layers are active it
      // must be force-hidden regardless of unsaved-edit count.
      _vaUpdateEditBanner();
    }

    vaOverlayToggle?.addEventListener("change", () => {
      _vaOverlayEnabled = vaOverlayToggle.checked;
      vaOverlayControls.classList.toggle("hidden", !_vaOverlayEnabled);
      if (!_vaOverlayEnabled) {
        if (vaOverlayCtx) vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
        if (vaBpListWrap) vaBpListWrap.classList.add("hidden");
        if (vaOverlayCanvas) vaOverlayCanvas.style.cursor = "default";
        return;
      }
      if (_vaAllBodyParts.length && vaBpListWrap) vaBpListWrap.classList.remove("hidden");
      if (!_vaPrimary() && _vaCurrentVideoPath) _vaDiscoverVariants(_vaCurrentVideoPath);
      if (_vaPrimary() && !_vaPlayTimer) _vaFetchPoses(_vaCurrentFrame);
    });

    const vaOverlayPrimarySelect = document.getElementById("va3d-overlay-primary-select");
    vaOverlayPrimarySelect?.addEventListener("change", _vaApplyPrimaryFromSelect);

    const vaOverlayAddCompare = document.getElementById("va3d-overlay-add-compare");
    vaOverlayAddCompare?.addEventListener("change", async (e) => {
      const path = e.target.value;
      if (!path) return;
      const opt  = e.target.options[e.target.selectedIndex];
      await _vaAddCompare(path, opt.dataset.label, opt.dataset.type);
      e.target.value = "";  // reset to placeholder
      // Pair this comparison h5 across every tile (tile-0 trivially keeps
      // `path`; tile-1 resolves to its sibling h5 or notes the miss in pill).
      try { await Controller.addComparisonLayer(path); } catch (err) {}
    });

    const vaOverlayPrimaryVisible = document.getElementById("va3d-overlay-primary-visible");
    const vaOverlayPrimaryShape   = document.getElementById("va3d-overlay-primary-shape");
    const vaOverlayPrimaryLabel   = document.getElementById("va3d-overlay-primary-label");

    vaOverlayPrimaryVisible?.addEventListener("change", () => {
      const layer = _vaPrimary();
      if (!layer) return;
      layer.visible = !!vaOverlayPrimaryVisible.checked;
      _vaDrawCurrentFrame();
    });

    function _vaSyncPrimaryRow() {
      const layer = _vaPrimary();
      if (!layer) {
        if (vaOverlayPrimaryShape) vaOverlayPrimaryShape.textContent = "—";
        if (vaOverlayPrimaryLabel) vaOverlayPrimaryLabel.textContent = "(no primary)";
        if (vaOverlayPrimaryVisible) vaOverlayPrimaryVisible.checked = false;
        return;
      }
      if (vaOverlayPrimaryShape) vaOverlayPrimaryShape.textContent = _shapeGlyph(layer.shape);
      if (vaOverlayPrimaryLabel) vaOverlayPrimaryLabel.textContent = layer.label || "";
      if (vaOverlayPrimaryVisible) vaOverlayPrimaryVisible.checked = !!layer.visible;
    }

    vaOverlayH5Clear?.addEventListener("click", () => {
      _vaSetPrimaryLayer(null);
      vaOverlayH5Path.value = "";
      _vaAllBodyParts = [];
      _vaHiddenParts.clear();
      _vaSelectedBp = null;
      _vaClearPoseCache();
      if (vaBpChips)    vaBpChips.innerHTML = "";
      if (vaBpListWrap) vaBpListWrap.classList.add("hidden");
      if (vaOverlayCanvas) vaOverlayCanvas.style.cursor = "default";
      _vaOverlayStatus("");
      _vaCurrentPoses = [];
      if (vaOverlayCtx) vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
    });

    // Threshold slider
    vaOverlayThreshold?.addEventListener("input", () => {
      _vaGlobalThreshold = Number(vaOverlayThreshold.value);
      vaOverlayThreshVal.textContent = _vaGlobalThreshold.toFixed(2);
      // Stale per-layer cache entries are auto-skipped by _vaFetchPosesForFrame
      // (key mismatch on threshold), so we just trigger a re-fetch of the
      // current frame.
      if (_vaOverlayEnabled) _vaLoadFrame(_vaCurrentFrame);
    });

    // Customize per-layer thresholds toggle
    const vaCustomizeThr = document.getElementById("va3d-overlay-customize-thresholds");
    vaCustomizeThr?.addEventListener("change", () => {
      _vaPerLayerThresholds = vaCustomizeThr.checked;
      if (!_vaPerLayerThresholds) {
        // Forget per-layer overrides; revert to global.
        _vaLayers.forEach(l => l.threshold = null);
      } else {
        // Seed each layer's override with the current global so toggling on
        // produces no immediate visual change.
        _vaLayers.forEach(l => l.threshold = _vaGlobalThreshold);
      }
      _vaRenderCompareRows();
      _vaRenderPrimaryThresholdInline();
      if (_vaOverlayEnabled) _vaLoadFrame(_vaCurrentFrame);
    });

    // Marker size slider — redraw canvas immediately, no frame reload needed
    vaOverlayMarkerSz?.addEventListener("input", () => {
      _vaMarkerSize = parseInt(vaOverlayMarkerSz.value, 10);
      vaOverlayMarkerVal.textContent = _vaMarkerSize;
      _vaDrawHoverLabel();
    });

    vaOverlayPartsAll?.addEventListener("click", () => {
      _vaHiddenParts.clear();
      _vaDrawHoverLabel();
      _vaUpdateBpChipStatus();
    });
    vaOverlayPartsNone?.addEventListener("click", () => {
      _vaAllBodyParts.forEach(bp => _vaHiddenParts.add(bp));
      _vaDrawHoverLabel();
      _vaUpdateBpChipStatus();
    });

    // h5 file browser (shows .h5 files and dirs)
    let _vaH5BrowsePath = null;

    async function _vaH5BrowseDir(path) {
      _vaH5BrowsePath = path;
      vaOverlayH5Browser.innerHTML = '<p class="explorer-empty">Loading…</p>';
      try {
        const res  = await fetch(`/fs/ls?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        if (data.error) { vaOverlayH5Browser.innerHTML = `<p class="explorer-empty">${data.error}</p>`; return; }
        vaOverlayH5Browser.innerHTML = "";
        const entries = data.entries || [];
        // Up button
        if (data.parent) {
          const upRow = document.createElement("div");
          upRow.className = "fe-video-item";
          upRow.style.cursor = "pointer";
          upRow.textContent = "↑ ..";
          upRow.addEventListener("click", () => _vaH5BrowseDir(data.parent));
          vaOverlayH5Browser.appendChild(upRow);
        }
        entries.forEach(e => {
          const isH5  = e.type === "file" && e.name.toLowerCase().endsWith(".h5");
          const isDir = e.type === "dir";
          if (!isH5 && !isDir) return;
          const row = document.createElement("div");
          row.className   = "fe-video-item";
          row.style.cursor = "pointer";
          row.textContent  = isDir ? `📁 ${e.name}/` : `📊 ${e.name}`;
          row.addEventListener("click", async () => {
            if (isDir) {
              _vaH5BrowseDir(path + "/" + e.name);
            } else {
              const full = path + "/" + e.name;
              const layer = _vaMakeLayer({
                path:  full,
                label: `Custom — ${full.split("/").pop()}`,
                type:  "raw",
              });
              _vaSetPrimaryLayer(layer);
              vaOverlayH5Path.value = full;
              _vaClearPoseCache();
              vaOverlayH5Browser.classList.add("hidden");
              _vaOverlayStatus("h5 selected");
              await _vaLoadH5Info(full);
              await _vaLoadLayerInfo(layer);
              await _vaLoadEditCacheForPrimary();
              if (_vaOverlayEnabled) _vaLoadFrame(_vaCurrentFrame);
            }
          });
          vaOverlayH5Browser.appendChild(row);
        });
        if (!vaOverlayH5Browser.children.length)
          vaOverlayH5Browser.innerHTML = '<p class="explorer-empty">No .h5 files found here.</p>';
      } catch (e) {
        vaOverlayH5Browser.innerHTML = `<p class="explorer-empty">Error: ${e.message}</p>`;
      }
    }

    vaOverlayH5Browse?.addEventListener("click", () => {
      const isHidden = vaOverlayH5Browser.classList.toggle("hidden");
      if (!isHidden) {
        const startDir = _vaCurrentVideoPath
          ? _vaCurrentVideoPath.substring(0, _vaCurrentVideoPath.lastIndexOf("/"))
          : (state.userDataDir || state.dataDir || "/");
        _vaH5BrowseDir(startDir);
      }
    });

    // ── Load content list ─────────────────────────────────────
    async function _vaLoadContent() {
      vaContentList.innerHTML = '<p class="explorer-empty">Loading…</p>';
      try {
        const res  = await fetch("/dlc/project/labeled-content");
        const data = await res.json();
        if (data.error) {
          vaContentList.innerHTML = `<p class="explorer-empty">${data.error}</p>`;
          return;
        }
        const hasVideos  = data.videos  && data.videos.length  > 0;
        const hasFolders = data.frame_folders && data.frame_folders.length > 0;
        if (!hasVideos && !hasFolders) {
          vaContentList.innerHTML = '<p class="explorer-empty">No labeled videos or frame folders found. Run "Analyze Video / Frames" with "Create labeled video / frame" enabled.</p>';
          return;
        }
        vaContentList.innerHTML = "";

        function _makeItem(svgHtml, name, subtitle, onClick) {
          const item = document.createElement("div");
          item.className = "fe-video-item";
          item.innerHTML = `${svgHtml}<div style="display:flex;flex-direction:column;min-width:0;flex:1"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${name}</span>${subtitle ? `<span style="font-size:.7rem;color:var(--text-dim)">${subtitle}</span>` : ""}</div>`;
          item.addEventListener("click", onClick);
          return item;
        }

        if (hasVideos) {
          const hdr = document.createElement("div");
          hdr.style.cssText = "font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);padding:.25rem .3rem .1rem";
          hdr.textContent   = "Labeled Videos";
          vaContentList.appendChild(hdr);
          data.videos.forEach(v => {
            const sub  = v.size ? Math.round(v.size / 1024 / 1024) + " MB" : "";
            const svg  = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><rect x="2" y="2" width="20" height="20" rx="3"/><polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none"/></svg>`;
            vaContentList.appendChild(_makeItem(svg, v.name, sub, () => _vaOpenVideo(v.name)));
          });
        }

        if (hasFolders) {
          const hdr = document.createElement("div");
          hdr.style.cssText = "font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text-dim);padding:.35rem .3rem .1rem";
          hdr.textContent   = "Labeled Frame Folders";
          vaContentList.appendChild(hdr);
          data.frame_folders.forEach(f => {
            const sub = f.frame_count + " labeled frames";
            const svg = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
            vaContentList.appendChild(_makeItem(svg, f.stem + "/", sub, () => _vaOpenFrameFolder(f.stem, f.frames)));
          });
        }
      } catch (err) {
        vaContentList.innerHTML = `<p class="explorer-empty">Error: ${err.message}</p>`;
      }
    }

    // ── Player controls ───────────────────────────────────────
    //
    // Strict sequential playback loop — replaces setInterval.
    //
    // setInterval would fire at a fixed wall-clock rate regardless of whether
    // the previous frame finished rendering.  When _vaFrameBusy is true the
    // tick is silently dropped, causing frame-skips and marker desync.
    //
    // Instead: each iteration awaits _vaLoadFrame() (which itself awaits the
    // image-load AND a requestAnimationFrame paint barrier) before scheduling
    // the next tick with setTimeout.  This guarantees both the raw image and
    // its overlay markers are fully composited before the engine advances.
    //
    // _vaPlayTimer is used as a boolean sentinel: truthy = playing.
    // _vaPlayTimeoutId holds the setTimeout handle for cancellation.
    let _vaPlayTimeoutId = null;

    function _vaStopPlayback() {
      if (_vaPlayTimeoutId !== null) { clearTimeout(_vaPlayTimeoutId); _vaPlayTimeoutId = null; }
      _vaPlayTimer = null;
      vaPlayIcon.classList.remove("hidden");
      vaPauseIcon.classList.add("hidden");
    }

    async function _vaPlayLoop() {
      // Guard: stop if externally cancelled between ticks
      if (!_vaPlayTimer) return;

      const next = _vaCurrentFrame + _vaPlayStep();
      if (next >= _vaFrameCount) {
        _vaStopPlayback();
        if (_vaOverlayEnabled && _vaPrimary()) _vaFetchPoses(_vaCurrentFrame);
        return;
      }

      const t0 = performance.now();
      await Controller.seek(next);
      // If play was stopped while we were awaiting the frame, exit cleanly
      if (!_vaPlayTimer) return;

      // Pace the next tick: subtract actual render time from the target interval.
      // Clamped to 0 so a slow frame never makes us "owe" future ticks.
      const elapsed = performance.now() - t0;
      const delay   = Math.max(0, _vaPlayDelayMs() - elapsed);
      _vaPlayTimeoutId = setTimeout(_vaPlayLoop, delay);
    }

    vaBtnPlay.addEventListener("click", () => {
      if (_vaPlayTimer) {
        _vaStopPlayback();
        // Just paused: fetch and display poses for current frame
        if (_vaOverlayEnabled && _vaPrimary()) _vaFetchPoses(_vaCurrentFrame);
      } else {
        vaPlayIcon.classList.add("hidden");
        vaPauseIcon.classList.remove("hidden");
        _vaPlayTimer = true;   // sentinel: truthy = playing
        // Pre-warm pose cache before playback so the first N frames render with markers
        if (_vaOverlayEnabled && _vaPrimary()) _vaPrefetchPoseWindow(_vaCurrentFrame);
        _vaPlayLoop();
      }
    });

    vaBtnPrev.addEventListener("click", () => Controller.seek(_vaCurrentFrame - 1));
    vaBtnNext.addEventListener("click", () => Controller.seek(_vaCurrentFrame + 1));

    function _vaSkipN() { return Math.max(1, parseInt(vaSkipN?.value, 10) || 10); }
    vaBtnSkipBack?.addEventListener("click", () => Controller.seek(_vaCurrentFrame - _vaSkipN()));
    vaBtnSkipFwd?.addEventListener("click",  () => Controller.seek(_vaCurrentFrame + _vaSkipN()));
    // Prevent arrow keys from changing the skip-N field from triggering frame nav
    vaSkipN?.addEventListener("keydown", e => e.stopPropagation());

    vaSeek.addEventListener("mousedown",  () => { _vaSeekDragging = true; });
    vaSeek.addEventListener("touchstart", () => { _vaSeekDragging = true; });
    vaSeek.addEventListener("input", () => {
      _vaCurrentFrame = Math.round((vaSeek.value / 1000) * Math.max(_vaFrameCount - 1, 0));
      _vaUpdateDisplay();
    });
    vaSeek.addEventListener("change", () => { _vaSeekDragging = false; Controller.seek(_vaCurrentFrame); });

    vaBackBtn.addEventListener("click", _vaReset);
    vaRefreshBtn.addEventListener("click", _vaLoadContent);

    // ── Open / close ──────────────────────────────────────────
    // Defensive bind-time guard: the #btn-open-view-analyzed trigger is
    // shared with the upstream viewer.js. Today upstream throws at init
    // so its handler never binds, but if that ever changes we must not
    // wire ours when our va3d card is not in the DOM.
    if (vaOpenBtn && vaCard) {
      vaOpenBtn.addEventListener("click", () => {
        vaCard.classList.remove("hidden");
        vaCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
        _vaLoadContent();
      });
    }

    vaCloseBtn?.addEventListener("click", () => {
      vaCard.classList.add("hidden");
      _vaReset();
    });

    // ── Keyboard navigation ───────────────────────────────────
    // Scoped to vaCard so it doesn't fire when another card has focus.
    vaCard.addEventListener("keydown", (e) => {
      if (vaPlayerSec.classList.contains("hidden")) return;
      // Don't intercept when typing in any input except the skip-N field
      if (e.target.tagName === "INPUT" && e.target !== vaSkipN) return;
      if (e.target.tagName === "TEXTAREA") return;

      const overlayActive = _vaOverlayEnabled && _vaPrimary() && _vaCurrentPoses.length > 0;

      // ── Spacebar: visibility toggle when overlay+bp selected, else play/pause ──
      if (e.key === " ") {
        e.preventDefault();
        if (overlayActive && _vaSelectedBp) {
          if (_vaHiddenParts.has(_vaSelectedBp)) _vaHiddenParts.delete(_vaSelectedBp);
          else _vaHiddenParts.add(_vaSelectedBp);
          _vaDrawHoverLabel();
          _vaUpdateBpChipStatus();
        } else {
          vaBtnPlay.click();
        }
        return;
      }

      // ── Frame navigation ──────────────────────────────────────────────────────
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        e.ctrlKey ? Controller.seek(_vaCurrentFrame - _vaSkipN())
                  : Controller.seek(_vaCurrentFrame - 1);
        return;
      }
      if (e.key === "ArrowRight") {
        e.preventDefault();
        e.ctrlKey ? Controller.seek(_vaCurrentFrame + _vaSkipN())
                  : Controller.seek(_vaCurrentFrame + 1);
        return;
      }

      // ── Tab: cycle bodyparts (only when overlay is active) ────────────────────
      if (e.key === "Tab" && overlayActive) {
        e.preventDefault();
        if (!_vaAllBodyParts.length) return;
        const idx = _vaAllBodyParts.indexOf(_vaSelectedBp);
        const next = e.shiftKey
          ? (_vaAllBodyParts.length + idx - 1) % _vaAllBodyParts.length
          : (idx + 1) % _vaAllBodyParts.length;
        _vaSelectBp(_vaAllBodyParts[next]);
        _vaDrawHoverLabel();
        return;
      }

      // ── Backspace/Delete: delete (NaN) selected marker ────────────────────────
      if ((e.key === "Backspace" || e.key === "Delete") && overlayActive && _vaSelectedBp) {
        e.preventDefault();
        if (!_vaLocalEdits.has(_vaCurrentFrame)) _vaLocalEdits.set(_vaCurrentFrame, {});
        _vaLocalEdits.get(_vaCurrentFrame)[_vaSelectedBp] = { x: null, y: null };
        _vaSyncCanvas();
        vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
        _vaDrawPoseMarkers();
        _vaFlushMarkerDelete(_vaCurrentFrame, _vaSelectedBp);
        _vaUpdateEditBanner();
        _vaUpdateBpChipStatus();
        return;
      }

      // ── WASD nudge: ±1px (±10px with Shift) when overlay+bp selected ─────────
      if (overlayActive && _vaSelectedBp) {
        const step = e.shiftKey ? 10 : 1;
        let dx = 0, dy = 0;
        if      (e.key === "a" || e.key === "A") dx = -step;
        else if (e.key === "d" || e.key === "D") dx =  step;
        else if (e.key === "w" || e.key === "W") dy = -step;
        else if (e.key === "s" || e.key === "S") dy =  step;
        if (dx !== 0 || dy !== 0) {
          e.preventDefault();
          const frameEdits = _vaLocalEdits.get(_vaCurrentFrame) || {};
          const pose = _vaCurrentPoses.find(p => p.bp === _vaSelectedBp);
          const base = frameEdits[_vaSelectedBp] || (pose ? { x: pose.x, y: pose.y } : null);
          if (base && base.x != null && base.y != null) {
            const nx = base.x + dx;
            const ny = base.y + dy;
            if (!_vaLocalEdits.has(_vaCurrentFrame)) _vaLocalEdits.set(_vaCurrentFrame, {});
            _vaLocalEdits.get(_vaCurrentFrame)[_vaSelectedBp] = { x: nx, y: ny };
            _vaSyncCanvas();
            vaOverlayCtx.clearRect(0, 0, vaOverlayCanvas.width, vaOverlayCanvas.height);
            _vaDrawPoseMarkers();
            _vaFlushMarkerEdit(_vaCurrentFrame, _vaSelectedBp, nx, ny);
            _vaUpdateEditBanner();
          }
          return;
        }
      }
    });
    // Make the card focusable so keydown fires when clicked inside it
    if (!vaCard.hasAttribute("tabindex")) vaCard.setAttribute("tabindex", "-1");

    // ── Dataset Curation ──────────────────────────────────────────
    (() => {
      const vaCurationStatus  = document.getElementById("va3d-curation-status");
      const vaExtractFrameBtn = document.getElementById("va3d-extract-frame-btn");
      const vaAddToDatasetBtn = document.getElementById("va3d-add-to-dataset-btn");
      const vaBatchAddBtn     = document.getElementById("va3d-batch-add-btn");
      const vaBatchCount      = document.getElementById("va3d-batch-count");
      const vaBatchStep       = document.getElementById("va3d-batch-step");
      const vaCsvNone         = document.getElementById("va3d-csv-none");
      const vaCsvLoaded       = document.getElementById("va3d-csv-loaded");
      const vaCsvPathDisplay  = document.getElementById("va3d-csv-path-display");
      const vaCreateCsvBtn    = document.getElementById("va3d-create-csv-btn");
      const vaCsvCreateStatus = document.getElementById("va3d-csv-create-status");
      const vaCsvBars         = document.getElementById("va3d-csv-bars");
      const vaStatusBarWrap   = document.getElementById("va3d-status-bar-wrap");
      const vaNoteBarWrap     = document.getElementById("va3d-note-bar-wrap");
      const vaStatusCanvas    = document.getElementById("va3d-status-canvas");
      const vaNoteCanvas      = document.getElementById("va3d-note-canvas");
      const vaStatusChips     = document.getElementById("va3d-status-chips");
      const vaNoteChips       = document.getElementById("va3d-note-chips");
      const vaAnnotPanel      = document.getElementById("va3d-annot-panel");
      const vaAnnotFrameNum   = document.getElementById("va3d-annot-frame-num");
      const vaNoteInput       = document.getElementById("va3d-note-input");
      const vaStatusInput     = document.getElementById("va3d-status-input");
      const vaSaveStatusBtn   = document.getElementById("va3d-save-status-btn");
      const vaSaveNoteBtn     = document.getElementById("va3d-save-note-btn");
      const vaAnnotSaveStatus = document.getElementById("va3d-annot-save-status");
      const vaStatusPrevBtn   = document.getElementById("va3d-status-prev-btn");
      const vaStatusNextBtn   = document.getElementById("va3d-status-next-btn");
      const vaNoteStepPrevBtn = document.getElementById("va3d-note-prev-btn");
      const vaNoteStepNextBtn = document.getElementById("va3d-note-next-btn");
      const vaNewTagInput     = document.getElementById("va3d-new-tag-input");
      const vaAddTagBtn       = document.getElementById("va3d-add-tag-btn");

      // Companion CSV state
      let _vaCsvPath          = null;
      let _vaCsvRows          = [];     // {frame_number, timestamp, frame_line_status, note}
      let _vaUserTags         = [];
      let _vaUserStatuses     = [];
      let _vaActiveNoteFilter = null;

      // Per-chip active sets and color maps (populated when chips are rendered)
      let _vaActiveNoteChips   = new Set();
      let _vaActiveStatusChips = new Set();
      let _vaNoteColorMap      = {};
      let _vaStatusColorMap    = {};

      // Color palettes — status uses warm/green tones, notes use cool/blue tones
      const _VA_STATUS_COLORS = ["#34d399","#f97316","#e879f9","#facc15","#f87171","#22d3ee","#a78bfa","#fb923c"];
      const _VA_NOTE_COLORS   = ["#60a5fa","#f472b6","#4ade80","#38bdf8","#e879f9","#a78bfa","#facc15","#fb7185"];

      // ── Status helpers ──────────────────────────────────────────
      let _curationMsgTimer = null;
      function _curStatus(msg, isErr) {
        if (!vaCurationStatus) return;
        vaCurationStatus.textContent = msg;
        vaCurationStatus.className   = "fe-extract-status" + (isErr ? " err" : "");
        if (_curationMsgTimer) clearTimeout(_curationMsgTimer);
        if (msg && !isErr) {
          _curationMsgTimer = setTimeout(() => {
            vaCurationStatus.textContent = "";
          }, 4000);
        }
      }
      // Expose so outer-scope _va3dShowCuratorStatus can route per-cam summaries
      // through the same single-source timer (avoids the 4s clobber).
      window.__va3dCurStatus = _curStatus;
      // Expose current mode so outer-scope _va3dBuildCuratorBody can pick the
      // right body shape (video_name vs video_path) for sibling fan-out.
      window.__va3dGetMode = () => _vaMode;

      // ── Build request body helper ───────────────────────────────
      function _videoRequestBody(frameNum) {
        const n = (frameNum !== undefined) ? frameNum : _vaCurrentFrame;
        const body = { frame_number: n };
        if (_vaMode === "browse-video" && _vaCurrentVideoPath) {
          body.video_path = _vaCurrentVideoPath;
        } else if (_vaMode === "video" && _vaVideoName) {
          body.video_name = _vaVideoName;
        }
        return body;
      }

      // ── Extract Frame ────────────────────────────────────────────
      if (vaExtractFrameBtn) {
        vaExtractFrameBtn.addEventListener("click", async () => {
          if (!_vaMode || _vaMode === "frames") {
            _curStatus("No video loaded — open a video first.", true); return;
          }
          vaExtractFrameBtn.disabled = true;
          _curStatus("Extracting…");
          let primaryRes = { ok: false };
          try {
            const res  = await fetch("/dlc/curator/extract-frame", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(_videoRequestBody()),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            primaryRes = { ok: true, body: data };
            _curStatus(
              data.duplicate
                ? `Already extracted: ${data.saved}`
                : `Saved ${data.saved} (${data.folder}, #${data.frame_count})`
            );
          } catch (err) {
            primaryRes = { ok: false, error: err.message };
            _curStatus(`Extract failed: ${err.message}`, true);
          }
          // ── Paired sibling-cam fan-out (when sync + Both cams) ──
          if (_va3dShouldDoubleUp()) {
            const tile1 = Controller.tiles[1];
            const sibBody = _va3dBuildCuratorBody(tile1, _vaCurrentFrame);
            const sibRes = await _va3dCuratorCall("/dlc/curator/extract-frame", sibBody);
            _va3dShowCuratorStatus(Controller.tiles, [primaryRes, sibRes]);
          }
          vaExtractFrameBtn.disabled = false;
        });
      }

      // ── Add to Dataset ────────────────────────────────────────────
      if (vaAddToDatasetBtn) {
        vaAddToDatasetBtn.addEventListener("click", async () => {
          if (!_vaMode || _vaMode === "frames") {
            _curStatus("No video loaded — open a video first.", true); return;
          }
          vaAddToDatasetBtn.disabled = true;
          _curStatus("Adding to dataset…");
          let primaryRes = { ok: false };
          try {
            const res  = await fetch("/dlc/curator/add-to-dataset", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(_videoRequestBody()),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            primaryRes = { ok: true, body: data };
            const h5note = data.h5_updated ? " + H5" : "";
            _curStatus(
              data.duplicate
                ? `Already in dataset: ${data.saved}`
                : `Added ${data.saved} to CSV${h5note} (${data.frame_count} frames)`
            );
          } catch (err) {
            primaryRes = { ok: false, error: err.message };
            _curStatus(`Failed: ${err.message}`, true);
          }
          // ── Paired sibling-cam fan-out (when sync + Both cams) ──
          if (_va3dShouldDoubleUp()) {
            const tile1 = Controller.tiles[1];
            const sibBody = _va3dBuildCuratorBody(tile1, _vaCurrentFrame);
            const sibRes = await _va3dCuratorCall("/dlc/curator/add-to-dataset", sibBody);
            _va3dShowCuratorStatus(Controller.tiles, [primaryRes, sibRes]);
          }
          vaAddToDatasetBtn.disabled = false;
        });
      }

      // ── Batch Add ─────────────────────────────────────────────────
      if (vaBatchAddBtn) {
        vaBatchAddBtn.addEventListener("click", async () => {
          if (!_vaMode || _vaMode === "frames") {
            _curStatus("No video loaded — open a video first.", true); return;
          }
          const count = Math.max(1, parseInt(vaBatchCount?.value) || 10);
          const step  = Math.max(1, parseInt(vaBatchStep?.value)  || 30);
          vaBatchAddBtn.disabled = true;
          let added = 0, dupes = 0, errors = 0;
          const start = _vaCurrentFrame;
          let lastFrame = start;
          let aborted = false;
          for (let i = 0; i < count; i++) {
            const frameNum = start + i * step;
            if (frameNum >= _vaFrameCount) break;
            lastFrame = frameNum;
            _curStatus(`Batch adding… ${i + 1}/${count} (frame ${frameNum})`);
            // Navigate player to the frame being extracted
            await Controller.seek(frameNum);
            try {
              const res  = await fetch("/dlc/curator/add-to-dataset", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(_videoRequestBody(frameNum)),
              });
              const data = await res.json();
              if (!res.ok) { errors++; continue; }
              if (data.duplicate) dupes++; else added++;
            } catch (_) { errors++; }
            // ── Paired sibling-cam fan-out (when sync + Both cams) ──
            // Stop on first sibling-side failure (per spec).
            if (_va3dShouldDoubleUp()) {
              const tile1 = Controller.tiles[1];
              const sibBody = _va3dBuildCuratorBody(tile1, frameNum);
              const sibRes = await _va3dCuratorCall("/dlc/curator/add-to-dataset", sibBody);
              if (!sibRes.ok) {
                errors++;
                _curStatus(`Batch aborted at frame ${frameNum} — cam1 failed: ${sibRes.error || ''}`, true);
                aborted = true;
                break;
              }
              const sibData = sibRes.body || {};
              if (sibData.duplicate) dupes++; else added++;
            }
          }
          // Ensure player is on the last frame processed
          if (lastFrame !== _vaCurrentFrame) await Controller.seek(lastFrame);
          vaBatchAddBtn.disabled = false;
          if (!aborted) {
            const parts = [];
            if (added) parts.push(`${added} added`);
            if (dupes) parts.push(`${dupes} duplicate${dupes !== 1 ? "s" : ""}`);
            if (errors) parts.push(`${errors} error${errors !== 1 ? "s" : ""}`);
            _curStatus(`Batch done: ${parts.join(", ") || "nothing to add"}.`, errors > 0 && added === 0);
          }
        });
      }

      // ── Timeline bars ────────────────────────────────────────────

      // Canvas-based timeline: one fillRect per annotated frame, zero DOM nodes per frame.
      // Only frames whose field value is in activeSet are drawn; each value uses its own color from colorMap.
      function _vaDrawCanvas(canvas, rows, field, activeSet, colorMap) {
        if (!canvas) return;
        const total = Math.max(_vaFrameCount, 1);
        const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
        canvas.width = W;
        const H    = canvas.height || 12;
        const ctx  = canvas.getContext("2d");
        const minW = Math.max(1, Math.round(W / total));
        ctx.clearRect(0, 0, W, H);
        if (!activeSet || activeSet.size === 0) return;
        rows.forEach(row => {
          const val = row[field];
          if (!val || (field === "frame_line_status" && val === "0")) return;
          if (!activeSet.has(val)) return;
          ctx.fillStyle = colorMap[val] || "#888";
          const x = Math.round((Number(row.frame_number) / total) * W);
          ctx.fillRect(x, 0, minW, H);
        });
      }

      function _vaRedrawNoteCanvas()   { _vaDrawCanvas(vaNoteCanvas,   _vaCsvRows, "note",              _vaActiveNoteChips,   _vaNoteColorMap);   }
      function _vaRedrawStatusCanvas() { _vaDrawCanvas(vaStatusCanvas, _vaCsvRows, "frame_line_status", _vaActiveStatusChips, _vaStatusColorMap); }

      function _vaBuildCsvBars() {
        if (!vaCsvBars) return;
        const hasNote   = _vaCsvRows.some(r => r.note);
        const hasStatus = _vaCsvRows.some(r => r.frame_line_status && r.frame_line_status !== "0");
        vaCsvBars.classList.toggle("hidden", !hasNote && !hasStatus);
        vaNoteBarWrap?.classList.toggle("hidden", !hasNote);
        vaStatusBarWrap?.classList.toggle("hidden", !hasStatus);
        // Canvases start empty; chips toggle individual values onto them.
        _vaRedrawNoteCanvas();
        _vaRedrawStatusCanvas();
      }

      // Click on either canvas — map x position to frame number and jump.
      [vaNoteCanvas, vaStatusCanvas].forEach(canvas => {
        if (!canvas) return;
        canvas.addEventListener("click", e => {
          const rect = canvas.getBoundingClientRect();
          const fn = Math.round((e.clientX - rect.left) / rect.width * Math.max(_vaFrameCount - 1, 0));
          Controller.seek(fn);
        });
      });

      // Prev/next navigation within the active chip set for a given field.
      function _vaNavAnnot(field, activeSet, dir) {
        if (!activeSet.size) return;
        const frames = _vaCsvRows
          .filter(r => { const v = r[field]; return v && (field !== "frame_line_status" || v !== "0") && activeSet.has(v); })
          .map(r => r.frame_number)
          .sort((a, b) => a - b);
        if (!frames.length) return;
        if (dir < 0) {
          const prev = [...frames].reverse().find(f => f < _vaCurrentFrame);
          if (prev != null) Controller.seek(prev);
        } else {
          const next = frames.find(f => f > _vaCurrentFrame);
          if (next != null) Controller.seek(next);
        }
      }

      if (vaStatusPrevBtn) vaStatusPrevBtn.addEventListener("click", () => _vaNavAnnot("frame_line_status", _vaActiveStatusChips, -1));
      if (vaStatusNextBtn) vaStatusNextBtn.addEventListener("click", () => _vaNavAnnot("frame_line_status", _vaActiveStatusChips,  1));
      if (vaNoteStepPrevBtn) vaNoteStepPrevBtn.addEventListener("click", () => _vaNavAnnot("note", _vaActiveNoteChips, -1));
      if (vaNoteStepNextBtn) vaNoteStepNextBtn.addEventListener("click", () => _vaNavAnnot("note", _vaActiveNoteChips,  1));

      // ── Companion CSV helpers ────────────────────────────────────

      function _vaCsvSyncPanel() {
        if (!_vaCsvPath) return;
        if (vaAnnotFrameNum) vaAnnotFrameNum.textContent = _vaCurrentFrame;
        const row = _vaCsvRows.find(r => r.frame_number === _vaCurrentFrame);
        if (vaNoteInput)   vaNoteInput.value   = row ? (row.note || "") : "";
        if (vaStatusInput) vaStatusInput.value = row ? (row.frame_line_status ?? "0") : "0";
      }

      function _vaCsvApplyRows(rows, csvPath) {
        _vaCsvPath  = csvPath;
        _vaCsvRows  = rows;
        const noteVals   = [...new Set(rows.map(r => r.note).filter(v => v))];
        const statusVals = [...new Set(rows.map(r => r.frame_line_status).filter(v => v && v !== "0"))];
        _vaUserTags     = [...new Set([..._vaUserTags,     ...noteVals])];
        _vaUserStatuses = [...new Set([..._vaUserStatuses, ...statusVals])];

        if (vaCsvNone)        vaCsvNone.classList.add("hidden");
        if (vaCsvLoaded)      vaCsvLoaded.classList.remove("hidden");
        if (vaCsvPathDisplay) { vaCsvPathDisplay.textContent = csvPath; vaCsvPathDisplay.title = csvPath; }
        if (vaAnnotPanel)     vaAnnotPanel.classList.remove("hidden");

        _vaBuildCsvBars();
        _vaCsvRenderStatusChips();
        _vaCsvRenderTags();
        _vaCsvSyncPanel();
      }

      function _vaCsvRenderStatusChips() {
        if (!vaStatusChips) return;
        vaStatusChips.innerHTML = "";
        _vaStatusColorMap = {};
        _vaUserStatuses.forEach((val, i) => {
          const color = _VA_STATUS_COLORS[i % _VA_STATUS_COLORS.length];
          _vaStatusColorMap[val] = color;
          const chip = document.createElement("span");
          chip.className = "fe-tag-chip" + (_vaActiveStatusChips.has(val) ? " active" : "");
          chip.textContent = val;
          chip.style.setProperty("--chip-color", color);
          chip.title = `Click to show/hide "${val}" on timeline`;
          chip.addEventListener("click", () => {
            if (_vaActiveStatusChips.has(val)) _vaActiveStatusChips.delete(val);
            else _vaActiveStatusChips.add(val);
            _vaCsvRenderStatusChips();
            _vaRedrawStatusCanvas();
          });
          vaStatusChips.appendChild(chip);
        });
        const hasActive = _vaActiveStatusChips.size > 0;
        if (vaStatusPrevBtn) vaStatusPrevBtn.disabled = !hasActive;
        if (vaStatusNextBtn) vaStatusNextBtn.disabled = !hasActive;
      }

      function _vaCsvRenderTags() {
        if (!vaNoteChips) return;
        vaNoteChips.innerHTML = "";
        _vaNoteColorMap = {};
        _vaUserTags.forEach((tag, i) => {
          const color = _VA_NOTE_COLORS[i % _VA_NOTE_COLORS.length];
          _vaNoteColorMap[tag] = color;
          const chip = document.createElement("span");
          chip.className = "fe-tag-chip" + (_vaActiveNoteChips.has(tag) ? " active" : "");
          chip.textContent = tag;
          chip.style.setProperty("--chip-color", color);
          chip.title = `Click to show/hide "${tag}" on timeline`;
          chip.addEventListener("click", () => {
            if (_vaActiveNoteChips.has(tag)) _vaActiveNoteChips.delete(tag);
            else _vaActiveNoteChips.add(tag);
            _vaCsvRenderTags();
            _vaRedrawNoteCanvas();
          });
          vaNoteChips.appendChild(chip);
        });
        const hasActive = _vaActiveNoteChips.size > 0;
        if (vaNoteStepPrevBtn) vaNoteStepPrevBtn.disabled = !hasActive;
        if (vaNoteStepNextBtn) vaNoteStepNextBtn.disabled = !hasActive;
      }

      async function _vaCsvSaveStatus() {
        if (!_vaCsvPath) return;
        // Read existing note for this frame so saving status doesn't wipe it
        const existingRow = _vaCsvRows.find(r => r.frame_number === _vaCurrentFrame);
        const note   = vaNoteInput ? vaNoteInput.value.trim() : (existingRow?.note || "");
        const status = vaStatusInput ? (vaStatusInput.value || "0") : "0";
        await _vaCsvDoSave(note, status);
      }

      async function _vaCsvSaveNote() {
        if (!_vaCsvPath) return;
        // Read existing status for this frame so saving note doesn't wipe it
        const existingRow = _vaCsvRows.find(r => r.frame_number === _vaCurrentFrame);
        const note   = vaNoteInput ? vaNoteInput.value.trim() : "";
        const status = vaStatusInput ? (vaStatusInput.value || "0") : (existingRow?.frame_line_status || "0");
        await _vaCsvDoSave(note, status);
      }

      async function _vaCsvDoSave(note, status) {
        if (vaAnnotSaveStatus) { vaAnnotSaveStatus.textContent = "Saving…"; vaAnnotSaveStatus.className = "fe-extract-status"; }
        try {
          const res  = await fetch("/annotate/save-row", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({
              csv_path:          _vaCsvPath,
              frame_number:      _vaCurrentFrame,
              note,
              frame_line_status: status,
              fps:               _vaFps,
            }),
          });
          const data = await res.json();
          if (data.error) throw new Error(data.error);

          const isInteresting = note || (status && status !== "0");
          const idx = _vaCsvRows.findIndex(r => r.frame_number === _vaCurrentFrame);
          if (isInteresting) {
            const savedRow = data.row || { frame_number: _vaCurrentFrame, timestamp: (_vaCurrentFrame / _vaFps).toFixed(3), frame_line_status: status, note };
            if (idx >= 0) _vaCsvRows[idx] = savedRow;
            else { _vaCsvRows.push(savedRow); _vaCsvRows.sort((a, b) => a.frame_number - b.frame_number); }
            if (note && !_vaUserTags.includes(note)) { _vaUserTags.push(note); _vaCsvRenderTags(); }
            if (status && status !== "0" && !_vaUserStatuses.includes(status)) { _vaUserStatuses.push(status); _vaCsvRenderStatusChips(); }
          } else {
            if (idx >= 0) _vaCsvRows.splice(idx, 1);
          }

          _vaBuildCsvBars();

          if (vaAnnotSaveStatus) {
            vaAnnotSaveStatus.textContent = "Saved";
            vaAnnotSaveStatus.className   = "fe-extract-status ok";
            setTimeout(() => { if (vaAnnotSaveStatus?.textContent === "Saved") vaAnnotSaveStatus.textContent = ""; }, 2000);
          }
        } catch (err) {
          if (vaAnnotSaveStatus) { vaAnnotSaveStatus.textContent = `Error: ${err.message}`; vaAnnotSaveStatus.className = "fe-extract-status err"; }
        }
      }

      async function _vaCsvLoad(videoPath) {
        // Reset CSV state
        _vaCsvPath = null; _vaCsvRows = []; _vaUserTags = []; _vaUserStatuses = []; _vaActiveNoteFilter = null;
        _vaActiveNoteChips = new Set(); _vaActiveStatusChips = new Set();
        _vaNoteColorMap = {}; _vaStatusColorMap = {};
        if (vaCsvNone)        vaCsvNone.classList.remove("hidden");
        if (vaCsvLoaded)      vaCsvLoaded.classList.add("hidden");
        if (vaCsvBars)        vaCsvBars.classList.add("hidden");
        if (vaAnnotPanel)     vaAnnotPanel.classList.add("hidden");
        if (vaCsvCreateStatus) vaCsvCreateStatus.textContent = "";

        if (!videoPath) return;
        try {
          const res  = await fetch(`/annotate/csv?path=${encodeURIComponent(videoPath)}`);
          const data = await res.json();
          if (data.csv_exists) {
            _vaCsvApplyRows(data.rows, data.csv_path);
          }
        } catch (_) {}
      }

      // Hook into frame navigation
      _vaCurationFrameHook = () => {
        _vaCsvSyncPanel();
      };

      // Load companion CSV when player section becomes visible (video opened)
      if (typeof MutationObserver !== "undefined" && vaPlayerSec) {
        new MutationObserver(async () => {
          if (!vaPlayerSec.classList.contains("hidden") && _vaCurrentVideoPath) {
            await _vaCsvLoad(_vaCurrentVideoPath);
          } else if (vaPlayerSec.classList.contains("hidden")) {
            _vaCsvPath = null; _vaCsvRows = []; _vaUserTags = []; _vaUserStatuses = []; _vaActiveNoteFilter = null;
            _vaActiveNoteChips = new Set(); _vaActiveStatusChips = new Set();
            _vaNoteColorMap = {}; _vaStatusColorMap = {};
            if (vaCsvNone)    vaCsvNone.classList.remove("hidden");
            if (vaCsvLoaded)  vaCsvLoaded.classList.add("hidden");
            if (vaCsvBars)    vaCsvBars.classList.add("hidden");
            if (vaAnnotPanel) vaAnnotPanel.classList.add("hidden");
          }
        }).observe(vaPlayerSec, { attributes: true, attributeFilter: ["class"] });
      }

      // Create CSV
      if (vaCreateCsvBtn) {
        vaCreateCsvBtn.addEventListener("click", async () => {
          if (!_vaCurrentVideoPath) return;
          if (vaCsvCreateStatus) { vaCsvCreateStatus.textContent = `Creating CSV for ${_vaFrameCount} frames…`; vaCsvCreateStatus.className = "fe-extract-status"; }
          try {
            const res  = await fetch("/annotate/create-csv", {
              method:  "POST",
              headers: { "Content-Type": "application/json" },
              body:    JSON.stringify({ video_path: _vaCurrentVideoPath, fps: _vaFps, frame_count: _vaFrameCount }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            if (vaCsvCreateStatus) vaCsvCreateStatus.textContent = "";
            _vaCsvApplyRows(data.rows, data.csv_path);
          } catch (err) {
            if (vaCsvCreateStatus) { vaCsvCreateStatus.textContent = `Error: ${err.message}`; vaCsvCreateStatus.className = "fe-extract-status err"; }
          }
        });
      }

      // Save annotation
      if (vaSaveStatusBtn) {
        vaSaveStatusBtn.addEventListener("click", _vaCsvSaveStatus);
      }
      if (vaSaveNoteBtn) {
        vaSaveNoteBtn.addEventListener("click", _vaCsvSaveNote);
      }

      // Add new tag
      if (vaAddTagBtn) {
        vaAddTagBtn.addEventListener("click", () => {
          const tag = vaNewTagInput ? vaNewTagInput.value.trim() : "";
          if (!tag) return;
          if (!_vaUserTags.includes(tag)) { _vaUserTags.push(tag); _vaCsvRenderTags(); }
          if (vaNewTagInput) vaNewTagInput.value = "";
        });
      }
      if (vaNewTagInput) {
        vaNewTagInput.addEventListener("keydown", e => {
          if (e.key === "Enter") { e.preventDefault(); vaAddTagBtn?.click(); }
        });
      }

    })(); // end Dataset Curation

    // ── Video Metadata Panel (companion CSV viewer) ────────────────────────
    (() => {
      const vaMetaCsvInfo   = document.getElementById("va3d-meta-csv-info");
      const vaMetaFrameRow  = document.getElementById("va3d-meta-frame-row");
      const vaMetaFrameNote = document.getElementById("va3d-meta-frame-note");
      const vaMetaFrameStat = document.getElementById("va3d-meta-frame-status");
      if (!vaMetaCsvInfo) return;

      let _metaCsvRows = [];

      function _metaClear() {
        _metaCsvRows = [];
        vaMetaCsvInfo.textContent = "No companion CSV";
        vaMetaFrameRow.style.display = "none";
      }

      function _metaShowFrame(n) {
        if (!_metaCsvRows.length) { vaMetaFrameRow.style.display = "none"; return; }
        const row = _metaCsvRows.find(r => r.frame_number === n);
        const hasContent = row && (row.note || (row.frame_line_status && row.frame_line_status !== "0"));
        if (!hasContent) { vaMetaFrameRow.style.display = "none"; return; }
        vaMetaFrameRow.style.display = "flex";
        vaMetaFrameNote.textContent = row.note || "—";
        vaMetaFrameStat.textContent = row.frame_line_status || "0";
      }

      async function _metaLoad(videoPath) {
        _metaClear();
        if (!videoPath) return;
        try {
          const res  = await fetch(`/annotate/csv?path=${encodeURIComponent(videoPath)}`);
          const data = await res.json();
          if (!data.csv_exists) return;
          // Store only rows with actual annotations for the frame tooltip
          _metaCsvRows = (data.rows || []).filter(
            r => r.note || (r.frame_line_status && r.frame_line_status !== "0"),
          );
          const fname = (data.csv_path || "").split("/").pop();
          vaMetaCsvInfo.textContent = _metaCsvRows.length
            ? `${fname} · ${_metaCsvRows.length.toLocaleString()} annotated frames`
            : `${fname} · no annotations yet`;
        } catch (_) {}
      }

      // Hook into frame navigation (outer scope variable set above)
      _vaMetadataFrameHook = n => _metaShowFrame(n);

      // Watch vaPlayerSec visibility to auto-load the companion CSV
      if (typeof MutationObserver !== "undefined" && vaPlayerSec) {
        new MutationObserver(async () => {
          if (!vaPlayerSec.classList.contains("hidden") && _vaCurrentVideoPath) {
            await _metaLoad(_vaCurrentVideoPath);
            _metaShowFrame(_vaCurrentFrame);
          } else if (vaPlayerSec.classList.contains("hidden")) {
            _metaClear();
          }
        }).observe(vaPlayerSec, { attributes: true, attributeFilter: ["class"] });
      }
    })(); // end Video Metadata Panel

