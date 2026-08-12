// Paired candidate thumbnails: 5 cam0 · gap · the same 5 from cam1.
//
// The point of the layout is that column i is ONE frame seen twice. If the two
// groups ever fall out of step the strip still looks fine — five thumbnails
// beside five thumbnails — while silently inviting you to compare a paw in cam0
// against a different moment in cam1. That is only catchable by a test.
import test from "node:test";
import assert from "node:assert/strict";

import { pairCandidates, PAIR_LIMIT } from "../../src/static/internal/candidate_pairs.mjs";

const TOP = [
  { frame: 28496, score: 0.93 },
  { frame: 28501, score: 0.91 },
  { frame: 28506, score: 0.88 },
  { frame: 28511, score: 0.84 },
  { frame: 28516, score: 0.80 },
  { frame: 28521, score: 0.77 },
];

test("five per camera by default", () => {
  const { cam0, cam1 } = pairCandidates(TOP);
  assert.equal(cam0.length, PAIR_LIMIT);
  assert.equal(cam1.length, PAIR_LIMIT);
  assert.equal(PAIR_LIMIT, 5);
});

test("column i is the same frame in both cameras", () => {
  const { cam0, cam1 } = pairCandidates(TOP);
  cam0.forEach((c, i) => assert.equal(c.frame, cam1[i].frame));
});

test("the groups keep the incoming ranking", () => {
  const { cam0 } = pairCandidates(TOP);
  assert.deepEqual(cam0.map((c) => c.frame), [28496, 28501, 28506, 28511, 28516]);
});

test("each entry knows which camera it is", () => {
  // The thumbnail URL needs it: the crop is anchored on that camera's pellet.
  const { cam0, cam1 } = pairCandidates(TOP);
  assert.ok(cam0.every((c) => c.cam === "cam0"));
  assert.ok(cam1.every((c) => c.cam === "cam1"));
});

test("only the top-ranked entry is flagged best", () => {
  const { cam0, cam1 } = pairCandidates(TOP);
  assert.equal(cam0[0].best, true);
  assert.equal(cam1[0].best, true, "the same frame is best in both views");
  assert.equal(cam0.slice(1).some((c) => c.best), false);
});

test("fewer than five candidates does not pad", () => {
  const { cam0, cam1 } = pairCandidates(TOP.slice(0, 2));
  assert.equal(cam0.length, 2);
  assert.equal(cam1.length, 2);
});

test("no candidates gives two empty groups, not an error", () => {
  const { cam0, cam1 } = pairCandidates([]);
  assert.deepEqual(cam0, []);
  assert.deepEqual(cam1, []);
  assert.deepEqual(pairCandidates(undefined).cam0, []);
});

test("a candidate with no frame is dropped rather than rendered blank", () => {
  const { cam0, cam1 } = pairCandidates([{ score: 0.9 }, TOP[0]]);
  assert.equal(cam0.length, 1);
  assert.equal(cam0[0].frame, 28496);
  assert.equal(cam1.length, 1, "dropping must not desynchronise the columns");
});

test("the score travels with both halves of the pair", () => {
  const { cam0, cam1 } = pairCandidates(TOP);
  assert.equal(cam0[2].score, cam1[2].score);
  assert.equal(cam0[2].score, 0.88);
});

test("the limit is respected when more are offered", () => {
  const many = Array.from({ length: 40 }, (_, i) => ({ frame: i, score: 1 - i / 40 }));
  const { cam0, cam1 } = pairCandidates(many);
  assert.equal(cam0.length, 5);
  assert.equal(cam1.length, 5);
});

test("an explicit limit overrides the default", () => {
  const { cam0, cam1 } = pairCandidates(TOP, 3);
  assert.equal(cam0.length, 3);
  assert.equal(cam1.length, 3);
});
