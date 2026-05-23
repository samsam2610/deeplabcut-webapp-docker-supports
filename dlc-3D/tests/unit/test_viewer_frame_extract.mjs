import test from "node:test";
import assert from "node:assert/strict";
import {
  parseBatchCount, parseBatchStep, planBatch, buildSaveFramePayload,
} from "../../src/static/components/viewer/internal/frame_extract.mjs";

test("parseBatchCount: >=2, default 10 on NaN", () => {
  assert.equal(parseBatchCount("5"), 5);
  assert.equal(parseBatchCount("1"), 2);   // floor of 2
  assert.equal(parseBatchCount("abc"), 10);
  assert.equal(parseBatchCount(""), 10);
});

test("parseBatchStep: >=1, default 1 on NaN", () => {
  assert.equal(parseBatchStep("3"), 3);
  assert.equal(parseBatchStep("0"), 1);
  assert.equal(parseBatchStep("xyz"), 1);
});

test("planBatch: full count when room, frames = start + i*step", () => {
  assert.deepEqual(planBatch({ startFrame: 0, step: 1, requested: 5, frameCount: 100 }),
    { count: 5, frames: [0, 1, 2, 3, 4], clamped: false });
});

test("planBatch: clamps count to what fits at the given step", () => {
  // maxCount = floor((99-95)/2)+1 = 3
  assert.deepEqual(planBatch({ startFrame: 95, step: 2, requested: 10, frameCount: 100 }),
    { count: 3, frames: [95, 97, 99], clamped: true });
});

test("planBatch: last frame only when at the end", () => {
  assert.deepEqual(planBatch({ startFrame: 99, step: 1, requested: 5, frameCount: 100 }),
    { count: 1, frames: [99], clamped: true });
});

test("buildSaveFramePayload: omits sibling fields unless extracting a sibling", () => {
  assert.deepEqual(
    buildSaveFramePayload({ primaryVideo: "a.avi", frameNumber: 7, extractSibling: false, siblingVideo: "b.avi" }),
    { primary_video: "a.avi", primary_frame_number: 7, extract_sibling: false });
  assert.deepEqual(
    buildSaveFramePayload({ primaryVideo: "a.avi", frameNumber: 7, extractSibling: true, siblingVideo: "b.avi" }),
    { primary_video: "a.avi", primary_frame_number: 7, extract_sibling: true,
      sibling_video: "b.avi", sibling_frame_number: 7 });
  // extractSibling true but no sibling path → no sibling fields
  assert.deepEqual(
    buildSaveFramePayload({ primaryVideo: "a.avi", frameNumber: 7, extractSibling: true, siblingVideo: null }),
    { primary_video: "a.avi", primary_frame_number: 7, extract_sibling: true });
});
