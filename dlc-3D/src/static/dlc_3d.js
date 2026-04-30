// dlc_3d.js — session browser, project loader, extract button handler.
"use strict";

import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath   = null;
let _sessions      = {};
let _activeSession = null;
let _activeVideo   = null;
let _loadToken     = 0;

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setStatus(msg) {
  const el = document.getElementById("extract-status");
  if (el) el.textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

// ── Extractor reset ───────────────────────────────────────────────────────────

function _resetExtractorUI() {
  _projectPath   = null;
  _sessions      = {};
  _activeVideo   = null;
  _activeSession = null;

  document.getElementById("dlc3d-player-section").style.display = "none";
  const list = document.getElementById("dlc3d-video-list");
  list.innerHTML     = "";
  list.style.display = "none";
  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) { empty.style.display = ""; empty.textContent = "Load a project to see sessions."; }
  document.getElementById("dlc3d-project-path").textContent = "No project loaded";
  document.getElementById("dlc3d-btn-rescan").style.display = "none";
  _setStatus("");
  const labeledWrap = document.getElementById("labeled-wrap");
  if (labeledWrap) labeledWrap.style.display = "none";
}

// ── Card open / close ─────────────────────────────────────────────────────────

function _openCard() {
  document.querySelectorAll(".card:not(#dlc-3d-extract-card)").forEach(c => c.classList.add("hidden"));
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
  _sessions    = data.sessions || {};

  document.getElementById("dlc3d-project-path").textContent = _projectPath;
  document.getElementById("dlc3d-btn-rescan").style.display = "";
  _setStatus("");
  _renderSessions();
  // Player section stays hidden until a camera row is clicked
}

// ── Session / camera list rendering ──────────────────────────────────────────

function _renderSessions() {
  const list  = document.getElementById("dlc3d-video-list");
  const empty = document.getElementById("dlc3d-session-empty");

  if (!_sessions || Object.keys(_sessions).length === 0) {
    list.innerHTML = "";
    list.style.display = "none";
    if (empty) { empty.style.display = ""; empty.textContent = "No multi-camera videos found."; }
    return;
  }

  if (empty) empty.style.display = "none";
  list.innerHTML = "";
  list.style.display = "";

  for (const [sessionKey, cams] of Object.entries(_sessions).sort()) {
    // Session header (non-clickable label)
    const header = document.createElement("div");
    header.className = "dlc3d-session-header";
    header.textContent = sessionKey;
    list.appendChild(header);

    const camCount = Object.keys(cams).length;

    for (const [camKey, camData] of Object.entries(cams).sort()) {
      // Raw AVI row
      list.appendChild(_makeVideoItem(camData.avi, sessionKey, camCount > 1 ? camKey : null, false));

      // Clip rows (indented)
      for (const clipPath of (camData.clips || [])) {
        list.appendChild(_makeVideoItem(clipPath, sessionKey, null, true));
      }
    }
  }
}

function _makeVideoItem(videoRel, sessionKey, camBadgeText, isClip) {
  const item = document.createElement("div");
  item.className = "fe-video-item" + (isClip ? " dlc3d-clip-item" : "");
  item.dataset.videoRel   = videoRel;
  item.dataset.sessionKey = sessionKey;

  const videoSvg = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>`;
  const clipSvg  = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"/><polyline points="14 2 14 8 20 8"/></svg>`;

  const iconEl = document.createElement("span");
  iconEl.innerHTML = isClip ? clipSvg : videoSvg;
  item.appendChild(iconEl);

  if (camBadgeText) {
    const badge = document.createElement("span");
    badge.className = "dlc3d-cam-badge";
    badge.textContent = camBadgeText;
    item.appendChild(badge);
  }

  const nameSpan = document.createElement("span");
  nameSpan.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
  nameSpan.textContent = videoRel.split("/").pop();
  item.appendChild(nameSpan);

  item.addEventListener("click", () => _selectVideo(videoRel, sessionKey));
  return item;
}

// ── Video selection ───────────────────────────────────────────────────────────

async function _selectVideo(videoRel, sessionKey) {
  _activeVideo   = videoRel;
  _activeSession = sessionKey;

  // Mark the clicked item active, clear others
  document.querySelectorAll("#dlc3d-video-list .fe-video-item").forEach(el => {
    el.classList.toggle("active", el.dataset.videoRel === videoRel);
  });

  // Show the player section
  document.getElementById("dlc3d-player-section").style.display = "";

  // Update primary camera label
  const camIdx = videoRel.match(/_cam(\d+)_/)?.[1] ?? "?";
  document.getElementById("cam1-label").textContent = `Camera ${camIdx} (primary)`;

  // Fetch sibling camera
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

// ── Filesystem browser ────────────────────────────────────────────────────────

let _browserCurrentPath = null;

async function _browserNavigate(path) {
  let data;
  try {
    const url = path ? `/dlc-3d/browse?path=${encodeURIComponent(path)}` : "/dlc-3d/browse";
    const resp = await fetch(url);
    data = await resp.json();
    if (!resp.ok) { alert(data.error || "Browse error"); return; }
  } catch (e) { alert("Network error: " + e.message); return; }

  _browserCurrentPath = data.path;
  document.getElementById("dlc3d-browser-path-bar").textContent = data.path;

  const list = document.getElementById("dlc3d-browser-list");
  list.innerHTML = "";

  if (data.parent) {
    const upRow = document.createElement("div");
    upRow.className = "browser-entry browser-up";
    upRow.innerHTML = '<span class="entry-icon">↑</span> ..';
    upRow.addEventListener("click", () => _browserNavigate(data.parent));
    list.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    if (entry.type === "dir") {
      row.className = "browser-entry" + (entry.has_config ? " has-config" : "");
      const iconEl = document.createElement("span");
      iconEl.className = "entry-icon";
      iconEl.textContent = entry.has_config ? "📂" : "📁";
      const nameEl = document.createElement("span");
      nameEl.textContent = entry.name;
      row.append(iconEl, nameEl);
      row.addEventListener("click", () => _browserNavigate(_browserCurrentPath + "/" + entry.name));
      if (entry.has_config) {
        const selectBtn = document.createElement("button");
        selectBtn.className = "btn-sm";
        selectBtn.style.cssText = "margin-left:auto;font-size:.7rem;padding:.15rem .4rem";
        selectBtn.textContent = "Select";
        selectBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          _closeBrowser();
          _loadProject(_browserCurrentPath + "/" + entry.name);
        });
        row.appendChild(selectBtn);
      }
    } else if (entry.type === "yaml") {
      row.className = "browser-entry yaml";
      const iconEl2 = document.createElement("span");
      iconEl2.className = "entry-icon";
      iconEl2.textContent = "✓";
      const nameEl2 = document.createElement("span");
      nameEl2.textContent = entry.name;
      row.append(iconEl2, nameEl2);
      row.addEventListener("click", () => {
        _closeBrowser();
        _loadProject(_browserCurrentPath);
      });
    }
    list.appendChild(row);
  }
}

function _openBrowser() {
  document.getElementById("dlc3d-browser-modal").classList.add("open");
  _browserNavigate(null);
}

function _closeBrowser() {
  document.getElementById("dlc3d-browser-modal").classList.remove("open");
}

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Open 3D extractor card via the DLC Project card's "Extract Frames" button
  document.getElementById("btn-open-frame-extractor")?.addEventListener("click", _openCard);

  document.getElementById("btn-close-3d-extract")?.addEventListener("click", _closeCard);
  document.getElementById("dlc3d-btn-open-project")?.addEventListener("click", _openBrowser);
  document.getElementById("dlc3d-browser-close")?.addEventListener("click", _closeBrowser);
  document.getElementById("dlc3d-browser-modal")?.addEventListener("click", (e) => {
    if (e.target === document.getElementById("dlc3d-browser-modal")) _closeBrowser();
  });

  document.getElementById("dlc3d-btn-rescan")?.addEventListener("click", async () => {
    _setStatus("Rescanning…");
    try {
      const resp = await fetch("/dlc-3d/project/rescan", { method: "POST" });
      const data = await resp.json();
      if (!resp.ok) { _setStatus(data.error || "Rescan failed"); return; }
      _sessions = data.sessions || {};
      _renderSessions();
      _setStatus("Rescan complete.");
    } catch (e) { _setStatus("Rescan failed: " + e.message); }
  });

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
