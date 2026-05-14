// Lightning-Pose cards — Card 1 (Convert) wiring.

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

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Running…";
    const payload = { force: $("#lp-convert-force").checked };
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
    };

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
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          `run_dir: ${j.options?.lp_project || ""}\n` +
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
  const projectEl = $("#lp-predict-project");
  const modelEl   = $("#lp-predict-model");
  const noteEl    = $("#lp-predict-model-note");
  const videosEl  = $("#lp-predict-videos");
  const runEl     = $("#btn-lp-predict-run");
  const resEl     = $("#lp-predict-result");

  $("#btn-close-lp-predict")?.addEventListener("click", () => card.classList.add("hidden"));

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
      if (!r.ok) {
        modelEl.innerHTML = `<option value="">— ${body.error || "error"} —</option>`;
        return;
      }
    } catch (e) {
      modelEl.innerHTML = `<option value="">— ${e.message} —</option>`;
      return;
    }
    const models = body.models || [];
    if (!models.length) {
      modelEl.innerHTML = '<option value="">— no models found —</option>';
      noteEl.textContent = "Train a model first, or pick a different LP project.";
      return;
    }
    const usable = models.filter((m) => m.has_checkpoint);
    modelEl.innerHTML = models
      .map((m) => {
        const label = `${m.run_id}${m.has_checkpoint ? " ✓" : " (no checkpoint)"}${m.has_predictions ? " · trained" : ""}`;
        const disabled = m.has_checkpoint ? "" : " disabled";
        return `<option value="${m.path}"${disabled}>${label}</option>`;
      })
      .join("");
    if (usable.length) {
      modelEl.value = usable[0].path;  // pre-select newest usable
    }
    noteEl.textContent = `${usable.length} usable model${usable.length === 1 ? "" : "s"} of ${models.length} total`;
  }

  const onCardOpen = () => {
    syncProjectField();
    reloadModels();
  };
  new MutationObserver(onCardOpen).observe(card, { attributes: true, attributeFilter: ["class"] });
  const upstream = document.getElementById("dlc-active-path");
  if (upstream) {
    new MutationObserver(() => { syncProjectField(); reloadModels(); }).observe(upstream, { childList: true, characterData: true, subtree: true });
  }
  // Refresh models when user edits the project field
  projectEl.addEventListener("change", reloadModels);
  syncProjectField();

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Submitting…";
    const videos = videosEl.value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!videos.length) {
      resEl.textContent = "Error: enter at least one video path";
      runEl.disabled = false;
      return;
    }
    const payload = {
      lp_project: projectEl.value.trim() || undefined,
      model_dir:  modelEl.value || undefined,
      videos,
      skip_viz:   $("#lp-predict-skip-viz").checked,
      overwrite:  $("#lp-predict-overwrite").checked,
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
      resEl.textContent = `Job ${jobId}: PENDING\nmodel_dir: ${body.model_dir || ""}`;
      await pollJob(jobId, (j) => {
        const tail = (j.log_tail || []).slice(-30).join("\n");
        resEl.textContent =
          `state: ${j.celery_state || "PENDING"}\n` +
          `model_dir: ${j.celery_info?.model_dir || j.model_dir || ""}\n` +
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
  $("#btn-close-lp-jobs")?.addEventListener("click", () => card.classList.add("hidden"));

  async function refresh() {
    const r = await fetch("/dlc-3d/lp/jobs");
    const body = await r.json();
    tbody.innerHTML = "";
    for (const j of body.jobs || []) {
      const created = new Date((j.created_at || 0) * 1000).toLocaleString();
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${j.type || ""}</td>
        <td title="${j.lp_project || j.out || (j.in_paths || []).join(",")}">${
          (j.lp_project || j.out || (j.in_paths || [])[0] || "").split("/").slice(-2).join("/")
        }</td>
        <td>${created}</td>
        <td>${j.celery_state || "?"}</td>
        <td><button class="btn-sm" data-job="${j.id}">view</button></td>`;
      tbody.appendChild(tr);
    }
    tbody.querySelectorAll("button[data-job]").forEach((b) => {
      b.addEventListener("click", async () => {
        const r2 = await fetch(`/dlc-3d/lp/job/${b.dataset.job}`);
        detail.hidden = false;
        detail.textContent = JSON.stringify(await r2.json(), null, 2);
      });
    });
  }

  $("#btn-lp-jobs-refresh")?.addEventListener("click", refresh);
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.attributeName === "class" && !card.classList.contains("hidden")) refresh();
    }
  }).observe(card, { attributes: true, attributeFilter: ["class"] });
}

initJobsCard();


function initLpLauncher() {
  document.querySelectorAll("[data-lp-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.lpTarget;
      const card = document.getElementById(targetId);
      if (!card) return;
      card.classList.remove("hidden");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
}

initLpLauncher();
