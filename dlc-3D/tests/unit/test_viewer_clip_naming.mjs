import test from "node:test";
import assert from "node:assert/strict";
import {
  PRE_WINDOW, POST_WINDOW, clipWindow, computeEnd,
  sanitizePostfix, buildClipStem, parseClipStem,
} from "../../src/static/components/viewer/internal/clip_naming.mjs";

test("clipWindow centers on the keyframe and clamps to [0, frameCount-1]", () => {
  assert.deepEqual(clipWindow(500, 2000), { start: 500 - PRE_WINDOW, end: 500 + POST_WINDOW });
  assert.deepEqual(clipWindow(50, 2000), { start: 0, end: 649 });          // clamp low
  assert.deepEqual(clipWindow(1950, 2000), { start: 1750, end: 1999 });    // clamp high
});

test("computeEnd is 1-based length: start + frames - 1", () => {
  assert.equal(computeEnd(1, 800), 800);
  assert.equal(computeEnd(301, 800), 1100);
});

test("sanitizePostfix keeps [A-Za-z0-9_-] and truncates to 64", () => {
  assert.equal(sanitizePostfix("ab!c d#e"), "abcde"); // drops ! space #
  assert.equal(sanitizePostfix("multi_word-1"), "multi_word-1");
  assert.equal(sanitizePostfix(null), "");
  assert.equal(sanitizePostfix("x".repeat(100)).length, 64);
});

test("buildClipStem appends sanitized postfix only when non-empty", () => {
  assert.equal(buildClipStem("vid", 300, 1099, "good"), "vid_300_1099_good");
  assert.equal(buildClipStem("vid", 300, 1099, ""), "vid_300_1099");
  assert.equal(buildClipStem("vid", 300, 1099, "  "), "vid_300_1099");
});

test("parseClipStem extracts start/end/postfix, null on garbage", () => {
  assert.deepEqual(parseClipStem("vid", "vid_300_1099_good"), { start: 300, end: 1099, postfix: "good" });
  assert.deepEqual(parseClipStem("vid", "vid_300_1099"), { start: 300, end: 1099, postfix: "" });
  assert.deepEqual(parseClipStem("vid", "vid_300_1099_multi_word"), { start: 300, end: 1099, postfix: "multi_word" });
  assert.equal(parseClipStem("vid", "vid_garbage"), null);
});

test("build/parse round-trip", () => {
  const stem = buildClipStem("OM-2_cam0_x", 12, 811, "ok");
  assert.deepEqual(parseClipStem("OM-2_cam0_x", stem), { start: 12, end: 811, postfix: "ok" });
});
