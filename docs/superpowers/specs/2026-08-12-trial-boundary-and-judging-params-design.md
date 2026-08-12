# Trial boundaries, human markers, and adjustable judging — design

**Date:** 2026-08-12
**Card:** `3D Inline Analysis - SAM Model`
**Reported:** trial #11 of banh-mi-1 2026-07-07 is a failed attempt — an `f` marker
follows it — but the panel labelled it a success.

## 1. The label bug

`build_windows` opens a window at `marker - MAX_LOOKBACK` (3000 frames) and closes
it at the outcome marker. Nothing clips the opening at the *previous* marker.

Trial #11 spans `[25915, 28915]` with outcome `s`. The previous marker — `f` at
**27536** — sits inside it, and four of its eight armed stretches (26030–27370)
lie before that `f`. A candidate picked there is a failed reach, labelled
`start-success-candidate` from a marker 1379 frames further on.

This is not an edge case. Across the ten tag-done sessions:

| | value |
|---|---|
| windows reaching back past the previous marker | **1215 / 1309 (92.8 %)** |
| candidate frames on the wrong side of a marker (Jul 7) | **64592 / 161398 (40.0 %)** |
| windows on Jul 7 holding another trial's candidates | 120 / 131 |

The invariant the design already claims — *"the window exists only because an
outcome marker follows it"* — is false whenever a nearer marker follows first.

### Fix

Clip the opening at the previous outcome marker:

```
start = max(0, marker - lookback, prev_marker + 1 - guard)
```

`guard` (default **0**) is how far a window may reach back past the previous
marker. At 0 the invariant holds by construction: for every frame in a window,
the window's own marker is the next marker.

**Cost, measured:** onset reachability falls from 100 % to **98.77 %** (16 of
1304 paired trials). Those are trials where the human keyed the previous
marker *after* the next reach had already begun — the onset genuinely sits
behind an intervening marker, and no consistent rule can attribute it to the
later one. `guard` exists so this is tunable rather than my decision.

**Benefit beyond correctness:** mean window span falls 3001 → 1750 frames, so
stage 2 embeds roughly half as many frames.

## 2. The missing human marker line

The trial strip draws only `A.onset` — the human `start-success`/`start-failure`
tag. banh-mi-1 Jul 7 is a *tag-pending* video: **131 `s`/`f` markers, zero start
tags**. So nothing was ever drawn, and the `f` at 27536 — the very evidence that
the label was wrong — was invisible.

The whole-video timeline has the same hole from a different cause:
`api_onset_csv` writes `notes.onsets(...)` into the sidecar's `note` column and
never `notes.outcomes(...)`. On a tag-pending video that column is empty.

### Fix

* the sidecar records outcome markers as well as onset tags
* `/windows` returns the human markers, and the strip draws every one falling in
  the span: the closing marker labelled at the right edge, any *intervening*
  marker in a warning colour, because with `guard > 0` it means the trial is
  ambiguous

## 3. Adjustable judging parameters

Five constants decide what counts as a candidate. All were tuned once and
compiled in. They become a per-project `sam_training_judge.json`:

| field | default | effect |
|---|---|---|
| `threshold` | 0.50 | NCC above which the pellet is present |
| `min_run` | 6 | samples a state flip must persist (debounce) |
| `lookback` | 3000 | how far a window reaches back |
| `min_candidates` | 30 | armed frames below which a trial is skipped |
| `guard` | 0 | frames a window may reach past the previous marker |

**These deliberately do not enter the sweep cache key.** The sweep produces raw
NCC per frame; all five are applied to that trace afterwards. Re-judging is
instant, and tuning a threshold must never trigger a four-minute re-sweep.

Out-of-range values are clamped rather than rejected — the same clamp on both
sides, so the panel cannot show a value the backend will not honour.

## 4. Regression found while reading

`api_onset_csv` calls `store.load_sweep(video, SWEEP_STRIDE)` with **no `sig=`**.
Since the cache key gained a signature yesterday, that call can never hit:
"Build onset CSV" answers 409 "not swept yet" on a video that has just been
swept. Fixed here.

## Tests

Python (`sam-training/tests/`):
1. a window never opens at or before the previous marker (`guard=0`)
2. `guard=n` reaches exactly `n` frames past it
3. the first trial has no previous marker and keeps the full lookback
4. a window clipped to nothing is dropped, not emitted empty
5. clipping is unaffected by the order trials arrive in
6. **regression, from real numbers:** a `[25915, 28915]` `s` window with an `f`
   at 27536 no longer contains any frame before 27537
7. judge round-trips through JSON; out-of-range values clamp identically
8. the sidecar's `note` column carries `s`/`f` markers, not only start tags
9. `api_onset_csv` finds a sweep saved with a signature

JavaScript (`dlc-3D/tests/unit/test_trial_judge.mjs`), pure functions in
`internal/trial_judge.mjs`:
10. `markersInSpan` includes the closing marker and excludes neighbours
11. `intervening` returns markers strictly inside the span — empty at `guard=0`
12. `clampJudge` matches the Python clamp for every out-of-range field
13. a blank field falls back to the default rather than `NaN`

## Out of scope

Retuning the defaults. `guard=0` changes which frames are searchable, so the
acceptance figures must be re-measured — but that is a measurement run, not part
of this change.
