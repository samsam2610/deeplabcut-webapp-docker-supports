// FrameExtractor — feature module for VideoViewer.
// Saves the current frame (and batches of frames) into DLC labeled-data via an injected
// save-frame endpoint, with optional sibling-cam extraction. Reads frame count / current
// frame / sibling video from the viewer (no video-info re-fetch). All endpoints/elements
// injected; follows the feature-teardown pattern.
//
// Usage:
//   viewer.use(frameExtractor({
//     endpoints: { saveFrame: (payload) => fetchPromise },
//     els: { extractBtn?, batchBtn?, batchStopBtn?, batchCount?, batchStep?,
//            extractSibling?, statusDisplay? },
//     onSaved?: () => void,   // called after a save/batch completes (e.g. refresh labeled list)
//   }));

import {
  parseBatchCount, parseBatchStep, planBatch, buildSaveFramePayload,
} from "../internal/frame_extract.mjs";

export function frameExtractor(config = {}) {
  const els = config.els || {};
  const endpoints = config.endpoints || {};

  let viewer = null;
  let stopRequested = false;
  let running = false;

  const setStatus = (msg) => { if (els.statusDisplay) els.statusDisplay.textContent = msg; };
  const siblingPath = () => {
    const t = viewer && viewer.getTile(1);
    return t ? t.videoRel : null;
  };
  const wantSibling = () => Boolean(siblingPath()) && (els.extractSibling ? els.extractSibling.checked : true);

  function setBatchRunning(on) {
    if (els.extractBtn) els.extractBtn.disabled = on;
    if (els.batchBtn) els.batchBtn.disabled = on;
    if (els.batchStopBtn) els.batchStopBtn.classList.toggle("hidden", !on);
  }

  async function saveFrame() {
    if (!viewer || running || !endpoints.saveFrame) return;
    const primaryVideo = viewer.videoPath();
    const frame = viewer.currentFrame();
    if (!primaryVideo || frame == null) return;
    if (els.extractBtn) els.extractBtn.disabled = true;
    setStatus("Saving…");
    try {
      const payload = buildSaveFramePayload({
        primaryVideo, frameNumber: frame, extractSibling: wantSibling(), siblingVideo: siblingPath(),
      });
      const data = await (await endpoints.saveFrame(payload)).json();
      if (data.error) { setStatus(data.error); return; }
      const calib = data.calibration_copied ? " — calibration.toml copied" : "";
      if (data.saved && data.saved.length) setStatus(`Saved: ${data.saved.join(", ")}${calib}`);
      else if (data.skipped && data.skipped.length) setStatus(`Frame ${frame} already extracted — skipped.${calib}`);
      if (config.onSaved) config.onSaved();
    } catch (e) {
      setStatus("Network error: " + e.message);
    } finally {
      if (els.extractBtn) els.extractBtn.disabled = false;
    }
  }

  async function saveBatch() {
    if (!viewer || running || !endpoints.saveFrame) return;
    const primaryVideo = viewer.videoPath();
    if (!primaryVideo) return;
    const startFrame = viewer.currentFrame();
    const requested = parseBatchCount(els.batchCount ? els.batchCount.value : undefined);
    const step = parseBatchStep(els.batchStep ? els.batchStep.value : undefined);
    const { count, frames, clamped } = planBatch({ startFrame, step, requested, frameCount: viewer.frameCount() });
    if (!frames.length) { setStatus("No frames available from this position."); return; }

    const extractSibling = wantSibling();
    const sib = siblingPath();
    stopRequested = false;
    running = true;
    setBatchRunning(true);

    let saved = 0, skipped = 0, aborted = false, errored = false, calibCopied = false;
    for (let i = 0; i < frames.length; i++) {
      if (stopRequested) { aborted = true; break; }
      const targetFrame = frames[i];
      setStatus(`Saving… ${i + 1}/${count}`);
      try {
        const payload = buildSaveFramePayload({
          primaryVideo, frameNumber: targetFrame, extractSibling, siblingVideo: sib,
        });
        const data = await (await endpoints.saveFrame(payload)).json();
        if (data.error) { setStatus(`Server error at frame ${targetFrame}: ${data.error}`); errored = true; break; }
        saved += (data.saved || []).length;
        skipped += (data.skipped || []).length;
        if (data.calibration_copied) calibCopied = true;
      } catch (e) {
        setStatus(`Network error at frame ${targetFrame}: ${e.message}`);
        errored = true;
        break;
      }
      if (i < frames.length - 1) await viewer.seek(targetFrame + step);
    }

    running = false;
    setBatchRunning(false);
    if (!errored) {
      const sibTag = (extractSibling && sib) ? " (×2 sibling)" : "";
      const clampTag = clamped ? ` (clamped from ${requested})` : "";
      const calibTag = calibCopied ? " — calibration.toml copied" : "";
      setStatus(aborted
        ? `Stopped — saved ${saved}${sibTag}, skipped ${skipped}${clampTag}${calibTag}`
        : `Done — saved ${saved}${sibTag}, skipped ${skipped}${clampTag}${calibTag}`);
    }
    if (config.onSaved) config.onSaved();
  }

  return {
    attach(v) {
      viewer = v;
      const ac = new AbortController();
      const sig = { signal: ac.signal };
      if (els.extractBtn) els.extractBtn.addEventListener("click", saveFrame, sig);
      if (els.batchBtn) els.batchBtn.addEventListener("click", saveBatch, sig);
      if (els.batchStopBtn) els.batchStopBtn.addEventListener("click", () => { stopRequested = true; }, sig);
      v.on("teardown", () => ac.abort());
    },
  };
}
