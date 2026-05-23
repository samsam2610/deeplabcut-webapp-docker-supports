// ClipExtractor — feature module for VideoViewer.
// Trims the master clip (clip-cutter gold standard): start/length/end inputs, postfix +
// quick-tags, keyframe-overlap check, synchronous extract of the primary (and optionally
// the sibling cam over the same frame range), plus rename/delete of the produced clip.
// Gated behind an "enable clip extract" checkbox that is UNCHECKED by default (the consumer
// renders it unchecked; the panel starts hidden until enabled). All endpoints/elements
// injected; follows the feature-teardown pattern.
//
// Usage:
//   viewer.use(clipExtractor({
//     endpoints: {
//       extractClip: (payload) => fetchPromise,  // → { avi_path }
//       rename?:     (payload) => fetchPromise,  // → { avi_path }
//       del?:        (payload) => fetchPromise,
//       overlap?:    (payload) => fetchPromise,  // → { overlaps, conflicts:[{name,overlap_frames}] }
//     },
//     els: { enable, panel, startInput, framesInput, endDisplay, postfixInput,
//            extractBtn, renameBtn, deleteBtn, extractSibling?,
//            tagsContainer?, addTagBtn?, newTagInput?, statusDisplay?, warning? },
//     storagePrefix?: "vv", preWindow?: 200, defaultFrames?: 800,
//     onExtracted?: ({ primary, sibling }) => void,
//   }));

import {
  buildExtractRequest, buildRenameRequest, buildDeleteRequest,
  buildOverlapRequest, addTag, removeTagAt,
} from "../internal/clip_extract.mjs";
import { computeEnd } from "../internal/clip_naming.mjs";

export function clipExtractor(config = {}) {
  const els = config.els || {};
  const endpoints = config.endpoints || {};
  const storagePrefix = config.storagePrefix || "vv";
  const preWindow = config.preWindow ?? 200;
  const defaultFrames = config.defaultFrames || 800;
  const TAGS_KEY = `${storagePrefix}:clip-postfix-tags`;

  let viewer = null;
  let tags = [];
  let activeTag = null;
  let lastPrimaryAvi = null;
  let lastSiblingAvi = null;
  let running = false;
  const ac = new AbortController(); // feature-scoped so confirmOverlap can observe teardown

  const setStatus = (m) => { if (els.statusDisplay) els.statusDisplay.textContent = m; };
  const siblingPath = () => { const t = viewer && viewer.getTile(1); return t ? t.videoRel : null; };
  const wantSibling = () => Boolean(siblingPath()) && (els.extractSibling ? els.extractSibling.checked : false);
  const readStart = () => parseInt(els.startInput && els.startInput.value, 10) || 1;
  const readFrames = () => parseInt(els.framesInput && els.framesInput.value, 10) || defaultFrames;
  const readPostfix = () => (els.postfixInput ? els.postfixInput.value : "");

  function updateEnd() {
    if (els.endDisplay) els.endDisplay.value = computeEnd(readStart(), readFrames());
  }

  // ── postfix quick-tags (localStorage, namespaced by storagePrefix) ──
  function loadTags() {
    try { tags = JSON.parse(localStorage.getItem(TAGS_KEY)) || []; } catch (_) { tags = []; }
  }
  function persistTags() {
    try { localStorage.setItem(TAGS_KEY, JSON.stringify(tags)); } catch (_) { /* ignore */ }
  }
  function renderTags() {
    const c = els.tagsContainer;
    if (!c) return;
    c.innerHTML = "";
    tags.forEach((tag, idx) => {
      const pill = c.ownerDocument.createElement("span");
      pill.className = "vv-postfix-tag" + (activeTag === tag ? " active" : "");
      const label = c.ownerDocument.createElement("span");
      label.textContent = tag;
      const del = c.ownerDocument.createElement("span");
      del.className = "vv-tag-del";
      del.textContent = "×";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        tags = removeTagAt(tags, idx);
        if (activeTag === tag) { activeTag = null; if (els.postfixInput) els.postfixInput.value = ""; }
        persistTags();
        renderTags();
      });
      pill.appendChild(label);
      pill.appendChild(del);
      pill.addEventListener("click", () => {
        if (activeTag === tag) { activeTag = null; if (els.postfixInput) els.postfixInput.value = ""; }
        else { activeTag = tag; if (els.postfixInput) els.postfixInput.value = tag; }
        renderTags();
      });
      c.appendChild(pill);
    });
  }
  function addNewTag() {
    const next = addTag(tags, els.newTagInput ? els.newTagInput.value : "");
    if (next.length !== tags.length) { tags = next; persistTags(); renderTags(); }
    if (els.newTagInput) els.newTagInput.value = "";
  }

  // ── enable gate (panel hidden until the checkbox is checked) ──
  function applyEnabled() {
    const on = els.enable ? els.enable.checked : true;
    if (els.panel) els.panel.classList.toggle("hidden", !on);
  }

  function updateExtractActions() {
    const has = Boolean(lastPrimaryAvi);
    if (els.renameBtn) els.renameBtn.disabled = !has;
    if (els.deleteBtn) els.deleteBtn.disabled = !has;
  }

  // ── overlap warning (resolve true to proceed; resolves false if torn down) ──
  function confirmOverlap(conflicts) {
    return new Promise((resolve) => {
      if (ac.signal.aborted) { resolve(false); return; }
      const w = els.warning;
      if (!w) { resolve(true); return; }
      w.innerHTML = "";
      const onAbort = () => { w.innerHTML = ""; w.classList.add("hidden"); resolve(false); };
      ac.signal.addEventListener("abort", onAbort, { once: true });
      const finish = (val) => { ac.signal.removeEventListener("abort", onAbort); w.classList.add("hidden"); resolve(val); };
      const c = conflicts && conflicts[0];
      const msg = w.ownerDocument.createElement("div");
      msg.textContent = c ? `⚠ Overlaps ${c.name} by ${c.overlap_frames} fr` : "⚠ Overlap detected";
      const cancel = w.ownerDocument.createElement("button");
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", () => finish(false));
      const keep = w.ownerDocument.createElement("button");
      keep.textContent = "Keep anyway";
      keep.addEventListener("click", () => finish(true));
      w.appendChild(msg);
      w.appendChild(cancel);
      w.appendChild(keep);
      w.classList.remove("hidden");
    });
  }

  async function doExtract() {
    if (!viewer || !endpoints.extractClip || running) return;
    const videoPath = viewer.videoPath();
    if (!videoPath) return;
    running = true;
    if (els.extractBtn) els.extractBtn.disabled = true;
    try {
      const start = readStart();
      const frames = readFrames();
      const postfix = readPostfix();

      if (endpoints.overlap) {
        try {
          const ov = await (await endpoints.overlap(buildOverlapRequest({ videoPath, start, preWindow }))).json();
          if (ov.overlaps && !(await confirmOverlap(ov.conflicts))) return;
        } catch (_) { /* overlap check best-effort */ }
      }

      setStatus("Extracting…");
      const primary = await (await endpoints.extractClip(
        buildExtractRequest({ videoPath, start, frames, postfix, preWindow }))).json();
      if (primary.error) { setStatus(primary.error); return; }
      lastPrimaryAvi = primary.avi_path || null;
      lastSiblingAvi = null;
      if (wantSibling()) {
        const sib = await (await endpoints.extractClip(
          buildExtractRequest({ videoPath: siblingPath(), start, frames, postfix, preWindow }))).json();
        lastSiblingAvi = sib.avi_path || null;
      }
      setStatus("Extracted" + (lastSiblingAvi ? " (+sibling)" : ""));
      updateExtractActions();
      if (config.onExtracted) config.onExtracted({ primary: lastPrimaryAvi, sibling: lastSiblingAvi });
    } catch (e) {
      setStatus("Network error: " + e.message);
    } finally {
      running = false;
      if (els.extractBtn) els.extractBtn.disabled = false;
    }
  }

  async function doRename() {
    if (!lastPrimaryAvi || !endpoints.rename) return;
    const postfix = readPostfix();
    try {
      const r = await (await endpoints.rename(buildRenameRequest({ aviPath: lastPrimaryAvi, postfix }))).json();
      if (r.avi_path) lastPrimaryAvi = r.avi_path;
      if (lastSiblingAvi) {
        const rs = await (await endpoints.rename(buildRenameRequest({ aviPath: lastSiblingAvi, postfix }))).json();
        if (rs.avi_path) lastSiblingAvi = rs.avi_path;
      }
      setStatus("Renamed");
    } catch (e) {
      setStatus("Network error: " + e.message);
    }
  }

  async function doDelete() {
    if (!lastPrimaryAvi || !endpoints.del) return;
    try {
      await endpoints.del(buildDeleteRequest({ aviPath: lastPrimaryAvi }));
      if (lastSiblingAvi) await endpoints.del(buildDeleteRequest({ aviPath: lastSiblingAvi }));
      lastPrimaryAvi = null;
      lastSiblingAvi = null;
      updateExtractActions();
      setStatus("Deleted");
    } catch (e) {
      setStatus("Network error: " + e.message);
    }
  }

  return {
    attach(v) {
      viewer = v;
      loadTags();
      renderTags();
      updateEnd();
      applyEnabled();
      updateExtractActions();
      const sig = { signal: ac.signal };
      if (els.enable) els.enable.addEventListener("change", applyEnabled, sig);
      if (els.startInput) els.startInput.addEventListener("input", updateEnd, sig);
      if (els.framesInput) els.framesInput.addEventListener("input", updateEnd, sig);
      if (els.extractBtn) els.extractBtn.addEventListener("click", doExtract, sig);
      if (els.renameBtn) els.renameBtn.addEventListener("click", doRename, sig);
      if (els.deleteBtn) els.deleteBtn.addEventListener("click", doDelete, sig);
      if (els.addTagBtn) els.addTagBtn.addEventListener("click", addNewTag, sig);
      if (els.newTagInput) {
        els.newTagInput.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); addNewTag(); }
        }, sig);
      }
      // Reset the produced-clip handles when a new video loads, so Rename/Delete never
      // act on a clip from the previous video.
      const disposers = [
        v.on("videoLoad", () => {
          lastPrimaryAvi = null;
          lastSiblingAvi = null;
          updateExtractActions();
        }),
      ];
      v.on("teardown", () => { for (const d of disposers) d(); ac.abort(); });
    },
  };
}
