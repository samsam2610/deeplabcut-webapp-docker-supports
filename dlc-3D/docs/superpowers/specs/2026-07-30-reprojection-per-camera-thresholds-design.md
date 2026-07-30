# Reprojection — per-camera likelihood thresholds

**Date:** 2026-07-30
**Status:** design approved, not yet implemented
**Module:** `dlc-3D`
**Builds on:** [2026-07-29-inline-3d-reprojection-design.md](2026-07-29-inline-3d-reprojection-design.md)

## Problem

The reprojection panel exposes only `k₁` and `k₂`. The four likelihood knobs —
`gate_ref`, `low_tgt`, `high_conf`, `rescue_floor` — are already accepted by the
endpoints and plumbed into the engine, but the UI never sends them, so they are
stuck at their defaults of 0.6/0.6/0.9/0.9.

Worse, they are single-valued while the two cameras are genuinely asymmetric. On
`eggtart-1` the mean likelihood is 0.39 for cam0 and 0.51 for cam1, so a flat
0.6 means something different for each: it is a mild filter on cam1 and a severe
one on cam0. The same applies to `high_conf` — cam0 clears 0.9 far less often,
so it contributes a much smaller calibration sample than cam1 for the same
nominal bar.

## Scope

1. Every one of the four likelihood parameters becomes settable per camera.
2. All of them, plus `k₁`/`k₂`, the trusted-camera choice and the per-bodypart
   overrides, are exposed in the panel and persisted per project.

### Non-goals

- Changing the verdict rule itself. The decision table, the 3D gate and the
  threshold formula are unchanged.
- Per-bodypart likelihood thresholds. Only per-camera.
- More than two cameras.

## Semantics

Each parameter is looked up by **the camera it actually applies to**. That single
rule makes the behaviour survive per-bodypart reference flips with no special
casing:

| Parameter | Applies to | Resolved from |
| --- | --- | --- |
| `gate_ref` | the **trusted** camera — can its marker induce a reliable line? | that camera's value |
| `low_tgt` | the **judged** camera — is this marker a rescue candidate? | that camera's value |
| `high_conf` | **both** — the "both cameras confident" calibration sample | each camera checks its own |
| `rescue_floor` | the **judged** camera — what likelihood to write on a rescue | that camera's value |

So the calibration mask becomes:

```
hi = isfinite(d) & (lik_ref > high_conf[ref_cam]) & (lik_tgt > high_conf[tgt_cam])
```

A bodypart flipped via a per-bodypart override swaps which camera is trusted, and
therefore automatically swaps which camera's `gate_ref`, `low_tgt` and
`rescue_floor` apply. No extra logic is needed.

### Consequence worth stating plainly

Lowering a camera's `high_conf` **widens** its calibration sample by admitting
sloppier correspondences, which **inflates** that bodypart's `med` and `mad`, and
therefore widens `t_ok` and `t_bad`. It makes the rule more permissive, not more
careful. This is a legitimate dial for a weak camera that rarely clears 0.9, but
it is easy to misread. The `n_hi` and `t_ok` columns in the panel surface the
effect immediately, which is why `Estimate thresholds` must use the same
per-camera values a `Run` would.

## Engine changes

Deliberately small. `classify` and `apply_verdicts` need **no change at all** —
their `gate_ref`, `low_tgt` and `rescue_floor` arguments are already role-scoped,
so `run_reprojection` resolves the right camera's value before calling them.

Exactly one `epipolar_core` function changes:

```python
def auto_threshold(d, lik_ref, lik_tgt,
                   high_conf=0.9,            # back-compat: applies to both
                   high_conf_ref=None,       # overrides high_conf for the reference
                   high_conf_tgt=None,       # overrides high_conf for the target
                   k1=3.0, k2=8.0, min_n=200, pooled=None):
    hr = high_conf if high_conf_ref is None else high_conf_ref
    ht = high_conf if high_conf_tgt is None else high_conf_tgt
    hi = np.isfinite(d) & (lik_ref > hr) & (lik_tgt > ht)
```

Existing callers passing a single `high_conf` keep working unchanged, so the 34
existing `epipolar_core` tests stand.

`reprojection.py` gains one helper and uses it for all four parameters:

```python
def normalize_per_cam(value, default, cam_keys):
    """Accept a scalar (applies to every camera) or {cam_key: value}.

    Returns {cam_key: float} for every key in cam_keys. A dict missing a key
    falls back to `default` for that camera. Raises ValueError on an unknown
    camera key or a value outside [0, 1].
    """
```

`run_reprojection`'s four likelihood parameters accept scalar-or-dict and are
normalized on entry. Per-camera values are recorded in the audit JSON's `config`
block, so a run stays reproducible from its own audit.

## API

`POST /reproject/thresholds` and `POST /reproject/run` accept, for each of
`gate_ref`, `low_tgt`, `high_conf`, `rescue_floor`, either:

```json
0.6                              // scalar — applies to both cameras
{"cam_0": 0.45, "cam_1": 0.6}    // per camera
```

`/reproject/run` accepts all four. `/reproject/thresholds` accepts **only
`high_conf`** (per camera), because that is the only one of the four that feeds
`auto_threshold`: `gate_ref` and `low_tgt` are consumed by `classify`, and
`rescue_floor` by `apply_verdicts`, and neither runs during a threshold estimate.
Accepting the other three there would imply an effect they do not have.

That is also why the preview matches a run: `t_ok`/`t_bad` depend on `high_conf`,
`k₁` and `k₂` alone.

`normalize_per_cam` raises `ValueError` on bad input; the routes catch it and
return **400** with a message naming the offending field. It must never surface
as a 500. Rejected cases:

- a value outside `[0, 1]`
- a camera key not present in the calibration
- a non-numeric value

Bad paths still return 403 as before; validation order is path first, then
arguments.

## Panel

Two per-camera column groups sit under the `k₁`/`k₂` row, always visible:

```
Trusted camera  [cam1 v]
Trust band k₁ [3]   Reject band k₂ [8]

┌─ cam0 ──────────────┐  ┌─ cam1 ──────────────┐
│ gate_ref      0.6   │  │ gate_ref      0.6   │
│ low_tgt       0.6   │  │ low_tgt       0.6   │
│ high_conf     0.9   │  │ high_conf     0.9   │
│ rescue_floor  0.9   │  │ rescue_floor  0.9   │
└─────────────────────┘  └─────────────────────┘
```

Element ids follow `ia3dr-reproj-{cam}-{param}`, e.g.
`ia3dr-reproj-cam0-gate-ref`, `ia3dr-reproj-cam1-rescue-floor`. Inputs are
`type="number"`, `min="0"`, `max="1"`, `step="0.05"`.

`Run` sends all four as per-camera dicts. `Estimate thresholds` sends only
`high_conf` (plus `k₁`/`k₂`) — the others do not affect a threshold estimate,
so sending them would imply an effect they do not have.

Labels keep the engine's parameter names rather than plain-language wording, so
what you set in the panel matches what appears in the audit JSON.

## Persistence

The full run configuration is persisted **per project** under a single
`ui-setting` key, `reproj_params`, following the pattern already used for
`pose3d_view_prefs_reproj` in this card: a debounced 400 ms POST to
`/dlc/project/ui-setting`, best-effort, with failures swallowed.

The key needs no `_reproj` suffix. The suffix convention exists to stop the clone
colliding with keys the *original* card also writes; `reproj_params` is unique to
this card, so there is nothing to collide with.

Stored value (JSON string):

```json
{
  "ref_cam": "cam_1",
  "k1": 3.0,
  "k2": 8.0,
  "gate_ref":     {"cam_0": 0.6, "cam_1": 0.6},
  "low_tgt":      {"cam_0": 0.6, "cam_1": 0.6},
  "high_conf":    {"cam_0": 0.9, "cam_1": 0.9},
  "rescue_floor": {"cam_0": 0.9, "cam_1": 0.9},
  "overrides":    {"Wrist": "ref"}
}
```

- **Saved** on `change` of any of those controls, debounced.
- **Loaded when the card is opened**, not when the panel wires up. The panel
  wires at `DOMContentLoaded`, before any project is selected, and `ui-setting`
  is project-scoped — a load there would query the wrong project or none at all.
  This mirrors `_loadPose3dViewPrefs`, which loads on pose3d load rather than at
  bootstrap. The load completes before any action can run, and absent or
  unparseable data leaves the defaults standing.
- **Overrides are filtered on load.** They are keyed by bodypart name, which is
  model-specific. Entries naming a bodypart absent from the current session are
  dropped rather than sent to the engine, so switching projects or retraining
  cannot resurrect a stale flip.

## Testing

**Engine** (`tests/unit/test_epipolar_core.py`, `tests/test_reprojection_io.py`):

- `normalize_per_cam`: scalar applies to every camera; a dict maps per camera; a
  dict missing a key falls back to the default; an unknown camera key raises; a
  value outside `[0, 1]` raises.
- `auto_threshold` with asymmetric `high_conf`: a lower bar on one camera admits
  a strictly larger `n_highconf` than the symmetric case, and the existing
  single-`high_conf` call signature still behaves identically.
- `run_reprojection` with per-camera `rescue_floor`: a rescued marker in the
  judged view carries that camera's floor, not the other's.

**Routes** (`tests/test_reprojection_routes.py`):

- a dict payload is accepted and reaches the engine with the right shape
  (monkeypatched, no disk touched)
- a value outside `[0, 1]` → 400 naming the field
- an unknown camera key → 400 naming the key

**Panel** (`tests/test_reproj_panel_markup.py`, `tests/test_reproj_panel_wiring.py`):

- the eight inputs exist with the correct defaults and `min`/`max`
- the `Run` payload carries all four as per-camera dicts, and the `Estimate`
  payload carries per-camera `high_conf` but NOT the other three
- the persistence key `reproj_params` is written on change and read on wire-up
- overrides are filtered against the current bodypart list on load

## Risks

- **`high_conf` is a footgun.** Lowering it loosens the rule while feeling like
  tightening it. Mitigated by surfacing `n_hi` and `t_ok` in the same table, not
  by preventing it.
- **Ten inputs invite fiddling.** The defaults are the values validated on real
  data; anything else is the user's own calibration decision. The audit JSON
  records what was used, so a surprising result is always traceable.
- **Persistence hides state.** A run silently inherits whatever was last set for
  this project, including from a previous session. The panel always displays the
  loaded values, and the audit JSON records them, so the state is visible in both
  places rather than implicit.
