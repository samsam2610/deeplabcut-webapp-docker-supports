import test from "node:test";
import assert from "node:assert/strict";
import { resolveKey, clampPlayStep, clampFps }
  from "../../src/static/components/viewer/internal/controls.mjs";

test("space → playPause", () => {
  assert.deepEqual(resolveKey({ key: " " }), { type: "playPause" });
});

test("arrows → single step; ctrl+arrows → skip step", () => {
  assert.deepEqual(resolveKey({ key: "ArrowLeft" }),  { type: "step", delta: -1 });
  assert.deepEqual(resolveKey({ key: "ArrowRight" }), { type: "step", delta: 1 });
  assert.deepEqual(resolveKey({ key: "ArrowLeft", ctrlKey: true }),  { type: "stepSkip", dir: -1 });
  assert.deepEqual(resolveKey({ key: "ArrowRight", ctrlKey: true }), { type: "stepSkip", dir: 1 });
});

test("unhandled keys → null", () => {
  assert.equal(resolveKey({ key: "x" }), null);
  assert.equal(resolveKey({ key: "Tab" }), null);
});

test("clampPlayStep: 1..100, default 1 on NaN", () => {
  assert.equal(clampPlayStep("3"), 3);
  assert.equal(clampPlayStep("0"), 1);
  assert.equal(clampPlayStep("500"), 100);
  assert.equal(clampPlayStep("abc"), 1);
});

test("clampFps: 1..120, default 5 on NaN", () => {
  assert.equal(clampFps("30"), 30);
  assert.equal(clampFps("0"), 1);
  assert.equal(clampFps("999"), 120);
  assert.equal(clampFps(""), 5);
});
