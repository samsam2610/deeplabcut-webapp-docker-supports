// Lightning-Pose cards — Card 1 (Convert) wiring.

import { makeFileBrowser } from "./components/file_browser.js";

const $ = (sel) => document.querySelector(sel);

function activeDlcProjectFromDom() {
  // Reads the active DLC project path from the DOM element managed by
  // the main webapp's dlc_project.js. Empty string when no project is loaded.
  return (document.getElementById("dlc-active-path")?.textContent || "").trim();
}

function initConvertCard() {
  const card = $("#lp-convert-card");
  if (!card) return;
  const activeEl = $("#lp-convert-active");
  const dstEl = $("#lp-convert-dst");
  const runEl = $("#btn-lp-convert-run");
  const resEl = $("#lp-convert-result");
  const closeBtn = $("#btn-close-lp-convert");

  closeBtn?.addEventListener("click", () => card.classList.add("hidden"));

  const renderActive = () => {
    const p = activeDlcProjectFromDom();
    if (p) {
      activeEl.textContent = p;
      activeEl.style.color = "var(--text)";
    } else {
      activeEl.innerHTML = "<em>load a DLC project in the \"DeepLabCut Project Manager\" card first</em>";
      activeEl.style.color = "var(--text-dim)";
    }
  };

  // Refresh display when the card becomes visible OR when the upstream DOM changes.
  new MutationObserver(renderActive).observe(card, { attributes: true, attributeFilter: ["class"] });
  const upstream = document.getElementById("dlc-active-path");
  if (upstream) {
    new MutationObserver(renderActive).observe(upstream, { childList: true, characterData: true, subtree: true });
  }
  renderActive();

  const modeEl = () =>
    document.querySelector('input[name="lp-convert-mode"]:checked')?.value || "fresh";

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Running…";
    const payload = { mode: modeEl() };
    const dst = dstEl.value.trim();
    if (dst) payload.lp_dir = dst;   // dlc_dir omitted → server uses active project
    try {
      const r = await fetch("/dlc-3d/lp/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json();
      resEl.textContent = JSON.stringify(body, null, 2);
    } catch (e) {
      resEl.textContent = "Error: " + e.message;
    } finally {
      runEl.disabled = false;
    }
  });

}

initConvertCard();


async function pollJob(jobId, onUpdate, intervalMs = 1500) {
  while (true) {
    let body;
    try {
      const r = await fetch(`/dlc-3d/lp/job/${jobId}`);
      body = await r.json();
      if (!r.ok) {
        onUpdate({ error: `job poll failed: ${r.status}`, ...body });
        return;
      }
    } catch (e) {
      onUpdate({ error: `poll failed: ${e.message}` });
      return;
    }
    onUpdate(body);
    const state = body.celery_state || "PENDING";
    if (["SUCCESS", "FAILURE", "REVOKED"].includes(state)) return;
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}


function initEksCard() {
  const card = $("#lp-eks-card");
  if (!card) return;
  const modeEl = $("#lp-eks-mode");
  const inEl   = $("#lp-eks-in");
  const outEl  = $("#lp-eks-out");
  const sEl    = $("#lp-eks-s");
  const runEl  = $("#btn-lp-eks-run");
  const resEl  = $("#lp-eks-result");

  $("#btn-close-lp-eks")?.addEventListener("click", () => card.classList.add("hidden"));

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Submitting…";
    const mode = modeEl.value;
    const inPaths = inEl.value.split(",").map((s) => s.trim()).filter(Boolean);
    const payload = {
      mode,
      in_paths: inPaths,
      s: parseFloat(sEl.value) || 1.0,
    };
    if (mode === "single") payload.out_csv = outEl.value.trim();
    else                   payload.out_dir = outEl.value.trim();

    try {
      const r = await fetch("/dlc-3d/lp/eks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json();
      if (!r.ok) {
        resEl.textContent = "Error: " + JSON.stringify(body, null, 2);
        return;
      }
      const jobId = body.job_id;
      resEl.textContent = `Job ${jobId}: PENDING`;
      await pollJob(jobId, (j) => {
        resEl.textContent = JSON.stringify(j, null, 2);
      });
    } catch (e) {
      resEl.textContent = "Error: " + e.message;
    } finally {
      runEl.disabled = false;
    }
  });
}

initEksCard();


function initTrainCard() {
  const card = $("#lp-train-card");
  if (!card) return;
  const projectEl = $("#lp-train-project");
  const runEl = $("#btn-lp-train-run");
  const resEl = $("#lp-train-result");

  $("#btn-close-lp-train")?.addEventListener("click", () => card.classList.add("hidden"));

  // Auto-fill LP project path from the active DLC project ("<dlc>-LP/").
  // Only overwrite if the user hasn't typed something different.
  let lastAutoFill = "";
  const syncProjectField = () => {
    const dlc = activeDlcProjectFromDom();
    const auto = dlc ? dlc.replace(/\/+$/, "") + "-LP" : "";
    if (projectEl.value === "" || projectEl.value === lastAutoFill) {
      projectEl.value = auto;
      lastAutoFill = auto;
    }
  };
  new MutationObserver(syncProjectField).observe(card, { attributes: true, attributeFilter: ["class"] });
  const upstream = document.getElementById("dlc-active-path");
  if (upstream) {
    new MutationObserver(syncProjectField).observe(upstream, { childList: true, characterData: true, subtree: true });
  }
  syncProjectField();

  $("#lp-train-pm")?.addEventListener("change", (e) => {
    $("#lp-train-pm-params").style.display = e.target.checked ? "flex" : "none";
  });
  $("#lp-train-reproj")?.addEventListener("change", (e) => {
    $("#lp-train-reproj-params").style.display = e.target.checked ? "flex" : "none";
  });
  $("#lp-train-two-stage")?.addEventListener("change", (e) => {
    $("#lp-train-two-stage-params").style.display = e.target.checked ? "flex" : "none";
    $("#lp-train-stage1-override-wrap").style.display = e.target.checked ? "block" : "none";
  });

  const semiEl = $("#lp-train-semi-supervised");
  const semiParamsEl = $("#lp-train-semi-supervised-params");
  const tempLwEl = $("#lp-train-temporal-log-weight");
  const tempEpsEl = $("#lp-train-temporal-epsilon");
  semiEl?.addEventListener("change", () => {
    if (semiParamsEl) semiParamsEl.style.display = semiEl.checked ? "flex" : "none";
  });

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Submitting…";

    const options = {
      mvt_enabled: $("#lp-train-mvt").checked,
      patch_masking_enabled: $("#lp-train-pm").checked,
      patch_masking_init_epoch:  +$("#lp-train-pm-init-epoch").value,
      patch_masking_final_epoch: +$("#lp-train-pm-final-epoch").value,
      patch_masking_init_ratio:  +$("#lp-train-pm-init-ratio").value,
      patch_masking_final_ratio: +$("#lp-train-pm-final-ratio").value,
      reproj_loss_enabled: $("#lp-train-reproj").checked,
      reproj_loss_log_weight: +$("#lp-train-reproj-weight").value,
      max_epochs: +$("#lp-train-epochs").value,
      batch_size: +$("#lp-train-batch").value,
      predict_vids_after_training: $("#lp-train-predict-vids").checked,
      save_vids_after_training:    $("#lp-train-save-vids").checked,
      two_stage:                 $("#lp-train-two-stage").checked,
      stage1_max_epochs:         +$("#lp-train-stage1-epochs").value,
      stage1_early_stop_patience:+$("#lp-train-stage1-patience").value,
      stage1_ckpt_override:      $("#lp-train-stage1-override").value.trim(),
    };

    options.semi_supervised_enabled = !!semiEl?.checked;
    if (semiEl?.checked) {
      options.temporal_log_weight = parseFloat(tempLwEl.value) || 5.0;
      options.temporal_epsilon    = parseFloat(tempEpsEl.value) || 0.0;
    }

    try {
      const r = await fetch("/dlc-3d/lp/train", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lp_project: projectEl.value.trim(), options }),
      });
      const body = await r.json();
      if (!r.ok) { resEl.textContent = "Error: " + JSON.stringify(body); return; }
      const jobId = body.job_id;
      resEl.textContent = `Job ${jobId}: PENDING`;
      await pollJob(jobId, (j) => {
        const tail = (j.log_tail || []).slice(-30).join("\n");
        const stage = j.celery_info?.stage || "";
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          (stage ? `stage: ${stage}\n` : "") +
          `run_dir: ${j.celery_info?.lp_project || j.options?.lp_project || ""}\n` +
          `--- log tail ---\n${tail}`;
      }, 2500);
    } finally {
      runEl.disabled = false;
    }
  });
}

initTrainCard();


function initPredictCard() {
  const card = $("#lp-predict-card");
  if (!card) return;

  const projectEl     = $("#lp-predict-project");
  const modelEl       = $("#lp-predict-model");
  const noteEl        = $("#lp-predict-model-note");

  const targetEl      = $("#lp-predict-target");
  const browseUpEl    = $("#lp-predict-browse-up");
  const browseBtnEl   = $("#lp-predict-browse-btn");
  const browserEl     = $("#lp-predict-browser");
  const batchAddEl    = $("#lp-predict-batch-add-btn");
  const batchClearEl  = $("#lp-predict-batch-clear-btn");
  const batchListEl   = $("#lp-predict-batch-list");

  const destEl        = $("#lp-predict-destfolder");
  const destUpEl      = $("#lp-predict-dest-up");
  const destBrowseEl  = $("#lp-predict-dest-browse-btn");
  const destBrowserEl = $("#lp-predict-dest-browser");
  const destClearEl   = $("#lp-predict-dest-clear-btn");

  const skipVizEl     = $("#lp-predict-skip-viz");
  const overwriteEl   = $("#lp-predict-overwrite");
  const runEl         = $("#btn-lp-predict-run");
  const resEl         = $("#lp-predict-result");

  $("#btn-close-lp-predict")?.addEventListener("click", () => card.classList.add("hidden"));

  // ── LP project + model dropdown (unchanged from previous behaviour) ──
  let lastAutoFill = "";
  const syncProjectField = () => {
    const dlc = activeDlcProjectFromDom();
    const auto = dlc ? dlc.replace(/\/+$/, "") + "-LP" : "";
    if (projectEl.value === "" || projectEl.value === lastAutoFill) {
      projectEl.value = auto;
      lastAutoFill = auto;
    }
  };

  async function reloadModels() {
    const p = projectEl.value.trim();
    modelEl.innerHTML = '<option value="">— loading… —</option>';
    noteEl.textContent = "";
    const url = "/dlc-3d/lp/models" + (p ? `?lp_project=${encodeURIComponent(p)}` : "");
    let body;
    try {
      const r = await fetch(url);
      body = await r.json();
      if (!r.ok) { modelEl.innerHTML = `<option value="">— ${body.error || "error"} —</option>`; return; }
    } catch (e) {
      modelEl.innerHTML = `<option value="">— ${e.message} —</option>`; return;
    }
    const models = body.models || [];
    if (!models.length) {
      modelEl.innerHTML = '<option value="">— no models found —</option>';
      noteEl.textContent = "Train a model first, or pick a different LP project.";
      return;
    }
    const usable = models.filter((m) => m.has_checkpoint);
    modelEl.innerHTML = models.map((m) => {
      const label = `${m.run_id}${m.has_checkpoint ? " ✓" : " (no checkpoint)"}${m.has_predictions ? " · trained" : ""}`;
      const disabled = m.has_checkpoint ? "" : " disabled";
      return `<option value="${m.path}"${disabled}>${label}</option>`;
    }).join("");
    if (usable.length) modelEl.value = usable[0].path;
    noteEl.textContent = `${usable.length} usable model${usable.length === 1 ? "" : "s"} of ${models.length} total`;
  }

  new MutationObserver(() => { syncProjectField(); reloadModels(); })
    .observe(card, { attributes: true, attributeFilter: ["class"] });
  const upstream = document.getElementById("dlc-active-path");
  if (upstream) {
    new MutationObserver(() => { syncProjectField(); reloadModels(); })
      .observe(upstream, { childList: true, characterData: true, subtree: true });
  }
  projectEl.addEventListener("change", reloadModels);
  syncProjectField();

  // ── Videos picker ───────────────────────────────────────────────────
  const videoBrowser = makeFileBrowser({ inputEl: targetEl, paneEl: browserEl, dirOnly: false });
  const queue = []; // ordered, deduped

  function renderQueue() {
    if (!queue.length) {
      batchListEl.style.display = "none";
      batchListEl.innerHTML = "";
      return;
    }
    batchListEl.style.display = "block";
    batchListEl.innerHTML = "";
    queue.forEach((p, i) => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.1rem 0";
      const txt = document.createElement("span");
      txt.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
      txt.textContent = p;
      const rm = document.createElement("button");
      rm.className = "btn-sm"; rm.style.cssText = "padding:0 .35rem;font-size:.7rem;opacity:.6";
      rm.textContent = "×"; rm.title = "Remove";
      rm.addEventListener("click", () => { queue.splice(i, 1); renderQueue(); });
      row.appendChild(txt); row.appendChild(rm);
      batchListEl.appendChild(row);
    });
  }

  function addToQueue(p) {
    p = (p || "").trim();
    if (!p) return;
    if (!queue.includes(p)) queue.push(p);
    renderQueue();
  }

  browserEl.addEventListener("lp-picker-dblclick", (e) => addToQueue(e.detail.path));
  batchAddEl.addEventListener("click", () => addToQueue(videoBrowser.getHighlighted() || targetEl.value));
  batchClearEl.addEventListener("click", () => { queue.length = 0; renderQueue(); });

  browseBtnEl.addEventListener("click", () => {
    const fallback = (projectEl.value.trim().replace(/-LP\/?$/, "")) || "/user-data";
    videoBrowser.openAt(fallback);
  });
  browseUpEl.addEventListener("click", () => videoBrowser.up());
  targetEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); videoBrowser.browseDir(targetEl.value.trim()); browserEl.classList.remove("hidden"); }
  });

  // ── Output folder picker (dir-only) ────────────────────────────────
  const destBrowser = makeFileBrowser({ inputEl: destEl, paneEl: destBrowserEl, dirOnly: true });
  destBrowseEl.addEventListener("click", () => destBrowser.openAt(destEl.value.trim() || "/user-data"));
  destUpEl.addEventListener("click", () => destBrowser.up());
  destClearEl.addEventListener("click", () => { destEl.value = ""; destBrowserEl.classList.add("hidden"); });
  destEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); destBrowser.browseDir(destEl.value.trim()); destBrowserEl.classList.remove("hidden"); }
  });

  // ── Submit ─────────────────────────────────────────────────────────
  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Submitting…";
    const videos = queue.length ? queue.slice() : (targetEl.value.trim() ? [targetEl.value.trim()] : []);
    if (!videos.length) {
      resEl.textContent = "Error: queue at least one video (browse + double-click, or + Add to queue).";
      runEl.disabled = false;
      return;
    }
    const payload = {
      lp_project: projectEl.value.trim() || undefined,
      model_dir:  modelEl.value || undefined,
      videos,
      skip_viz:   skipVizEl.checked,
      overwrite:  overwriteEl.checked,
      dest_dir:   destEl.value.trim(),
    };
    try {
      const r = await fetch("/dlc-3d/lp/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json();
      if (!r.ok) { resEl.textContent = "Error: " + JSON.stringify(body, null, 2); return; }
      const jobId = body.job_id;
      resEl.textContent = `Job ${jobId}: PENDING\nmodel_dir: ${body.model_dir || ""}\ndest: ${body.dest_dir || "<per-video parent>"}`;
      await pollJob(jobId, (j) => {
        const tail = (j.log_tail || []).slice(-30).join("\n");
        const info = j.celery_info || {};
        const transcoded = info.transcoded || [];
        const warnings   = info.sibling_warnings || [];
        const extras = [];
        if (transcoded.length) extras.push(`transcoded:\n  ` + transcoded.join("\n  "));
        if (warnings.length)   extras.push(`warnings:\n  ` + warnings.join("\n  "));
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          `model_dir: ${info.model_dir || j.model_dir || ""}\n` +
          `dest: ${info.dest_dir || j.dest_dir || "<per-video parent>"}\n` +
          (extras.length ? extras.join("\n") + "\n" : "") +
          `--- log tail ---\n${tail}`;
      }, 2500);
    } finally {
      runEl.disabled = false;
    }
  });
}

initPredictCard();


function initJobsCard() {
  const card = $("#lp-jobs-card");
  if (!card) return;
  const tbody = $("#lp-jobs-tbody");
  const detail = $("#lp-jobs-detail");
  $("#btn-close-lp-jobs")?.addEventListener("click", () => {
    card.classList.add("hidden");
    stopAutoRefresh();
    stopDetailPoll();
  });

  const TERMINAL = new Set(["SUCCESS", "FAILURE", "REVOKED"]);
  let autoRefreshTimer = null;
  let detailPollAbort = null;
  const jobsById = new Map();   // id -> last-seen job row (used by openDetail)

  // analyze rows come from the inline-analysis Celery task in the MAIN webapp,
  // NOT the lp_3d queue — so /dlc-3d/lp/jobs reports PENDING for them. Pull live
  // state straight from the inline-analysis status endpoint and map it onto the
  // same celery_state vocabulary the LP rows use.
  const _INLINE_STATE = { done: "SUCCESS", error: "FAILURE", pending: "STARTED" };
  async function augmentAnalyze(job) {
    try {
      const r = await fetch(`/dlc/project/inline-analysis/range/status?req_id=${encodeURIComponent(job.id)}`);
      if (!r.ok) return;
      const d = await r.json();
      job.celery_state = _INLINE_STATE[d.status] || "STARTED";
      job.inline_status = d;
    } catch (e) { /* leave row as registered; state shows '?' */ }
  }

  // triangulate rows come from the MAIN webapp's triangulate Celery task, whose
  // status endpoint already reports Celery-native state — use it directly.
  async function augmentTriangulate(job) {
    try {
      const r = await fetch(`/dlc/project/triangulate/range/status?req_id=${encodeURIComponent(job.id)}`);
      if (!r.ok) return;
      const d = await r.json();
      job.celery_state = d.state || job.celery_state;
      job.tri_status = d;
    } catch (e) { /* leave row as registered; state shows '?' */ }
  }

  function stopAutoRefresh() {
    if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null; }
  }
  function stopDetailPoll() {
    if (detailPollAbort) { detailPollAbort.aborted = true; detailPollAbort = null; }
  }

  function fmtRow(j) {
    const created = new Date((j.created_at || 0) * 1000).toLocaleString();
    const target  = j.lp_project || j.out || (j.in_paths || [])[0] || j.model_dir || j.video || "";
    const stateRaw = j.celery_state || "?";
    let stage = j.celery_info?.stage || "";
    // analyze rows carry inline-analysis counts instead of a Celery stage string.
    if (j.type === "analyze" && j.inline_status) {
      const s = j.inline_status;
      stage = s.status === "done"  ? `${s.n_analyzed} analyzed / ${s.n_skipped} skipped`
            : s.status === "error" ? (s.error || "error")
            : "running…";
    }
    // triangulate rows show the Celery stage/progress, or a terminal summary.
    if (j.type === "triangulate" && j.tri_status) {
      const t = j.tri_status;
      stage = t.state === "SUCCESS"
                ? (t.result && t.result.skipped ? "skipped — no 2D data" : "3D ✓")
            : t.state === "FAILURE" ? (t.error || "error")
            : `${t.stage || "working"}${t.progress ? ` ${t.progress}%` : ""}`;
    }
    const stateCell = stage ? `${stateRaw} <span style="color:var(--text-dim);font-size:.65rem">· ${stage}</span>` : stateRaw;
    // analyze + triangulate run on the MAIN webapp worker; LP Celery revoke can't
    // reach them, so no Cancel button for those rows.
    const canCancel = j.type !== "analyze" && j.type !== "triangulate"
      && stateRaw && !TERMINAL.has(stateRaw) && stateRaw !== "?";
    const cancelBtn = canCancel
      ? `<button class="btn-sm" data-cancel="${j.id}" title="Revoke this Celery task (SIGTERM)" style="opacity:.85">Cancel</button>`
      : `<button class="btn-sm" disabled style="opacity:.3">Cancel</button>`;
    return `
      <td>${j.type || ""}</td>
      <td title="${target}">${target.split("/").slice(-2).join("/")}</td>
      <td>${created}</td>
      <td>${stateCell}</td>
      <td style="display:flex;gap:.25rem">
        <button class="btn-sm" data-view="${j.id}">View</button>
        ${cancelBtn}
      </td>`;
  }

  async function refresh() {
    let body;
    try {
      const r = await fetch("/dlc-3d/lp/jobs");
      body = await r.json();
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-dim)">refresh failed: ${e.message}</td></tr>`;
      return;
    }
    const jobs = body.jobs || [];
    // Pull live state for analyze + triangulate rows from their status endpoints.
    await Promise.all(jobs.filter((j) => j.type === "analyze").map(augmentAnalyze));
    await Promise.all(jobs.filter((j) => j.type === "triangulate").map(augmentTriangulate));
    jobsById.clear();
    for (const j of jobs) jobsById.set(j.id, j);
    tbody.innerHTML = "";
    if (!jobs.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-dim)">no jobs yet — kick off a Convert / Train / EKS / Predict / Analyze / Triangulate run</td></tr>`;
      return;
    }
    for (const j of jobs) {
      const tr = document.createElement("tr");
      tr.innerHTML = fmtRow(j);
      tbody.appendChild(tr);
    }
    tbody.querySelectorAll("button[data-view]").forEach((b) => {
      b.addEventListener("click", () => openDetail(b.dataset.view));
    });
    tbody.querySelectorAll("button[data-cancel]").forEach((b) => {
      b.addEventListener("click", async () => {
        if (!confirm(`Cancel job ${b.dataset.cancel}?`)) return;
        b.disabled = true; b.textContent = "…";
        try {
          await fetch(`/dlc-3d/lp/job/${b.dataset.cancel}/cancel`, { method: "POST" });
        } finally {
          refresh();
        }
      });
    });
    // Keep the table live while the card is open: poll every 5s when something is
    // running, and a slower 15s idle poll otherwise. The idle poll matters — an
    // already-open card that saw no live jobs used to stop refreshing entirely, so
    // a run started elsewhere (e.g. a triangulate batch) never appeared until a
    // manual Refresh. Polling while visible fixes that.
    const hasLive = jobs.some((j) => j.celery_state && !TERMINAL.has(j.celery_state));
    stopAutoRefresh();
    if (!card.classList.contains("hidden")) {
      autoRefreshTimer = setInterval(refresh, hasLive ? 5000 : 15000);
    }
  }

  async function openAnalyzeDetail(jobId, job) {
    stopDetailPoll();
    detail.hidden = false;
    const token = detailPollAbort = { aborted: false };
    while (!token.aborted && !card.classList.contains("hidden")) {
      let d;
      try {
        const r = await fetch(`/dlc/project/inline-analysis/range/status?req_id=${encodeURIComponent(jobId)}`);
        d = await r.json();
      } catch (e) {
        detail.textContent = `fetch failed: ${e.message}`;
        return;
      }
      const rng = job.range || [];
      detail.textContent =
        `job: ${jobId}\n` +
        `type: analyze\n` +
        `status: ${d.status || "?"}\n` +
        `video: ${job.video || ""}\n` +
        `range: start ${rng[0] ?? "?"}, n ${rng[1] ?? "?"}\n` +
        `created: ${new Date((job.created_at || 0) * 1000).toLocaleString()}\n` +
        `analyzed: ${d.n_analyzed ?? 0}   skipped: ${d.n_skipped ?? 0}\n` +
        (d.scorer ? `scorer: ${d.scorer}\n` : "") +
        (d.error ? `error: ${d.error}\n` : "");
      if (["done", "error"].includes(d.status)) return;
      await new Promise((res) => setTimeout(res, 2000));
    }
  }

  async function openTriangulateDetail(jobId, job) {
    stopDetailPoll();
    detail.hidden = false;
    const token = detailPollAbort = { aborted: false };
    while (!token.aborted && !card.classList.contains("hidden")) {
      let d;
      try {
        const r = await fetch(`/dlc/project/triangulate/range/status?req_id=${encodeURIComponent(jobId)}`);
        d = await r.json();
      } catch (e) {
        detail.textContent = `fetch failed: ${e.message}`;
        return;
      }
      const rng = job.range || [];
      const res = d.result || {};
      detail.textContent =
        `job: ${jobId}\n` +
        `type: triangulate\n` +
        `state: ${d.state || "?"}${d.progress ? `  ${d.progress}%` : ""}\n` +
        `stage: ${d.stage || ""}\n` +
        `video: ${job.video || ""}\n` +
        `range: start ${rng[0] ?? "?"}, n ${rng[1] ?? "?"}\n` +
        `created: ${new Date((job.created_at || 0) * 1000).toLocaleString()}\n` +
        (res.skipped ? `skipped: ${res.reason || "no 2D data in range"}\n` : "") +
        (res.pair_name ? `pair: ${res.pair_name}\n` : "") +
        (d.error ? `error: ${d.error}\n` : "");
      if (["SUCCESS", "FAILURE"].includes(d.state)) return;
      await new Promise((res2) => setTimeout(res2, 2000));
    }
  }

  async function openDetail(jobId) {
    const job = jobsById.get(jobId);
    if (job && job.type === "analyze") { return openAnalyzeDetail(jobId, job); }
    if (job && job.type === "triangulate") { return openTriangulateDetail(jobId, job); }
    stopDetailPoll();
    detail.hidden = false;
    const token = detailPollAbort = { aborted: false };
    while (!token.aborted && !card.classList.contains("hidden")) {
      let body;
      try {
        const r = await fetch(`/dlc-3d/lp/job/${jobId}`);
        body = await r.json();
      } catch (e) {
        detail.textContent = `fetch failed: ${e.message}`;
        return;
      }
      const info = body.celery_info || {};
      const tail = (body.log_tail || []).slice(-30).join("\n");
      detail.textContent =
        `job: ${jobId}\n` +
        `type: ${body.type || ""}\n` +
        `state: ${body.celery_state || "?"}\n` +
        (info.stage ? `stage: ${info.stage}\n` : "") +
        `created: ${new Date((body.created_at || 0) * 1000).toLocaleString()}\n` +
        `target: ${body.lp_project || body.out || (body.in_paths || []).join(", ") || body.model_dir || ""}\n` +
        `\n--- log tail (last 30) ---\n${tail}`;
      if (TERMINAL.has(body.celery_state)) return;
      await new Promise((res) => setTimeout(res, 2000));
    }
  }

  $("#btn-lp-jobs-refresh")?.addEventListener("click", refresh);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.attributeName !== "class") continue;
      if (card.classList.contains("hidden")) {
        stopAutoRefresh();
        stopDetailPoll();
      } else {
        refresh();
      }
    }
  }).observe(card, { attributes: true, attributeFilter: ["class"] });
}

initJobsCard();


function initVideosCard() {
  const card = $("#lp-videos-card");
  if (!card) return;

  const projectEl = $("#lp-videos-project");
  const listEl    = $("#lp-videos-list");
  const refreshEl = $("#btn-lp-videos-refresh");
  const selAllEl  = $("#btn-lp-videos-select-all");
  const delEl     = $("#btn-lp-videos-delete");
  const countEl   = $("#lp-videos-selected-count");
  const resEl     = $("#lp-videos-result");

  $("#btn-close-lp-videos")?.addEventListener("click", () => card.classList.add("hidden"));

  // Auto-fill project from the active DLC project (mirrors initPredictCard's logic)
  function syncProject() {
    const dlc = activeDlcProjectFromDom();
    const auto = dlc ? dlc.replace(/\/+$/, "") + "-LP" : "";
    if (!projectEl.value) projectEl.value = auto;
  }

  function fmtSize(n) {
    if (n === null || n === undefined) return "?";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0; let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
  }

  function selectedNames() {
    return Array.from(listEl.querySelectorAll('input[type="checkbox"]:checked'))
      .map(cb => cb.dataset.name);
  }
  function updateCount() {
    countEl.textContent = String(selectedNames().length);
  }

  async function refresh() {
    syncProject();
    const lp = projectEl.value.trim();
    if (!lp) {
      listEl.innerHTML = '<span style="color:var(--text-dim)">specify the LP project above</span>';
      return;
    }
    listEl.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      const r = await fetch(`/dlc-3d/lp/videos/list?lp_project=${encodeURIComponent(lp)}`);
      const body = await r.json();
      if (!r.ok) { listEl.innerHTML = `<span style="color:var(--text-dim)">error: ${body.error || r.status}</span>`; return; }
      const videos = body.videos || [];
      if (!videos.length) {
        listEl.innerHTML = '<span style="color:var(--text-dim)">(no videos)</span>';
        updateCount();
        return;
      }
      listEl.innerHTML = "";
      for (const v of videos) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:.4rem;padding:.1rem 0;border-bottom:1px solid rgba(255,255,255,.05)";
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.dataset.name = v.name; cb.style.cursor = "pointer";
        cb.addEventListener("change", updateCount);
        const name = document.createElement("span");
        name.textContent = v.name;
        name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
        const tag = document.createElement("span");
        tag.style.cssText = "font-size:.68rem;padding:0 .3rem;border-radius:3px";
        if (v.is_symlink) {
          tag.textContent = v.target_exists ? "symlink" : "symlink (broken)";
          tag.style.color = v.target_exists ? "var(--accent, #63b3ed)" : "var(--warn, #e2a050)";
          tag.style.background = "rgba(99,179,237,.12)";
        } else {
          tag.textContent = "file";
          tag.style.color = "var(--text-dim)";
        }
        const size = document.createElement("span");
        size.textContent = fmtSize(v.size_bytes);
        size.style.cssText = "color:var(--text-dim);font-size:.7rem;min-width:4rem;text-align:right";
        row.append(cb, name, tag, size);
        if (v.is_symlink && v.target) {
          row.title = `→ ${v.target}`;
        }
        listEl.appendChild(row);
      }
      updateCount();
    } catch (e) {
      listEl.innerHTML = `<span style="color:var(--text-dim)">error: ${e.message}</span>`;
    }
  }

  refreshEl?.addEventListener("click", refresh);

  selAllEl?.addEventListener("click", () => {
    const boxes = Array.from(listEl.querySelectorAll('input[type="checkbox"]'));
    if (!boxes.length) return;
    const anyUnchecked = boxes.some(b => !b.checked);
    boxes.forEach(b => { b.checked = anyUnchecked; });
    updateCount();
  });

  delEl?.addEventListener("click", async () => {
    const names = selectedNames();
    if (!names.length) { resEl.hidden = false; resEl.textContent = "Nothing selected."; return; }
    if (!confirm(`Delete ${names.length} entry/entries from <lp>/videos/?\nSymlinks unlink only the shortcut.`)) return;
    delEl.disabled = true; const oldText = delEl.innerHTML; delEl.textContent = "Deleting…";
    try {
      const r = await fetch("/dlc-3d/lp/videos/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lp_project: projectEl.value.trim(), video_names: names }),
      });
      const body = await r.json();
      resEl.hidden = false;
      resEl.textContent = JSON.stringify(body, null, 2);
      if (r.ok) await refresh();
    } catch (e) {
      resEl.hidden = false; resEl.textContent = "error: " + e.message;
    } finally {
      delEl.disabled = false; delEl.innerHTML = oldText;
      updateCount();
    }
  });

  // ── Add-videos section (moved from Convert card; same shape) ────────
  const avModeEl    = $("#lp-videos-add-mode");
  const avTargetEl  = $("#lp-videos-add-target");
  const avUpEl      = $("#lp-videos-add-up");
  const avBrowseEl  = $("#lp-videos-add-browse-btn");
  const avPaneEl    = $("#lp-videos-add-browser");
  const avBatchAdd  = $("#lp-videos-add-batch-add");
  const avBatchClr  = $("#lp-videos-add-batch-clear");
  const avBatchList = $("#lp-videos-add-batch-list");
  const avRunEl     = $("#btn-lp-videos-add-run");

  if (avTargetEl) {
    const avBrowser = makeFileBrowser({
      inputEl: avTargetEl, paneEl: avPaneEl, dirOnly: false,
      onPick: (p) => avAddToQueue(p),
    });
    const avQueue = [];

    function avRenderQueue() {
      if (!avQueue.length) {
        avBatchList.style.display = "none";
        avBatchList.innerHTML = "";
        return;
      }
      avBatchList.style.display = "block";
      avBatchList.innerHTML = "";
      avQueue.forEach((p, i) => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.1rem 0";
        const txt = document.createElement("span");
        txt.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
        txt.textContent = p;
        const rm = document.createElement("button");
        rm.className = "btn-sm"; rm.style.cssText = "padding:0 .35rem;font-size:.7rem;opacity:.6";
        rm.textContent = "×";
        rm.addEventListener("click", () => { avQueue.splice(i, 1); avRenderQueue(); });
        row.appendChild(txt); row.appendChild(rm);
        avBatchList.appendChild(row);
      });
    }
    function avAddToQueue(p) {
      p = (p || "").trim(); if (!p) return;
      if (!avQueue.includes(p)) avQueue.push(p);
      avRenderQueue();
    }

    avBatchAdd.addEventListener("click", () => avAddToQueue(avBrowser.getHighlighted() || avTargetEl.value));
    avBatchClr.addEventListener("click", () => { avQueue.length = 0; avRenderQueue(); });
    avBrowseEl.addEventListener("click", () => avBrowser.openAt(projectEl.value.trim() || "/user-data"));
    avUpEl.addEventListener("click", () => avBrowser.up());
    avTargetEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); avBrowser.browseDir(avTargetEl.value.trim()); avPaneEl.classList.remove("hidden"); }
    });

    avRunEl?.addEventListener("click", async () => {
      const lp = projectEl.value.trim();
      if (!lp) { resEl.hidden = false; resEl.textContent = "Specify the LP project above."; return; }
      const paths = avQueue.length ? avQueue.slice() : (avTargetEl.value.trim() ? [avTargetEl.value.trim()] : []);
      if (!paths.length) { resEl.hidden = false; resEl.textContent = "Queue at least one video."; return; }
      avRunEl.disabled = true; resEl.hidden = false; resEl.textContent = "Adding…";
      try {
        const r = await fetch("/dlc-3d/lp/videos/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lp_project: lp, video_paths: paths, mode: avModeEl.value || "symlink" }),
        });
        const body = await r.json();
        resEl.textContent = JSON.stringify(body, null, 2);
        if (r.ok) { avQueue.length = 0; avRenderQueue(); await refresh(); }
      } catch (e) {
        resEl.textContent = "error: " + e.message;
      } finally {
        avRunEl.disabled = false;
      }
    });
  }

  // Refresh whenever the card becomes visible (matches Jobs card pattern)
  new MutationObserver(() => {
    if (!card.classList.contains("hidden")) refresh();
  }).observe(card, { attributes: true, attributeFilter: ["class"] });

  // Also refresh when the active DLC project changes
  const upstream = document.getElementById("dlc-active-path");
  if (upstream) {
    new MutationObserver(() => { if (!card.classList.contains("hidden")) refresh(); })
      .observe(upstream, { childList: true, characterData: true, subtree: true });
  }
}

initVideosCard();


function initLpLauncher() {
  document.querySelectorAll("[data-lp-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.lpTarget;
      const card = document.getElementById(targetId);
      if (!card) return;
      card.classList.remove("hidden");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      // Belt-and-suspenders: also click each card's own refresh button if it
      // has one, so a fresh-open always pulls live data even if the
      // MutationObserver path is intercepted by browser cache shenanigans.
      const refreshBtn = card.querySelector("[id^='btn-'][id$='-refresh'], [id$='-jobs-refresh']");
      refreshBtn?.click();
    });
  });
}

initLpLauncher();
