# Heatmap peak screen for epipolar rescues

**Date:** 2026-07-30
**Status:** design approved, not yet implemented
**Module:** `dlc-3D` (plus two additive files in the main webapp)
**Builds on:** [2026-07-30-candidate-peak-correction-design.md](2026-07-30-candidate-peak-correction-design.md)

## Problem

The reprojection engine rescues a low-confidence marker when it lies on the
epipolar line induced by the trusted camera. When the bodypart is occluded, that
reasoning fails: DeepLabCut had no image evidence, so its marker is a guess, and
the epipolar line — a one-degree-of-freedom constraint — endorses any guess that
lands in the band.

The candidate-peak spec established the fix: keep DeepLabCut's top-K heatmap
peaks and ask whether the *image* supports the part being on the line. Phase 1
built and verified peak extraction. What is missing is a way to get peaks out of
the normal workflow, and a rule that uses them.

Phase 2's measurement also constrains what that rule may do. Correcting a marker
to a different peak improved the badly-tracked session (23.57 → 17.27 px median
distance to the human label) but degraded both sessions where DeepLabCut was
already accurate (8.42 → 10.33 px and 4.45 → 7.38 px). Moving markers is
therefore out of scope here.

## Scope

1. Peak emission integrated into **Analyze-for-tag** on the reprojection card.
2. A **veto-only** screen that can refuse a rescue but never move a marker.

### Non-goals

- **Moving any marker.** `CORRECTED` remains a reported verdict; the applier
  refuses it. This is deliberate, and the measurement above is the reason.
- **Screening `CONFIRM` or `REJECT`.** Vetoing a confident marker on heatmap
  evidence is a different feature with a different risk profile.
- **Storing heatmaps.** Only the top-K peaks are kept. A full heatmap is ~3.9 MB
  per frame per camera (16 bodyparts × 400×304 cells); a 2000-frame tag run
  would be ~7.8 GB. Peaks are ~2 MB for the same run.
- **Changing `_run_range`.** See below.

## Architecture

Nothing in the existing analysis path changes. Peak emission is a second,
additive GPU pass fired by the reprojection card after both cameras finish.

```
_onAnalyzeTagClick()                     [reprojection card]
  ├→ POST /dlc/project/inline-analysis/range  × ranges × 2 cams  → pose h5
  └→ await all polls
     └→ if "Emit peaks" is ticked:
        POST /dlc/project/inline-analysis/peaks
             { video_paths: [cam0, cam1], ranges: [{start, n}, …],
               snapshot_path, k, min_distance }
             └→ tasks.dlc_emit_peaks — one model load, both cams, all ranges
                → <stem><scorer>_peaks.h5 beside each pose h5
```

### Why a second pass rather than a flag on the first

`_run_range` (`deeplabcut-webapp-docker/src/dlc/tasks.py:3022`) is the function
the **production** "3D Inline Analysis" card runs on every analysis. Keeping the
heatmap there means swapping the predictor inside the shared warm runner. A
regression would break work in progress.

The second pass costs one extra model forward over the same frames. Phase 1
measured peak extraction at 42 fps on the RTX 5090, so a 2000-frame tag run adds
roughly 50 seconds. That is the price of leaving the production path bit-identical.

The pass runs after both cameras finish, so it never contends with the warm
session for the GPU.

### Why the main worker

`dlc-3d-worker` has torch and Lightning Pose but not `deeplabcut`, and is pinned
to GPU 1 (the LLM card). The DLC package, the model, and GPU 0 all live in
`deeplabcut-webapp-docker-worker-1`. Installing `deeplabcut` beside Lightning
Pose to honour the self-containment rule would risk a version conflict in a
working training container.

This is a **third** change to the main webapp, against CLAUDE.md's "exactly two
things" rule. It is additive — one new route, one new task, no edits to existing
functions — but the deviation is real and is recorded here rather than glossed.

### The inference pipeline is a port, not a rewrite

`scripts/emit_peaks.py` already contains the verified pipeline, measured at
**0.344 px median / 0.975 px p95** against the existing pose h5 on confident
markers. Every element was established empirically after an earlier draft was
wrong on all five:

- **native** resolution padded to a multiple of 32 — never resized to 448×448
  (resizing gave 427 px median error)
- ImageNet mean/std normalisation after `/255` (plain `/255` gave 186 px)
- output is nested: `out["bodypart"]["heatmap"]`, not `out["heatmap"]`
- stride is exactly `2.0` — deriving it as `net_width/heatmap_width` (1.995)
  drifts ~2 px at the frame edge
- locref sub-pixel refinement is required (1.116 px without it)

The task moves this code into the worker package. **It must not be re-derived.**

## Sidecar format

`<stem><scorer>_peaks.h5`, written beside the pose h5.

| dataset | dtype | shape | meaning |
|---|---|---|---|
| `frames` | int32 | (N,) | absolute video frame numbers, sorted ascending, unique |
| `xy` | float32 | (N, B, K, 2) | peak position in original video pixels, NaN-padded |
| `score` | float32 | (N, B, K) | heatmap score at the peak, 0-padded |

Root attrs: `bodyparts` (list of str, length B), `k`, `min_distance`,
`snapshot`, `stride`, `locref_std`.

Along K, **index 0 is DeepLabCut's own argmax** — the marker already present in
the pose h5. Peaks are ordered by descending score, so this holds by construction.

### Sparse, unlike the pose h5

The pose h5 is dense (one row per video frame) because downstream tools index it
positionally. The sidecar has no such consumer, and tag runs are sparse: dense
over 251,640 frames would be 241 MB of mostly-NaN, while sparse over a
2000-frame run is about 2 MB.

Re-running merges: frames are unioned, and frames present in both are taken from
the new run. A sidecar whose `bodyparts` attr disagrees with the incoming run is
an error, not a merge — silently mixing two models' peaks would be worse than
failing.

## The screen

`peak_verdict.py` is unchanged. Veto-only lives in a new applier that consumes
its verdicts:

```
for each cell the geometry engine marked RESCUE:
    no peak row for this frame     → leave RESCUE, count as uncovered
    peak_verdict RESCUE            → keep RESCUE
    peak_verdict AMBIGUOUS         → refuse
    peak_verdict NO_EVIDENCE       → refuse
    peak_verdict CORRECTED         → refuse
```

A refused cell keeps the verdict `peak_verdict` returned, so the audit can
distinguish "nothing on the line" from "several things on the line" from "the
wrong thing on the line". Marker positions are never written.

Peak-to-line distance reuses `epipolar_core.epipolar_distance` and
`undistort_to_pixels`: peaks are in the same raw distorted pixel space as the
pose h5, so no new geometry is introduced.

Retaining `CORRECTED` as a reported-but-refused verdict means enabling
correction later is one line in the applier plus a checkbox — no GPU re-run.

### What the screen adds over `rescue_floor`

When the argmax itself lies on the line, the only veto available is
`score_floor`, which is what the existing `rescue_floor` parameter already does.
The genuinely new capability is the multi-peak cases. On the Phase 2 validation
run, of 15,191 judged cells:

| verdict | count | geometry alone could reach it? |
|---|---|---|
| RESCUE | 7,547 | yes |
| AMBIGUOUS | 4,031 | **no** |
| NO_EVIDENCE | 2,585 | partly (some are geometry REJECTs already) |
| CORRECTED | 1,028 | **no** |

The 5,059 AMBIGUOUS and CORRECTED cells — 33% of judged cells — are refusals
geometry cannot make at any threshold.

### Missing peaks do not mean refusal

A cell with no sidecar row is left to geometry. The alternative — treating
absence as no-evidence — would void every rescue on every analysis run before
this feature existed. Coverage is reported instead of assumed.

## UI

On the reprojection card:

- **`[x] Emit peaks`** beside Analyze-for-tag, default **on**. When ticked, the
  peaks pass fires automatically once both cameras finish.
- **`[ ] Require peak evidence`** in the reprojection parameters panel, default
  **off**. Disabled with a stated reason when no sidecar covers the loaded video.
- **`Peak score floor`** number field, `min=0 max=1 step=0.01`, default **0.05**.

All three persist in the existing `reproj_params` blob and carry `data-help`
entries, which the existing cross-file guard test already enforces.

`k` and `min_distance` are **not** exposed. The card sends the Phase 1 verified
values, `k=5` and `min_distance=3`, and the route defaults to them when absent.
They are extraction parameters, not judgement parameters, and adding two more
fields to a panel that already carries twelve buys nothing.

The audit gains a coverage line, for example:

> peak screen: 1,842/2,000 cells covered; 511 rescues refused (312 ambiguous,
> 199 no evidence)

Refusing rescues makes the marker count go **down** relative to a geometry-only
run. That is the feature working, and the audit line is what distinguishes it
from a fault. This project has twice diagnosed a working change as a break
because output got sparser.

## Error handling

- **Peaks task fails** — analyze-for-tag has already succeeded and written the
  pose h5; the failure is surfaced in the status line and the sidecar is simply
  absent. Analysis results are never rolled back for a peaks failure.
- **Partial sidecar** — the task writes atomically per video after all ranges
  complete, so a crash leaves the previous sidecar intact rather than a truncated one.
- **Bodypart mismatch on merge** — hard error, no write.
- **Screen enabled with no sidecar** — the checkbox is disabled, so this state is
  not reachable from the UI; the engine additionally treats it as full
  non-coverage rather than raising.
- **Path containment** — the new route validates through the same
  `_sec_check` / data-root rule as `/inline-analysis/range`.

## Testing

Following the existing pure-core split, so most of this runs on the host with
neither torch nor DeepLabCut installed.

**Pure (pytest, numpy only)**
- the applier: each downgrade path, the keep-RESCUE path, the uncovered
  passthrough, and that no marker position is ever written
- sidecar write → read round-trip; merge with overlapping and disjoint frames;
  bodypart-mismatch raises
- peak-to-line distance agrees with `epipolar_distance` on a known geometry

**Route (pytest)**
- payload validation and path containment, including the traversal cases already
  covered for `/reproject/run`
- the peaks route rejects a request naming a video outside the data root

**Markup and wiring (existing test files)**
- the two checkboxes and the number field exist with the stated defaults and bounds
- all three carry `data-help` and have `HELP` entries
- all three round-trip through `reproj_params`
- analyze-for-tag posts to `/peaks` only when the checkbox is ticked

**Not host-testable**, and stated as such rather than faked: the inference
pipeline itself. It is verified by the existing 0.344 px measurement, and the
port must be checked by re-running that comparison on the deployed container.

## Risks

- **`score_floor = 0.05` is unmeasured.** Too high and the screen degenerates
  into `rescue_floor`; too low and hallucinated peaks pass. It ships as a tunable
  field with an unvalidated default, and tuning it needs labelled data the
  project does not currently have much of — 175 low-confidence cases across 13
  sessions, 84 of them unseen.
- **A third change to the main webapp**, discussed above.
- **The ~50 s pass is per tag run, not per frame**, so it is cheap for large runs
  and proportionally expensive for a two-frame one. The checkbox is the escape.
