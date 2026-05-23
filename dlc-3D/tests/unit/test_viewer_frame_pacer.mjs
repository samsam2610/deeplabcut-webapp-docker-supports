import test from "node:test";
import assert from "node:assert/strict";
import {
  clampFrame, nextFrame, frameDelayMs, frameRange,
} from "../../src/static/components/viewer/internal/frame_pacer.mjs";

test("clampFrame bounds n into [lo,hi]", () => {
  assert.equal(clampFrame(5, 0, 10), 5);
  assert.equal(clampFrame(-3, 0, 10), 0);
  assert.equal(clampFrame(20, 0, 10), 10);
});

test("nextFrame advances forward by playN*playDir within range", () => {
  assert.deepEqual(nextFrame({ current: 4, playN: 2, playDir: 1, lo: 0, hi: 10, looping: false }),
    { frame: 6, stop: false });
  assert.deepEqual(nextFrame({ current: 6, playN: 1, playDir: -1, lo: 0, hi: 10, looping: false }),
    { frame: 5, stop: false });
});

test("nextFrame wraps when looping, stops when not", () => {
  // forward past hi
  assert.deepEqual(nextFrame({ current: 10, playN: 1, playDir: 1, lo: 2, hi: 10, looping: true }),
    { frame: 2, stop: false });
  assert.deepEqual(nextFrame({ current: 10, playN: 1, playDir: 1, lo: 2, hi: 10, looping: false }),
    { frame: 10, stop: true });
  // backward past lo
  assert.deepEqual(nextFrame({ current: 2, playN: 1, playDir: -1, lo: 2, hi: 10, looping: true }),
    { frame: 10, stop: false });
  assert.deepEqual(nextFrame({ current: 2, playN: 1, playDir: -1, lo: 2, hi: 10, looping: false }),
    { frame: 2, stop: true });
});

test("frameDelayMs subtracts elapsed from the per-frame budget, never negative", () => {
  assert.equal(frameDelayMs(15, 10), Math.round(1000 / 15) - 10); // 67 - 10 = 57
  assert.equal(frameDelayMs(15, 10000), 0);
});

test("frameRange picks full range when unlocked, clip range otherwise", () => {
  assert.deepEqual(frameRange({ frameCount: 100, unlocked: true, clipStart: 10, clipEnd: 20 }),
    { lo: 0, hi: 99 });
  assert.deepEqual(frameRange({ frameCount: 100, unlocked: false, clipStart: 10, clipEnd: 20 }),
    { lo: 10, hi: 20 });
});
