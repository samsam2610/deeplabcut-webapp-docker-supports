// State
let selectedVideoPath = null;
let currentJobId = null;
let eventSource = null;
const detections = [];
let currentFilter = "sensor+clip";

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

function applyFilter() {
  document.querySelectorAll(".result-card").forEach((card) => {
    const src = card.dataset.source || "";
    const visible =
      currentFilter === "all" ||
      (currentFilter === "sensor+clip" && src === "sensor+clip") ||
      (currentFilter === "clip_only" && src === "clip_only");
    card.style.display = visible ? "" : "none";
  });
}

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadTemplate();
  const _savedPath = (() => { try { return localStorage.getItem("cc-browser-path"); } catch { return null; } })();
  loadFolder(_savedPath || null);

  // Settings toggle
  const settingsToggle = document.getElementById("settings-toggle");
  const settingsBody = document.getElementById("settings-body");
  if (settingsToggle && settingsBody) {
    settingsToggle.setAttribute("aria-expanded", "false");
    settingsBody.style.display = "none";
    settingsToggle.addEventListener("click", () => {
      const open = settingsToggle.getAttribute("aria-expanded") === "true";
      settingsBody.style.display = open ? "none" : "block";
      settingsToggle.setAttribute("aria-expanded", String(!open));
    });
  }

  // Tab switching
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.style.display = p.id === `tab-${tab}` ? "block" : "none";
      });
    });
  });

  // Reset defaults
  const resetBtn = document.getElementById("settings-reset");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      document.getElementById("trigger-value").value = "14";
      document.getElementById("sensor-margin").value = "25";
      document.getElementById("scan-stride").value = "10";
      document.getElementById("scan-threshold").value = "0.70";
      document.getElementById("min-spacing").value = "900";
      document.getElementById("fine-window").value = "50";
      document.getElementById("scan-threshold").dispatchEvent(new Event("input"));
    });
  }

  // Threshold slider live label
  const thresholdInput = document.getElementById("scan-threshold");
  const thresholdLabel = document.getElementById("threshold-label");
  if (thresholdInput && thresholdLabel) {
    thresholdInput.addEventListener("input", () => {
      thresholdLabel.textContent = parseFloat(thresholdInput.value).toFixed(2);
    });
  }

  // Source filter buttons
  document.querySelectorAll(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentFilter = btn.dataset.filter;
      document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      applyFilter();
    });
  });

  // Sidebar init button
  document.getElementById("sidebar-init-btn").addEventListener("click", initTemplate);

  // Browse frames buttons (no-template state and has-template state)
  document.getElementById("sidebar-browse-btn").addEventListener("click", () => {
    if (typeof openTemplatePlayer === "function") openTemplatePlayer();
  });
  document.getElementById("sidebar-browse-btn2").addEventListener("click", () => {
    if (typeof openTemplatePlayer === "function") openTemplatePlayer();
  });

  // Clear button — open confirmation modal
  document.getElementById("sidebar-clear-btn").addEventListener("click", () => {
    document.getElementById("clear-confirm-input").value = "";
    document.getElementById("clear-confirm-btn").disabled = true;
    document.getElementById("clear-confirm-modal").classList.add("open");
  });

  // Clear modal — type "delete" to enable confirm button
  document.getElementById("clear-confirm-input").addEventListener("input", (e) => {
    document.getElementById("clear-confirm-btn").disabled = e.target.value !== "delete";
  });

  // Clear modal — cancel
  document.getElementById("clear-cancel-btn").addEventListener("click", () => {
    document.getElementById("clear-confirm-modal").classList.remove("open");
  });

  // Clear modal — confirm
  document.getElementById("clear-confirm-btn").addEventListener("click", async () => {
    document.getElementById("clear-confirm-modal").classList.remove("open");
    const resp = await fetch("/clip-cutter/template/clear", { method: "POST" });
    if (resp.ok) {
      await loadTemplate();
      setStatus("Template cleared");
    } else {
      setStatus("Clear failed");
    }
  });
});

// ── Template bank ─────────────────────────────────────────────────────────────

async function loadTemplate() {
  const resp = await fetch("/clip-cutter/template");
  const data = await resp.json();
  renderTemplate(data);
}

function renderTemplate(data) {
  const emptyState = document.getElementById("sidebar-empty-state");
  const noTemplate = document.getElementById("sidebar-no-template");
  const noTemplateMsg = document.getElementById("sidebar-no-template-msg");
  const grid = document.getElementById("template-grid");
  const footer = document.getElementById("template-footer");
  const initBtn = document.getElementById("sidebar-init-btn");
  const sidebarActions = document.getElementById("sidebar-actions");

  if (!_selectedVideoStem) {
    emptyState.style.display = "";
    noTemplate.style.display = "none";
    grid.style.display = "none";
    footer.style.display = "none";
    initBtn.style.display = "none";
    sidebarActions.style.display = "none";
    return;
  }

  emptyState.style.display = "none";
  initBtn.style.display = "";

  if (!data.has_template) {
    noTemplate.style.display = "";
    noTemplateMsg.textContent = `No template for ${_selectedVideoStem}`;
    grid.style.display = "none";
    footer.style.display = "none";
    sidebarActions.style.display = "none";
    return;
  }

  noTemplate.style.display = "none";
  grid.style.display = "flex";
  footer.style.display = "";
  sidebarActions.style.display = "flex";

  grid.innerHTML = "";
  data.frames.forEach((f, idx) => {
    const div = document.createElement("div");
    div.className = "thumb";
    div.title = `${f.video_path} frame ${f.frame_number}\nClick to remove`;
    div.innerHTML = `<img src="data:image/jpeg;base64,${f.thumbnail}"><span class="thumb-label">fr${f.frame_number}</span>`;
    div.addEventListener("click", () => removeTemplateFrame(idx));
    grid.appendChild(div);
  });
  footer.textContent = `${data.count} frame${data.count !== 1 ? "s" : ""} loaded`;
}

async function initTemplate() {
  if (document.getElementById("template-grid").style.display !== "none") {
    // Template already exists — confirm re-init
    if (!confirm(`Re-initialise template for ${_selectedVideoStem}? This will replace the current template.`)) return;
  }
  setStatus("Starting template build…");
  try {
    const resp = await fetch("/clip-cutter/template/init", { method: "POST" });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      setStatus("Init error: " + err.error);
      return;
    }
    setStatus("Building template from clips — this may take a minute…");
    pollInitStatus();
  } catch (err) {
    setStatus("Network error: " + err.message);
  }
}

function pollInitStatus() {
  const iv = setInterval(async () => {
    try {
      const resp = await fetch("/clip-cutter/template/init/status");
      const data = await resp.json();
      if (data.error) {
        clearInterval(iv);
        setStatus("Init error: " + data.error);
        return;
      }
      if (!data.running) {
        clearInterval(iv);
        await loadTemplate();
        setStatus(`Template initialised: ${data.count} frame${data.count !== 1 ? "s" : ""} — browse to add more`);
        openTemplatePlayer();
      } else {
        setStatus(`Building template… ${data.count} frame${data.count !== 1 ? "s" : ""} embedded`);
      }
    } catch (err) {
      clearInterval(iv);
      setStatus("Network error while polling: " + err.message);
    }
  }, 2000);
}

async function removeTemplateFrame(idx) {
  if (!confirm("Remove this frame from the template?")) return;
  await fetch(`/clip-cutter/template/${idx}`, { method: "DELETE" });
  await loadTemplate();
}

async function addToTemplate(videoPath, frameNumber) {
  const resp = await fetch("/clip-cutter/template/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath, frame_number: frameNumber }),
  });
  if (resp.ok) {
    await loadTemplate();
    setStatus(`Frame ${frameNumber} added to template`);
  } else {
    const err = await resp.json();
    setStatus("Error: " + err.error);
  }
}

// ── Folder browser ────────────────────────────────────────────────────────────

let _browserCurrentPath = null;
let _selectedVideoStem = null;
let _selectedVideoParent = null;

async function loadFolder(path) {
  const url = path
    ? `/clip-cutter/fs/ls?path=${encodeURIComponent(path)}`
    : "/clip-cutter/fs/ls";
  const resp = await fetch(url);
  if (!resp.ok) { setStatus("Cannot open folder"); return; }
  const data = await resp.json();
  _browserCurrentPath = data.path;
  try { localStorage.setItem("cc-browser-path", data.path); } catch {}
  renderBrowser(data);
}

function renderBrowser(data) {
  // Breadcrumb
  const bc = document.getElementById("browser-breadcrumb");
  bc.innerHTML = "";
  const parts = data.path.split("/").filter(Boolean);
  parts.forEach((part, i) => {
    if (i > 0) {
      const sep = document.createElement("span");
      sep.className = "bc-sep";
      sep.textContent = " / ";
      bc.appendChild(sep);
    }
    const seg = document.createElement("span");
    const isLast = i === parts.length - 1;
    seg.className = isLast ? "bc-current" : "bc-segment";
    seg.textContent = part;
    if (!isLast) {
      const fullPath = "/" + parts.slice(0, i + 1).join("/");
      seg.addEventListener("click", () => loadFolder(fullPath));
    }
    bc.appendChild(seg);
  });

  // Up button
  const upBtn = document.getElementById("browser-up");
  upBtn.disabled = !data.parent;
  upBtn.onclick = () => { if (data.parent) loadFolder(data.parent); };

  // Entries
  const list = document.getElementById("browser-list");
  list.innerHTML = "";
  data.entries.forEach((entry) => {
    const row = document.createElement("div");
    row.className = "browser-row";
    const icon = document.createElement("span");
    icon.className = "browser-icon";
    const name = document.createElement("span");
    name.className = "browser-name";
    name.textContent = entry.name;
    row.appendChild(icon);
    row.appendChild(name);

    if (entry.type === "dir") {
      icon.textContent = "📁";
      row.addEventListener("click", () => loadFolder(data.path + "/" + entry.name));
    } else {
      icon.textContent = "▶";
      const badge = document.createElement("span");
      badge.className = `badge ${entry.done ? "badge-done" : "badge-pending"}`;
      badge.textContent = entry.done ? "done" : "ready";
      row.appendChild(badge);
      row.addEventListener("click", () => {
        document.querySelectorAll(".browser-row.selected").forEach((r) =>
          r.classList.remove("selected")
        );
        row.classList.add("selected");
        const videoPath = data.path + "/" + entry.name;
        const stem = entry.name.replace(/\.avi$/i, "");
        selectVideo(videoPath, stem, data.path);
      });
    }
    list.appendChild(row);
  });
}

async function selectVideo(videoPath, stem, parent) {
  selectedVideoPath = videoPath;
  _selectedVideoStem = stem;
  _selectedVideoParent = parent;

  await fetch("/clip-cutter/select-video", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath }),
  });

  document.getElementById("scan-btn").disabled = false;
  detections.length = 0;
  document.getElementById("results-list").innerHTML = "";
  document.getElementById("results-count").textContent = "";

  await loadTemplate();
  await loadSavedDetections(videoPath);
}

// ── Persistence ───────────────────────────────────────────────────────────────

async function saveDetections() {
  if (!selectedVideoPath || detections.length === 0) return;
  try {
    const resp = await fetch("/clip-cutter/detections", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_path: selectedVideoPath, detections }),
    });
    if (!resp.ok) console.warn("saveDetections: server returned", resp.status);
  } catch (e) {
    console.warn("saveDetections failed:", e);
  }
}

async function loadSavedDetections(videoPath) {
  try {
    const resp = await fetch(
      `/clip-cutter/detections?video=${encodeURIComponent(videoPath)}`
    );
    if (!resp.ok) return false;
    if (videoPath !== selectedVideoPath) return false;
    const data = await resp.json();
    detections.length = 0;
    renderDetections(data.detections);
    applyFilter();
    return true;
  } catch {
    return false;
  }
}

// ── Scan ──────────────────────────────────────────────────────────────────────

async function startScan() {
  if (!selectedVideoPath) return;
  document.getElementById("scan-btn").disabled = true;
  document.getElementById("results-list").innerHTML = "";
  document.getElementById("results-count").textContent = "";
  detections.length = 0;

  try {
    const resp = await fetch("/clip-cutter/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: selectedVideoPath,
        params: {
          trigger_value: parseInt(document.getElementById("trigger-value").value, 10),
          sensor_margin: parseInt(document.getElementById("sensor-margin").value, 10),
          stride: parseInt(document.getElementById("scan-stride").value, 10),
          threshold: parseFloat(document.getElementById("scan-threshold").value),
          min_spacing: parseInt(document.getElementById("min-spacing").value, 10),
          fine_window: parseInt(document.getElementById("fine-window").value, 10),
        },
      }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      setStatus("Error: " + err.error);
      document.getElementById("scan-btn").disabled = false;
      return;
    }
    const { job_id } = await resp.json();
    currentJobId = job_id;
    listenToScan(job_id);
  } catch (err) {
    setStatus("Network error: " + err.message);
    document.getElementById("scan-btn").disabled = false;
  }
}

function listenToScan(jobId) {
  const progressSection = document.getElementById("progress-section");
  progressSection.style.display = "block";
  resetPipelineStrip();
  setStatus("Scanning…");

  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/clip-cutter/scan/stream?job_id=${jobId}`);

  eventSource.onmessage = async (e) => {
    const job = JSON.parse(e.data);
    updateProgress(job);
    if (job.status === "done") {
      eventSource.close();
      PIPELINE_PHASES.forEach((p) => {
        const stepEl = document.querySelector(`.pipeline-step[data-phase="${p}"]`);
        if (stepEl) { stepEl.classList.remove("active"); stepEl.classList.add("done"); }
      });
      document.querySelectorAll(".pipeline-connector").forEach((el) => el.classList.add("done"));
      progressSection.style.display = "none";
      renderDetections(job.detections);
      currentFilter = "sensor+clip";
      document.querySelectorAll(".filter-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.filter === "sensor+clip");
      });
      applyFilter();
      await saveDetections();
      document.getElementById("scan-btn").disabled = false;
      setStatus(`Scan complete — ${job.detections.length} detection${job.detections.length !== 1 ? "s" : ""}`);
    } else if (job.status === "error") {
      eventSource.close();
      progressSection.style.display = "none";
      setStatus("Scan error: " + job.error);
      document.getElementById("scan-btn").disabled = false;
    }
  };
}

const PIPELINE_PHASES = ["sensor_parse", "coarse", "peak_detection", "fine"];

const PHASE_LABELS = {
  sensor_parse: "Sensor parse",
  coarse: "Coarse scan",
  peak_detection: "Peak detection",
  fine: "Fine scan",
};

function updateProgress(job) {
  const pct = job.total > 0 ? Math.round((job.current / job.total) * 100) : 0;
  document.getElementById("progress-fill").style.width = pct + "%";
  document.getElementById("progress-pct").textContent = pct + "%";

  const phase = job.phase || "coarse";
  const phaseIdx = PIPELINE_PHASES.indexOf(phase);

  PIPELINE_PHASES.forEach((p, i) => {
    const stepEl = document.querySelector(`.pipeline-step[data-phase="${p}"]`);
    if (!stepEl) return;
    stepEl.classList.remove("active", "done");
    if (i < phaseIdx) stepEl.classList.add("done");
    else if (i === phaseIdx) stepEl.classList.add("active");
  });

  document.querySelectorAll(".pipeline-connector[data-after]").forEach((el) => {
    const afterPhase = el.dataset.after;
    const afterIdx = PIPELINE_PHASES.indexOf(afterPhase);
    el.classList.toggle("done", afterIdx < phaseIdx);
  });

  if (phase === "peak_detection") {
    document.getElementById("progress-text").textContent = "Detecting peaks…";
  } else if (phase === "fine") {
    const label = job.total > 0
      ? `Fine scan — ${job.current} / ${job.total} candidate${job.total !== 1 ? "s" : ""}`
      : "Fine scan…";
    document.getElementById("progress-text").textContent = label;
  } else if (phase === "sensor_parse") {
    document.getElementById("progress-text").textContent = "Parsing sensor data…";
  } else {
    document.getElementById("progress-text").textContent =
      `Coarse scan — frame ${(job.current ?? 0).toLocaleString()} / ${(job.total ?? 0).toLocaleString()}`;
  }
}

function resetPipelineStrip() {
  PIPELINE_PHASES.forEach((p) => {
    const stepEl = document.querySelector(`.pipeline-step[data-phase="${p}"]`);
    if (stepEl) stepEl.classList.remove("active", "done");
  });
  document.querySelectorAll(".pipeline-connector").forEach((el) => el.classList.remove("done"));
}

// ── Results ───────────────────────────────────────────────────────────────────

function renderDetections(dets) {
  const list = document.getElementById("results-list");
  const count = document.getElementById("results-count");
  list.innerHTML = "";
  count.textContent = `${dets.length} found`;

  dets.forEach((d) => {
    if (!d.video_path) d.video_path = selectedVideoPath;
    if (!d.status) d.status = "pending";
    detections.push(d);
    const card = buildResultCard(d, detections.length - 1);
    if (d.status === "kept") {
      card.classList.add("kept");
      card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    } else if (d.status === "rejected") {
      card.classList.add("rejected");
      card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    }
    list.appendChild(card);
  });
  applyFilter();
}

function buildResultCard(d, idx) {
  const videoName = d.video_path.split("/").pop().replace(".avi", "");
  const pre = 200, post = 600;
  const clipName = `${videoName}_${d.frame_number - pre}_${d.frame_number + post - 1}`;
  const isKnown = !!d.known_match;

  const card = document.createElement("div");
  card.className = "result-card" + (isKnown ? "" : " new");
  card.id = `card-${idx}`;
  card.dataset.source = d.source || "";

  // Build inner structure with safe static skeleton
  card.innerHTML = `
    <div class="result-meta">
      <div class="result-name"></div>
      <div class="result-info">
        Key frame <span class="kf-num"></span> &middot;
        <span class="match-pill ${isKnown ? "match-known" : "match-new"}"></span>
      </div>
      <div class="result-actions">
        <button class="btn-sm btn-green keep-btn">&#10003; Keep</button>
        <button class="btn-sm btn-red reject-btn">&#10007; Reject</button>
        <button class="btn-sm btn-blue add-btn">+ Add to template</button>
      </div>
    </div>
    <span class="sim-pill"></span>`;

  // Populate text content safely
  card.querySelector(".result-name").textContent = clipName + ".avi";
  card.querySelector(".kf-num").textContent = d.frame_number.toLocaleString();
  card.querySelector(".match-pill").textContent = isKnown
    ? "✓ matches " + d.known_match
    : "new detection";
  card.querySelector(".sim-pill").textContent = d.similarity.toFixed(2);

  // Source badge
  if (d.source && d.source !== "pending") {
    const badge = document.createElement("span");
    badge.className = "source-badge";
    if (d.source === "sensor+clip") {
      badge.classList.add("source-sensor-clip");
      badge.textContent = "✓ sensor+CLIP";
    } else if (d.source === "sensor_only") {
      badge.classList.add("source-sensor-only");
      badge.textContent = "sensor only";
    } else if (d.source === "clip_only") {
      badge.classList.add("source-clip-only");
      badge.textContent = "CLIP only";
    }
    card.querySelector(".result-meta").appendChild(badge);
  }

  // Attach event listeners (no onclick attributes with embedded data)
  card.querySelector(".keep-btn").addEventListener("click", () => keepDetection(idx));
  card.querySelector(".reject-btn").addEventListener("click", () => rejectDetection(idx));
  card.querySelector(".add-btn").addEventListener("click", () =>
    addToTemplate(d.video_path, d.frame_number)
  );

  card.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    document.querySelectorAll(".result-card").forEach((c) => c.classList.remove("active-preview"));
    card.classList.add("active-preview");
    if (typeof loadClip === "function") loadClip(d.video_path, d.frame_number);
  });

  return card;
}

async function keepDetection(idx) {
  const d = detections[idx];
  const resp = await fetch("/clip-cutter/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: d.video_path, key_frame: d.frame_number }),
  });
  if (resp.ok) {
    detections[idx].status = "kept";
    const card = document.getElementById(`card-${idx}`);
    card.classList.add("kept");
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    setStatus(`Clip extracted for frame ${d.frame_number}`);
    await saveDetections();
  } else {
    const err = await resp.json();
    setStatus("Error: " + err.error);
  }
}

async function rejectDetection(idx) {
  detections[idx].status = "rejected";
  const card = document.getElementById(`card-${idx}`);
  card.classList.add("rejected");
  card.querySelectorAll("button").forEach((b) => (b.disabled = true));
  await saveDetections();
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}
