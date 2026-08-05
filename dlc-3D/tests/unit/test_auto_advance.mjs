// Executable model of _flAutoAdvanceBp's selection rule.
//
// The real function lives inside frame_labeler_3d.js's DOM-bound IIFE and
// cannot be imported, so this mirrors its logic exactly and pins the property
// that broke: the advance must be computed against the frame that was just
// LABELLED, not against whichever tile happens to hold focus.
//
// Why that mattered (2026-08-05): a canvas click fires in the target phase,
// but the row handler that moves focus to the clicked tile runs afterwards on
// the bubble. Clicking the non-focused camera therefore wrote the label to
// that camera while the advance was computed against the other one. With cam0
// fully labelled, the search found nothing missing there and never advanced.
import test from "node:test";
import assert from "node:assert/strict";

/** Mirrors _flAutoAdvanceBp: next bodypart with no label on `fname`. */
function nextBp(bodyparts, selected, labelsByFrame, fname, locked = false) {
  if (locked) return selected;
  const frameLabels = labelsByFrame[fname] || {};
  const cur = bodyparts.indexOf(selected);
  for (let i = 1; i <= bodyparts.length; i++) {
    const next = bodyparts[(cur + i) % bodyparts.length];
    if (!frameLabels[next]) return next;
  }
  return selected;
}

const BPS = ["wrist", "elbow", "paw"];

test("advances to the next unlabelled bodypart on the labelled frame", () => {
  const labels = { "cam1.png": { wrist: [1, 2] } };
  assert.equal(nextBp(BPS, "wrist", labels, "cam1.png"), "elbow");
});

test("THE BUG: judging against the other camera stalls the advance", () => {
  // cam0 fully labelled (the user finished it), cam1 just got its first point.
  const labels = {
    "cam0.png": { wrist: [0, 0], elbow: [0, 0], paw: [0, 0] },
    "cam1.png": { wrist: [1, 2] },
  };
  // Correct: judge on the frame just labelled -> advances.
  assert.equal(nextBp(BPS, "wrist", labels, "cam1.png"), "elbow");
  // Broken: judge on the focused (other) frame -> nothing missing, no advance.
  assert.equal(nextBp(BPS, "wrist", labels, "cam0.png"), "wrist",
    "this is what the focused-tile lookup did, and why it never advanced");
});

test("skips bodyparts already labelled on that frame", () => {
  const labels = { "f.png": { wrist: [1, 1], elbow: [2, 2] } };
  assert.equal(nextBp(BPS, "wrist", labels, "f.png"), "paw");
});

test("wraps around the list", () => {
  const labels = { "f.png": { paw: [1, 1] } };
  assert.equal(nextBp(BPS, "paw", labels, "f.png"), "wrist");
});

test("stays put when the frame is fully labelled", () => {
  const labels = { "f.png": { wrist: [1, 1], elbow: [2, 2], paw: [3, 3] } };
  assert.equal(nextBp(BPS, "wrist", labels, "f.png"), "wrist");
});

test("lock (L) pins the selection", () => {
  const labels = { "f.png": { wrist: [1, 1] } };
  assert.equal(nextBp(BPS, "wrist", labels, "f.png", true), "wrist");
});

test("an unknown frame advances rather than stalling", () => {
  assert.equal(nextBp(BPS, "wrist", {}, "never-seen.png"), "elbow");
});
