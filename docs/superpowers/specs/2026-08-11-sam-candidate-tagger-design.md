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
live but whose onset was never tagged. Measured: 313 orphan markers across the 13 tracked
files, but Jul 3 is one session stored twice (see below), so **~203 unique untagged
trials**. They are not scattered: nine videos have 0–1 orphans each, and 98 % sit in
banh-mi-1 Jul 7 (131, never onset-tagged), Jul 3 (67 of 107, a third done) and the Jul 3
duplicate.

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
| Onset tags | 817 `start-success` + 551 `start-failure` across 13 tracked videos |
| Outcome markers | `s` / `f`, keyed **live during the experiment** |
| Onset→outcome gap | median 373 frames, p10 306, p90 1080 — **varies, never a fixed offset** |
| Paired trials | 1361 / 1368 onsets pair with a matching outcome within 3000 frames |
| Animals | 4 (khoai-lang-1, khoai-lang-2, banh-mi-1, eggtart-1) across 13 videos |

Tags are cam0-only; cameras are hardware-triggered so frame *n* is the same instant on cam1.

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

## Architecture

```
per video (cam0)
├─ Stage 0  locate pedestal + aperture once per session      NCC, seconds
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

The aperture is static, so SAM never has to find it — it is located once per session by
the same NCC trick, and SAM's only job is the paw/wrist mask.

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

**Leave-one-animal-out.** There are only 4 animals and sessions are per-animal-per-day; a
random split leaks the same animal's posture across train and test and reports a fake
number.

**Deduplicate by session, not by file.** `banh-mi-1_cam0_20260703_115411_2.avi` (253 083
frames) and `..._synced.avi` (253 078) are the same recording — 107 of 110 `s`/`f` markers
sit at identical frame numbers, median offset 0. Both are in `tracked_files.sqlite`, and
the tagging is split across them (0 start tags on one, 45 on the other). Feeding both into
training duplicates those 40 trials inside a fold and inflates the score. Pick one
canonical file per session before building the dataset; the human should decide which.

**Metric:** fraction of candidates within ±5 / ±10 / ±25 frames of the human tag, and
per-video false-positive count (a review list longer than the manual pass is a failure
regardless of precision). **No success/failure accuracy** — the label is read from the
CSV, not predicted.

**Baselines SAM must beat** — if either wins, SAM is not needed:

- NCC steepest-drop: 5 % at ±5 (already measured).
- Existing DLC model's `Wrist`, digit joints and `Pellet` fed to the same Stage-3 head.
  Free to run, trained on this exact rig, 4718 labelled frames.

The DLC baseline is now the **stronger** of the two, and may well win. Restricting scope to
the unoccluded outside-the-glass phase removes occlusion robustness, which was SAM's main
structural edge; and DLC already outputs exactly the landmarks in scope — wrist, twelve
digit joints, pellet. SAM's remaining edge is that a mask's extent is better defined than a
point estimate, and that it is immune to the vane confounder that defeated every
photometric approach tried. Run the DLC baseline first; it is cheap and it may end the
question.

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

**Every stage must render its result on the frame**: Stage 0/1 overlay the pedestal and
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
2. **Checkpoint access is gated** — request it before anything else; it blocks Stage 2.
3. **No masks exist for fine-tuning.** Start zero-shot + a learned head. Only fine-tune if
   that misses, bootstrapping masks by prompting SAM with DLC keypoints.
4. **±5 may be below the human's own tagging noise.** Every trial is tagged once, so it
   cannot be measured from existing data. Re-tag ~30 trials blind and compute
   self-agreement; if the human's own jitter exceeds ±5, the target must move.
5. **Two videos carry no tags** (`banh-mi-1` Jul 3 and Jul 7) — 11 usable, not 13.

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
