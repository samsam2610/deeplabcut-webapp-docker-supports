# Methodology

How `sam-training` proposes reach-onset frames, why each stage is built the way
it is, and what has been measured rather than assumed.

Companion to `README.md` (what it is) and the design docs under
`docs/superpowers/specs/` (how each decision was reached).

---

## 1. The problem, stated precisely

During an experiment the outcome of each reach is keyed **live** as an `s` or
`f` note in the video's companion CSV. Afterwards someone must go back and
hand-place the **onset** frame of each reach — roughly 85 per video, about
0.03 % of a 252 000-frame recording.

**That retrospective hunt is the only thing automated here.**

Three constraints follow, and every design decision below serves them.

**Success and failure are never predicted.** A candidate's label is read off the
human `s`/`f` marker that closes its window. No marker, no candidate. The
outcome is a human input, known before the search starts, so using it is not
leakage.

**The delay from onset to marker is not fixed.** It is keyed by hand during the
experiment: median 372 frames, p90 1080, p99 2217, max 2926. Anything assuming a
constant offset is wrong.

**Output is a candidate, not a decision.** Everything ends at a human confirming
or rejecting a proposed frame. Accuracy is judged as ±5 frames against the
human's own tag.

### Vocabulary

| note | meaning |
|---|---|
| `s` / `f` | outcome, keyed live during the experiment |
| `start-success` / `start-failure` | the human's onset tag, placed afterwards |
| `start-*-candidate` | this tool's proposal |

Matching is **exact** everywhere, so `start-failure` never picks up
`start-failure-2` or our own `start-failure-candidate`.

### Which videos

The working set is not "every video in `videos/`". It is the tracked files in
`tracked_files.sqlite` whose **`Tag` segment is `Done`** — those supply
exemplars. Videos whose `Tag` is anything else are the *targets*. Getting this
wrong silently pulls untagged videos into training.

---

## 2. Stage 0 — the pellet template

A reach can only be a reach if a pellet was sitting there to reach for. Finding
the pellet is therefore the gate on everything downstream, and it is done with
plain normalised cross-correlation, not a network.

**The template is DLC-derived.** 44×44 px, pooled from 261 labelled pellet
positions across the project, held per camera. It is a *pool*: an immutable seed
from the DLC labels plus user clicks, weighted-averaged. Clicks add to the pool
rather than replacing it.

**The search box is placed by a human, per video pair.** One click on the
stationary pellet in each camera. Sweeping is blocked until both are placed and
confirmed, because a wrong box does not fail loudly — it fills the candidate
mask with paws and costs a seven-minute sweep to discover.

> **Why not a canonical template and a wide search band?** That was the first
> implementation and it is instructive. The canonical template was 60×90 px,
> ~86 % dark pedestal with the pellet clipped, slid over a 140×160 band. It
> matched a **paw resting on the pedestal at 0.85**, and blank background beside
> the pedestal at 0.64 — on frames with no pellet at all.

On Confirm, the template is scored where the box was placed and the result
reported. A box that cannot clear the threshold arms nothing, and without this
check the first sign of that is a multi-minute sweep returning candidates with
no pellet on them.

---

## 3. Stage 1 — the two-camera sweep

Every 5th frame of **both** cameras is scored against that camera's template. A
frame is armed — "a stationary pellet is present" — only if all three hold:

1. cam0 matches above `pellet thr`
2. cam1 matches above `pellet thr`
3. the two match positions **triangulate** to within `3D gate` of the reference
   pellet point

(3) is what earns its place. Measured on the frame that prompted this design:

| frame | what is there | one camera | cam0 | cam1 | 3D dist | verdict |
|---|---|---|---|---|---|---|
| 27591 | empty background | 0.643 armed | 0.553 | 0.673 | 8.29 | reject |
| 27621 | a paw on the pedestal | 0.849 armed | 0.678 | 0.600 | 14.09 | reject |
| 28496 | the pellet | — | 0.891 | 0.902 | 0.29 | **arm** |

Both cameras clear threshold on the paw frame. **Only the 3D gate rejects it.**
Two views agreeing in 2D is weaker evidence than two views agreeing in 3D.

Effect on one video: armed samples 19 843 → 5 078, candidate frames
161 398 → 24 634.

### The reference pellet point

Derived per pair by triangulating the human's **placed box** — already required
before sweeping, and by definition the stationary pellet in both views.

It used to be a project-level constant, which cannot survive a calibration
change: a 3D coordinate only means something in the frame that produced it.
Moving one session onto its own calibration pushed the triangulated pellet from
0.48 to **29.30** away from the stored reference, which would have failed every
pellet against a 2.0 gate.

Verified: frames with a pellet land 0.20–1.02 from the derived reference, frames
without 2.31–9.81.

### Debouncing

A state flip must persist `debounce` consecutive samples. The paw and the body
transiently occlude the pedestal and the white reload vane sweeps through;
without this, each is a spurious edge. Set to 6 samples (30 frames at stride 5).
It was 20, which eroded short armed stretches and cost 12 of 82 onsets on the
worst session.

### Storage

The sweep stores **raw** per-camera scores and the 3D distance — never the armed
decision. Thresholds are applied afterwards, so retuning re-judges in under a
second instead of costing another seven-minute pass. Measured: 0.75 s to
re-judge a whole video.

---

## 4. Trial windows

One search window per outcome marker. It **closes** at the marker and **opens**
at `max(marker − lookback, previous marker + 1 − guard)`.

The second term is not optional. Without it:

| | |
|---|---|
| windows reaching back past the previous marker | **1215 / 1309 (92.8 %)** |
| candidate frames on the wrong side of a marker | **64 592 / 161 398 (40 %)** |

A candidate before an intervening marker is followed by *that* marker, so its
outcome belongs to that trial. This is how a failed reach was labelled
`start-success`: its window reached back over an `f` and took its label from an
`s` 1379 frames later.

At `guard = 0` the invariant holds by construction — for every frame in a
window, the window's own marker is the next marker. Cost, measured: onset
reachability 100 % → **98.77 %** (16 of 1304 paired trials, where the human keyed
the previous marker after the next reach had already begun). Raising `guard`
recovers those at the price of the guarantee; ambiguous windows are flagged.

Only pellet-stationary frames inside the window are candidates, and a window
with fewer than `min cand` of them is skipped as unsearchable.

---

## 5. Stages 2 and 3 — SAM 3 and DINOv3

Two modes, sharing everything except how many cameras they use.

### DINOv3 similarity — the learned part

Each candidate frame is cropped to a fixed rectangle **anchored on that camera's
pellet centre**, embedded with DINOv3, and compared to a bank of exemplars
embedded from human onset frames. The highest similarity wins.

The crop is wide enough to contain the aperture and the pedestal, so the
embedding captures *paw relative to pellet* rather than just paw. Anchoring
means each camera derives its own crop — cam1's pellet sits 177 px right of
cam0's, so one fixed rectangle frames the wrong part of cam1 entirely.

**Exemplars are label-matched**: a trial closing on `f` is scored only against
`start-failure` onsets. DINOv3 is frozen and has never seen this rig, so holding
a session's exemplars out is sufficient to hold that session out — there is no
training-contamination problem to reason around.

The cam1 bank is built from the **same human onset frames** read out of the
frame-synced sibling video. It costs no new human labelling.

> `bfloat16`, never `fp16`. In fp16 the embeddings come out all-NaN, `argmax`
> over NaN returns index 0, and the result reads as "the method does not work"
> rather than as a numerical fault.

### SAM 3 — the paw, and the geometry

SAM 3 segments the frame from a text prompt and returns every paw it can see —
typically three or four. The **mask centroid** is the paw's position: one splayed
digit moves a bounding box far more than it moves the mass, and this point is
about to be compared across two views that see different silhouettes.

**cam1's paw is chosen by cam0's epipolar line**, not picked independently.

This is the single most important detail in stages 2–3. The first implementation
picked each camera's paw independently — nearest that camera's pellet — and then
tested whether they agreed. At the **onset**, the frame this tool exists to find,
the emerging paw is small and cam1's nearest-to-pellet instance is a different
paw entirely:

| frame | independent | epipolar-constrained | rank of the correct instance in cam1 |
|---|---|---|---|
| 24041 | 176.6 px | **2.7** | 3 |
| 24045 | 189.0 px | **5.7** | 2 |
| 24046 | 179.8 px | **1.3** | 3 |

On one trial that rejected **113 of 121 candidates**, including the
highest-scoring frame in the window. The correct instance was in SAM's output
the whole time, at rank 2. Geometry now *chooses* rather than vetoes, and a
rejection finally means something: no instance in cam1 lies near the line, so
that camera genuinely does not see this paw.

### The prompt matters

`"paw"` over-detects. With ~3 instances per frame, a small blob at the pellet can
outrank the obvious paw slightly further away, because the reaching paw is picked
by distance to the pellet.

| prompt | instances (cam0/cam1) | paw drawn, cam0 | cam1 |
|---|---|---|---|
| `paw` | 15 / 20 | 3/5 | 3/5 |
| `right paw` | 5 / 10 | **5/5** | **5/5** |

Default `right paw`, editable per project — the reaching paw is not the right
paw for every animal. Note this changed *segmentation quality*, not the pick:
same frame, same top five, same order.

### 2D versus 3D

| | 2D | 3D |
|---|---|---|
| cameras scored | cam0 | both |
| paw selection | nearest pellet | cam0 nearest pellet, cam1 by epipolar line |
| candidate score | cam0 DINO similarity | mean of the two |
| geometric gate | none | epipolar residual within `epipolar tol` |
| 3D track written | no | yes |
| cost | ~15 s/trial | ~35 s/trial |

`mean`, not `min`: the paw is transiently occluded in one view on many frames,
and `min` lets either view veto a frame the other is certain about. Wrong-paw
matches are the epipolar gate's job, not the score's.

---

## 6. The judging parameters

All seven are per-project, stored in `sam_training_judge.json`, and applied to
the **stored raw sweep** — so changing any of them re-judges in under a second.

| parameter | default | what it does |
|---|---|---|
| `pellet thr` | 0.55 | NCC each camera must reach for the pellet to count |
| `debounce` | 6 | samples a state flip must persist |
| `lookback` | 3000 | how far a window reaches back from its marker |
| `min cand` | 30 | armed frames below which a trial is skipped |
| `past prev marker` | 0 | frames a window may reach past the previous marker |
| `3D gate` | 2.0 | max distance of the triangulated **pellet** from the reference |
| `epipolar tol` | 20 px | max off-line distance for the cam1 **paw** |

Both sides clamp identically — the panel mirrors the Python clamp, and a test
asserts the same default numbers on both, so retuning one side fails on the
other.

### How `epipolar tol` was set, and two ways it was set wrongly

Worth recording, because the failure mode is subtle and repeated.

The quantity that matters is the epipolar residual of a **SAM mask centroid**
between the two views. It was twice estimated from a stand-in:

1. **`Left-Paw`** gave 20 px. But `Left-Paw` is a **decoy label**, placed
   randomly to stop DLC labelling that paw's joints — it measured random
   placement, not geometry.
2. **The centroid of the real digit joints** gave 15 px. Anatomically
   corresponding, but a SAM mask includes the forearm and each view sees a
   different amount of it, worth about 2×.

Measured directly — mask centroids on 55 frames where both views verifiably
picked the correct paw, under that session's own calibration — p50 3.39 px,
**p95 17.80 px**. Hence 20.

Dwarfing both mistakes: **using another session's calibration**, which alone
moves the same pairs from p50 0.78 px to p50 27.8 px.

---

## 7. Calibration

Anipose stereo calibrations live per session in `labeled-data/*/calibration.toml`.
The nearest one is chosen for each recording: same session if it has one, else
the same animal on the nearest date, else the nearest date.

This used to take the last path *alphabetically* under a docstring claiming "the
most recent", so a July session was triangulated with a different animal's May
calibration. It is the single largest error found in the 3D gates.

The chosen calibration is part of the sweep's cache key, because the 3D distance
is triangulated with it during the sweep — switching calibrations must miss the
cache rather than silently reuse old distances.

---

## 8. Artefacts

| file | holds | keyed by |
|---|---|---|
| `<video>.csv` | the experimental record: notes, sensor status | — |
| `<video>_onset.csv` | every signal behind an armed decision, plus human box/pellet placements | frame |
| `<video>_motion3d.csv` | triangulated marker tracks | (frame, source, marker) |
| `sam_training_pellet.json` | per-camera template pool and geometry | project |
| `sam_training_judge.json` | the seven judging parameters | project |
| sweep cache (`.npz`) | raw per-camera scores and 3D distance | video + detector signature |

**The companion CSV is the experimental record.** Pipeline signals go in a
sidecar so a bad run is deleted with `rm` rather than repaired, and the record
can never be corrupted by a rewrite.

`<video>_motion3d.csv` is tidy long format — one row per `(frame, source,
marker)` — so a new marker or a new segmenter is new **rows**, never a schema
change, and a re-run replaces only its own rows. Rejected frames are written too,
with their residual: a decision without its inputs cannot be diagnosed from the
file.

### Cache invalidation

A cache that looks fresh but is not is worse than no cache. The sweep key covers
the box position, template pool, per-camera geometry, thresholds and the
calibration. Judging parameters are deliberately **excluded** — they are applied
to the stored trace, so tuning one must not cost a re-sweep.

### One index base

Every frame number the pipeline hands out is a **1-based companion-CSV
`frame_number`**. The sweep counts video frames from 0; the conversion happens
once, at the pipeline boundary. Only the video seek and the thumbnail endpoint
convert back.

Before this, armed intervals (0-based) were compared against outcome markers
(1-based), so every armed interval sat a frame adrift of the trial it belonged
to, and a run's JSON disagreed with its own sidecar about which frame was which.

---

## 9. What is measured, and what is not

**Measured**

- pellet detection: the numbers in §3
- window boundaries: §4
- `epipolar tol`: §6
- cam1 paw selection, before it was trusted: 0/25 missed paws, p50 14.3 px from
  the labelled joint centroid, 88 % within 30 px — not worse than cam0
- SAM 0.067 s/frame, DINOv3 ~0.02 s/frame batched

**Not measured — the important gap**

**End-to-end acceptance is unknown.** An early figure of 98.9 % was recall-only,
which rewards over-admitting, and is void regardless: the detector has changed
several times since. No recall or precision number for the current pipeline
should be quoted until a leave-one-session-out run over the tag-done videos has
been done.

---

## 10. Known limits

- **`choose_reaching_paw` ranks by distance to the pellet alone**, so a spurious
  blob at the pellet can outrank the real paw. `right paw` suppresses the
  symptom by producing fewer blobs; it does not fix the rule. Mask area or SAM's
  own confidence would be a better tie-break — but cam0's choice feeds the
  epipolar line, so changing it moves everything.
- **Stage 0 does not locate the aperture.** The configured box is an unvalidated
  guess and is deliberately *not* used as a filter: when it was, it rejected
  every correct paw, because the guess spans y 150–320 while the reaching paw at
  the pellet spans y 341–449.
- **Per-session spread in `epipolar tol`** is real — one session reaches p95
  17.97, above the default — which is why it is a tunable field.
- **Two sessions have a dead hardware reach sensor**, so `frame_line_status`
  edges are a bonus signal, never a requirement.
