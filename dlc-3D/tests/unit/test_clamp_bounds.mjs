import test from "node:test";
import assert from "node:assert/strict";
import { clampToBounds } from "../../src/static/internal/clamp_bounds.mjs";

test("clampToBounds: returns the frame unchanged when inside [start,end]", () => {
  assert.equal(clampToBounds(1200, 1034, 1833), 1200);
  assert.equal(clampToBounds(1034, 1034, 1833), 1034);   // inclusive low edge
  assert.equal(clampToBounds(1833, 1034, 1833), 1833);   // inclusive high edge
});

test("clampToBounds: clamps below start up to start, above end down to end", () => {
  assert.equal(clampToBounds(500, 1034, 1833), 1034);
  assert.equal(clampToBounds(9000, 1034, 1833), 1833);
});

test("clampToBounds: floors fractional frames and coerces NaN to start", () => {
  assert.equal(clampToBounds(1200.7, 1034, 1833), 1200);
  assert.equal(clampToBounds(NaN, 1034, 1833), 1034);
});

test("clampToBounds: tolerates reversed bounds (start>end) by normalizing", () => {
  assert.equal(clampToBounds(1200, 1833, 1034), 1200);
  assert.equal(clampToBounds(500, 1833, 1034), 1034);
});
