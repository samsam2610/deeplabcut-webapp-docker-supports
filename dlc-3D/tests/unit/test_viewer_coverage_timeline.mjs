import test from "node:test";
import assert from "node:assert/strict";
import { coverageRects, xToFrame } from "../../src/static/components/viewer/internal/coverage_timeline.mjs";

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
