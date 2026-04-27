const PLAYER_FPS = 15;

let _playerVideoPath = null;
let _playerFrameCount = 0;
let _playerCurrentFrame = 0;
let _playerClipStart = 0;
let _playerClipEnd = 0;
let _playerKeyFrame = 0;
let _playerLooping = true;
let _playerPlaying = false;
let _playerBusy = false;
let _playerTimeoutId = null;
let _playerDetectionIdx = null;

async function loadClip(videoPath, keyFrame1Based, detectionIdx = null) {
  const resp = await fetch(
    `/clip-cutter/video-info?video=${encodeURIComponent(videoPath)}`
  );
  if (!resp.ok) { setStatus("Cannot load video info"); return; }
  const info = await resp.json();

  _playerVideoPath = videoPath;
  _playerFrameCount = info.frame_count;
  const kf0 = keyFrame1Based - 1;
  _playerKeyFrame = kf0;
  _playerDetectionIdx = detectionIdx;
  document.getElementById("player-kf-num").textContent = keyFrame1Based;
  document.getElementById("player-overlap-warning").style.display = "none";
  _playerClipStart = Math.max(0, kf0 - 200);
  _playerClipEnd = Math.min(info.frame_count - 1, kf0 + 599);

  _playerStop();
  document.getElementById("player-placeholder").style.display = "none";
  document.getElementById("player-container").style.display = "flex";

  await _playerLoadFrame(_playerClipStart);
}

function applyNewKF(kf1) {
  if (_playerDetectionIdx === null) return;
  detections[_playerDetectionIdx].frame_number = kf1;
  const kf0 = kf1 - 1;
  _playerKeyFrame = kf0;
  _playerClipStart = Math.max(0, kf0 - 200);
  _playerClipEnd = Math.min(_playerFrameCount - 1, kf0 + 599);
  document.getElementById("player-kf-num").textContent = kf1;
  document.getElementById("player-overlap-warning").style.display = "none";
  const nameEl = document.getElementById(`card-clipname-${_playerDetectionIdx}`);
  if (nameEl) {
    const d = detections[_playerDetectionIdx];
    const videoName = d.video_path.split("/").pop().replace(".avi", "");
    // mirrors buildResultCard formula in clip_cutter.js (pre=200, post=600, end=kf1+599)
    nameEl.textContent = `${videoName}_${kf1 - 200}_${kf1 + 599}.avi`;
  }
  if (typeof saveDetections === "function") saveDetections();
}

async function _playerLoadFrame(n) {
  if (_playerBusy || _playerVideoPath === null || _playerFrameCount === 0) return;
  _playerBusy = true;
  n = Math.max(0, Math.min(n, _playerFrameCount - 1));
  const prevFrame = _playerCurrentFrame;
  _playerCurrentFrame = n;

  try {
    const url = `/clip-cutter/frame?video=${encodeURIComponent(_playerVideoPath)}&n=${n}`;
    const resp = await fetch(url);
    if (!resp.ok) { _playerCurrentFrame = prevFrame; return; }
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    const img = document.getElementById("player-frame");
    const prev = img.src;
    await new Promise((resolve, reject) => {
      img.onload = () => {
        if (prev && prev.startsWith("blob:")) URL.revokeObjectURL(prev);
        resolve();
      };
      img.onerror = reject;
      img.src = blobUrl;
    });
    _playerUpdateDisplay();
    if (n < _playerClipEnd) {
      new Image().src = `/clip-cutter/frame?video=${encodeURIComponent(_playerVideoPath)}&n=${n + 1}`;
    }
  } finally {
    _playerBusy = false;
  }
}

async function _playerLoop() {
  if (!_playerPlaying) return;

  if (_playerBusy) {
    _playerTimeoutId = setTimeout(_playerLoop, Math.round(1000 / PLAYER_FPS));
    return;
  }

  let next = _playerCurrentFrame + 1;
  if (next > _playerClipEnd) {
    if (_playerLooping) {
      next = _playerClipStart;
    } else {
      _playerStop();
      return;
    }
  }

  const t0 = performance.now();
  await _playerLoadFrame(next);
  if (!_playerPlaying) return;

  const elapsed = performance.now() - t0;
  const delay = Math.max(0, Math.round(1000 / PLAYER_FPS) - elapsed);
  _playerTimeoutId = setTimeout(_playerLoop, delay);
}

function _playerStop() {
  if (_playerTimeoutId !== null) { clearTimeout(_playerTimeoutId); _playerTimeoutId = null; }
  _playerPlaying = false;
  const btn = document.getElementById("player-play");
  if (btn) btn.textContent = "▶";
}

function _playerUpdateDisplay() {
  document.getElementById("player-frame-num").textContent = `fr ${_playerCurrentFrame}`;
  const seek = document.getElementById("player-seek");
  const pct = _playerFrameCount > 1 ? _playerCurrentFrame / (_playerFrameCount - 1) : 0;
  seek.value = Math.round(pct * 1000);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("player-play").addEventListener("click", () => {
    if (_playerVideoPath === null) return;
    if (_playerPlaying) {
      _playerStop();
    } else {
      _playerPlaying = true;
      document.getElementById("player-play").textContent = "⏸";
      _playerLoop();
    }
  });

  document.getElementById("player-prev").addEventListener("click", () => {
    _playerStop();
    _playerLoadFrame(_playerCurrentFrame - 1);
  });

  document.getElementById("player-next").addEventListener("click", () => {
    _playerStop();
    _playerLoadFrame(_playerCurrentFrame + 1);
  });

  document.getElementById("player-keyframe").addEventListener("click", () => {
    _playerStop();
    _playerLoadFrame(_playerKeyFrame);
  });

  document.getElementById("player-loop").addEventListener("click", () => {
    _playerLooping = !_playerLooping;
    document.getElementById("player-loop").classList.toggle("active", _playerLooping);
  });

  document.getElementById("player-seek").addEventListener("input", (e) => {
    if (_playerFrameCount === 0) return;
    _playerStop();
    const n = Math.round((e.target.value / 1000) * (_playerFrameCount - 1));
    _playerLoadFrame(n);
  });

  document.getElementById("player-set-kf").addEventListener("click", async () => {
    if (_playerVideoPath === null || _playerDetectionIdx === null) return;
    const kf1 = _playerCurrentFrame + 1;
    let data;
    try {
      const resp = await fetch("/clip-cutter/check-keyframe-overlap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _playerVideoPath, key_frame: kf1 }),
      });
      if (!resp.ok) { setStatus("Overlap check failed"); return; }
      data = await resp.json();
    } catch (e) {
      setStatus("Network error: " + e.message);
      return;
    }
    if (!data.overlaps) {
      applyNewKF(kf1);
      return;
    }
    const conflict = data.conflicts[0];
    const warning = document.getElementById("player-overlap-warning");
    warning.innerHTML = "";
    const title = document.createElement("div");
    title.className = "ow-title";
    title.textContent = "⚠ Overlap detected";
    const body = document.createElement("div");
    body.className = "ow-body";
    const code = document.createElement("code");
    code.textContent = conflict.name;
    body.appendChild(document.createTextNode("New range overlaps "));
    body.appendChild(code);
    body.appendChild(document.createTextNode(` by ${conflict.overlap_frames} frames.`));
    const actions = document.createElement("div");
    actions.className = "ow-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "player-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", () => {
      warning.style.display = "none";
    });
    const keepBtn = document.createElement("button");
    keepBtn.className = "player-btn player-btn-red";
    keepBtn.textContent = "Keep anyway";
    keepBtn.addEventListener("click", () => applyNewKF(kf1));
    actions.appendChild(cancelBtn);
    actions.appendChild(keepBtn);
    warning.appendChild(title);
    warning.appendChild(body);
    warning.appendChild(actions);
    warning.style.display = "block";
  });

  document.getElementById("player-clip-start").addEventListener("click", () => {
    if (_playerVideoPath === null) return;
    _playerStop();
    _playerLoadFrame(_playerClipStart).then(() => {
      _playerPlaying = true;
      document.getElementById("player-play").textContent = "⏸";
      _playerLoop();
    });
  });
});
