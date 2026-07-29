"""Verify the reprojection engine against a real two-camera session.

Reads the source session READ-ONLY and writes artifacts to --out-dir (default
/tmp/reproject-verify inside the container). Never writes beside the source.

Run:
  docker cp dlc-3D/src/dlc_3d_bp/epipolar_core.py \\
      deeplabcut-webapp-docker-dlc-3d-1:/app/dlc_3d_bp/epipolar_core.py
  docker cp dlc-3D/src/dlc_3d_bp/reprojection.py \\
      deeplabcut-webapp-docker-dlc-3d-1:/app/dlc_3d_bp/reprojection.py
  docker cp dlc-3D/scripts/verify_reprojection.py \\
      deeplabcut-webapp-docker-dlc-3d-1:/tmp/verify_reprojection.py
  docker exec deeplabcut-webapp-docker-dlc-3d-1 python3 /tmp/verify_reprojection.py

(src/dlc_3d_bp is a whole-directory bind mount, so the two module copies are
usually already present; the docker cp lines are the fallback.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, "/app")

from dlc_3d_bp import epipolar_core as ec           # noqa: E402
from dlc_3d_bp.reprojection import (                # noqa: E402
    load_calibration,
    read_pose_h5,
    run_reprojection,
)

SESSION = (
    "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/070126"
)
STEM = (
    "eggtart-1_cam{c}_20260701_094411_10_trig1_fps200_exposure1500_gain10"
    "DLC_HrnetW48_DREADDJan7shuffle1_snapshot_best-180.h5"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=SESSION)
    ap.add_argument("--out-dir", default="/tmp/reproject-verify")
    ap.add_argument("--ref-cam", default="cam_1",
                    help="cam_1 is the better camera on eggtart-1")
    ap.add_argument("--tgt-cam", default="cam_0")
    args = ap.parse_args()

    session = Path(args.session)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ref_idx = args.ref_cam.split("_")[-1]
    tgt_idx = args.tgt_cam.split("_")[-1]
    ref_h5 = session / STEM.format(c=ref_idx)
    tgt_h5 = session / STEM.format(c=tgt_idx)
    calib = session / "calibration.toml"
    for p in (ref_h5, tgt_h5, calib):
        if not p.is_file():
            print("MISSING: {}".format(p))
            return 2

    cams = load_calibration(calib)
    print("cameras: {}".format(sorted(cams)))
    print("reference: {}  target: {}".format(args.ref_cam, args.tgt_cam))

    summary = run_reprojection(
        ref_h5=ref_h5, tgt_h5=tgt_h5, calib_path=calib,
        ref_cam_key=args.ref_cam, tgt_cam_key=args.tgt_cam,
        out_dir=out_dir,
    )

    print("\n{:12s} {:>6s} {:>6s} {:>7s} {:>7s} {:>8s} {:>8s}".format(
        "bodypart", "t_ok", "t_bad", "n_hi", "src", "med", "mad"))
    for name, st in summary["bodyparts"].items():
        print("{:12s} {:6.2f} {:6.2f} {:7d} {:>7s} {:8.3f} {:8.3f}".format(
            name, st["t_ok"], st["t_bad"], st["n_highconf"],
            st["threshold_source"], st["med"], st["mad"]))

    print("\nverdict counts")
    total = sum(summary["counts"].values())
    for name, n in sorted(summary["counts"].items(), key=lambda kv: -kv[1]):
        pct = 100.0 * n / total if total else 0.0
        print("  {:16s} {:9d}  {:5.2f}%".format(name, n, pct))

    # ── Invariants ──
    fails = []
    if summary["counts"]["RESCUE"] <= 0:
        fails.append("no rescues — the whole point of the module")
    if summary["counts"]["REJECT"] <= 0:
        fails.append("no rejects")

    ref_out = Path(summary["outputs"]["ref_h5"])
    tgt_out = Path(summary["outputs"]["tgt_h5"])
    if ref_out.name.replace("_cam{}_".format(ref_idx),
                            "_cam{}_".format(tgt_idx)) != tgt_out.name:
        fails.append("output names do not differ only by the _cam{N}_ token, "
                     "so sibling pairing will not find them")

    src_ref, meta_src = read_pose_h5(ref_h5)
    got_ref, meta_ref_out = read_pose_h5(ref_out)
    if meta_ref_out["key"] != meta_src["key"]:
        fails.append("h5 key changed: {} -> {}".format(
            meta_src["key"], meta_ref_out["key"]))
    if meta_ref_out["is_table"] != meta_src["is_table"]:
        fails.append("h5 storage format changed")
    if not src_ref.equals(got_ref):
        fails.append("reference output is not a faithful copy")

    src_tgt, meta_tgt = read_pose_h5(tgt_h5)
    got_tgt, _ = read_pose_h5(tgt_out)
    if got_tgt.shape != src_tgt.shape:
        fails.append("target shape changed: {} -> {}".format(
            src_tgt.shape, got_tgt.shape))
    if set(map(str, got_tgt.dtypes)) != set(map(str, src_tgt.dtypes)):
        fails.append("target dtypes changed")

    # Every REJECT must be NaN with likelihood 0; every RESCUE must keep its
    # coordinates and carry likelihood >= 0.9.
    with np.load(summary["outputs"]["npz"]) as z:
        sc = meta_tgt["scorer"]
        for bp_name in summary["bodyparts"]:
            codes = z["codes__" + bp_name]
            col = got_tgt[sc][bp_name]
            rej = codes == ec.REJECT
            if rej.any():
                if not np.isnan(col["x"].to_numpy()[rej]).all():
                    fails.append("{}: REJECT rows not NaN".format(bp_name))
                if not (col["likelihood"].to_numpy()[rej] == 0).all():
                    fails.append("{}: REJECT likelihood not 0".format(bp_name))
            res = codes == ec.RESCUE
            if res.any():
                if np.isnan(col["x"].to_numpy()[res]).any():
                    fails.append("{}: RESCUE rows became NaN".format(bp_name))
                if (col["likelihood"].to_numpy()[res] < 0.9).any():
                    fails.append("{}: RESCUE likelihood below floor".format(bp_name))
                src_xy = src_tgt[sc][bp_name][["x", "y"]].to_numpy()[res]
                got_xy = col[["x", "y"]].to_numpy()[res]
                if not np.allclose(src_xy, got_xy, equal_nan=True):
                    fails.append("{}: RESCUE coordinates moved".format(bp_name))
            xyz = z["xyz__" + bp_name]
            if res.any() and not np.isfinite(xyz[res]).all(axis=1).all():
                fails.append("{}: rescued point has no valid 3D".format(bp_name))

    if list(session.glob("*_reprojected.*")):
        fails.append("WROTE INTO THE SOURCE SESSION — must never happen")

    print("\noutputs in {}".format(out_dir))
    if fails:
        print("\nFAILED:")
        for f in fails:
            print("  - {}".format(f))
        return 1
    print("\nAll invariants passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
