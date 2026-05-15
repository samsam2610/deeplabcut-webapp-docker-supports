// Lightning-Pose cards — Card 1 (Convert) wiring.

const $ = (sel) => document.querySelector(sel);

// ── Shared file-picker helpers (used by Predict + Convert/Add-Videos cards) ──
const _LP_VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"]);
const _LP_IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]);

function _lpSupportedFile(name) {
  const i = name.lastIndexOf(".");
  if (i < 0) return false;
  const ext = name.slice(i).toLowerCase();
  return _LP_VIDEO_EXTS.has(ext) || _LP_IMAGE_EXTS.has(ext);
}

/** Build a directory-tree picker for any (inputEl, paneEl) pair.
 *  Mirrors analyze.js' video picker. dirOnly=true hides files entirely.
 *  Returns { browseDir, openAt, up, getHighlighted }.
 *  Emits 'lp-picker-dblclick' (bubbles:false) on paneEl on file double-click. */
function _lpMakeBrowser({ inputEl, paneEl, dirOnly }) {
  let highlightedRow = null;
  let highlightedPath = "";
  let browserLoaded = false;
  let currentDir = "";

  function setHighlight(row, path) {
    if (highlightedRow && highlightedRow !== row) {
      highlightedRow.style.background = "";
      highlightedRow.style.outline = "";
    }
    highlightedRow = row;
    highlightedPath = path;
    inputEl.value = path;
    row.style.background = "var(--accent-dim, rgba(99,179,237,.18))";
    row.style.outline = "1px solid var(--accent, #63b3ed)";
  }

  function makeEntry(name, fullPath, isDir) {
    const wrapper = document.createElement("div");
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.15rem .4rem;border-radius:3px;cursor:pointer";
    const arrow = document.createElement("span");
    arrow.style.cssText = "width:.8rem;color:var(--text-dim);font-size:.7rem";
    arrow.textContent = isDir ? "▶" : "·";
    const label = document.createElement("span");
    label.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--mono);font-size:.74rem";
    label.textContent = name + (isDir ? "/" : "");
    row.appendChild(arrow); row.appendChild(label);
    wrapper.appendChild(row);

    const childContainer = document.createElement("div");
    childContainer.style.cssText = "display:none;padding-left:1rem";
    wrapper.appendChild(childContainer);

    let loaded = false, expanded = false;

    if (isDir) {
      row.addEventListener("click", async () => {
        setHighlight(row, fullPath);
        if (!expanded && !loaded) {
          childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">Loading…</span>`;
          childContainer.style.display = "block";
          try {
            const res = await fetch(`/fs/ls?path=${encodeURIComponent(fullPath)}`);
            const d = await res.json();
            childContainer.innerHTML = "";
            if (!d.error) {
              const vis = (d.entries || []).filter((e) =>
                (e.type === "dir" && e.has_media !== false) ||
                (!dirOnly && e.type === "file" && _lpSupportedFile(e.name)));
              vis.forEach((e) =>
                childContainer.appendChild(makeEntry(e.name, fullPath.replace(/\/+$/, "") + "/" + e.name, e.type === "dir")));
              if (!vis.length) childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">(no supported entries)</span>`;
            } else {
              childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">${d.error}</span>`;
            }
          } catch (e) {
            childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">Error loading.</span>`;
          }
          loaded = true; expanded = true; arrow.textContent = "▼";
        } else {
          expanded = !expanded;
          childContainer.style.display = expanded ? "block" : "none";
          arrow.textContent = expanded ? "▼" : "▶";
        }
      });
    } else {
      row.addEventListener("click", () => setHighlight(row, fullPath));
    }

    // Double-click: emit a custom event the parent wires to its queue handler
    row.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      inputEl.value = fullPath;
      paneEl.dispatchEvent(new CustomEvent("lp-picker-dblclick", { detail: { path: fullPath }, bubbles: false }));
      paneEl.classList.add("hidden");
      browserLoaded = false;
    });

    return wrapper;
  }

  async function browseDir(dirPath) {
    browserLoaded = false;
    currentDir = dirPath;
    inputEl.value = dirPath;
    paneEl.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">Loading…</span>`;
    try {
      const res = await fetch(`/fs/ls?path=${encodeURIComponent(dirPath)}`);
      const data = await res.json();
      if (data.error) { paneEl.textContent = data.error; return; }
      paneEl.innerHTML = "";
      const visible = (data.entries || []).filter((e) =>
        (e.type === "dir" && e.has_media !== false) ||
        (!dirOnly && e.type === "file" && _lpSupportedFile(e.name)));
      if (!visible.length) {
        const empty = document.createElement("span");
        empty.style.cssText = "font-size:.78rem;color:var(--text-dim);padding:.3rem;display:block";
        empty.textContent = dirOnly ? "(no subfolders)" : "(no supported video or image files)";
        paneEl.appendChild(empty);
      } else {
        visible.forEach((e) =>
          paneEl.appendChild(makeEntry(e.name, (data.path || dirPath).replace(/\/+$/, "") + "/" + e.name, e.type === "dir")));
      }
      browserLoaded = true;
    } catch (err) {
      paneEl.textContent = "Failed to load.";
    }
  }

  function openAt(initialPath) {
    const isHidden = paneEl.classList.contains("hidden");
    paneEl.classList.toggle("hidden");
    if (!isHidden) return;
    const typed = inputEl.value.trim() || initialPath || "/user-data";
    browseDir(typed);
  }

  function up() {
    const cur = (inputEl.value.trim() || currentDir).replace(/\/+$/, "");
    if (!cur) return;
    const parent = cur.split("/").slice(0, -1).join("/") || "/";
    if (parent !== cur) { browseDir(parent); paneEl.classList.remove("hidden"); }
  }

  return { browseDir, openAt, up, getHighlighted: () => highlightedPath };
}

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

  // ── Add-videos panel ────────────────────────────────────────────────
  const aProj   = $("#lp-add-videos-project");
  const aMode   = $("#lp-add-videos-mode");
  const aBrowse = $("#btn-lp-add-videos-browse");
  const aList   = $("#lp-add-videos-browser");
  const aQueueEl = $("#lp-add-videos-queue");
  const aCountEl = $("#lp-add-videos-count");
  const aRun    = $("#btn-lp-add-videos-run");
  const aResult = $("#lp-add-videos-result");

  let curPath = null;
  const queue = new Set();

  function renderQueue() {
    if (!aQueueEl) return;
    aQueueEl.innerHTML = "";
    Array.from(queue).forEach(p => {
      const li = document.createElement("li");
      li.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.15rem 0";
      const btn = document.createElement("button");
      btn.className = "btn-sm";
      btn.textContent = "−";
      btn.addEventListener("click", () => { queue.delete(p); renderQueue(); });
      const span = document.createElement("span");
      span.textContent = p;
      li.appendChild(btn);
      li.appendChild(span);
      aQueueEl.appendChild(li);
    });
    if (aCountEl) aCountEl.textContent = String(queue.size);
  }

  async function loadDir(path) {
    curPath = path;
    const url = "/dlc-3d/browse" + (path ? "?path=" + encodeURIComponent(path) : "");
    let j;
    try {
      const r = await fetch(url);
      j = await r.json();
      if (!r.ok) { aList.textContent = "browse error: " + (j.error || r.status); return; }
    } catch (e) {
      aList.textContent = "browse error: " + e.message;
      return;
    }
    aList.innerHTML = "";
    const up = document.createElement("div");
    up.textContent = "../";
    up.style.cssText = "cursor:pointer;color:var(--accent)";
    up.addEventListener("click", () => loadDir(j.parent_path || ""));
    aList.appendChild(up);
    (j.entries || []).forEach(e => {
      const row = document.createElement("div");
      row.style.cssText = "display:flex;align-items:center;gap:.4rem;padding:.1rem 0";
      if (e.type === "dir") {
        const a = document.createElement("a");
        a.href = "#";
        a.textContent = e.name + "/";
        a.style.color = "var(--accent)";
        a.addEventListener("click", ev => {
          ev.preventDefault();
          loadDir((j.current_path || curPath || "") + "/" + e.name);
        });
        row.appendChild(a);
      } else {
        const lower = (e.name || "").toLowerCase();
        const isVid = lower.endsWith(".mp4") || lower.endsWith(".avi") || lower.endsWith(".mov") || lower.endsWith(".mkv");
        const btn = document.createElement("button");
        btn.className = "btn-sm";
        btn.disabled = !isVid;
        btn.textContent = "+";
        btn.addEventListener("click", () => {
          const full = (j.current_path || curPath || "") + "/" + e.name;
          queue.add(full);
          renderQueue();
        });
        row.appendChild(btn);
        const span = document.createElement("span");
        span.textContent = e.name;
        if (!isVid) span.style.opacity = "0.5";
        row.appendChild(span);
      }
      aList.appendChild(row);
    });
  }

  aBrowse?.addEventListener("click", () => {
    aList.classList.toggle("hidden");
    if (!aList.classList.contains("hidden") && !curPath) {
      const seed = aProj?.value?.trim() || dstEl?.value?.trim() || "";
      loadDir(seed ? seed.replace(/\/+$/, "").split("/").slice(0, -1).join("/") : "");
    }
  });

  aRun?.addEventListener("click", async () => {
    const lp = aProj?.value?.trim() || dstEl?.value?.trim();
    if (!lp) { aResult.hidden = false; aResult.textContent = "specify LP project"; return; }
    if (!queue.size) { aResult.hidden = false; aResult.textContent = "queue is empty"; return; }
    aRun.disabled = true;
    aRun.textContent = "Adding…";
    try {
      const r = await fetch("/dlc-3d/lp/videos/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lp_project: lp, video_paths: Array.from(queue), mode: aMode.value }),
      });
      const j = await r.json();
      aResult.hidden = false;
      aResult.textContent = JSON.stringify(j, null, 2);
      if (r.ok) { queue.clear(); renderQueue(); }
    } catch (e) {
      aResult.hidden = false;
      aResult.textContent = "error: " + e.message;
    } finally {
      aRun.disabled = false;
      aRun.textContent = "Add videos";
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
  const videoBrowser = _lpMakeBrowser({ inputEl: targetEl, paneEl: browserEl, dirOnly: false });
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
  const destBrowser = _lpMakeBrowser({ inputEl: destEl, paneEl: destBrowserEl, dirOnly: true });
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

  function stopAutoRefresh() {
    if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null; }
  }
  function stopDetailPoll() {
    if (detailPollAbort) { detailPollAbort.aborted = true; detailPollAbort = null; }
  }

  function fmtRow(j) {
    const created = new Date((j.created_at || 0) * 1000).toLocaleString();
    const target  = j.lp_project || j.out || (j.in_paths || [])[0] || j.model_dir || "";
    const stateRaw = j.celery_state || "?";
    const stage = j.celery_info?.stage || "";
    const stateCell = stage ? `${stateRaw} <span style="color:var(--text-dim);font-size:.65rem">· ${stage}</span>` : stateRaw;
    const canCancel = stateRaw && !TERMINAL.has(stateRaw) && stateRaw !== "?";
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
    tbody.innerHTML = "";
    if (!jobs.length) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-dim)">no jobs yet — kick off a Convert / Train / EKS / Predict run</td></tr>`;
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
    // If any job is non-terminal, keep refreshing the table every 5s
    const hasLive = jobs.some((j) => j.celery_state && !TERMINAL.has(j.celery_state));
    stopAutoRefresh();
    if (hasLive && !card.classList.contains("hidden")) {
      autoRefreshTimer = setInterval(refresh, 5000);
    }
  }

  async function openDetail(jobId) {
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
