import test from "node:test";
import assert from "node:assert/strict";
import { pinnedScorerTokens, matchesPinned, pickPrimaryVariant }
  from "../../src/static/internal/pick_primary_variant.mjs";

// Real strings from the DREADD-Ali project, not invented ones.
const PIN = "dlc-models-pytorch/iteration-24/DREADDJan7-trainset70shuffle1/train/snapshot-best-150.pt";
const H5_PINNED = "/d/eggtart-1_cam0DLC_HrnetW48_DREADDJan7shuffle1_iter24_snapshot_best-150.h5";
const H5_OTHER  = "/d/eggtart-1_cam0DLC_HrnetW48_DREADDJan7shuffle1_iter25_snapshot_180.h5";
const H5_NOITER = "/d/MAP1_20250713DLC_HrnetW48_DREADDJan7shuffle1_snapshot_best-100.h5";

const latest = (vs) => (vs.length ? vs[vs.length - 1] : null);

test("tokens survive both of DLC's renames", () => {
  // iteration-24 -> iter24, and snapshot-best-150 -> snapshot_best-150.
  assert.deepEqual(pinnedScorerTokens(PIN),
                   { iter: "iter24", snap: "snapshot_best-150" });
});

test("a plain numbered snapshot keeps its stem", () => {
  assert.deepEqual(
    pinnedScorerTokens("dlc-models-pytorch/iteration-9/x/train/snapshot-180.pt"),
    { iter: "iter9", snap: "snapshot_180" });
});

test("no pin, or a non-snapshot path, yields no tokens", () => {
  for (const bad of ["", null, undefined, 42, "train/config.yaml", "x/model.pt"]) {
    assert.equal(pinnedScorerTokens(bad), null, String(bad));
  }
});

test("matches the h5 written by that snapshot", () => {
  assert.equal(matchesPinned(H5_PINNED, pinnedScorerTokens(PIN)), true);
});

test("does not match a different iteration", () => {
  // The decisive case: same project, same shuffle, different model.
  assert.equal(matchesPinned(H5_OTHER, pinnedScorerTokens(PIN)), false);
});

test("does not match the same snapshot number from another iteration", () => {
  const other = "/d/vidDLC_HrnetW48_DREADDJan7shuffle1_iter22_snapshot_best-150.h5";
  assert.equal(matchesPinned(other, pinnedScorerTokens(PIN)), false,
    "snapshot-best-150 exists in many iterations; the iter token disambiguates");
});

test("an untagged h5 does not satisfy an iteration-specific pin", () => {
  // Written before iteration tagging existed. It MIGHT be the pinned model,
  // but nothing in the name proves it, and guessing would reintroduce exactly
  // the ambiguity pinning removes.
  assert.equal(matchesPinned(H5_NOITER, pinnedScorerTokens(PIN)), false);
});

test("picks the pinned variant over the newer one", () => {
  const variants = [{ path: H5_PINNED, ts: "2026-01-01" },
                    { path: H5_OTHER,  ts: "2026-08-01" }];
  assert.equal(pickPrimaryVariant(variants, PIN, latest).path, H5_PINNED,
    "the pin must win even though the other variant is newer — that is the "
    + "whole point");
});

test("falls back to latest when the pinned model has no h5 here", () => {
  const variants = [{ path: H5_NOITER, ts: null }, { path: H5_OTHER, ts: "2026-08-01" }];
  assert.equal(pickPrimaryVariant(variants, PIN, latest).path, H5_OTHER);
});

test("falls back to latest when nothing is pinned", () => {
  const variants = [{ path: H5_PINNED, ts: "2026-01-01" }, { path: H5_OTHER, ts: "2026-08-01" }];
  for (const none of ["", null, undefined]) {
    assert.equal(pickPrimaryVariant(variants, none, latest).path, H5_OTHER);
  }
});

test("never selects a disabled variant, even when it matches the pin", () => {
  const variants = [{ path: H5_PINNED, disabled: true }, { path: H5_OTHER, ts: "2026-08-01" }];
  assert.equal(pickPrimaryVariant(variants, PIN, latest).path, H5_OTHER);
});

test("the card's own fallback is used verbatim", () => {
  // Each card has a different 'latest' rule; this must not quietly replace one.
  const sentinel = { path: "/sentinel.h5" };
  assert.equal(pickPrimaryVariant([{ path: H5_OTHER }], "", () => sentinel),
               sentinel);
});

test("empty or malformed input does not throw", () => {
  // What matters is that a ragged variant list cannot crash the overlay; what
  // comes back is the fallback's business, not this function's.
  assert.equal(pickPrimaryVariant([], PIN, latest), null);
  assert.equal(pickPrimaryVariant(null, PIN, latest), null);
  assert.doesNotThrow(() => pickPrimaryVariant([null, {}, { path: null }], PIN, latest));
  assert.doesNotThrow(() => pickPrimaryVariant([{ path: H5_PINNED }], PIN, null));
});
