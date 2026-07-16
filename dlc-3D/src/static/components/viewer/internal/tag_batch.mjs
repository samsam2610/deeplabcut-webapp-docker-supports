// Pure range math for the inline-3D "Analyze for tag" batch. Turns tagged frames
// into the minimal set of contiguous analyze ranges. No DOM. Works in CSV
// frame_number space (the inline-3D timeline uses frameBase 0, so frame_number ==
// viewer seek-frame).
import { finalizeRange } from "./keyframe_window.mjs";

// Sorted, deduped, non-negative integer frame_numbers whose note === tagValue.
export function tagKeyframes(rows, tagValue) {
  const out = new Set();
  for (const r of rows || []) {
    if (!r || r.note !== tagValue) continue;
    const n = Math.floor(Number(r.frame_number));
    if (Number.isFinite(n) && n >= 0) out.add(n);
  }
  return [...out].sort((a, b) => a - b);
}

// Expand each frame to [frame-before, frame+after] (clamped via finalizeRange),
// then union overlapping/adjacent spans into a minimal sorted list of {start,end,n}.
export function mergeWindows(frames, before, after, frameCount) {
  const spans = (frames || []).map((f) => {
    const { start, end } = finalizeRange(f, before, after, frameCount);
    return { start, end };
  });
  spans.sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [];
  for (const s of spans) {
    const last = merged[merged.length - 1];
    if (last && s.start <= last.end + 1) {
      if (s.end > last.end) last.end = s.end;
    } else {
      merged.push({ start: s.start, end: s.end });
    }
  }
  return merged.map((r) => ({ start: r.start, end: r.end, n: r.end - r.start + 1 }));
}
