// Pure frame-bounds clamp for the inline-3D keyframe-lock range-confine. DOM-free.
// Returns `frame` floored into the inclusive range [start, end]. Bounds are
// normalized so a reversed (start>end) pair still clamps sanely. A non-finite
// frame coerces to the low bound.

export function clampToBounds(frame, start, end) {
  const lo = Math.min(start, end);
  const hi = Math.max(start, end);
  const f = Math.floor(Number(frame));
  if (!Number.isFinite(f)) return lo;
  return Math.min(Math.max(f, lo), hi);
}
