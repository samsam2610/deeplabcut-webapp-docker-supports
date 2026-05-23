import test from "node:test";
import assert from "node:assert/strict";
import {
  keyFrameForStart, buildExtractRequest, buildRenameRequest,
  buildDeleteRequest, buildOverlapRequest, addTag, removeTagAt,
} from "../../src/static/components/viewer/internal/clip_extract.mjs";

test("keyFrameForStart = start + preWindow (default 200)", () => {
  assert.equal(keyFrameForStart(300), 500);
  assert.equal(keyFrameForStart(300, 100), 400);
});

test("buildExtractRequest: end = start+frames-1, keyframe, sanitized postfix", () => {
  assert.deepEqual(
    buildExtractRequest({ videoPath: "v.avi", start: 301, frames: 800, postfix: "go od!" }),
    { video_path: "v.avi", key_frame: 501, start_fn: 301, end_fn: 1100, postfix: "good" });
});

test("buildRenameRequest sanitizes the postfix", () => {
  assert.deepEqual(buildRenameRequest({ aviPath: "/c.avi", postfix: "a b#c" }),
    { avi_path: "/c.avi", postfix: "abc" });
});

test("buildDeleteRequest / buildOverlapRequest shapes", () => {
  assert.deepEqual(buildDeleteRequest({ aviPath: "/c.avi" }), { avi_path: "/c.avi" });
  assert.deepEqual(buildOverlapRequest({ videoPath: "v.avi", start: 300 }),
    { video_path: "v.avi", key_frame: 500 });
});

test("addTag: trims, dedups, ignores empty; returns a new array", () => {
  assert.deepEqual(addTag(["a"], "b"), ["a", "b"]);
  assert.deepEqual(addTag(["a"], "  a  "), ["a"]);   // dedup after trim
  assert.deepEqual(addTag(["a"], "   "), ["a"]);     // empty ignored
  const base = ["a"];
  addTag(base, "b");
  assert.deepEqual(base, ["a"]);                      // no mutation
});

test("removeTagAt: removes by index, ignores out-of-range, new array", () => {
  assert.deepEqual(removeTagAt(["a", "b", "c"], 1), ["a", "c"]);
  assert.deepEqual(removeTagAt(["a"], 5), ["a"]);
  const base = ["a", "b"];
  removeTagAt(base, 0);
  assert.deepEqual(base, ["a", "b"]);                 // no mutation
});
