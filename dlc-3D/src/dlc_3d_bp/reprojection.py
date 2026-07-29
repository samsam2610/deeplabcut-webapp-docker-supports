"""I/O and orchestration for epipolar reprojection of 2D DLC markers.

epipolar_core holds the maths and stays pure; everything that touches disk is
here.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from dlc_3d_bp import epipolar_core as ec

_CAM_RE = re.compile(r"_cam(\d+)_")


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


def run_reprojection(
    ref_h5,
    tgt_h5,
    calib_path,
    ref_cam_key: str,
    tgt_cam_key: str,
    out_dir=None,
    k1: float = 3.0,
    k2: float = 8.0,
    gate_ref: float = 0.6,
    low_tgt: float = 0.6,
    high_conf: float = 0.9,
    rescue_floor: float = 0.9,
    overrides: "dict | None" = None,
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
        st = ec.auto_threshold(
            d, lik_tgt if flipped else lik_ref, lik_ref if flipped else lik_tgt,
            high_conf=high_conf, k1=k1, k2=k2,
        )
        codes = ec.classify(
            d,
            lik_tgt if flipped else lik_ref,
            lik_ref if flipped else lik_tgt,
            t_ok=st["t_ok"], t_bad=st["t_bad"],
            gate_ref=gate_ref, low_tgt=low_tgt,
        )

        pts3d = ec.triangulate_dlt(cam_ref, cam_tgt, xy_ref, xy_tgt)
        codes = ec.apply_gate(codes, ec.plausibility_gate(pts3d, codes))

        # The judged side is the one whose markers are being corrected: normally
        # the target, or the reference for a bodypart the caller flipped.
        if flipped:
            frame_out, meta_j, xy_j, lik_j = df_ref_out, meta_ref, xy_ref, lik_ref
        else:
            frame_out, meta_j, xy_j, lik_j = df_tgt_out, meta_tgt, xy_tgt, lik_tgt

        xy_new, lik_new = ec.apply_verdicts(
            xy_j, lik_j, codes, rescue_floor=rescue_floor
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
            "k1": k1, "k2": k2, "gate_ref": gate_ref, "low_tgt": low_tgt,
            "high_conf": high_conf, "rescue_floor": rescue_floor,
            "overrides": overrides,
        },
        "bodyparts": stats_out,
        "counts": counts,
        "outputs": {
            "ref_h5": str(ref_out), "tgt_h5": str(tgt_out),
            "npz": str(npz_path), "json": str(_out_path(tgt_h5, out_dir, ".json")),
        },
        "verdict_codes": {v: k for k, v in ec.VERDICT_NAMES.items()},
    }
    Path(summary["outputs"]["json"]).write_text(json.dumps(summary, indent=2))
    return summary
