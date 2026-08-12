# Wiring the two-camera pellet detector — design

**Date:** 2026-08-12
**Card:** `3D Inline Analysis - SAM Model`
**Reported:** frame 27591 of banh-mi-1 2026-07-07 is armed ("pellet stationary")
with no pellet on the frame.

## 1. The sweep never used the two-camera detector

`sweep2.py` — both cameras must match the pooled pellet template, and their match
positions must triangulate near the project's reference pellet point — was built,
unit-tested, and **never wired in**. The sweep still ran the original
single-camera path: the *canonical* 60x90 template (mostly dark pedestal, the
pellet clipped) slid over a 140x160 band, taking the best correlation anywhere.

On the reported frame that band's best match was blank background beside the
pedestal, at 0.643. Thirty frames later a paw resting on the pedestal scored
0.849. Neither frame has a pellet.

Measured on the reported pair, with the pooled 44x44 DLC-derived template
(261 samples) and the 3D gate:

| frame | what is there | 1-cam | cam0 | cam1 | 3D dist | 2-cam verdict |
|---|---|---|---|---|---|---|
| 27591 | empty background | 0.643 armed | 0.553 | 0.673 | 8.29 | **reject** |
| 27621 | paw on the pedestal | 0.849 armed | 0.678 | 0.600 | 14.09 | **reject** |
| 28496 | the pellet | — | 0.891 | 0.902 | 0.29 | **arm** |

Note 27591 and 27621: both cameras clear 0.55 on the paw frame. **Only the 3D
gate rejects it** — the same result that justified the gate originally.

Whole-video effect: armed samples 19843 -> 5078, candidate frames 161398 ->
24634, across 129 windows.

### Design

A single module, `pipeline.py`, does stage 0+1 for a video: cached pair sweep ->
armed mask -> windows. The debug panel, `/windows` and `/onset-csv` all call it.
Each previously carried its own copy, and the last divergence had one of them
forget the cache signature.

The sweep stores **raw** `score0`, `score1`, `dist3d`. The thresholds are applied
at judge time, so retuning re-judges in under a second instead of costing another
seven-minute pass. Verified: 0.75 s to re-judge the whole video.

## 2. The placed box was stored in display pixels

Investigating the above showed the box on this pair sat at (369.5, 339.9) while
the pellet is at (417, 385). Every stored mark was a uniform ~0.88x its true
coordinate — **both cameras, both axes**:

| | stored | /0.882 | project default |
|---|---|---|---|
| cam0 | 369.5, 339.9 | 419.0, 385.5 | 416, 388 |
| cam1 | 522.0, 396.9 | 591.9, 450.1 | 592.7, 449.7 |

`_pelletCanvasToImage` scaled the click by `canvas.width / rect.width`, assuming
the backing store is the video's native size. `VideoViewer` sizes it to the
**displayed** size, so that ratio is 1 and clicks were stored in display pixels.

The draw path made the mirrored assumption, painting the stored coordinate
straight onto the display canvas — so the box appeared **exactly under the
cursor** while being wrong in the file. Self-consistent on screen, wrong on disk:
no amount of looking at it could catch this.

Scored against the pooled template on a frame with a pellet:

* stored box: cam0 **0.44**, cam1 **0.36** — below any workable threshold, so
  this box could never have detected a pellet at all
* un-scaled: cam0 **0.894**, cam1 **0.901** — identical to the project default,
  and both converge on the same match point

So the user aimed correctly; only the storage was wrong. Both directions now go
through tested pure helpers (`toImage`, `toCanvas`, `scaleFor`) that live next to
each other so they cannot drift apart again.

**The existing marks were repaired** to the un-scaled reconstruction of the
user's own clicks rather than left corrupt or silently deleted.

## 3. One place decides

`threshold` and `max_3d_dist` were on `PelletModel`, edited in the pellet
section, while `Judge` owned every other candidate parameter. Both now live in
the Judge, with the pellet section keeping geometry only. The panel's mirror
(`trial_judge.mjs`) asserts the same default numbers, so retuning one side fails
on the other.

## 4. A wrong box now says so

A wrong box is silent — it costs a seven-minute sweep and returns a mask full of
paws. `GET /pellet/check` scores the template at each placed centre on the
current frame; Confirm reports it. Two template matches is milliseconds.

Verified against the actual bad box: *"the template only scores 0.44 here, under
the 0.50 threshold — this box would arm nothing."* No grace band: the sweep uses
the threshold verbatim, so a "close enough" verdict would promise detections that
cannot happen. The check is advice, never a gate — it must not block confirming
if it fails.

## Tests

Python: 9 pair-cache (incl. cross-shape reads returning None, NaN survival),
7 pipeline (cached sweep -> windows, the 3D gate removing frames both cameras
liked, re-judging without a re-sweep), 6 two-camera judging, 5 box resolution,
4 placement verdict, 3 sidecar columns.

JavaScript: 11 coordinate-conversion (incl. the round-trip identity — what is
drawn sits under the cursor *and* what is stored is the true coordinate), 5 for
the 3D gate in the judge, 1 asserting the thresholds exist in exactly one place.

## Out of scope

Re-measuring acceptance. The detector changed, so every recall/precision figure
for this pipeline is now void and must be re-run.

## Follow-up — RESOLVED 2026-08-12 (commit 24d44a1)

`intervals.build_windows` compared outcome markers (1-based, from the companion
CSV) against armed intervals (0-based, from the sweep), so every armed interval
sat a frame adrift of the trial it belonged to.

It surfaced properly during deployment verification of the 3D scorer: a run
reported frames 172185–174665 in its JSON while writing 172186–174666 to its
motion3d sidecar. Same payload, same order, same length — only the label
differed, so every 3D point in the durable record disagreed with the result that
produced it.

The sidecar was the correct one. The conversion now happens ONCE, at the pipeline
boundary; everything the pipeline hands out is a 1-based `frame_number`, and only
the cv2 seek and `/thumb` convert back. The panel needed no change and becomes
correct by it — `_samGoToFrame` already assumed 1-based, so it had been seeking a
frame early.
