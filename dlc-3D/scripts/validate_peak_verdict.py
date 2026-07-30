"""Score peak-based verdicts against human labels. READ-ONLY on the DLC project.

  docker cp dlc-3D/src/dlc_3d_bp/peaks.py            <c>:/tmp/m_peaks.py
  docker cp dlc-3D/src/dlc_3d_bp/peak_verdict.py     <c>:/tmp/m_verdict.py
  docker cp dlc-3D/src/dlc_3d_bp/labelled_session.py <c>:/tmp/m_session.py
  docker cp dlc-3D/scripts/validate_peak_verdict.py  <c>:/tmp/validate.py
  docker exec <c> python3 /tmp/validate.py --out-dir /tmp/val --device cuda:1
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import time

import numpy as np

ROOT = ("/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
        "DREADD-Ali-2026-01-07")
MODEL = ROOT + "/dlc-models-pytorch/iteration-22/DREADDJan7-trainset70shuffle1"
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
STRIDE, LOCREF_STD = 2.0, 7.2801


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_toml(text):
    out, sec = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            sec = line[1:-1]
            out[sec] = {}
            continue
        if sec is None or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().rstrip(",")
        out[sec][k.strip()] = (v == "true") if v in ("true", "false") else ast.literal_eval(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True,
                    help="explicit; never point this at the DLC project")
    ap.add_argument("--labelled-root", default=ROOT + "/labeled-data")
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-distance", type=int, default=3)
    ap.add_argument("--t-ok", type=float, default=8.0)
    ap.add_argument("--score-floor", type=float, default=0.10)
    ap.add_argument("--low-tgt", type=float, default=0.6)
    args = ap.parse_args()

    if os.path.abspath(args.out_dir).startswith(os.path.abspath(ROOT)):
        print("REFUSING: --out-dir is inside the DLC project")
        return 2

    import cv2
    import torch
    import yaml
    import deeplabcut.pose_estimation_pytorch as dlcpt

    pk = _load("m_peaks", "/tmp/m_peaks.py")
    pv = _load("m_verdict", "/tmp/m_verdict.py")
    ls = _load("m_session", "/tmp/m_session.py")

    cfg = yaml.safe_load(open(MODEL + "/train/pytorch_config.yaml"))
    model = dlcpt.models.PoseModel.build(cfg["model"])
    st = torch.load(MODEL + "/train/snapshot-best-180.pt",
                    map_location="cpu", weights_only=False)
    model.load_state_dict(st.get("model", st))
    model.to(args.device).eval()

    def infer(path):
        img = cv2.imread(path)
        h, w = img.shape[:2]
        H, W = ((h + 31) // 32) * 32, ((w + 31) // 32) * 32
        im = cv2.copyMakeBorder(img, 0, H - h, 0, W - w, cv2.BORDER_CONSTANT, value=0)
        rgb = (cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - MEAN) / STD
        with torch.no_grad():
            o = model(torch.from_numpy(rgb).permute(2, 0, 1)[None].to(args.device))
        hm = torch.sigmoid(o["bodypart"]["heatmap"])[0].cpu().numpy()
        lr = o["bodypart"]["locref"][0].cpu().numpy()
        return hm, lr

    def peaks_for(hm, lr, j):
        cells, sc = pk.extract_peaks(hm[j], k=args.k, min_distance=args.min_distance)
        xy = pk.heatmap_to_image(cells, STRIDE, (0, 0), (1.0, 1.0))
        for i in range(len(sc)):
            if np.isfinite(cells[i]).all():
                c, r = int(cells[i, 0]), int(cells[i, 1])
                xy[i, 0] += lr[2 * j, r, c] * LOCREF_STD
                xy[i, 1] += lr[2 * j + 1, r, c] * LOCREF_STD
        return xy, sc

    sessions = sorted(
        d for d in os.listdir(args.labelled_root)
        if os.path.isdir(os.path.join(args.labelled_root, d))
        and os.path.exists(os.path.join(args.labelled_root, d, "calibration.toml")))

    report, t0 = {}, time.time()
    for name in sessions:
        sdir = os.path.join(args.labelled_root, name)
        try:
            sess = ls.load_labelled_session(sdir)
        except Exception as exc:
            print("skip", name, type(exc).__name__)
            continue
        if not sess["pairs"]:
            continue
        cal = _parse_toml(open(sess["calibration_path"]).read())
        if "cam_0" not in cal or "cam_1" not in cal:
            continue

        import sys
        sys.path.insert(0, "/tmp")
        from dlc_3d_bp import epipolar_core as ec

        def mkcam(key):
            s = cal[key]
            return ec.Cam(name=str(s.get("name", key)),
                          K=np.asarray(s["matrix"], float).reshape(3, 3),
                          dist=np.asarray(s["distortions"], float).reshape(-1),
                          rvec=np.asarray(s["rotation"], float).reshape(3),
                          tvec=np.asarray(s["translation"], float).reshape(3),
                          size=(int(s["size"][0]), int(s["size"][1])))

        c0, c1 = mkcam("cam_0"), mkcam("cam_1")
        F = ec.fundamental_matrix(c1, c0)      # cam1 trusted, cam0 judged
        bps = sess["bodyparts"]
        orig_err, corr_err, counts, occl_total, occl_refused = [], [], {}, 0, 0

        for pair in sess["pairs"]:
            hm0, lr0 = infer(pair["cam0_image"])
            for j, _bp in enumerate(bps):
                ref = pair["cam1_xy"][j]
                if not np.isfinite(ref).all():
                    continue                     # no trusted marker: not judged
                xy, sc = peaks_for(hm0, lr0, j)
                u_ref = ec.undistort_to_pixels(c1, ref[None, :])
                u_pk = ec.undistort_to_pixels(c0, np.nan_to_num(xy, nan=1e9))
                d = ec.epipolar_distance(F, np.repeat(u_ref, len(u_pk), axis=0), u_pk)
                d[~np.isfinite(xy).all(axis=1)] = np.nan
                verdict, chosen = pv.peak_verdict(d, sc, args.t_ok, args.score_floor)
                counts[verdict] = counts.get(verdict, 0) + 1

                truth = pair["cam0_xy"][j]
                if not np.isfinite(truth).all():
                    occl_total += 1              # annotator says not visible
                    if verdict == pv.NO_EVIDENCE:
                        occl_refused += 1
                    continue
                if sc[0] >= args.low_tgt:
                    continue                     # confident already: not our population
                orig_err.append(float(np.linalg.norm(xy[0] - truth)))
                if verdict == pv.CORRECTED:
                    corr_err.append(float(np.linalg.norm(xy[chosen] - truth)))
                else:
                    corr_err.append(float(np.linalg.norm(xy[0] - truth)))

        report[name] = {
            "pairs": len(sess["pairs"]),
            "n_lowconf": len(orig_err),
            "median_original_px": float(np.median(orig_err)) if orig_err else None,
            "median_after_px": float(np.median(corr_err)) if corr_err else None,
            "occluded_cells": occl_total,
            "occluded_refused": occl_refused,
            "verdicts": {str(k): v for k, v in sorted(counts.items())},
        }
        r = report[name]
        print(f"{name:26s} pairs={r['pairs']:4d} lowconf={r['n_lowconf']:5d} "
              f"orig={r['median_original_px']} after={r['median_after_px']} "
              f"occl={occl_refused}/{occl_total}", flush=True)

    os.makedirs(args.out_dir, exist_ok=True)
    dst = os.path.join(args.out_dir, "peak_verdict_validation.json")
    with open(dst, "w") as fh:
        json.dump({"config": vars(args), "sessions": report}, fh, indent=2)
    print("\nwrote", dst, f"({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
