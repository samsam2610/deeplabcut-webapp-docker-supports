import test from "node:test";
import assert from "node:assert/strict";
import { nextUnlabeledBodypart, cycleBodypart }
  from "../../src/static/components/viewer/internal/bodypart_cycle.mjs";

const BPS = ["Snout", "Ear", "Tail"];

test("nextUnlabeledBodypart: skips placed, advances to the next unlabeled (wrapping)", () => {
  // Snout placed, current=Snout → next unplaced is Ear.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Snout"]), "Snout", false), "Ear");
  // Snout+Ear placed, current=Ear → wrap past Tail? Tail unplaced → Tail.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Snout", "Ear"]), "Ear", false), "Tail");
  // Tail placed last, current=Tail, Snout still unplaced → wraps to Snout.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Tail"]), "Tail", false), "Snout");
});

test("nextUnlabeledBodypart: all placed → stays on current", () => {
  assert.equal(
    nextUnlabeledBodypart(BPS, new Set(["Snout", "Ear", "Tail"]), "Ear", false), "Ear");
});

test("nextUnlabeledBodypart: lock=true → stays on current (no advance)", () => {
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Snout"]), "Snout", true), "Snout");
});

test("nextUnlabeledBodypart: empty / non-array list → returns current unchanged", () => {
  assert.equal(nextUnlabeledBodypart([], new Set(), "Snout", false), "Snout");
  assert.equal(nextUnlabeledBodypart(null, new Set(), "Snout", false), "Snout");
});

test("nextUnlabeledBodypart: current not in list → scans from start", () => {
  // current unknown, nothing placed → first bp.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(), "ZZZ", false), "Snout");
});

test("cycleBodypart: forward wraps, backward wraps", () => {
  assert.equal(cycleBodypart(BPS, "Snout", 1), "Ear");
  assert.equal(cycleBodypart(BPS, "Tail", 1), "Snout");   // forward wrap
  assert.equal(cycleBodypart(BPS, "Snout", -1), "Tail");  // backward wrap
  assert.equal(cycleBodypart(BPS, "Ear", -1), "Snout");
});

test("cycleBodypart: empty list → null; current not found → first", () => {
  assert.equal(cycleBodypart([], "x", 1), null);
  assert.equal(cycleBodypart(BPS, "ZZZ", 1), "Snout");
});
