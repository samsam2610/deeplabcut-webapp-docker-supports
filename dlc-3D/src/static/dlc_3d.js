// dlc_3d.js — inline file browser, project loader, extract button handler.
"use strict";

import { VideoViewer } from "./components/viewer/video_viewer.js";
import { statusNoteTimeline } from "./components/viewer/features/status_notes.js";
import { frameExtractor } from "./components/viewer/features/frame_extractor.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath        = null;
let _activeSession      = null;
let _activeVideo        = null;
let _siblingVideo       = null;
let _calibrationExists  = false;
let _loadToken          = 0;
let _browserCurrentPath = null;
let _browserParentPath  = null;

let _viewer             = null;
let _frameExtractor     = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setStatus(msg) {
  const el = document.getElementById("extract-status");
  if (el) el.textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

function _sessionKeyFromVideoPath(videoPath) {
  const parts = videoPath.split("/");
  // Try filename stem first
  let stem = parts[parts.length - 1].replace(/\.[^.]+$/, "");
  let m = stem.match(/^(.+?)_cam\d+_(\d{8})/);
  if (m) return `${m[1]}_${m[2]}`;
  // Fallback: try parent folder name (for clips in subfolders)
  if (parts.length >= 2) {
    stem = parts[parts.length - 2];
    m = stem.match(/^(.+?)_cam\d+_(\d{8})/);
    if (m) return `${m[1]}_${m[2]}`;
  }
  return null;
}

// ── VideoViewer composition ─────────────────────────────────────────────────

function _ensureViewer() {
  if (_viewer) return _viewer;
  const mount = document.getElementById("ep-viewer-mount");
  _viewer = new VideoViewer({
    mount,
    fps: 15,
    storagePrefix: "dlc3d-extract",
    endpoints: {
      videoInfo: (v) => `/dlc-3d/video-info?video=${encodeURIComponent(v)}`,
      frame:     (v, n) => `/dlc-3d/frame?video=${encodeURIComponent(v)}&n=${n}`,
      // sibling discovery is handled by the consumer (we pass siblingPath to load()
      // only when sync-cam is enabled), so endpoints.sibling is intentionally omitted.
    },
  });

  // status/note timeline (browse-only — no save-row in this card)
  _viewer.use(statusNoteTimeline({
    endpoints: { csv: (v) => `/dlc-3d/csv?video=${encodeURIComponent(v)}` },
    els: {
      statusCanvas: document.getElementById("ep-status-canvas"),
      noteCanvas:   document.getElementById("ep-note-canvas"),
      statusWrap:   document.getElementById("ep-status-bar-wrap"),
      noteWrap:     document.getElementById("ep-note-bar-wrap"),
      statusChips:  document.getElementById("ep-status-chips"),
      noteChips:    document.getElementById("ep-note-chips"),
      statusPrev:   document.getElementById("ep-status-prev"),
      statusNext:   document.getElementById("ep-status-next"),
      notePrev:     document.getElementById("ep-note-prev"),
      noteNext:     document.getElementById("ep-note-next"),
    },
  }));

  // frame extractor (single + batch + sibling) → /dlc-3d/save-frame
  _frameExtractor = frameExtractor({
    endpoints: {
      saveFrame: (payload) => fetch("/dlc-3d/save-frame", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    },
    els: {
      extractBtn:     document.getElementById("ep-extract-btn"),
      batchBtn:       document.getElementById("ep-batch-extract-btn"),
      batchStopBtn:   document.getElementById("ep-batch-stop-btn"),
      batchCount:     document.getElementById("ep-batch-count"),
      batchStep:      document.getElementById("ep-batch-step"),
      extractSibling: document.getElementById("ep-extract-sibling"),
      statusDisplay:  document.getElementById("extract-status"),
    },
    onSaved: () => _refreshLabeledFrames(),
  });
  _viewer.use(_frameExtractor);

  _wireViewerChrome(_viewer);
  return _viewer;
}

function _wireViewerChrome(v) {
  const $ = (id) => document.getElementById(id);
  const stepSize = () => Math.max(1, parseInt($("ep-step")?.value, 10) || 10);

  // Initialise viewer state from the card's existing control defaults so behaviour
  // matches the old player (loop ON by default — #ep-loop carries .active in markup).
  v.setSkipN(stepSize());
  v.setPlayStep($("ep-playn")?.value || 1);
  v.setLooping($("ep-loop")?.classList.contains("active") ?? true);

  $("ep-skip-start")?.addEventListener("click", () => v.seek(0));
  $("ep-skip-end")?.addEventListener("click", () => v.seek(v.frameCount() - 1));
  $("ep-back1")?.addEventListener("click", () => v.step(-1));
  $("ep-fwd1")?.addEventListener("click", () => v.step(1));
  $("ep-back")?.addEventListener("click", () => v.step(-stepSize()));
  $("ep-fwd")?.addEventListener("click", () => v.step(stepSize()));
  $("ep-play")?.addEventListener("click", () => { v.setPlayDir(1); v.togglePlay(); });
  $("ep-play-back")?.addEventListener("click", () => { v.setPlayDir(-1); v.togglePlay(); });
  $("ep-loop")?.addEventListener("click", (e) => {
    const on = !e.currentTarget.classList.contains("active");
    e.currentTarget.classList.toggle("active", on);
    v.setLooping(on);
  });
  $("ep-step")?.addEventListener("input", () => { v.setSkipN(stepSize()); v.setPlayStep(stepSize()); });
  $("ep-playn")?.addEventListener("input", (e) => v.setPlayStep(e.target.value));
  document.querySelectorAll(".ep-step-preset").forEach((p) =>
    p.addEventListener("click", () => { const s = $("ep-step"); if (s) { s.value = p.value; s.dispatchEvent(new Event("input")); } }));

  const seek = $("ep-seek");
  seek?.addEventListener("input", () => v.seek(parseInt(seek.value, 10) || 0));

  const zoom = $("ep-zoom-3d");
  zoom?.addEventListener("input", () => {
    v.setZoom(parseInt(zoom.value, 10) || 100);
    const pct = $("ep-zoom-3d-pct"); if (pct) pct.textContent = zoom.value + "%";
  });

  v.on("videoLoad", ({ frameCount }) => {
    if (seek) { seek.min = 0; seek.max = Math.max(frameCount - 1, 0); }
    const tot = $("ep-frame-total"); if (tot) tot.textContent = String(frameCount);
    $("no-video-msg")?.style.setProperty("display", "none");
    $("ep-extract-btn")?.removeAttribute("disabled");
    $("ep-batch-extract-btn")?.removeAttribute("disabled");
  });
  v.on("frameChange", (n) => {
    if (seek) seek.value = String(n);
    const num = $("ep-frame-num"); if (num) num.textContent = String(n + 1); // 1-based display
  });
}

function _setupSyncCamToggle(v) {
  const row = document.getElementById("sync-cam-row");
  const cb = document.getElementById("ep-sync-cam");
  const sibLabel = document.getElementById("ep-extract-sibling-label");
  if (!cb) return;
  // show the sync-cam row only when a sibling exists
  if (row) row.style.display = _siblingVideo ? "flex" : "none";
  // reset toggle state to OFF on each (re)selection — matches the old player's
  // per-video reset (sync cam starts disabled, sibling-extract label hidden).
  cb.checked = false;
  if (sibLabel) sibLabel.style.display = "none";
  if (cb._wired) return; cb._wired = true;
  cb.addEventListener("change", async () => {
    if (cb.checked && !_calibrationExists) {
      cb.checked = false;
      const st = document.getElementById("extract-status");
      if (st) st.textContent = "Cannot enable Sync Cam: calibration.toml not found in recording folder.";
      return;
    }
    if (sibLabel) sibLabel.style.display = cb.checked ? "flex" : "none";
    if (cb.checked) {
      const ex = document.getElementById("ep-extract-sibling");
      if (ex) ex.checked = true;
    }
    // reload with/without the sibling tile to match the toggle, preserving frame
    const keepFrame = v.currentFrame();
    await v.load({ videoPath: _activeVideo, siblingPath: cb.checked ? _siblingVideo : null });
    if (keepFrame > 0) v.seek(keepFrame);
    _applyCamLabels();
  });
}

// ── Extractor reset ───────────────────────────────────────────────────────────

function _resetExtractorUI() {
  _projectPath        = null;
  _activeVideo        = null;
  _siblingVideo       = null;
  _calibrationExists  = false;
  _activeSession      = null;
  _browserCurrentPath = null;

  // Tear down the shared viewer so a re-open rebuilds cleanly.
  _viewer?.destroy();
  _viewer = null;
  _frameExtractor = null;

  document.getElementById("dlc3d-player-section").style.display = "none";
  const browser = document.getElementById("dlc3d-file-browser");
  if (browser) { browser.innerHTML = ""; browser.style.display = "none"; }
  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) { empty.style.display = ""; empty.textContent = "Load a DLC project via \"Manage DLC Project\"."; }
  const browseRow = document.getElementById("dlc3d-browse-row");
  if (browseRow) browseRow.style.display = "none";
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) { pathInput.style.display = "none"; pathInput.value = ""; }
  const upBtn = document.getElementById("dlc3d-browse-up");
  if (upBtn) upBtn.style.display = "none";
  _browserParentPath = null;
  _setStatus("");
  const labeledWrap = document.getElementById("labeled-wrap");
  if (labeledWrap) labeledWrap.style.display = "none";
  const extractBtn = document.getElementById("ep-extract-btn");
  const batchBtn   = document.getElementById("ep-batch-extract-btn");
  const batchStop  = document.getElementById("ep-batch-stop-btn");
  if (extractBtn) extractBtn.disabled = true;
  if (batchBtn)   batchBtn.disabled = true;
  if (batchStop)  batchStop.classList.add("hidden");
}

// ── Card open / close ─────────────────────────────────────────────────────────

function _openCard() {
  document.getElementById("dlc-3d-extract-card").classList.remove("hidden");
  document.getElementById("dlc-3d-extract-card").scrollIntoView({ behavior: "smooth", block: "nearest" });

  if (!_projectPath) {
    const activePath = document.getElementById("dlc-active-path")?.textContent.trim();
    if (activePath) _loadProject(activePath);
  }
}

function _closeCard() {
  document.getElementById("dlc-3d-extract-card").classList.add("hidden");
}

// ── Project loading ───────────────────────────────────────────────────────────

async function _loadProject(path) {
  const token = ++_loadToken;
  _setStatus("Loading project…");
  let data;
  try {
    const resp = await fetch("/dlc-3d/project", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    data = await resp.json();
    if (!resp.ok) { _setStatus(data.error || "Failed to load project"); return; }
  } catch (e) { _setStatus("Network error: " + e.message); return; }
  if (token !== _loadToken) return;

  _projectPath = data.project_path;
  const browseRow = document.getElementById("dlc3d-browse-row");
  if (browseRow) browseRow.style.display = "flex";
  _setStatus("");
}

// ── Inline file browser ───────────────────────────────────────────────────────

async function _browseDir(path) {
  const browser = document.getElementById("dlc3d-file-browser");
  const empty   = document.getElementById("dlc3d-session-empty");
  browser.innerHTML = '<span style="font-size:.8rem;color:var(--text-dim)">Loading…</span>';
  browser.style.display = "";
  if (empty) empty.style.display = "none";

  let data;
  try {
    const url = path
      ? `/dlc-3d/browse?path=${encodeURIComponent(path)}`
      : "/dlc-3d/browse";
    const resp = await fetch(url);
    data = await resp.json();
    if (!resp.ok) {
      const errMsg = document.createElement("span");
      errMsg.style.cssText = "font-size:.8rem;color:var(--text-dim)";
      errMsg.textContent = data.error || "Browse error";
      browser.replaceChildren(errMsg);
      return;
    }
  } catch (e) {
    browser.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">Network error</span>`;
    return;
  }

  _browserCurrentPath = data.path;
  _browserParentPath  = data.parent || null;
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) pathInput.value = data.path;
  const upBtn = document.getElementById("dlc3d-browse-up");
  if (upBtn) upBtn.disabled = !_browserParentPath;
  browser.innerHTML = "";

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    row.className = "fe-video-item";
    row.style.cursor = "pointer";

    if (entry.type === "dir") {
      row.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${entry.name}/</span>`;
      row.addEventListener("click", () => _browseDir(_browserCurrentPath + "/" + entry.name));
    } else if (entry.type === "file") {
      row.dataset.videoPath = _browserCurrentPath + "/" + entry.name;
      row.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0">
          <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/>
          <line x1="7" y1="2" x2="7" y2="22"/>
          <line x1="17" y1="2" x2="17" y2="22"/>
          <line x1="2" y1="12" x2="22" y2="12"/>
          <line x1="2" y1="7" x2="7" y2="7"/>
          <line x1="2" y1="17" x2="7" y2="17"/>
          <line x1="17" y1="17" x2="22" y2="17"/>
          <line x1="17" y1="7" x2="22" y2="7"/>
        </svg>
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${entry.name}</span>`;
      row.addEventListener("click", () => _selectVideo(row.dataset.videoPath));
    } else {
      continue;
    }
    browser.appendChild(row);
  }

  if (browser.children.length === 0) {
    const msg = document.createElement("span");
    msg.style.cssText = "font-size:.8rem;color:var(--text-dim)";
    msg.textContent = "No files found.";
    browser.appendChild(msg);
  }
}

// ── Video selection ───────────────────────────────────────────────────────────

async function _selectVideo(videoPath) {
  _activeVideo   = videoPath;
  _activeSession = _sessionKeyFromVideoPath(videoPath);

  document.querySelectorAll("#dlc3d-file-browser .fe-video-item").forEach(el => {
    el.classList.toggle("active", el.dataset.videoPath === videoPath);
  });

  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) empty.style.display = "none";

  const browser = document.getElementById("dlc3d-file-browser");
  if (browser) browser.style.display = "none";

  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) pathInput.style.display = "none";
  const upBtn = document.getElementById("dlc3d-browse-up");
  if (upBtn) upBtn.style.display = "none";

  document.getElementById("dlc3d-player-section").style.display = "";

  // Sibling-camera discovery (consumer-owned — the viewer's sibling endpoint is
  // intentionally omitted so we control when the 2nd tile appears via sync-cam).
  let siblingPath        = null;
  let calibrationExists  = false;
  try {
    const sr = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoPath)}`);
    if (sr.ok) {
      const sd = await sr.json();
      siblingPath        = sd.sibling_video_path || null;
      calibrationExists  = !!sd.calibration_exists;
    }
  } catch (e) { console.warn("[dlc_3d] sibling-camera fetch failed:", e); }

  _siblingVideo      = siblingPath || null;
  _calibrationExists = !!calibrationExists;

  _setStatus("");
  const v = _ensureViewer();
  _setupSyncCamToggle(v);                       // wires #ep-sync-cam (calibration-gated)
  const syncOn = document.getElementById("ep-sync-cam")?.checked;
  await v.load({ videoPath, siblingPath: syncOn ? _siblingVideo : null });
  _applyCamLabels();
  _refreshLabeledFrames();
}

// Re-label the viewer's generated tiles with the camera indices (parity with the
// old "Camera N (primary)" / "Camera N (sibling)" labels). Tiles are rebuilt on
// every load(), so this runs after each load.
function _applyCamLabels() {
  if (!_viewer) return;
  const t0 = _viewer.getTile(0);
  if (t0 && t0.labelEl) {
    const idx = (_activeVideo || "").match(/_cam(\d+)_/)?.[1] ?? "?";
    t0.labelEl.textContent = `Camera ${idx} (primary)`;
  }
  const t1 = _viewer.getTile(1);
  if (t1 && t1.labelEl) {
    const idx = (_siblingVideo || "").match(/_cam(\d+)_/)?.[1] ?? "?";
    t1.labelEl.textContent = `Camera ${idx} (sibling)`;
  }
}

// ── Labeled frames display ────────────────────────────────────────────────────

async function _refreshLabeledFrames() {
  if (!_activeSession || !_projectPath) return;
  let data;
  try {
    const resp = await fetch(`/dlc-3d/labeled-frames?session=${encodeURIComponent(_activeSession)}`);
    if (!resp.ok) return;
    data = await resp.json();
  } catch (e) { return; }

  const wrap       = document.getElementById("labeled-wrap");
  const countEl    = document.getElementById("labeled-count");
  const list       = document.getElementById("labeled-list");
  const extractCnt = document.getElementById("extract-count");

  const count = data.count || 0;
  countEl.textContent = count;
  if (extractCnt) extractCnt.textContent = `${count} frame${count !== 1 ? "s" : ""} saved`;

  list.innerHTML = "";
  for (const fname of data.frames || []) {
    const chip = document.createElement("span");
    chip.className = "frame-chip " + _camColorClass(fname);
    chip.textContent = fname;
    list.appendChild(chip);
  }

  wrap.style.display = count > 0 ? "" : "none";
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Inject a "Jobs" link into the top nav so users can jump to /jobs without
  // leaving the dlc-3d page. base.html is baked into the image (not mounted),
  // so we patch the rendered DOM instead of editing the template.
  (() => {
    const nav = document.querySelector("header.site-header nav");
    if (!nav || nav.querySelector('a[href="/jobs"]')) return;
    const a = document.createElement("a");
    a.href = "/jobs";
    a.textContent = "Jobs";
    // Mirror the styling pattern used by the existing nav anchors in base.html.
    a.style.cssText =
      "font-size:.78rem;color:var(--text-dim);text-decoration:none;" +
      "padding:.2rem .55rem;border-radius:5px;border:1px solid transparent;" +
      "transition:all .15s";
    a.onmouseover = () => {
      a.style.borderColor = "var(--border)";
      a.style.color = "var(--text)";
    };
    a.onmouseout = () => {
      a.style.borderColor = "transparent";
      a.style.color = "var(--text-dim)";
    };
    nav.appendChild(a);
  })();

  document.getElementById("btn-open-frame-extractor")?.addEventListener("click", _openCard);
  document.getElementById("btn-close-3d-extract")?.addEventListener("click", _closeCard);
  // Extract / Batch / Stop buttons are wired by the frameExtractor feature
  // (in _ensureViewer) once a video is selected — no static listeners here.

  document.getElementById("dlc3d-browse-btn")?.addEventListener("click", () => {
    const browser   = document.getElementById("dlc3d-file-browser");
    const pathInput = document.getElementById("dlc3d-path-input");
    const upBtn     = document.getElementById("dlc3d-browse-up");
    if (browser.style.display === "none") {
      if (pathInput) pathInput.style.display = "";
      if (upBtn)     upBtn.style.display     = "";
      _browseDir(_browserCurrentPath || _projectPath);
    } else {
      browser.style.display = "none";
      if (pathInput) pathInput.style.display = "none";
      if (upBtn)     upBtn.style.display     = "none";
      const empty = document.getElementById("dlc3d-session-empty");
      if (empty) empty.style.display = "";
    }
  });

  document.getElementById("dlc3d-path-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const v = e.target.value.trim();
      if (v) _browseDir(v);
    }
  });

  document.getElementById("dlc3d-browse-up")?.addEventListener("click", () => {
    if (_browserParentPath) _browseDir(_browserParentPath);
  });

  const activePathEl = document.getElementById("dlc-active-path");
  if (activePathEl) {
    new MutationObserver(() => {
      const newPath = activePathEl.textContent.trim();
      _resetExtractorUI();
      if (newPath) _loadProject(newPath);
    }).observe(activePathEl, { childList: true, characterData: true, subtree: true });
  }
});
