// StatusNoteTimeline — feature module for VideoViewer.
// CSV-backed per-frame status + note browsing: timeline bars, toggle chips,
// prev/next-by-chip navigation, per-frame badges/inputs, and optional save-back.
// All endpoints/elements injected via config; subscribes to the viewer hook bus.
//
// Usage:
//   viewer.use(statusNoteTimeline({
//     endpoints: { csv: (videoPath) => url, saveRow: (payload) => fetchPromise },
//     els: { statusCanvas, noteCanvas, statusChips, noteChips,
//            statusWrap?, noteWrap?,
//            statusBadge?, noteBadge?, statusInput?, noteInput?,
//            statusPrev?, statusNext?, notePrev?, noteNext?,
//            saveStatusBtn?, saveNoteBtn?, saveFeedback? },
//     palette?: { status: [...], note: [...] }, frameBase?: 0, fps?: 30,
//   }));
//
// The reducer works in CSV frame_number space; frameBase maps it to viewer seek-frames
// (row.frame_number = seekFrame + frameBase).

import {
  uniqueValues, assignColors, findMatchingFrame, rowForFrame,
  isInterestingAnnotation, applySavedRow, buildSaveRowPayload,
} from "../internal/csv_annotations.mjs";

const DEFAULT_STATUS_PALETTE = ["#34d399", "#f97316", "#e879f9", "#facc15", "#f87171", "#22d3ee", "#a78bfa", "#fb923c"];
const DEFAULT_NOTE_PALETTE = ["#60a5fa", "#f472b6", "#4ade80", "#38bdf8", "#e879f9", "#a78bfa", "#facc15", "#fb7185"];

export function statusNoteTimeline(config = {}) {
  const els = config.els || {};
  const endpoints = config.endpoints || {};
  const statusPalette = (config.palette && config.palette.status) || DEFAULT_STATUS_PALETTE;
  const notePalette = (config.palette && config.palette.note) || DEFAULT_NOTE_PALETTE;
  const frameBase = config.frameBase ?? 0;

  let viewer = null;
  let rows = [];
  let csvPath = null;
  let loadGen = 0;
  let statusColors = {};
  let noteColors = {};
  const activeStatus = new Set();
  const activeNote = new Set();

  const seekToRow = (f) => f + frameBase;
  const rowToSeek = (fn) => fn - frameBase;
  const total = () => Math.max(viewer ? viewer.frameCount() : 1, 1);
  const curFrame = () => (viewer ? viewer.currentFrame() : 0);

  async function loadCsv(videoPath) {
    const gen = ++loadGen;
    rows = [];
    csvPath = null;
    activeStatus.clear();
    activeNote.clear();
    if (endpoints.csv && videoPath) {
      try {
        const data = await (await fetch(endpoints.csv(videoPath))).json();
        if (gen !== loadGen) return; // superseded by a newer load
        rows = data.rows || [];
        csvPath = data.csv_path || null;
      } catch (_) { rows = []; }
    }
    if (gen !== loadGen) return;
    recolor();
    rebuildChips();
    redraw(curFrame());
    updateBadges(curFrame());
  }

  function recolor() {
    statusColors = assignColors(uniqueValues(rows, "frame_line_status"), statusPalette);
    noteColors = assignColors(uniqueValues(rows, "note"), notePalette);
    if (els.statusWrap) els.statusWrap.style.display = Object.keys(statusColors).length ? "" : "none";
    if (els.noteWrap) els.noteWrap.style.display = Object.keys(noteColors).length ? "" : "none";
  }

  function rebuildChips() {
    renderChips(els.statusChips, statusColors, activeStatus);
    renderChips(els.noteChips, noteColors, activeNote);
    updateNavDisabled();
  }

  function renderChips(container, colorMap, activeSet) {
    if (!container) return;
    container.innerHTML = "";
    for (const val of Object.keys(colorMap)) {
      const chip = container.ownerDocument.createElement("span");
      chip.className = "vv-tag-chip" + (activeSet.has(val) ? " active" : "");
      chip.textContent = val;
      chip.style.setProperty("--chip-color", colorMap[val]);
      chip.addEventListener("click", () => {
        if (activeSet.has(val)) activeSet.delete(val);
        else activeSet.add(val);
        rebuildChips();
        redraw(curFrame());
      });
      container.appendChild(chip);
    }
  }

  function drawBar(canvas, field, activeSet, colorMap) {
    if (!canvas) return;
    const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
    canvas.width = W;
    const H = canvas.height || 12;
    const ctx = canvas.getContext("2d");
    const minW = Math.max(1, Math.round(W / total()));
    ctx.clearRect(0, 0, W, H);
    if (!activeSet.size) return;
    for (const row of rows) {
      const val = row[field];
      if (!val || (field === "frame_line_status" && val === "0")) continue;
      if (!activeSet.has(val)) continue;
      ctx.fillStyle = colorMap[val] || "#888";
      const x = Math.round((rowToSeek(Number(row.frame_number)) / Math.max(total() - 1, 1)) * W);
      ctx.fillRect(x, 0, minW, H);
    }
  }

  function drawCursor(canvas, frame) {
    if (!canvas || !canvas.width) return;
    const ctx = canvas.getContext("2d");
    const x = Math.round((frame / Math.max(total() - 1, 1)) * canvas.width);
    ctx.save();
    ctx.globalAlpha = 0.8;
    ctx.fillStyle = "#fff";
    ctx.fillRect(x, 0, 1, canvas.height);
    ctx.restore();
  }

  function redraw(frame) {
    drawBar(els.statusCanvas, "frame_line_status", activeStatus, statusColors);
    drawCursor(els.statusCanvas, frame);
    drawBar(els.noteCanvas, "note", activeNote, noteColors);
    drawCursor(els.noteCanvas, frame);
  }

  function updateBadges(frame) {
    const row = rowForFrame(rows, seekToRow(frame));
    if (els.statusBadge) els.statusBadge.textContent = (row && row.frame_line_status) || "—";
    if (els.noteBadge) els.noteBadge.textContent = (row && row.note) || "—";
    if (els.statusInput) els.statusInput.value = row ? (row.frame_line_status ?? "0") : "0";
    if (els.noteInput) els.noteInput.value = row ? (row.note || "") : "";
  }

  function updateNavDisabled() {
    const sOn = activeStatus.size > 0;
    const nOn = activeNote.size > 0;
    if (els.statusPrev) els.statusPrev.disabled = !sOn;
    if (els.statusNext) els.statusNext.disabled = !sOn;
    if (els.notePrev) els.notePrev.disabled = !nOn;
    if (els.noteNext) els.noteNext.disabled = !nOn;
  }

  function timelineSeek(e, canvas) {
    if (!viewer || !canvas || !canvas.width) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    viewer.pause();
    viewer.seek(Math.round(frac * Math.max(total() - 1, 0)));
  }

  function nav(field, activeSet, dir) {
    if (!viewer) return;
    const fn = findMatchingFrame(rows, field, activeSet, seekToRow(curFrame()), dir);
    if (fn != null) { viewer.pause(); viewer.seek(rowToSeek(fn)); }
  }

  async function save(kind) {
    if (!viewer || !csvPath || !endpoints.saveRow) return;
    if (kind === "note" && !els.noteInput) return;     // nothing to save without the input
    if (kind === "status" && !els.statusInput) return;
    const frame = curFrame();
    const existing = rowForFrame(rows, seekToRow(frame));
    const note = els.noteInput ? els.noteInput.value.trim()
      : (kind === "status" && existing ? (existing.note || "") : "");
    const status = els.statusInput ? (els.statusInput.value || "0")
      : (kind === "note" && existing ? (existing.frame_line_status || "0") : "0");
    const payload = buildSaveRowPayload({
      csvPath, frameNumber: seekToRow(frame), note, status, fps: config.fps || 30,
    });
    if (els.saveFeedback) els.saveFeedback.textContent = "Saving…";
    try {
      const data = await (await endpoints.saveRow(payload)).json();
      if (data.error) throw new Error(data.error);
      const savedRow = data.row || { frame_number: seekToRow(frame), frame_line_status: status, note };
      rows = applySavedRow(rows, savedRow, isInterestingAnnotation(note, status));
      recolor();
      rebuildChips();
      redraw(frame);
      updateBadges(frame);
      if (els.saveFeedback) {
        els.saveFeedback.textContent = "Saved";
        setTimeout(() => {
          if (els.saveFeedback.textContent === "Saved") els.saveFeedback.textContent = "";
        }, 2000);
      }
    } catch (err) {
      if (els.saveFeedback) els.saveFeedback.textContent = `Error: ${err.message}`;
    }
  }

  return {
    attach(v) {
      viewer = v;
      // Capture bus disposers + an AbortController for DOM listeners so the feature
      // fully detaches on viewer "teardown" (the canonical feature-teardown pattern).
      const disposers = [
        v.on("videoLoad", (e) => loadCsv(e && e.videoPath)),
        v.on("frameChange", (frame) => { updateBadges(frame); redraw(frame); }),
      ];
      const ac = new AbortController();
      const sig = { signal: ac.signal };
      if (els.statusPrev) els.statusPrev.addEventListener("click", () => nav("frame_line_status", activeStatus, -1), sig);
      if (els.statusNext) els.statusNext.addEventListener("click", () => nav("frame_line_status", activeStatus, 1), sig);
      if (els.notePrev) els.notePrev.addEventListener("click", () => nav("note", activeNote, -1), sig);
      if (els.noteNext) els.noteNext.addEventListener("click", () => nav("note", activeNote, 1), sig);
      if (els.saveStatusBtn) els.saveStatusBtn.addEventListener("click", () => save("status"), sig);
      if (els.saveNoteBtn) els.saveNoteBtn.addEventListener("click", () => save("note"), sig);
      if (els.statusCanvas) els.statusCanvas.addEventListener("click", (e) => timelineSeek(e, els.statusCanvas), sig);
      if (els.noteCanvas) els.noteCanvas.addEventListener("click", (e) => timelineSeek(e, els.noteCanvas), sig);
      v.on("teardown", () => { for (const d of disposers) d(); ac.abort(); });
    },
  };
}
