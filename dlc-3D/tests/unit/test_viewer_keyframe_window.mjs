import test from "node:test";
import assert from "node:assert/strict";
import { syncWindow, finalizeRange } from "../../src/static/components/viewer/internal/keyframe_window.mjs";

test("syncWindow: editing before/after recomputes length (=before+after+1)", () => {
  assert.deepEqual(syncWindow("before", { before: 50, after: 200, length: 401 }), { before: 50, after: 200, length: 251 });
  assert.deepEqual(syncWindow("after", { before: 200, after: 50, length: 401 }), { before: 200, after: 50, length: 251 });
});

test("syncWindow: editing length keeps `before`, recomputes after (clamped >= 0)", () => {
  assert.deepEqual(syncWindow("length", { before: 100, after: 50, length: 400 }), { before: 100, after: 299, length: 400 });
  // length below before+1 → after clamps to 0, length re-syncs up to before+1
  assert.deepEqual(syncWindow("length", { before: 200, after: 200, length: 100 }), { before: 200, after: 0, length: 201 });
});

test("syncWindow: coerces to non-negative ints", () => {
  assert.deepEqual(syncWindow("before", { before: -5, after: 10, length: 1 }), { before: 0, after: 10, length: 11 });
});

test("finalizeRange: window around the keyframe, clamped to [0, frameCount-1]", () => {
  assert.deepEqual(finalizeRange(1234, 200, 200, 3000), { start: 1034, end: 1434, n: 401 });
  assert.deepEqual(finalizeRange(100, 200, 200, 3000), { start: 0, end: 300, n: 301 });     // clamp low
  assert.deepEqual(finalizeRange(2950, 200, 200, 3000), { start: 2750, end: 2999, n: 250 }); // clamp high (last=2999)
  assert.deepEqual(finalizeRange(50, 0, 0, 3000), { start: 50, end: 50, n: 1 });             // single frame
});
