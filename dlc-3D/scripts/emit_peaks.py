"""Emit DeepLabCut candidate peaks for a video as <stem>_peaks.npz.

Runs inside deeplabcut-webapp-docker-worker-1, the only container with DLC.
Defaults to CPU and a short frame range so it does not contend for the GPU.

  docker cp dlc-3D/src/dlc_3d_bp/peaks.py \\
      deeplabcut-webapp-docker-worker-1:/tmp/peaks_mod.py
  docker cp dlc-3D/scripts/emit_peaks.py \\
      deeplabcut-webapp-docker-worker-1:/tmp/emit_peaks.py
  docker exec deeplabcut-webapp-docker-worker-1 python3 /tmp/emit_peaks.py \\
      --video "<video>" --out-dir /tmp/peaks --end 200

NOTE: copy peaks.py to /tmp, NOT into /app/dlc_3d_bp — that path is a bind mount
onto the host checkout and a docker cp there writes through to the repository.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np
import torch

MODEL = ("/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
         "DREADD-Ali-2026-01-07/dlc-models-pytorch/iteration-22/"
         "DREADDJan7-trainset70shuffle1")


def _load_peaks_module(path="/tmp/peaks_mod.py"):
    spec = importlib.util.spec_from_file_location("peaks_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--snapshot", default="snapshot-best-180.pt")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-distance", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=200,
                    help="exclusive; keep small unless the GPU is free")
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    pk = _load_peaks_module()
    import cv2
    import yaml
    import deeplabcut.pose_estimation_pytorch as dlcpt

    cfg = yaml.safe_load(open(Path(args.model) / "train" / "pytorch_config.yaml"))
    bodyparts = cfg["metadata"]["bodyparts"]
    model = dlcpt.models.PoseModel.build(cfg["model"])
    state = torch.load(Path(args.model) / "train" / args.snapshot,
                       map_location=args.device, weights_only=False)
    model.load_state_dict(state["model"] if "model" in state else state)
    model.to(args.device).eval()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print("cannot open", args.video)
        return 2
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.start)

    n = args.end - args.start
    XY = np.full((n, len(bodyparts), args.k, 2), np.nan, np.float32)
    SC = np.zeros((n, len(bodyparts), args.k), np.float32)

    # PIPELINE VERIFIED EMPIRICALLY against the existing pose h5 (0.344 px median,
    # 0.975 px p95 on confident markers). Every element below was measured, not
    # assumed — an earlier draft of this script was wrong on all five:
    #   * NATIVE resolution, padded to a multiple of 32. NOT resized to 448x448
    #     (resizing gave 427 px median error).
    #   * ImageNet mean/std normalisation after /255 (plain /255 gave 186 px).
    #   * output is NESTED: out["bodypart"]["heatmap"], not out["heatmap"].
    #   * stride is exactly 2. Using net_width/heatmap_width (1.995) drifts by
    #     ~2 px at the frame edge.
    #   * locref sub-pixel refinement is REQUIRED: without it, 1.116 px median
    #     instead of 0.344 px.
    MEAN = np.array([0.485, 0.456, 0.406], np.float32)
    STD = np.array([0.229, 0.224, 0.225], np.float32)
    STRIDE = 2.0
    locref_std = (cfg.get("model", {}).get("heads", {}).get("bodypart", {})
                     .get("predictor", {}).get("locref_std", 7.2801))

    for i in range(n):
        ok, frame = cap.read()
        if not ok:
            XY, SC = XY[:i], SC[:i]
            break
        h, w = frame.shape[:2]
        H = ((h + 31) // 32) * 32
        W = ((w + 31) // 32) * 32
        im = cv2.copyMakeBorder(frame, 0, H - h, 0, W - w, cv2.BORDER_CONSTANT, value=0)
        rgb = (cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - MEAN) / STD
        t_in = torch.from_numpy(rgb).permute(2, 0, 1)[None].to(args.device)
        with torch.no_grad():
            out = model(t_in)
        hm = torch.sigmoid(out["bodypart"]["heatmap"])[0].cpu().numpy()
        lr = out["bodypart"]["locref"][0].cpu().numpy()
        for j in range(len(bodyparts)):
            cells, sc = pk.extract_peaks(hm[j], k=args.k,
                                         min_distance=args.min_distance)
            # Padding is bottom/right only, so it does not shift the origin, and
            # there is no resize: pad_xy=(0,0), scale_xy=(1,1).
            xy = pk.heatmap_to_image(cells, STRIDE, (0, 0), (1.0, 1.0))
            for p_i in range(args.k):
                if not np.isfinite(cells[p_i]).all():
                    continue
                c_col, c_row = int(cells[p_i, 0]), int(cells[p_i, 1])
                xy[p_i, 0] += lr[2 * j, c_row, c_col] * locref_std
                xy[p_i, 1] += lr[2 * j + 1, c_row, c_col] * locref_std
            XY[i, j] = xy
            SC[i, j] = sc
        if i % 50 == 0:
            print(f"  frame {args.start + i}", flush=True)
    cap.release()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (Path(args.video).stem + "_peaks.npz")
    np.savez_compressed(dst, xy=XY, score=SC,
                        bodyparts=np.array(bodyparts, dtype=object))
    print("wrote", dst, XY.shape, f"{dst.stat().st_size/1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
