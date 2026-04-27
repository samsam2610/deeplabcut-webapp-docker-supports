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
let _kfCanvasVisible = false;

// ── Public API ──────────────────────────────────────────────────────────────────

async function openPlayer({ mode, videoPath, keyFrame1Based = null, detectionIdx = null, csvPath = null }) {
  _stop();
  _mode = mode;
  _videoPath = videoPath;
  _detectionIdx = detectionIdx;
  _csvRows = [];
  _stepSize = 10;
  _playN = 1;
  _looping = true;
  const stepEl = document.getElementById("ep-step");
  const playNEl = document.getElementById("ep-playn");
  if (stepEl) stepEl.value = 10;
  if (playNEl) playNEl.value = 1;

  _kfCanvasVisible = false;

  // Show panel immediately so user sees it open without waiting for network
  document.getElementById("player-panel").style.display = "";
  document.getElementById("ep-frame").src = "";

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

  _epUpdateModeUI();
  _epInitExtractPanel(videoPath, keyFrame1Based);

  if (csvPath) {
    try {
      const r = await fetch(`/clip-cutter/csv?path=${encodeURIComponent(csvPath)}`);
      if (r.ok) _csvRows = (await r.json()).rows;
    } catch (e) {
      console.warn("[enhanced_player] CSV load failed:", e);
    }
  }

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
  n = Math.max(_clipStart, Math.min(n, _clipEnd));
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
    if (n < _clipEnd) {
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

  let next = _currentFrame + _playN;
  if (next > _clipEnd) {
    if (_looping) next = _clipStart;
    else { _stop(); return; }
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
  const btn = document.getElementById("ep-play");
  if (btn) btn.textContent = "▶";
  _epRedrawAllCanvases();
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

function _epUpdateSeekHighlight() {
  const h = document.getElementById("ep-seek-highlight");
  if (!h) return;
  if (_mode !== "clip" || _frameCount <= 1) { h.style.display = "none"; return; }
  h.style.display = "";
  const total = _frameCount - 1;
  const left = (_clipStart / total) * 100;
  const width = ((_clipEnd - _clipStart) / total) * 100;
  h.style.left = left + "%";
  h.style.width = width + "%";
}

function _epUpdateCsvStrip() {
  const cur1 = _currentFrame + 1;
  const row = _csvRows.find(r => r.frame_number === cur1);
  const statusBadge = document.getElementById("ep-status-badge");
  const noteBadge = document.getElementById("ep-note-badge");
  if (row) {
    statusBadge.textContent = row.frame_line_status || "—";
    noteBadge.textContent = row.note || "—";
  } else {
    statusBadge.textContent = "—";
    noteBadge.textContent = "—";
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

function _epRedrawStatusCanvas() {
  const canvas = document.getElementById("ep-status-canvas");
  if (!canvas || document.getElementById("ep-status-bar-wrap").style.display === "none") return;
  _epDrawTagCanvas(canvas, _csvRows, "frame_line_status", _epActiveStatus, _epStatusColorMap);
  _epDrawCanvasCursor(canvas);
}

function _epRedrawNoteCanvas() {
  const canvas = document.getElementById("ep-note-canvas");
  if (!canvas || document.getElementById("ep-note-bar-wrap").style.display === "none") return;
  _epDrawTagCanvas(canvas, _csvRows, "note", _epActiveNote, _epNoteColorMap);
  _epDrawCanvasCursor(canvas);
}

function _epRedrawAllCanvases() {
  _epRedrawStatusCanvas();
  _epRedrawNoteCanvas();
}

function _epRenderStatusChips() {
  const container = document.getElementById("ep-status-chips");
  if (!container) return;
  container.innerHTML = "";
  Object.keys(_epStatusColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (_epActiveStatus.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epStatusColorMap[val]);
    chip.addEventListener("click", () => {
      if (_epActiveStatus.has(val)) _epActiveStatus.delete(val);
      else _epActiveStatus.add(val);
      _epRenderStatusChips();
      _epRedrawStatusCanvas();
    });
    container.appendChild(chip);
  });
}

function _epRenderNoteChips() {
  const container = document.getElementById("ep-note-chips");
  if (!container) return;
  container.innerHTML = "";
  Object.keys(_epNoteColorMap).forEach(val => {
    const chip = document.createElement("span");
    chip.className = "ep-tag-chip" + (_epActiveNote.has(val) ? " active" : "");
    chip.textContent = val;
    chip.style.setProperty("--chip-color", _epNoteColorMap[val]);
    chip.addEventListener("click", () => {
      if (_epActiveNote.has(val)) _epActiveNote.delete(val);
      else _epActiveNote.add(val);
      _epRenderNoteChips();
      _epRedrawNoteCanvas();
    });
    container.appendChild(chip);
  });
}

function _epBuildTagBars() {
  const hasStatus = _csvRows.some(r => r.frame_line_status && r.frame_line_status !== "0");
  const hasNote   = _csvRows.some(r => r.note);

  document.getElementById("ep-status-bar-wrap").style.display = hasStatus ? "" : "none";
  document.getElementById("ep-note-bar-wrap").style.display   = hasNote   ? "" : "none";

  const statusVals = [...new Set(_csvRows.map(r => r.frame_line_status).filter(v => v && v !== "0"))];
  _epStatusColorMap = {};
  _epActiveStatus   = new Set(statusVals);
  statusVals.forEach((v, i) => { _epStatusColorMap[v] = _EP_TAG_COLORS[i % _EP_TAG_COLORS.length]; });
  _epRenderStatusChips();

  const noteVals = [...new Set(_csvRows.map(r => r.note).filter(v => v))];
  _epNoteColorMap = {};
  _epActiveNote   = new Set(noteVals);
  noteVals.forEach((v, i) => { _epNoteColorMap[v] = _EP_TAG_COLORS[i % _EP_TAG_COLORS.length]; });
  _epRenderNoteChips();

  requestAnimationFrame(() => _epRedrawAllCanvases());
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
    lockBadge.textContent = "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);
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
  } else {
    lockBadge.style.display = "none";
    setKfBtn.style.display = "none";
    rejectBtn.style.display = "none";
    addTemplateBtn.style.display = "";
    gotoKfBtn.style.display = "none";
    document.getElementById("ep-lock-start").checked = false;
  }

  _epUpdateSeekHighlight();
}

// ── Extract panel init ─────────────────────────────────────────────────────────

function _epInitExtractPanel(videoPath, keyFrame1Based) {
  const start = (_mode === "clip" && keyFrame1Based !== null)
    ? Math.max(1, keyFrame1Based - 200)
    : 1;
  document.getElementById("ep-start").value = start;
  document.getElementById("ep-frames").value = 800;
  document.getElementById("ep-postfix").value = "";
  document.getElementById("ep-extract").disabled = false;
  document.getElementById("ep-warning").style.display = "none";
  _epUpdateEnd();

  const parts = videoPath.split("/");
  const filename = parts[parts.length - 1];
  const stem = filename.replace(/\.avi$/i, "");
  const parentName = parts[parts.length - 2] || "";
  const parent = parts.slice(0, -1).join("/");
  document.getElementById("ep-outdir").textContent = "…/" + parentName + "/" + stem + "/";
  document.getElementById("ep-outdir").title = parent + "/" + stem + "/";
}

// ── Apply new keyframe ─────────────────────────────────────────────────────────

function _epApplyNewKF(kf1) {
  if (_detectionIdx === null || typeof detections === "undefined") return;
  detections[_detectionIdx].frame_number = kf1;
  const kf0 = kf1 - 1;
  _keyFrame = kf0;
  _clipStart = Math.max(0, kf0 - 200);
  _clipEnd = Math.min(_frameCount - 1, kf0 + 599);

  document.getElementById("ep-lock-badge").textContent =
    "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);

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
  if (typeof saveDetections === "function") saveDetections();
  document.getElementById("ep-warning").style.display = "none";
  _epDrawKfCanvas();
}

// ── Event wiring ───────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {

  // Collapse
  document.getElementById("ep-collapse").addEventListener("click", () => {
    _stop();
    document.getElementById("player-panel").style.display = "none";
  });

  // Play / pause
  document.getElementById("ep-play").addEventListener("click", () => {
    if (!_videoPath) return;
    if (_playing) {
      _stop();
    } else {
      _playing = true;
      document.getElementById("ep-play").textContent = "⏸";
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

  // Step size input
  document.getElementById("ep-step").addEventListener("change", (e) => {
    const v = parseInt(e.target.value, 10);
    _stepSize = v > 0 ? v : 1;
    e.target.value = _stepSize;
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
    if (_mode === "clip") {
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

  // Frame counter — double-click to jump
  document.getElementById("ep-frame-counter").addEventListener("dblclick", () => {
    if (!_videoPath) return;
    const jump = document.getElementById("ep-frame-jump");
    jump.value = _currentFrame + 1;
    jump.min = _clipStart + 1;
    jump.max = _clipEnd + 1;
    document.getElementById("ep-frame-counter").style.display = "none";
    jump.style.display = "";
    jump.select();
  });

  let _jumpCancelled = false;

  const _commitJump = () => {
    const jump = document.getElementById("ep-frame-jump");
    let n1 = parseInt(jump.value, 10);
    n1 = Math.max(_clipStart + 1, Math.min(n1, _clipEnd + 1));
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

  // CSV tag navigation
  document.getElementById("ep-prev-tag").addEventListener("click", () => {
    if (!_csvRows.length) return;
    const cur1 = _currentFrame + 1;
    const row = _csvRows.find(r => r.frame_number === cur1);
    const tagVal = row && row.note ? row.note : null;
    if (!tagVal) return;
    const prev = [..._csvRows].reverse().find(r => r.frame_number < cur1 && r.note === tagVal);
    if (prev) { _stop(); _epLoadFrame(prev.frame_number - 1); }
  });

  document.getElementById("ep-next-tag").addEventListener("click", () => {
    if (!_csvRows.length) return;
    const cur1 = _currentFrame + 1;
    const row = _csvRows.find(r => r.frame_number === cur1);
    const tagVal = row && row.note ? row.note : null;
    if (!tagVal) return;
    const next = _csvRows.find(r => r.frame_number > cur1 && r.note === tagVal);
    if (next) { _stop(); _epLoadFrame(next.frame_number - 1); }
  });

  // ── Status timeline canvas ────────────────────────────────────────────────

  document.getElementById("ep-status-canvas").addEventListener("click", e => {
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r.frame_line_status; return v && v !== "0" && _epActiveStatus.has(v); })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });

  document.getElementById("ep-status-prev").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const prev = [..._csvRows]
      .filter(r => { const v = r.frame_line_status; return v && v !== "0" && _epActiveStatus.has(v) && r.frame_number < cur1; })
      .sort((a, b) => b.frame_number - a.frame_number)[0];
    if (prev) { _stop(); _epLoadFrame(prev.frame_number - 1); }
  });

  document.getElementById("ep-status-next").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const next = _csvRows
      .filter(r => { const v = r.frame_line_status; return v && v !== "0" && _epActiveStatus.has(v) && r.frame_number > cur1; })
      .sort((a, b) => a.frame_number - b.frame_number)[0];
    if (next) { _stop(); _epLoadFrame(next.frame_number - 1); }
  });

  // ── Note timeline canvas ──────────────────────────────────────────────────

  document.getElementById("ep-note-canvas").addEventListener("click", e => {
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const target = Math.round((e.clientX - rect.left) / rect.width * Math.max(_frameCount - 1, 0));
    const annotated = _csvRows
      .filter(r => { const v = r.note; return v && _epActiveNote.has(v); })
      .map(r => Number(r.frame_number) - 1);
    if (!annotated.length) return;
    const nearest = annotated.reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
    _stop(); _epLoadFrame(nearest);
  });

  document.getElementById("ep-note-prev").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const prev = [..._csvRows]
      .filter(r => { const v = r.note; return v && _epActiveNote.has(v) && r.frame_number < cur1; })
      .sort((a, b) => b.frame_number - a.frame_number)[0];
    if (prev) { _stop(); _epLoadFrame(prev.frame_number - 1); }
  });

  document.getElementById("ep-note-next").addEventListener("click", () => {
    const cur1 = _currentFrame + 1;
    const next = _csvRows
      .filter(r => { const v = r.note; return v && _epActiveNote.has(v) && r.frame_number > cur1; })
      .sort((a, b) => a.frame_number - b.frame_number)[0];
    if (next) { _stop(); _epLoadFrame(next.frame_number - 1); }
  });

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
      _epApplyNewKF(kf1);
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
    keepBtn.onclick = () => _epApplyNewKF(kf1);

    btns.appendChild(cancelBtn);
    btns.appendChild(keepBtn);
    warning.appendChild(msg);
    warning.appendChild(btns);
    warning.style.display = "";
  });

  // Extract
  document.getElementById("ep-extract").addEventListener("click", async () => {
    if (!_videoPath) return;
    const start = parseInt(document.getElementById("ep-start").value, 10);
    const keyFrame = start + 200;
    const postfix = document.getElementById("ep-postfix").value.trim();

    const body = { video_path: _videoPath, key_frame: keyFrame };
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
      setStatus("Clip extracted");
      if (_detectionIdx !== null && typeof detections !== "undefined" && detections[_detectionIdx]) {
        detections[_detectionIdx].status = "kept";
        const card = document.getElementById("card-" + _detectionIdx);
        if (card) {
          card.classList.add("kept");
          card.querySelectorAll("button").forEach(b => { b.disabled = true; });
        }
        if (typeof saveDetections === "function") saveDetections();
      }
      document.getElementById("ep-extract").disabled = true;
      document.getElementById("ep-set-kf").disabled = true;
      document.getElementById("ep-reject").disabled = true;
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
    }

    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
    }
  })();

}); // end DOMContentLoaded
