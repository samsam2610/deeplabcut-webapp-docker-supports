import test from "node:test";
import assert from "node:assert/strict";
import {
  trialLabel, defaultOutcome, tagNote, writableTrials, candidateStrips,
} from "../../src/static/internal/trial_labels.mjs";

const base = {
  index: 7, marker: 24454, start: 22923, end: 24454, outcome: "f",
  n_candidates: 121, onset: null, result: null, tag: null,
};

test("an untagged, unscored trial reads plainly", () => {
  const s = trialLabel(base, 7);
  assert.ok(s.startsWith("#8  f  [22923–24454]  121 cand  orphan"));
  assert.ok(!s.includes("✓") && !s.includes("~"));
});

test("a human tag is marked and its frame shown", () => {
  const s = trialLabel({ ...base, tag: { kind: "human", note: "start-failure", frame: 24041 } }, 7);
  assert.ok(s.includes("✓ start-failure @24041"));
});

test("our own candidate is marked differently from a human tag", () => {
  const s = trialLabel({ ...base, tag: { kind: "candidate", note: "start-failure-candidate", frame: 24045 } }, 7);
  assert.ok(s.includes("~ start-failure-candidate @24045"));
  assert.ok(!s.includes("✓"), "a candidate must not read as a human tag");
});

test("a stored result shows its pick", () => {
  const s = trialLabel({ ...base, result: { pick: 24045, stale: false } }, 7);
  assert.ok(s.includes("pick 24045"));
  assert.ok(!s.includes("stale"));
});

test("a result scored under different parameters is flagged stale", () => {
  const s = trialLabel({ ...base, result: { pick: 24045, stale: true } }, 7);
  assert.ok(s.includes("(stale)"));
});

test("a human onset tag shows as the truth column", () => {
  assert.ok(trialLabel({ ...base, onset: 24041 }, 7).includes("tag 24041"));
});

// ── the Add control ─────────────────────────────────────────────────────────

test("the default outcome comes from the trial's marker", () => {
  assert.equal(defaultOutcome({ outcome: "f" }), "f");
  assert.equal(defaultOutcome({ outcome: "s" }), "s");
});

test("an unknown outcome falls back to success rather than throwing", () => {
  assert.equal(defaultOutcome({}), "s");
  assert.equal(defaultOutcome(null), "s");
});

test("the written note is the REAL tag, not a candidate", () => {
  // A human approved this frame on screen, so it carries the same weight as a
  // hand-placed tag — including as a future exemplar.
  assert.equal(tagNote("s"), "start-success");
  assert.equal(tagNote("f"), "start-failure");
  assert.ok(!tagNote("s").endsWith("-candidate"));
});

// ── what a batch write would touch ──────────────────────────────────────────

const scored = (over) => ({ ...base, result: { pick: 1, stale: false }, ...over });

test("only trials with a stored result are writable", () => {
  assert.equal(writableTrials([base, scored({})]).length, 1);
});

test("human-tagged trials are skipped by default", () => {
  const list = [scored({ tag: { kind: "human", note: "start-failure", frame: 9 } }),
                scored({})];
  assert.equal(writableTrials(list).length, 1);
});

test("include-tagged brings them back, for measuring agreement", () => {
  const list = [scored({ tag: { kind: "human", note: "start-failure", frame: 9 } }),
                scored({})];
  assert.equal(writableTrials(list, true).length, 2);
});

test("a trial already carrying OUR candidate is still writable", () => {
  // Re-running a batch should be able to update its own proposal.
  const list = [scored({ tag: { kind: "candidate", note: "start-failure-candidate", frame: 9 } })];
  assert.equal(writableTrials(list).length, 1);
});

test("an empty list is not an error", () => {
  assert.deepEqual(writableTrials([]), []);
  assert.deepEqual(writableTrials(undefined), []);
});

// ── what the thumbnail strips show when you browse ──────────────────────────
//
// Reported after the first batch: the candidate frames and their segmentations
// did not update when switching trials. Two causes — the batch stored only the
// pick, and the trial-change handler cleared the 2D strip but not the 3D one,
// so the previous trial's paired thumbnails stayed on screen.

test("changing trial always clears both strips", () => {
  // Not "clear if there is something new to draw": a trial with no result must
  // not inherit the last one's thumbnails.
  assert.equal(candidateStrips(null).clear, true);
  assert.equal(candidateStrips({ result: null }).clear, true);
  assert.equal(candidateStrips({ result: { mode: "3d", top: [1] } }).clear, true);
});

test("a trial with no stored result renders nothing", () => {
  const plan = candidateStrips({ result: null });
  assert.equal(plan.render, null);
  assert.deepEqual(plan.top, []);
});

test("a stored 3D result renders the paired strip", () => {
  const plan = candidateStrips({ result: { mode: "3d", top: [24045, 24046] } });
  assert.equal(plan.render, "pairs");
  assert.deepEqual(plan.top, [24045, 24046]);
});

test("a stored 2D result renders the single strip", () => {
  assert.equal(candidateStrips({ result: { mode: "2d", top: [1, 2] } }).render, "single");
});

test("a result with an empty ranking renders nothing", () => {
  // A batch row written before the ranking was stored; better blank than the
  // previous trial's frames.
  assert.equal(candidateStrips({ result: { mode: "3d", top: [] } }).render, null);
});

test("the stored order is preserved, not sorted", () => {
  const plan = candidateStrips({ result: { mode: "3d", top: [24046, 24041, 24045] } });
  assert.deepEqual(plan.top, [24046, 24041, 24045]);
});

// A result stored before the ranking column existed has a pick but no top. The
// pick's own frame IS knowable, so show that rather than nothing — and say the
// ranking is missing rather than implying one thumbnail was the whole result.

test("a result with a pick but no ranking shows the pick alone", () => {
  const plan = candidateStrips({ result: { mode: "3d", pick: 24045, top: [] } });
  assert.equal(plan.render, "pairs");
  assert.deepEqual(plan.top, [24045]);
  assert.equal(plan.partial, true);
});

test("a full ranking is not marked partial", () => {
  const plan = candidateStrips({ result: { mode: "3d", pick: 24045, top: [24045, 24046] } });
  assert.equal(plan.partial, false);
  assert.deepEqual(plan.top, [24045, 24046]);
});

test("no pick and no ranking still renders nothing", () => {
  assert.equal(candidateStrips({ result: { mode: "3d", top: [] } }).render, null);
});
