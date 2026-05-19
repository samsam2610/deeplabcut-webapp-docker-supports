// dlc_3d.js — inline file browser, project loader, extract button handler.
"use strict";

import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled, epLoadFrameAt } from "./enhanced_player.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath        = null;
let _activeSession      = null;
let _activeVideo        = null;
let _loadToken          = 0;
let _browserCurrentPath = null;
let _browserParentPath  = null;
let _batchStopRequested = false;

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

// ── Extractor reset ───────────────────────────────────────────────────────────

function _resetExtractorUI() {
  _projectPath        = null;
  _activeVideo        = null;
  _activeSession      = null;
  _browserCurrentPath = null;

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
  const batchBtn  = document.getElementById("ep-batch-extract-btn");
  const batchStop = document.getElementById("ep-batch-stop-btn");
  if (batchBtn)  batchBtn.disabled = true;
  if (batchStop) batchStop.classList.add("hidden");
  _batchStopRequested = false;
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

  const camIdx = videoPath.match(/_cam(\d+)_/)?.[1] ?? "?";
  document.getElementById("cam1-label").textContent = `Camera ${camIdx} (primary)`;

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

  if (siblingPath) {
    const sibCamIdx = siblingPath.match(/_cam(\d+)_/)?.[1] ?? "?";
    document.getElementById("cam2-label").textContent = `Camera ${sibCamIdx} (sibling)`;
  }

  _setStatus("");
  await openPlayer(videoPath, siblingPath, calibrationExists);
  _refreshLabeledFrames();
}

// ── Extract ───────────────────────────────────────────────────────────────────

function _setBatchUIRunning(running) {
  const single = document.getElementById("ep-extract-btn");
  const batch  = document.getElementById("ep-batch-extract-btn");
  const stop   = document.getElementById("ep-batch-stop-btn");
  if (single) single.disabled = running;
  if (batch)  batch.disabled  = running;
  if (stop)   stop.classList.toggle("hidden", !running);
}

async function _extractBatch() {
  const primaryVideo = getVideoPath();
  const siblingPath  = getSiblingPath();
  if (!primaryVideo || !_projectPath) {
    if (!_projectPath) _setStatus("No project loaded.");
    return;
  }

  let frameCount;
  try {
    const resp = await fetch(`/dlc-3d/video-info?video=${encodeURIComponent(primaryVideo)}`);
    if (!resp.ok) { _setStatus("Cannot load video info"); return; }
    const info = await resp.json();
    if (typeof info.frame_count !== "number") { _setStatus("Invalid video info"); return; }
    frameCount = info.frame_count;
  } catch (e) { _setStatus("Network error: " + e.message); return; }

  const startFrame = getCurrentFrame();
  const requested  = Math.max(2, parseInt(document.getElementById("ep-batch-count").value, 10) || 10);
  const step       = Math.max(1, parseInt(document.getElementById("ep-batch-step").value,  10) || 1);
  const maxCount   = Math.floor((frameCount - 1 - startFrame) / step) + 1;
  const count      = Math.min(requested, maxCount);
  if (count < 1) { _setStatus("No frames available from this position."); return; }

  const extractSibling   = isSyncCamEnabled()
    ? (document.getElementById("ep-extract-sibling")?.checked ?? true)
    : false;
  const siblingExtracted = extractSibling && !!siblingPath;
  const clamped          = count < requested;

  _batchStopRequested = false;
  _setBatchUIRunning(true);

  let saved = 0, skipped = 0, aborted = false, errored = false;
  let calibrationCopied = false;
  for (let i = 0; i < count; i++) {
    if (_batchStopRequested) { aborted = true; break; }
    const targetFrame = startFrame + i * step;
    _setStatus(`Saving… ${i + 1}/${count}`);
    const body = {
      primary_video:        primaryVideo,
      primary_frame_number: targetFrame,
      extract_sibling:      extractSibling,
    };
    if (siblingExtracted) {
      body.sibling_video        = siblingPath;
      body.sibling_frame_number = targetFrame;
    }
    try {
      const resp = await fetch("/dlc-3d/save-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json();
      if (resp.ok) {
        saved   += (data.saved   || []).length;
        skipped += (data.skipped || []).length;
        if (data.calibration_copied) calibrationCopied = true;
      } else {
        _setStatus(`Server error at frame ${targetFrame}: ${data.error || resp.status}`);
        errored = true;
        break;
      }
    } catch (e) {
      _setStatus(`Network error at frame ${targetFrame}: ${e.message}`);
      errored = true;
      break;
    }
    if (i < count - 1) await epLoadFrameAt(targetFrame + step);
  }

  _setBatchUIRunning(false);
  if (!errored) {
    const sibTag    = siblingExtracted ? " (×2 sibling)" : "";
    const clampTag  = clamped ? ` (clamped from ${requested})` : "";
    const calibTag  = calibrationCopied ? " — calibration.toml copied" : "";
    _setStatus(aborted
      ? `Stopped — saved ${saved}${sibTag}, skipped ${skipped}${clampTag}${calibTag}`
      : `Done — saved ${saved}${sibTag}, skipped ${skipped}${clampTag}${calibTag}`);
  }
  _refreshLabeledFrames();
}

async function _extractFrame() {
  const primaryVideo   = getVideoPath();
  const primaryFrame   = getCurrentFrame();
  const siblingPath    = getSiblingPath();
  const extractSibling = isSyncCamEnabled()
    ? (document.getElementById("ep-extract-sibling")?.checked ?? true)
    : false;

  if (!primaryVideo || primaryFrame == null || !_projectPath) {
    if (!_projectPath) _setStatus("No project loaded.");
    return;
  }

  const extractBtn = document.getElementById("ep-extract-btn");
  if (extractBtn) extractBtn.disabled = true;
  _setStatus("Saving…");

  const body = {
    primary_video:        primaryVideo,
    primary_frame_number: primaryFrame,
    extract_sibling:      extractSibling,
  };
  if (extractSibling && siblingPath) {
    body.sibling_video        = siblingPath;
    body.sibling_frame_number = primaryFrame;
  }

  let data;
  try {
    const resp = await fetch("/dlc-3d/save-frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    data = await resp.json();
    if (!resp.ok) { _setStatus(data.error || "Save failed"); return; }
  } catch (e) { _setStatus("Network error: " + e.message); return; }
  finally { if (extractBtn) extractBtn.disabled = false; }

  const calibTag = data.calibration_copied ? " — calibration.toml copied" : "";
  if (data.saved && data.saved.length > 0) {
    _setStatus(`Saved: ${data.saved.join(", ")}${calibTag}`);
  } else if (data.skipped && data.skipped.length > 0) {
    _setStatus(`Frame ${primaryFrame} already extracted — skipped.${calibTag}`);
  }
  _refreshLabeledFrames();
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
  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);
  document.getElementById("ep-batch-extract-btn")?.addEventListener("click", _extractBatch);
  document.getElementById("ep-batch-stop-btn")?.addEventListener("click", () => { _batchStopRequested = true; });

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
