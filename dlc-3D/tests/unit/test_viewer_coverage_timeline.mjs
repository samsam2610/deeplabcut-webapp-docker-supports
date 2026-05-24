import test from "node:test";
import assert from "node:assert/strict";
import { coverageRects, xToFrame } from "../../src/static/components/viewer/internal/coverage_timeline.mjs";
import { nextCoveredBucket, bucketToFrame, frameToBucket, coverageFrameRects, nearestCoveredFrame }
  from "../../src/static/components/viewer/internal/coverage_timeline.mjs";

test("coverageFrameRects positions marks in FRAME space (aligned with the playhead), not bucket space", () => {
  // 4 buckets but the covered frames are NOT at bucket boundaries: this is where
  // bucket-space drawing (coverageRects) drifts from where a click seeks. The
  // playhead draws frame f at round(f/(fc-1)*width); marks must use the SAME map.
  const buckets = [1, 1, 0, 1];
  const frames  = [0, 30, -1, 90];   // first covered frame per bucket
  const fc = 100, width = 400;        // denom = 99
  const rects = coverageFrameRects(buckets, frames, fc, width);
  // markW = ceil(400/4) = 100; x = round(f/99*400)
  assert.deepEqual(rects, [
    { x: 0,   w: 100 },               // frame 0  → 0
    { x: 121, w: 100 },               // frame 30 → round(121.2) = 121 (bucket-space would be 100)
    { x: 364, w: 100 },               // frame 90 → round(363.6) = 364 (bucket-space would be 300)
  ]);
  // each mark x equals the playhead x for that frame (zero teleport by construction)
  for (const [i, f] of [[0,0],[1,30],[2,90]]) {
    assert.equal(rects[i].x, Math.round((f / (fc - 1)) * width));
  }
  assert.deepEqual(coverageFrameRects([0,0], [-1,-1], 100, 400), []);
  assert.deepEqual(coverageFrameRects(null, null, 100, 400), []);
});

test("nearestCoveredFrame snaps a clicked frame to the closest covered frame (ignores -1)", () => {
  const frames = [0, 30, -1, 90];
  assert.equal(nearestCoveredFrame(frames, 25), 30);   // 25 closer to 30 than 0
  assert.equal(nearestCoveredFrame(frames, 10), 0);    // 10 closer to 0 than 30
  assert.equal(nearestCoveredFrame(frames, 70), 90);   // ignores the -1 bucket
  assert.equal(nearestCoveredFrame(frames, 999), 90);  // beyond → last covered
  assert.equal(nearestCoveredFrame([-1, -1], 5), null);
  assert.equal(nearestCoveredFrame([], 5), null);
});

test("coverageRects maps covered buckets to merged x-rects scaled to width", () => {
  // 4 buckets, width 100 → each bucket 25px. covered = [1,1,0,1]
  const rects = coverageRects([1, 1, 0, 1], 100);
  // adjacent covered buckets merge into one rect; the lone last bucket is its own
  assert.deepEqual(rects, [{ x: 0, w: 50 }, { x: 75, w: 25 }]);
});

test("coverageRects: empty / all-zero → no rects", () => {
  assert.deepEqual(coverageRects([], 100), []);
  assert.deepEqual(coverageRects([0, 0, 0], 100), []);
});

test("xToFrame maps a pixel to a clamped frame index", () => {
  assert.equal(xToFrame(0, 100, 1000), 0);
  assert.equal(xToFrame(100, 100, 1000), 999);   // clamped to last frame
  assert.equal(xToFrame(50, 100, 1001), 500);
  assert.equal(xToFrame(-5, 100, 1000), 0);       // clamp low
  assert.equal(xToFrame(50, 0, 1000), 0);         // zero width → 0
});

test("nextCoveredBucket jumps to covered-run starts", () => {
  const b = [1, 1, 0, 0, 1, 1, 0, 1]; // run starts at 0, 4, 7
  assert.equal(nextCoveredBucket(b, 5, 1), 7);    // forward → next run start
  assert.equal(nextCoveredBucket(b, 5, -1), 4);   // back → current run start
  assert.equal(nextCoveredBucket(b, 4, -1), 0);   // back from a run start → previous run
  assert.equal(nextCoveredBucket(b, 0, -1), null);
  assert.equal(nextCoveredBucket(b, 7, 1), null);
  assert.equal(nextCoveredBucket([0, 0, 0], 0, 1), null);
});

test("bucket<->frame mapping clamps (bucketToFrame → bucket center)", () => {
  // bucketToFrame returns the bucket's CENTER frame so it round-trips through
  // frameToBucket (floor) — a start-of-bucket mapping undershoots by one and
  // breaks region nav (see the round-trip test below).
  assert.equal(bucketToFrame(0, 10, 1000), 50);     // center of bucket 0
  assert.equal(bucketToFrame(5, 10, 1000), 550);    // center of bucket 5
  assert.equal(bucketToFrame(10, 10, 1000), 999);   // clamp to last frame
  assert.equal(frameToBucket(0, 1000, 10), 0);
  assert.equal(frameToBucket(999, 1000, 10), 9);     // clamp to last bucket
  assert.equal(frameToBucket(500, 1000, 10), 5);
  assert.equal(frameToBucket(0, 0, 10), 0);          // zero frames → 0
});

test("bucketToFrame round-trips through frameToBucket (stable region nav)", () => {
  const fc = 250000, nB = 600;
  for (const b of [0, 1, 99, 100, 300, 499, 500, 599]) {
    assert.equal(frameToBucket(bucketToFrame(b, nB, fc), fc, nB), b, `bucket ${b} must round-trip`);
  }
});

test("repeated region-nav advances through every run without sticking", () => {
  // Simulates the finalize-bar "next" loop: frame → bucket → next run → frame.
  // With a start-of-bucket mapping this stuck on a region forever (re-bucketing
  // landed one bucket BEFORE the run start, so nextCoveredBucket returned it again).
  const fc = 250000, nB = 600;
  const buckets = new Array(nB).fill(0);
  for (let i = 100; i <= 110; i++) buckets[i] = 1;
  for (let i = 300; i <= 305; i++) buckets[i] = 1;
  for (let i = 500; i <= 520; i++) buckets[i] = 1;
  let frame = 0;
  const runs = [];
  for (let c = 0; c < 5; c++) {
    const b = nextCoveredBucket(buckets, frameToBucket(frame, fc, nB), 1);
    if (b == null) { runs.push(null); break; }
    runs.push(b);
    frame = bucketToFrame(b, nB, fc);
  }
  assert.deepEqual(runs, [100, 300, 500, null]); // each run once, then terminates
});
