// enhanced_player.js — simplified video player for dlc-3D module.
// Public API: openPlayer(videoPath, siblingPath), getCurrentFrame(), getVideoPath(), getSiblingPath(), isSyncCamEnabled()

"use strict";

const _EP_FPS = 15;

let _videoPath     = null;
let _frameCount    = 0;
let _currentFrame  = 0;
let _stepSize      = 10;
let _playing       = false;
let _playDir       = 1;
let _busy          = false;
let _timerId       = null;
let _syncCamEnabled   = false;
let _siblingVideoPath = null;

let _csvRows           = [];
let _epStatusColorMap  = {};
let _epNoteColorMap    = {};
let _epActiveStatus    = new Set();
let _epActiveNote      = new Set();
let _epActiveChip      = null;       // { type: "status"|"note", val: string }

const _EP_TAG_PALETTE  = [
  "#58a6ff", "#3fb950", "#f0c040", "#f85149",
  "#d2a8ff", "#ffa657", "#79c0ff", "#56d364",
];

async function _epLoadCsv(videoPath) {
  _csvRows = [];
  _epStatusColorMap = {};
  _epNoteColorMap   = {};
  _epActiveStatus.clear();
  _epActiveNote.clear();
  _epActiveChip = null;
  try {
    const resp = await fetch(`/dlc-3d/csv?video=${encodeURIComponent(videoPath)}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (!data.csv_exists) return;
    _csvRows = data.rows || [];
    const statusVals = [...new Set(_csvRows.map(r => r.frame_line_status).filter(v => v && v !== "0"))];
    const noteVals   = [...new Set(_csvRows.map(r => r.note).filter(v => v))];
    statusVals.forEach((v, i) => { _epStatusColorMap[v] = _EP_TAG_PALETTE[i % _EP_TAG_PALETTE.length]; });
    noteVals  .forEach((v, i) => { _epNoteColorMap[v]   = _EP_TAG_PALETTE[i % _EP_TAG_PALETTE.length]; });
  } catch (e) {
    console.warn("[enhanced_player] CSV load failed:", e.message);
  }
}

function _epDrawTagCanvas(canvas, rows, field, activeSet, colorMap) {
  if (!canvas) return;
  const total = Math.max(_frameCount, 1);
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 10;
  const ctx = canvas.getContext("2d");
  const minW = Math.max(1, Math.round(W / total));
  ctx.clearRect(0, 0, W, H);
  if (!activeSet || activeSet.size === 0) return;
  rows.forEach(row => {
    const val = row[field];
    if (!val || (field === "frame_line_status" && val === "0")) return;
    if (!activeSet.has(val)) return;
    ctx.fillStyle = colorMap[val] || "#888";
    const x = Math.round(((row.frame_number - 1) / Math.max(total - 1, 1)) * W);
    ctx.fillRect(x, 0, minW, H);
  });
}

function _epDrawCursor(canvas) {
  if (!canvas) return;
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 6;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  if (_frameCount <= 1) return;
  const x = Math.round((_currentFrame / (_frameCount - 1)) * W);
  ctx.fillStyle = "#58a6ff";
  ctx.beginPath();
  ctx.moveTo(x - 4, 0);
  ctx.lineTo(x + 4, 0);
  ctx.lineTo(x, H);
  ctx.closePath();
  ctx.fill();
}

function _epRedrawAllCanvases() {
  _epDrawTagCanvas(document.getElementById("ep-status-canvas"), _csvRows, "frame_line_status", _epActiveStatus, _epStatusColorMap);
  _epDrawTagCanvas(document.getElementById("ep-note-canvas"),   _csvRows, "note",              _epActiveNote,   _epNoteColorMap);
  _epDrawCursor(document.getElementById("ep-status-cursor"));
  _epDrawCursor(document.getElementById("ep-note-cursor"));
}

function _epUpdateBarsVisibility() {
  const hasStatus = _csvRows.some(r => r.frame_line_status && r.frame_line_status !== "0");
  const hasNote   = _csvRows.some(r => r.note);
  const sw = document.getElementById("ep-status-bar-wrap");
  const nw = document.getElementById("ep-note-bar-wrap");
  if (sw) sw.style.display = hasStatus ? "" : "none";
  if (nw) nw.style.display = hasNote   ? "" : "none";
}

function _epRebuildChips() {
  const statusRow = document.getElementById("ep-status-chips");
  const noteRow   = document.getElementById("ep-note-chips");
  if (statusRow) statusRow.innerHTML = "";
  if (noteRow)   noteRow.innerHTML   = "";

  const buildChip = (type, val, color, container, activeSet) => {
    const btn = document.createElement("button");
    btn.className = "ep-chip";
    btn.dataset.type = type;
    btn.dataset.val  = val;
    btn.style.background = color;
    btn.textContent = val;
    btn.addEventListener("click", () => _epOnChipClick(type, val, btn, activeSet));
    container.appendChild(btn);
  };

  if (statusRow) {
    Object.entries(_epStatusColorMap).forEach(([val, color]) =>
      buildChip("status", val, color, statusRow, _epActiveStatus));
  }
  if (noteRow) {
    Object.entries(_epNoteColorMap).forEach(([val, color]) =>
      buildChip("note", val, color, noteRow, _epActiveNote));
  }
  _epUpdateNavButtonsEnabled();
}

function _epOnChipClick(type, val, btnEl, activeSet) {
  const wasActive = !!(_epActiveChip && _epActiveChip.type === type && _epActiveChip.val === val);
  if (wasActive) {
    _epActiveChip = null;
    activeSet.delete(val);
    btnEl.classList.remove("active");
  } else {
    if (_epActiveChip) {
      const otherSet = _epActiveChip.type === "status" ? _epActiveStatus : _epActiveNote;
      otherSet.delete(_epActiveChip.val);
      const prev = document.querySelector(`.ep-chip[data-type="${_epActiveChip.type}"][data-val="${CSS.escape(_epActiveChip.val)}"]`);
      if (prev) prev.classList.remove("active");
    }
    _epActiveChip = { type, val };
    activeSet.add(val);
    btnEl.classList.add("active");
  }
  _epUpdateNavButtonsEnabled();
  _epRedrawAllCanvases();
}

function _epUpdateNavButtonsEnabled() {
  const enabled = !!_epActiveChip;
  ["ep-status-prev", "ep-status-next", "ep-note-prev", "ep-note-next"].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.disabled = !enabled;
  });
}

function _epNavByChip(dir) {
  if (!_epActiveChip || !_csvRows.length) return;
  const { type, val } = _epActiveChip;
  const field = type === "status" ? "frame_line_status" : "note";
  const cur1  = _currentFrame + 1;
  const matches = _csvRows.filter(r => r[field] === val);
  let target = null;
  if (dir < 0) {
    target = [...matches].filter(r => Number(r.frame_number) < cur1)
      .sort((a, b) => b.frame_number - a.frame_number)[0];
  } else {
    target = matches.filter(r => Number(r.frame_number) > cur1)
      .sort((a, b) => a.frame_number - b.frame_number)[0];
  }
  if (target) { _stop(); _epLoadFrame(Number(target.frame_number) - 1); }
}

// ── Public API ────────────────────────────────────────────────────────────────

export function getVideoPath()     { return _videoPath; }
export function getCurrentFrame()  { return _currentFrame; }
export function getSiblingPath()   { return _siblingVideoPath; }
export function isSyncCamEnabled() { return _syncCamEnabled; }

export async function openPlayer(videoPath, siblingPath) {
  _stop();
  _videoPath        = videoPath;
  _siblingVideoPath = siblingPath || null;
  _syncCamEnabled   = false;
  _currentFrame     = 0;
  _stepSize         = 10;

  const stepEl = document.getElementById("ep-step");
  if (stepEl) stepEl.value = 10;

  // Show primary frame area
  const noMsg = document.getElementById("no-video-msg");
  const epFrame = document.getElementById("ep-frame");
  if (noMsg)    noMsg.style.display = "none";
  if (epFrame)  epFrame.style.display = "";

  // Fetch frame count
  let frameCount = 0;
  try {
    const resp = await fetch(`/dlc-3d/video-info?video=${encodeURIComponent(videoPath)}`);
    if (!resp.ok) { _setStatus("Cannot load video info"); return; }
    const info = await resp.json();
    frameCount = info.frame_count;
  } catch (e) { _setStatus("Network error: " + e.message); return; }

  _frameCount = frameCount;

  const seekEl = document.getElementById("ep-seek");
  if (seekEl) { seekEl.min = 0; seekEl.max = frameCount - 1; seekEl.value = 0; }

  await _epLoadCsv(videoPath);
  _epRebuildChips();
  _epUpdateBarsVisibility();
  _epRedrawAllCanvases();

  _epUpdateSyncCamUI();

  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = false;

  const zoomEl  = document.getElementById("ep-zoom-3d");
  const zoomPct = document.getElementById("ep-zoom-3d-pct");
  const camDisp = document.getElementById("cam-displays");
  if (zoomEl)  zoomEl.value = 100;
  if (zoomPct) zoomPct.textContent = "100%";
  if (camDisp) { camDisp.style.width = ""; camDisp.style.marginLeft = ""; }

  await _epLoadFrame(0);
}

// ── Frame loading ─────────────────────────────────────────────────────────────

async function _epLoadFrame(n) {
  if (_busy || !_videoPath) return;
  _busy = true;
  n = Math.max(0, Math.min(n, _frameCount - 1));
  const prev = _currentFrame;
  _currentFrame = n;
  try {
    const resp = await fetch(`/dlc-3d/frame?video=${encodeURIComponent(_videoPath)}&n=${n}`);
    if (!resp.ok) { _currentFrame = prev; return; }
    const blob   = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img    = document.getElementById("ep-frame");
    const prevSrc = img.src;
    await new Promise((resolve, reject) => {
      img.onload  = () => { if (prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); resolve(); };
      img.onerror = () => { URL.revokeObjectURL(blobUrl); reject(new Error("frame load failed")); };
      img.src = blobUrl;
    });
    _epUpdateDisplay();
    _epLoadCam2Frame(n);
    // Prefetch next frame
    if (n < _frameCount - 1) {
      new Image().src = `/dlc-3d/frame?video=${encodeURIComponent(_videoPath)}&n=${n + 1}`;
    }
  } catch (e) {
    console.warn("[enhanced_player] frame load error:", e.message);
  } finally {
    _busy = false;
  }
}

// ── Cam2 (sibling) ────────────────────────────────────────────────────────────

async function _epLoadCam2Frame(n) {
  if (!_syncCamEnabled || !_siblingVideoPath) return;
  try {
    const resp = await fetch(`/dlc-3d/frame?video=${encodeURIComponent(_siblingVideoPath)}&n=${n}`);
    if (!resp.ok) return;
    const blob    = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img     = document.getElementById("ep-cam2-frame");
    const prevSrc = img.src;
    img.onload  = () => { if (prevSrc && prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); };
    img.onerror = () => URL.revokeObjectURL(blobUrl);
    img.src = blobUrl;
  } catch (e) {
    console.warn("[enhanced_player] cam2 load error:", e.message);
  }
}

// ── Sync cam UI ───────────────────────────────────────────────────────────────

function _epUpdateSyncCamUI() {
  const syncRow    = document.getElementById("sync-cam-row");
  const syncCb     = document.getElementById("ep-sync-cam");
  const cam2Wrap   = document.getElementById("ep-cam2-wrap");
  const siblingLbl = document.getElementById("ep-extract-sibling-label");

  if (!_siblingVideoPath) {
    if (syncRow)  syncRow.style.display = "none";
    if (syncCb)   syncCb.checked = false;
    if (cam2Wrap) cam2Wrap.style.display = "none";
    if (siblingLbl) siblingLbl.style.display = "none";
    _syncCamEnabled = false;
    return;
  }

  if (syncRow) syncRow.style.display = "flex";
  if (syncCb)  syncCb.checked = _syncCamEnabled;
  if (cam2Wrap) cam2Wrap.style.display = _syncCamEnabled ? "flex" : "none";
  if (siblingLbl) {
    siblingLbl.style.display = _syncCamEnabled ? "flex" : "none";
    if (_syncCamEnabled) {
      const cb = document.getElementById("ep-extract-sibling");
      if (cb) cb.checked = true;
    }
  }
}

// ── Display ───────────────────────────────────────────────────────────────────

function _epUpdateDisplay() {
  const numEl   = document.getElementById("ep-frame-num");
  const totalEl = document.getElementById("ep-frame-total");
  const seekEl  = document.getElementById("ep-seek");
  if (numEl)   numEl.textContent   = _currentFrame + 1;
  if (totalEl) totalEl.textContent = _frameCount;
  if (seekEl)  seekEl.value        = _currentFrame;
  _epDrawCursor(document.getElementById("ep-status-cursor"));
  _epDrawCursor(document.getElementById("ep-note-cursor"));
}

// ── Playback ──────────────────────────────────────────────────────────────────

async function _epLoop() {
  if (!_playing) return;
  if (_busy) { _timerId = setTimeout(_epLoop, Math.round(1000 / _EP_FPS)); return; }
  let next = _currentFrame + _playDir;
  if (next >= _frameCount) next = 0;
  if (next < 0) next = _frameCount - 1;
  const t0 = performance.now();
  await _epLoadFrame(next);
  if (!_playing) return;
  const delay = Math.max(0, Math.round(1000 / _EP_FPS) - (performance.now() - t0));
  _timerId = setTimeout(_epLoop, delay);
}

function _stop() {
  if (_timerId !== null) { clearTimeout(_timerId); _timerId = null; }
  _playing = false;
  _busy    = false;
  const playBtn = document.getElementById("ep-play");
  if (playBtn) playBtn.textContent = "▶";
}

function _setStatus(msg) {
  const el = document.getElementById("extract-status");
  if (el) el.textContent = msg;
}

function _epWireCanvasClick(canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.addEventListener("click", (e) => {
    if (_frameCount <= 1) return;
    const rect = canvas.getBoundingClientRect();
    const x    = e.clientX - rect.left;
    const frac = Math.max(0, Math.min(1, x / rect.width));
    const target = Math.round(frac * (_frameCount - 1));
    _stop(); _epLoadFrame(target);
  });
}

// ── Event wiring (runs once DOM is ready) ─────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  let _resizeRaf = null;
  window.addEventListener("resize", () => {
    if (_resizeRaf) cancelAnimationFrame(_resizeRaf);
    _resizeRaf = requestAnimationFrame(() => {
      _epRedrawAllCanvases();
      _resizeRaf = null;
    });
  });

  // Chip prev/next navigation
  ["ep-status-prev", "ep-note-prev"].forEach(id => {
    document.getElementById(id)?.addEventListener("click", () => _epNavByChip(-1));
  });
  ["ep-status-next", "ep-note-next"].forEach(id => {
    document.getElementById(id)?.addEventListener("click", () => _epNavByChip(+1));
  });

  // Canvas click → jump to frame
  _epWireCanvasClick("ep-status-canvas");
  _epWireCanvasClick("ep-note-canvas");

  // Seek bar
  document.getElementById("ep-seek")?.addEventListener("input", (e) => {
    _stop();
    _epLoadFrame(parseInt(e.target.value, 10));
  });

  // Play
  document.getElementById("ep-play")?.addEventListener("click", () => {
    if (!_videoPath) return;
    if (_playing) {
      _stop();
    } else {
      _playing = true;
      document.getElementById("ep-play").textContent = "⏸";
      _epLoop();
    }
  });

  // Step back / forward
  document.getElementById("ep-step-back")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    const s = parseInt(document.getElementById("ep-step")?.value || "10", 10);
    _epLoadFrame(_currentFrame - s);
  });
  document.getElementById("ep-step-fwd")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop();
    const s = parseInt(document.getElementById("ep-step")?.value || "10", 10);
    _epLoadFrame(_currentFrame + s);
  });

  // Skip to start / end
  document.getElementById("ep-skip-start")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop(); _epLoadFrame(0);
  });
  document.getElementById("ep-skip-end")?.addEventListener("click", () => {
    if (!_videoPath) return;
    _stop(); _epLoadFrame(_frameCount - 1);
  });

  // Sync cam checkbox
  document.getElementById("ep-sync-cam")?.addEventListener("change", (e) => {
    _syncCamEnabled = e.target.checked;
    _epUpdateSyncCamUI();
    if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
  });

  // Step size input — sync to module var
  document.getElementById("ep-step")?.addEventListener("change", (e) => {
    _stepSize = Math.max(1, parseInt(e.target.value, 10) || 10);
  });

  // Zoom slider
  document.getElementById("ep-zoom-3d")?.addEventListener("input", (e) => {
    const v       = parseInt(e.target.value, 10);
    const camDisp = document.getElementById("cam-displays");
    const pct     = document.getElementById("ep-zoom-3d-pct");
    if (camDisp) {
      camDisp.style.width      = v === 100 ? "" : `${v}%`;
      camDisp.style.marginLeft = v === 100 ? "" : `${(100 - v) / 2}%`;
    }
    if (pct) pct.textContent = `${v}%`;
  });

  // Keyboard shortcuts (hover-free — active whenever no text input focused)
  document.addEventListener("keydown", (e) => {
    if (!_videoPath) return;
    const tag = (e.target || {}).tagName || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

    if (e.key === " " && !e.shiftKey) {
      e.preventDefault();
      if (_playing) { _stop(); }
      else { _playing = true; document.getElementById("ep-play").textContent = "⏸"; _epLoop(); }
    } else if (e.key === "ArrowRight" && e.shiftKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + 1);
    } else if (e.key === "ArrowLeft" && e.shiftKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - 1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + _stepSize);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - _stepSize);
    }
  });
});
