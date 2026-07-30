"""I/O and orchestration for epipolar reprojection of 2D DLC markers.

epipolar_core holds the maths and stays pure; everything that touches disk is
here.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dlc_3d_bp import epipolar_core as ec
from dlc_3d_bp import peak_screen as ps
from dlc_3d_bp import peaks_io as pio


def _parse_toml(text: str) -> dict:
    """Read a flat aniposelib calibration.toml.

    Prefers a real TOML parser. The fallback exists because the host test
    environment is Python 3.9 with neither `toml` nor `tomllib`; the file is
    machine-generated with one level of sections and Python-literal values.
    """
    try:
        import toml
        return toml.loads(text)
    except ImportError:
        pass
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        pass

    out: "dict" = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out[section] = {}
            continue
        if section is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().rstrip(",")
        if value in ("true", "false"):
            parsed = value == "true"
        else:
            parsed = ast.literal_eval(value)
        out[section][key.strip()] = parsed
    return out


def load_calibration(path) -> "dict":
    """Build a Cam per camera section of an aniposelib calibration.toml."""
    data = _parse_toml(Path(path).read_text())
    cams = {}
    for key, sec in data.items():
        if not key.startswith("cam") or "matrix" not in sec:
            continue
        size = sec.get("size") or [0, 0]
        cams[key] = ec.Cam(
            name=str(sec.get("name", key)),
            K=np.asarray(sec["matrix"], dtype=float).reshape(3, 3),
            dist=np.asarray(sec.get("distortions", [0] * 5), dtype=float).reshape(-1),
            rvec=np.asarray(sec["rotation"], dtype=float).reshape(3),
            tvec=np.asarray(sec["translation"], dtype=float).reshape(3),
            size=(int(size[0]), int(size[1])),
        )
    return cams


def read_pose_h5(path) -> "tuple[pd.DataFrame, dict]":
    """Read a DLC pose h5 and capture its storage contract for round-tripping."""
    path = Path(path)
    with pd.HDFStore(str(path), "r") as store:
        keys = store.keys()
        if not keys:
            raise ValueError("no datasets in {}".format(path))
        key = keys[0]
        is_table = bool(store.get_storer(key).is_table)
    df = pd.read_hdf(str(path), key=key)
    scorer = df.columns.get_level_values(0)[0]
    bodyparts = list(dict.fromkeys(df.columns.get_level_values("bodyparts")))
    meta = {
        "key": key.lstrip("/"),
        "is_table": is_table,
        "scorer": scorer,
        "bodyparts": bodyparts,
        "dtypes": {str(c): str(t) for c, t in zip(df.columns, df.dtypes)},
    }
    return df, meta


def write_pose_h5(df: pd.DataFrame, meta: dict, path) -> None:
    """Write a pose DataFrame using the source file's key and storage format."""
    df.to_hdf(
        str(path), key=meta["key"],
        format="table" if meta["is_table"] else "fixed", mode="w",
    )


def _out_path(src, out_dir, suffix) -> Path:
    src = Path(src)
    base = src.parent if out_dir is None else Path(out_dir)
    return base / (src.stem + "_reprojected" + suffix)


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


def align_peaks_to_frames(n_frames: int, peaks: "dict | None", bodypart: str):
    """Project a sparse sidecar onto dense frame positions for one bodypart.

    Returns (xy, score, covered) with shapes (n, K, 2), (n, K) and (n,).
    Frames the sidecar does not carry — and every frame when the sidecar lacks
    this bodypart — come back uncovered, which the screen passes through
    untouched.
    """
    if not peaks or bodypart not in peaks["bodyparts"]:
        return (np.full((n_frames, 1, 2), np.nan, np.float32),
                np.zeros((n_frames, 1), np.float32),
                np.zeros(n_frames, bool))

    j = list(peaks["bodyparts"]).index(bodypart)
    k = int(peaks["xy"].shape[2])
    xy = np.full((n_frames, k, 2), np.nan, np.float32)
    score = np.zeros((n_frames, k), np.float32)
    covered = np.zeros(n_frames, bool)

    frames = np.asarray(peaks["frames"], dtype=np.int64)
    keep = (frames >= 0) & (frames < n_frames)
    rows = np.flatnonzero(keep)
    if rows.size:
        dest = frames[keep]
        xy[dest] = peaks["xy"][rows, j]
        score[dest] = peaks["score"][rows, j]
        covered[dest] = True
    return xy, score, covered


def run_reprojection(
    ref_h5,
    tgt_h5,
    calib_path,
    ref_cam_key: str,
    tgt_cam_key: str,
    out_dir=None,
    k1: float = 3.0,
    k2: float = 8.0,
    gate_ref = 0.6,
    low_tgt = 0.6,
    high_conf = 0.9,
    rescue_floor = 0.9,
    overrides: "dict | None" = None,
    require_peaks: bool = False,
    peak_score_floor: float = 0.05,
) -> dict:
    """Judge the target view against the reference view and write artifacts.

    `overrides` maps a bodypart name to "ref" or "tgt", naming which camera to
    trust for that bodypart, overriding the session-level choice. Writes
    <stem>_reprojected.h5 for BOTH cameras: the reference copy is required so
    the _cam{N}_ sibling pairing in routes.py still discovers the pair.
    """
    cams = load_calibration(calib_path)
    cam_ref, cam_tgt = cams[ref_cam_key], cams[tgt_cam_key]
    df_ref, meta_ref = read_pose_h5(ref_h5)
    df_tgt, meta_tgt = read_pose_h5(tgt_h5)

    bodyparts = [b for b in meta_tgt["bodyparts"] if b in meta_ref["bodyparts"]]
    overrides = overrides or {}

    # Load whichever sidecars exist. A missing one is not an error: analyses
    # predating this feature have none, and treating absence as "no evidence"
    # would void every rescue in them.
    peaks_by_side = {"ref": None, "tgt": None}
    screen_totals = None
    if require_peaks:
        screen_totals = {"rescues": 0, "covered": 0, "kept": 0, "refused": 0,
                         "ambiguous": 0, "no_evidence": 0, "corrected": 0,
                         # Which model produced the evidence, so a stale
                         # sidecar left over from an earlier snapshot is at
                         # least visible in the audit JSON, even though we
                         # don't attempt to validate it against the pose h5.
                         "snapshot": {"ref": None, "tgt": None},
                         "bodyparts": {}}
        for side, h5 in (("ref", ref_h5), ("tgt", tgt_h5)):
            sc_path = pio.peaks_sidecar_path(h5)
            if Path(sc_path).is_file():
                peaks = pio.read_peaks_npz(sc_path)
                peaks_by_side[side] = peaks
                screen_totals["snapshot"][side] = peaks["meta"].get("snapshot")

    # Normalize all four parameters to per-camera dicts
    cam_keys = tuple(cams.keys())
    gate_ref_by_cam = normalize_per_cam(gate_ref, 0.6, cam_keys)
    low_tgt_by_cam = normalize_per_cam(low_tgt, 0.6, cam_keys)
    high_conf_by_cam = normalize_per_cam(high_conf, 0.9, cam_keys)
    rescue_floor_by_cam = normalize_per_cam(rescue_floor, 0.9, cam_keys)

    F = {
        "tgt": ec.fundamental_matrix(cam_ref, cam_tgt),
        "ref": ec.fundamental_matrix(cam_tgt, cam_ref),
    }

    # Both sides are copied because a per-bodypart override flips which camera
    # is judged for that bodypart, and therefore which file receives the
    # correction. With no overrides, df_ref_out stays a faithful copy.
    df_tgt_out = df_tgt.copy()
    df_ref_out = df_ref.copy()
    arrays: "dict" = {}
    stats_out: "dict" = {}
    counts = {name: 0 for name in ec.VERDICT_NAMES.values()}

    for bp in bodyparts:
        a = df_ref[meta_ref["scorer"]][bp]
        b = df_tgt[meta_tgt["scorer"]][bp]
        xy_ref = a[["x", "y"]].to_numpy(dtype=float)
        xy_tgt = b[["x", "y"]].to_numpy(dtype=float)
        lik_ref = a["likelihood"].to_numpy(dtype=float)
        lik_tgt = b["likelihood"].to_numpy(dtype=float)

        u_ref = ec.undistort_to_pixels(cam_ref, xy_ref)
        u_tgt = ec.undistort_to_pixels(cam_tgt, xy_tgt)
        # Both directions cached so a reference flip needs no h5 reread.
        d_tgt = ec.epipolar_distance(F["tgt"], u_ref, u_tgt)
        d_ref = ec.epipolar_distance(F["ref"], u_tgt, u_ref)

        flipped = overrides.get(bp) == "ref"
        d = d_ref if flipped else d_tgt
        # A flip swaps which camera induces the line and which one is judged, so
        # it swaps which camera's thresholds apply. Resolving by role here is
        # what lets classify() and apply_verdicts() stay unchanged.
        role_ref = tgt_cam_key if flipped else ref_cam_key
        role_tgt = ref_cam_key if flipped else tgt_cam_key
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

        pts3d = ec.triangulate_dlt(cam_ref, cam_tgt, xy_ref, xy_tgt)
        codes = ec.apply_gate(codes, ec.plausibility_gate(pts3d, codes))

        if require_peaks:
            # The judged side is the one being corrected, so its sidecar is the
            # one that carries evidence about the marker under test.
            judged_peaks = peaks_by_side["ref" if flipped else "tgt"]
            cam_judged = cam_ref if flipped else cam_tgt
            u_inducing = u_tgt if flipped else u_ref
            F_judged = F["ref"] if flipped else F["tgt"]

            p_xy, p_sc, covered = align_peaks_to_frames(len(codes), judged_peaks, bp)
            d_pk = np.full(p_sc.shape, np.nan)
            for kk in range(p_xy.shape[1]):
                # Peaks live in the same raw distorted pixel space as the pose
                # h5, so the existing undistort applies unchanged.
                d_pk[:, kk] = ec.epipolar_distance(
                    F_judged, u_inducing,
                    ec.undistort_to_pixels(cam_judged, p_xy[:, kk, :].astype(float)),
                )
            codes, sstats = ps.screen_rescues(
                codes, d_pk, p_sc, covered,
                t_ok=st["t_ok"], score_floor=peak_score_floor)
            screen_totals["bodyparts"][bp] = sstats
            for key in ("rescues", "covered", "kept", "refused",
                        "ambiguous", "no_evidence", "corrected"):
                screen_totals[key] += sstats[key]

        # The judged side is the one whose markers are being corrected: normally
        # the target, or the reference for a bodypart the caller flipped.
        if flipped:
            frame_out, meta_j, xy_j, lik_j = df_ref_out, meta_ref, xy_ref, lik_ref
        else:
            frame_out, meta_j, xy_j, lik_j = df_tgt_out, meta_tgt, xy_tgt, lik_tgt

        xy_new, lik_new = ec.apply_verdicts(
            xy_j, lik_j, codes, rescue_floor=rescue_floor_by_cam[role_tgt]
        )
        sc = meta_j["scorer"]
        dtype = frame_out[(sc, bp, "x")].dtype
        frame_out[(sc, bp, "x")] = xy_new[:, 0].astype(dtype)
        frame_out[(sc, bp, "y")] = xy_new[:, 1].astype(dtype)
        frame_out[(sc, bp, "likelihood")] = lik_new.astype(dtype)

        for code, name in ec.VERDICT_NAMES.items():
            counts[name] += int((codes == code).sum())
        st = dict(st)
        st["flipped"] = bool(flipped)
        stats_out[bp] = st
        arrays["d_tgt__" + bp] = d_tgt.astype(np.float32)
        arrays["d_ref__" + bp] = d_ref.astype(np.float32)
        arrays["codes__" + bp] = codes.astype(np.uint8)
        arrays["xyz__" + bp] = pts3d.astype(np.float32)

    ref_out = _out_path(ref_h5, out_dir, ".h5")
    tgt_out = _out_path(tgt_h5, out_dir, ".h5")
    write_pose_h5(df_ref_out, meta_ref, ref_out)
    write_pose_h5(df_tgt_out, meta_tgt, tgt_out)

    npz_path = _out_path(tgt_h5, out_dir, ".npz")
    np.savez_compressed(str(npz_path), **arrays)

    summary = {
        "config": {
            "ref_h5": str(ref_h5), "tgt_h5": str(tgt_h5),
            "calibration": str(calib_path),
            "ref_cam": ref_cam_key, "tgt_cam": tgt_cam_key,
            "k1": k1, "k2": k2,
            "gate_ref": gate_ref_by_cam, "low_tgt": low_tgt_by_cam,
            "high_conf": high_conf_by_cam, "rescue_floor": rescue_floor_by_cam,
            "overrides": overrides,
            "require_peaks": bool(require_peaks),
            "peak_score_floor": float(peak_score_floor),
        },
        "bodyparts": stats_out,
        "counts": counts,
        "outputs": {
            "ref_h5": str(ref_out), "tgt_h5": str(tgt_out),
            "npz": str(npz_path), "json": str(_out_path(tgt_h5, out_dir, ".json")),
        },
        "verdict_codes": {v: k for k, v in ec.VERDICT_NAMES.items()},
        "peak_screen": screen_totals,
    }
    Path(summary["outputs"]["json"]).write_text(json.dumps(summary, indent=2))
    return summary
