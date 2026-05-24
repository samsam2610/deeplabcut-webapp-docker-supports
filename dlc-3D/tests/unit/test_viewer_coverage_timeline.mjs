import test from "node:test";
import assert from "node:assert/strict";
import { coverageRects, xToFrame } from "../../src/static/components/viewer/internal/coverage_timeline.mjs";
import { nextCoveredBucket, bucketToFrame, frameToBucket }
  from "../../src/static/components/viewer/internal/coverage_timeline.mjs";

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

test("bucket<->frame mapping clamps", () => {
  assert.equal(bucketToFrame(0, 10, 1000), 0);
  assert.equal(bucketToFrame(5, 10, 1000), 500);
  assert.equal(bucketToFrame(10, 10, 1000), 999);   // clamp to last frame
  assert.equal(frameToBucket(0, 1000, 10), 0);
  assert.equal(frameToBucket(999, 1000, 10), 9);     // clamp to last bucket
  assert.equal(frameToBucket(500, 1000, 10), 5);
  assert.equal(frameToBucket(0, 0, 10), 0);          // zero frames → 0
});
