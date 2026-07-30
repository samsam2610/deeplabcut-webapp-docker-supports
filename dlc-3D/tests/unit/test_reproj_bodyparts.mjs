import test from "node:test";
import assert from "node:assert/strict";
import { activeBodyparts } from "../../src/static/internal/reproj_bodyparts.mjs";

test("prefers the bp-chips: available as soon as markers are shown", () => {
  const got = activeBodyparts({
    chipNames: ["Snout", "Wrist"], knownBodyparts: ["X"], auditBodyparts: ["Y"],
  });
  assert.deepEqual(got, ["Snout", "Wrist"]);
});

test("falls back to the Estimate list when no chips exist yet", () => {
  const got = activeBodyparts({
    chipNames: [], knownBodyparts: ["Snout"], auditBodyparts: ["Y"],
  });
  assert.deepEqual(got, ["Snout"]);
});

test("falls back to the audit only as a last resort", () => {
  const got = activeBodyparts({
    chipNames: [], knownBodyparts: [], auditBodyparts: ["Pellet"],
  });
  assert.deepEqual(got, ["Pellet"]);
});

test("REGRESSION: lines must not require a Run first", () => {
  // The old code read markerEditor.posedBodyparts (which does not exist) and
  // then _reprojAudit (set only by Run), so with markers on screen but no Run
  // clicked it returned [] and NOTHING was ever drawn.
  const got = activeBodyparts({
    chipNames: ["Snout", "Wrist", "Pellet"],
    knownBodyparts: [], auditBodyparts: [],   // no Estimate, no Run
  });
  assert.equal(got.length, 3, "chips alone must be enough to draw lines");
});

test("returns an empty list when nothing is known, without throwing", () => {
  assert.deepEqual(activeBodyparts({}), []);
  assert.deepEqual(
    activeBodyparts({ chipNames: null, knownBodyparts: null, auditBodyparts: null }), []);
});
