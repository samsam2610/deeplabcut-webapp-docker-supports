// Lightning-Pose cards — Card 1 (Convert) wiring.

const $ = (sel) => document.querySelector(sel);

function activeDlcProjectPath() {
  // The main dlc-3D UI exposes the active project on a known element if any.
  // Fall back to a global hint set by the project-load flow.
  return (window.__dlc3d_active_project__ || "").trim();
}

function defaultLpDst(src) {
  if (!src) return "";
  return src.replace(/\/+$/, "") + "-LP";
}

function initConvertCard() {
  const card = $("#lp-convert-card");
  if (!card) return;
  const srcEl = $("#lp-convert-src");
  const dstEl = $("#lp-convert-dst");
  const runEl = $("#btn-lp-convert-run");
  const resEl = $("#lp-convert-result");
  const closeBtn = $("#btn-close-lp-convert");

  closeBtn?.addEventListener("click", () => card.classList.add("hidden"));

  // Sync source field with active project when card opens
  const sync = () => {
    const p = activeDlcProjectPath();
    srcEl.value = p;
    if (!dstEl.value) dstEl.value = defaultLpDst(p);
  };
  // Observe class changes to refresh fields when shown
  new MutationObserver(sync).observe(card, { attributes: true, attributeFilter: ["class"] });
  sync();

  runEl.addEventListener("click", async () => {
    runEl.disabled = true;
    resEl.hidden = false;
    resEl.textContent = "Running…";
    try {
      const r = await fetch("/dlc-3d/lp/convert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dlc_dir: srcEl.value.trim(),
          lp_dir:  dstEl.value.trim(),
          force:   $("#lp-convert-force").checked,
        }),
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
