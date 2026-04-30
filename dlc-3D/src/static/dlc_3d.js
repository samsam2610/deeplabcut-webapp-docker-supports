// dlc_3d.js — session browser, project loader, extract button handler.
"use strict";

import { openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled } from "./enhanced_player.js";

// ── State ─────────────────────────────────────────────────────────────────────

let _projectPath   = null;
let _sessions      = {};
let _activeSession = null;
let _activeVideo   = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function _setStatus(msg) {
  document.getElementById("extract-status").textContent = msg;
}

function _camColorClass(filename) {
  const m = filename.match(/img_cam(\d)_/);
  return m ? `cam${m[1]}` : "";
}

// ── Card open / close ─────────────────────────────────────────────────────────

function _openCard() {
  document.querySelectorAll(".card:not(#dlc-3d-extract-card)").forEach(c => c.classList.add("hidden"));
  document.getElementById("dlc-3d-extract-card").classList.remove("hidden");
}

function _closeCard() {
  document.getElementById("dlc-3d-extract-card").classList.add("hidden");
  document.querySelectorAll(".card:not(#dlc-3d-extract-card)").forEach(c => c.classList.remove("hidden"));
}

// ── Project loading ───────────────────────────────────────────────────────────

async function _loadProject(path) {
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

  _projectPath = data.project_path;
  _sessions    = data.sessions || {};

  document.getElementById("dlc3d-project-path").textContent = _projectPath;
  document.getElementById("dlc3d-btn-rescan").style.display = "";
  document.getElementById("dlc3d-player-section").style.display = "";
  _setStatus("");
  _renderSessions();
}

// ── Session browser rendering ─────────────────────────────────────────────────

function _renderSessions() {
  const panel = document.getElementById("dlc3d-session-panel");
  const empty = document.getElementById("dlc3d-session-empty");

  if (!_sessions || Object.keys(_sessions).length === 0) {
    panel.innerHTML = "";
    if (empty) { empty.textContent = "No multi-camera videos found."; panel.appendChild(empty); }
    return;
  }
  if (empty) empty.remove();

  panel.innerHTML = "";
  for (const [sessionKey, cams] of Object.entries(_sessions).sort()) {
    const group  = document.createElement("div");
    group.className = "session-group";

    const header = document.createElement("div");
    header.className = "session-header";
    header.textContent = "▶ " + sessionKey;
    group.appendChild(header);

    const body = document.createElement("div");
    body.className = "session-body";

    for (const [camKey, camData] of Object.entries(cams).sort()) {
      const camRow = document.createElement("div");
      camRow.className = "cam-row";
      camRow.dataset.videoRel = camData.avi;
      camRow.innerHTML = `<span class="cam-badge">${camKey}</span><span>${camData.avi.split("/").pop()}</span>`;
      camRow.addEventListener("click", () => _selectVideo(camData.avi, sessionKey));
      body.appendChild(camRow);

      if (camData.clips && camData.clips.length > 0) {
        const clipSection = document.createElement("div");
        clipSection.className = "clip-section";
        const clipHeader = document.createElement("div");
        clipHeader.className = "clip-header";
        clipHeader.textContent = `${camData.clips.length} clip(s)`;
        clipSection.appendChild(clipHeader);
        for (const clipPath of camData.clips) {
          const clipRow = document.createElement("div");
          clipRow.className = "clip-row";
          clipRow.dataset.videoRel = clipPath;
          clipRow.textContent = clipPath.split("/").pop();
          clipRow.addEventListener("click", () => _selectVideo(clipPath, sessionKey));
          clipSection.appendChild(clipRow);
        }
        body.appendChild(clipSection);
      }
    }

    header.addEventListener("click", () => {
      body.classList.toggle("open");
      header.textContent = (body.classList.contains("open") ? "▼ " : "▶ ") + sessionKey;
    });

    group.appendChild(body);
    panel.appendChild(group);
  }
}

// ── Video selection ───────────────────────────────────────────────────────────

async function _selectVideo(videoRel, sessionKey) {
  _activeVideo   = videoRel;
  _activeSession = sessionKey;

  document.querySelectorAll(".cam-row, .clip-row").forEach(el => {
    el.classList.toggle("active", el.dataset.videoRel === videoRel);
  });

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

  const wrap    = document.getElementById("labeled-wrap");
  const countEl = document.getElementById("labeled-count");
  const list    = document.getElementById("labeled-list");

  countEl.textContent = data.count || 0;
  list.innerHTML = "";

  for (const fname of data.frames || []) {
    const chip = document.createElement("span");
    chip.className = "frame-chip " + _camColorClass(fname);
    chip.textContent = fname;
    list.appendChild(chip);
  }

  wrap.style.display = data.count > 0 ? "" : "none";
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
  // Inject "3D Frame Extractor" button into DLC session bar
  const dlcBarBtns = document.querySelector("#dlc-bar .session-btns");
  if (dlcBarBtns) {
    const btn = document.createElement("button");
    btn.className = "btn-sm btn-create";
    btn.id = "btn-open-3d-extract";
    btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="12" cy="12" r="4"/></svg> 3D Frame Extractor`;
    dlcBarBtns.appendChild(btn);
    btn.addEventListener("click", _openCard);
  }

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
});
