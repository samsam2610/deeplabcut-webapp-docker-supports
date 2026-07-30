# Per-Camera Likelihood Thresholds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all four likelihood parameters settable per camera, expose them in the reprojection panel, and persist the whole run configuration per project.

**Architecture:** Each parameter resolves by *the camera it applies to*, so per-bodypart reference flips need no special casing. `classify` and `apply_verdicts` are unchanged — their arguments are already role-scoped, so `run_reprojection` resolves the right camera's value before calling them. Only `auto_threshold` changes, gaining optional per-side `high_conf`.

**Tech Stack:** Python 3.9-compatible, numpy, pandas, Flask; vanilla ES modules; pytest.

## Global Constraints

- **Python 3.9-compatible syntax.** Host pytest runner is 3.9.23, container is 3.10.20. Quote any `X | Y` annotation.
- **`epipolar_core.py` imports only `numpy`, `cv2` and stdlib `dataclasses`.** Do not add imports.
- **Never modify the live original card:** `src/templates/partials/card_inline_analysis_3d.html`, `src/static/inline_analysis_3d.js`, `src/static/inline_analysis_3d.css`.
- **Backward compatibility is required.** Every parameter must still accept a bare scalar, because the existing route tests and `scripts/verify_reprojection.py` pass scalars. A change that breaks them is a defect.
- **Baseline is not clean.** Ten tests already fail on this host for unrelated reasons (numpy 2.x `isinstance(np.int64, int)`, absent playwright browser, ffmpeg-dependent LP tests):

  - tests/e2e/test_analyzed_viewer.py::test_card_opens_and_lists_project_content[chromium]
  - tests/e2e/test_sync_frame.py::test_f2_focus_swap_then_marker_routes_to_sibling[chromium]
  - tests/test_inline_analysis_3d_ui_isolation.py::test_finalize3d_confirms_before_overwrite
  - tests/test_lp_csv_to_h5.py::test_csv_to_h5_writes_table_format
  - tests/test_lp_csv_to_h5.py::test_emit_h5_sidecars_filters_metric_csvs
  - tests/test_lp_predict_pairing.py::test_transcode_skips_when_mp4_exists
  - tests/test_lp_predict_pairing.py::test_transcode_invokes_ffmpeg_stream_copy
  - tests/test_lp_predict_pairing.py::test_transcode_falls_back_on_copy_failure
  - tests/test_lp_predict_pairing.py::test_prepare_predict_inputs_end_to_end_multiview
  - tests/test_lp_predict_pairing.py::test_prepare_predict_inputs_singleview_transcodes_only

  A run is clean when these ten — and only these ten — fail.
- Run tests from `dlc-3D/` with `python3 -m pytest`.

## THE CARD IS LIVE — task order is a safety constraint

The `dlc-3d` container is running and in use. `src/static/` is a bind mount, so
**frontend changes take effect on the next browser reload**, while Python changes
need a gunicorn restart.

That makes the order load-bearing. If the panel shipped first, it would send
per-camera dicts to a backend still doing `float(...)` on them — a `TypeError`,
surfacing as a 500 for anyone who clicks Run.

**Tasks 1–4 (backend) → Task 5 (restart) → Tasks 6–7 (frontend).** Do not reorder.
Tasks 6–7 need no restart; a browser reload picks them up.

## Camera-role resolution (the core rule, used in Task 3)

`ref_cam_key` is the session-level trusted camera and `tgt_cam_key` the other.
For a bodypart, `flipped = overrides.get(bp) == "ref"` swaps the roles:

```python
role_ref = tgt_cam_key if flipped else ref_cam_key   # induces the epipolar line
role_tgt = ref_cam_key if flipped else tgt_cam_key   # is judged and corrected
```

Then `gate_ref` comes from `role_ref`, `low_tgt` and `rescue_floor` from
`role_tgt`, and `high_conf` from each side separately.

## File Structure

| File | Change |
| --- | --- |
| `src/dlc_3d_bp/epipolar_core.py` | `auto_threshold` gains `high_conf_ref` / `high_conf_tgt` |
| `src/dlc_3d_bp/reprojection.py` | new `normalize_per_cam`; `run_reprojection` resolves per camera |
| `src/dlc_3d_bp/routes.py` | both POST routes accept scalar-or-dict, 400 on bad input |
| `src/static/card_inline_analysis_3d_reprojection.html` | two per-camera column groups |
| `src/static/inline_analysis_3d_reprojection.js` | send per-camera values; persist config |
| `src/static/inline_analysis_3d_reprojection.css` | styles for the column groups |
| `tests/unit/test_epipolar_core.py` | per-side `high_conf` |
| `tests/test_reprojection_io.py` | `normalize_per_cam`, per-camera `rescue_floor` |
| `tests/test_reprojection_routes.py` | dict payloads, validation |
| `tests/test_reproj_panel_markup.py` | the eight inputs |
| `tests/test_reproj_panel_wiring.py` | payload shape, persistence |

---

### Task 1: `auto_threshold` per-side `high_conf`

**Files:**
- Modify: `src/dlc_3d_bp/epipolar_core.py` (`auto_threshold`, currently line ~224)
- Test: `tests/unit/test_epipolar_core.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `auto_threshold(d, lik_ref, lik_tgt, high_conf=0.9, high_conf_ref=None, high_conf_tgt=None, k1=3.0, k2=8.0, min_n=200, pooled=None) -> dict` with the same return keys as today (`med`, `mad`, `t_ok`, `t_bad`, `n_highconf`, `threshold_source`).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_epipolar_core.py`:

```python
def test_auto_threshold_accepts_per_side_high_conf():
    """The two cameras can require different confidence bars. Lowering one
    camera's bar admits strictly more frames into the calibration sample."""
    d = np.full(1000, 2.0)
    lik_ref = np.full(1000, 0.95)      # reference is confident
    lik_tgt = np.linspace(0.5, 1.0, 1000)  # target spans the range

    both_09 = auto_threshold(d, lik_ref, lik_tgt, high_conf=0.9, min_n=1)
    tgt_07 = auto_threshold(d, lik_ref, lik_tgt, high_conf=0.9,
                            high_conf_tgt=0.7, min_n=1)
    assert tgt_07["n_highconf"] > both_09["n_highconf"]


def test_auto_threshold_per_side_defaults_to_the_shared_value():
    """Omitting a per-side value must reproduce the single-high_conf behaviour
    exactly — the existing callers and verification script rely on it."""
    rng = np.random.default_rng(3)
    d = np.abs(rng.normal(0.0, 2.0, 2000)) + 1.0
    lik = rng.uniform(0.5, 1.0, 2000)
    a = auto_threshold(d, lik, lik, high_conf=0.85)
    b = auto_threshold(d, lik, lik, high_conf=0.85,
                       high_conf_ref=None, high_conf_tgt=None)
    assert a == b


def test_auto_threshold_per_side_gates_each_camera_independently():
    """A frame counts only if EACH camera clears its OWN bar."""
    d = np.array([1.0, 1.0, 1.0, 1.0])
    lik_ref = np.array([0.95, 0.95, 0.60, 0.60])
    lik_tgt = np.array([0.95, 0.60, 0.95, 0.60])
    # ref must clear 0.9, tgt only 0.5 -> rows 0 and 1 qualify.
    st = auto_threshold(d, lik_ref, lik_tgt,
                        high_conf_ref=0.9, high_conf_tgt=0.5, min_n=1)
    assert st["n_highconf"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -k per_side -v`
Expected: FAIL — `auto_threshold() got an unexpected keyword argument 'high_conf_tgt'`

- [ ] **Step 3: Write minimal implementation**

In `src/dlc_3d_bp/epipolar_core.py`, change the signature and the `hi` mask:

```python
def auto_threshold(
    d: np.ndarray,
    lik_ref: np.ndarray,
    lik_tgt: np.ndarray,
    high_conf: float = 0.9,
    high_conf_ref: "float | None" = None,
    high_conf_tgt: "float | None" = None,
    k1: float = 3.0,
    k2: float = 8.0,
    min_n: int = 200,
    pooled: "dict | None" = None,
) -> dict:
```

and replace the mask:

```python
    # Each camera clears its OWN bar. high_conf remains the shared default so
    # existing single-value callers behave identically.
    hr = high_conf if high_conf_ref is None else high_conf_ref
    ht = high_conf if high_conf_tgt is None else high_conf_tgt
    hi = (
        np.isfinite(d)
        & (np.asarray(lik_ref, dtype=float) > hr)
        & (np.asarray(lik_tgt, dtype=float) > ht)
    )
```

Leave the rest of the function untouched, including the docstring body below the summary line — add one sentence noting the per-side override.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py -v`
Expected: PASS, 37 tests (34 existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/epipolar_core.py dlc-3D/tests/unit/test_epipolar_core.py
git commit -m "feat(reprojection): per-side high_conf in auto_threshold"
```

---

### Task 2: `normalize_per_cam` helper

**Files:**
- Modify: `src/dlc_3d_bp/reprojection.py`
- Test: `tests/test_reprojection_io.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize_per_cam(value, default, cam_keys) -> "dict[str, float]"`. Accepts a scalar or a `{cam_key: number}` dict. Raises `ValueError` on an unknown camera key, a non-numeric value, or a value outside `[0, 1]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reprojection_io.py`:

```python
from dlc_3d_bp.reprojection import normalize_per_cam

CAMS = ("cam_0", "cam_1")


def test_normalize_per_cam_scalar_applies_to_every_camera():
    assert normalize_per_cam(0.6, 0.9, CAMS) == {"cam_0": 0.6, "cam_1": 0.6}


def test_normalize_per_cam_none_uses_the_default():
    assert normalize_per_cam(None, 0.9, CAMS) == {"cam_0": 0.9, "cam_1": 0.9}


def test_normalize_per_cam_dict_maps_each_camera():
    got = normalize_per_cam({"cam_0": 0.45, "cam_1": 0.8}, 0.9, CAMS)
    assert got == {"cam_0": 0.45, "cam_1": 0.8}


def test_normalize_per_cam_missing_key_falls_back_to_default():
    got = normalize_per_cam({"cam_0": 0.45}, 0.9, CAMS)
    assert got == {"cam_0": 0.45, "cam_1": 0.9}


def test_normalize_per_cam_rejects_unknown_camera():
    with pytest.raises(ValueError) as e:
        normalize_per_cam({"cam_9": 0.5}, 0.9, CAMS)
    assert "cam_9" in str(e.value)


def test_normalize_per_cam_rejects_out_of_range():
    for bad in (-0.1, 1.5):
        with pytest.raises(ValueError):
            normalize_per_cam(bad, 0.9, CAMS)
        with pytest.raises(ValueError):
            normalize_per_cam({"cam_0": bad}, 0.9, CAMS)


def test_normalize_per_cam_rejects_non_numeric():
    with pytest.raises(ValueError):
        normalize_per_cam("high", 0.9, CAMS)
    with pytest.raises(ValueError):
        normalize_per_cam({"cam_0": "high"}, 0.9, CAMS)


def test_normalize_per_cam_accepts_the_range_endpoints():
    assert normalize_per_cam(0.0, 0.9, CAMS)["cam_0"] == 0.0
    assert normalize_per_cam(1.0, 0.9, CAMS)["cam_1"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_io.py -k normalize -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_per_cam'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/dlc_3d_bp/reprojection.py`, above `run_reprojection`:

```python
def normalize_per_cam(value, default, cam_keys) -> "dict":
    """Resolve a likelihood parameter to one value per camera.

    `value` may be None (use `default` everywhere), a scalar (the same value for
    every camera), or a {camera_key: value} mapping. A mapping that omits a
    camera falls back to `default` for it.

    Raises ValueError — which the routes turn into a 400 — on an unknown camera
    key, a non-numeric value, or a value outside [0, 1].
    """
    def _check(v, where):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("{} must be a number, got {!r}".format(where, v))
        v = float(v)
        if not (0.0 <= v <= 1.0):
            raise ValueError("{} must be within [0, 1], got {}".format(where, v))
        return v

    if value is None:
        return {k: float(default) for k in cam_keys}
    if isinstance(value, dict):
        unknown = [k for k in value if k not in cam_keys]
        if unknown:
            raise ValueError(
                "unknown camera {}; calibration has {}".format(
                    sorted(unknown), sorted(cam_keys))
            )
        return {
            k: (_check(value[k], k) if k in value else float(default))
            for k in cam_keys
        }
    return {k: _check(value, "value") for k in cam_keys}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_io.py -v`
Expected: PASS, 14 tests (6 existing + 8 new)

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/reprojection.py dlc-3D/tests/test_reprojection_io.py
git commit -m "feat(reprojection): normalize_per_cam accepts a scalar or a per-camera dict"
```

---

### Task 3: `run_reprojection` resolves per camera

**Files:**
- Modify: `src/dlc_3d_bp/reprojection.py` (`run_reprojection`, the per-bodypart loop around lines 165–200)
- Test: `tests/test_reprojection_io.py`

**Interfaces:**
- Consumes: `normalize_per_cam` (Task 2); `auto_threshold(..., high_conf_ref=, high_conf_tgt=)` (Task 1).
- Produces: `run_reprojection`'s `gate_ref`, `low_tgt`, `high_conf`, `rescue_floor` accept scalar-or-dict. The audit JSON `config` block records the normalized per-camera dicts under the same key names.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reprojection_io.py`:

```python
def test_per_camera_rescue_floor_applies_to_the_judged_camera(tmp_path):
    """cam_0 is judged here, so its own rescue_floor must be written — not
    cam_1's."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 300
    t = np.linspace(0.0, 1.0, n)
    xyz = np.c_[10.0 + 2.0 * t, -5.0 + 2.0 * t, 250.0 + 5.0 * t]
    ref_xy = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    tgt_xy = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    ref_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik = np.full((n, 2), 0.99, dtype=np.float32)
    tgt_lik[100:150, 0] = 0.10          # correct place, low confidence -> rescue

    ref_h5 = tmp_path / "s_cam1_x.h5"
    tgt_h5 = tmp_path / "s_cam0_x.h5"
    _write_h5(ref_h5, _make_df(ref_xy, ref_lik))
    _write_h5(tgt_h5, _make_df(tgt_xy, tgt_lik))

    out = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key="cam_1", tgt_cam_key="cam_0", out_dir=tmp_path,
        rescue_floor={"cam_0": 0.77, "cam_1": 0.95},
    )
    assert out["counts"]["RESCUE"] > 0
    got, _ = read_pose_h5(out["outputs"]["tgt_h5"])
    lik = got[SCORER]["Snout"]["likelihood"].to_numpy()
    rescued = lik[100:150]
    assert np.allclose(rescued, 0.77, atol=1e-6), (
        "judged camera cam_0's floor (0.77) must be used, not cam_1's 0.95"
    )


def test_per_camera_values_are_recorded_in_the_audit(tmp_path):
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 80
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)
    _write_h5(tmp_path / "s_cam1_x.h5", _make_df(xy1, lik))
    _write_h5(tmp_path / "s_cam0_x.h5", _make_df(xy0, lik))

    out = run_reprojection(
        ref_h5=tmp_path / "s_cam1_x.h5", tgt_h5=tmp_path / "s_cam0_x.h5",
        calib_path=calib, ref_cam_key="cam_1", tgt_cam_key="cam_0",
        out_dir=tmp_path, gate_ref={"cam_0": 0.4, "cam_1": 0.7},
    )
    assert out["config"]["gate_ref"] == {"cam_0": 0.4, "cam_1": 0.7}
    # A scalar is normalized too, so the audit always shows per-camera values.
    assert out["config"]["low_tgt"] == {"cam_0": 0.6, "cam_1": 0.6}


def test_scalar_parameters_still_work(tmp_path):
    """Back-compat: scripts/verify_reprojection.py and the existing route tests
    pass scalars."""
    calib = _write_calib(tmp_path)
    cams = load_calibration(calib)
    n = 80
    xyz = np.c_[np.full(n, 10.0), np.full(n, -5.0), np.linspace(250, 260, n)]
    xy1 = np.stack([project_point(cams["cam_1"], xyz)] * 2, axis=1)
    xy0 = np.stack([project_point(cams["cam_0"], xyz)] * 2, axis=1)
    lik = np.full((n, 2), 0.99, dtype=np.float32)
    _write_h5(tmp_path / "s_cam1_x.h5", _make_df(xy1, lik))
    _write_h5(tmp_path / "s_cam0_x.h5", _make_df(xy0, lik))

    out = run_reprojection(
        ref_h5=tmp_path / "s_cam1_x.h5", tgt_h5=tmp_path / "s_cam0_x.h5",
        calib_path=calib, ref_cam_key="cam_1", tgt_cam_key="cam_0",
        out_dir=tmp_path, gate_ref=0.5, low_tgt=0.5,
        high_conf=0.8, rescue_floor=0.85,
    )
    assert out["config"]["gate_ref"] == {"cam_0": 0.5, "cam_1": 0.5}
    assert out["config"]["rescue_floor"] == {"cam_0": 0.85, "cam_1": 0.85}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_io.py -k "per_camera or scalar_parameters" -v`
Expected: FAIL — the rescued likelihood is 0.9 (the old scalar default), not 0.77

- [ ] **Step 3: Write minimal implementation**

In `run_reprojection`, immediately after `cams = load_calibration(calib_path)` and the `cam_ref`/`cam_tgt` lookups, normalize all four:

```python
    cam_keys = tuple(cams.keys())
    gate_ref_by_cam = normalize_per_cam(gate_ref, 0.6, cam_keys)
    low_tgt_by_cam = normalize_per_cam(low_tgt, 0.6, cam_keys)
    high_conf_by_cam = normalize_per_cam(high_conf, 0.9, cam_keys)
    rescue_floor_by_cam = normalize_per_cam(rescue_floor, 0.9, cam_keys)
```

Inside the per-bodypart loop, right after `flipped = overrides.get(bp) == "ref"`,
resolve which camera holds each role:

```python
        # A flip swaps which camera induces the line and which one is judged, so
        # it swaps which camera's thresholds apply. Resolving by role here is
        # what lets classify() and apply_verdicts() stay unchanged.
        role_ref = tgt_cam_key if flipped else ref_cam_key
        role_tgt = ref_cam_key if flipped else tgt_cam_key
```

Then change the three call sites to use the resolved values:

```python
        st = ec.auto_threshold(
            d, lik_tgt if flipped else lik_ref, lik_ref if flipped else lik_tgt,
            high_conf_ref=high_conf_by_cam[role_ref],
            high_conf_tgt=high_conf_by_cam[role_tgt],
            k1=k1, k2=k2,
        )
        codes = ec.classify(
            d,
            lik_tgt if flipped else lik_ref,
            lik_ref if flipped else lik_tgt,
            t_ok=st["t_ok"], t_bad=st["t_bad"],
            gate_ref=gate_ref_by_cam[role_ref],
            low_tgt=low_tgt_by_cam[role_tgt],
        )
```

and:

```python
        xy_new, lik_new = ec.apply_verdicts(
            xy_j, lik_j, codes, rescue_floor=rescue_floor_by_cam[role_tgt]
        )
```

Finally, in the `summary["config"]` dict, replace the four scalar entries with
the normalized dicts:

```python
            "gate_ref": gate_ref_by_cam, "low_tgt": low_tgt_by_cam,
            "high_conf": high_conf_by_cam, "rescue_floor": rescue_floor_by_cam,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_io.py -v`
Expected: PASS, 17 tests

- [ ] **Step 5: Confirm the real-data verification script still works**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
docker cp dlc-3D/scripts/verify_reprojection.py \
  deeplabcut-webapp-docker-dlc-3d-1:/tmp/verify_reprojection.py
docker exec deeplabcut-webapp-docker-dlc-3d-1 python3 /tmp/verify_reprojection.py
```

Expected: `All invariants passed.` with RESCUE ≈ 125,524 and REJECT ≈ 106,965 —
identical to before, because the script passes no likelihood parameters and the
defaults are unchanged. A different number means the normalization changed
behaviour and must be fixed before proceeding.

This is safe to run against the live container: it is read-only on the source
data and writes only to the container's `/tmp`. Run NO other docker command.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/reprojection.py dlc-3D/tests/test_reprojection_io.py
git commit -m "feat(reprojection): resolve likelihood thresholds per camera by role"
```

---

### Task 4: Routes accept scalar-or-dict

**Files:**
- Modify: `src/dlc_3d_bp/routes.py` (`reproject_thresholds` ~line 820, `reproject_run` ~line 860)
- Test: `tests/test_reprojection_routes.py`

**Interfaces:**
- Consumes: `normalize_per_cam` (Task 2), `run_reprojection` (Task 3).
- Produces: `/reproject/run` forwards all four parameters unconverted (the engine normalizes). `/reproject/thresholds` forwards per-camera `high_conf` only. Both return 400 with a message naming the offending field when `normalize_per_cam` raises.

**Why the routes no longer call `float()`:** they currently do
`float(body.get("gate_ref", 0.6))`, which raises `TypeError` on a dict and
surfaces as a 500. Pass the raw value through and let the engine's
`normalize_per_cam` validate it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reprojection_routes.py`:

```python
def test_run_accepts_per_camera_dicts(client, monkeypatch, tmp_path):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"counts": {}, "outputs": {}, "bodyparts": {}, "config": {}}

    monkeypatch.setattr(routes, "_reproject_run_impl", fake_run)
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a_cam1_x.h5", "tgt_h5": "/user-data/a_cam0_x.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_1", "tgt_cam": "cam_0",
        "gate_ref": {"cam_0": 0.4, "cam_1": 0.7},
        "rescue_floor": {"cam_0": 0.77, "cam_1": 0.95},
    })
    assert r.status_code == 200
    assert seen["gate_ref"] == {"cam_0": 0.4, "cam_1": 0.7}
    assert seen["rescue_floor"] == {"cam_0": 0.77, "cam_1": 0.95}
    # Unsupplied parameters must not be coerced to something the engine can't
    # tell apart from "use the default".
    assert seen["low_tgt"] in (None, 0.6)


def test_run_rejects_out_of_range_value(client, monkeypatch, tmp_path):
    import dlc_3d_bp.reprojection as rp
    monkeypatch.setattr(rp, "load_calibration",
                        lambda p: {"cam_0": object(), "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
        "gate_ref": {"cam_0": 1.7},
    })
    assert r.status_code == 400
    assert "gate_ref" in r.get_json()["error"]


def test_run_rejects_unknown_camera_in_a_parameter(client, monkeypatch):
    import dlc_3d_bp.reprojection as rp
    monkeypatch.setattr(rp, "load_calibration",
                        lambda p: {"cam_0": object(), "cam_1": object()})
    r = client.post("/dlc-3d/reproject/run", json={
        "ref_h5": "/user-data/a.h5", "tgt_h5": "/user-data/b.h5",
        "calibration": "/user-data/calibration.toml",
        "ref_cam": "cam_0", "tgt_cam": "cam_1",
        "high_conf": {"cam_9": 0.8},
    })
    assert r.status_code == 400
    assert "cam_9" in r.get_json()["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_routes.py -k "per_camera or out_of_range or unknown_camera_in" -v`
Expected: FAIL — 500 from `float()` on a dict

- [ ] **Step 3: Write minimal implementation**

In `reproject_run`, replace the four `float(body.get(...))` arguments with the raw
values and wrap the engine call so a `ValueError` becomes a 400:

```python
    try:
        summary = _reproject_run_impl(
            ref_h5=paths["ref_h5"], tgt_h5=paths["tgt_h5"],
            calib_path=paths["calibration"],
            ref_cam_key=body["ref_cam"], tgt_cam_key=body["tgt_cam"],
            out_dir=out_dir,
            k1=float(body.get("k1", 3.0)), k2=float(body.get("k2", 8.0)),
            gate_ref=body.get("gate_ref", 0.6),
            low_tgt=body.get("low_tgt", 0.6),
            high_conf=body.get("high_conf", 0.9),
            rescue_floor=body.get("rescue_floor", 0.9),
            overrides=body.get("overrides") or {},
        )
    except ValueError as exc:
        # normalize_per_cam rejects unknown camera keys and out-of-range values.
        return jsonify({"error": str(exc)}), 400
```

The `ValueError` message from `normalize_per_cam` names the camera key but not
the field, so name the field when normalizing in `reproject_thresholds` and
prefix it in `run` by normalizing there too. Add, before the engine call:

```python
    cams = rp.load_calibration(paths["calibration"])
    cam_keys = tuple(cams.keys())
    for field, default in (("gate_ref", 0.6), ("low_tgt", 0.6),
                           ("high_conf", 0.9), ("rescue_floor", 0.9)):
        if field in body:
            try:
                rp.normalize_per_cam(body[field], default, cam_keys)
            except ValueError as exc:
                return jsonify({"error": "{}: {}".format(field, exc)}), 400
```

In `reproject_thresholds`, replace `high_conf=float(body.get("high_conf", 0.9))`
with a per-camera resolution. Immediately after the existing `cams = ...` lookup
and the camera-key guard, add:

```python
    try:
        high_conf_by_cam = rp.normalize_per_cam(
            body.get("high_conf", 0.9), 0.9, tuple(cams.keys()))
    except ValueError as exc:
        return jsonify({"error": "high_conf: {}".format(exc)}), 400
```

and change the `auto_threshold` call in that route to:

```python
        out[bp_name] = ec.auto_threshold(
            d,
            a["likelihood"].to_numpy(dtype=float),
            b["likelihood"].to_numpy(dtype=float),
            high_conf_ref=high_conf_by_cam[body["ref_cam"]],
            high_conf_tgt=high_conf_by_cam[body["tgt_cam"]],
            k1=float(body.get("k1", 3.0)),
            k2=float(body.get("k2", 8.0)),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd dlc-3D && python3 -m pytest tests/test_reprojection_routes.py -v`
Expected: PASS, 10 tests (7 existing + 3 new)

- [ ] **Step 5: Run the whole suite**

Run: `cd dlc-3D && python3 -m pytest -q 2>&1 | tail -20`
Expected: your new tests pass and the ONLY failures are the ten listed in Global
Constraints.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_reprojection_routes.py
git commit -m "feat(reprojection): routes accept per-camera likelihood parameters"
```

---

### Task 5: Deploy the backend

**Files:** none — this task changes no code.

**Interfaces:**
- Consumes: Tasks 1–4, committed and green.
- Produces: a running container whose routes accept per-camera dicts, so Tasks 6–7 can ship the panel safely.

**Why this sits in the middle of the plan:** `src/static/` is a bind mount, so the
panel goes live on the next browser reload, but Python needs a gunicorn restart.
Shipping the panel first would send per-camera dicts to a backend that still
calls `float()` on them — a 500 for anyone who clicks Run. Restarting here closes
that window.

- [ ] **Step 1: Confirm the backend work is committed and green**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git status --porcelain | grep -v '^??' || echo "clean"
cd dlc-3D && python3 -m pytest tests/unit/test_epipolar_core.py \
  tests/test_reprojection_io.py tests/test_reprojection_routes.py -q | tail -3
```

Expected: clean tree, all three files passing.

- [ ] **Step 2: Restart**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
```

`docker compose up -d dlc-3d` is a NO-OP here — with no compose change it reports
"Container ... Running" and never reloads gunicorn. Use `restart`.

- [ ] **Step 3: Confirm a clean boot**

```bash
docker logs --since 2m deeplabcut-webapp-docker-dlc-3d-1 2>&1 | tail -8
```

Expected: `Booting worker with pid: N` and no traceback. An `ImportError` here
means a Task 1–4 change broke module import — roll back before going further.

- [ ] **Step 4: Confirm the live route accepts a per-camera dict**

```bash
cat > /tmp/probe_percam.py <<'PY'
import json, urllib.request as u, urllib.error
B = "http://localhost:5050"
def post(path, payload):
    req = u.Request(B + path, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"}, method="POST")
    try:
        r = u.urlopen(req, timeout=60); return r.status, r.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]
D = "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/070126"
S = ("eggtart-1_cam{c}_20260701_094411_10_trig1_fps200_exposure1500_gain10"
     "DLC_HrnetW48_DREADDJan7shuffle1_snapshot_best-180.h5")
base = {"ref_h5": D + "/" + S.format(c=1), "tgt_h5": D + "/" + S.format(c=0),
        "calibration": D + "/calibration.toml", "ref_cam": "cam_1", "tgt_cam": "cam_0"}
code, body = post("/dlc-3d/reproject/thresholds",
                  dict(base, high_conf={"cam_0": 0.75, "cam_1": 0.9}))
print("per-camera high_conf ->", code, "(want 200)")
data = json.loads(body) if code == 200 else {}
code2, body2 = post("/dlc-3d/reproject/thresholds", dict(base, high_conf=0.9))
print("scalar high_conf     ->", code2, "(want 200 — back-compat)")
code3, _ = post("/dlc-3d/reproject/thresholds", dict(base, high_conf={"cam_9": 0.5}))
print("unknown camera key   ->", code3, "(want 400)")
code4, _ = post("/dlc-3d/reproject/thresholds", dict(base, high_conf={"cam_0": 1.7}))
print("out of range         ->", code4, "(want 400)")
PY
docker cp /tmp/probe_percam.py deeplabcut-webapp-docker-dlc-3d-1:/tmp/probe_percam.py
docker exec deeplabcut-webapp-docker-dlc-3d-1 python3 /tmp/probe_percam.py
docker exec deeplabcut-webapp-docker-dlc-3d-1 rm -f /tmp/probe_percam.py
```

Expected: `200`, `200`, `400`, `400`. Anything else means Task 4 is wrong —
fix it and restart again before continuing.

- [ ] **Step 5: Confirm the source data is untouched**

```bash
ls "/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/RatBox Videos/tdcs/070126" \
  | grep -c reprojected
```

Expected: `0`. The thresholds endpoint is read-only; a non-zero count means
something wrote into the session and must be investigated immediately.

- [ ] **Step 6: No commit** — this task produces no repository change.

---

### Task 6: Panel markup and wiring

**Files:**
- Modify: `src/static/card_inline_analysis_3d_reprojection.html`
- Modify: `src/static/inline_analysis_3d_reprojection.css`
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_panel_markup.py`, `tests/test_reproj_panel_wiring.py`

**Interfaces:**
- Consumes: the live endpoints from Task 5.
- Produces: element ids `ia3dr-reproj-{cam0,cam1}-{gate-ref,low-tgt,high-conf,rescue-floor}`; a `_reprojPerCam(param)` helper returning `{cam_0, cam_1}`.

**Markup and wiring land in ONE task on purpose:** the card is live, so a commit
that adds inputs without wiring them would put dead controls in front of users on
their next reload.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reproj_panel_markup.py`:

```python
PER_CAM_IDS = [
    "ia3dr-reproj-cam0-gate-ref", "ia3dr-reproj-cam0-low-tgt",
    "ia3dr-reproj-cam0-high-conf", "ia3dr-reproj-cam0-rescue-floor",
    "ia3dr-reproj-cam1-gate-ref", "ia3dr-reproj-cam1-low-tgt",
    "ia3dr-reproj-cam1-high-conf", "ia3dr-reproj-cam1-rescue-floor",
]


@pytest.mark.parametrize("element_id", PER_CAM_IDS)
def test_per_camera_input_present(card, element_id):
    assert 'id="{}"'.format(element_id) in card


def test_per_camera_inputs_are_bounded_to_a_likelihood(card):
    """These are likelihoods; the browser should refuse values outside [0, 1]
    before the request is ever made."""
    for element_id in PER_CAM_IDS:
        frag = card.split('id="{}"'.format(element_id))[1][:200]
        assert 'min="0"' in frag and 'max="1"' in frag


def test_per_camera_defaults_match_the_engine(card):
    for element_id in PER_CAM_IDS:
        frag = card.split('id="{}"'.format(element_id))[1][:200]
        want = '0.9' if ("high-conf" in element_id or "rescue-floor" in element_id) else '0.6'
        assert 'value="{}"'.format(want) in frag
```

Append to `tests/test_reproj_panel_wiring.py`:

```python
def test_run_payload_sends_all_four_per_camera(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "_reprojPerCam" in block
    for field in ("gate_ref", "low_tgt", "high_conf", "rescue_floor"):
        assert field in block


def test_estimate_sends_high_conf_but_not_the_other_three(js):
    """Only high_conf feeds auto_threshold. Sending gate_ref / low_tgt /
    rescue_floor to the thresholds endpoint would imply an effect they do not
    have — they are consumed by classify and apply_verdicts, neither of which
    runs during an estimate."""
    fn = js.split("async function _reprojEstimate")[1].split("\nasync function")[0]
    assert "high_conf" in fn
    for field in ("gate_ref", "low_tgt", "rescue_floor"):
        assert field not in fn, "{} must not be sent to /reproject/thresholds".format(field)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py tests/test_reproj_panel_wiring.py -q`
Expected: FAIL — the eight ids are missing and `_reprojPerCam` is undefined

- [ ] **Step 3: Add the markup**

In `src/static/card_inline_analysis_3d_reprojection.html`, insert immediately
after the `ia3dr-reproj-k1` / `ia3dr-reproj-k2` control row:

```html
        <div class="ia3dr-percam-wrap">
          <fieldset class="ia3dr-percam">
            <legend>cam0</legend>
            <label>gate_ref
              <input type="number" id="ia3dr-reproj-cam0-gate-ref"
                     min="0" max="1" step="0.05" value="0.6"></label>
            <label>low_tgt
              <input type="number" id="ia3dr-reproj-cam0-low-tgt"
                     min="0" max="1" step="0.05" value="0.6"></label>
            <label>high_conf
              <input type="number" id="ia3dr-reproj-cam0-high-conf"
                     min="0" max="1" step="0.05" value="0.9"></label>
            <label>rescue_floor
              <input type="number" id="ia3dr-reproj-cam0-rescue-floor"
                     min="0" max="1" step="0.05" value="0.9"></label>
          </fieldset>
          <fieldset class="ia3dr-percam">
            <legend>cam1</legend>
            <label>gate_ref
              <input type="number" id="ia3dr-reproj-cam1-gate-ref"
                     min="0" max="1" step="0.05" value="0.6"></label>
            <label>low_tgt
              <input type="number" id="ia3dr-reproj-cam1-low-tgt"
                     min="0" max="1" step="0.05" value="0.6"></label>
            <label>high_conf
              <input type="number" id="ia3dr-reproj-cam1-high-conf"
                     min="0" max="1" step="0.05" value="0.9"></label>
            <label>rescue_floor
              <input type="number" id="ia3dr-reproj-cam1-rescue-floor"
                     min="0" max="1" step="0.05" value="0.9"></label>
          </fieldset>
        </div>
```

- [ ] **Step 4: Add the styles**

Append to `src/static/inline_analysis_3d_reprojection.css`:

```css
#ia3dr-reproj-panel .ia3dr-percam-wrap {
  display: flex; gap: 1rem; flex-wrap: wrap; margin: .4rem 0;
}
#ia3dr-reproj-panel .ia3dr-percam {
  border: 1px solid rgba(255, 255, 255, .18);
  border-radius: 6px; padding: .35rem .6rem .5rem; min-width: 12rem;
}
#ia3dr-reproj-panel .ia3dr-percam legend {
  padding: 0 .35rem; font-size: .85em; opacity: .8;
}
#ia3dr-reproj-panel .ia3dr-percam label {
  display: flex; align-items: center; justify-content: space-between;
  gap: .5rem; font-size: .85em; margin: .15rem 0;
}
#ia3dr-reproj-panel .ia3dr-percam input { width: 5rem; }
```

- [ ] **Step 5: Wire the payloads**

In `src/static/inline_analysis_3d_reprojection.js`, add to the `_reprojEl` map:

```javascript
  perCam:     (cam, param) =>
                document.getElementById(`ia3dr-reproj-${cam}-${param}`),
```

Add this helper next to `_reprojPayload`:

```javascript
// Read one likelihood parameter for both cameras. Returns the per-camera dict
// the endpoints accept; an unreadable input falls back to the engine default so
// a blanked field never sends NaN.
function _reprojPerCam(param, fallback) {
  const read = (cam) => {
    const v = parseFloat(_reprojEl.perCam(cam, param)?.value);
    return Number.isFinite(v) ? v : fallback;
  };
  return { cam_0: read("cam0"), cam_1: read("cam1") };
}
```

Change `_reprojPayload` to include all four:

```javascript
function _reprojPayload() {
  const pair = _reprojPair();
  if (!pair) return null;
  return Object.assign({}, pair, {
    k1: parseFloat(_reprojEl.k1()?.value) || 3.0,
    k2: parseFloat(_reprojEl.k2()?.value) || 8.0,
    gate_ref:     _reprojPerCam("gate-ref", 0.6),
    low_tgt:      _reprojPerCam("low-tgt", 0.6),
    high_conf:    _reprojPerCam("high-conf", 0.9),
    rescue_floor: _reprojPerCam("rescue-floor", 0.9),
    overrides: _reprojOverrides,
  });
}
```

In `_reprojEstimate`, build a reduced payload — the thresholds endpoint must not
receive the three parameters that do not affect it:

```javascript
  const full = _reprojPayload();
  if (!full) { _reprojStatus("Open a paired session with an overlay h5 first.", true); return; }
  // Only high_conf feeds auto_threshold; gate_ref/low_tgt are consumed by
  // classify and rescue_floor by apply_verdicts, neither of which runs here.
  const payload = {
    ref_h5: full.ref_h5, tgt_h5: full.tgt_h5, calibration: full.calibration,
    ref_cam: full.ref_cam, tgt_cam: full.tgt_cam,
    k1: full.k1, k2: full.k2, high_conf: full.high_conf,
  };
```

and use `payload` in the fetch body, replacing the previous `_reprojPayload()`
call in that function.

- [ ] **Step 6: Run the tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_markup.py tests/test_reproj_panel_wiring.py -q`
Expected: PASS

- [ ] **Step 7: Verify the module still parses**

Run: `cd dlc-3D && node --input-type=module --check < src/static/inline_analysis_3d_reprojection.js && echo "parses OK"`
Expected: `parses OK`. The Python tests only match strings — they never execute
the module, so this is the only syntax check.

- [ ] **Step 8: Commit**

```bash
git add dlc-3D/src/static/card_inline_analysis_3d_reprojection.html \
        dlc-3D/src/static/inline_analysis_3d_reprojection.css \
        dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_panel_markup.py \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(reprojection): per-camera likelihood inputs in the panel"
```

---

### Task 7: Per-project persistence

**Files:**
- Modify: `src/static/inline_analysis_3d_reprojection.js`
- Test: `tests/test_reproj_panel_wiring.py`

**Interfaces:**
- Consumes: the panel from Task 6.
- Produces: `_reprojSaveParams()` and `_reprojLoadParams()`, persisting under the `ui-setting` key `reproj_params`.

**Why no `_reproj` suffix on the key:** the suffix convention exists to stop this
clone colliding with keys the *original* card also writes. `reproj_params` is
unique to this card, so there is nothing to collide with.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reproj_panel_wiring.py`:

```python
def test_params_are_persisted_per_project(js):
    block = js.split("REPROJECTION PANEL")[1]
    assert "reproj_params" in block
    assert "/dlc/project/ui-setting" in block


def test_persistence_save_is_debounced(js):
    """Matches the existing pose3d_view_prefs_reproj flow — a change on every
    keystroke must not become a POST on every keystroke."""
    fn = js.split("function _reprojSaveParams")[1].split("\nfunction ")[0]
    assert "setTimeout" in fn and "clearTimeout" in fn


def test_persistence_load_happens_on_card_open_not_at_bootstrap(js):
    """ui-setting is project-scoped and the panel wires at DOMContentLoaded,
    before any project is selected. Loading there would query the wrong project
    or none at all."""
    assert "_reprojLoadParams" in js
    boot = js.split("REPROJECTION BOOTSTRAP")[1].split("REPROJECTION PANEL")[0]
    assert "_reprojLoadParams" not in boot, (
        "params must not load from the bootstrap path"
    )


def test_persisted_overrides_are_filtered_against_current_bodyparts(js):
    """Overrides are keyed by bodypart name, which is model-specific. A stale
    entry from another project must not resurrect a flip."""
    fn = js.split("async function _reprojLoadParams")[1].split("\nasync function")[0]
    assert "bodyparts" in fn or "_reprojKnownBodyparts" in fn
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -k persist -v`
Expected: FAIL — `_reprojSaveParams` is undefined

- [ ] **Step 3: Implement save and load**

Add to `src/static/inline_analysis_3d_reprojection.js`, inside the REPROJECTION
PANEL block:

```javascript
// ── Per-project persistence ─────────────────────────────────────────────────
// The whole run configuration lives under one ui-setting key so reopening the
// card restores the last setup for THIS project. Best-effort in both
// directions: a failed POST or a corrupt value leaves the defaults standing,
// mirroring the pose3d view-prefs flow.

const REPROJ_PARAMS_KEY = "reproj_params";
let _reprojParamsSaveTimer = null;
let _reprojKnownBodyparts = [];

function _reprojSaveParams() {
  const prefs = {
    ref_cam: _reprojEl.refCam()?.value || "cam_1",
    k1: parseFloat(_reprojEl.k1()?.value) || 3.0,
    k2: parseFloat(_reprojEl.k2()?.value) || 8.0,
    gate_ref:     _reprojPerCam("gate-ref", 0.6),
    low_tgt:      _reprojPerCam("low-tgt", 0.6),
    high_conf:    _reprojPerCam("high-conf", 0.9),
    rescue_floor: _reprojPerCam("rescue-floor", 0.9),
    overrides: _reprojOverrides,
  };
  if (_reprojParamsSaveTimer) clearTimeout(_reprojParamsSaveTimer);
  _reprojParamsSaveTimer = setTimeout(() => {
    fetch("/dlc/project/ui-setting", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: REPROJ_PARAMS_KEY, value: JSON.stringify(prefs) }),
    }).catch(() => {});
  }, 400);
}

async function _reprojLoadParams() {
  try {
    const data = await (await fetch(
      `/dlc/project/ui-setting?key=${REPROJ_PARAMS_KEY}`)).json();
    if (!data || !data.value) return;
    const prefs = JSON.parse(data.value);
    if (!prefs || typeof prefs !== "object") return;

    const setNum = (el, v) => {
      if (el && Number.isFinite(v)) el.value = String(v);
    };
    if (prefs.ref_cam && _reprojEl.refCam()) _reprojEl.refCam().value = prefs.ref_cam;
    setNum(_reprojEl.k1(), prefs.k1);
    setNum(_reprojEl.k2(), prefs.k2);
    for (const param of ["gate-ref", "low-tgt", "high-conf", "rescue-floor"]) {
      const key = param.replace("-", "_");
      const vals = prefs[key];
      if (!vals || typeof vals !== "object") continue;
      setNum(_reprojEl.perCam("cam0", param), vals.cam_0);
      setNum(_reprojEl.perCam("cam1", param), vals.cam_1);
    }
    // Overrides are keyed by bodypart, which is model-specific: drop entries
    // naming a bodypart this session does not have, so switching projects or
    // retraining cannot resurrect a stale flip.
    _reprojOverrides = {};
    if (prefs.overrides && typeof prefs.overrides === "object") {
      const known = new Set(_reprojKnownBodyparts);
      for (const [bp, mode] of Object.entries(prefs.overrides)) {
        if (mode === "ref" && (known.size === 0 || known.has(bp))) {
          _reprojOverrides[bp] = "ref";
        }
      }
    }
  } catch (_) { /* keep the defaults */ }
}
```

Note the `param.replace("-", "_")` mapping: element ids use hyphens
(`high-conf`) while the stored keys use the engine's underscored names
(`high_conf`).

- [ ] **Step 4: Record the bodypart list and hook up save/load**

In `_reprojRenderOverrides`, record the current bodyparts as the first line so
the load filter has something to check against:

```javascript
function _reprojRenderOverrides(bodyparts) {
  _reprojKnownBodyparts = Object.keys(bodyparts);
```

In `_reprojWirePanel`, attach the save handler to every control and load on open.
Add before the closing brace of `_reprojWirePanel`:

```javascript
  for (const el of [
    _reprojEl.refCam(), _reprojEl.k1(), _reprojEl.k2(),
    ...["gate-ref", "low-tgt", "high-conf", "rescue-floor"].flatMap((p) => [
      _reprojEl.perCam("cam0", p), _reprojEl.perCam("cam1", p),
    ]),
  ]) {
    el?.addEventListener("change", _reprojSaveParams);
  }
```

Also call `_reprojSaveParams()` at the end of the per-bodypart override `change`
listener inside `_reprojRenderOverrides`, so a flip is persisted too:

```javascript
      if (sel.value === "ref") _reprojOverrides[bp] = "ref";
      else delete _reprojOverrides[bp];
      _reprojSaveParams();
```

Finally, load on card open rather than at bootstrap. In the cloned open handler —
find it with `grep -n "_reprojWirePanel\|function _iaOpen" src/static/inline_analysis_3d_reprojection.js`
— call `_reprojLoadParams()` immediately after the panel is visible. If the card
has no single open function, call it from `_ensureViewer()` right after
`_reprojWireEpipolarOverlay();`, which runs exactly once per card open and is
guaranteed to be after a project is selected. Report which you chose.

- [ ] **Step 5: Run the tests**

Run: `cd dlc-3D && python3 -m pytest tests/test_reproj_panel_wiring.py -q`
Expected: PASS

- [ ] **Step 6: Verify the module parses**

Run: `cd dlc-3D && node --input-type=module --check < src/static/inline_analysis_3d_reprojection.js && echo "parses OK"`
Expected: `parses OK`

- [ ] **Step 7: Run the whole suite**

Run: `cd dlc-3D && python3 -m pytest -q 2>&1 | tail -20`
Expected: only the ten baseline failures.

- [ ] **Step 8: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d_reprojection.js \
        dlc-3D/tests/test_reproj_panel_wiring.py
git commit -m "feat(reprojection): persist the run configuration per project"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| Per-camera semantics (role resolution table) | 3 |
| `auto_threshold` per-side `high_conf` | 1 |
| `normalize_per_cam` (scalar-or-dict, validation) | 2 |
| `classify` / `apply_verdicts` unchanged | 3 (verified by the back-compat test) |
| Audit records per-camera values | 3 |
| API accepts scalar-or-dict; 400 not 500 | 4 |
| `/reproject/thresholds` takes only `high_conf` | 4, 6 |
| Two per-camera column groups, ids, bounds | 6 |
| `Run` sends four, `Estimate` sends `high_conf` only | 6 |
| Persistence under `reproj_params`, debounced | 7 |
| Load on card open, not bootstrap | 7 |
| Overrides filtered against current bodyparts | 7 |
| Deployment ordering (backend before frontend) | 5 |

**Placeholder scan:** none. Task 7 Step 4 contains a conditional ("if the card
has no single open function") but gives an exact fallback location and requires
the implementer to report the choice — that is a located decision, not a
deferred one.

**Type consistency:** `normalize_per_cam(value, default, cam_keys) -> dict` is
defined in Task 2 and called in Tasks 3 and 4 with that signature.
`auto_threshold`'s new `high_conf_ref`/`high_conf_tgt` keywords are defined in
Task 1 and used in Tasks 3 and 4. Element ids `ia3dr-reproj-{cam}-{param}` are
created in Task 6 and read in Task 7 via the same `_reprojEl.perCam(cam, param)`
helper. Stored JSON keys use underscores (`high_conf`) while element ids use
hyphens (`high-conf`); Task 7 Step 3 maps between them explicitly.
