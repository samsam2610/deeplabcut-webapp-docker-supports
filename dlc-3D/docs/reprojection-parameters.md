# Reprojection panel — what each parameter does

Reference for the *3D Inline Analysis - Reprojection* card. Numbers quoted are
measured on the `eggtart-1` pair in `RatBox Videos/tdcs/070126`
(251,640 frames × 16 bodyparts, `snapshot_best-180`).

## The idea in one paragraph

One camera is **trusted**. Its marker for a bodypart induces an epipolar line in
the other camera's frame; the same bodypart's marker there should sit on that
line. Distance from the line measures correspondence error. Markers far off the
line are deleted; markers on the line whose DeepLabCut confidence was low are
*rescued* — their likelihood is raised so downstream filters stop discarding
them. Nothing is ever moved: the module only accepts, rejects or re-scores what
DeepLabCut produced.

## Trusted camera

Which camera induces the line. The other is judged and corrected. Per-bodypart
overrides flip this for individual bodyparts, which also flips which camera's
`gate_ref`, `low_tgt` and `rescue_floor` apply.

Pick the better-tracked view. On `eggtart-1` that is cam1 — mean likelihood 0.51
against cam0's 0.39.

## k₁ — trust band, k₂ — reject band

Multipliers, not pixels. Per bodypart, the engine takes frames where **both**
cameras clear their `high_conf`, treats those correspondences as correct, and
measures their spread:

```
t_ok  = median + k₁ × MAD      (default k₁ = 3)
t_bad = median + k₂ × MAD      (default k₂ = 8)
```

MAD (median absolute deviation) is used rather than standard deviation because
the residual distribution has a long tail of genuinely broken correspondences
that would inflate a standard deviation.

Because they are multipliers on each bodypart's own noise, the same k values
produce very different pixel thresholds:

| Bodypart | t_ok | t_bad |
| --- | --- | --- |
| Pellet | 3.30 px | 7.28 px |
| Snout | 5.12 px | 11.37 px |
| MCP-4 | 17.73 px | 38.66 px |
| Wrist | 21.53 px | 45.66 px |

That spread is the point: a single global pixel threshold would either discard
good Wrist data or wave through bad Pellet data.

**Keep k₁ < k₂.** The UI does not enforce it. The code applies REJECT last so an
inverted pair cannot resurrect a bad marker, but a trust band wider than the
reject band is meaningless.

## gate_ref — applies to the TRUSTED camera

Below this likelihood, the trusted camera's own marker is too weak to induce a
line worth believing, so the judged camera's marker is left **completely
untouched** and recorded as `UNJUDGED`.

This is the coverage dial:

- **Raise it** — only very confident markers induce lines. Fewer judgements, more
  `UNJUDGED`, higher confidence in the ones you get.
- **Lower it** — more coverage, but lines induced from shakier reference markers,
  which can reject a perfectly good marker in the other view.

At the default 0.6, `UNJUDGED` was 3,293,909 of 4,026,240 frame × bodypart slots
on `eggtart-1` — most of them frames where the animal is not reaching and neither
camera has a real detection.

## low_tgt — applies to the JUDGED camera

The ceiling for "worth rescuing". A marker below this likelihood that also sits
inside the trust band becomes a **rescue candidate**. A marker at or above it,
inside the trust band, is simply `CONFIRM` — nothing is written.

`low_tgt` has **no effect on rejection**. A marker beyond `t_bad` is deleted
whatever its likelihood.

- **Raise it** — more markers qualify as rescue candidates, so more rescues.
- **Lower it** — only the least confident markers are considered.

## high_conf — applies to EACH camera separately

Used **only** to choose the calibration sample. A frame joins that sample when
each camera independently clears its own `high_conf`. The sample's median and MAD
become `t_ok` and `t_bad`.

**This dial runs the opposite way to intuition.** Lowering a camera's bar admits
sloppier correspondences into the sample, which inflates the median and MAD,
which *widens* both bands. It makes the rule more permissive, not more careful.

Measured, dropping cam0 from 0.9 to 0.7:

| Bodypart | sample @ 0.9 | sample @ 0.7 | t_ok @ 0.9 | t_ok @ 0.7 |
| --- | --- | --- | --- | --- |
| Pellet | 21,138 | 25,986 | 3.30 | 3.34 |
| Snout | 11,792 | 13,436 | 5.12 | 5.28 |
| Wrist | 2,803 | 4,924 | 21.53 | 22.21 |
| MCP-4 | 3,550 | 8,855 | 17.73 | 18.18 |

The legitimate use is a weak camera that rarely clears 0.9, leaving a bodypart
with too small a sample to calibrate from. Watch the `n_hi` and `t_ok` columns:
they show the trade immediately.

**Fallbacks.** Under 200 qualifying frames, a bodypart falls back to a pooled
estimate across all bodyparts; under 200 pooled, to fixed defaults of
`t_ok = 10 px`, `t_bad = 25 px`. The `source` column reports `self`, `pooled` or
`default`. Anything but `self` means that bodypart's thresholds are not
self-calibrated and its verdicts deserve less trust.

## rescue_floor — applies to the JUDGED camera

The likelihood written onto a successful rescue. It uses `max`, so a marker that
already had a higher likelihood keeps it.

Set it above whatever likelihood threshold your downstream filtering uses —
otherwise a rescue will not survive that filter and the rescue achieved nothing.
Setting different floors per camera lets you tell rescued markers apart by which
camera they came from.

## require_peaks — candidate-peak screen

Refuses a `RESCUE` unless exactly one of DeepLabCut's top-K candidate heatmap
peaks for that bodypart sits on the epipolar line. It can only **REFUSE** — no
marker is ever moved, and it cannot turn a `REJECT` or `CONFIRM` into anything
else. Needs a peaks sidecar (`<pose_h5_stem>_peaks.npz`), which "emit peaks"
writes during Analyze-for-tag. A frame with no sidecar coverage is not treated
as failing evidence — it **keeps its geometry verdict** rather than being
refused, because absence of a sidecar is absence of evidence, not evidence of
absence.

On the validation run, 4,031 of 15,191 judged cells had SEVERAL peaks on the
line and 1,028 had the wrong one — 33% of refusals that geometry alone cannot
make at any threshold.

## peak_floor — applies to the JUDGED camera

A candidate peak below this heatmap score does not count as evidence for
`require_peaks`. Same 0–1 scale as likelihood. Set it too high and the screen
degenerates into another `rescue_floor`; set it too low and a hallucinated peak
passes.

**The 0.05 default is unvalidated** — there is no labelled measurement behind
it, unlike every other default on this page. Under occlusion DeepLabCut
typically scores below 0.10, so raising `peak_floor` toward 0.10 refuses more
and rescues less.

## The verdicts

Evaluated per frame, per bodypart, on the judged camera. `REJECT` is applied last
so it wins unconditionally, whatever the bands are set to.

| Verdict | When | Effect |
| --- | --- | --- |
| `UNJUDGED` | trusted marker missing or `≤ gate_ref` | untouched |
| `REJECT` | `d > t_bad` | x, y → NaN; likelihood → 0 |
| `RESCUE` | `d ≤ t_ok`, likelihood `< low_tgt`, passes the 3D gate | coordinates kept; likelihood → `rescue_floor` |
| `RESCUE_REJECTED` | as above but fails the 3D gate | untouched |
| `CONFIRM` | `d ≤ t_ok`, likelihood `≥ low_tgt` | untouched |
| `AMBIGUOUS` | `t_ok < d ≤ t_bad` | untouched |

### The 3D gate

An epipolar line is a one-degree-of-freedom constraint: a marker can sit exactly
on the correct line at a completely wrong depth. Before a rescue is granted, the
pair is triangulated and must land inside that bodypart's working volume and
within a jump limit of the most recent confirmed position. On `eggtart-1` this
refused 8,285 of 133,809 candidates — 6.2%, concentrated in Pellet (58% kept) and
Left-Paw (75% kept), the parts most prone to that failure.

## Reading the counts

Verdict counts in the audit JSON are over **all** frames × bodyparts. Compare
absolute counts, not percentages — the design spec's evidence table used a
smaller denominator (only frames where both cameras had a detection), so the same
result reads as a different percentage there.

Defaults on `eggtart-1`: `CONFIRM` 390,499 · `RESCUE` 125,524 · `REJECT` 106,965
· `AMBIGUOUS` 101,058 · `RESCUE_REJECTED` 8,285 · `UNJUDGED` 3,293,909.

## Persistence

Everything on this panel — trusted camera, k₁, k₂, all eight per-camera values
and any per-bodypart overrides — is saved per project and restored when you
reopen the card. Overrides naming a bodypart the current session does not have
are dropped once the real bodypart list is known.
