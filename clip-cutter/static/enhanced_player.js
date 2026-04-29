// enhanced_player.js — unified video player for clip mode and template mode.
// Public API: openPlayer(config) — all other symbols are module-private.

const _EP_FPS = 15;

// ── State ──────────────────────────────────────────────────────────────────────
let _mode = null;          // "template" | "clip"
let _videoPath = null;
let _frameCount = 0;
let _currentFrame = 0;     // 0-based
let _clipStart = 0;        // 0-based
let _clipEnd = 0;          // 0-based
let _keyFrame = 0;         // 0-based
let _detectionIdx = null;
let _csvRows = [];
let _stepSize = 10;
let _playN = 1;
let _playDir = 1;          // 1 = forward, -1 = backward
let _activePresetIdx = null;
let _playing = false;
let _looping = true;
let _busy = false;
let _timerId = null;
const _videoInfoCache = {};

const _EP_TAG_COLORS = ["#58a6ff","#3fb950","#f0c040","#f85149","#d2a8ff","#ffa657","#79c0ff","#56d364"];
let _epStatusColorMap = {};
let _epNoteColorMap   = {};
let _epActiveStatus   = new Set();
let _epActiveNote     = new Set();
let _epActiveChip     = null;  // { type: "status"|"note", val: string } | null for nav
let _kfCanvasVisible = false;
let _unlocked = false;
let _syncCamEnabled = false;
let _siblingVideoPath = null;
let _rescanJobId = null;
let _rescanEs = null;

// Postfix tags — persistent via localStorage
let _epPostfixTags = [];
let _epActivePostfixTag = null;
const _EP_POSTFIX_TAGS_KEY = "clip_cutter_postfix_tags";

// ── Public API ──────────────────────────────────────────────────────────────────

function getVideoPath() { return _videoPath; }

// Switch to a different detection on the SAME already-loaded video.
// Preserves step size, loop, presets, play direction, active chip, and tag bars.
async function epSwitchDetection({ detectionIdx, keyFrame1Based }) {
  _stop();
  _detectionIdx = detectionIdx;

  const kf0 = keyFrame1Based - 1;
  _keyFrame = kf0;
  _clipStart = Math.max(0, kf0 - 200);
  _clipEnd = Math.min(_frameCount - 1, kf0 + 599);
  _unlocked = false;

  _epInitExtractPanel(_videoPath, keyFrame1Based);
  _epUpdateModeUI();

  // Navigate to the new detection's keyframe
  await _epLoadFrame(_keyFrame);
}

async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null }) {
  _stop();
  _mode = mode;
  _videoPath = videoPath;
  _detectionIdx = detectionIdx;
  _csvRows = [];
  _stepSize = 10;
  _playN = 1;
  _playDir = 1;
  _activePresetIdx = null;
  _looping = true;
  const stepEl = document.getElementById("ep-step");
  const playNEl = document.getElementById("ep-playn");
  if (stepEl) stepEl.value = 10;
  if (playNEl) playNEl.value = 1;
  document.querySelectorAll(".ep-step-preset").forEach(el => el.classList.remove("active"));

  _kfCanvasVisible = false;
  _unlocked = false;
  _epActiveChip = null;
  _epActivePostfixTag = null;
  _epRenderPostfixTags();
  // Sub-rows are cleared inside _epBuildTagBars when a new video loads

  // Show panel immediately so user sees it open without waiting for network
  document.getElementById("player-panel").style.display = "";
  document.getElementById("ep-frame").src = "";
  _epSyncResultsPadding();

  // Fetch frame count — use cache to skip round-trip on repeated opens
  let frameCount;
  if (_videoInfoCache[videoPath] !== undefined) {
    frameCount = _videoInfoCache[videoPath];
  } else {
    let info;
    try {
      const resp = await fetch(`/clip-cutter/video-info?video=${encodeURIComponent(videoPath)}`);
      if (!resp.ok) { setStatus("Cannot load video info"); return; }
      info = await resp.json();
    } catch (e) { setStatus("Network error: " + e.message); return; }
    frameCount = info.frame_count;
    _videoInfoCache[videoPath] = frameCount;
  }
  _frameCount = frameCount;

  if (mode === "clip" && keyFrame1Based !== null) {
    const kf0 = keyFrame1Based - 1;
    _keyFrame = kf0;
    _clipStart = Math.max(0, kf0 - 200);
    _clipEnd = Math.min(_frameCount - 1, kf0 + 599);
  } else {
    _keyFrame = 0;
    _clipStart = 0;
    _clipEnd = _frameCount - 1;
  }
  _currentFrame = _clipStart;

  _epInitExtractPanel(videoPath, keyFrame1Based);
  _epUpdateModeUI();

  if (csvPath) {
    try {
      const r = await fetch(`/clip-cutter/csv?path=${encodeURIComponent(csvPath)}`);
      if (r.ok) _csvRows = (await r.json()).rows;
    } catch (e) {
      console.warn("[enhanced_player] CSV load failed:", e);
    }
  }

  // Fetch sibling camera path (computed server-side at select-video time)
  _syncCamEnabled = false;
  _siblingVideoPath = null;
  try {
    const sr = await fetch("/clip-cutter/sibling-camera");
    if (sr.ok) {
      const sd = await sr.json();
      _siblingVideoPath = sd.sibling_video_path || null;
    }
  } catch (e) { console.warn("[enhanced_player] sibling-camera fetch failed:", e); }
  _epUpdateSyncCamUI();

  _epBuildTagBars();

  await _epLoadFrame(_clipStart);

  document.getElementById("ep-kf-toggle").classList.toggle("active", _kfCanvasVisible);
  if (_kfCanvasVisible) {
    document.getElementById("ep-kf-canvas").style.display = "block";
    _epDrawKfCanvas();
  } else {
    document.getElementById("ep-kf-canvas").style.display = "none";
  }
}

// ── Frame loading ──────────────────────────────────────────────────────────────

async function _epLoadFrame(n) {
  if (_busy || !_videoPath) return;
  _busy = true;
  n = _unlocked
    ? Math.max(0, Math.min(n, _frameCount - 1))
    : Math.max(_clipStart, Math.min(n, _clipEnd));
  const prev = _currentFrame;
  _currentFrame = n;
  try {
    const resp = await fetch(`/clip-cutter/frame?video=${encodeURIComponent(_videoPath)}&n=${n}`);
    if (!resp.ok) { _currentFrame = prev; return; }
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img = document.getElementById("ep-frame");
    const prevSrc = img.src;
    try {
      await new Promise((resolve, reject) => {
        img.onload = () => { if (prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); resolve(); };
        img.onerror = () => reject(new Error(`Frame load failed: ${blobUrl}`));
        img.src = blobUrl;
      });
    } catch (err) {
      console.warn("[enhanced_player] frame load error:", err.message);
      return;
    }
    _epUpdateDisplay();
    const _ac = document.getElementById("ep-add-confirm");
    if (_ac) _ac.style.display = "none";
    _epLoadCam2Frame(n);   // non-blocking parallel fetch for second camera
    if (n < (_unlocked ? _frameCount - 1 : _clipEnd)) {
      new Image().src = `/clip-cutter/frame?video=${encodeURIComponent(_videoPath)}&n=${n + 1}`;
    }
  } finally {
    _busy = false;
  }
}

// ── Playback loop ──────────────────────────────────────────────────────────────

async function _epLoop() {
  if (!_playing) return;
  if (_busy) { _timerId = setTimeout(_epLoop, Math.round(1000 / _EP_FPS)); return; }

  const lo = _unlocked ? 0 : _clipStart;
  const hi = _unlocked ? _frameCount - 1 : _clipEnd;
  let next = _currentFrame + _playN * _playDir;

  if (_playDir > 0 && next > hi) {
    if (_looping) next = lo; else { _stop(); return; }
  } else if (_playDir < 0 && next < lo) {
    if (_looping) next = hi; else { _stop(); return; }
  }

  const t0 = performance.now();
  await _epLoadFrame(next);
  if (!_playing) return;
  const delay = Math.max(0, Math.round(1000 / _EP_FPS) - (performance.now() - t0));
  _timerId = setTimeout(_epLoop, delay);
}

function _stop() {
  if (_timerId !== null) { clearTimeout(_timerId); _timerId = null; }
  _playing = false;
  const fwd = document.getElementById("ep-play");
  const bwd = document.getElementById("ep-play-back");
  if (fwd) fwd.textContent = "▶";
  if (bwd) bwd.textContent = "◀";
  _epRedrawAllCanvases();
}

function _epUpdateSyncCamUI() {
  const label = document.getElementById("ep-sync-cam-label");
  const cb    = document.getElementById("ep-sync-cam");
  const cam2  = document.getElementById("ep-cam2-wrap");
  if (!label || !cb || !cam2) return;
  if (!_siblingVideoPath) {
    label.style.display = "none";
    cb.checked = false;
    _syncCamEnabled = false;
    cam2.style.display = "none";
    return;
  }
  label.style.display = "";
  cb.checked = _syncCamEnabled;
  cam2.style.display = _syncCamEnabled ? "flex" : "none";
}

async function _epLoadCam2Frame(n) {
  if (!_syncCamEnabled || !_siblingVideoPath) return;
  try {
    const resp = await fetch(`/clip-cutter/frame?video=${encodeURIComponent(_siblingVideoPath)}&n=${n}`);
    if (!resp.ok) return;
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img = document.getElementById("ep-cam2-frame");
    const prevSrc = img.src;
    img.onload  = () => { if (prevSrc && prevSrc.startsWith("blob:")) URL.revokeObjectURL(prevSrc); };
    img.onerror = () => { URL.revokeObjectURL(blobUrl); };
    img.src = blobUrl;
  } catch (e) {
    console.warn("[enhanced_player] cam2 frame load error:", e.message);
  }
}

// ── Display ────────────────────────────────────────────────────────────────────

function _epUpdateDisplay() {
  const cur1 = _currentFrame + 1;
  document.getElementById("ep-frame-num").textContent = cur1;
  document.getElementById("ep-frame-total").textContent = _frameCount;

  const seekEl = document.getElementById("ep-seek");
  seekEl.value = _currentFrame;

  _epUpdateSeekHighlight();
  _epUpdateCsvStrip();

  if (!_playing && !document.getElementById("ep-lock-start").checked) {
    document.getElementById("ep-start").value = cur1;
    _epUpdateEnd();
  }
  if (!_playing) _epRedrawAllCanvases();
}

function _epUpdateLockOverlay() {
  const overlay = document.getElementById("ep-lock-overlay");
  if (!overlay) return;
  if (!_unlocked || _mode !== "clip" || _frameCount <= 1) {
    overlay.style.display = "none";
    return;
  }
  overlay.style.display = "";
  const total = _frameCount - 1;
  const left = (_clipStart / total) * 100;
  const width = ((_clipEnd - _clipStart) / total) * 100;
  overlay.style.left = left + "%";
  overlay.style.width = width + "%";
}

function _epUpdateSeekHighlight() {
  const h = document.getElementById("ep-seek-highlight");
  if (!h) return;
  if (_mode !== "clip" || _frameCount <= 1 || _unlocked) { h.style.display = "none"; return; }
  h.style.display = "";
  const total = _frameCount - 1;
  const left = (_clipStart / total) * 100;
  const width = ((_clipEnd - _clipStart) / total) * 100;
  h.style.left = left + "%";
  h.style.width = width + "%";
}

function _epUpdateCsvStrip() {
  const statusBadge = document.getElementById("ep-status-badge");
  const noteBadge = document.getElementById("ep-note-badge");
  if (!statusBadge && !noteBadge) return;
  const cur1 = _currentFrame + 1;
  const row = _csvRows.find(r => r.frame_number === cur1);
  if (row) {
    if (statusBadge) statusBadge.textContent = row.frame_line_status || "—";
    if (noteBadge) noteBadge.textContent = row.note || "—";
  } else {
    if (statusBadge) statusBadge.textContent = "—";
    if (noteBadge) noteBadge.textContent = "—";
  }
}

function _epUpdateEnd() {
  const start = parseInt(document.getElementById("ep-start").value, 10) || 1;
  const frames = parseInt(document.getElementById("ep-frames").value, 10) || 800;
  document.getElementById("ep-end").value = start + frames - 1;
}

// ── Tag timeline canvases ──────────────────────────────────────────────────────

function _epDrawTagCanvas(canvas, rows, field, activeSet, colorMap) {
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

function _epDrawCanvasCursor(canvas) {
  if (!canvas || !_frameCount) return;
  const W = canvas.width;
  if (!W) return;
  const ctx = canvas.getContext("2d");
  const x = Math.round((_currentFrame / Math.max(_frameCount - 1, 1)) * W);
  ctx.save();
  ctx.globalAlpha = 0.8;
  ctx.fillStyle = "#fff";
  ctx.fillRect(x, 0, 1, canvas.height);
  ctx.restore();
}

function _epDrawCursorTriangle(cursorCanvas, mainCanvas) {
  if (!cursorCanvas || !_frameCount) return;
  const cursorRect = cursorCanvas.getBoundingClientRect();
  const W = Math.round(cursorRect.width) || cursorCanvas.clientWidth || 600;
  cursorCanvas.width = W;
  const H = cursorCanvas.height;
  const ctx = cursorCanvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  let x;
  if (mainCanvas) {
    const mainRect = mainCanvas.getBoundingClientRect();
    const leftOffset = mainRect.left - cursorRect.left;
    const mainW = mainRect.width || (W - leftOffset);
    x = Math.round(leftOffset + (_currentFrame / Math.max(_frameCount - 1, 1)) * mainW);
  } else {
    x = Math.round((_currentFrame / Math.max(_frameCount - 1, 1)) * W);
  }
  ctx.fillStyle = "#e6edf3";
  ctx.beginPath();
  ctx.moveTo(x - 4, 0);
  ctx.lineTo(x + 4, 0);
  ctx.lineTo(x, H);
  ctx.closePath();
  ctx.fill();
}

function _epRedrawStatusCanvas() {
  const canvas = document.getElementById("ep-status-canvas");
  if (!canvas || document.getElementById("ep-status-bar-wrap").style.display === "none") return;
  _epDrawTagCanvas(canvas, _csvRows, "frame_line_status", _epActiveStatus, _epStatusColorMap);
  _epDrawCanvasCursor(canvas);
  _epDrawCursorTriangle(document.getElementById("ep-status-cursor"), canvas);
}

function _epRedrawNoteCanvas() {
  const canvas = document.getElementById("ep-note-canvas");
  if (!canvas || document.getElementById("ep-note-bar-wrap").style.display === "none") return;
  _epDrawTagCanvas(canvas, _csvRows, "note", _epActiveNote, _epNoteColorMap);
  _epDrawCanvasCursor(canvas);
  _epDrawCursorTriangle(document.getElementById("ep-note-cursor"), canvas);
}

function _epRedrawAllCanvases() {
  _epRedrawStatusCanvas();
  _epRedrawNoteCanvas();
  _epRedrawSubRows("ep-status-sub-rows", "frame_line_status", _epStatusColorMap);
  _epRedrawSubRows("ep-note-sub-rows",   "note",              _epNoteColorMap);
}

function _epRedrawSubRows(containerId, field, colorMap) {
  document.querySelectorAll(`#${containerId} .ep-sub-row`).forEach(row => {
    const canvas = row.querySelector("canvas");
    if (canvas) _epDrawSubCanvas(canvas, _csvRows, field, row._activeChips || new Set(), colorMap);
  });
}

function _epDrawSubCanvas(canvas, rows, field, chipSet, colorMap) {
  if (!canvas) return;
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 8;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  if (chipSet && chipSet.size > 0) {
    const total = Math.max(_frameCount, 1);
    const minW = Math.max(1, Math.round(W / total));
    rows.forEach(row => {
      const v = row[field];
      if (!v || !chipSet.has(v)) return;
      if (field === "frame_line_status" && v === "0") return;
      ctx.fillStyle = colorMap[v] || "#888";
      const x = Math.round(((row.frame_number - 1) / Math.max(total - 1, 1)) * W);
      ctx.fillRect(x, 0, minW, H);
    });
  }
  _epDrawCanvasCursor(canvas);
}


function _epRenderStatusChips() {
  const container = document.getElementById("ep-status-chips");
  if (!container) return;
  container.innerHTML = "";
  const mainChecked = document.getElementById("ep-status-main-radio")?.checked;
  const selSubRow = mainChecked
    ? null
    : document.querySelector("#ep-status-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
  const activeSet = mainChecked ? _epActiveStatus : (selSubRow?._activeChips ?? new Set());
  Object.keys(_epStatusColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (activeSet.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epStatusColorMap[val]);
    chip.addEventListener("click", () => {
      const isMain = document.getElementById("ep-status-main-radio")?.checked;
      if (isMain) {
        if (_epActiveStatus.has(val)) {
          _epActiveStatus.delete(val);
          if (!_epActiveStatus.size) _epActiveChip = null;
        } else {
          _epActiveStatus.add(val);
          _epActiveChip = { type: "status", val };
        }
        _epRedrawStatusCanvas();
      } else {
        let row = document.querySelector("#ep-status-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
        if (!row) {
          _epAddSubRow("ep-status-sub-rows", "frame_line_status");
          row = document.querySelector("#ep-status-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
        }
        if (!row) return;
        if (row._activeChips.has(val)) {
          row._activeChips.delete(val);
          if (!row._activeChips.size) _epActiveChip = null;
        } else {
          row._activeChips.add(val);
          _epActiveChip = { type: "status", val };
        }
        const canvas = row.querySelector("canvas");
        if (canvas) _epDrawSubCanvas(canvas, _csvRows, "frame_line_status", row._activeChips, _epStatusColorMap);
      }
      _epRenderStatusChips();
      _epUpdateNavButtons();
    });
    container.appendChild(chip);
  });
}

function _epRenderNoteChips() {
  const container = document.getElementById("ep-note-chips");
  if (!container) return;
  container.innerHTML = "";
  const mainChecked = document.getElementById("ep-note-main-radio")?.checked;
  const selSubRow = mainChecked
    ? null
    : document.querySelector("#ep-note-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
  const activeSet = mainChecked ? _epActiveNote : (selSubRow?._activeChips ?? new Set());
  Object.keys(_epNoteColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (activeSet.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epNoteColorMap[val]);
    chip.addEventListener("click", () => {
      const isMain = document.getElementById("ep-note-main-radio")?.checked;
      if (isMain) {
        if (_epActiveNote.has(val)) {
          _epActiveNote.delete(val);
          if (!_epActiveNote.size) _epActiveChip = null;
        } else {
          _epActiveNote.add(val);
          _epActiveChip = { type: "note", val };
        }
        _epRedrawNoteCanvas();
      } else {
        let row = document.querySelector("#ep-note-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
        if (!row) {
          _epAddSubRow("ep-note-sub-rows", "note");
          row = document.querySelector("#ep-note-sub-rows .ep-sub-radio:checked")?.closest(".ep-sub-row");
        }
        if (!row) return;
        if (row._activeChips.has(val)) {
          row._activeChips.delete(val);
          if (!row._activeChips.size) _epActiveChip = null;
        } else {
          row._activeChips.add(val);
          _epActiveChip = { type: "note", val };
        }
        const canvas = row.querySelector("canvas");
        if (canvas) _epDrawSubCanvas(canvas, _csvRows, "note", row._activeChips, _epNoteColorMap);
      }
      _epRenderNoteChips();
      _epUpdateNavButtons();
    });
    container.appendChild(chip);
  });
}

function _epAddSubRow(containerId, field) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const barType  = containerId.includes("status") ? "status" : "note";
  const radioName = `ep-${barType}-sub-radio`;

  const row = document.createElement("div");
  row.className = "ep-sub-row";
  row._activeChips = new Set();

  const radio = document.createElement("input");
  radio.type = "radio";
  radio.name = radioName;
  radio.className = "ep-sub-radio";
  radio.style.cssText = "accent-color:#388bfd;cursor:pointer;flex-shrink:0;";
  radio.addEventListener("change", () => {
    const lastChip = [...(row._activeChips || [])].at(-1) || null;
    _epActiveChip = lastChip ? { type: barType, val: lastChip } : null;
    if (barType === "status") _epRenderStatusChips(); else _epRenderNoteChips();
    _epUpdateNavButtons();
  });

  const canvas = document.createElement("canvas");
  canvas.height = 8;
  canvas.addEventListener("click", e => {
    if (!row._activeChips.size) return;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r[field]; return v && row._activeChips.has(v) && (field !== "frame_line_status" || v !== "0"); })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });

  const removeBtn = document.createElement("button");
  removeBtn.className = "player-btn ep-sub-remove";
  removeBtn.textContent = "×";
  removeBtn.addEventListener("click", () => {
    const wasChecked = radio.checked;
    row.remove();
    if (wasChecked) {
      const mainRadioId = barType === "status" ? "ep-status-main-radio" : "ep-note-main-radio";
      const mainRadio = document.getElementById(mainRadioId);
      if (mainRadio) mainRadio.checked = true;
      const lastChip = [...(barType === "status" ? _epActiveStatus : _epActiveNote)].at(-1) || null;
      _epActiveChip = lastChip ? { type: barType, val: lastChip } : null;
      if (barType === "status") _epRenderStatusChips(); else _epRenderNoteChips();
      _epUpdateNavButtons();
    }
  });

  row.appendChild(radio);
  row.appendChild(canvas);
  row.appendChild(removeBtn);
  container.appendChild(row);

  radio.checked = true;
  _epActiveChip = null;
  if (barType === "status") _epRenderStatusChips(); else _epRenderNoteChips();
  _epUpdateNavButtons();
}

function _epBuildTagBars() {
  const hasStatus = _csvRows.some(r => r.frame_line_status && r.frame_line_status !== "0");
  const hasNote   = _csvRows.some(r => r.note);

  document.getElementById("ep-status-bar-wrap").style.display = hasStatus ? "" : "none";
  document.getElementById("ep-note-bar-wrap").style.display   = hasNote   ? "" : "none";

  // Clear sub-rows from previous video
  document.getElementById("ep-status-sub-rows").innerHTML = "";
  document.getElementById("ep-note-sub-rows").innerHTML   = "";

  const statusVals = [...new Set(_csvRows.map(r => r.frame_line_status).filter(v => v && v !== "0"))];
  _epStatusColorMap = {};
  _epActiveStatus   = new Set();
  statusVals.forEach((v, i) => { _epStatusColorMap[v] = _EP_TAG_COLORS[i % _EP_TAG_COLORS.length]; });
  _epRenderStatusChips();

  const noteVals = [...new Set(_csvRows.map(r => r.note).filter(v => v))];
  _epNoteColorMap = {};
  _epActiveNote   = new Set();
  noteVals.forEach((v, i) => { _epNoteColorMap[v] = _EP_TAG_COLORS[i % _EP_TAG_COLORS.length]; });
  _epRenderNoteChips();

  const srMain = document.getElementById("ep-status-main-radio");
  if (srMain) {
    srMain.checked = true;
    srMain.addEventListener("change", () => {
      const lastChip = [..._epActiveStatus].at(-1) || null;
      _epActiveChip = lastChip ? { type: "status", val: lastChip } : null;
      _epRenderStatusChips();
      _epUpdateNavButtons();
    });
  }
  const nrMain = document.getElementById("ep-note-main-radio");
  if (nrMain) {
    nrMain.checked = true;
    nrMain.addEventListener("change", () => {
      const lastChip = [..._epActiveNote].at(-1) || null;
      _epActiveChip = lastChip ? { type: "note", val: lastChip } : null;
      _epRenderNoteChips();
      _epUpdateNavButtons();
    });
  }
  _epActiveChip = null;
  _epUpdateNavButtons();
  requestAnimationFrame(() => _epRedrawAllCanvases());
}

// ── Nav button state ───────────────────────────────────────────────────────────

function _epUpdateNavButtons() {
  const any  = _epActiveChip !== null;
  const stat = any && _epActiveChip.type === "status";
  const note = any && _epActiveChip.type === "note";
  document.getElementById("ep-status-prev").disabled = !stat;
  document.getElementById("ep-status-next").disabled = !stat;
  document.getElementById("ep-note-prev").disabled   = !note;
  document.getElementById("ep-note-next").disabled   = !note;
}

function _epNavByChip(dir) {
  if (!_epActiveChip || !_csvRows.length) return;
  const { type, val } = _epActiveChip;
  const field = type === "status" ? "frame_line_status" : "note";
  const cur1  = _currentFrame + 1;
  const rows  = _csvRows.filter(r => {
    const v = r[field];
    return v && (field !== "frame_line_status" || v !== "0") && v === val;
  });
  if (dir < 0) {
    const prev = [...rows].filter(r => Number(r.frame_number) < cur1)
      .sort((a, b) => b.frame_number - a.frame_number)[0];
    if (prev) { _stop(); _epLoadFrame(Number(prev.frame_number) - 1); }
  } else {
    const next = rows.filter(r => Number(r.frame_number) > cur1)
      .sort((a, b) => a.frame_number - b.frame_number)[0];
    if (next) { _stop(); _epLoadFrame(Number(next.frame_number) - 1); }
  }
}

// ── Postfix tags ───────────────────────────────────────────────────────────────

function _epLoadPostfixTags() {
  try {
    const saved = localStorage.getItem(_EP_POSTFIX_TAGS_KEY);
    _epPostfixTags = saved ? JSON.parse(saved) : [];
  } catch { _epPostfixTags = []; }
}

function _epSavePostfixTags() {
  localStorage.setItem(_EP_POSTFIX_TAGS_KEY, JSON.stringify(_epPostfixTags));
}

function _epRenderPostfixTags() {
  const container = document.getElementById("ep-postfix-tags");
  if (!container) return;
  container.innerHTML = "";
  _epPostfixTags.forEach((tag, idx) => {
    const pill = document.createElement("span");
    pill.className = "ep-postfix-tag" + (_epActivePostfixTag === tag ? " active" : "");
    const label = document.createElement("span");
    label.textContent = tag;
    const del = document.createElement("span");
    del.className = "ep-tag-del";
    del.textContent = "×";
    del.title = "Remove tag";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      _epPostfixTags.splice(idx, 1);
      if (_epActivePostfixTag === tag) {
        _epActivePostfixTag = null;
        document.getElementById("ep-postfix").value = "";
      }
      _epSavePostfixTags();
      _epRenderPostfixTags();
    });
    pill.appendChild(label);
    pill.appendChild(del);
    pill.addEventListener("click", () => {
      if (_epActivePostfixTag === tag) {
        _epActivePostfixTag = null;
        document.getElementById("ep-postfix").value = "";
      } else {
        _epActivePostfixTag = tag;
        document.getElementById("ep-postfix").value = tag;
      }
      _epRenderPostfixTags();
    });
    container.appendChild(pill);
  });
}

// ── Keyframe canvas overlay ────────────────────────────────────────────────────

function _epAllKfFrames() {
  if (typeof detections === "undefined") return [];
  return detections
    .filter(d => d.video_path === _videoPath && d.frame_number != null)
    .map(d => d.frame_number - 1)
    .sort((a, b) => a - b);
}

function _epDrawKfCanvas() {
  const canvas = document.getElementById("ep-kf-canvas");
  if (!canvas || !_kfCanvasVisible || !_frameCount) return;
  const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = W;
  const H = canvas.height || 8;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  const total = Math.max(_frameCount - 1, 1);
  if (typeof detections === "undefined") return;
  detections.forEach((d, i) => {
    if (d.video_path !== _videoPath || d.frame_number == null) return;
    const kf0 = d.frame_number - 1;
    const x = Math.round((kf0 / total) * W);
    if (i === _detectionIdx) {
      ctx.fillStyle = "#56d4db"; // current clip: cyan, 2px wide
      ctx.fillRect(x, 0, 2, H);
    } else {
      ctx.fillStyle = "#f0c040"; // other clips: yellow, 1px wide
      ctx.fillRect(x, 0, 1, H);
    }
  });
}

// ── Mode-specific UI ───────────────────────────────────────────────────────────

function _epUpdateModeUI() {
  const lockBadge = document.getElementById("ep-lock-badge");
  const setKfBtn = document.getElementById("ep-set-kf");
  const rejectBtn = document.getElementById("ep-reject");
  const addTemplateBtn = document.getElementById("ep-add-template");
  const gotoKfBtn = document.getElementById("ep-goto-kf");
  const seekEl = document.getElementById("ep-seek");

  seekEl.min = 0;
  seekEl.max = _frameCount - 1;

  if (_mode === "clip") {
    lockBadge.style.display = "";
    lockBadge.className = _unlocked ? "unlocked" : "locked";
    lockBadge.textContent = _unlocked
      ? "🔓 " + (_clipStart + 1) + "–" + (_clipEnd + 1)
      : "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);
    setKfBtn.style.display = "";
    rejectBtn.style.display = "";
    addTemplateBtn.style.display = "none";
    gotoKfBtn.style.display = "";
    document.getElementById("ep-lock-start").checked = true;

    const isFinished = _detectionIdx !== null &&
      typeof detections !== "undefined" &&
      detections[_detectionIdx] &&
      (detections[_detectionIdx].status === "kept" || detections[_detectionIdx].status === "rejected");
    setKfBtn.disabled = isFinished;
    rejectBtn.disabled = isFinished;
    document.getElementById("ep-extract").disabled = isFinished;

    const propagateRow = document.getElementById("ep-propagate-row");
    if (propagateRow) propagateRow.style.display = "flex";
  } else {
    lockBadge.style.display = "none";
    setKfBtn.style.display = "none";
    rejectBtn.style.display = "none";
    addTemplateBtn.style.display = "";
    gotoKfBtn.style.display = "none";
    document.getElementById("ep-lock-start").checked = false;
    document.getElementById("ep-extract").disabled = false;

    const propagateRow = document.getElementById("ep-propagate-row");
    if (propagateRow) propagateRow.style.display = "none";
  }

  _epUpdateSeekHighlight();
  _epUpdateLockOverlay();
}

// ── Extract panel init ─────────────────────────────────────────────────────────

function _epInitExtractPanel(videoPath, keyFrame1Based) {
  const start = (_mode === "clip" && keyFrame1Based !== null)
    ? Math.max(1, keyFrame1Based - 200)
    : 1;
  document.getElementById("ep-start").value = start;
  document.getElementById("ep-frames").value = 800;
  const _storedPostfix = (_detectionIdx !== null && typeof detections !== "undefined")
    ? (detections[_detectionIdx]?.extract_postfix || "")
    : "";
  document.getElementById("ep-postfix").value = _storedPostfix;
  document.getElementById("ep-warning").style.display = "none";
  _epUpdateEnd();

  // Show extract button or rename/delete buttons based on detection state
  const isKept = _mode === "clip" && _detectionIdx !== null &&
    typeof detections !== "undefined" && detections[_detectionIdx]?.status === "kept";
  const hasPath = isKept && !!detections[_detectionIdx]?.extract_avi_path;
  document.getElementById("ep-extract").style.display = isKept ? "none" : "";
  document.getElementById("ep-rename-extract").style.display = isKept ? "" : "none";
  document.getElementById("ep-rename-extract").disabled = !hasPath;
  document.getElementById("ep-delete-extract").style.display = isKept ? "" : "none";

  const parts = videoPath.split("/");
  const filename = parts[parts.length - 1];
  const stem = filename.replace(/\.avi$/i, "");
  const parentName = parts[parts.length - 2] || "";
  const parent = parts.slice(0, -1).join("/");
  document.getElementById("ep-outdir").textContent = "…/" + parentName + "/" + stem + "/";
  document.getElementById("ep-outdir").title = parent + "/" + stem + "/";
}

// ── Apply new keyframe ─────────────────────────────────────────────────────────

async function _epApplyNewKF(kf1) {
  if (_detectionIdx === null || typeof detections === "undefined") return;
  detections[_detectionIdx].frame_number = kf1;
  const kf0 = kf1 - 1;
  _keyFrame = kf0;
  _clipStart = Math.max(0, kf0 - 200);
  _clipEnd = Math.min(_frameCount - 1, kf0 + 599);

  _unlocked = false;
  const badge = document.getElementById("ep-lock-badge");
  badge.className = "locked";
  badge.textContent = "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);

  const seekEl = document.getElementById("ep-seek");
  seekEl.min = 0;
  seekEl.max = _frameCount - 1;
  seekEl.value = Math.max(_clipStart, Math.min(_currentFrame, _clipEnd));

  const start = Math.max(1, kf1 - 200);
  document.getElementById("ep-start").value = start;
  _epUpdateEnd();

  const nameEl = document.getElementById("card-clipname-" + _detectionIdx);
  if (nameEl) {
    const d = detections[_detectionIdx];
    const videoName = d.video_path.split("/").pop().replace(/\.avi$/i, "");
    nameEl.textContent = videoName + "_" + (kf1 - 200) + "_" + (kf1 + 599) + ".avi";
  }

  _epUpdateSeekHighlight();
  _epUpdateLockOverlay();
  if (typeof saveDetections === "function") saveDetections();
  document.getElementById("ep-warning").style.display = "none";
  _epDrawKfCanvas();

  // Enrich template with new keyframe before rescanning
  if (document.getElementById("ep-propagate-kf")?.checked) {
    try {
      await fetch("/clip-cutter/template/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _videoPath, frame_number: kf1 }),
      });
    } catch { /* non-fatal */ }
  }
  _epStartRescan(_detectionIdx);
}

function _epApplyRescanKF(idx, newFrame1Based) {
  if (typeof detections === "undefined" || !detections[idx]) return;
  const d = detections[idx];
  if (_detectionIdx === idx) return;  // user is on this candidate — discard
  if (d.status === "kept" || d.status === "rejected") return;  // already processed

  d.frame_number = newFrame1Based;
  const nameEl = document.getElementById("card-clipname-" + idx);
  if (nameEl) {
    const videoName = d.video_path.split("/").pop().replace(/\.avi$/i, "");
    const postfixSuffix = d.extract_postfix ? `_${d.extract_postfix}` : "";
    nameEl.textContent =
      videoName + "_" + (newFrame1Based - 200) + "_" + (newFrame1Based + 599) + postfixSuffix + ".avi";
  }
  if (_kfCanvasVisible) _epDrawKfCanvas();
  if (typeof saveDetections === "function") saveDetections();
}

async function _epStartRescan(detectionIdx) {
  if (!document.getElementById("ep-propagate-kf")?.checked) return;

  const candidates = [];
  for (let i = detectionIdx + 3; i < detections.length; i++) {
    const d = detections[i];
    if (!d || d.video_path !== _videoPath) continue;
    if (d.status === "kept" || d.status === "rejected") continue;
    candidates.push({ idx: i, frame_number: d.frame_number });
  }
  if (!candidates.length) return;

  const fineWindowEl = document.getElementById("fine-window");
  const fineWindow = fineWindowEl ? parseInt(fineWindowEl.value, 10) : 50;

  let data;
  try {
    const resp = await fetch("/clip-cutter/rescan-forward", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: _videoPath,
        candidates,
        params: { fine_window: fineWindow },
      }),
    });
    if (!resp.ok) return;
    data = await resp.json();
  } catch { return; }

  _rescanJobId = data.job_id;

  const prog = document.getElementById("ep-rescan-progress");
  const textEl = document.getElementById("ep-rescan-text");
  const countEl = document.getElementById("ep-rescan-count");
  if (prog) {
    prog.style.display = "flex";
    if (textEl) textEl.textContent = `↻ Rescanning ${candidates.length} ahead…`;
    if (countEl) countEl.textContent = "";
  }

  let done = 0;
  const total = candidates.length;
  const es = new EventSource(`/clip-cutter/rescan-forward/stream?job_id=${_rescanJobId}`);
  _rescanEs = es;

  function _finishRescan() {
    _rescanEs = null;
    _rescanJobId = null;
    if (prog) prog.style.display = "none";
  }

  es.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.phase) {
      es.close();
      _finishRescan();
      return;
    }
    done++;
    if (countEl) countEl.textContent = `${done} / ${total}`;
    _epApplyRescanKF(msg.idx, msg.new_frame_number);
  };
  es.onerror = () => { es.close(); _finishRescan(); };
}

// ── Layout helpers ─────────────────────────────────────────────────────────────

function _epSyncResultsPadding() {
  const panel = document.getElementById("player-panel");
  const list  = document.getElementById("results-list");
  if (!panel || !list) return;
  list.style.paddingBottom = panel.offsetHeight + "px";
}

function _epClearResultsPadding() {
  const list = document.getElementById("results-list");
  if (list) list.style.paddingBottom = "0px";
}

// ── Event wiring ───────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {

  // Collapse
  document.getElementById("ep-collapse").addEventListener("click", () => {
    _stop();
    document.getElementById("player-panel").style.display = "none";
    _epClearResultsPadding();
  });

  // Lock badge — toggle lock/unlock clip range
  document.getElementById("ep-lock-badge").addEventListener("click", () => {
    if (!_videoPath || _mode !== "clip") return;
    _unlocked = !_unlocked;
    const badge = document.getElementById("ep-lock-badge");
    badge.className = _unlocked ? "unlocked" : "locked";
    badge.textContent = (_unlocked ? "🔓 " : "🔒 ") + (_clipStart + 1) + "–" + (_clipEnd + 1);
    _epUpdateSeekHighlight();
    _epUpdateLockOverlay();
    if (!_unlocked) {
      const clamped = Math.max(_clipStart, Math.min(_currentFrame, _clipEnd));
      if (clamped !== _currentFrame) _epLoadFrame(clamped);
    }
  });

  // Play forward / pause
  document.getElementById("ep-play").addEventListener("click", () => {
    if (!_videoPath) return;
    if (_playing && _playDir === 1) {
      _stop();
    } else {
      _stop();
      _playDir = 1;
      _playing = true;
      document.getElementById("ep-play").textContent = "⏸";
      _epLoop();
    }
  });

  // Play backward / pause
  document.getElementById("ep-play-back").addEventListener("click", () => {
    if (!_videoPath) return;
    if (_playing && _playDir === -1) {
      _stop();
    } else {
      _stop();
      _playDir = -1;
      _playing = true;
      document.getElementById("ep-play-back").textContent = "⏸";
      _epLoop();
    }
  });

  // ⏮ jump to clip start
  document.getElementById("ep-first").addEventListener("click", () => {
    _stop(); _epLoadFrame(_clipStart);
  });

  // ⌖ KF — jump to current clip's keyframe (clip mode only)
  document.getElementById("ep-goto-kf").addEventListener("click", () => {
    _stop(); _epLoadFrame(_keyFrame);
  });

  // KF canvas toggle
  document.getElementById("ep-kf-toggle").addEventListener("click", () => {
    _kfCanvasVisible = !_kfCanvasVisible;
    const canvas = document.getElementById("ep-kf-canvas");
    canvas.style.display = _kfCanvasVisible ? "block" : "none";
    document.getElementById("ep-kf-toggle").classList.toggle("active", _kfCanvasVisible);
    if (_kfCanvasVisible) _epDrawKfCanvas();
  });

  // KF prev/next navigation
  document.getElementById("ep-kf-prev").addEventListener("click", () => {
    const frames = _epAllKfFrames();
    const prev = [...frames].reverse().find(f => f < _currentFrame);
    if (prev !== undefined) { _stop(); _epLoadFrame(prev); }
  });

  document.getElementById("ep-kf-next").addEventListener("click", () => {
    const frames = _epAllKfFrames();
    const next = frames.find(f => f > _currentFrame);
    if (next !== undefined) { _stop(); _epLoadFrame(next); }
  });

  // ⏭ jump to clip end
  document.getElementById("ep-last").addEventListener("click", () => {
    _stop(); _epLoadFrame(_clipEnd);
  });

  // ◀ back by step size
  document.getElementById("ep-back").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame - _stepSize);
  });

  // ‹ back 1 frame
  document.getElementById("ep-back1").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame - 1);
  });

  // › forward 1 frame
  document.getElementById("ep-fwd1").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame + 1);
  });

  // ▶▶ forward by step size
  document.getElementById("ep-fwd").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame + _stepSize);
  });

  // Step size input — deselects all presets
  document.getElementById("ep-step").addEventListener("change", (e) => {
    const v = parseInt(e.target.value, 10);
    _stepSize = v > 0 ? v : 1;
    e.target.value = _stepSize;
    _activePresetIdx = null;
    document.querySelectorAll(".ep-step-preset").forEach(el => el.classList.remove("active"));
  });

  // Step preset inputs — radio-style; click selects, value change updates step
  document.querySelectorAll(".ep-step-preset").forEach((input, idx) => {
    input.addEventListener("click", () => {
      _activePresetIdx = idx;
      document.querySelectorAll(".ep-step-preset").forEach((el, i) => el.classList.toggle("active", i === idx));
      const v = parseInt(input.value, 10);
      if (v > 0) {
        _stepSize = v;
        document.getElementById("ep-step").value = _stepSize;
      }
    });
    input.addEventListener("change", () => {
      const v = parseInt(input.value, 10);
      if (v > 0) {
        input.value = v;
        if (_activePresetIdx === idx) {
          _stepSize = v;
          document.getElementById("ep-step").value = _stepSize;
        }
      }
    });
  });

  // Play-N input
  document.getElementById("ep-playn").addEventListener("change", (e) => {
    const v = parseInt(e.target.value, 10);
    _playN = v > 0 ? v : 1;
    e.target.value = _playN;
  });

  // Loop toggle
  document.getElementById("ep-loop").addEventListener("click", () => {
    _looping = !_looping;
    document.getElementById("ep-loop").classList.toggle("active", _looping);
  });

  // Seek bar — in clip mode, clamp value to [_clipStart, _clipEnd]
  document.getElementById("ep-seek").addEventListener("input", (e) => {
    _stop();
    let n = parseInt(e.target.value, 10);
    if (_mode === "clip" && !_unlocked) {
      n = Math.max(_clipStart, Math.min(n, _clipEnd));
      e.target.value = n;
    }
    _epLoadFrame(n);
  });

  // Zoom slider
  document.getElementById("ep-zoom").addEventListener("input", (e) => {
    const pct = parseInt(e.target.value, 10);
    document.getElementById("ep-zoom-pct").textContent = pct + "%";
    const img = document.getElementById("ep-frame");
    img.style.transform = "scale(" + (pct / 100) + ")";
  });

  // Sync cam checkbox
  document.getElementById("ep-sync-cam").addEventListener("change", (e) => {
    _syncCamEnabled = e.target.checked;
    _epUpdateSyncCamUI();
    if (_syncCamEnabled) _epLoadCam2Frame(_currentFrame);
  });

  // Frame counter — double-click to jump
  document.getElementById("ep-frame-counter").addEventListener("dblclick", () => {
    if (!_videoPath) return;
    const jump = document.getElementById("ep-frame-jump");
    jump.value = _currentFrame + 1;
    jump.min = _unlocked ? 1 : _clipStart + 1;
    jump.max = _unlocked ? _frameCount : _clipEnd + 1;
    document.getElementById("ep-frame-counter").style.display = "none";
    jump.style.display = "";
    jump.select();
  });

  let _jumpCancelled = false;

  const _commitJump = () => {
    const jump = document.getElementById("ep-frame-jump");
    let n1 = parseInt(jump.value, 10);
    n1 = Math.max(
      _unlocked ? 1 : _clipStart + 1,
      Math.min(n1, _unlocked ? _frameCount : _clipEnd + 1)
    );
    jump.style.display = "none";
    document.getElementById("ep-frame-counter").style.display = "";
    _stop();
    _epLoadFrame(n1 - 1);
  };

  const _cancelJump = () => {
    _jumpCancelled = true;
    document.getElementById("ep-frame-jump").style.display = "none";
    document.getElementById("ep-frame-counter").style.display = "";
  };

  document.getElementById("ep-frame-jump").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); _commitJump(); }
    else if (e.key === "Escape") { e.preventDefault(); _cancelJump(); }
  });
  document.getElementById("ep-frame-jump").addEventListener("blur", () => {
    if (!_jumpCancelled) _commitJump();
    _jumpCancelled = false;
  });

  // Keyboard navigation (when player panel is open and no text input is focused)
  document.addEventListener("keydown", (e) => {
    if (!_videoPath) return;
    if (document.getElementById("ep-frame-jump").style.display !== "none") return;
    const tag = (e.target || {}).tagName || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (e.target && e.target.isContentEditable) return;

    if (e.key === "ArrowLeft" && !e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - 1);
    } else if (e.key === "ArrowRight" && !e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + 1);
    } else if (e.key === "ArrowLeft" && e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame - _stepSize);
    } else if (e.key === "ArrowRight" && e.ctrlKey) {
      e.preventDefault(); _stop(); _epLoadFrame(_currentFrame + _stepSize);
    }
  });

  // Start / Frames → recalculate End
  document.getElementById("ep-start").addEventListener("input", _epUpdateEnd);
  document.getElementById("ep-frames").addEventListener("input", _epUpdateEnd);

  // Lock start checkbox — when unchecked, sync Start to current frame
  document.getElementById("ep-lock-start").addEventListener("change", (e) => {
    if (!e.target.checked && _videoPath) {
      document.getElementById("ep-start").value = _currentFrame + 1;
      _epUpdateEnd();
    }
  });

  // ── Add sub-timeline rows ─────────────────────────────────────────────────
  document.getElementById("ep-status-add-sub").addEventListener("click", () => {
    _epAddSubRow("ep-status-sub-rows", "frame_line_status");
  });
  document.getElementById("ep-note-add-sub").addEventListener("click", () => {
    _epAddSubRow("ep-note-sub-rows", "note");
  });

  // ── Status timeline canvas ────────────────────────────────────────────────

  document.getElementById("ep-status-canvas").addEventListener("click", e => {
    if (!_epActiveChip || _epActiveChip.type !== "status") return;
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r.frame_line_status; return v && v !== "0" && v === _epActiveChip.val; })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });

  document.getElementById("ep-status-prev").addEventListener("click", () => { _epNavByChip(-1); });
  document.getElementById("ep-status-next").addEventListener("click", () => { _epNavByChip(1); });

  // ── Note timeline canvas ──────────────────────────────────────────────────

  document.getElementById("ep-note-canvas").addEventListener("click", e => {
    if (!_epActiveChip || _epActiveChip.type !== "note") return;
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r.note; return v && v === _epActiveChip.val; })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });

  document.getElementById("ep-note-prev").addEventListener("click", () => { _epNavByChip(-1); });
  document.getElementById("ep-note-next").addEventListener("click", () => { _epNavByChip(1); });

  // Add to template (template mode only) — two-step confirm
  const _addConfirmEl  = document.getElementById("ep-add-confirm");
  const _addConfirmMsg = document.getElementById("ep-add-confirm-msg");

  const _hideAddConfirm = () => { _addConfirmEl.style.display = "none"; };

  document.getElementById("ep-add-template").addEventListener("click", () => {
    if (!_videoPath) return;
    _addConfirmMsg.textContent = "Add frame " + (_currentFrame + 1) + " to template?";
    _addConfirmEl.style.display = "";
  });

  document.getElementById("ep-add-confirm-cancel").addEventListener("click", _hideAddConfirm);

  document.getElementById("ep-add-confirm-yes").addEventListener("click", async () => {
    _hideAddConfirm();
    const frameNumber = _currentFrame + 1;
    try {
      const resp = await fetch("/clip-cutter/template/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _videoPath, frame_number: frameNumber }),
      });
      if (resp.ok) {
        if (typeof loadTemplate === "function") await loadTemplate();
        setStatus("Frame " + frameNumber + " added to template");
      } else {
        const err = await resp.json().catch(() => ({ error: "unknown" }));
        setStatus("Error: " + err.error);
      }
    } catch (e) { setStatus("Network error: " + e.message); }
  });

  // Set KF (clip mode — with overlap check)
  document.getElementById("ep-set-kf").addEventListener("click", async () => {
    if (!_videoPath || _detectionIdx === null) return;
    const kf1 = _currentFrame + 1;

    let data;
    try {
      const resp = await fetch("/clip-cutter/check-keyframe-overlap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _videoPath, key_frame: kf1 }),
      });
      if (!resp.ok) { setStatus("Overlap check failed"); return; }
      data = await resp.json();
    } catch (e) { setStatus("Network error: " + e.message); return; }

    if (!data.overlaps) {
      await _epApplyNewKF(kf1);
      return;
    }

    const conflict = data.conflicts[0];
    const warning = document.getElementById("ep-warning");
    warning.innerHTML = "";

    const msg = document.createElement("div");
    msg.style.cssText = "color:#f85149;margin-bottom:3px;";
    msg.textContent = "⚠ Overlaps " + conflict.name + " by " + conflict.overlap_frames + " fr";

    const btns = document.createElement("div");
    btns.style.cssText = "display:flex;gap:4px;margin-top:2px;";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "player-btn";
    cancelBtn.style.fontSize = "8px";
    cancelBtn.textContent = "Cancel";
    cancelBtn.onclick = () => { warning.style.display = "none"; };

    const keepBtn = document.createElement("button");
    keepBtn.className = "player-btn ep-btn-red";
    keepBtn.style.fontSize = "8px";
    keepBtn.textContent = "Keep anyway";
    keepBtn.onclick = async () => await _epApplyNewKF(kf1);

    btns.appendChild(cancelBtn);
    btns.appendChild(keepBtn);
    warning.appendChild(msg);
    warning.appendChild(btns);
    warning.style.display = "";
  });

  // Extract
  document.getElementById("ep-extract").addEventListener("click", async () => {
    if (!_videoPath) return;
    const capturedIdx = _detectionIdx;
    const capturedVideoPath = _videoPath;
    const start = parseInt(document.getElementById("ep-start").value, 10);
    const keyFrame = start + 200;
    const postfix = document.getElementById("ep-postfix").value.trim();

    const body = { video_path: capturedVideoPath, key_frame: keyFrame };
    if (postfix) body.postfix = postfix;

    try {
      const resp = await fetch("/clip-cutter/extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        setStatus("Extract error: " + err.error);
        return;
      }
      const data = await resp.json();
      setStatus("Clip extracted");
      if (capturedIdx !== null && typeof detections !== "undefined" && detections[capturedIdx]) {
        detections[capturedIdx].status = "kept";
        detections[capturedIdx].extract_avi_path = data.avi_path;
        detections[capturedIdx].extract_postfix = postfix || null;
        const card = document.getElementById("card-" + capturedIdx);
        if (card) {
          card.classList.add("kept");
          card.querySelectorAll("button").forEach(b => { b.disabled = true; });
          const nameEl = card.querySelector(".result-name");
          if (nameEl) nameEl.textContent = data.avi_path.split("/").pop();
        }
        if (typeof saveDetections === "function") saveDetections();
      }
      if (_detectionIdx === capturedIdx) {
        document.getElementById("ep-extract").style.display = "none";
        document.getElementById("ep-rename-extract").style.display = "";
        document.getElementById("ep-rename-extract").disabled = false;
        document.getElementById("ep-delete-extract").style.display = "";
        document.getElementById("ep-set-kf").disabled = true;
        document.getElementById("ep-reject").disabled = true;
      }
    } catch (e) { setStatus("Network error: " + e.message); }
  });

  // Delete extract
  document.getElementById("ep-delete-extract").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;
    const capturedIdx = _detectionIdx;
    const det = detections[capturedIdx];
    const aviPath = det?.extract_avi_path;

    const _unlock = () => {
      det.status = null;
      delete det.extract_avi_path;
      document.getElementById("ep-delete-extract").style.display = "none";
      document.getElementById("ep-rename-extract").style.display = "none";
      document.getElementById("ep-extract").style.display = "";
      document.getElementById("ep-extract").disabled = false;
      document.getElementById("ep-set-kf").disabled = false;
      document.getElementById("ep-reject").disabled = false;
      const card = document.getElementById("card-" + capturedIdx);
      if (card) {
        card.classList.remove("kept");
        card.querySelectorAll("button").forEach(b => { b.disabled = false; });
      }
      if (typeof saveDetections === "function") saveDetections();
    };

    if (!aviPath) {
      // No path recorded — just unlock the candidate
      _unlock();
      setStatus("No file path recorded — candidate unlocked");
      return;
    }

    try {
      const resp = await fetch("/clip-cutter/extract/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avi_path: aviPath }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        // File-not-found (404) → still unlock the candidate
        if (resp.status === 404) {
          _unlock();
          setStatus("File not found on disk — candidate unlocked");
        } else {
          setStatus("Delete error: " + err.error);
        }
        return;
      }
      _unlock();
      setStatus("Extract deleted");
    } catch (e) { setStatus("Network error: " + e.message); }
  });

  // Rename extract — apply current postfix to the extracted filename
  document.getElementById("ep-rename-extract").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;
    const capturedIdx = _detectionIdx;
    const det = detections[capturedIdx];
    const aviPath = det?.extract_avi_path;
    if (!aviPath) { setStatus("No extract path recorded"); return; }
    const postfix = document.getElementById("ep-postfix").value.trim();
    try {
      const resp = await fetch("/clip-cutter/extract/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avi_path: aviPath, postfix }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        setStatus("Rename error: " + err.error);
        return;
      }
      const data = await resp.json();
      det.extract_avi_path = data.avi_path;
      det.extract_postfix = postfix || null;
      const card = document.getElementById("card-" + capturedIdx);
      if (card) {
        const nameEl = card.querySelector(".result-name");
        if (nameEl) nameEl.textContent = data.avi_path.split("/").pop();
      }
      if (typeof saveDetections === "function") saveDetections();
      setStatus("Renamed → " + data.avi_path.split("/").pop());
    } catch (e) { setStatus("Network error: " + e.message); }
  });

  // Reject (clip mode)
  document.getElementById("ep-reject").addEventListener("click", async () => {
    if (_detectionIdx === null || typeof detections === "undefined") return;
    detections.splice(_detectionIdx, 1);
    const card = document.getElementById("card-" + _detectionIdx);
    if (card) card.remove();
    if (typeof saveDetections === "function") saveDetections();
    _stop();
    document.getElementById("player-panel").style.display = "none";
    _epClearResultsPadding();
  });

  // Drag handle — resize panel height by dragging the top border
  (function () {
    const handle = document.getElementById("ep-drag-handle");
    const panel  = document.getElementById("player-panel");
    let startY = 0, startH = 0;

    handle.addEventListener("mousedown", (e) => {
      startY = e.clientY;
      startH = panel.offsetHeight;
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup",   onUp);
      e.preventDefault();
    });

    function onMove(e) {
      const delta = startY - e.clientY;   // drag up → taller
      panel.style.height = Math.max(180, startH + delta) + "px";
      _epSyncResultsPadding();
    }

    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
    }
  })();

  // Horizontal resize — drag handle between video and extract panel
  (function () {
    const handle  = document.getElementById("ep-panel-resize-handle");
    const extract = document.getElementById("ep-extract-panel");
    let startX = 0, startW = 0;

    handle.addEventListener("mousedown", (e) => {
      startX = e.clientX;
      startW = extract.offsetWidth;
      handle.classList.add("dragging");
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup",   onUp);
      e.preventDefault();
    });

    function onMove(e) {
      const delta = startX - e.clientX;   // drag left → wider extract panel
      extract.style.width = Math.max(160, Math.min(480, startW + delta)) + "px";
    }

    function onUp() {
      handle.classList.remove("dragging");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
    }
  })();

  // Minimize / restore
  (function () {
    const panel = document.getElementById("player-panel");
    const btn   = document.getElementById("ep-minimize-btn");
    let savedHeight = null;

    btn.addEventListener("click", () => {
      if (panel.classList.contains("minimized")) {
        panel.classList.remove("minimized");
        if (savedHeight) panel.style.height = savedHeight;
        btn.innerHTML = "&#9660;";
        btn.title = "Minimize viewer";
        _epSyncResultsPadding();
      } else {
        savedHeight = panel.style.height || panel.offsetHeight + "px";
        panel.classList.add("minimized");
        panel.style.height = "";
        btn.innerHTML = "&#9650;";
        btn.title = "Restore viewer";
        _epClearResultsPadding();
      }
    });
  })();

  // ── Postfix tags ──────────────────────────────────────────────────────────

  _epLoadPostfixTags();
  _epRenderPostfixTags();

  document.getElementById("ep-add-tag-btn").addEventListener("click", () => {
    const input = document.getElementById("ep-new-tag-input");
    const val = input.value.trim();
    if (!val || _epPostfixTags.includes(val)) { input.value = ""; return; }
    _epPostfixTags.push(val);
    _epSavePostfixTags();
    _epRenderPostfixTags();
    input.value = "";
  });

  document.getElementById("ep-new-tag-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); document.getElementById("ep-add-tag-btn").click(); }
  });

  // Sync postfix input back to active tag selection
  document.getElementById("ep-postfix").addEventListener("input", (e) => {
    const val = e.target.value.trim();
    if (_epActivePostfixTag && val !== _epActivePostfixTag) {
      _epActivePostfixTag = null;
      _epRenderPostfixTags();
    }
  });

  document.getElementById("ep-rescan-cancel")?.addEventListener("click", async () => {
    if (_rescanEs) { _rescanEs.close(); _rescanEs = null; }
    const jid = _rescanJobId;
    _rescanJobId = null;
    const prog = document.getElementById("ep-rescan-progress");
    if (prog) prog.style.display = "none";
    if (jid) {
      await fetch(`/clip-cutter/rescan-forward/${jid}/cancel`, { method: "POST" }).catch(() => {});
    }
  });

}); // end DOMContentLoaded
