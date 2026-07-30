# Candidate-peak epipolar correction

**Date:** 2026-07-30
**Status:** design approved, not yet implemented
**Module:** `dlc-3D`
**Builds on:** [2026-07-29-inline-3d-reprojection-design.md](2026-07-29-inline-3d-reprojection-design.md)

## Problem

The reprojection engine rescues a low-confidence marker when it lies on the
epipolar line induced by the trusted camera. When the bodypart is **occluded**
in the judged view, that reasoning fails: DeepLabCut had no image evidence, so
its marker is a guess, and the epipolar line — a one-degree-of-freedom
constraint — endorses any guess that happens to fall in the band.

### Measured on `eggtart-1`

Of 125,524 rescues:

- **19.1% came from a marker DLC scored below 0.10** — "I see nothing", not "I am
  unsure". For the Wrist it is 46.0%.
- **15.9% sit within 5 px of a *different* bodypart's marker** in the same frame,
  rising to 33.3% for PIP-3 — the signature of the detector putting one blob on
  two parts. Adjacent digits have nearly coincident epipolar lines, so geometry
  cannot separate them.

A temporal median filter does not address this. Of the low-confidence rescues,
only **10.0%** are isolated single frames; **56.9%** sit inside runs of ten or
more consecutive sub-0.10 frames, and the Wrist's median run is **21 frames**
(~105 ms at 200 fps). Any window a median filter could use lies entirely inside
the occlusion, so it would smooth hallucination into smoother hallucination while
blurring genuine motion.

Human labelling corroborates the diagnosis independently: across the project's 44
labelled directories the annotator left 63.7% of cells unlabelled, and the Wrist
unlabelled 73% of the time — the same part, the same story.

## The idea

Stop asking *"is this marker consistent with the line?"* and start asking
*"does the image contain evidence for this part on the line?"*

DeepLabCut's heatmap holds that evidence. Stock single-animal inference discards
it: the predictor takes an argmax and emits one peak. Keeping the **top-K peaks**
per bodypart per frame lets the engine ask a better question, and lets it do
something it currently cannot — pick a *different* peak.

## Scope

1. A re-analysis pass that emits candidate peaks alongside the usual pose h5.
2. Engine changes that use those peaks to refuse, confirm, or **correct** a
   marker.

### A stated non-goal is deliberately reversed

The original spec says the module "never invents or snaps a position". That
stands: it still never invents one. But it may now **choose among positions
DeepLabCut itself detected**. Selecting the candidate that satisfies the epipolar
constraint is not invention — it is the same principle as DeepLabCut's own
`cross_view_match_dataframes`, which uses `x'ᵀFx` to assign detections across
views. The prohibition was against fabricating a coordinate, and that still
holds.

### Non-goals

- Full heatmap storage. See Feasibility.
- Multi-animal identity assignment.
- Retraining. This uses the existing snapshot.

## Feasibility, established

| Question | Finding |
| --- | --- |
| DLC version | 3.0.0rc14, PyTorch engine |
| Model | `hrnet_w48`, 448×448 input, `num_heatmaps: 16` |
| Does `analyze_videos` expose raw output? | **No.** 25 parameters, none for full/heatmap output |
| Is the heatmap reachable? | **Yes** — `HeatmapPredictor.forward` receives `outputs["heatmap"]` before the argmax |
| Can the predictor be swapped? | **Yes** — `PREDICTORS` is a `Registry` with `register_module` and `build` |
| Model availability | `iteration-22/DREADDJan7-trainset70shuffle1/train/snapshot-best-180.pt` is present on the NAS — the snapshot that produced the current h5 files |
| Full heatmaps | ~800 KB/frame → ~400 GB for both cameras. **Not viable** |
| Top-5 peaks | ~240 floats/frame → **~240 MB per camera**. Viable |

Because the same snapshot is used, peaks correspond to the existing markers by
construction: the argmax peak *is* the marker already in the h5. That makes the
sidecar verifiable — see Testing.

## Artifact: the peaks sidecar

The interface between the two phases, so it is specified once.

`<stem>_peaks.npz`, beside the pose h5:

| Array | Shape | Contents |
| --- | --- | --- |
| `xy` | `(frames, bodyparts, K, 2)` `float32` | peak coordinates in **original video pixels** |
| `score` | `(frames, bodyparts, K)` `float32` | heatmap score per peak, sigmoid-applied |
| `bodyparts` | `(bodyparts,)` | names, in the pose h5's column order |

Peaks are ordered by descending score, so `k=0` is the argmax and must reproduce
the pose h5's coordinate. Missing peaks are `NaN` with score `0`.

**Coordinates are in original video pixels, not model input space.** The model
runs at 448×448 on 800×600 frames, so peaks must be carried back through the same
resize/pad transform DLC applies to poses, after `locref` sub-pixel refinement.
This is the highest-risk part of the implementation and is what the `k=0`
equality test exists to catch.

## Phase 1 — emit the peaks

A predictor registered into `PREDICTORS` that returns top-K local maxima instead
of a single argmax.

**Non-maximum suppression is essential.** A naive top-K over a heatmap returns K
adjacent cells of the same blob. Peaks must be local maxima separated by a
minimum distance (default 3 heatmap cells), so K genuinely means K distinct
candidates.

Driven by a script that runs analysis with the custom predictor and writes the
sidecar. It does not replace the normal analysis: the pose h5 is produced as
usual, and the sidecar is additive.

## Phase 2 — use the peaks

For each rescue candidate, gather peaks whose score exceeds a floor and whose
distance to the epipolar line is within `t_ok`. Then:

| Situation | Verdict | Effect |
| --- | --- | --- |
| No qualifying peak | `NO_EVIDENCE` | **untouched**, and never rescued — the image does not support this part being anywhere on the line |
| The argmax peak qualifies | `RESCUE` | as today, but now evidenced rather than assumed |
| A different peak qualifies, argmax does not | `CORRECTED` | marker **moved** to that peak |
| Several peaks qualify | `AMBIGUOUS` | untouched — the constraint did not identify the part |

`NO_EVIDENCE` is the occlusion answer. `AMBIGUOUS` is the adjacent-digit answer:
when two candidates both satisfy the line, the geometry has discriminated
nothing and the honest response is to decline.

**A correction writes the peak's own score as the likelihood**, not
`rescue_floor`. The value then means what it says — DeepLabCut's confidence in
the chosen detection — instead of a flat number that hides provenance.

The 3D plausibility gate still applies to `RESCUE` and `CORRECTED`.

## The labelled data is READ-ONLY. This is not negotiable.

`labeled-data/` in the DeepLabCut project holds the human annotations the model
was trained on. It is the most valuable and least reproducible asset in the
project: corrupt it and you lose both this validation and the provenance of every
future retrain.

Phase 2 reads it as a **test set only**. Nothing in this work writes to, moves,
renames or reorganises anything under the DLC project:

- `labeled-data/**` — including every `CollectedData_*.h5`, `CollectedData_*.csv`
  and extracted frame image
- `training-datasets/**`
- `dlc-models-pytorch/**` — snapshots are loaded, never written
- `config.yaml`

Validation output — metrics, tables, any per-frame comparison — goes to a scratch
directory passed explicitly on the command line, never beside the labels.

Two habits enforce this, because intent alone has already failed once on this
project: the validation script takes an explicit `--out-dir` with no default that
points anywhere near the project, and every plan derived from this spec ends with
a step that counts files under `labeled-data/` before and after and reports the
observed numbers.

The same applies to the session data under
`/user-data/Parra-Data/Cloud/Reaching-Task-Data/`. Note in particular that
`/reproject/run` writes `<stem>_reprojected.*` beside the source and overwrites
any previous set — it is not a safe probe, and that mistake has already been made
once here.

## Testing

**Phase 1 correctness has an exact check.** Because the same snapshot is used,
`k=0` must reproduce the existing pose h5 coordinates to within sub-pixel
tolerance for every frame and bodypart. Any mismatch means the coordinate
transform is wrong. This is a strong test: it validates the riskiest part
against 251,640 frames of existing output.

Also: scores must be descending in `k`; peaks must be at least the NMS distance
apart; `NaN` padding must carry score `0`.

**Phase 2 validates against human labels**, which exist for 44 directories:

- **Occlusion recall.** Where the annotator left a part unlabelled — their
  judgement that it was not visible — the engine should return `NO_EVIDENCE`
  rather than `RESCUE`. Today it can only return `RESCUE` or nothing.
- **Correction accuracy.** Where the annotator *did* label a part and DLC's
  argmax is far from that label, a `CORRECTED` marker should land closer to the
  human position than the original did. If corrections do not reduce that
  distance, the approach does not work and should not ship.

That second measurement is the one that decides whether this is worth having.
It is stated as a threshold, not a hope: corrections must reduce median distance
to the human label, on held-out labelled frames, or the feature is abandoned.

## Phasing

Two implementation plans. Phase 1 delivers a verifiable artifact on its own —
the `k=0` equality test proves it without any engine change. Phase 2 depends on
that artifact and is where the scientific claim is tested.

Cost is not yet measured: throughput for 251,640 frames × 2 cameras at 448×448 on
the RTX 5090 is unknown, and the GPU is currently in use. Phase 1's plan should
open by timing a short clip so the full pass can be scheduled rather than
guessed at.

## Risks

- **The coordinate transform.** Mapping peaks back from 448×448 model space
  through padding and resize to original pixels is fiddly and silently wrong if
  mishandled. Mitigated by the `k=0` equality test, which would fail loudly.
- **Peaks may not exist where the part is occluded — which is the point, but it
  cuts both ways.** A part that is faintly visible may produce a weak peak that
  passes the floor and licenses a bad correction. The score floor is the only
  defence and will need tuning against the labelled frames.
- **Re-analysis cost.** A full pass over both cameras is substantial and competes
  with ongoing work on the same GPU.
- **`CORRECTED` markers move data.** Every previous verdict either deleted or
  re-scored; none moved a coordinate. The audit records the original position so
  a run stays reversible, and the validation threshold above is what justifies
  the change at all.
