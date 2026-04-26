// State
let selectedVideoPath = null;
let currentJobId = null;
let eventSource = null;
const detections = [];

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadTemplate();
  loadVideos();
});

// ── Template bank ─────────────────────────────────────────────────────────────

async function loadTemplate() {
  const resp = await fetch("/clip-cutter/template");
  const data = await resp.json();
  renderTemplate(data);
}

function renderTemplate(data) {
  const grid = document.getElementById("template-grid");
  const footer = document.getElementById("template-footer");
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
  setStatus("Starting template build…");
  try {
    const resp = await fetch("/clip-cutter/template/init", { method: "POST" });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: resp.statusText }));
      setStatus("Init error: " + err.error);
      return;
    }
    setStatus("Building template from training clips — this may take a minute…");
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
        setStatus(`Template initialised: ${data.count} frame${data.count !== 1 ? "s" : ""}`);
      } else {
        setStatus(`Building template… ${data.count} frame${data.count !== 1 ? "s" : ""} embedded so far`);
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

// ── Video list ─────────────────────────────────────────────────────────────────

async function loadVideos() {
  const resp = await fetch("/clip-cutter/videos");
  const data = await resp.json();
  renderVideos(data.videos);
}

function renderVideos(videos) {
  const list = document.getElementById("video-list");
  list.innerHTML = "";
  videos.forEach((v) => {
    const row = document.createElement("div");
    row.className = "video-row" + (v.done ? " done" : "");
    row.innerHTML = `
      <span class="video-name" title="${esc(v.path)}">${esc(v.name)}</span>
      <span class="badge ${v.done ? "badge-done" : "badge-pending"}">${v.done ? "done" : "ready"}</span>`;
    if (!v.done) {
      row.addEventListener("click", () => selectVideo(v.path, row));
    }
    list.appendChild(row);
  });
}

async function selectVideo(path, rowEl) {
  document.querySelectorAll(".video-row").forEach((r) => r.classList.remove("selected"));
  rowEl.classList.add("selected");
  selectedVideoPath = path;
  document.getElementById("scan-btn").disabled = false;
  detections.length = 0;
  document.getElementById("results-list").innerHTML = "";
  document.getElementById("results-count").textContent = "";
  await loadSavedDetections(path);
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
      body: JSON.stringify({ video_path: selectedVideoPath }),
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

const PIPELINE_PHASES = ["coarse", "peak_detection", "fine"];

const PHASE_LABELS = {
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
  } else {
    document.getElementById("progress-text").textContent =
      `Coarse scan — frame ${job.current.toLocaleString()} / ${job.total.toLocaleString()}`;
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
}

function buildResultCard(d, idx) {
  const videoName = d.video_path.split("/").pop().replace(".avi", "");
  const pre = 200, post = 600;
  const clipName = `${videoName}_${d.frame_number - pre}_${d.frame_number + post - 1}`;
  const isKnown = !!d.known_match;

  const card = document.createElement("div");
  card.className = "result-card" + (isKnown ? "" : " new");
  card.id = `card-${idx}`;

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
