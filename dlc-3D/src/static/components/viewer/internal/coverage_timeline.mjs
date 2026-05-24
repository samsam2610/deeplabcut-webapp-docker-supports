// Pure geometry for the marker-coverage timeline: turn a downsampled coverage
// bitmap into x-rects to fill, and map a click x back to a frame index. No DOM.

// buckets: array of 0/1 (covered). Returns merged [{x,w}] spans scaled to `width`.
export function coverageRects(buckets, width) {
  const n = buckets.length;
  if (!n || !width) return [];
  const rects = [];
  let runStart = -1;
  for (let i = 0; i <= n; i++) {
    const on = i < n && !!buckets[i];
    if (on && runStart < 0) runStart = i;
    else if (!on && runStart >= 0) {
      const x = Math.round((runStart / n) * width);
      const xEnd = Math.round((i / n) * width);
      rects.push({ x, w: Math.max(1, xEnd - x) });
      runStart = -1;
    }
  }
  return rects;
}

// Map a pixel x (0..width) to a frame index (0..frameCount-1), clamped.
export function xToFrame(px, width, frameCount) {
  if (!width || frameCount <= 0) return 0;
  const frac = Math.min(1, Math.max(0, px / width));
  return Math.min(frameCount - 1, Math.max(0, Math.round(frac * (frameCount - 1))));
}
