// Human markers on the trial strip, and the judging-parameter fields.
//
// Why these exist (2026-08-12): trial #11 of banh-mi-1 Jul 7 was a FAILED reach
// labelled start-success. Its window [25915, 28915] closed on an `s` at 28915
// while an `f` sat at 27536, inside the window. The strip drew only the human
// `start-*` tag — of which that video has none — so the `f` that proved the
// label wrong was never on screen.
//
// The clamp is mirrored from src/judging.py. If the two ever disagree the panel
// shows a value the backend will not honour, which is worse than no field.
import test from "node:test";
import assert from "node:assert/strict";

import {
  clampJudge,
  DEFAULT_JUDGE,
  markersInSpan,
  intervening,
  markerStyle,
  isHumanMarker,
} from "../../src/static/internal/trial_judge.mjs";

// ── markers on the strip ────────────────────────────────────────────────────

// The real numbers from the report.
const JUL7 = [
  { frame: 25847, note: "s" },
  { frame: 27536, note: "f" },
  { frame: 28915, note: "s" },
  { frame: 30371, note: "s" },
];

test("the marker that closes the window is in the span", () => {
  const got = markersInSpan(JUL7, 27537, 28915);
  assert.deepEqual(got.map((m) => m.frame), [28915]);
});

test("neighbouring trials' markers are not drawn", () => {
  const got = markersInSpan(JUL7, 27537, 28915);
  assert.equal(got.some((m) => m.frame === 27536), false);
  assert.equal(got.some((m) => m.frame === 30371), false);
});

test("the unclipped window shows the f that made the label wrong", () => {
  // The pre-fix span. Drawing this would have made the bug visible on sight.
  const got = markersInSpan(JUL7, 25915, 28915);
  assert.deepEqual(got.map((m) => m.note), ["f", "s"]);
});

test("intervening returns markers strictly inside the span", () => {
  assert.deepEqual(intervening(JUL7, 25915, 28915).map((m) => m.frame), [27536]);
});

test("a correctly clipped window has no intervening marker", () => {
  assert.deepEqual(intervening(JUL7, 27537, 28915), []);
});

test("the closing marker is never counted as intervening", () => {
  // Otherwise every window would warn about itself.
  assert.deepEqual(intervening([{ frame: 100, note: "s" }], 1, 100), []);
});

test("an empty marker list is not an error", () => {
  assert.deepEqual(markersInSpan([], 1, 100), []);
  assert.deepEqual(markersInSpan(undefined, 1, 100), []);
  assert.deepEqual(intervening(null, 1, 100), []);
});

test("markers come back in frame order however they arrive", () => {
  const shuffled = [JUL7[2], JUL7[0], JUL7[1]];
  assert.deepEqual(markersInSpan(shuffled, 25000, 29000).map((m) => m.frame),
                   [25847, 27536, 28915]);
});

// ── which notes are human ───────────────────────────────────────────────────

test("s and f are human markers", () => {
  assert.equal(isHumanMarker("s"), true);
  assert.equal(isHumanMarker("f"), true);
});

test("start tags are human markers", () => {
  assert.equal(isHumanMarker("start-success"), true);
  assert.equal(isHumanMarker("start-failure"), true);
});

test("our own proposals are not human markers", () => {
  // Drawing a proposal in the human colour would make the tool look like it
  // agreed with a human who never keyed anything.
  assert.equal(isHumanMarker("start-success-candidate"), false);
  assert.equal(isHumanMarker("start-failure-candidate"), false);
});

test("outcome markers are styled by outcome, not by position", () => {
  assert.notEqual(markerStyle("s").colour, markerStyle("f").colour);
  assert.equal(markerStyle("s").label, "s");
});

// ── judging parameters ──────────────────────────────────────────────────────

test("the defaults match the backend's", () => {
  // Mirrored from judging.Judge(). This assertion is the whole point of the
  // mirror: it fails the moment one side is retuned without the other.
  assert.deepEqual(DEFAULT_JUDGE, {
    threshold: 0.55, min_run: 6, lookback: 3000, min_candidates: 30, guard: 0,
    max_3d_dist: 2.0, max_epi_px: 20.0,
  });
});

test("out-of-range values clamp exactly as Python does", () => {
  assert.equal(clampJudge({ threshold: -1 }).threshold, 0);
  assert.equal(clampJudge({ threshold: 4 }).threshold, 1);
  assert.equal(clampJudge({ min_run: 0 }).min_run, 1);
  assert.equal(clampJudge({ min_run: -5 }).min_run, 1);
  assert.equal(clampJudge({ lookback: 0 }).lookback, 1);
  assert.equal(clampJudge({ min_candidates: -3 }).min_candidates, 0);
  assert.equal(clampJudge({ guard: -10 }).guard, 0);
});

test("guard is capped at the lookback", () => {
  assert.equal(clampJudge({ lookback: 1000, guard: 5000 }).guard, 1000);
});

test("a blank field falls back to the default, not NaN", () => {
  // An <input type=number> that the user cleared reads as "".
  const j = clampJudge({ threshold: "", min_run: null, lookback: undefined });
  assert.equal(j.threshold, DEFAULT_JUDGE.threshold);
  assert.equal(j.min_run, DEFAULT_JUDGE.min_run);
  assert.equal(j.lookback, DEFAULT_JUDGE.lookback);
});

test("numeric strings are accepted because inputs return strings", () => {
  const j = clampJudge({ threshold: "0.62", min_run: "9" });
  assert.equal(j.threshold, 0.62);
  assert.equal(j.min_run, 9);
});

test("a non-numeric value keeps the default", () => {
  assert.equal(clampJudge({ lookback: "soon" }).lookback, DEFAULT_JUDGE.lookback);
});

test("integer fields never come back fractional", () => {
  // 6.7 samples of debounce is not a thing; the backend would int() it and the
  // two sides must agree on the result.
  const j = clampJudge({ min_run: 6.7, lookback: 2999.5, guard: 10.2 });
  assert.equal(j.min_run, 6);
  assert.equal(j.lookback, 2999);
  assert.equal(j.guard, 10);
});

test("clamping is idempotent", () => {
  const once = clampJudge({ threshold: 9, guard: -4 });
  assert.deepEqual(clampJudge(once), once);
});

// ── the 3D gate joins the judge ─────────────────────────────────────────────
//
// `threshold` and `max_3d_dist` were on the pellet model, edited in a different
// panel section, while the judge owned everything else that decides a
// candidate. Two places deciding one thing.

test("max_3d_dist is part of the judge", () => {
  assert.equal(DEFAULT_JUDGE.max_3d_dist, 2.0);
});

test("the default threshold is the two-camera one", () => {
  // 0.55, not the single-camera path's 0.50: with two cameras and a 3D gate
  // behind it this no longer has to be the only defence.
  assert.equal(DEFAULT_JUDGE.threshold, 0.55);
});

test("max_3d_dist clamps at zero and accepts fractions", () => {
  assert.equal(clampJudge({ max_3d_dist: -1 }).max_3d_dist, 0);
  assert.equal(clampJudge({ max_3d_dist: "1.5" }).max_3d_dist, 1.5);
  assert.equal(clampJudge({ max_3d_dist: "" }).max_3d_dist, DEFAULT_JUDGE.max_3d_dist);
});

test("max_3d_dist is not truncated to an integer", () => {
  // It is a distance in calibration units; real pellets measured <= 1.03, so
  // rounding to whole numbers would make the gate untunable.
  assert.equal(clampJudge({ max_3d_dist: 2.5 }).max_3d_dist, 2.5);
});

test("the epipolar tolerance is measured, not guessed", () => {
  // 20 px, from SAM mask centroids on 55 frames where both views verifiably
  // picked the correct paw, under that session's own calibration (p95 17.8).
  // Measured on the real quantity after two stand-ins gave the wrong answer.
  assert.equal(DEFAULT_JUDGE.max_epi_px, 20.0);
});

test("the epipolar tolerance clamps at zero and keeps fractions", () => {
  assert.equal(clampJudge({ max_epi_px: -4 }).max_epi_px, 0);
  assert.equal(clampJudge({ max_epi_px: "12.5" }).max_epi_px, 12.5);
  assert.equal(clampJudge({ max_epi_px: "" }).max_epi_px, DEFAULT_JUDGE.max_epi_px);
});
