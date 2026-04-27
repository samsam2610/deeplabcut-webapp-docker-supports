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

  let info;
  try {
    const resp = await fetch(`/clip-cutter/video-info?video=${encodeURIComponent(videoPath)}`);
    if (!resp.ok) { setStatus("Cannot load video info"); return; }
    info = await resp.json();
  } catch (e) { setStatus("Network error: " + e.message); return; }
  _frameCount = info.frame_count;

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

  document.getElementById("player-panel").style.display = "";

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

  await _epLoadFrame(_clipStart);
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

// ── Mode-specific UI ───────────────────────────────────────────────────────────

function _epUpdateModeUI() {
  const lockBadge = document.getElementById("ep-lock-badge");
  const setKfBtn = document.getElementById("ep-set-kf");
  const rejectBtn = document.getElementById("ep-reject");
  const addTemplateBtn = document.getElementById("ep-add-template");
  const seekEl = document.getElementById("ep-seek");

  seekEl.min = 0;
  seekEl.max = _frameCount - 1;

  if (_mode === "clip") {
    lockBadge.style.display = "";
    lockBadge.textContent = "🔒 " + (_clipStart + 1) + "–" + (_clipEnd + 1);
    setKfBtn.style.display = "";
    rejectBtn.style.display = "";
    addTemplateBtn.style.display = "none";
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

  // ⏭ jump to clip end
  document.getElementById("ep-last").addEventListener("click", () => {
    _stop(); _epLoadFrame(_clipEnd);
  });

  // ◀ back by step size
  document.getElementById("ep-back").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame - _stepSize);
  });

  // ▷ single frame forward
  document.getElementById("ep-fwd").addEventListener("click", () => {
    _stop(); _epLoadFrame(_currentFrame + 1);
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

  // Add to template (template mode only)
  document.getElementById("ep-add-template").addEventListener("click", async () => {
    if (!_videoPath) return;
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

}); // end DOMContentLoaded
