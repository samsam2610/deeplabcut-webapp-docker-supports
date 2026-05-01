"use strict";
import { _populateGpuSelect } from '/static/js/training.js';
import { buildPairMap, FL3D_FRAME_RE } from './pair_map.mjs';
export { FL3D_FRAME_RE, buildPairMap } from './pair_map.mjs';

(function initFl3d() {
    // Guard: bail out early if fl3d-* IDs are absent (not on the dlc-3D page).
    if (!document.getElementById("fl3d-stem-select")) return;

    const flCard         = document.getElementById("frame-labeler-card");
    const flOpenBtn      = document.getElementById("btn-open-frame-labeler");
    const flCloseBtn     = document.getElementById("btn-close-frame-labeler");
    const flStemSelect   = document.getElementById("fl3d-stem-select");
    const flRefreshBtn   = document.getElementById("fl3d-refresh-btn");
    const flStemStatus   = document.getElementById("fl3d-stem-status");
    const flPlayerSec    = document.getElementById("fl3d-player-section");
    const flBtnPrev      = document.getElementById("fl3d-btn-prev");
    const flBtnNext      = document.getElementById("fl3d-btn-next");
    const flFrameInfo    = document.getElementById("fl3d-frame-info");
    const flFrameName    = document.getElementById("fl3d-frame-name");
    const flCanvas       = document.getElementById("fl3d-canvas");
    const flCtx          = flCanvas.getContext("2d");
    const flCanvasLoading = document.getElementById("fl3d-canvas-loading");
    const flBodypartList = document.getElementById("fl3d-bodypart-list");
    const flBpHint       = document.getElementById("fl3d-bp-hint");
    const flBtnSave        = document.getElementById("fl3d-btn-save");
    const flBtnSaveH5      = document.getElementById("fl3d-btn-save-h5");
    const flSaveStatus     = document.getElementById("fl3d-save-status");
    const flLabelCount     = document.getElementById("fl3d-label-count");
    const flScorerFilename = document.getElementById("fl3d-scorer-filename");
    const flMarkerSizeInput = document.getElementById("fl3d-marker-size");
    const flMarkerSizeVal   = document.getElementById("fl3d-marker-size-val");
    const flShowNamesInput  = document.getElementById("fl3d-show-names");

    // ── TAPNet propagation elements ──────────────────────────────
    const flTapCheckbox      = document.getElementById("fl3d-tap-checkbox");
    const flTapOpts          = document.getElementById("fl3d-tap-opts");
    const flTapCkpt          = document.getElementById("fl3d-tap-ckpt");
    const flTapAnchor        = document.getElementById("fl3d-tap-anchor");
    const flTapCheckBtn      = document.getElementById("fl3d-tap-check-btn");
    const flTapCheckStatus   = document.getElementById("fl3d-tap-check-status");
    const flTapSeqInfo       = document.getElementById("fl3d-tap-seq-info");
    const flTapOverwrite     = document.getElementById("fl3d-tap-overwrite");
    const flTapRunBtn        = document.getElementById("fl3d-tap-run-btn");
    const flTapStopBtn       = document.getElementById("fl3d-tap-stop-btn");
    const flTapRerunBtn      = document.getElementById("fl3d-tap-rerun-btn");
    const flTapConfirmedCount= document.getElementById("fl3d-tap-confirmed-count");
    const flTapStatus        = document.getElementById("fl3d-tap-status");
    const flTapProgress      = document.getElementById("fl3d-tap-progress");
    const flTapTaskId        = document.getElementById("fl3d-tap-task-id");
    const flTapProgressBar   = document.getElementById("fl3d-tap-progress-bar");
    const flTapProgressStage = document.getElementById("fl3d-tap-progress-stage");
    const flTapProgressPct   = document.getElementById("fl3d-tap-progress-pct");
    const flTapLogOutput     = document.getElementById("fl3d-tap-log-output");
    // Per-frame confirm elements
    const flTapFrameBadge    = document.getElementById("fl3d-tap-frame-badge");
    const flTapConfirmBtn    = document.getElementById("fl3d-tap-confirm-btn");
    const flTapConfirmLabel  = document.getElementById("fl3d-tap-confirm-label");

    // ── Machine-labeling elements ────────────────────────────────
    const flMlCheckbox     = document.getElementById("fl3d-ml-checkbox");
    const flMlOpts         = document.getElementById("fl3d-ml-opts");
    const flMlSnapshot     = document.getElementById("fl3d-ml-snapshot");
    const flMlRefreshSnap  = document.getElementById("fl3d-ml-refresh-snap");
    const flMlShuffle      = document.getElementById("fl3d-ml-shuffle");
    const flMlRunBtn       = document.getElementById("fl3d-ml-run-btn");
    const flMlRunAllBtn    = document.getElementById("fl3d-ml-run-all-btn");
    const flMlLikelihood   = document.getElementById("fl3d-ml-likelihood");
    const flMlStopBtn      = document.getElementById("fl3d-ml-stop-btn");
    const flMlStatus       = document.getElementById("fl3d-ml-status");
    const flMlUpdateWrap   = document.getElementById("fl3d-ml-update-wrap");
    const flMlUpdateBtn    = document.getElementById("fl3d-ml-update-btn");
    const flMlUpdateStatus = document.getElementById("fl3d-ml-update-status");
    const flMlProgress     = document.getElementById("fl3d-ml-progress");
    const flMlTaskId       = document.getElementById("fl3d-ml-task-id");
    const flMlProgressBar  = document.getElementById("fl3d-ml-progress-bar");
    const flMlProgressStage= document.getElementById("fl3d-ml-progress-stage");
    const flMlProgressPct  = document.getElementById("fl3d-ml-progress-pct");
    const flMlLogOutput    = document.getElementById("fl3d-ml-log-output");

    // ── State ───────────────────────────────────────────────────
    let _flBodyparts   = [];
    let _flScorer      = "User";
    let _flStemData    = [];      // [{video_stem, frames[]}]
    let _flVideoStem   = null;
    let _flFrames      = [];      // array of filenames
    let _flFrameIdx    = 0;
    let _flLabels      = {};      // {frame_name: {bp: [x, y] | null}}
    let _flDirty       = false;  // unsaved changes since last save/load
    let _flSelectedBp  = null;
    let _flImg         = new Image();
    let _flImgLoaded   = false;
    let _flMarkerRadius   = 4;
    let _flShowNames      = true;
    let _flCursorInCanvas = false;
    let _flHoverBp        = null;   // bodypart marker the cursor is near
    let _flZoom           = 100;
    let _flHidden         = {};  // {frame_name: {bp: bool}} — visibility-toggled markers  // percent of container width (100 = fit to card)

    // ── Sync-frame state ─────────────────────────────────────────
    let _fl3dPairMap      = new Map();
    let _fl3dCamSet       = [];
    let _fl3dFrameNumbers = [];
    let _fl3dPrimaryCam   = 0;
    let _fl3dSyncOn        = false;
    let _fl3dFocusedCam    = 0;
    let _fl3dHoveredCam    = null;
    let _fl3dFrameNumIdx   = 0;
    let _fl3dDirtyFrames   = new Set();

    // Machine labeling state (persists across folder changes)
    let _flMlPollTimer   = null;
    let _flMlActiveTask  = null;
    let _flMlQueue       = [];   // stems queued for "Run All Folders"
    let _flMlQueueIdx    = -1;   // current index in queue (-1 = single-folder mode)
    let _flMlQueueTotal  = 0;

    // ── Machine labeling: toggle panel ──────────────────────────
    flMlCheckbox.addEventListener("change", () => {
      flMlOpts.classList.toggle("hidden", !flMlCheckbox.checked);
      if (flMlCheckbox.checked) {
        _flMlLoadSnapshots();
        _populateGpuSelect("fl3d-ml-gpu");
      }
    });

    // ── Machine labeling: load snapshots ────────────────────────
    async function _flMlLoadSnapshots() {
      try {
        // No shuffle filter — show all shuffles so models from any shuffle are visible.
        // The backend will auto-correct the shuffle when snapshot_path is provided.
        const res  = await fetch("/dlc/project/snapshots");
        const data = await res.json();
        if (data.error) return;
        flMlSnapshot.innerHTML = "";
        const latestOpt = document.createElement("option");
        // Use the actual latest snapshot path (not -1) so shuffle is auto-derived
        latestOpt.value = data.latest_rel_path || "-1";
        const latestSuffix = data.latest_label
          ? ` — ${data.latest_label}${data.latest_iteration != null ? "  ·  iter " + data.latest_iteration.toLocaleString() : ""}${data.latest_shuffle != null ? "  ·  sh" + data.latest_shuffle : ""}`
          : "";
        latestOpt.textContent = `Latest${latestSuffix}`;
        flMlSnapshot.appendChild(latestOpt);
        (data.snapshots || []).forEach(s => {
          const opt = document.createElement("option");
          opt.value = s.rel_path;
          const shuffleSuffix = s.shuffle != null ? `  ·  sh${s.shuffle}` : "";
          opt.textContent = `${s.label}${s.iteration != null ? "  ·  iter " + s.iteration.toLocaleString() : ""}${shuffleSuffix}`;
          flMlSnapshot.appendChild(opt);
        });
      } catch (err) {
        console.error("flMlLoadSnapshots:", err);
      }
    }

    flMlRefreshSnap.addEventListener("click", _flMlLoadSnapshots);
    flMlShuffle.addEventListener("change", _flMlLoadSnapshots);

    // ── Machine labeling: run / stop ────────────────────────────
    function _flMlSetRunning(running) {
      flMlRunBtn.classList.toggle("hidden",    running);
      flMlRunAllBtn.classList.toggle("hidden", running);
      flMlStopBtn.classList.toggle("hidden",  !running);
      flMlRunBtn.disabled    = running;
      flMlRunAllBtn.disabled = running;
      if (running) flMlUpdateWrap.classList.add("hidden");
    }

    function _flMlQueueLabel() {
      if (_flMlQueueIdx < 0 || _flMlQueueTotal <= 1) return "";
      return ` (${_flMlQueueIdx + 1}/${_flMlQueueTotal}: ${_flMlQueue[_flMlQueueIdx]})`;
    }

    function _flMlStartPolling(taskId) {
      flMlProgress.classList.remove("hidden", "state-success", "state-fail");
      flMlTaskId.textContent        = taskId.slice(0, 12) + "…";
      flMlProgressBar.style.width   = "0%";
      flMlProgressPct.textContent   = "0 %";
      flMlProgressStage.textContent = "Queued" + _flMlQueueLabel();
      flMlLogOutput.textContent     = "Waiting for output…";
      _flMlSetRunning(true);
      if (_flMlPollTimer) clearInterval(_flMlPollTimer);
      _flMlPollTimer = setInterval(() => _flMlPoll(taskId), 2000);
      _flMlPoll(taskId);
    }

    async function _flMlPoll(taskId) {
      try {
        const res  = await fetch(`/status/${taskId}`);
        const data = await res.json();
        const pct  = Math.min(data.progress || 0, 100);
        flMlProgressBar.style.width   = pct + "%";
        flMlProgressPct.textContent   = pct + " %";
        flMlProgressStage.textContent = (data.stage || data.state) + _flMlQueueLabel();
        if (data.log) {
          flMlLogOutput.textContent = data.log;
          flMlLogOutput.scrollTop   = flMlLogOutput.scrollHeight;
        }
        if (data.state === "SUCCESS") {
          clearInterval(_flMlPollTimer); _flMlPollTimer = null;
          if (data.result && data.result.log) flMlLogOutput.textContent = data.result.log;
          // Reload labels for the current stem so the user sees machine labels immediately
          if (_flVideoStem) {
            const found = _flStemData.find(s => s.video_stem === _flVideoStem);
            if (found) await _flSelectStem(found.video_stem, found.frames);
          }
          // Advance queue if running all folders
          if (_flMlQueueIdx >= 0 && _flMlQueueIdx < _flMlQueue.length - 1) {
            _flMlQueueIdx++;
            flMlStatus.textContent = `Folder ${_flMlQueueIdx + 1}/${_flMlQueueTotal} done — starting next…`;
            flMlStatus.className   = "fe-extract-status ok";
            await _flMlDispatch(_flMlQueue[_flMlQueueIdx]);
          } else {
            // Done (single folder or last in queue)
            _flMlQueue = []; _flMlQueueIdx = -1; _flMlQueueTotal = 0;
            flMlProgress.classList.add("state-success");
            flMlProgressStage.textContent = "✓ Machine labeling complete";
            flMlProgressBar.style.width   = "100%";
            flMlProgressPct.textContent   = "100 %";
            flMlStatus.textContent = "Labels loaded — review and correct as needed.";
            flMlStatus.className   = "fe-extract-status ok";
            _flMlSetRunning(false);
          }
        }
        if (data.state === "FAILURE" || data.state === "REVOKED") {
          clearInterval(_flMlPollTimer); _flMlPollTimer = null;
          _flMlQueue = []; _flMlQueueIdx = -1; _flMlQueueTotal = 0;
          const userStopped = data.state === "REVOKED" || (data.error || "").includes("__USER_STOPPED__");
          flMlProgress.classList.add("state-fail");
          flMlProgressStage.textContent = userStopped ? "✗ Stopped by user" : "✗ " + (data.error || "Failed").split("\n")[0];
          if (!userStopped) flMlLogOutput.textContent = data.error || "An unknown error occurred.";
          flMlStatus.textContent = userStopped ? "Machine labeling stopped." : "";
          flMlStatus.className   = "fe-extract-status";
          _flMlSetRunning(false);
        }
      } catch (err) {
        console.error("flMlPoll:", err);
      }
    }

    function _flMlBuildBody(videoStem) {
      const snapVal = flMlSnapshot.value;
      return {
        video_stem:           videoStem,
        shuffle:              parseInt(flMlShuffle.value) || 1,
        trainingsetindex:     parseInt(document.getElementById("fl3d-ml-tsidx").value) ?? 0,
        gputouse:             document.getElementById("fl3d-ml-gpu").value !== ""
                                ? parseInt(document.getElementById("fl3d-ml-gpu").value) : null,
        snapshot_path:        snapVal !== "-1" ? snapVal : null,
        likelihood_threshold: parseFloat(flMlLikelihood.value) || 0.9,
      };
    }

    async function _flMlDispatch(videoStem) {
      try {
        const res  = await fetch("/dlc/project/machine-label-frames", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(_flMlBuildBody(videoStem)),
        });
        const data = await res.json();
        if (!res.ok) {
          flMlStatus.textContent = data.error || "Failed to start machine labeling.";
          flMlStatus.className   = "fe-extract-status err";
          _flMlQueue = []; _flMlQueueIdx = -1; _flMlQueueTotal = 0;
          _flMlSetRunning(false);
          return;
        }
        _flMlActiveTask = data.task_id;
        _flMlStartPolling(data.task_id);
      } catch (err) {
        flMlStatus.textContent = "Network error: " + err.message;
        flMlStatus.className   = "fe-extract-status err";
        _flMlQueue = []; _flMlQueueIdx = -1; _flMlQueueTotal = 0;
        _flMlSetRunning(false);
      }
    }

    flMlRunBtn.addEventListener("click", async () => {
      if (!_flVideoStem) {
        flMlStatus.textContent = "Select a labeled-data folder first.";
        flMlStatus.className   = "fe-extract-status err";
        return;
      }
      flMlStatus.textContent = "";
      flMlStatus.className   = "fe-extract-status";
      _flMlQueue = []; _flMlQueueIdx = -1; _flMlQueueTotal = 0;
      await _flMlDispatch(_flVideoStem);
    });

    flMlRunAllBtn.addEventListener("click", async () => {
      if (!_flStemData || _flStemData.length === 0) {
        flMlStatus.textContent = "No labeled-data folders loaded.";
        flMlStatus.className   = "fe-extract-status err";
        return;
      }
      flMlStatus.textContent = "";
      flMlStatus.className   = "fe-extract-status";
      _flMlQueue      = _flStemData.map(s => s.video_stem);
      _flMlQueueIdx   = 0;
      _flMlQueueTotal = _flMlQueue.length;
      flMlStatus.textContent = `Starting ${_flMlQueueTotal} folder(s)…`;
      flMlStatus.className   = "fe-extract-status ok";
      await _flMlDispatch(_flMlQueue[0]);
    });

    flMlStopBtn.addEventListener("click", async () => {
      if (!_flMlActiveTask) return;
      // Cancel the whole queue
      _flMlQueue = []; _flMlQueueIdx = -1; _flMlQueueTotal = 0;
      flMlStopBtn.disabled = true;
      try {
        await fetch("/dlc/project/machine-label-frames/stop", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ task_id: _flMlActiveTask }),
        });
        flMlStatus.textContent = "Stop signal sent.";
        flMlStatus.className   = "fe-extract-status";
      } catch (err) {
        flMlStatus.textContent = "Stop error: " + err.message;
        flMlStatus.className   = "fe-extract-status err";
        flMlStopBtn.disabled = false;
      }
    });

    // ══════════════════════════════════════════════════════════════
    // TAPNet propagation
    // ══════════════════════════════════════════════════════════════
    let _flTapPollTimer   = null;
    let _flTapActiveTask  = null;
    let _flTapConfirmed   = new Set();   // confirmed anchor frame names
    let _flTapnetFrames   = new Set();   // frames labeled by TAPNet

    // Load confirmed anchors + tapnet frames from server for current stem
    async function _flTapLoadSidecars() {
      if (!_flVideoStem) return;
      try {
        const res  = await fetch(`/dlc/project/tapnet-confirmed?video_stem=${encodeURIComponent(_flVideoStem)}`);
        if (!res.ok) return;
        const data = await res.json();
        _flTapConfirmed  = new Set(data.confirmed     || []);
        _flTapnetFrames  = new Set(data.tapnet_frames || []);
      } catch (_) { /* non-critical */ }
      _flTapUpdateFrameStatus();
      _flTapUpdateConfirmedCount();
    }

    // Update the per-frame badge + confirm button for the current frame
    function _flTapUpdateFrameStatus() {
      const fname = _fl3dActiveFname();
      if (!fname || !flTapCheckbox.checked) {
        flTapFrameBadge.classList.add("hidden");
        flTapConfirmBtn.classList.add("hidden");
        return;
      }
      flTapConfirmBtn.classList.remove("hidden");
      const isConfirmed = _flTapConfirmed.has(fname);
      const isTapnet    = _flTapnetFrames.has(fname);
      flTapConfirmLabel.textContent = isConfirmed ? "✓ Confirmed anchor" : "Confirm as anchor";
      flTapConfirmBtn.style.background = isConfirmed ? "var(--accent)" : "";
      flTapConfirmBtn.style.color      = isConfirmed ? "#fff" : "";
      if (isConfirmed) {
        flTapFrameBadge.textContent = "Anchor";
        flTapFrameBadge.style.color = "var(--accent)";
        flTapFrameBadge.style.borderColor = "var(--accent)";
        flTapFrameBadge.classList.remove("hidden");
      } else if (isTapnet) {
        flTapFrameBadge.textContent = "TAPNet";
        flTapFrameBadge.style.color = "var(--text-dim)";
        flTapFrameBadge.style.borderColor = "var(--border)";
        flTapFrameBadge.classList.remove("hidden");
      } else {
        flTapFrameBadge.classList.add("hidden");
      }
    }

    // Update the confirmed-count display and rerun button visibility
    function _flTapUpdateConfirmedCount() {
      const n = _flTapConfirmed.size;
      if (n > 0 && flTapCheckbox.checked) {
        flTapConfirmedCount.textContent = `${n} confirmed anchor${n === 1 ? "" : "s"}`;
        flTapConfirmedCount.classList.remove("hidden");
        flTapRerunBtn.classList.remove("hidden");
      } else {
        flTapConfirmedCount.classList.add("hidden");
        flTapRerunBtn.classList.add("hidden");
      }
    }

    flTapCheckbox.addEventListener("change", () => {
      flTapOpts.classList.toggle("hidden", !flTapCheckbox.checked);
      _flTapUpdateFrameStatus();
      _flTapUpdateConfirmedCount();
      if (flTapCheckbox.checked && _flVideoStem) _flTapLoadSidecars();
    });

    // Confirm / unconfirm current frame as anchor
    flTapConfirmBtn.addEventListener("click", async () => {
      const fname = _fl3dActiveFname();
      if (!fname || !_flVideoStem) return;
      try {
        const res  = await fetch("/dlc/project/tapnet-confirm-frame", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ video_stem: _flVideoStem, frame_name: fname }),
        });
        const data = await res.json();
        if (data.error) { console.error("confirm-frame:", data.error); return; }
        if (data.confirmed) _flTapConfirmed.add(fname);
        else                _flTapConfirmed.delete(fname);
        _flTapUpdateFrameStatus();
        _flTapUpdateConfirmedCount();
      } catch (err) {
        console.error("confirm-frame error:", err);
      }
    });

    // Re-run with confirmed anchors
    flTapRerunBtn.addEventListener("click", async () => {
      if (!_flVideoStem) {
        flTapStatus.textContent = "Select a labeled-data folder first.";
        flTapStatus.className   = "fe-extract-status err";
        return;
      }
      const ckpt = flTapCkpt.value.trim();
      if (!ckpt) {
        flTapStatus.textContent = "Enter the checkpoint path.";
        flTapStatus.className   = "fe-extract-status err";
        return;
      }
      flTapStatus.textContent = "";
      flTapStatus.className   = "fe-extract-status";
      try {
        const res  = await fetch("/dlc/project/tapnet-propagate-multi", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({
            video_stem:            _flVideoStem,
            tapnet_checkpoint_path: ckpt,
            gpu_index:             0,
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          flTapStatus.textContent = data.error || "Failed to start multi-anchor TAPNet.";
          flTapStatus.className   = "fe-extract-status err";
          return;
        }
        _flTapActiveTask = data.task_id;
        _flTapStartPolling(data.task_id);
      } catch (err) {
        flTapStatus.textContent = "Network error: " + err.message;
        flTapStatus.className   = "fe-extract-status err";
      }
    });

    function _flTapSetRunning(running) {
      flTapRunBtn.classList.toggle("hidden",  running);
      flTapStopBtn.classList.toggle("hidden", !running);
    }

    flTapCheckBtn.addEventListener("click", async () => {
      if (!_flVideoStem) {
        flTapCheckStatus.textContent = "Select a labeled-data folder first.";
        flTapCheckStatus.className   = "fe-extract-status err";
        return;
      }
      flTapCheckStatus.textContent = "Checking…";
      flTapCheckStatus.className   = "fe-extract-status";
      flTapSeqInfo.classList.add("hidden");
      try {
        const res  = await fetch(`/dlc/project/tapnet-check?video_stem=${encodeURIComponent(_flVideoStem)}`);
        const data = await res.json();
        if (!res.ok) {
          flTapCheckStatus.textContent = data.error || "Check failed.";
          flTapCheckStatus.className   = "fe-extract-status err";
          return;
        }
        const n = data.propagatable_count;
        flTapCheckStatus.textContent = `${n} propagatable sequence(s) found`;
        flTapCheckStatus.className   = "fe-extract-status " + (n > 0 ? "ok" : "");
        if (data.sequences && data.sequences.length > 0) {
          flTapSeqInfo.innerHTML = data.sequences.map(s => {
            const badge = s.propagatable
              ? `<span style="color:var(--accent)">✓ anchor: ${s.anchor}</span>`
              : `<span style="color:var(--text-dim)">✗ no labeled anchor</span>`;
            return `<div>${s.first_frame} → ${s.last_frame} &nbsp;(${s.frame_count} frames) &nbsp;${badge}</div>`;
          }).join("");
          flTapSeqInfo.classList.remove("hidden");
        }
      } catch (err) {
        flTapCheckStatus.textContent = "Network error: " + err.message;
        flTapCheckStatus.className   = "fe-extract-status err";
      }
    });

    flTapRunBtn.addEventListener("click", async () => {
      if (!_flVideoStem) {
        flTapStatus.textContent = "Select a labeled-data folder first.";
        flTapStatus.className   = "fe-extract-status err";
        return;
      }
      const ckpt = flTapCkpt.value.trim();
      if (!ckpt) {
        flTapStatus.textContent = "Enter the checkpoint path.";
        flTapStatus.className   = "fe-extract-status err";
        return;
      }
      flTapStatus.textContent = "";
      flTapStatus.className   = "fe-extract-status";
      try {
        const res  = await fetch("/dlc/project/tapnet-propagate", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({
            video_stem:             _flVideoStem,
            tapnet_checkpoint_path: ckpt,
            anchor:                 flTapAnchor.value,
            gpu_index:              0,
            overwrite:              flTapOverwrite.checked,
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          flTapStatus.textContent = data.error || "Failed to start TAPNet.";
          flTapStatus.className   = "fe-extract-status err";
          return;
        }
        _flTapActiveTask = data.task_id;
        _flTapStartPolling(data.task_id);
      } catch (err) {
        flTapStatus.textContent = "Network error: " + err.message;
        flTapStatus.className   = "fe-extract-status err";
      }
    });

    flTapStopBtn.addEventListener("click", async () => {
      if (!_flTapActiveTask) return;
      flTapStopBtn.disabled = true;
      try {
        await fetch("/dlc/project/tapnet-propagate/stop", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ task_id: _flTapActiveTask }),
        });
        flTapStatus.textContent = "Stop signal sent.";
        flTapStatus.className   = "fe-extract-status";
      } catch (err) {
        flTapStatus.textContent = "Stop error: " + err.message;
        flTapStatus.className   = "fe-extract-status err";
        flTapStopBtn.disabled = false;
      }
    });

    function _flTapStartPolling(taskId) {
      flTapProgress.classList.remove("hidden", "state-success", "state-fail");
      flTapTaskId.textContent        = taskId.slice(0, 12) + "…";
      flTapProgressBar.style.width   = "0%";
      flTapProgressPct.textContent   = "0 %";
      flTapProgressStage.textContent = "Queued";
      flTapLogOutput.textContent     = "Waiting for output…";
      _flTapSetRunning(true);
      if (_flTapPollTimer) clearInterval(_flTapPollTimer);
      _flTapPollTimer = setInterval(() => _flTapPoll(taskId), 2000);
      _flTapPoll(taskId);
    }

    async function _flTapPoll(taskId) {
      try {
        const res  = await fetch(`/status/${taskId}`);
        const data = await res.json();
        const pct  = Math.min(data.progress || 0, 100);
        flTapProgressBar.style.width   = pct + "%";
        flTapProgressPct.textContent   = pct + " %";
        flTapProgressStage.textContent = data.stage || data.state;
        if (data.log) {
          flTapLogOutput.textContent = data.log;
          flTapLogOutput.scrollTop   = flTapLogOutput.scrollHeight;
        }
        if (data.state === "SUCCESS") {
          clearInterval(_flTapPollTimer); _flTapPollTimer = null;
          const r = data.result || {};
          if (r.log) flTapLogOutput.textContent = r.log;
          flTapProgress.classList.add("state-success");
          flTapProgressStage.textContent = "✓ Propagation complete";
          flTapProgressBar.style.width   = "100%";
          flTapProgressPct.textContent   = "100 %";
          flTapStatus.textContent = `Done — ${r.frames_labeled || 0} frame(s) labeled across ${r.sequences_found || 0} sequence(s).`;
          flTapStatus.className   = "fe-extract-status ok";
          _flTapSetRunning(false);
          // Reload labels so the user sees propagated markers immediately
          if (_flVideoStem) {
            const found = _flStemData.find(s => s.video_stem === _flVideoStem);
            if (found) await _flSelectStem(found.video_stem, found.frames);
          }
        }
        if (data.state === "FAILURE" || data.state === "REVOKED") {
          clearInterval(_flTapPollTimer); _flTapPollTimer = null;
          const userStopped = data.state === "REVOKED" || (data.error || "").includes("__USER_STOPPED__");
          flTapProgress.classList.add("state-fail");
          flTapProgressStage.textContent = userStopped ? "✗ Stopped" : "✗ " + (data.error || "Failed").split("\n")[0];
          if (!userStopped) flTapLogOutput.textContent = data.error || "An unknown error occurred.";
          flTapStatus.textContent = userStopped ? "TAPNet stopped." : "";
          flTapStatus.className   = "fe-extract-status";
          _flTapSetRunning(false);
        }
      } catch (err) {
        console.error("flTapPoll:", err);
      }
    }

    function _flUpdateScorerFilename() {
      if (flScorerFilename) flScorerFilename.textContent = `CollectedData_${_flScorer}.csv`;
    }

    // ── Napari-inspired color palette ────────────────────────────
    const FL_COLORS = [
      "#f87171","#fb923c","#fbbf24","#a3e635","#34d399",
      "#22d3ee","#818cf8","#e879f9","#f43f5e","#10b981",
      "#3b82f6","#ec4899","#f59e0b","#84cc16","#06b6d4",
    ];
    function _flColor(i) { return FL_COLORS[i % FL_COLORS.length]; }

    // ── Open / close ────────────────────────────────────────────
    if (flOpenBtn) {
      flOpenBtn.addEventListener("click", () => {
        flCard.classList.remove("hidden");
        flCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
        _flLoad();
      });
    }

    flCloseBtn.addEventListener("click", () => {
      flCard.classList.add("hidden");
    });

    // ── Marker display controls ──────────────────────────────────
    const flZoomInput = document.getElementById("fl3d-zoom");
    const flZoomVal   = document.getElementById("fl3d-zoom-val");

    flZoomInput.addEventListener("input", () => {
      _flZoom = parseInt(flZoomInput.value, 10);
      flZoomVal.textContent = _flZoom + " %";
      if (_flImgLoaded) { _flFitCanvas(); _flDraw(); }
    });

    // Wire primary tile's size slider once. Sibling-tile sliders are wired in _fl3dRenderTile.
    const _flPrimaryTile = document.querySelector("#fl3d-canvas-row .fl3d-tile:not(.fl3d-tile-sibling)");
    if (_flPrimaryTile) _fl3dWireTileSizeSlider(_flPrimaryTile);

    // Equalize button: reset all per-tile weights to 100.
    const flEqualizeBtn = document.getElementById("fl3d-equalize-btn");
    flEqualizeBtn.addEventListener("click", () => {
      document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
        _fl3dResetTileWeight(t);
        if (t.dataset.fname) _fl3dDrawTileMarkers(t, t.dataset.fname);
      });
    });

    flMarkerSizeInput.addEventListener("input", () => {
      _flMarkerRadius = parseInt(flMarkerSizeInput.value, 10);
      flMarkerSizeVal.textContent = _flMarkerRadius;
      // In sync mode, _flDraw paints stale _flImg onto the primary tile's
      // canvas (sync nav updates each tile's _fl3dImg but not the global).
      // Defer fully to per-tile redraws, which use tile._fl3dImg correctly.
      if (_fl3dSyncOn) {
        document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
          if (t.dataset.fname) _fl3dDrawTileMarkers(t, t.dataset.fname);
        });
      } else {
        _flDraw();
      }
    });

    flShowNamesInput.addEventListener("change", () => {
      _flShowNames = flShowNamesInput.checked;
      if (_fl3dSyncOn) {
        document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
          if (t.dataset.fname) _fl3dDrawTileMarkers(t, t.dataset.fname);
        });
      } else {
        _flDraw();
      }
    });

    document.getElementById("fl3d-sync-frame").addEventListener("change", (e) => {
      const row = document.getElementById("fl3d-canvas-row");
      if (e.target.checked) {
        if (_fl3dCamSet.length < 2) {
          e.target.checked = false;
          flStemStatus.textContent = "Sync Frame needs at least 2 cams in this folder.";
          return;
        }
        // Determine current cam + frame from current fname
        const fname = _flFrames[_flFrameIdx];
        const m = FL3D_FRAME_RE.exec(fname || "");
        if (!m) { e.target.checked = false; return; }
        _fl3dPrimaryCam = +m[1];
        _fl3dFocusedCam = _fl3dPrimaryCam;
        const currentFrameNum = +m[3];
        _fl3dFrameNumIdx = _fl3dFrameNumbers.indexOf(currentFrameNum);
        if (_fl3dFrameNumIdx < 0) _fl3dFrameNumIdx = 0;
        _fl3dSyncOn = true;
        // Sync ON: bump global slider max to 500, reveal per-tile sliders + equalize.
        flZoomInput.max = "500";
        row.classList.add("sync-on");
        flEqualizeBtn.classList.remove("hidden");
        // Reset primary tile's weight for a clean state on each sync ON.
        const primaryTile = row.querySelector(".fl3d-tile:not(.fl3d-tile-sibling)");
        if (primaryTile) _fl3dResetTileWeight(primaryTile);
        _flShowFrame(_fl3dFrameNumIdx);
      } else {
        // Capture focused fname while sync is still on
        const focusedFname = _fl3dActiveFname();
        _fl3dSyncOn = false;
        row.querySelectorAll(".fl3d-tile-sibling").forEach(t => t.remove());
        // Sync OFF: cap global slider at 300, hide per-tile sliders + equalize, clamp value.
        flZoomInput.max = "300";
        if (parseInt(flZoomInput.value, 10) > 300) {
          flZoomInput.value = "300";
          _flZoom = 300;
          flZoomVal.textContent = "300 %";
        }
        row.classList.remove("sync-on");
        flEqualizeBtn.classList.add("hidden");
        // Reset primary tile's weight so single-tile mode is unaffected.
        const primaryTile = row.querySelector(".fl3d-tile:not(.fl3d-tile-sibling)");
        if (primaryTile) _fl3dResetTileWeight(primaryTile);
        const idx = _flFrames.indexOf(focusedFname);
        if (idx >= 0) _flFrameIdx = idx;
        _flShowFrame(_flFrameIdx);
      }
    });

    // ── Load bodyparts + stems ───────────────────────────────────
    async function _flLoad() {
      try {
        const res  = await fetch("/dlc/project/bodyparts");
        const data = await res.json();
        _flBodyparts = data.bodyparts || [];
        _flScorer    = data.scorer    || "User";
        _flUpdateScorerFilename();
        _flRenderBodypartList();
      } catch (e) { console.error("FL bodyparts:", e); }
      await _flLoadStems();
    }

    async function _flLoadStems() {
      flStemStatus.textContent = "";
      flStemStatus.className   = "fe-extract-status";
      try {
        const res  = await fetch("/dlc/project/labeled-frames");
        const data = await res.json();
        if (data.error) {
          flStemStatus.textContent = data.error;
          flStemStatus.className   = "fe-extract-status err";
          return;
        }
        _flStemData = data.video_stems || [];
        const prev  = flStemSelect.value;
        flStemSelect.innerHTML = '<option value="">— select video —</option>';
        _flStemData.forEach(s => {
          const opt = document.createElement("option");
          opt.value       = s.video_stem;
          opt.textContent = `${s.video_stem}  (${s.frames.length} frame${s.frames.length !== 1 ? "s" : ""})`;
          flStemSelect.appendChild(opt);
        });
        // Restore selection or auto-select if only one
        if (_flStemData.length === 1) {
          flStemSelect.value = _flStemData[0].video_stem;
          await _flSelectStem(_flStemData[0].video_stem, _flStemData[0].frames);
        } else if (prev && _flStemData.find(s => s.video_stem === prev)) {
          flStemSelect.value = prev;
          const found = _flStemData.find(s => s.video_stem === prev);
          if (found) await _flSelectStem(found.video_stem, found.frames);
        }
      } catch (e) {
        flStemStatus.textContent = `Error: ${e.message}`;
        flStemStatus.className   = "fe-extract-status err";
      }
    }

    flRefreshBtn.addEventListener("click", () => _flLoadStems());

    flStemSelect.addEventListener("change", async () => {
      const stem = flStemSelect.value;
      if (!stem) { flPlayerSec.classList.add("hidden"); return; }
      const found = _flStemData.find(s => s.video_stem === stem);
      if (found) await _flSelectStem(found.video_stem, found.frames);
    });

    async function _flSelectStem(stem, frames) {
      _flVideoStem = stem;
      _flFrames    = frames;
      _flFrameIdx  = 0;
      _flDirty     = false;

      // Build pair map and surface cam set for sync-frame UI
      const _fl3dPairBuild = buildPairMap(_flFrames);
      _fl3dPairMap      = _fl3dPairBuild.pairMap;
      _fl3dCamSet       = _fl3dPairBuild.camSet;
      _fl3dFrameNumbers = _fl3dPairBuild.frameNumbers;

      const syncLbl = document.getElementById("fl3d-sync-frame-label");
      if (syncLbl) {
        syncLbl.style.display = _fl3dCamSet.length >= 2 ? "flex" : "none";
      }

      // Fetch existing labels
      try {
        const res  = await fetch(`/dlc/project/labels/${encodeURIComponent(stem)}`);
        const data = await res.json();
        if (!data.error) {
          _flLabels = data.labels || {};
          _flScorer = data.scorer || _flScorer;
          _flUpdateScorerFilename();
        }
      } catch (_) { _flLabels = {}; }

      // Show "Update Threshold" button only when raw predictions exist
      flMlUpdateWrap.classList.add("hidden");
      flMlUpdateStatus.textContent = "";
      try {
        const r = await fetch(`/dlc/project/machine-label-raw?video_stem=${encodeURIComponent(stem)}`);
        const d = await r.json();
        if (d.exists) flMlUpdateWrap.classList.remove("hidden");
      } catch (_) {}

      flPlayerSec.classList.remove("hidden");
      _flUpdateLabelCount();
      _flShowFrame(0);

      // Load TAPNet sidecars (confirmed anchors + tapnet-labeled frames)
      _flTapConfirmed  = new Set();
      _flTapnetFrames  = new Set();
      _flTapLoadSidecars();
    }

    // ── Update Threshold ─────────────────────────────────────────
    flMlUpdateBtn.addEventListener("click", async () => {
      if (!_flVideoStem) return;
      flMlUpdateBtn.disabled       = true;
      flMlUpdateStatus.textContent = "Dispatching…";
      flMlUpdateStatus.className   = "fe-extract-status";
      try {
        const res  = await fetch("/dlc/project/machine-label-reapply", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({
            video_stem:           _flVideoStem,
            likelihood_threshold: parseFloat(flMlLikelihood.value) || 0.9,
          }),
        });
        const dispatched = await res.json();
        if (!res.ok || dispatched.error) {
          flMlUpdateStatus.textContent = `Error: ${dispatched.error || "unknown"}`;
          flMlUpdateStatus.className   = "fe-extract-status err";
          flMlUpdateBtn.disabled = false;
          return;
        }

        // Poll until the worker finishes
        const taskId = dispatched.task_id;
        flMlUpdateStatus.textContent = "Applying…";
        let data = null;
        while (true) {
          await new Promise(r => setTimeout(r, 1000));
          const sr = await fetch(`/status/${taskId}`);
          const s  = await sr.json();
          if (s.state === "SUCCESS") {
            data = s.result;
            break;
          } else if (s.state === "FAILURE") {
            throw new Error(s.error || "Worker task failed");
          }
          // PENDING / PROGRESS — keep polling
        }

        flMlUpdateStatus.textContent =
          `Done — ${data.n_machine} machine label(s), ${data.n_human} human preserved`;
        flMlUpdateStatus.className = "fe-extract-status ok";
        // Reload labels so the labeler reflects the new threshold immediately
        const found = _flStemData.find(s => s.video_stem === _flVideoStem);
        if (found) await _flSelectStem(found.video_stem, found.frames);
      } catch (err) {
        flMlUpdateStatus.textContent = `Error: ${err.message}`;
        flMlUpdateStatus.className   = "fe-extract-status err";
      } finally {
        flMlUpdateBtn.disabled = false;
      }
    });

    // ── Render body-part chip list ───────────────────────────────
    function _flRenderBodypartList() {
      flBodypartList.innerHTML = "";
      if (!_flBodyparts.length) {
        flBpHint.classList.remove("hidden");
        return;
      }
      flBpHint.classList.add("hidden");
      _flBodyparts.forEach((bp, i) => {
        const chip = document.createElement("button");
        chip.className = "fl-bp-chip";
        chip.dataset.bp = bp;
        chip.style.setProperty("--fl-color", _flColor(i));
        chip.innerHTML =
          `<span class="fl-bp-dot"></span>` +
          `<span class="fl-bp-name">${bp}</span>` +
          `<svg class="fl-bp-check" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>` +
          `<svg class="fl-bp-eye-slash" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
        chip.addEventListener("click", () => _flSelectBp(bp));
        chip.addEventListener("dblclick", e => {
          e.preventDefault();
          _flSelectBp(bp);
          _flToggleVisibility(bp);
        });
        flBodypartList.appendChild(chip);
      });
      // Default: select first
      if (_flBodyparts.length) _flSelectBp(_flBodyparts[0]);
    }

    function _flSelectBp(bp) {
      _flSelectedBp = bp;
      flCanvas.style.cursor = "crosshair";
      flBodypartList.querySelectorAll(".fl-bp-chip").forEach(c => {
        c.classList.toggle("active", c.dataset.bp === bp);
      });
      // Repaint immediately so the white selection ring appears without
      // waiting for the user to nudge the cursor. _flDraw is sync-aware:
      // in sync mode it redraws the focused tile (which is the one whose
      // ring we want to update); in single-canvas it redraws flCanvas.
      _flDraw();
    }

    // ── Silent auto-save (fire-and-forget) ──────────────────────
    function _flAutoSave() {
      if (!_flVideoStem) return;
      fetch(`/dlc/project/labels/${encodeURIComponent(_flVideoStem)}`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ labels: _flLabels }),
      }).catch(() => {});  // silent — user can always use Save button
    }

    // ── Frame display ────────────────────────────────────────────
    function _flShowFrame(idx) {
      if (_fl3dSyncOn) {
        if (!_fl3dFrameNumbers.length) return;
        if (_flDirty) { _flDirty = false; _flAutoSave(); }
        idx = Math.max(0, Math.min(idx, _fl3dFrameNumbers.length - 1));
        _fl3dFrameNumIdx = idx;
        const frameNum = _fl3dFrameNumbers[idx];
        flFrameInfo.textContent = `Frame ${idx + 1} / ${_fl3dFrameNumbers.length}`;
        // Update primary fname display from the focused tile after render
        _fl3dSyncRenderRow(frameNum);
        const focusedFname = _fl3dActiveFname();
        flFrameName.textContent = focusedFname || `(no cam${_fl3dFocusedCam} @ ${String(frameNum).padStart(5, "0")})`;
        _flUpdateBpChipStatus();
        _flUpdateLabelCount();
        _flTapUpdateFrameStatus();
        return;
      }
      if (!_flFrames.length) return;
      // Auto-save unsaved changes before switching frames
      if (_flDirty) { _flDirty = false; _flAutoSave(); }
      idx = Math.max(0, Math.min(idx, _flFrames.length - 1));
      _flFrameIdx = idx;
      const fname = _flFrames[idx];
      flFrameInfo.textContent = `Frame ${idx + 1} / ${_flFrames.length}`;
      flFrameName.textContent = fname;

      // Mirror current frame onto the primary tile attributes for tests/assertions
      const _flCurrentTile = document.querySelector('.fl3d-tile');
      if (_flCurrentTile) {
        const m = FL3D_FRAME_RE.exec(fname);
        if (m) {
          _flCurrentTile.dataset.cam   = m[1];
          _flCurrentTile.dataset.fname = fname;
          flCanvas.dataset.cam         = m[1];
          flCanvas.dataset.fname       = fname;
          const lbl = document.getElementById("fl3d-tile-label-primary");
          if (lbl) lbl.textContent = `cam${m[1]}`;
        } else {
          // Non-conforming filename (single-cam project) — clear cam-specific attrs
          _flCurrentTile.dataset.fname = fname;
          flCanvas.dataset.fname = fname;
        }
      }

      _flUpdateBpChipStatus();
      _flUpdateLabelCount();
      _flTapUpdateFrameStatus();

      // Load frame image
      _flHoverBp   = null;
      _flImgLoaded = false;
      flCanvasLoading.classList.remove("hidden");
      const img   = new Image();
      img.onload  = () => {
        _flImg       = img;
        _flImgLoaded = true;
        flCanvasLoading.classList.add("hidden");
        _flFitCanvas();
        _flDraw();
      };
      img.onerror = () => {
        flCanvasLoading.textContent = "Failed to load frame.";
        flCanvasLoading.classList.remove("hidden");
      };
      img.src = `/dlc/project/frame-image/${encodeURIComponent(_flVideoStem)}/${encodeURIComponent(fname)}`;
    }

    // ── Sync-frame helpers ────────────────────────────────────────
    function _fl3dSyncRenderRow(currentFrameNum) {
      const row = document.getElementById("fl3d-canvas-row");
      if (!row) return;

      // Stash per-cam sibling weights so user-set sizing survives frame nav.
      // (Primary tile is preserved across renders so its weight is naturally retained.)
      const _siblingWeights = new Map();
      row.querySelectorAll(".fl3d-tile.fl3d-tile-sibling").forEach(el => {
        _siblingWeights.set(+el.dataset.cam, parseInt(el.dataset.weight || "100", 10));
      });

      // Remove any sibling tiles (keep only the primary tile, which always exists)
      Array.from(row.querySelectorAll(".fl3d-tile.fl3d-tile-sibling"))
        .forEach(el => el.remove());

      // Lookup tiles for this frame number
      const entries = _fl3dPairMap.get(currentFrameNum) || [];
      const byCam   = new Map(entries.map(e => [e.cam, e]));

      // Update primary tile (cam = primaryCam)
      const primaryTile = row.querySelector(".fl3d-tile:not(.fl3d-tile-sibling)");
      _fl3dRenderTile(primaryTile, _fl3dPrimaryCam, byCam.get(_fl3dPrimaryCam) || null, currentFrameNum);

      // Append sibling tiles for every other cam in camSet
      for (const cam of _fl3dCamSet) {
        if (cam === _fl3dPrimaryCam) continue;
        const tile = document.createElement("div");
        tile.className = "fl3d-tile fl3d-tile-sibling";
        tile.dataset.cam = String(cam);
        const _w = _siblingWeights.has(cam) ? _siblingWeights.get(cam) : 100;
        tile.dataset.weight = String(_w);
        tile.style.flexGrow = String(_w);
        tile.innerHTML = `
          <div class="fl3d-tile-header">
            <span class="fl3d-tile-label">cam${cam}</span>
            <input type="range" class="fl3d-tile-size" min="50" max="300" step="25" value="${_w}">
            <span class="fl3d-tile-size-val">${_w}%</span>
          </div>
          <canvas class="fl3d-tile-canvas" data-cam="${cam}"></canvas>
          <div class="fl3d-tile-empty hidden"></div>
        `;
        row.appendChild(tile);
        _fl3dRenderTile(tile, cam, byCam.get(cam) || null, currentFrameNum);
      }

      _fl3dApplyFocusClass();
    }

    function _fl3dRenderTile(tile, cam, entry, frameNum) {
      const canvas = tile.querySelector(".fl3d-tile-canvas");
      const empty  = tile.querySelector(".fl3d-tile-empty");
      const label  = tile.querySelector(".fl3d-tile-label");
      if (label) label.textContent = `cam${cam}`;

      if (!entry) {
        canvas.style.display = "none";
        empty.classList.remove("hidden");
        empty.textContent = `No frame extracted for cam${cam} @ ${String(frameNum).padStart(5, "0")}`;
        tile.dataset.fname = "";
        canvas.dataset.fname = "";
        canvas.dataset.cam   = String(cam);
        return;
      }

      canvas.style.display = "";
      empty.classList.add("hidden");
      tile.dataset.fname   = entry.fname;
      canvas.dataset.fname = entry.fname;
      canvas.dataset.cam   = String(cam);

      // Load image and draw into this tile's canvas
      const img = new Image();
      img.onload = () => {
        canvas.width  = img.naturalWidth;   // intrinsic; CSS scales to width:100%
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0);
        _fl3dDrawTileMarkers(tile, entry.fname);
      };
      img.src = `/dlc/project/frame-image/${encodeURIComponent(_flVideoStem)}/${encodeURIComponent(entry.fname)}`;

      // Stash the image on the tile for re-draw on marker-size / show-names changes
      tile._fl3dImg = img;

      // ── Sibling-tile input listeners ──────────────────────────────
      // Only attach to sibling tiles; the primary tile's listeners are attached
      // once at startup above to prevent accumulation across re-renders.
      if (tile.classList.contains("fl3d-tile-sibling")) {
        // Per-tile size slider — sibling header was just (re)built, wire its input listener
        _fl3dWireTileSizeSlider(tile);
        // Hover tracking
        tile.addEventListener("mouseenter", () => { _fl3dHoveredCam = +tile.dataset.cam; });
        tile.addEventListener("mouseleave", () => {
          if (_fl3dHoveredCam === +tile.dataset.cam) _fl3dHoveredCam = null;
        });

        // Click → hit-test (select existing marker) or place marker on focused tile
        canvas.addEventListener("click", (e) => {
          if (!tile.dataset.fname) return;  // empty placeholder, no-op
          if (+tile.dataset.cam !== _fl3dFocusedCam) return;  // only focused tile accepts input
          const fname = tile.dataset.fname;
          const { x: cx, y: cy, scale } = _fl3dCanvasClickToImage(canvas, e);
          // Select-on-marker mirrors primary canvas behavior: hit-test first,
          // and if a marker is under the cursor, select that bp instead of
          // overwriting it.
          const hit = _flHitTest(cx, cy, fname, scale);
          if (hit) {
            _flSelectBp(hit);
            // Sync mode: restore crosshair on this tile's canvas after select
            // (mousemove will refine to "pointer" on next motion).
            canvas.style.cursor = "crosshair";
            return;
          }
          if (!_flSelectedBp) return;
          if (!_flLabels[fname]) _flLabels[fname] = {};
          _flLabels[fname][_flSelectedBp] = [cx, cy];
          _fl3dDirtyFrames.add(fname);
          _flDirty = true;
          _fl3dDrawTileMarkers(tile, fname);
          _flUpdateBpChipStatus();
          _flUpdateLabelCount();
          _flAutoAdvanceBp();
        });

        // Mousemove → cursor state + hover-bp tracking on sibling canvas.
        // Setting _flHoverBp + redrawing this tile pops the marker's name as
        // a tooltip (mirrors main webapp's flCanvas hover behavior).
        canvas.addEventListener("mousemove", (e) => {
          if (!tile.dataset.fname) return;
          const { x: cx, y: cy, scale } = _fl3dCanvasClickToImage(canvas, e);
          const hit = _flHitTest(cx, cy, tile.dataset.fname, scale);
          if (hit !== _flHoverBp) {
            _flHoverBp = hit;
            _fl3dDrawTileMarkers(tile, tile.dataset.fname);
          }
          canvas.style.cursor = hit
            ? "pointer"
            : (_flSelectedBp && +tile.dataset.cam === _fl3dFocusedCam ? "crosshair" : "default");
        });
        canvas.addEventListener("mouseleave", () => {
          canvas.style.cursor = "";  // fall back to .fl3d-tile { cursor: pointer }
          if (_flHoverBp) {
            _flHoverBp = null;
            if (tile.dataset.fname) _fl3dDrawTileMarkers(tile, tile.dataset.fname);
          }
        });

        // Right-click → remove marker on focused tile
        canvas.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          if (!tile.dataset.fname) return;
          if (+tile.dataset.cam !== _fl3dFocusedCam) return;
          if (!_flSelectedBp) return;
          const fname = tile.dataset.fname;
          if (!_flLabels[fname]) return;
          _flLabels[fname][_flSelectedBp] = null;
          _fl3dDirtyFrames.add(fname);
          _flDirty = true;
          _fl3dDrawTileMarkers(tile, fname);
          _flUpdateBpChipStatus();
          _flUpdateLabelCount();
        });
      }
    }

    function _fl3dDrawTileMarkers(tile, fname) {
      const canvas = tile.querySelector(".fl3d-tile-canvas");
      const ctx    = canvas.getContext("2d");
      // Re-paint the tile's own image first so toggling display controls
      // (show-names, marker-size) doesn't accumulate stale labels on top of
      // the canvas, and so the primary tile isn't overwritten by a stale
      // global _flImg that _flDraw might have used. Each tile owns its image
      // via tile._fl3dImg (set in _fl3dRenderTile).
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (tile._fl3dImg && tile._fl3dImg.complete && tile._fl3dImg.naturalWidth > 0) {
        ctx.drawImage(tile._fl3dImg, 0, 0, canvas.width, canvas.height);
      }
      const labels = _flLabels[fname] || {};
      const r      = _flMarkerRadius;
      const sx     = 1, sy = 1;  // canvas is at native pixel size; CSS handles display scaling
      _flBodyparts.forEach((bp, i) => {
        const pt = labels[bp];
        if (!pt) return;
        if (_flHidden[fname] && _flHidden[fname][bp]) return;
        const cx = pt[0] * sx, cy = pt[1] * sy;
        const color = _flColor(i);
        if (bp === _flSelectedBp && tile.classList.contains("focused")) {
          ctx.beginPath(); ctx.arc(cx, cy, r + 3.5, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 2; ctx.stroke();
        }
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fillStyle = color; ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 1.2; ctx.stroke();
        // Show name if global "Show names" is on, OR if cursor is hovering
        // this specific marker (matches main webapp tooltip behavior).
        if (_flShowNames || bp === _flHoverBp) {
          ctx.font = "bold 11px 'JetBrains Mono', monospace";
          ctx.fillStyle = "rgba(12,13,16,.65)";
          const tw = ctx.measureText(bp).width;
          ctx.fillRect(cx + r + 2, cy - 7, tw + 6, 14);
          ctx.fillStyle = color;
          ctx.fillText(bp, cx + r + 5, cy + 4);
        }
      });
    }

    function _fl3dApplyFocusClass() {
      document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
        t.classList.toggle("focused", +t.dataset.cam === _fl3dFocusedCam);
      });
    }

    document.getElementById("fl3d-canvas-row").addEventListener("click", (e) => {
      const tile = e.target.closest(".fl3d-tile");
      if (!tile) return;
      const cam = +tile.dataset.cam;
      if (Number.isNaN(cam)) return;
      if (cam === _fl3dFocusedCam) return;  // no-op if already focused
      _fl3dFocusedCam = cam;
      _fl3dApplyFocusClass();
      // Re-draw all tiles so the selection ring on the focused tile updates
      document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
        if (t._fl3dImg && t.dataset.fname) _fl3dDrawTileMarkers(t, t.dataset.fname);
      });
      // Also refresh chip status / label count from focused tile's frame
      _flUpdateBpChipStatus();
      _flUpdateLabelCount();
    });

    function _fl3dActiveFname() {
      if (!_fl3dSyncOn) return _flFrames[_flFrameIdx];
      const tile = document.querySelector(`#fl3d-canvas-row .fl3d-tile.focused`);
      return tile ? (tile.dataset.fname || "") : _flFrames[_flFrameIdx];
    }

    function _flFitCanvas() {
      if (_fl3dSyncOn) {
        _fl3dFitRow();
        return;
      }
      const wrap = flCanvas.parentElement;
      const cs   = getComputedStyle(flCard);
      const padL = parseFloat(cs.paddingLeft)  || 0;
      const padR = parseFloat(cs.paddingRight) || 0;

      // Base width = card's inner content width (canvas at 100% zoom)
      const baseW = flCard.clientWidth - padL - padR;

      // Maximum width: fill the viewport minus a small margin on each side.
      // The card is centred, so the canvas expands symmetrically beyond its border.
      const maxW    = Math.max(baseW, window.innerWidth - 32);
      const targetW = Math.min(Math.round(baseW * (_flZoom / 100)), Math.floor(maxW));

      flCanvas.width  = targetW;
      flCanvas.height = Math.round(_flImg.naturalHeight * (targetW / _flImg.naturalWidth));

      // Break out of card padding symmetrically — card has no overflow:hidden so
      // the wrapper renders beyond the card border without clipping.
      const extra = targetW - baseW;
      if (extra > 0) {
        wrap.style.width      = targetW + "px";
        wrap.style.marginLeft = `-${extra / 2}px`;
      } else {
        wrap.style.width      = "";
        wrap.style.marginLeft = "";
      }
    }

    function _fl3dFitRow() {
      const row = document.getElementById("fl3d-canvas-row");
      if (!row) return;
      const cs   = getComputedStyle(flCard);
      const padL = parseFloat(cs.paddingLeft)  || 0;
      const padR = parseFloat(cs.paddingRight) || 0;
      const baseW = flCard.clientWidth - padL - padR;
      const maxW  = Math.max(baseW, window.innerWidth - 32);
      const targetRowW = Math.min(Math.round(baseW * (_flZoom / 100)), Math.floor(maxW));
      row.style.width = targetRowW + "px";
      const extra = targetRowW - baseW;
      row.style.marginLeft = extra > 0 ? `-${extra / 2}px` : "";
    }

    function _fl3dWireTileSizeSlider(tile) {
      const slider = tile.querySelector(".fl3d-tile-size");
      const val    = tile.querySelector(".fl3d-tile-size-val");
      if (!slider || slider.dataset.wired === "1") return;
      slider.dataset.wired = "1";
      slider.addEventListener("input", () => {
        const w = parseInt(slider.value, 10);
        tile.dataset.weight = String(w);
        tile.style.flexGrow = String(w);
        val.textContent = w + "%";
        if (tile.dataset.fname) _fl3dDrawTileMarkers(tile, tile.dataset.fname);
      });
    }

    function _fl3dResetTileWeight(tile) {
      const slider = tile.querySelector(".fl3d-tile-size");
      const val    = tile.querySelector(".fl3d-tile-size-val");
      tile.dataset.weight = "100";
      tile.style.flexGrow = "100";
      if (slider) slider.value = "100";
      if (val) val.textContent = "100%";
    }

    // Re-fit whenever the card width changes (window resize, layout shifts)
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(() => {
        if (_flImgLoaded) { _flFitCanvas(); _flDraw(); }
      }).observe(flCard);
    }

    function _flDraw() {
      // In sync mode, the global _flImg is stale (sync nav updates each tile's
      // _fl3dImg per-tile, not the global) and the focused tile may not be the
      // primary one. Painting _flImg on flCanvas here corrupts the primary tile
      // (wrong frame + sibling's markers when sibling is focused). Redraw the
      // focused tile from its own image instead — that route uses tile._fl3dImg.
      if (_fl3dSyncOn) {
        const focused = document.querySelector("#fl3d-canvas-row .fl3d-tile.focused");
        if (focused && focused.dataset.fname) {
          _fl3dDrawTileMarkers(focused, focused.dataset.fname);
        }
        return;
      }
      if (!_flImgLoaded) return;
      flCtx.clearRect(0, 0, flCanvas.width, flCanvas.height);
      flCtx.drawImage(_flImg, 0, 0, flCanvas.width, flCanvas.height);

      const fname       = _fl3dActiveFname();
      const frameLabels = _flLabels[fname] || {};
      const scaleX      = flCanvas.width  / _flImg.naturalWidth;
      const scaleY      = flCanvas.height / _flImg.naturalHeight;
      const r           = _flMarkerRadius;

      _flBodyparts.forEach((bp, i) => {
        const pt = frameLabels[bp];
        if (!pt) return;
        if (_flHidden[fname] && _flHidden[fname][bp]) return;
        const cx    = pt[0] * scaleX;
        const cy    = pt[1] * scaleY;
        const color = _flColor(i);

        // Selection ring for the active bodypart
        if (bp === _flSelectedBp) {
          flCtx.beginPath();
          flCtx.arc(cx, cy, r + 3.5, 0, Math.PI * 2);
          flCtx.strokeStyle = "rgba(255,255,255,0.85)";
          flCtx.lineWidth   = 2;
          flCtx.stroke();
        }

        // Filled circle with a thin dark outline for contrast
        flCtx.beginPath();
        flCtx.arc(cx, cy, r, 0, Math.PI * 2);
        flCtx.fillStyle = color;
        flCtx.fill();
        flCtx.strokeStyle = "rgba(0,0,0,0.55)";
        flCtx.lineWidth   = 1.2;
        flCtx.stroke();

        if (_flShowNames || bp === _flHoverBp) {
          flCtx.font = "bold 11px 'JetBrains Mono', monospace";
          const tw = flCtx.measureText(bp).width;
          const tx = cx + r + 4;
          const ty = cy + 4;
          flCtx.fillStyle = "rgba(12,13,16,.65)";
          flCtx.fillRect(tx - 2, ty - 11, tw + 6, 14);
          flCtx.fillStyle = color;
          flCtx.fillText(bp, tx + 1, ty);
        }
      });
    }

    // ── Canvas interaction ───────────────────────────────────────
    // Compute the click→drawing-buffer scale for any canvas. In sync mode the
    // buffer is set to image natural dimensions while CSS displays at parent
    // width, so buffer != display. Rect-based scale handles both modes (sync
    // OFF zoom>100% had the same issue with the old _flImg-based math).
    function _fl3dCanvasClickToImage(canvas, e) {
      const rect = canvas.getBoundingClientRect();
      const sx = rect.width  > 0 ? canvas.width  / rect.width  : 1;
      const sy = rect.height > 0 ? canvas.height / rect.height : 1;
      return {
        x: (e.clientX - rect.left) * sx,
        y: (e.clientY - rect.top)  * sy,
        scale: Math.max(sx, sy),
      };
    }
    function _fl3dPrimaryClickToImage(e) {
      return _fl3dCanvasClickToImage(flCanvas, e);
    }

    // _flHitTest expects image-space coords (cx, cy in canvas drawing-buffer
    // px). hitScale lets the caller widen the hit radius proportionally to the
    // CSS→buffer scale so the user's click tolerance stays roughly constant in
    // CSS pixels regardless of zoom or sync-mode display shrinkage.
    function _flHitTest(cx, cy, fname, hitScale) {
      const frameLabels = _flLabels[fname] || {};
      const hitR = (_flMarkerRadius + 6) * (hitScale || 1);
      let hit = null;
      _flBodyparts.forEach(bp => {
        const pt = frameLabels[bp];
        if (!pt) return;
        if (_flHidden[fname] && _flHidden[fname][bp]) return;
        const dx = pt[0] - cx;
        const dy = pt[1] - cy;
        if (Math.sqrt(dx * dx + dy * dy) <= hitR) hit = bp;
      });
      return hit;
    }

    flCanvas.addEventListener("click", e => {
      if (!_flImgLoaded || !_flVideoStem) return;
      const fname = _fl3dActiveFname();
      const { x: cx, y: cy, scale } = _fl3dPrimaryClickToImage(e);

      // Click near an existing marker → select it
      const hit = _flHitTest(cx, cy, fname, scale);
      if (hit) {
        _flSelectBp(hit);
        return;
      }

      // Click on empty space → place point for selected bp (image-space coords)
      if (!_flSelectedBp) return;
      if (!_flLabels[fname]) _flLabels[fname] = {};
      _flLabels[fname][_flSelectedBp] = [cx, cy];
      _fl3dDirtyFrames.add(fname);
      _flDirty = true;
      _flDraw();
      _flUpdateBpChipStatus();
      _flUpdateLabelCount();
      _flAutoAdvanceBp();
    });

    // Right-click → remove current body-part point
    flCanvas.addEventListener("contextmenu", e => {
      e.preventDefault();
      if (!_flSelectedBp || !_flVideoStem) return;
      _flRemoveBpLabel(_flSelectedBp);
    });

    flCanvas.addEventListener("mousemove", e => {
      if (!_flImgLoaded) return;
      const fname = _fl3dActiveFname();
      const { x: cx, y: cy, scale } = _fl3dPrimaryClickToImage(e);
      const found = _flHitTest(cx, cy, fname, scale);
      if (found !== _flHoverBp) {
        _flHoverBp = found;
        _flDraw();
      }
      flCanvas.style.cursor = found ? "pointer" : (_flSelectedBp ? "crosshair" : "default");
    });

    flCanvas.addEventListener("mouseenter", () => { _flCursorInCanvas = true; });
    flCanvas.addEventListener("mouseleave", () => {
      _flCursorInCanvas = false;
      if (_flHoverBp) { _flHoverBp = null; _flDraw(); }
      flCanvas.style.cursor = _flSelectedBp ? "crosshair" : "default";
    });

    // ── Primary tile hover tracking (one-shot; attached once at startup) ──
    // Sibling tiles get their own hover listeners inside _fl3dRenderTile.
    const _fl3dPrimaryTileEl = document.querySelector("#fl3d-canvas-row .fl3d-tile");
    if (_fl3dPrimaryTileEl) {
      _fl3dPrimaryTileEl.addEventListener("mouseenter", () => {
        _fl3dHoveredCam = +_fl3dPrimaryTileEl.dataset.cam || 0;
      });
      _fl3dPrimaryTileEl.addEventListener("mouseleave", () => {
        if (_fl3dHoveredCam === (+_fl3dPrimaryTileEl.dataset.cam || 0)) _fl3dHoveredCam = null;
      });
    }

    function _flRemoveBpLabel(bp) {
      const fname = _fl3dActiveFname();
      if (!fname || !_flLabels[fname]) return;
      _flLabels[fname][bp] = null;
      // Also clear hidden state when marker is deleted
      if (_flHidden[fname]) delete _flHidden[fname][bp];
      _fl3dDirtyFrames.add(fname);
      _flDirty = true;
      _flDraw();
      _flUpdateBpChipStatus();
      _flUpdateLabelCount();
    }

    function _flToggleVisibility(bp) {
      const fname = _fl3dActiveFname();
      if (!fname) return;
      if (!_flHidden[fname]) _flHidden[fname] = {};
      _flHidden[fname][bp] = !_flHidden[fname][bp];
      _flDraw();
      _flUpdateBpChipStatus();
    }

    // Clear all body-part markers on the currently displayed frame
    function _flClearFrame() {
      const fname = _fl3dActiveFname();
      if (!fname) return;
      delete _flLabels[fname];
      delete _flHidden[fname];
      _fl3dDirtyFrames.add(fname);
      _flDirty = true;
      if (_fl3dSyncOn) {
        const tile = document.querySelector(`#fl3d-canvas-row .fl3d-tile.focused`);
        if (tile) _fl3dDrawTileMarkers(tile, fname);
      } else {
        _flDraw();
      }
      _flUpdateBpChipStatus();
      _flUpdateLabelCount();
    }

    // Double-click on Clear Frame button erases all markers on current frame
    document.getElementById("fl3d-btn-clear-frame").addEventListener("dblclick", e => {
      e.preventDefault();
      if (!_flVideoStem) return;
      _flClearFrame();
    });

    document.getElementById("fl3d-btn-delete-frame").addEventListener("dblclick", async e => {
      e.preventDefault();
      const fname = _fl3dActiveFname();
      if (!_flVideoStem || !fname) return;

      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const res = await fetch("/dlc/project/frame", {
          method:  "DELETE",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ video_stem: _flVideoStem, frame_name: fname }),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          flSaveStatus.textContent = `Delete failed: ${d.error || res.status}`;
          flSaveStatus.className   = "fl-save-status err";
          return;
        }
        // Remove from in-memory state
        delete _flLabels[fname];
        _flFrames.splice(_flFrameIdx, 1);
        _flUpdateLabelCount();

        if (_flFrames.length === 0) {
          // No frames left — reset canvas
          _flFrameIdx = 0;
          flFrameInfo.textContent = "Frame 0 / 0";
          flFrameName.textContent = "";
          const ctx = flCanvas.getContext("2d");
          ctx.clearRect(0, 0, flCanvas.width, flCanvas.height);
        } else {
          _flShowFrame(Math.min(_flFrameIdx, _flFrames.length - 1));
        }
        flSaveStatus.textContent = `Deleted ${fname}`;
        flSaveStatus.className   = "fl-save-status";
      } catch (err) {
        flSaveStatus.textContent = `Delete error: ${err.message}`;
        flSaveStatus.className   = "fl-save-status err";
      } finally {
        btn.disabled = false;
      }
    });

    // Auto-advance to the next unlabeled body part (napari behavior)
    function _flAutoAdvanceBp() {
      const fname       = _fl3dActiveFname();
      const frameLabels = _flLabels[fname] || {};
      const cur         = _flBodyparts.indexOf(_flSelectedBp);
      for (let i = 1; i <= _flBodyparts.length; i++) {
        const next = _flBodyparts[(cur + i) % _flBodyparts.length];
        if (!frameLabels[next]) { _flSelectBp(next); return; }
      }
      // All body parts labeled on this frame → move to next frame.
      // Use the right axis index for sync mode — _flFrameIdx is the
      // single-canvas axis and stays at its sync-on-time value while sync nav
      // advances _fl3dFrameNumIdx, so falling through here with the wrong
      // axis sends the user back to ~frame 1 of the frame-number list.
      const curIdx = _fl3dSyncOn ? _fl3dFrameNumIdx     : _flFrameIdx;
      const total  = _fl3dSyncOn ? _fl3dFrameNumbers.length : _flFrames.length;
      if (curIdx < total - 1) _flShowFrame(curIdx + 1);
    }

    // ── Chip status updates ──────────────────────────────────────
    function _flUpdateBpChipStatus() {
      const fname       = _fl3dActiveFname();
      const frameLabels = _flLabels[fname] || {};
      flBodypartList.querySelectorAll(".fl-bp-chip").forEach(c => {
        const bp = c.dataset.bp;
        const pt = frameLabels[bp];
        const isHidden = !!(_flHidden[fname] && _flHidden[fname][bp]);
        c.classList.toggle("labeled",    !!(pt && pt[0] !== null));
        c.classList.toggle("vis-hidden", !!(pt && pt[0] !== null) && isHidden);
      });
    }

    function _flUpdateLabelCount() {
      const labeled = Object.values(_flLabels).filter(fl =>
        _flBodyparts.some(bp => fl && fl[bp] && fl[bp][0] !== null)
      ).length;
      flLabelCount.textContent = `${labeled} / ${_flFrames.length} frame${_flFrames.length !== 1 ? "s" : ""} labeled`;
    }

    // ── Navigation ───────────────────────────────────────────────
    flBtnPrev.addEventListener("click", () => _flShowFrame((_fl3dSyncOn ? _fl3dFrameNumIdx : _flFrameIdx) - 1));
    flBtnNext.addEventListener("click", () => _flShowFrame((_fl3dSyncOn ? _fl3dFrameNumIdx : _flFrameIdx) + 1));

    document.addEventListener("keydown", e => {
      if (flCard.classList.contains("hidden")) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;

      // WASD nudge: move the selected marker when cursor is inside the canvas
      // and the current frame already has a point placed for the active body part.
      // In sync mode, sibling tiles have their own canvases (so _flCursorInCanvas
      // — bound to the primary canvas — wouldn't fire); use the per-tile hover
      // tracker instead, gated to the focused tile.
      const _wasdKeys = ["a", "d", "w", "s"];
      const _wasdGate = _fl3dSyncOn
        ? (_fl3dHoveredCam === _fl3dFocusedCam && _fl3dHoveredCam !== null)
        : _flCursorInCanvas;
      if (_wasdKeys.includes(e.key) && _wasdGate && _flSelectedBp && _flVideoStem) {
        const fname = _fl3dActiveFname();
        const pt    = fname && _flLabels[fname] && _flLabels[fname][_flSelectedBp];
        if (pt && pt[0] !== null) {
          e.preventDefault();
          const step = e.shiftKey ? 10 : 1;
          let [x, y] = pt;
          if (e.key === "a") x -= step;
          if (e.key === "d") x += step;
          if (e.key === "w") y -= step;
          if (e.key === "s") y += step;
          // Clamp to the focused tile's image dimensions (in sync mode the
          // sibling's image may differ from the global _flImg).
          let _clampImg = _flImg;
          if (_fl3dSyncOn) {
            const focused = document.querySelector("#fl3d-canvas-row .fl3d-tile.focused");
            if (focused && focused._fl3dImg && focused._fl3dImg.naturalWidth) {
              _clampImg = focused._fl3dImg;
            }
          }
          x = Math.max(0, Math.min(x, _clampImg.naturalWidth  - 1));
          y = Math.max(0, Math.min(y, _clampImg.naturalHeight - 1));
          _flLabels[fname][_flSelectedBp] = [x, y];
          _fl3dDirtyFrames.add(fname);
          _flDirty = true;
          _flDraw();
          return;
        }
      }

      // Tab / Shift+Tab — cycle through body parts
      if (e.key === "Tab" && _flVideoStem) {
        e.preventDefault();
        const cur  = _flBodyparts.indexOf(_flSelectedBp);
        const next = e.shiftKey
          ? (_flBodyparts.length + cur - 1) % _flBodyparts.length
          : (cur + 1) % _flBodyparts.length;
        _flSelectBp(_flBodyparts[next]);
        return;
      }

      // Spacebar — toggle visibility of selected marker
      if (e.key === " " && _flSelectedBp && _flVideoStem) {
        e.preventDefault();
        _flToggleVisibility(_flSelectedBp);
        return;
      }

      // Backspace — delete selected marker (no cursor-in-canvas requirement)
      if (e.key === "Backspace" && _flSelectedBp && _flVideoStem) {
        e.preventDefault();
        _flRemoveBpLabel(_flSelectedBp);
        return;
      }

      // Frame navigation (arrow keys)
      if (e.key === "ArrowLeft")  { e.preventDefault(); _flShowFrame((_fl3dSyncOn ? _fl3dFrameNumIdx : _flFrameIdx) - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); _flShowFrame((_fl3dSyncOn ? _fl3dFrameNumIdx : _flFrameIdx) + 1); }

      // Delete (with cursor over canvas) — also deletes selected marker
      if (e.key === "Delete" && _flCursorInCanvas && _flSelectedBp && _flVideoStem) {
        e.preventDefault();
        _flRemoveBpLabel(_flSelectedBp);
      }
    });

    // ── Save ─────────────────────────────────────────────────────
    flBtnSave.addEventListener("click", async () => {
      if (!_flVideoStem) return;
      flBtnSave.disabled      = true;
      flSaveStatus.textContent = "Saving…";
      flSaveStatus.className   = "fl-save-status";
      try {
        const res  = await fetch(`/dlc/project/labels/${encodeURIComponent(_flVideoStem)}`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ labels: _flLabels }),
        });
        const data = await res.json();
        if (res.ok) {
          _flDirty = false;
          const h5note = data.h5_warning ? ` (H5 warning: ${data.h5_warning})` : (data.h5_path ? " + H5" : "");
          flSaveStatus.textContent = `Saved ✓${h5note}`;
          flSaveStatus.className   = "fl-save-status ok";
        } else {
          flSaveStatus.textContent = data.error || "Error saving";
          flSaveStatus.className   = "fl-save-status err";
        }
      } catch (err) {
        flSaveStatus.textContent = `Network error: ${err.message}`;
        flSaveStatus.className   = "fl-save-status err";
      }
      flBtnSave.disabled = false;
      setTimeout(() => {
        flSaveStatus.textContent = "";
        flSaveStatus.className   = "fl-save-status";
      }, 4000);
    });

    // ── Save all to H5 ───────────────────────────────────────────
    flBtnSaveH5.addEventListener("click", async () => {
      if (!_flVideoStem) return;

      // First flush current frame's CSV
      flBtnSaveH5.disabled     = true;
      flSaveStatus.textContent = "Saving CSV…";
      flSaveStatus.className   = "fl-save-status";
      try {
        const csvRes = await fetch(`/dlc/project/labels/${encodeURIComponent(_flVideoStem)}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ labels: _flLabels }),
        });
        if (!csvRes.ok) {
          const d = await csvRes.json();
          flSaveStatus.textContent = d.error || "CSV save failed";
          flSaveStatus.className   = "fl-save-status err";
          flBtnSaveH5.disabled = false;
          return;
        }
        _flDirty = false;
      } catch (err) {
        flSaveStatus.textContent = `Network error: ${err.message}`;
        flSaveStatus.className   = "fl-save-status err";
        flBtnSaveH5.disabled = false;
        return;
      }

      // Dispatch Celery task for the full convertcsv2h5
      flSaveStatus.textContent = "Converting to H5…";
      try {
        const res  = await fetch("/dlc/project/labels/convert-to-h5", { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          flSaveStatus.textContent = data.error || "Failed to dispatch H5 conversion";
          flSaveStatus.className   = "fl-save-status err";
          flBtnSaveH5.disabled = false;
          return;
        }

        // Poll until done
        const taskId = data.task_id;
        const poll = setInterval(async () => {
          try {
            const tr   = await fetch(`/status/${taskId}`);
            const td   = await tr.json();
            if (td.state === "PENDING" || td.state === "STARTED") {
              flSaveStatus.textContent = td.stage || (td.state === "PENDING" ? "Queued — waiting for worker…" : "Converting to H5…");
            } else if (td.state === "SUCCESS") {
              clearInterval(poll);
              const r   = td.result || {};
              const cnt = (r.converted || []).length;
              const sk  = (r.skipped  || []).length;
              const note = sk > 0 ? `, ${sk} skipped` : "";
              flSaveStatus.textContent = `Saved ✓ CSV + H5 (${cnt} folder${cnt !== 1 ? "s" : ""}${note})`;
              flSaveStatus.className   = "fl-save-status ok";
              flBtnSaveH5.disabled = false;
              setTimeout(() => { flSaveStatus.textContent = ""; flSaveStatus.className = "fl-save-status"; }, 6000);
            } else if (td.state === "FAILURE" || td.state === "REVOKED") {
              clearInterval(poll);
              const errFull = td.error || td.state || "";
              // Show the last non-empty line (most specific part of the traceback)
              const lines   = errFull.split("\n").map(l => l.trim()).filter(Boolean);
              const errLine = lines[lines.length - 1] || errFull;
              flSaveStatus.textContent = "H5 failed: " + errLine;
              flSaveStatus.title       = errFull;   // full traceback on hover
              flSaveStatus.className   = "fl-save-status err";
              console.error("H5 conversion traceback:\n", errFull);
              flBtnSaveH5.disabled = false;
            }
          } catch (_) {}
        }, 1500);
      } catch (err) {
        flSaveStatus.textContent = `Network error: ${err.message}`;
        flSaveStatus.className   = "fl-save-status err";
        flBtnSaveH5.disabled = false;
      }
    });

    // ── Redraw on resize ─────────────────────────────────────────
    window.addEventListener("resize", () => {
      if (!flCard.classList.contains("hidden") && _flImgLoaded) {
        _flFitCanvas();
        _flDraw();
      }
    });

    window.__fl3d = new Proxy({}, {
      get(_, prop) {
        const map = {
          syncOn:        _fl3dSyncOn,
          focusedCam:    _fl3dFocusedCam,
          primaryCam:    _fl3dPrimaryCam,
          hoveredCam:    _fl3dHoveredCam,
          camSet:        _fl3dCamSet,
          pairMapSize:   _fl3dPairMap ? _fl3dPairMap.size : 0,
          frameNumberIdx:_fl3dFrameNumIdx,
          frameNumbers:  _fl3dFrameNumbers,
          selectedBp:    _flSelectedBp,
          markerRadius:  _flMarkerRadius,
          showNames:     _flShowNames,
          zoom:          _flZoom,
          labels:        _flLabels,
          dirtyFrames:   Array.from(_fl3dDirtyFrames || []),
        };
        return map[prop];
      },
    });

})(); // end initFl3d
