# SAM candidate tagger — design

**Date:** 2026-08-11
**Module:** `deeplabcut-webapp-docker-supports/sam-training/`
**Status:** design approved, not yet planned

## Problem

During the experiment the human keys the outcome of each reach live, as an `s` or `f` note.
Afterwards they must go back through a ~21-minute, 252 k-frame video and hand-place the
onset frame for each one — roughly 85 per video, ~0.03 % of frames. **That retrospective
onset hunt is the only thing being automated.**

**Success/failure is never predicted.** It is already in the CSV: the label for a candidate
is read off the next human `s`/`f` marker after it. A candidate is therefore only emitted
where a downstream human outcome marker exists — no marker, no candidate.

The tool proposes **candidates only**. A human always makes the final call.

The immediate payoff is the **orphan `s`/`f` markers** — trials whose outcome was keyed
live but whose onset was never tagged: **198 of them**, in banh-mi-1 Jul 3 (67 of 107) and
Jul 7 (131 of 131).

### Scope

Only the phase where the **wrist, digit joints and pellet are all outside the glass**,
reaching for the pellet. Frames where the animal is behind the panel are explicitly out of
scope — no occlusion handling, no behind-glass segmentation, no implant-occlusion logic.
The aperture crossing is precisely the moment the paw becomes "outside the glass", so the
gate and the scope boundary are the same event.

## Data

Full note/tag semantics and rig geometry: see the `reference-reaching-task-note-vocabulary`
memory. Summary of what this design depends on:

| fact | value |
|---|---|
| Source videos | 800×600 **grayscale** MJPG AVI, 200 fps, ~252 k frames, ~9.9 GB, cam0 |
| Tags live in | `<video>.csv` — `timestamp, frame_number, frame_line_status, note`; 1-based |
| Onset tags | 1323 in the training set — see the dataset selector below |
| Outcome markers | `s` / `f`, keyed **live during the experiment** |
| Onset→outcome gap | median 373 frames, p10 306, p90 1080 — **varies, never a fixed offset** |
| Paired trials | 1361 / 1368 onsets pair with a matching outcome within 3000 frames |
| Animals | 4 (khoai-lang-1, khoai-lang-2, banh-mi-1, eggtart-1) across 13 videos |

Tags are cam0-only; cameras are hardware-triggered so frame *n* is the same instant on cam1.

### Dataset selector — `Tag = Done`

**The training set is defined by `tracked_files.sqlite`, not by scanning the videos
directory.** Use only tracked files whose `Tag` progress segment is `Done`. Join
`tracked` → `video` → `progress_value` → `progress_segment`/`progress_option`; the `video`
table alone is a registry of files seen, not the working set.

| | videos | `start-*` | `s`/`f` | orphans |
|---|---|---|---|---|
| **Training set** (`Tag = Done`) | 10 | **1323** | 1309 | 5 |
| **Targets** (`Tag` not Done) | 2 | 45 | 238 | **198** |

`Tag = Done` videos are 99.6 % complete, which is the check that the filter is right.

Two traps this avoids. 13 files are registered but only **12 are tracked** — the extra is
`banh-mi-1_cam0_20260703_115411_2...avi`, an untracked near-duplicate of the tracked
`..._synced.avi` (107 of 110 `s`/`f` markers at identical frame numbers). And the two
untagged videos are exactly the two whose `Tag` is unset, so the selector excludes them
from training and identifies them as the targets in one step.

Animals: khoai-lang-1 (3 videos), banh-mi-1 (4), eggtart-1 (2), khoai-lang-2 (1).
Both targets are banh-mi-1 days.

## Measured findings that drive the design

All measured on `banh-mi-1_cam0_20260702_104728_5` unless noted.

**Pellet template matching is solid and transfers.** Normalised cross-correlation
(`TM_CCOEFF_NORMED`) of a pellet-on-pedestal patch, searched in a fixed band around the
pedestal. One template built from banh-mi-1 (Jul 2) separates pellet-present from
pellet-gone on three other sessions spanning two months and three other animals:

| session | NCC at onset | NCC at outcome | separation |
|---|---|---|---|
| khoai-lang-1, May 6 | 0.760 | 0.405 | +0.355 |
| khoai-lang-2, May 7 | 0.815 | 0.499 | +0.316 |
| eggtart-1, Jul 1 | 0.790 | 0.343 | +0.447 |

Must be NCC, not a brightness threshold: the white reload vane swings the frame mean
from ~40 to ~142.

**Throughput:** 1063 frames/s single-threaded on CPU including MJPEG decode, at stride 5
→ ~4 min for a full 252 k-frame video, ~45 min for all 11 tagged videos. This is what
makes the heavy stage affordable: SAM sees ~50 k frames per video instead of 252 k.

**NCC alone cannot name the key frame.** At the human tag the pellet template sits on a
plateau (~0.82) and collapses shortly after; the steepest drop lands within ±5 frames of
the tag on only **5 %** of trials (±10: 18 %, ±25: 39 %).

**Success/failure separability was measured and is now moot.** Best AUC from the NCC trace
was 0.71 (`ncc_at_+99`). Recorded only so nobody re-runs it: nothing predicts the outcome,
because the human already keyed it.

**Photometric paw detection fails on the vane.** Three successive OpenCV guards
(global-median, bright-fraction, texture) all failed to distinguish the white reload vane
from a white paw; the resulting crossing estimate moved from −91 to −88 to −31 frames
depending on the guard. The vane intrudes on 44 % of trial windows. A sheet of white
plastic and a white paw are the same thing to a threshold. **This is the evidence-backed
justification for using SAM on the paw/wrist**, and for keeping OpenCV on the pellet where
it is reliable.

**The aperture crossing precedes the tag with high variance** — tens to ~200 frames,
unstable across detector variants. It is a good *trigger* and a bad *answer*: it opens a
search window, it does not name a frame.

### The DLC keypoint baseline hits ±5 on ~85 % of trials

Measured 2026-08-11 on the 6 `Tag=Done` videos that already carry
`iter28_snapshot_best-120` h5 for **both** cameras (752 trials, eggtart-1 ×2 +
banh-mi-1 ×4). No new inference was needed — the h5 already covers [−199, +399] around
every tag, a by-product of the existing tag-mode analysis.

A 3-layer dilated 1D-CNN over per-frame DLC features from both cameras (32 likelihoods,
paw↔pellet geometry, pellet displacement, velocities — 100 features), trained to pick the
onset frame, leave-one-session-out:

| search window | CNN ±5 | ±10 | ±25 | best single feature ±5 |
|---|---|---|---|---|
| 250 frames | 85.1 % | 91.5 % | 93.8 % | 45.1 % |
| 400 frames | 83.8 % | 89.8 % | 92.8 % | 42.7 % |
| 550 frames | 84.4 % | 89.9 % | 91.9 % | 40.8 % |

Median absolute error: **2 frames**. Accuracy is flat as the search window widens 2.2×, so
the head is finding a real local signature rather than exploiting a positional prior.

#### Controlling for DLC training contamination

Leave-one-session-out holds out the *head*'s training data but **not the DLC model's** —
the model has labelled frames from these same sessions, and in eggtart-1 Jul 1, 21 of its
30 labelled frames sit within ±5 frames of a tag (median distance 4). That contamination is
real and had to be measured, not assumed away.

Cross-referencing labelled-frame count against fold accuracy shows it runs the **opposite**
way:

| session | labelled cam0 frames | fold ±5 |
|---|---|---|
| banh-mi-1 Jul 2 | 163 | 63.5 % |
| eggtart-1 Jul 1 | 30 (21 within ±5 of a tag) | 74.6 % |
| banh-mi-1 Jul 4 | 53 | 85.8 % |
| banh-mi-1 Jul 5 | 5 | 89.0 % |
| **eggtart-1 Jul 5** | **0** | **89.1 %** |
| **banh-mi-1 Jul 6** | **0** | **96.5 %** |

Restricted to the two sessions with **zero labelled frames anywhere in DLC training**
(281 trials): **92.9 % within ±5, 95.7 % ±10, 97.5 % ±25, median absolute error 1 frame** —
better than the contaminated average, not worse.

Hypothesis for the inversion (unverified): the labelling workflow targets frames where the
model already fails, so heavily-labelled sessions are the hard ones.

**Limitation — session-clean, not animal-clean.** Both clean sessions come from animals
with labelled frames on other days, and no animal in this project is entirely unlabelled,
so animal-level DLC generalisation cannot be tested without retraining DLC minus an animal.
If a new animal always gets frames labelled before analysis, "new day, known animal" is the
deployment case and 92.9 % is the honest figure. It does not cover a never-labelled animal.

### Both cameras are needed, for opposite reasons

| | cam0 | cam1 |
|---|---|---|
| mean `P(wrist)` over the window | 0.22 | **0.39** |
| mean `P(digits)` | 0.39 | **0.49** |
| **`P(wrist)` at the tag frame** | **0.73** | 0.43 |
| `argmax P(wrist)` within ±5 | **43.8 %** | 13.0 % |

cam0's wrist is poorly tracked on average but spikes sharply *exactly at the tag*
(0.24 at −20 → 0.73 at +0 → 0.42 at +20): through the slot, the wrist is only visible at
full extension. cam1 sees the wrist far better overall but as a broad plateau peaking
*after* the tag (0.43 at +0 → 0.76 at +20 → 0.54 at +100), so it localises poorly alone.
**On cam0 the occlusion is the signal.** Naively summing the two cameras is worse than cam0
alone (27.3 % vs 43.8 %); the learned head weights them and reaches 85 %.

## Architecture

```
per video (cam0)
├─ Stage 0  validate the canonical pellet template here      NCC, seconds
├─ Stage 1  NCC sweep → pellet-stationary intervals          CPU, ~4 min/video
├─ Stage 2  SAM 3, on those intervals only
│            ├─ paw/wrist mask crosses the aperture → window opens (now "outside glass")
│            └─ per-frame mask features until the human s/f marker closes it
├─ Stage 3  temporal head over the window
│            └─ per-frame key-frame probability → argmax          (localisation only)
└─ Stage 4  suffix := next human s/f marker after the frame
            write start-success-candidate / start-failure-candidate
            → human confirms/nudges → real tag
```

Each search window is bounded: it **opens** when the paw clears the aperture and **closes**
at the human `s`/`f` marker. Windows without a closing marker are skipped entirely.

The aperture is static, so SAM never has to find it — and SAM's only job is the paw/wrist
mask. **Not yet implemented:** stage 0 does not locate the aperture, it uses a hard-coded
default. Nothing needs it until stage 2 gates on the paw clearing it, at which point it has
to become a real measurement.

### Stage 0 validates a canonical template — it does not derive one

Implementation note, and a correction to the original design. Deriving a pellet template
per session was tried three ways and each broke a *different* session:

| selection rule | worst session | separation |
|---|---|---|
| highest patch contrast | banh-mi-1 Jul 4 | +0.12 — lost 42 % of its onsets |
| widest probe-score spread | banh-mi-1 Jul 2 | −0.01 — selected the reload vane |
| both combined | khoai-lang-1 May 6 | −0.10 |

The vane is the recurring confounder: its in/out cycle is the strongest bimodal signal in
the pellet box, so "most discriminative patch" picks it rather than the pellet.

One template cut from banh-mi-1 Jul 2 frame 49296 separates present from absent by
**+0.34 to +0.56 on all ten sessions** — better than every per-session pick, which follows
from the camera not having moved in two months. It ships as
`sam-training/src/assets/pellet_template.png`.

Stage 0 therefore measures the canonical's score spread on a sample of the session and only
searches locally if it falls below `MIN_SPREAD`, which would mean the camera actually moved.
All 10 sessions choose the canonical.

### Stage 1 acceptance — 98.9 % of onsets survive

Measured 2026-08-11 across all 10 `Tag=Done` videos, 1 304 tagged trials
(`sam-training/scripts/acceptance.py`). This is the recall gate: anything stage 1 drops,
stages 2–3 can never recover.

| | |
|---|---|
| onset inside the window span | **1304/1304 (100 %)** |
| onset is a candidate frame | **1290/1304 (98.9 %)** |
| sessions at 100 % | 8 of 10 |
| worst sessions | khoai-lang-1 May 6 (94.7 %), May 7 (96.1 %) |
| median candidate frames per window | ~1 300 |
| sweep cost | ~200 s per video, CPU only |

The residual 14 losses are onsets where the paw occludes the pellet enough to drag NCC
under the fixed 0.50 threshold. A per-session threshold derived from the calibration's
measured modes is the obvious next lever, but three separate attempts to make stage 0
adaptive each broke a different session, so it should only be attempted with all ten
sessions measured — not tuned on one.

~1 300 candidate frames per window is what stage 2 must process per trial. With SAM
prompt-once-then-track rather than per-frame detection, that is the difference between
tractable and not.

### Stage 3 — what the head learns

The key-frame definition is **not hand-written**. SAM masks yield a compact per-frame
feature vector (paw centroid / area / bbox, paw↔pellet distance and overlap, pellet
displacement from its resting position, wrist position relative to the aperture, plus
velocities). A 1D-CNN or BiGRU over the window learns whatever regularity the human
tagging follows, trained on the 1361 labelled windows.

**Localisation only — there is no classification head.** The window's success/failure is
already known from its closing `s`/`f` marker. It may still be fed in as an *input* feature
if it helps localisation (success and failure reaches may peak differently), but it is
never an output.

### Stage 4 — write rules

Candidates are written into the real companion CSV, under a distinct namespace.
`tagged_frames()` matches **exactly**, so `*-candidate` notes can never be picked up by
tag-mode analysis until a human promotes them.

The suffix is **derived, not predicted**: `s` → `start-success-candidate`, `f` →
`start-failure-candidate`, taken from the marker that closed the window.

Three hard rules:

1. **Never overwrite an existing note.** If the predicted frame already carries a note,
   shift to the nearest note-free frame within ±5; if all 11 frames in that span are
   occupied, skip the candidate and log it.

   ±5 is deliberately the same number in two places: it is the accuracy target the model
   is scored against, *and* the slack the writer may use to dodge an occupied row. Because
   a candidate landing anywhere within ±5 of the human tag counts as correct, shifting
   within ±5 cannot turn a correct candidate into an incorrect one.
2. **Atomic write.** `annotate_save_row` (`src/routes/annotate.py:202`) does a full
   read-modify-write of the 252 k-row file, unlocked, opening the real path with `"w"` —
   a crash mid-write truncates the experimental record. Our writer uses temp-then-rename
   plus a lock, following `canonical.py:75`.
3. **One pass per video.** All candidates for a video are written in a single
   read-modify-write, not 85 separate full-file rewrites.

## Validation

Report **both** protocols; a random split leaks the same animal's posture across train and
test and reports a fake number.

- **Leave-one-session-out** — matches deployment. Both targets are banh-mi-1 days and
  banh-mi-1 already has 4 sessions in training, so the real question is "predict a new day
  for an animal we have seen".
- **Leave-one-animal-out** — the conservative bound, with only 4 groups (and khoai-lang-2
  contributing a single session).

**Metric:** fraction of candidates within ±5 / ±10 / ±25 frames of the human tag, and
per-video false-positive count (a review list longer than the manual pass is a failure
regardless of precision). **No success/failure accuracy** — the label is read from the
CSV, not predicted.

**The bar SAM must clear is now measured: 92.9 % within ±5 on DLC-clean sessions, median
error 1 frame** (83.5 % across all folds including contaminated ones), from
the existing DLC model at zero additional inference cost. SAM has to beat that to justify
its own stage. Remaining gaps where it might: the 64.7 % worst fold, the untested
leave-one-animal-out generalisation, and the ~15 % of trials the head misses.

## Environment

A clone of the stack on a git worktree, so production is untouched while people are using it.

- **Services cloned:** `flask` (hosts the nav button and the proxy route) and `redis`.
  `worker`, `worker-tf`, `dlc-3d` and `dlc-3d-worker` are **not** cloned — nothing in
  stages 0–4 needs them. Add a pytorch worker later only if the DLC keypoint baseline is
  run inside the clone.
- **New service:** `sam-training`, internal port only, proxied like `dlc-3d`. This is the
  one image that must be built; the cloned `flask` and `redis` reuse their existing images
  so no rebuild can overwrite what production is running.
- **Worktree** on a new branch for both repos; the clone mounts source from there.
- **Ports** 5001 (flask) / 6380 (redis) — verified free. In use: 5000, 5002, 5055, 5263,
  5433, 5678, 6333, 6379.
- GPU and data are shared with production by explicit decision.

## UI

A new nav button in `base.html` (one `<a>`, alongside the existing `/dlc-3d/` link) opening
a panel, proxied the way `src/app.py:614` proxies `/dlc-3d/`.

The panel is cloned from the inline-analysis-3D card —
`card_inline_analysis_3d.html` (962 lines) + `inline_analysis_3d.js` (3817) +
`.css` (313) — using the existing `dlc-3D/scripts/clone_inline_analysis_card.sh`, which
already performs the id / class / global renaming for this kind of spin-off. Copy rather
than refactor; the clone is then trimmed to what the SAM panel needs.

**Every stage must render its result on the frame** (built, see the module README): Stage 0/1 overlay the pedestal and
aperture boxes and the NCC trace; Stage 2 overlays SAM masks; Stage 3 shows the per-frame
key-frame probability against the window with the proposed frame marked. Nothing in this
pipeline is trusted from a number alone — the failures found while designing it (the vane
firing as a paw) were only visible by looking at frames.

## Test fixture

A **~2000-frame clip (~80 MB)** cut from one video spanning two or three trials, plus its
CSV slice — not a duplicated 9.9 GB video. Teardown removes it. This follows the earlier
incident where webapp tests leaked 614 GB into `/tmp`.

## Risks

1. **SAM 3 zero-shot quality on this imagery is unknown** — still the biggest technical
   risk, though the scope restriction cuts it down: SAM only ever sees an unoccluded white
   paw and a white pellet against a dark background, never a paw behind glass. **Spike this
   first**: request the gated checkpoint (`facebook/sam3.1` on Hugging Face), run zero-shot
   on ~50 frames spanning the outside-the-glass reach phase including vane-in frames, and
   look at the masks. If text prompting is poor on grayscale rodent anatomy, prompt with the
   existing DLC `Pellet` / `Left-Paw` keypoints.
2. **Checkpoint access is gated and BLOCKING.** Verified 2026-08-11: both `facebook/sam3`
   and `facebook/sam3.1` report `gated: manual` and return HTTP 401 unauthenticated. This
   needs a human to request access on Hugging Face and Meta to approve it manually — it
   cannot be worked around. `facebook/sam2.1-hiera-large` and `facebook/sam-vit-huge` are
   ungated and usable today; since grayscale rodent anatomy is a poor fit for text prompts
   and we would prompt with points/boxes anyway, SAM 2.1 is a viable stand-in for most of
   what Stage 2 needs.

3. **Only 2 animals were in the measured baseline.** The 4 khoai-lang videos lack an
   `iter28` h5 (they carry iter23/24 and older), so leave-one-**animal**-out is untested.
   Getting them analysed at iter28 on both cameras (~674 k frames, ~2 h GPU) is the single
   most valuable remaining measurement.
5. **No masks exist for fine-tuning.** Start zero-shot + a learned head. Only fine-tune if
   that misses, bootstrapping masks by prompting SAM with DLC keypoints.
6. **±5 may be below the human's own tagging noise.** Every trial is tagged once, so it
   cannot be measured from existing data. Re-tag ~30 trials blind and compute
   self-agreement; if the human's own jitter exceeds ±5, the target must move.
7. **khoai-lang-2 contributes a single session** (117 trials), so its leave-one-animal-out
   fold trains on three animals and tests on one thin one. Expect that fold to be noisy.

## Deferred: improving DLC labels

Feasible, but it depends on the same mask quality risk #1 is testing, so it gets its own
spec once the spike lands.

Masks **cannot** become an extra input channel to DLC's pose net without modifying DLC
internals — rejected. What works, ranked:

1. **Crop-to-paw.** 12 of the 16 bodyparts are digit joints (MCP/PIP/DIP ×4) on a paw
   occupying ~150 px of an 800×600 frame; adjacent joints are a few pixels apart. A SAM
   box → crop → upsample is architecturally supported — DLC 3's pytorch engine already
   does top-down detector+pose, and a SAM box is a detector output.
2. **Reflection rejection.** The glass mirrors the paw and causes keypoint jumps. Reject
   keypoints outside the paw mask. Post-hoc, no retraining.
3. **Occlusion flagging.** Mask area collapses behind the panel edge or the implant — flag
   rather than trust a confident-but-wrong point.
4. **Targeted frame selection** for the next labelling round, over DLC's uniform picking.

Free today, in the useful direction: **DLC keypoints → SAM prompts**, avoiding reliance on
text prompting for grayscale rodent anatomy.
