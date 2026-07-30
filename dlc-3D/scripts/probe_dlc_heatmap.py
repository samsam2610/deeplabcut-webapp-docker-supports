"""Print how DeepLabCut turns a heatmap into a pose coordinate.

Runs on CPU over a handful of frames so it does not contend for the GPU.
Read the output, then implement heatmap_to_image accordingly.

  docker cp dlc-3D/scripts/probe_dlc_heatmap.py \\
      deeplabcut-webapp-docker-worker-1:/tmp/probe_dlc_heatmap.py
  docker exec deeplabcut-webapp-docker-worker-1 python3 /tmp/probe_dlc_heatmap.py
"""
from __future__ import annotations

import sys

import numpy as np
import torch

MODEL = ("/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/"
         "DREADD-Ali-2026-01-07/dlc-models-pytorch/iteration-22/"
         "DREADDJan7-trainset70shuffle1")


def main() -> int:
    import deeplabcut.pose_estimation_pytorch as dlcpt
    from deeplabcut.pose_estimation_pytorch.models.predictors import HeatmapPredictor

    cfg_path = MODEL + "/train/pytorch_config.yaml"
    print("config:", cfg_path)

    import yaml
    cfg = yaml.safe_load(open(cfg_path))

    # What the network expects, and what it emits.
    print("\n=== preprocessing config ===")
    for key in ("data", "model"):
        sub = cfg.get(key, {})
        if isinstance(sub, dict):
            for k, v in sub.items():
                s = str(v)
                if len(s) < 120:
                    print(f"  {key}.{k}: {s}")

    print("\n=== predictor ===")
    print("  ", cfg.get("predictor"))

    # A forward pass on synthetic input reveals stride: input size / heatmap size.
    print("\n=== stride, from a forward pass ===")
    try:
        model = dlcpt.models.PoseModel.build(cfg["model"])
        model.eval()
        with torch.no_grad():
            out = model(torch.zeros(1, 3, 448, 448))
        hm = out["heatmap"] if isinstance(out, dict) else out[0]["heatmap"]
        print("  heatmap shape:", tuple(hm.shape))
        print("  implied stride:", 448 / hm.shape[-1])
    except Exception as exc:
        print("  could not build model directly:", type(exc).__name__, exc)
        print("  -> fall back to reading cfg['model']['heads'] for the stride")

    print("\n=== what HeatmapPredictor does with stride ===")
    import inspect
    src = inspect.getsource(HeatmapPredictor.forward)
    for line in src.splitlines():
        if any(t in line for t in ("stride", "scale", "locref", "argmax", "poses")):
            print("   ", line.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
