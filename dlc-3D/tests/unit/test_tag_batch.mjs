import test from "node:test";
import assert from "node:assert/strict";
import { tagKeyframes, mergeWindows } from "../../src/static/components/viewer/internal/tag_batch.mjs";

test("tagKeyframes: filters by note value, dedupes, sorts, drops non-numeric/negative", () => {
  const rows = [
    { frame_number: "30", note: "grab" },
    { frame_number: "10", note: "grab" },
    { frame_number: "10", note: "grab" },   // dup
    { frame_number: "20", note: "rest" },    // other note
    { frame_number: "50", note: "" },        // empty note
    { frame_number: "x", note: "grab" },     // non-numeric
    { frame_number: "-5", note: "grab" },    // negative
  ];
  assert.deepEqual(tagKeyframes(rows, "grab"), [10, 30]);
  assert.deepEqual(tagKeyframes([], "grab"), []);
  assert.deepEqual(tagKeyframes(null, "grab"), []);
});

test("mergeWindows: single frame → one clamped range with correct n", () => {
  assert.deepEqual(mergeWindows([1234], 200, 200, 3000), [{ start: 1034, end: 1434, n: 401 }]);
  assert.deepEqual(mergeWindows([50], 0, 0, 3000), [{ start: 50, end: 50, n: 1 }]);
});

test("mergeWindows: far-apart frames → two ranges; close/overlapping → merged", () => {
  // 10 → [0,609] (clamp low, before 200), 5000 → [4800,5599]; far apart → 2 ranges
  assert.deepEqual(mergeWindows([10, 5000], 200, 599, 6000),
    [{ start: 0, end: 609, n: 610 }, { start: 4800, end: 5599, n: 800 }]);
  // 100 → [0,300], 300 → [100,500]; overlap → merged [0,500]
  assert.deepEqual(mergeWindows([100, 300], 200, 200, 3000), [{ start: 0, end: 500, n: 501 }]);
});

test("mergeWindows: adjacent (touching) windows merge", () => {
  // 200 → [0,400], 601 → [401,801]; touch at 400/401 → merged [0,801]
  assert.deepEqual(mergeWindows([200, 601], 200, 200, 3000), [{ start: 0, end: 801, n: 802 }]);
});

test("mergeWindows: empty input → empty list", () => {
  assert.deepEqual(mergeWindows([], 200, 200, 3000), []);
});
