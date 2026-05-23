// Clip geometry + extract filename convention, mirrored from the clip-cutter
// frontend (enhanced_player.js clip window / end math) and backend
// (routes.py rename_extract: {stem}_{start}_{end}[_postfix], postfix sanitizer).

export const PRE_WINDOW = 200;
export const POST_WINDOW = 599;

// 0-based clip bounds around a 0-based keyframe, clamped to the video.
export function clipWindow(keyFrame0, frameCount, pre = PRE_WINDOW, post = POST_WINDOW) {
  return {
    start: Math.max(0, keyFrame0 - pre),
    end: Math.min(frameCount - 1, keyFrame0 + post),
  };
}

// 1-based length semantics: a clip of `frames` frames starting at `start` ends here.
export function computeEnd(start, frames) {
  return start + frames - 1;
}

// Keep only [A-Za-z0-9_-], cap at 64 chars (matches routes.py:1182).
export function sanitizePostfix(s) {
  return [...(s || "")].filter((c) => /[A-Za-z0-9_-]/.test(c)).join("").slice(0, 64);
}

export function buildClipStem(videoStem, start, end, postfix) {
  let stem = `${videoStem}_${start}_${end}`;
  const safe = sanitizePostfix(postfix);
  if (safe) stem += `_${safe}`;
  return stem;
}

// Parse "{videoStem}_{start}_{end}[_{postfix}]" → { start, end, postfix } or null.
export function parseClipStem(videoStem, stem) {
  const suffix = stem.slice(videoStem.length); // "_start_end[_postfix]"
  const m = suffix.match(/^_(\d+)_(\d+)(?:_(.+))?$/);
  if (!m) return null;
  return { start: parseInt(m[1], 10), end: parseInt(m[2], 10), postfix: m[3] || "" };
}
