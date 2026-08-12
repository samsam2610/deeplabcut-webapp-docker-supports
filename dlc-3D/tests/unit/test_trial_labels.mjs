import test from "node:test";
import assert from "node:assert/strict";
import {
  trialLabel, defaultOutcome, tagNote, writableTrials,
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
