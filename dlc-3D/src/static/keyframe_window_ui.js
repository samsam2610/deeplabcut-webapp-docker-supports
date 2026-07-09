// Reusable keyframe-window controller for the inline-3D finalize + create-clip
// panels. Owns the editable keyframe (typing auto-locks), before/after/length
// sync, lock checkbox + 'l' shortcut, range readout, frameChange tracking, and
// per-project persistence of {before, after}. Pure math: keyframe_window.mjs.
//
// opts: { viewer, panelEl, els:{keyframe,lock,before,after,length,range}, settingKey, onChange? }
import { syncWindow, finalizeRange } from "./components/viewer/internal/keyframe_window.mjs";

export function makeKeyframeWindow({ viewer, panelEl, els, settingKey, onChange, onLockChange }) {
  let keyframe = 0;
  let locked = false;
  let saveTimer = null;

  const num = (el, min) => { const n = parseInt(el && el.value, 10); return Number.isFinite(n) ? Math.max(min, n) : min; };
  const vals = () => ({ before: num(els.before, 0), after: num(els.after, 0), length: num(els.length, 1) });
  const fc = () => (viewer ? viewer.frameCount() : 0);

  function refresh() {
    // don't clobber the keyframe input while the user is typing in it
    if (els.keyframe && document.activeElement !== els.keyframe) els.keyframe.value = String(keyframe);
    const { before, after } = vals();
    const r = finalizeRange(keyframe, before, after, fc());
    if (els.range) els.range.textContent = `frames ${r.start}–${r.end} (${r.n})`;
    if (onChange) onChange(r);
  }

  function setLock(on) {
    // Single source of truth for lock state: every path (checkbox click, keyframe
    // typing auto-lock, 'l' shortcut) flips lock HERE and notifies the consumer via
    // onLockChange — so the inline card's range-confine (_applyLockState) stays in
    // sync even when the shortcut sets els.lock.checked programmatically (which does
    // NOT fire a native 'change' event). The `changed` guard suppresses redundant
    // work on repeated toggles to the same value.
    const next = !!on;
    const changed = next !== locked;
    locked = next;
    if (els.lock) els.lock.checked = locked;
    if (!locked && viewer) keyframe = viewer.currentFrame();
    refresh();
    if (changed && onLockChange) onLockChange(locked);
  }

  function onWindowInput(edited) {
    const out = syncWindow(edited, vals());
    if (els.before) els.before.value = out.before;
    if (els.after) els.after.value = out.after;
    if (els.length) els.length.value = out.length;
    refresh();
    save();
  }

  function save() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const { before, after } = vals();
      fetch("/dlc/project/ui-setting", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: settingKey, value: JSON.stringify({ before, after }) }),
      }).catch(() => {});
    }, 400);
  }

  async function load() {
    try {
      const d = await (await fetch(`/dlc/project/ui-setting?key=${encodeURIComponent(settingKey)}`)).json();
      if (d && d.value) {
        const w = JSON.parse(d.value);
        if (els.before && Number.isFinite(w.before)) els.before.value = w.before;
        if (els.after && Number.isFinite(w.after)) els.after.value = w.after;
        if (els.length) els.length.value = num(els.before, 0) + num(els.after, 0) + 1;
      }
    } catch (_) { /* keep defaults */ }
    setLock(false);   // keyframe = current frame, unlocked, refresh
  }

  // ── wiring ──
  if (els.keyframe) {
    els.keyframe.addEventListener("input", () => {
      const n = parseInt(els.keyframe.value, 10);
      if (Number.isFinite(n)) { keyframe = n; setLock(true); }   // typing auto-locks
    });
  }
  for (const id of ["before", "after", "length"]) {
    if (els[id]) els[id].addEventListener("input", () => onWindowInput(id));
  }
  [els.keyframe, els.before, els.after, els.length].forEach((el) => {
    if (el) el.addEventListener("keydown", (e) => e.stopPropagation());
  });
  // Named handlers + captured disposers so destroy() can fully unwire this instance.
  // Prevents listener accumulation across viewer teardown/rebuild (open → Back →
  // reopen), which otherwise leaves dead document-keydown + checkbox listeners behind.
  const onLockToggle = (e) => setLock(e.target.checked);
  const onDocKeydown = (e) => {
    if (e.key === "l" || e.key === "L") {
      if (!panelEl || panelEl.offsetParent === null) return;      // only when this panel is visible
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      e.preventDefault();
      setLock(!locked);
    }
  };
  if (els.lock) els.lock.addEventListener("change", onLockToggle);
  const disposeFrameChange = viewer
    ? viewer.on("frameChange", (n) => { if (!locked) { keyframe = n; refresh(); } })
    : null;
  document.addEventListener("keydown", onDocKeydown);

  function destroy() {
    if (els.lock) els.lock.removeEventListener("change", onLockToggle);
    document.removeEventListener("keydown", onDocKeydown);
    if (disposeFrameChange) disposeFrameChange();
  }

  return {
    getRange: () => { const { before, after } = vals(); return finalizeRange(keyframe, before, after, fc()); },
    refresh, load, setLock, destroy,
  };
}
