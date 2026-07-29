# 3D Inline Analysis — Reprojection

**Date:** 2026-07-29
**Status:** design approved, not yet implemented
**Module:** `dlc-3D`

## Problem

A synced two-camera session is analysed by one DeepLabCut model. One view routinely
tracks worse than the other. Two distinct failure modes hurt downstream triangulation:

1. A marker is placed **wrong** but DLC reports high confidence. The point survives
   every likelihood filter and poisons the 3D reconstruction.
2. A marker is placed **correctly** but DLC reports low confidence. The point is
   discarded by the likelihood filter, and good data is lost.

Neither is detectable from a single view. Both are detectable from stereo geometry:
a point in the trusted view constrains the same bodypart in the other view to an
epipolar line, and distance from that line is a direct measure of correspondence error.

### Evidence

Measured on `eggtart-1` (`RatBox Videos/tdcs/070126`), 251,640 frames × 16 bodyparts,
`snapshot_best-180`, cam1 as reference (mean likelihood 0.51 vs cam0's 0.39):

| Outcome | Points | Share |
| --- | --- | --- |
| Rescued (likelihood < 0.6, geometry confirms) | 133,809 | 8.9% |
| Rejected (likelihood > 0.9, geometrically impossible) | 3,173 | 0.21% |
| Confirmed (confident and agrees) | 196,129 | — |
| Reference too weak to judge | 778,069 | 51.5% |

Calibration quality is high: `calibration.toml` reports RMS 0.074 px, and triangulating
high-confidence Pellet correspondences reprojects at 0.20–0.27 px median. When both views
exceed likelihood 0.9, median epipolar distance is 0.66 px (Pellet) to 5.12 px (Wrist) —
an 8× spread that makes a single global threshold unworkable.

The measurement is also genuinely asymmetric: for the same Pellet points, median distance
is 5.97 px cam0→cam1 but 8.16 px cam1→cam0. Which camera is trusted changes the verdict.

## Scope

Deliver a clone of the existing *3D Inline Analysis* card, named
**3D Inline Analysis - Reprojection**, launched by a button directly below the existing
one in the `dlc-3d` tab. It gains an epipolar reprojection engine that judges the weaker
view's markers against the trusted view and writes corrected 2D h5 files.

The clone is temporary: it will be merged back into the original card once proven.

This spec covers two implementation phases that are sequenced by a hard external
constraint — the container cannot be restarted while in use — and so become two
implementation plans: the engine (verifiable now, no restart) and the card clone (dormant
until a restart is authorised). See Rollout.

### Non-goals

- Moving markers. The module never invents or snaps a position — it only accepts,
  rejects, or re-scores what DeepLabCut produced. An epipolar line is a one-dimensional
  constraint and cannot determine position along itself.
- Re-running inference or reading heatmaps.
- Supporting more than two cameras.
- Changing the original *3D Inline Analysis* card.

## Architecture

```
dlc-3D/src/dlc_3d_bp/
  epipolar_core.py    ← pure math: arrays in, arrays out. No Flask, no anipose, no numba.
  reprojection.py     ← orchestration: load pair → thresholds → verdicts → write artifacts
  routes.py           ← + 4 endpoints
dlc-3D/src/static/
  inline_analysis_3d_reprojection.js    ← clone of inline_analysis_3d.js
  inline_analysis_3d_reprojection.css   ← clone of inline_analysis_3d.css
  card_inline_analysis_3d_reprojection.html  ← card markup, fetched and injected (see Rollout)
dlc-3D/src/templates/
  dlc_3d.html         ← + launcher button, + <link>, + <script>
```

`epipolar_core.py` performs no I/O. That is what makes verdicts testable against the
numbers above without a browser or a running container.

### Dependencies

The `dlc-3d` flask container has `cv2 4.13`, `numpy 2.2`, `pandas 2.3`, `toml`, `tables`,
`scipy`. It does **not** have `numba`, so `anipose_src.cameras` cannot be imported there —
`from numba import jit` fails at module load. The engine therefore reads `calibration.toml`
directly and builds its own camera model. It needs only `matrix`, `distortions`,
`rotation`, and `translation` per camera, all present in the file.

## Geometry

```python
K, dist, rvec, tvec = from calibration.toml, per camera
R_cam = cv2.Rodrigues(rvec)[0]                  # world → camera
R = R_tgt @ R_ref.T                             # reference → target
t = t_tgt - R @ t_ref
E = skew(t) @ R
F = inv(K_tgt).T @ E @ inv(K_ref)               # acts on UNDISTORTED pixel coordinates
```

Points are undistorted with `cv2.undistortPoints(p, K, dist, P=K)`. Passing `P=K` is
required: without it the function returns normalized coordinates, and mixing those with a
pixel-space `F` yields a near-constant residual (~101.7 px for every bodypart) that looks
like data but is not. The distortion vectors in this project are `[k1, 0, 0, 0, 0]`, which
is directly cv2-compatible as `(k1, k2, p1, p2, k3)`.

Epipolar distance for a reference point `x` and target point `x'`, both undistorted and
homogeneous:

```
l = F @ x                        # epipolar line in the target view
d = |l · x'| / sqrt(l₀² + l₁²)   # perpendicular distance, in target-view pixels
```

The same `F` serves the UI: clipping the line `l` against the target image rectangle gives
two endpoints to draw, with no extra machinery.

## Threshold estimation

Thresholds are estimated per bodypart from frames where **both** views exceed likelihood
0.9. Those correspondences are presumed correct, so their residual distribution measures
this session's real geometric noise for that bodypart.

```
med = median(d_highconf)
mad = 1.4826 * median(|d_highconf - med|)
t_ok  = med + k₁ * mad      # k₁ default 3   — trusted band
t_bad = med + k₂ * mad      # k₂ default 8   — reject band
```

`k₁` and `k₂` are exposed as UI controls; changing them recomputes verdicts from cached
residuals without reloading the h5 files.

Fallback chain when a bodypart has fewer than 200 high-confidence frames:

1. Pooled estimate across all bodyparts.
2. If still under 200 frames pooled, a fixed default of `t_ok = 10 px`, `t_bad = 25 px`.

Either fallback sets `threshold_source` to `pooled` or `default` in the audit, so a
bodypart whose thresholds were never really calibrated is visible rather than silent.

Observed auto-thresholds on `eggtart-1` span `t_ok` = 3.3 px (Pellet) to 21.5 px (Wrist).

## Verdicts

### Parameters

Four independent likelihood knobs, all separately configurable. They are listed explicitly
because three of them default to values that coincide, which would otherwise read as one
setting used in several places.

| Name | Default | Role |
| --- | --- | --- |
| `gate_ref` | 0.6 | Below this, the reference point cannot induce a line; target is left alone |
| `low_tgt` | 0.6 | Below this, a target point is a rescue candidate |
| `high_conf` | 0.9 | Threshold-estimation only: what counts as "both views confident" |
| `rescue_floor` | 0.9 | Likelihood written to a successful rescue |

### Decision table

Computed per frame, per bodypart, for the **target** view only. The reference view is
never modified. Rows are evaluated in order and the first match wins, so `REJECT` takes
precedence over every other outcome.

| # | Verdict | Condition | Effect on output h5 |
| --- | --- | --- | --- |
| 1 | `UNJUDGED` | reference point is NaN, or `lik_ref ≤ gate_ref` | unchanged |
| 2 | `REJECT` | `d > t_bad` | `x`, `y` → NaN; `likelihood` → 0 |
| 3 | `RESCUE` | `d ≤ t_ok` and `lik_tgt < low_tgt` and passes 3D gate | `x`, `y` kept; `likelihood` → `max(lik_tgt, rescue_floor)` |
| 4 | `RESCUE_REJECTED` | `d ≤ t_ok` and `lik_tgt < low_tgt` and fails 3D gate | unchanged |
| 5 | `CONFIRM` | `d ≤ t_ok` and `lik_tgt ≥ low_tgt` | unchanged |
| 6 | `AMBIGUOUS` | `t_ok < d ≤ t_bad` | unchanged |

`REJECT` is deliberately independent of `lik_tgt`: a geometrically impossible point is
removed whatever DLC thought of it. The 3,173 figure in Evidence was measured with the
stricter `lik_tgt > 0.9` filter to isolate the confidently-wrong case for illustration; the
implemented rule rejects more than that.

The `gate_ref` cut excluded 51.5% of points on `eggtart-1`. That is correct behaviour — in
roughly half the frames the animal is not reaching and neither view has a real detection —
but it means the module's coverage is bounded by the trusted view's quality.

`AMBIGUOUS` and `RESCUE_REJECTED` deliberately do nothing, leaving the normal likelihood
filter in charge rather than forcing a binary call on a genuinely uncertain point.

Verdict codes stored in the npz: `0 UNJUDGED`, `1 REJECT`, `2 RESCUE`, `3 RESCUE_REJECTED`,
`4 CONFIRM`, `5 AMBIGUOUS`.

### The 3D plausibility gate

Applied to `RESCUE` candidates only.

A point can sit exactly on the correct epipolar line and still be badly wrong along it —
the constraint has one degree of freedom, so "on the line" for the Wrist means a 43 px-wide
band on an 800×600 image. Without a second test, rescues would raise the likelihood of
points that are on the right line at the wrong depth, which is worse than leaving them
low-confidence.

The gate DLT-triangulates the (reference, target) pair from undistorted normalized
coordinates and requires both:

- **Working volume.** The point lies inside the axis-aligned box spanned by the 1st–99th
  percentile of that bodypart's `CONFIRM` triangulations, expanded by 20% per axis.
- **Jump limit.** Distance from the last accepted 3D position of that bodypart is at most
  `v₉₉ × frame_gap`, where `v₉₉` is the 99th percentile of frame-to-frame 3D speed in the
  `CONFIRM` population. If no accepted position exists within 10 frames, this test is
  skipped and the volume test alone decides.

A candidate failing the gate is recorded as `RESCUE_REJECTED` and left untouched, not
deleted.

### Reference selection

A session-level trusted camera, with per-bodypart overrides. A run caches residuals in
**both** directions plus the triangulated 3D point per frame and bodypart. Triangulation is
direction-independent, and residuals for both directions are already computed, so flipping
the reference camera or a per-bodypart override re-derives verdicts and re-runs the 3D gate
from those cached arrays without rereading the h5 files.

## Outputs

Written beside the source h5 files.

### `<stem>_reprojected.h5` — both cameras

Both views get an output file. The reference camera's file is a faithful copy with
unchanged values. This is required, not cosmetic: `_resolve_sibling_h5` in `routes.py:197`
pairs files by substituting the `_cam{N}_` token in the **basename only**, so the two files
must be identical apart from that token for the inline 3D viewer to auto-discover the pair.

The writer mirrors the source file's storage contract exactly, read back at run time rather
than assumed. For this project's files that is HDF5 key `df_with_missing`, `format="table"`,
`float32` columns, plain integer index, and column level names
`['scorer', 'bodyparts', 'coords']`. Mirroring rather than hardcoding avoids the
fixed-vs-table HDF5 trap already recorded in the regression catalog.

### `<stem>_reprojected.json` — audit summary

Run configuration (reference camera, per-bodypart overrides, `k₁`, `k₂`, gates, floors,
source h5 paths, calibration path), and per bodypart: `med`, `mad`, `t_ok`, `t_bad`,
`threshold_source`, and counts for every verdict including `RESCUE_REJECTED`.

### `<stem>_reprojected.npz` — per-frame arrays

Per bodypart: residual `d` as `float32` for both directions, verdict code as `uint8`, and
the triangulated 3D point as `float32`. This exists so the timeline and epipolar overlay
render without recomputing, and so a reference-camera flip is cheap. JSON is not viable at
251,640 frames × 16 bodyparts.

## API

All under the existing `dlc-3d` blueprint.

| Endpoint | Purpose |
| --- | --- |
| `POST /reproject/thresholds` | Given a pair of h5 paths and a calibration path, return per-bodypart residual statistics and auto-thresholds. No files written. Populates the UI before a run. |
| `POST /reproject/run` | Full pass: verdicts, 3D gate, write the three artifacts. Returns verdict counts and output paths. |
| `GET /reproject/audit` | Serve a previous run's JSON summary and npz arrays for the timeline and overlay. |
| `GET /reproject/epiline` | For one frame and bodypart, return the epipolar line's two clipped endpoints in target-view pixel coordinates for live drawing. |

All path arguments are validated to resolve under `/user-data/`, matching the existing
route guards.

## UI clone

A byte-for-byte clone of the existing card, renamed, then extended.

The rename is mechanical and safe: 227 unique `ia3d-` element ids, all CSS classes
prefixed `.ia3d-`, and no `localStorage` or `sessionStorage` anywhere in the source — all
persistence is server-side. Renaming `ia3d-` → `ia3dr-` across markup, JS and CSS is
therefore complete.

The launcher button is defined in `dlc_3d.html` and relocated at runtime by the JS into the
shared launcher nav list, which lives in a main-webapp partial this module cannot edit. The
clone replicates that relocation and inserts itself directly below the original button.

### Approved divergences from byte-for-byte

The card calls 38 endpoints, most of them main-webapp routes under `/dlc/`. A pure clone
would share all of that server state with the card people are actively using. Two
divergences are required:

1. **Namespaced UI settings.** `ui-setting` keys are per-project, so `pose3d_bg_color` and
   `pose3d_view_prefs` would silently be the same setting in both cards. The clone suffixes
   its keys (`pose3d_bg_color_reproj`, `pose3d_view_prefs_reproj`).
2. **No cross-session stop.** `/dlc/project/inline-analysis/session/stop` is keyed by
   `snap_key`. The clone must refuse to stop a session it did not start itself, or it can
   kill a warm session out from under the original card. Stale `inline:session` state is a
   known hang in this project.

Everything else — including triangulate runs appearing in the shared Jobs card — stays
shared, which is the intended behaviour.

### New reprojection panel

Added to the cloned card:

- Reference camera selector, with per-bodypart overrides.
- `k₁` / `k₂` controls showing the resulting per-bodypart thresholds live.
- Run button, writing the three artifacts.
- Epipolar lines drawn on the target tile, sourced from the audit npz.
- Verdict counts, and a timeline banded by verdict.

## Testing

`epipolar_core.py` is pure and gets unit tests with synthetic cameras where ground truth is
known: a point triangulated from a known 3D position must have zero epipolar residual;
a point displaced by δ perpendicular to the line must have residual δ; threshold estimation
on a synthetic distribution must recover the injected median and MAD.

Integration tests run against a duplicate of the `070126` session containing only the two
h5 files and `calibration.toml` — not the 9 GB videos — copied into scratchpad. The
original data is never written to. Assertions: output MultiIndex, HDF5 key, storage format
and dtypes match the source; `REJECT` points are NaN with likelihood 0; `RESCUE` points
retain their coordinates with likelihood ≥ 0.9; every rescued point's triangulation lies
inside the working volume; verdict counts are consistent with the figures in Evidence.

Tests run under the existing `dlc-3D/pytest.ini`, whose cleanup hooks are mandatory — this
project has previously leaked 614 GB into `/tmp` from unhooked test runs.

## Rollout

The `dlc-3d` container must not be restarted while it is in use. Current mounts determine
what can be verified before then:

| Mount | Effect |
| --- | --- |
| `src/static/` — whole directory | new JS, CSS and HTML fragments appear live, no restart |
| `src/dlc_3d_bp/` — whole directory | files appear, but gunicorn must reload to register routes |
| `templates/partials/*.html` — file by file | a new partial is invisible without a compose edit |

The card markup therefore lives in `src/static/` as an HTML fragment that the cloned JS
fetches and injects into `<main class="cards">`, rather than as a Jinja include. This
avoids a `docker-compose.yml` edit entirely and makes every subsequent markup, JS and CSS
change live-reloading. The cost is that this one file diverges from the include-based
pattern and must be moved into a partial when the clone is merged back.

**Phase 1 — no restart.** Build and validate the engine. Run it via `docker exec` into the
`dlc-3d` container, the real target environment, against the scratchpad copy of the
session. Produces real verdict numbers and real output files with zero disruption.

**Phase 2 — built but dormant.** Clone the card, JS and CSS; wire the button and routes.
Nothing takes effect until `docker compose up -d dlc-3d`, triggered when the tool is idle.

## Risks

- **Coverage is bounded by the trusted view.** Half of all points on `eggtart-1` had no
  usable reference. The module improves what it can judge and is silent elsewhere.
- **A wrong reference produces confidently wrong verdicts.** If the trusted camera's point
  is misplaced but confident, the epipolar line is wrong and a correct target point can be
  rejected. The 0.6 gate mitigates but does not eliminate this.
- **Threshold estimation assumes high-confidence agreement means correctness.** A bodypart
  that DLC gets confidently and consistently wrong in both views would inflate its own
  threshold. The `threshold_source` field and per-bodypart statistics make this inspectable.
- **168 KB of duplicated JavaScript** must be kept in sync while both cards exist. This is
  accepted deliberately to keep the working card untouched, and is bounded by merging the
  clone back once proven.
