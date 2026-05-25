// Pure bodypart-selection reducers for the MarkerEditor feature. No DOM, no fetch.
// `posedSet` is the set of bodyparts considered "already labeled in this frame"
// (the caller unions raw posed bps + just-placed edits — see marker_editor.js).

// Advance selection to the next bodypart with NO label in this frame, wrapping
// once. Used after a successful place (auto-advance). When `lock` is true (Lock-BP),
// stay on `current` so the next click re-places the same bp. If every bodypart is
// labeled, or the list is empty/not-an-array, stay on `current`.
export function nextUnlabeledBodypart(bodyparts, posedSet, current, lock = false) {
  if (lock) return current;
  if (!Array.isArray(bodyparts) || bodyparts.length === 0) return current;
  const set = posedSet || new Set();
  const start = bodyparts.indexOf(current); // -1 → scan begins at index 0
  for (let i = 1; i <= bodyparts.length; i++) {
    const cand = bodyparts[(start + i + bodyparts.length) % bodyparts.length];
    if (!set.has(cand)) return cand;
  }
  return current; // all placed → stay
}

// Step selection by `dir` (+1 forward, -1 backward) with wraparound. Returns null
// for an empty list; if `current` is not in the list, returns the first element.
export function cycleBodypart(bodyparts, current, dir) {
  if (!Array.isArray(bodyparts) || bodyparts.length === 0) return null;
  const idx = bodyparts.indexOf(current);
  if (idx < 0) return bodyparts[0];
  const n = (idx + dir + bodyparts.length) % bodyparts.length;
  return bodyparts[n];
}
