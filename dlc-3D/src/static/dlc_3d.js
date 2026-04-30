// dlc_3d.js — inline file browser, project loader, extract button handler.
"use strict";

import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath        = null;
let _activeSession      = null;
let _activeVideo        = null;
let _loadToken          = 0;
let _browserCurrentPath = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setStatus(msg) {
  const el = document.getElementById("extract-status");
  if (el) el.textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

function _sessionKeyFromVideoRel(videoRel) {
  const parts = videoRel.split("/");
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
  const display = document.getElementById("dlc3d-project-display");
  if (display) display.textContent = "—";
  _setStatus("");
  const labeledWrap = document.getElementById("labeled-wrap");
  if (labeledWrap) labeledWrap.style.display = "none";
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
  document.getElementById("dlc3d-project-display").textContent = _projectPath;
  _setStatus("");
  _browseDir(_projectPath + "/videos");
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
  browser.innerHTML = "";

  if (data.parent) {
    const upRow = document.createElement("div");
    upRow.className = "fe-video-item";
    const upSpan = document.createElement("span");
    upSpan.textContent = "↑  ..";
    upSpan.style.cssText = "color:var(--text-dim);font-style:italic";
    upRow.appendChild(upSpan);
    upRow.addEventListener("click", () => _browseDir(data.parent));
    browser.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    row.className = "fe-video-item";

    const icon = document.createElement("span");
    const name = document.createElement("span");
    name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    name.textContent = entry.name;

    if (entry.type === "dir") {
      icon.textContent = "📁 ";
      row.append(icon, name);
      row.addEventListener("click", () => _browseDir(_browserCurrentPath + "/" + entry.name));
    } else if (entry.type === "file") {
      icon.textContent = "🎬 ";
      row.dataset.videoRel = (_browserCurrentPath + "/" + entry.name).slice(_projectPath.length + 1);
      row.append(icon, name);
      row.addEventListener("click", () => _selectVideo(row.dataset.videoRel));
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

async function _selectVideo(videoRel) {
  _activeVideo   = videoRel;
  _activeSession = _sessionKeyFromVideoRel(videoRel);

  document.querySelectorAll("#dlc3d-file-browser .fe-video-item").forEach(el => {
    el.classList.toggle("active", el.dataset.videoRel === videoRel);
  });

  document.getElementById("dlc3d-player-section").style.display = "";

  const camIdx = videoRel.match(/_cam(\d+)_/)?.[1] ?? "?";
  document.getElementById("cam1-label").textContent = `Camera ${camIdx} (primary)`;

  let siblingPath = null;
  try {
    const sr = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoRel)}`);
    if (sr.ok) {
      const sd = await sr.json();
      siblingPath = sd.sibling_video_path || null;
    }
  } catch (e) { console.warn("[dlc_3d] sibling-camera fetch failed:", e); }

  if (siblingPath) {
    const sibCamIdx = siblingPath.match(/_cam(\d+)_/)?.[1] ?? "?";
    document.getElementById("cam2-label").textContent = `Camera ${sibCamIdx} (sibling)`;
  }

  _setStatus("");
  await openPlayer(videoRel, siblingPath);
  _refreshLabeledFrames();
}

// ── Extract ───────────────────────────────────────────────────────────────────

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

  if (data.saved && data.saved.length > 0) {
    _setStatus(`Saved: ${data.saved.join(", ")}`);
  } else if (data.skipped && data.skipped.length > 0) {
    _setStatus(`Frame ${primaryFrame} already extracted — skipped.`);
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
  document.getElementById("btn-open-frame-extractor")?.addEventListener("click", _openCard);
  document.getElementById("btn-close-3d-extract")?.addEventListener("click", _closeCard);
  document.getElementById("ep-extract-btn")?.addEventListener("click", _extractFrame);

  const activePathEl = document.getElementById("dlc-active-path");
  if (activePathEl) {
    new MutationObserver(() => {
      const newPath = activePathEl.textContent.trim();
      _resetExtractorUI();
      if (newPath) _loadProject(newPath);
    }).observe(activePathEl, { childList: true, characterData: true, subtree: true });
  }
});
