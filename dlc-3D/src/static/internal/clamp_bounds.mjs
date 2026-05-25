// Pure frame-bounds clamp for the inline-3D keyframe-lock range-confine. DOM-free.
// Returns `frame` floored into the inclusive range [start, end]. Bounds are
// normalized so a reversed (start>end) pair still clamps sanely. A non-finite
// frame coerces to the low bound. If a bound is itself non-finite (e.g. called
// before the keyframe window is initialised) the clamp is a no-op: the floored
// frame passes through (or 0 if it is also non-finite), never NaN.

export function clampToBounds(frame, start, end) {
  const s = Number(start);
  const e = Number(end);
  const f = Math.floor(Number(frame));
  if (!Number.isFinite(s) || !Number.isFinite(e)) return Number.isFinite(f) ? f : 0;
  const lo = Math.min(s, e);
  const hi = Math.max(s, e);
  if (!Number.isFinite(f)) return lo;
  return Math.min(Math.max(f, lo), hi);
}
