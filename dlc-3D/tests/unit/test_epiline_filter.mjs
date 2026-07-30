import test from "node:test";
import assert from "node:assert/strict";
import { shouldDrawLine } from "../../src/static/internal/epiline_filter.mjs";

test("draws when the reference marker clears the threshold", () => {
  assert.equal(shouldDrawLine(0.9, 0.4), true);
  assert.equal(shouldDrawLine(0.4, 0.4), true, "the threshold itself passes");
});

test("hides a marker below the threshold", () => {
  assert.equal(shouldDrawLine(0.39, 0.4), false);
  assert.equal(shouldDrawLine(0.0, 0.4), false);
});

test("an unknown likelihood is not a confident one", () => {
  assert.equal(shouldDrawLine(null, 0.4), false);
  assert.equal(shouldDrawLine(undefined, 0.4), false);
  assert.equal(shouldDrawLine(NaN, 0.4), false);
});

test("a threshold of 0 genuinely means show everything", () => {
  assert.equal(shouldDrawLine(0, 0), true);
  assert.equal(shouldDrawLine(0.01, 0), true);
});

test("a blanked field must not make every line vanish", () => {
  // Clearing the input to retype gives NaN; falling back to 'draw' keeps the
  // overlay usable instead of silently emptying it mid-edit.
  assert.equal(shouldDrawLine(0.5, NaN), true);
  assert.equal(shouldDrawLine(0.5, undefined), true);
  assert.equal(shouldDrawLine(0.5, null), true);
});

test("an unknown likelihood stays hidden even with a blanked threshold", () => {
  assert.equal(shouldDrawLine(NaN, NaN), false);
});
