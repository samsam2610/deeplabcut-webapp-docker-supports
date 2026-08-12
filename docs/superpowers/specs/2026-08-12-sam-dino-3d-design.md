# Run SAM + DINO 3D — design

**Date:** 2026-08-12
**Card:** `3D Inline Analysis - SAM Model`
**Status:** implemented 2026-08-12 (929379a, 24d44a1, f742cd4)

Scoring currently runs on cam0 alone. This adds a second button that segments
**both** cameras, cross-checks the two paws geometrically, triangulates the paw,
and stores the 3D motion for later analysis.

## 1. What the button does

Per candidate frame in the window, for each camera:

1. SAM 3 segments with the text prompt.
2. `choose_reaching_paw` picks the reaching paw (nearest the pellet).
3. The **centroid of the mask** is that camera's 2D point — not the bbox centre,
   which moves with the silhouette's bounding extent rather than its mass.

Then, per frame:

4. **Epipolar cross-check.** Undistort cam0's centroid, take its epipolar line in
   cam1, measure the perpendicular distance to cam1's undistorted centroid.
   Above `epi_px` the two views are not looking at the same paw — **reject**.
5. **Triangulate** the two centroids to a 3D point.
6. **DINO picks.** Among survivors, fuse cam0 and cam1 similarity by **mean** and
   take the highest.

Geometry vetoes; the learned model chooses. Same shape as the pellet 3D gate
that caught frame 27591, and no hand-tuned blend weights to invent.

`mean` not `min`: the paw is transiently occluded in one view on a large
fraction of frames, and `min` lets either view veto a frame the other is certain
about. A wrong-paw match is already handled by the epipolar gate, which is
geometric and does not need the score to police it.

## 2. The cam1 exemplar bank

The bank is cam0-only and its crop is a fixed cam0 rectangle. Two changes.

**The crop becomes pellet-anchored.** cam0's `CROP = (150, 420, 320, 520)` is
exactly its pellet centre (416, 388) plus `(-238, +32, -96, +104)`. Applying the
same offsets to each camera's own centre gives cam1 `(211, 481, 496, 696)` —
rendered and checked: pedestal bottom-centre, aperture above, fully in frame.
One rule instead of a second magic constant, and it follows a re-placed box.

**A cam1 bank**, built from the *same* human onset frames read out of the sibling
video. The cameras are frame-synced and the notes are cam0-only, so this needs
**no new human labelling**. Cached per camera; the cache key already covers the
crop, and gains the camera. Leave-one-session-out is unchanged: a session is
still never scored against its own tags.

## 3. `epi_px`, measured

Set from the project's own labelled cam0/cam1 pairs, the way `max_3d_dist = 2.0`
was set. Positives are the paw centroid in both views; negatives are the failure
the gate exists to catch — cam1's picker locking onto a different structure, and
onto the paw in a different frame.

Undistorting barely moves the residual (p50 2.27 vs 2.17 raw); it is done anyway,
for consistency with `triangulate`.

### The proxy has to be a real paw centroid

**`Left-Paw` is not a landmark.** It is a decoy, placed randomly to stop DLC
labelling that paw's joints. An earlier draft used it as the whole-paw proxy and
derived `epi_px = 20` from it; that number measured random placement, not
geometry, and was 5 px too loose.

The honest proxy is the centroid of the **real** digit joints (MCP/PIP/DIP-1..4).
`Wrist` is excluded too — it is an interior, occluded point (p95 37.7), the
occlusion noted at the start of this project.

| proxy for the mask centroid | p50 | p95 | p99 |
|---|---|---|---|
| joint centroid, matched subset in both views | 2.08 | 6.71 | 9.66 |
| **joint centroid, each view's own visible joints** | **3.53** | **12.85** | **17.89** |

The gap between those rows *is* the mask-centroid effect. When each camera
averages only the joints it can see, the two centroids stop being the same 3D
point and the residual roughly doubles. A SAM mask centroid has precisely that
property, so the second row is what the gate faces. (Averaging by mean rather
than median gives p95 12.03 — a pixel-mass centroid is mean-like, so the true
figure sits just inside this.)

| threshold | keeps true | rejects wrong structure | rejects wrong instance |
|---|---|---|---|
| 12 px | 93.6 % | 87.3 % | 75.2 % |
| **15 px** | **97.1 %** | **84.4 %** | 71.4 % |
| 18 px | 99.0 % | 81.9 % | 67.3 % |
| 20 px | 99.3 % | 80.5 % | 64.8 % |

**`epi_px = 15`.** Roughly 3 % of true paws for roughly 84 % of cross-view
mismatches. Not tighter: stage-1 recall cannot be recovered downstream.

Per-session spread is real — banh-mi-1 Jul 2 reaches p95 17.97, above the
default — which is another reason it is a Judge field and tunable per project
rather than a constant.

## 4. `<video>_motion3d.csv`

Tidy long format, one row per `(frame, source, marker)`:

```
frame,source,marker,cam0_x,cam0_y,cam1_x,cam1_y,X,Y,Z,epi_px,score
28496,sam3,paw_centroid,441.2,352.8,600.1,410.4,2.11,9.87,277.4,1.8,0.93
28496,sam3,pellet,417.0,387.0,591.0,449.0,1.68,11.09,278.8,0.9,0.89
28501,dlc,paw_centroid,440.0,351.0,599.0,409.0,2.20,9.70,277.2,1.2,0.99
```

* a new marker or a new segmenter is new **rows**, never a schema change, so
  adding on top never migrates what is already written
* merged on `(frame, source, marker)`: re-running replaces only its own rows and
  leaves every other source intact
* written for **every candidate that segments**, not only the pick, so the
  trajectory is dense and the whole window is available to later analysis
* rejected frames are written too, with their `epi_px` — the evidence for a
  rejection is exactly what is needed when a frame that should have been kept
  was not. This is the lesson from the sidecar: a decision without its inputs
  cannot be diagnosed from the file.

## 5. Thumbnails

Top-5 **cam0** with the mask burnt in · gap · the **same 5 frames** from **cam1**,
column-aligned so column *i* is one frame in two views. Clicking either seeks.
`/thumb` already takes a video path; it needs the per-camera crop from §2.

## 6. The judging note

Rewritten so every parameter is named and bolded:

> **pellet thr** — the NCC each camera must reach for the pellet to count as
> present.
> **debounce** — how many consecutive samples a change must persist; stops the
> reload vane and passing paws flicking the mask on and off.
> **lookback** — how far a window reaches back from its outcome marker.
> **min cand** — armed frames below which a trial is skipped as unsearchable.
> **past prev marker** — why trial #11 of banh-mi-1 Jul 7 read as a success: its
> window reached back over the `f` at 27536 and took its label from the `s` 1379
> frames later. At 0 a window opens after the previous marker, so the marker that
> closes it is the next one after every candidate in it. Raising it recovers the
> ~1.2 % of onsets the human marked late, at the cost of that guarantee —
> ambiguous trials are flagged ⚠ in the trial list.
> **3D gate** — how far the triangulated *pellet* may sit from the project's
> reference point. Frame 27591 passed both cameras at 0.55/0.67 and was rejected
> at 8.29.
> **epipolar tol** — how far off cam0's epipolar line the cam1 *paw* may sit
> before the two views are judged to be looking at different paws. 15 px keeps
> 97.1 % of the project's labelled paw centroids.

## 7. Cost

SAM measured at 0.067 s/frame, DINO ~0.02 s/frame batched. Windows now average
**191 candidates** (was ~1800 before the two-camera pellet gate), so both cameras
densely is ~26 s SAM + ~8 s DINO ≈ **35 s per trial**. No sampling needed.

## 8. Risk retired

`choose_reaching_paw` picks by distance-to-pellet and had never run on cam1.
Measured against labelled joint centroids on 25 frames of banh-mi-1 Jul 2, before
anything was wired:

| | no paw found | centroid vs labelled joints, p50 | within 30 px | SAM instances |
|---|---|---|---|---|
| cam0 | 0/25 | 15.5 px | 84 % | 4.0 |
| cam1 | 0/25 | 14.3 px | 88 % | 3.5 |

cam1 is **not worse** than cam0. SAM returns 3–4 paw instances per frame, so the
picker is discriminating rather than defaulting to the only candidate.

## Tests, first

Pure, unit-tested: mask centroid; epipolar residual (a known correspondence near
zero, a deliberate mismatch large); the pellet-anchored crop rule; fusion by mean
with one view missing; motion-CSV merge preserving a foreign `source`; the gate
rejecting a mismatched pair; thumbnail pairing keeping columns aligned.

Panel-side `.mjs`: the paired thumbnail layout, and the judge mirror gaining
`epi_px` — that mirror asserts the same defaults on both sides, so a retune on
one fails on the other.

## Out of scope

Folding 3D kinematics into the score. The columns are written, so their value can
be measured against the human tags and only then earned. Re-measuring acceptance
also stays out: the detector changed again, so those figures are void regardless.


## Post-implementation: what verification changed

Deployment verification ran the scorer end to end and found it rejecting 127 of
the 193 frames where both cameras actually found a paw. Three corrections came
out of that, in order of size.

### The calibration was from the wrong session

`find_for_project` returned the last path alphabetically while its docstring
claimed "the most recent". banh-mi-1 Jul 7 was therefore triangulated with
khoai-lang-2's **May 12** calibration — a different animal, two months earlier —
while banh-mi's own Jul 5 calibration sat unused. Measured on banh-mi-1 Jul 2's
labelled frames, over verified-correct paw pairs:

| | p50 | p95 |
|---|---|---|
| joint centroid + own calibration | 0.78 | 8.83 |
| joint centroid + khoai-lang | 27.80 | 30.00 |
| SAM mask centroid + own calibration | 3.39 | 17.80 |
| SAM mask centroid + khoai-lang | 26.82 | 36.70 |

`find_for_video` now picks the same session, else the same animal on the nearest
date, else the nearest date. The calibration also joins the pair-sweep cache key,
since `dist3d` is triangulated with it during the sweep.

### `epi_px` had been measured on a stand-in — twice

`Left-Paw` gave 20 px (a decoy, §3). The digit-joint centroid gave 15 px:
anatomically corresponding, but a SAM mask includes the forearm and each view
sees a different amount of it, worth about 2x. The real quantity — SAM mask
centroids on 55 frames where both views verifiably picked the correct paw, under
that session's own calibration — is p95 **17.80**, so the default is **20**
(keeps 98.2 %).

The lesson is not "pick a better percentile". It is that a stand-in for the
measured quantity has to be justified as a stand-in, and neither of the first
two was.

### `ref_3d` could not survive the calibration change

A 3D coordinate only means something in the frame of the calibration that
produced it. Moving Jul 7 onto its own calibration pushed the triangulated pellet
from 0.48 to **29.30** away from the stored project-level reference — every
pellet would have failed the 2.0 gate.

The reference is now derived per pair by triangulating the human's **placed
box**, which is already required before sweeping and is by definition the
stationary pellet in both views. It is therefore always in the same frame as the
calibration, and cannot go stale. Verified on Jul 7: frames with a pellet land
0.20-1.02 from it, frames without 2.31-9.81.

### Result after the corrections

Same window (2486 candidates), same session, before and after fixing the
calibration:

| | real pairs | accepted | median epi_px |
|---|---|---|---|
| khoai-lang calibration, tol 15 | 193 | 66 (34 %) | 17.4 |
| own calibration, tol 20 | 193 | **116 (60 %)** | **13.2** |

The remaining rejections are not borderline. Pass rates at 15/20/25/30 px are
55/60/63/66 %, and the real pairs' p90 is 63 px — so the threshold sits on a
flat part of the distribution, with the rejected group far outside it. Those are
frames where the two cameras locked onto genuinely different paws, which is what
the gate is for. Raising the tolerance to 30 would buy 6 pp of recall and admit
mismatches.

Of 2486 candidates only 193 have a paw in both views at all; on the rest SAM
finds no reaching paw near the pellet in cam0, which is expected — most of a
window is the animal not reaching.
