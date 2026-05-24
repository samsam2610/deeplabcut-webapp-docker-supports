// Pure keyframe-window math for the inline-3D Finalize panel: a keyframe with N
// frames before + M frames after defines an exact-length window (keyframe
// inclusive, so length = before + after + 1). No DOM.

const toInt = (v, min) => {
  const n = Math.floor(Number(v));
  return Number.isFinite(n) ? Math.max(min, n) : min;
};

// Keep before/after/length consistent after the user edits one field.
// `edited` is "before" | "after" | "length":
//  - before/after edited → recompute length.
//  - length edited       → keep `before`, recompute after = max(0, length-before-1),
//                          then re-sync length (so a too-small length clamps up).
export function syncWindow(edited, { before, after, length }) {
  let b = toInt(before, 0), a = toInt(after, 0), l = toInt(length, 1);
  if (edited === "length") a = Math.max(0, l - b - 1);
  l = b + a + 1;
  return { before: b, after: a, length: l };
}

// Finalized range for a keyframe: [keyframe-before, keyframe+after], clamped to
// [0, frameCount-1]. n is the (clamped) inclusive frame count.
export function finalizeRange(keyframe, before, after, frameCount) {
  const k = toInt(keyframe, 0), b = toInt(before, 0), a = toInt(after, 0);
  const last = Math.max(0, toInt(frameCount, 0) - 1);
  const start = Math.min(Math.max(k - b, 0), last);
  const end = Math.min(Math.max(k + a, 0), last);
  return { start, end, n: end - start + 1 };
}
