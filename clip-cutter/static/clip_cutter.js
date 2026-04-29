// State
let selectedVideoPath = null;
let currentJobId = null;
let eventSource = null;
const detections = [];
let currentFilter = "sensor+clip";
let _activeBatchLibrary = null;   // name of expanded library card
let _activeBatchFolders = new Set();  // checked folder paths in expanded library
let _batchMode = false;
const _batchQueue = new Set();
let _libScanType   = "clips";       // "clips" | "template_frames"
let _libSensorMode = "clip_only";   // "clip_only" | "sensor+clip"
let _templateScanJobId = null;
let _libBatchScanEs = null;
let _libBatchScanJobId = null;

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

function applyFilter() {
  const sliderEl = document.getElementById("sim-slider");
  const threshold = sliderEl ? parseFloat(sliderEl.value) : 0;
  document.querySelectorAll(".result-card").forEach((card) => {
    const src = card.dataset.source || "";
    const sim = parseFloat(card.dataset.similarity ?? 0);
    const sourceOk =
      currentFilter === "all" ||
      (currentFilter === "sensor+clip" && src === "sensor+clip") ||
      (currentFilter === "clip_only" && src === "clip_only");
    card.style.display = sourceOk && sim >= threshold ? "" : "none";
  });
}

// ── Global libraries ──────────────────────────────────────────────────────────

async function loadLibraries() {
  const resp = await fetch("/clip-cutter/global-libraries");
  if (!resp.ok) { setStatus("Failed to load libraries"); return; }
  const { libraries, counts } = await resp.json();
  renderLibraries(libraries, counts || {});
}

function renderLibraries(libraries, counts) {
  const list = document.getElementById("lib-list");
  list.innerHTML = "";
  for (const [name, folders] of Object.entries(libraries)) {
    const card = document.createElement("div");
    card.className = "lib-card";
    const isActive = name === _activeBatchLibrary;
    const escapedName = esc(name);
    const counts = {};
    card.innerHTML = `
      <div class="lib-card-header">
        <span class="lib-name" title="${escapedName}">${escapedName}</span>
        <span class="lib-folder-count">${folders.length} folder${folders.length !== 1 ? "s" : ""}</span>
        <button class="player-btn lib-refresh-btn" title="Refresh frame counts">&#8635;</button>
        <button class="player-btn lib-delete-btn" title="Delete library">&#10005;</button>
      </div>
      <div class="lib-card-body${isActive ? " open" : ""}">
        <div class="lib-zone1">
          ${folders.map(p => {
            const escapedP = esc(p);
            const parts = p.split("/");
            const label = esc(parts[parts.length - 2] || parts[parts.length - 1]);
            const checked = _activeBatchFolders.has(p);
            const frameCount = counts[p] ?? "?";
            return `<div class="lib-folder-row">
              <input type="checkbox" class="lib-folder-check" data-path="${escapedP}" ${checked ? "checked" : ""}>
              <span class="lib-folder-label" title="${escapedP}">${label}</span>
              <span class="lib-folder-frames">${frameCount} fr</span>
              <button class="player-btn lib-folder-remove" data-path="${escapedP}" title="Remove folder">&#10005;</button>
            </div>`;
          }).join("")}
          <button class="player-btn lib-scan-btn" disabled>&#9654; Scan with checked (${
            folders.filter(p => _activeBatchFolders.has(p)).length
          })</button>
        </div>
        <div class="lib-zone1-handle"></div>
        <div class="lib-zone2" style="display:none;">
          <div class="lib-zone2-header"></div>
          <div class="lib-zone2-frames"></div>
        </div>
      </div>
    `;

    // Header click: expand/collapse
    card.querySelector(".lib-card-header").addEventListener("click", (e) => {
      if (e.target.closest(".lib-delete-btn") || e.target.closest(".lib-refresh-btn")) return;
      const body = card.querySelector(".lib-card-body");
      const opening = !body.classList.contains("open");
      // Collapse all
      document.querySelectorAll(".lib-card-body.open").forEach(b => b.classList.remove("open"));
      if (opening) {
        body.classList.add("open");
        _activeBatchLibrary = name;
        _activeBatchFolders = new Set(
          [...body.querySelectorAll(".lib-folder-check:checked")].map(cb => cb.dataset.path)
        );
      } else {
        _activeBatchLibrary = null;
        _activeBatchFolders = new Set();
      }
      updateBatchToolbar();
    });

    // Refresh frame counts
    card.querySelector(".lib-refresh-btn").addEventListener("click", () => loadLibraries());

    // Delete library
    card.querySelector(".lib-delete-btn").addEventListener("click", async () => {
      if (!confirm(`Delete library "${name}"?`)) return;
      await fetch(`/clip-cutter/global-libraries/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (_activeBatchLibrary === name) { _activeBatchLibrary = null; _activeBatchFolders = new Set(); }
      await loadLibraries();
    });

    // Folder checkboxes
    card.querySelectorAll(".lib-folder-check").forEach(cb => {
      cb.addEventListener("change", () => {
        if (cb.checked) _activeBatchFolders.add(cb.dataset.path);
        else _activeBatchFolders.delete(cb.dataset.path);
        const scanBtn = card.querySelector(".lib-scan-btn");
        scanBtn.textContent = `▶ Scan with checked (${_activeBatchFolders.size})`;
        updateBatchScanBtn();
      });
    });

    // Remove folder buttons
    card.querySelectorAll(".lib-folder-remove").forEach(btn => {
      btn.addEventListener("click", async () => {
        const p = btn.dataset.path;
        await fetch(`/clip-cutter/global-libraries/${encodeURIComponent(name)}/folders`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: p }),
        });
        _activeBatchFolders.delete(p);
        await loadLibraries();
      });
    });

    // Folder row click → load Zone 2
    const zone2El = card.querySelector(".lib-zone2");
    card.querySelectorAll(".lib-folder-row").forEach(row => {
      row.addEventListener("click", (e) => {
        if (e.target.closest(".lib-folder-check") || e.target.closest(".lib-folder-remove")) return;
        const path  = row.querySelector(".lib-folder-check").dataset.path;
        const label = row.querySelector(".lib-folder-label").textContent;
        card.querySelectorAll(".lib-folder-row").forEach(r => r.classList.remove("selected"));
        row.classList.add("selected");
        loadFolderFrames(path, label, zone2El);
      });
    });

    // Zone 1 drag handle
    const zone1El = card.querySelector(".lib-zone1");
    const handleEl = card.querySelector(".lib-zone1-handle");
    handleEl.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = zone1El.offsetHeight;
      const onMove = (me) => {
        zone1El.style.height = Math.max(56, Math.min(224, startH + me.clientY - startY)) + "px";
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    // Scan button
    card.querySelector(".lib-scan-btn").addEventListener("click", () => {
      if (_libScanType === "template_frames") startBatchTemplateScan();
      else startBatchScan();
    });

    list.appendChild(card);
  }
}

function updateBatchScanBtn() {
  const hasVideos = _batchQueue.size > 0 || selectedVideoPath !== null;
  document.querySelectorAll(".lib-scan-btn").forEach(btn => {
    btn.disabled = _activeBatchFolders.size === 0 || !hasVideos;
  });
}

async function startBatchScan() {
  const video_paths = _batchQueue.size > 0 ? [..._batchQueue] : (selectedVideoPath ? [selectedVideoPath] : []);
  if (_activeBatchFolders.size === 0 || video_paths.length === 0) return;
  const template_dirs = [..._activeBatchFolders];
  setStatus(`Starting batch scan: ${template_dirs.length} template source(s), ${video_paths.length} video(s)…`);
  const progressEl = document.getElementById("lib-scan-progress");
  const setProgress = (msg) => { progressEl.style.display = msg ? "" : "none"; progressEl.textContent = msg; };

  try {
    const resp = await fetch("/clip-cutter/batch-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_dirs,
        video_paths,
        params: {
          stride:      parseInt(document.getElementById("lib-scan-stride").value, 10),
          threshold:   parseFloat(document.getElementById("lib-scan-threshold").value),
          min_spacing: parseInt(document.getElementById("lib-scan-min-spacing").value, 10),
          fine_window: parseInt(document.getElementById("lib-scan-fine-window").value, 10),
          scan_mode:     _libSensorMode,
          trigger_value: parseInt(document.getElementById("lib-trigger-value").value, 10) || 14,
          sensor_margin: parseInt(document.getElementById("lib-sensor-margin").value, 10) || 25,
        },
      }),
    });
    if (!resp.ok) { setStatus("Batch scan error"); return; }
    const { job_id } = await resp.json();
    _libBatchScanJobId = job_id;
    try { localStorage.setItem("cc-active-job", JSON.stringify({ job_id, type: "batch-scan", video_paths })); } catch {}
    const es = new EventSource(`/clip-cutter/batch-scan/stream?job_id=${job_id}`);
    _libBatchScanEs = es;
    const cancelBtn = document.getElementById("lib-scan-cancel-btn");
    cancelBtn.style.display = "";
    cancelBtn.disabled = false;
    function finishBatchScan() {
      setProgress(""); cancelBtn.style.display = "none"; _libBatchScanEs = null; _libBatchScanJobId = null;
      try { localStorage.removeItem("cc-active-job"); } catch {}
    }
    es.onmessage = (e) => {
      const job = JSON.parse(e.data);
      if (job.phase === "done") {
        es.close();
        finishBatchScan();
        const allDetections = [];
        const videoErrors = [];
        (job.results || []).forEach(r => {
          (r.detections || []).forEach(d => {
            d.video_path = r.video;   // ensure correct video_path per detection
            allDetections.push(d);
          });
          if (r.error) videoErrors.push(`${r.video.split("/").pop()}: ${r.error}`);
        });
        // Persist each video's detections so they survive video switching
        const byVideo = {};
        allDetections.forEach(d => {
          if (!byVideo[d.video_path]) byVideo[d.video_path] = [];
          byVideo[d.video_path].push(d);
        });
        Object.entries(byVideo).forEach(([vp, dets]) => {
          fetch("/clip-cutter/detections", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_path: vp, detections: dets }),
          }).catch(() => {});
        });
        video_paths.forEach(vp => _setBrowserScanBadge(vp, "done-scan"));
        currentFilter = "all";
        renderDetections(allDetections);
        const total = allDetections.length;
        const errMsg = videoErrors.length ? ` (${videoErrors.length} error(s): ${videoErrors[0]})` : "";
        setStatus(`Batch scan done — ${total} detection${total !== 1 ? "s" : ""} across ${video_paths.length} video${video_paths.length !== 1 ? "s" : ""}${errMsg}`);
      } else if (job.phase === "error") {
        es.close();
        finishBatchScan();
        setStatus("Batch scan error: " + job.error);
      } else if (job.phase === "cancelled") {
        es.close();
        finishBatchScan();
        setStatus("Batch scan cancelled");
      } else {
        const msg = `${job.video || "…"} (${job.video_index || "?"}/${job.video_total || "?"}) — ${job.phase}`;
        setProgress(msg);
        setStatus(`Scanning ${msg}`);
        const idx = (job.video_index || 1) - 1;
        video_paths.forEach((vp, i) => {
          if (i < idx) _setBrowserScanBadge(vp, "done-scan");
          else if (i === idx) _setBrowserScanBadge(vp, "scanning");
        });
      }
    };
    es.onerror = () => { es.close(); finishBatchScan(); setStatus("Batch scan stream error"); };
  } catch (err) {
    setProgress("");
    setStatus("Network error: " + err.message);
  }
}

async function startBatchTemplateScan() {
  const video_paths = _batchQueue.size > 0 ? [..._batchQueue] : (selectedVideoPath ? [selectedVideoPath] : []);
  if (_activeBatchFolders.size === 0 || video_paths.length === 0) return;
  const template_dirs = [..._activeBatchFolders];
  setStatus(`Starting template scan: ${template_dirs.length} template source(s), ${video_paths.length} video(s)…`);
  const progressEl = document.getElementById("lib-scan-progress");
  const setProgress = (msg) => { progressEl.style.display = msg ? "" : "none"; progressEl.textContent = msg; };

  const oldBar = document.getElementById("rethreshold-bar");
  if (oldBar) oldBar.remove();

  try {
    const resp = await fetch("/clip-cutter/batch-template-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_dirs,
        video_paths,
        params: {
          scan_mode:     _libSensorMode,
          stride:        parseInt(document.getElementById("lib-scan-stride").value, 10),
          threshold:     parseFloat(document.getElementById("lib-scan-threshold").value),
          n_clusters:    parseInt(document.getElementById("lib-target-clusters").value, 10),
          trigger_value: parseInt(document.getElementById("lib-trigger-value").value, 10) || 14,
          sensor_margin: parseInt(document.getElementById("lib-sensor-margin").value, 10) || 25,
        },
      }),
    });
    if (!resp.ok) { setStatus("Template scan error"); return; }
    const { job_id } = await resp.json();
    _templateScanJobId = job_id;
    _libBatchScanJobId = job_id;
    try { localStorage.setItem("cc-active-job", JSON.stringify({ job_id, type: "batch-template-scan", video_paths })); } catch {}
    const es = new EventSource(`/clip-cutter/batch-template-scan/stream?job_id=${job_id}`);
    _libBatchScanEs = es;
    const cancelBtn = document.getElementById("lib-scan-cancel-btn");
    cancelBtn.style.display = "";
    cancelBtn.disabled = false;
    function finishTemplateScan() {
      setProgress(""); cancelBtn.style.display = "none"; _libBatchScanEs = null; _libBatchScanJobId = null;
      try { localStorage.removeItem("cc-active-job"); } catch {}
    }
    es.onmessage = (e) => {
      const job = JSON.parse(e.data);
      if (job.phase === "done") {
        es.close();
        finishTemplateScan();
        const allCandidates = [];
        const videoErrors = [];
        (job.results || []).forEach(r => {
          (r.candidates || []).forEach(c => allCandidates.push({ ...c, video_path: r.video_path }));
          if (r.error) videoErrors.push(`${r.video_path.split("/").pop()}: ${r.error}`);
        });
        video_paths.forEach(vp => _setBrowserScanBadge(vp, "done-scan"));
        renderTemplateCandidateCards(allCandidates);
        showRethresholdBar();   // always show — lets user adjust threshold even when 0 candidates
        const errMsg = videoErrors.length ? ` (${videoErrors.length} error(s): ${videoErrors[0]})` : "";
        setStatus(`Template scan done — ${allCandidates.length} candidate(s)${errMsg}`);
      } else if (job.phase === "error") {
        es.close();
        finishTemplateScan();
        setStatus("Template scan error: " + job.error);
      } else if (job.phase === "cancelled") {
        es.close();
        finishTemplateScan();
        setStatus("Template scan cancelled");
      } else {
        const msg = `${job.video || "…"} (${job.video_index || "?"}/${job.video_total || "?"}) — ${job.phase}`;
        setProgress(msg);
        const idx = (job.video_index || 1) - 1;
        video_paths.forEach((vp, i) => {
          if (i < idx) _setBrowserScanBadge(vp, "done-scan");
          else if (i === idx) _setBrowserScanBadge(vp, "scanning");
        });
      }
    };
    es.onerror = () => { es.close(); finishTemplateScan(); setStatus("Template scan stream error"); };
  } catch (err) {
    setProgress("");
    setStatus("Template scan error: " + err.message);
  }
}

function renderTemplateCandidateCards(candidates) {
  const list = document.getElementById("results-list");
  list.innerHTML = "";
  candidates.forEach((c) => {
    const videoName = c.video_path.split("/").pop().replace(/\.avi$/i, "");
    const card = document.createElement("div");
    card.className = "result-card";
    card.dataset.resultType = "template-candidate";
    const sensorBadge = _libSensorMode === "sensor+clip"
      ? `<span class="source-badge source-sensor-clip">sensor+clip</span>` : "";
    card.innerHTML = `
      <img class="result-thumb" src="/clip-cutter/frame?video=${encodeURIComponent(c.video_path)}&n=${c.frame_number - 1}" style="width:80px;height:60px;object-fit:cover;border-radius:3px;">
      <div class="result-info">
        <div class="result-title">${esc(videoName)}</div>
        <div class="result-sub">Frame ${esc(String(c.frame_number))} &middot; sim ${esc(c.similarity.toFixed(2))}</div>
        ${sensorBadge}
        <div style="display:flex;gap:4px;margin-top:4px;">
          <button class="player-btn tc-add-btn" data-video="${esc(c.video_path)}" data-frame="${esc(String(c.frame_number))}">Add to template</button>
          <button class="player-btn tc-skip-btn">Skip</button>
        </div>
      </div>
    `;

    card.querySelector(".tc-add-btn").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const r = await fetch("/clip-cutter/template-frame-add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_path: btn.dataset.video, frame_number: parseInt(btn.dataset.frame, 10) }),
        });
        if (r.ok) {
          const { count } = await r.json();
          btn.textContent = "Added";
          setStatus(`Frame ${btn.dataset.frame} added. Template now has ${count} frame(s).`);
          loadLibraries();
          loadTemplate();
        } else {
          btn.disabled = false;
          setStatus("Error adding frame to template");
        }
      } catch (err) {
        btn.disabled = false;
        setStatus("Network error: " + err.message);
      }
    });

    card.querySelector(".tc-skip-btn").addEventListener("click", (e) => {
      e.currentTarget.closest(".result-card").remove();
    });

    list.appendChild(card);
  });
}

function showRethresholdBar() {
  const resultsList = document.getElementById("results-list");
  const bar = document.createElement("div");
  bar.id = "rethreshold-bar";
  bar.style.cssText =
    "display:flex;align-items:center;gap:8px;padding:6px 8px;" +
    "background:#1c2128;border:1px solid #444c56;border-radius:4px;margin-bottom:6px;";
  const initVal = document.getElementById("lib-scan-threshold").value;
  bar.innerHTML = `
    <span style="font-size:10px;color:#768390;">Threshold</span>
    <input type="range" id="rethreshold-slider" min="0" max="1" step="0.01" value="${initVal}" style="flex:1;">
    <span id="rethreshold-label" style="font-size:10px;color:#cdd9e5;min-width:32px;">${parseFloat(initVal).toFixed(2)}</span>
    <button class="player-btn" id="rethreshold-apply">Apply</button>
  `;
  resultsList.parentElement.insertBefore(bar, resultsList);

  document.getElementById("rethreshold-slider").addEventListener("input", (e) => {
    document.getElementById("rethreshold-label").textContent = parseFloat(e.target.value).toFixed(2);
  });

  document.getElementById("rethreshold-apply").addEventListener("click", async (e) => {
    if (!_templateScanJobId) return;
    const applyBtn = e.currentTarget;
    applyBtn.disabled = true;
    const threshold  = parseFloat(document.getElementById("rethreshold-slider").value);
    const n_clusters = parseInt(document.getElementById("lib-target-clusters").value, 10);
    try {
      const r = await fetch(`/clip-cutter/batch-template-scan/${_templateScanJobId}/recluster`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold, n_clusters }),
      });
      if (!r.ok) { setStatus("Recluster error"); return; }
      const { results } = await r.json();
      const allCandidates = [];
      (results || []).forEach(rv => {
        (rv.candidates || []).forEach(c => allCandidates.push({ ...c, video_path: rv.video_path }));
      });
      renderTemplateCandidateCards(allCandidates);
    } catch (err) {
      setStatus("Recluster error: " + err.message);
    } finally {
      applyBtn.disabled = false;
    }
  });
}

async function loadFolderFrames(path, label, zone2El) {
  zone2El.style.display = "";
  const headerEl = zone2El.querySelector(".lib-zone2-header");
  const framesEl = zone2El.querySelector(".lib-zone2-frames");
  headerEl.textContent = `${label} — loading…`;
  framesEl.innerHTML = "";

  try {
    const r = await fetch(`/clip-cutter/library-folder-frames?path=${encodeURIComponent(path)}`);
    if (!r.ok) { headerEl.textContent = "Error loading frames"; return; }
    const { frames, count } = await r.json();
    headerEl.textContent = `${label} — ${count} frame${count !== 1 ? "s" : ""}`;

    frames.forEach(f => {
      const row = document.createElement("div");
      row.className = "lib-frame-row";
      row.innerHTML = `
        <img class="lib-frame-thumb" src="/clip-cutter/frame?video=${encodeURIComponent(f.video_path)}&n=${encodeURIComponent(f.frame_number - 1)}" width="48" height="36">
        <span class="lib-frame-num">fr ${esc(String(f.frame_number))}</span>
        <button class="player-btn lib-frame-view">View</button>
        <button class="player-btn lib-frame-del">Del</button>
      `;

      row.querySelector(".lib-frame-view").addEventListener("click", async () => {
        await openPlayer({ mode: "template", videoPath: f.video_path });
        _epLoadFrame(f.frame_number - 1);
      });

      row.querySelector(".lib-frame-del").addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        const r2 = await fetch("/clip-cutter/library-folder-frames", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, frame_number: f.frame_number }),
        });
        if (r2.ok) {
          const { count: newCount } = await r2.json();
          row.remove();
          headerEl.textContent = `${label} — ${newCount} frame${newCount !== 1 ? "s" : ""}`;
          loadLibraries();
        } else {
          btn.disabled = false;
        }
      });

      framesEl.appendChild(row);
    });
  } catch (err) {
    headerEl.textContent = "Error: " + err.message;
  }
}

function updateBatchToolbar() {
  const countEl  = document.getElementById("batch-count");
  const initBtn  = document.getElementById("batch-init-btn");
  const addFolderBtn = document.getElementById("batch-add-folder-btn");
  const toggleBtn = document.getElementById("batch-toggle");
  toggleBtn.classList.toggle("active", _batchMode);
  if (_batchMode && _batchQueue.size > 0) {
    countEl.style.display = "";
    countEl.textContent = `(${_batchQueue.size} selected)`;
    initBtn.style.display = "";
  } else {
    countEl.style.display = "none";
    initBtn.style.display = "none";
  }
  addFolderBtn.style.display = (_activeBatchLibrary !== null) ? "" : "none";
  updateBatchScanBtn();
}

async function startBatchInit() {
  if (_batchQueue.size === 0) return;
  const videos = [..._batchQueue];
  document.getElementById("batch-init-btn").disabled = true;
  setStatus(`Starting batch init for ${videos.length} video${videos.length !== 1 ? "s" : ""}…`);
  try {
    const resp = await fetch("/clip-cutter/batch-init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videos }),
    });
    if (!resp.ok) { setStatus("Batch init error"); document.getElementById("batch-init-btn").disabled = false; return; }
    const { job_id } = await resp.json();
    const es = new EventSource(`/clip-cutter/batch-init/stream?job_id=${job_id}`);
    es.onmessage = (e) => {
      const job = JSON.parse(e.data);
      if (job.phase === "done") {
        es.close();
        document.getElementById("batch-init-btn").disabled = false;
        const msg = `Batch init done: ${job.initialized} initialized` +
          (job.failed > 0 ? `, ${job.failed} failed` : "");
        setStatus(msg);
      } else {
        setStatus(`Initializing ${job.current}/${job.total}: ${job.video}…`);
      }
    };
    es.onerror = () => {
      es.close();
      document.getElementById("batch-init-btn").disabled = false;
      setStatus("Batch init stream error");
    };
  } catch (err) {
    document.getElementById("batch-init-btn").disabled = false;
    setStatus("Network error: " + err.message);
  }
}

// ── Reconnect active batch job after page refresh ────────────────────────────

function _reconnectActiveJob() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem("cc-active-job")); } catch {}
  if (!saved || !saved.job_id) return;

  const { job_id, type, video_paths } = saved;
  const isBatchScan = type === "batch-scan";
  const streamUrl = isBatchScan
    ? `/clip-cutter/batch-scan/stream?job_id=${job_id}`
    : `/clip-cutter/batch-template-scan/stream?job_id=${job_id}`;

  _libBatchScanJobId = job_id;
  if (!isBatchScan) _templateScanJobId = job_id;

  const progressEl = document.getElementById("lib-scan-progress");
  const setProgress = (msg) => { progressEl.style.display = msg ? "" : "none"; progressEl.textContent = msg; };
  const cancelBtn = document.getElementById("lib-scan-cancel-btn");
  cancelBtn.style.display = "";
  cancelBtn.disabled = false;

  function finish() {
    setProgress(""); cancelBtn.style.display = "none"; _libBatchScanEs = null; _libBatchScanJobId = null;
    try { localStorage.removeItem("cc-active-job"); } catch {}
  }

  const es = new EventSource(streamUrl);
  _libBatchScanEs = es;

  es.onmessage = (e) => {
    const job = JSON.parse(e.data);
    if (job.phase === "done") {
      es.close(); finish();
      if (isBatchScan) {
        const allDetections = [];
        (job.results || []).forEach(r => {
          (r.detections || []).forEach(d => { d.video_path = r.video; allDetections.push(d); });
        });
        const byVideo = {};
        allDetections.forEach(d => { if (!byVideo[d.video_path]) byVideo[d.video_path] = []; byVideo[d.video_path].push(d); });
        Object.entries(byVideo).forEach(([vp, dets]) => {
          fetch("/clip-cutter/detections", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_path: vp, detections: dets }) }).catch(() => {});
        });
        video_paths.forEach(vp => _setBrowserScanBadge(vp, "done-scan"));
        currentFilter = "all";
        renderDetections(allDetections);
        setStatus(`Batch scan done — ${allDetections.length} detection(s)`);
      } else {
        const allCandidates = [];
        (job.results || []).forEach(r => (r.candidates || []).forEach(c => allCandidates.push({ ...c, video_path: r.video_path })));
        video_paths.forEach(vp => _setBrowserScanBadge(vp, "done-scan"));
        renderTemplateCandidateCards(allCandidates);
        showRethresholdBar();
        setStatus(`Template scan done — ${allCandidates.length} candidate(s)`);
      }
    } else if (job.phase === "error") {
      es.close(); finish(); setStatus("Scan error: " + job.error);
    } else if (job.phase === "cancelled") {
      es.close(); finish(); setStatus("Scan cancelled");
    } else {
      const msg = `${job.video || "…"} (${job.video_index || "?"}/${job.video_total || "?"}) — ${job.phase}`;
      setProgress(msg);
      setStatus(`Scanning ${msg}`);
      const idx = (job.video_index || 1) - 1;
      video_paths.forEach((vp, i) => {
        if (i < idx) _setBrowserScanBadge(vp, "done-scan");
        else if (i === idx) _setBrowserScanBadge(vp, "scanning");
      });
    }
  };
  es.onerror = () => {
    // Server may have gone away — clear saved job so we don't loop forever
    es.close(); finish(); setStatus("Scan stream lost (server restarted?)");
  };
}

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  loadTemplate();
  const _savedPath = (() => { try { return localStorage.getItem("cc-browser-path"); } catch { return null; } })();
  loadFolder(_savedPath || null).then(() => _reconnectActiveJob());

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

  // Sidebar collapse toggle
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebarEl = document.querySelector(".sidebar");
  const sidebarExpandTab = document.getElementById("sidebar-tab");
  function _collapsePanel(el) {
    el.dataset.savedMaxWidth = el.style.maxWidth || "";
    el.dataset.savedWidth    = el.style.width    || "";
    el.style.maxWidth = "";
    el.style.width    = "";
    el.classList.add("collapsed");
  }
  function _expandPanel(el) {
    el.classList.remove("collapsed");
    if (el.dataset.savedMaxWidth) el.style.maxWidth = el.dataset.savedMaxWidth;
    if (el.dataset.savedWidth)    el.style.width    = el.dataset.savedWidth;
  }
  if (sidebarToggle && sidebarEl) {
    sidebarToggle.addEventListener("click", () => {
      if (sidebarEl.classList.contains("collapsed")) _expandPanel(sidebarEl);
      else _collapsePanel(sidebarEl);
    });
  }
  if (sidebarExpandTab && sidebarEl) {
    sidebarExpandTab.addEventListener("click", () => _expandPanel(sidebarEl));
  }

  // Browser panel collapse toggle
  const browserToggle = document.getElementById("browser-toggle");
  const browserPanel = document.getElementById("browser-panel");
  const browserExpandTab = document.getElementById("browser-tab");
  if (browserToggle && browserPanel) {
    browserToggle.addEventListener("click", () => {
      if (browserPanel.classList.contains("collapsed")) _expandPanel(browserPanel);
      else _collapsePanel(browserPanel);
    });
  }
  if (browserExpandTab && browserPanel) {
    browserExpandTab.addEventListener("click", () => _expandPanel(browserPanel));
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

  // ── Similarity threshold filter ────────────────────────────────────────────
  (function () {
    const slider = document.getElementById("sim-slider");
    const field  = document.getElementById("sim-value");
    const reset  = document.getElementById("sim-reset");
    if (!slider || !field || !reset) return;

    function _updateReset() {
      reset.style.display = parseFloat(slider.value) > 0 ? "" : "none";
    }

    slider.addEventListener("input", () => {
      field.value = slider.value;
      _updateReset();
      applyFilter();
    });

    field.addEventListener("input", () => {
      let v = parseFloat(field.value);
      if (isNaN(v)) v = 0;
      v = Math.max(0, Math.min(1, v));
      field.value = v;
      slider.value = v;
      _updateReset();
      applyFilter();
    });

    reset.addEventListener("click", () => {
      slider.value = 0;
      field.value = 0;
      reset.style.display = "none";
      applyFilter();
    });
  })();

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

  // ── Sidebar tabs ──────────────────────────────────────────────────────────────
  const tabTemplate  = document.getElementById("tab-template");
  const tabLibraries = document.getElementById("tab-libraries");
  const templateBody = [
    "sidebar-empty-state", "sidebar-no-template", "template-list",
    "template-footer", "sidebar-actions",
  ].map(id => document.getElementById(id));
  const librariesPanel = document.getElementById("libraries-panel");
  const initBtn = document.getElementById("sidebar-init-btn");

  function showTemplateTab() {
    tabTemplate.classList.add("active");
    tabLibraries.classList.remove("active");
    librariesPanel.style.display = "none";
    initBtn.style.display = _selectedVideoStem ? "" : "none";
    loadTemplate();
  }

  function showLibrariesTab() {
    tabLibraries.classList.add("active");
    tabTemplate.classList.remove("active");
    templateBody.forEach(el => { if (el) el.style.display = "none"; });
    initBtn.style.display = "none";
    librariesPanel.style.display = "flex";
    loadLibraries();
  }

  tabTemplate.addEventListener("click", showTemplateTab);
  tabLibraries.addEventListener("click", showLibrariesTab);

  // ── [+ New] library button ────────────────────────────────────────────────────
  document.getElementById("lib-new-btn").addEventListener("click", async () => {
    const name = document.getElementById("lib-new-name").value.trim();
    if (!name) return;
    const resp = await fetch("/clip-cutter/global-libraries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (resp.ok) {
      document.getElementById("lib-new-name").value = "";
      await loadLibraries();
    } else {
      const err = await resp.json();
      setStatus("Error: " + err.error);
    }
  });

  // Browse frames buttons
  const _openBrowse = () => {
    if (!selectedVideoPath) { setStatus("No video selected"); return; }
    openPlayer({
      mode: "template",
      videoPath: selectedVideoPath,
      csvPath: selectedVideoPath.replace(/\.avi$/i, ".csv"),
    });
  };
  document.getElementById("sidebar-browse-btn").addEventListener("click", _openBrowse);
  document.getElementById("sidebar-browse-btn2").addEventListener("click", _openBrowse);

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

  // Library scan settings toggle + threshold label
  document.getElementById("lib-settings-toggle").addEventListener("click", () => {
    const body = document.getElementById("lib-settings-body");
    const open = body.style.display === "none";
    body.style.display = open ? "" : "none";
    document.getElementById("lib-settings-toggle").innerHTML =
      `&#9881; Scan settings ${open ? "&#9650;" : "&#9660;"}`;
  });
  document.getElementById("lib-scan-threshold").addEventListener("input", (e) => {
    document.getElementById("lib-threshold-label").textContent = parseFloat(e.target.value).toFixed(2);
  });

  document.getElementById("batch-toggle").addEventListener("click", () => {
    _batchMode = !_batchMode;
    updateBatchToolbar();
    if (_browserCurrentPath) loadFolder(_browserCurrentPath);
  });

  document.getElementById("batch-init-btn").addEventListener("click", startBatchInit);

  document.getElementById("batch-add-folder-btn").addEventListener("click", async () => {
    if (!_activeBatchLibrary || !_browserCurrentPath) return;
    const resp = await fetch(
      `/clip-cutter/global-libraries/${encodeURIComponent(_activeBatchLibrary)}/folders`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: _browserCurrentPath }),
      }
    );
    if (resp.ok) {
      setStatus(`Added "${_browserCurrentPath.split("/").pop()}" to ${_activeBatchLibrary}`);
      await loadLibraries();
    } else {
      const err = await resp.json();
      setStatus("Error: " + err.error);
    }
  });

  // Scan type pills
  document.getElementById("lib-scan-type").querySelectorAll(".pill-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById("lib-scan-type")
        .querySelectorAll(".pill-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _libScanType = btn.dataset.val;
      document.getElementById("lib-clips-fields").style.display    = _libScanType === "clips"            ? "" : "none";
      document.getElementById("lib-template-fields").style.display = _libScanType === "template_frames" ? "" : "none";
    });
  });

  // Sensor mode pills
  document.getElementById("lib-sensor-mode").querySelectorAll(".pill-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.getElementById("lib-sensor-mode")
        .querySelectorAll(".pill-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      _libSensorMode = btn.dataset.val;
      document.getElementById("lib-sensor-fields").style.display = _libSensorMode === "sensor+clip" ? "" : "none";
    });
  });

});

// ── Template bank ─────────────────────────────────────────────────────────────

async function loadTemplate() {
  const resp = await fetch("/clip-cutter/template");
  const data = await resp.json();
  renderTemplate(data);
}

function renderTemplate(data) {
  if (document.getElementById("tab-libraries").classList.contains("active")) return;
  const emptyState = document.getElementById("sidebar-empty-state");
  const noTemplate = document.getElementById("sidebar-no-template");
  const noTemplateMsg = document.getElementById("sidebar-no-template-msg");
  const list = document.getElementById("template-list");
  const footer = document.getElementById("template-footer");
  const initBtn = document.getElementById("sidebar-init-btn");
  const sidebarActions = document.getElementById("sidebar-actions");
  const frameCount = document.getElementById("sidebar-frame-count");

  if (!_selectedVideoStem) {
    emptyState.style.display = "";
    noTemplate.style.display = "none";
    list.style.display = "none";
    footer.style.display = "none";
    initBtn.style.display = "none";
    sidebarActions.style.display = "none";
    frameCount.textContent = "";
    return;
  }

  emptyState.style.display = "none";
  initBtn.style.display = "";

  if (!data.has_template) {
    noTemplate.style.display = "";
    noTemplateMsg.textContent = `No template for ${_selectedVideoStem}`;
    list.style.display = "none";
    footer.style.display = "none";
    sidebarActions.style.display = "none";
    frameCount.textContent = "";
    return;
  }

  noTemplate.style.display = "none";
  list.style.display = "";
  footer.style.display = "";
  sidebarActions.style.display = "flex";
  frameCount.textContent = `${data.count} fr`;

  list.innerHTML = "";
  data.frames.forEach((f, idx) => {
    const stem = f.video_path.split("/").pop().replace(/\.avi$/i, "");
    const label = `${stem} · fr${f.frame_number}`;
    const row = document.createElement("div");
    row.className = "tpl-row";
    row.innerHTML = `
      <span class="tpl-label" title="${f.video_path} · fr${f.frame_number}">${label}</span>
      <button class="player-btn tpl-view-btn" title="View frame">&#8599;</button>
      <button class="player-btn tpl-del-btn" title="Remove">&#10005;</button>
    `;
    row.querySelector(".tpl-view-btn").addEventListener("click", () => {
      window.open(
        `/clip-cutter/frame?video=${encodeURIComponent(f.video_path)}&n=${f.frame_number - 1}`,
        "_blank"
      );
    });
    row.querySelector(".tpl-del-btn").addEventListener("click", () => removeTemplateFrame(idx));
    list.appendChild(row);
  });
  footer.textContent = `${data.count} frame${data.count !== 1 ? "s" : ""} loaded`;
}

async function initTemplate() {
  if (document.getElementById("template-list").style.display !== "none") {
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
        if (selectedVideoPath) openPlayer({
          mode: "template",
          videoPath: selectedVideoPath,
          csvPath: selectedVideoPath.replace(/\.avi$/i, ".csv"),
        });
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

    const videoPath = data.path + "/" + entry.name;
    const stem = entry.name.replace(/\.avi$/i, "");
    row.dataset.videoPath = videoPath;

    if (entry.type === "dir") {
      icon.textContent = "📁";
      row.addEventListener("click", () => loadFolder(data.path + "/" + entry.name));
    } else {
      icon.textContent = "▶";
      const badge = document.createElement("span");
      badge.className = `badge ${entry.done ? "badge-done" : "badge-pending"}`;
      badge.textContent = entry.done ? "done" : "ready";
      row.appendChild(badge);

      if (_batchMode) {
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.className = "browser-row-checkbox";
        cb.checked = _batchQueue.has(videoPath);
        cb.addEventListener("change", (e) => {
          e.stopPropagation();
          if (cb.checked) _batchQueue.add(videoPath);
          else _batchQueue.delete(videoPath);
          updateBatchToolbar();
        });
        row.insertBefore(cb, icon);
        row.addEventListener("click", (e) => {
          if (e.target === cb) return;
          cb.checked = !cb.checked;
          if (cb.checked) _batchQueue.add(videoPath);
          else _batchQueue.delete(videoPath);
          updateBatchToolbar();
        });
      } else {
        row.addEventListener("click", () => {
          document.querySelectorAll(".browser-row.selected").forEach((r) =>
            r.classList.remove("selected")
          );
          row.classList.add("selected");
          selectVideo(videoPath, stem, data.path);
        });
      }
    }
    list.appendChild(row);
  });
}

function _setBrowserScanBadge(fullPath, status) {
  const row = document.querySelector(`#browser-list .browser-row[data-video-path="${CSS.escape(fullPath)}"]`);
  if (!row) return;
  const badge = row.querySelector(".badge");
  if (!badge) return;
  if (status === "scanning") {
    badge.className = "badge badge-scanning";
    badge.textContent = "▶ scanning";
  } else if (status === "done-scan") {
    badge.className = "badge badge-done";
    badge.textContent = "done";
  }
}

async function selectVideo(videoPath, stem, parent) {
  selectedVideoPath = videoPath;
  _selectedVideoStem = stem;
  _selectedVideoParent = parent;

  const selectResp = await fetch("/clip-cutter/select-video", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ video_path: videoPath }),
  });
  if (!selectResp.ok) {
    setStatus("Failed to select video");
    return;
  }

  document.getElementById("scan-btn").disabled = false;
  updateBatchScanBtn();
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
  const cancelBtn = document.getElementById("scan-cancel-btn");
  progressSection.style.display = "block";
  cancelBtn.style.display = "";
  resetPipelineStrip();
  setStatus("Scanning…");

  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/clip-cutter/scan/stream?job_id=${jobId}`);

  function finishScan() {
    cancelBtn.style.display = "none";
    progressSection.style.display = "none";
    document.getElementById("scan-btn").disabled = false;
  }

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
      renderDetections(job.detections);
      currentFilter = "sensor+clip";
      document.querySelectorAll(".filter-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.filter === "sensor+clip");
      });
      applyFilter();
      await saveDetections();
      finishScan();
      setStatus(`Scan complete — ${job.detections.length} detection${job.detections.length !== 1 ? "s" : ""}`);
    } else if (job.status === "error") {
      eventSource.close();
      finishScan();
      setStatus("Scan error: " + job.error);
    } else if (job.status === "cancelled") {
      eventSource.close();
      finishScan();
      setStatus("Scan cancelled");
    }
  };
}

async function cancelScan() {
  if (!currentJobId) return;
  document.getElementById("scan-cancel-btn").disabled = true;
  document.getElementById("progress-cancel-btn").disabled = true;
  await fetch(`/clip-cutter/scan/${encodeURIComponent(currentJobId)}/cancel`, { method: "POST" });
}

async function cancelLibScan() {
  if (!_libBatchScanJobId) return;
  const btn = document.getElementById("lib-scan-cancel-btn");
  btn.disabled = true;
  const endpoint = _libScanType === "template_frames"
    ? `/clip-cutter/batch-template-scan/${encodeURIComponent(_libBatchScanJobId)}/cancel`
    : `/clip-cutter/batch-scan/${encodeURIComponent(_libBatchScanJobId)}/cancel`;
  await fetch(endpoint, { method: "POST" });
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
  if (typeof _epAutoPopulatePostfixes === "function") _epAutoPopulatePostfixes();
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
  card.dataset.similarity = d.similarity ?? 0;

  // Build compact two-line card
  card.innerHTML = `
    <div class="result-accent-bar"></div>
    <div class="result-meta">
      <div class="result-name" id="card-clipname-${idx}"></div>
      <div class="result-row">
        <span style="font-size:9px;color:#768390;white-space:nowrap;">kf <span class="kf-num"></span></span>
        <span class="sim-pill"></span>
        <span class="match-pill ${isKnown ? "match-known" : "match-new"}"></span>
        <div style="flex:1;min-width:0;"></div>
        <span class="ep-conflict-badge"></span>
        <button class="btn-sm btn-green keep-btn" style="padding:1px 5px;font-size:9px;">&#10003;</button>
        <button class="btn-sm btn-red reject-btn" style="padding:1px 5px;font-size:9px;">&#10007;</button>
        <button class="btn-sm btn-blue add-btn" style="padding:1px 5px;font-size:9px;">+Tpl</button>
      </div>
    </div>`;

  // Populate text safely
  const postfixSuffix = d.extract_postfix ? `_${d.extract_postfix}` : "";
  card.querySelector(".result-name").textContent = clipName + postfixSuffix + ".avi";
  card.querySelector(".kf-num").textContent = d.frame_number.toLocaleString();
  card.querySelector(".match-pill").textContent = isKnown
    ? "✓ " + d.known_match
    : "new";
  card.querySelector(".sim-pill").textContent = d.similarity.toFixed(2);

  // Source badge — insert before the spacer in result-row
  if (d.source && d.source !== "pending") {
    const badge = document.createElement("span");
    badge.className = "source-badge";
    if (d.source === "sensor+clip") {
      badge.classList.add("source-sensor-clip"); badge.textContent = "s+c";
    } else if (d.source === "sensor_only") {
      badge.classList.add("source-sensor-only"); badge.textContent = "sen";
    } else if (d.source === "clip_only") {
      badge.classList.add("source-clip-only"); badge.textContent = "clip";
    } else if (d.source === "global_library") {
      badge.classList.add("source-global-library"); badge.textContent = "lib";
    }
    const spacer = card.querySelector(".result-row div");
    card.querySelector(".result-row").insertBefore(badge, spacer);
  }

  // Attach event listeners (no onclick attributes with embedded data)
  card.querySelector(".keep-btn").addEventListener("click", () => keepDetection(idx));
  card.querySelector(".reject-btn").addEventListener("click", () => rejectDetection(idx));
  card.querySelector(".add-btn").addEventListener("click", () =>
    addToTemplate(d.video_path, d.frame_number)
  );

  card.addEventListener("click", (e) => {
    if (e.target.closest("button:not([disabled])")) return;
    document.querySelectorAll(".result-card").forEach((c) => c.classList.remove("active-preview"));
    card.classList.add("active-preview");
    if (typeof getVideoPath === "function" && getVideoPath() === d.video_path) {
      epSwitchDetection({ detectionIdx: idx, keyFrame1Based: d.frame_number });
    } else {
      openPlayer({
        mode: "clip",
        videoPath: d.video_path,
        keyFrame1Based: d.frame_number,
        detectionIdx: idx,
        csvPath: d.video_path.replace(/\.avi$/i, ".csv"),
      });
    }
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
    const data = await resp.json().catch(() => ({}));
    detections[idx].status = "kept";
    if (data.avi_path) detections[idx].extract_avi_path = data.avi_path;
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
  if (card) {
    card.classList.add("rejected");
    card.querySelectorAll("button").forEach(b => (b.disabled = true));
  }
  await saveDetections();
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg;
}

// ── Tab navigation between candidates ─────────────────────────────────────────

document.addEventListener("keydown", e => {
  if (e.key !== "Tab") return;
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

  const playerPanel = document.getElementById("player-panel");
  if (!playerPanel || playerPanel.style.display === "none") return;

  const active = document.querySelector(".result-card.active-preview");
  if (!active) return;

  const cards = Array.from(document.querySelectorAll("#results-list .result-card"))
    .filter(c => c.style.display !== "none");
  const cur = cards.indexOf(active);
  if (cur === -1) return;

  const next = e.shiftKey ? cur - 1 : cur + 1;
  if (next < 0 || next >= cards.length) { e.preventDefault(); return; }

  e.preventDefault();
  cards[next].click();
  cards[next].scrollIntoView({ block: "nearest" });
});

// ── Sidebar resize ─────────────────────────────────────────────────────────────

(function () {
  const handle  = document.getElementById("sidebar-resize-handle");
  const sidebar = document.querySelector(".sidebar");
  if (!handle || !sidebar) return;
  let startX = 0, startW = 0;

  handle.addEventListener("mousedown", e => {
    startX = e.clientX;
    startW = sidebar.offsetWidth;
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
    window.addEventListener("blur",        onUp);
    e.preventDefault();
  });

  function onMove(e) {
    const w = Math.max(120, Math.min(400, startW + (e.clientX - startX)));
    sidebar.style.width = w + "px";
    sidebar.style.maxWidth = w + "px";
  }

  function onUp() {
    document.body.style.userSelect = "";
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup",   onUp);
    window.removeEventListener("blur",        onUp);
  }
})();

// ── Browser panel resize ────────────────────────────────────────────────────────

(function () {
  const handle  = document.getElementById("browser-resize-handle");
  const panel   = document.getElementById("browser-panel");
  if (!handle || !panel) return;
  let startX = 0, startW = 0;

  handle.addEventListener("mousedown", e => {
    startX = e.clientX;
    startW = panel.offsetWidth;
    handle.classList.add("dragging");
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
    window.addEventListener("blur",        onUp);
    e.preventDefault();
  });

  function onMove(e) {
    const w = Math.max(160, Math.min(520, startW + (e.clientX - startX)));
    panel.style.width    = w + "px";
    panel.style.maxWidth = w + "px";
  }

  function onUp() {
    handle.classList.remove("dragging");
    document.body.style.userSelect = "";
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup",   onUp);
    window.removeEventListener("blur",        onUp);
  }
})();
