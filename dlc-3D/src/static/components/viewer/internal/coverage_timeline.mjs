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

// Index of the next (dir=1) / previous (dir=-1) covered-RUN start relative to
// fromBucket, or null. A run start is a covered bucket whose predecessor is not
// covered. Forward skips the rest of the current run; backward returns the
// nearest run start strictly before fromBucket.
export function nextCoveredBucket(buckets, fromBucket, dir) {
  const n = buckets.length;
  const isStart = (i) => !!buckets[i] && (i === 0 || !buckets[i - 1]);
  if (dir < 0) {
    for (let i = Math.min(fromBucket - 1, n - 1); i >= 0; i--) if (isStart(i)) return i;
    return null;
  }
  for (let i = Math.max(fromBucket + 1, 0); i < n; i++) if (isStart(i)) return i;
  return null;
}

// Map a bucket index → frame index (clamped to 0..frameCount-1). Uses the
// bucket's CENTER, not its first frame: frameToBucket uses floor, so a
// start-of-bucket frame re-buckets to (bucket-1) and region nav ("jump to next
// covered run") would return the SAME run forever. The center round-trips
// exactly through frameToBucket.
export function bucketToFrame(bucket, nBuckets, frameCount) {
  if (nBuckets <= 0 || frameCount <= 0) return 0;
  return Math.min(frameCount - 1, Math.max(0, Math.round(((bucket + 0.5) / nBuckets) * frameCount)));
}

// Map a frame index → bucket index (clamped to 0..nBuckets-1).
export function frameToBucket(frame, frameCount, nBuckets) {
  if (frameCount <= 0 || nBuckets <= 0) return 0;
  return Math.min(nBuckets - 1, Math.max(0, Math.floor((frame / frameCount) * nBuckets)));
}

// Map a pixel x (0..width) → bucket index (clamped). Inverse of coverageRects'
// layout (bucket b spans [b/n, (b+1)/n)·width). Lets a click on the coverage bar
// resolve which bucket was hit, so we can seek to that bucket's real covered frame.
export function xToBucket(px, width, nBuckets) {
  if (!width || nBuckets <= 0) return 0;
  const frac = Math.min(1, Math.max(0, px / width));
  return Math.min(nBuckets - 1, Math.max(0, Math.floor(frac * nBuckets)));
}
