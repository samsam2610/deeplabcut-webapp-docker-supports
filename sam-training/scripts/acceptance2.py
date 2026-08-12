#!/usr/bin/env python3
"""Stage-1 acceptance for the TWO-CAMERA detector: recall AND precision.

The single-camera harness measured recall only — "is the human onset inside the
armed mask" — and a mask that over-admits scores BETTER on that. That is exactly
how a detector matching white paws at 0.87 passed at 98.9 %. Both numbers are
reported here, always, and neither is meaningful alone.

  recall     of tagged onsets, how many are candidate frames
             (anything lost here is unrecoverable downstream)
  precision  of armed frames, how many really do show a pellet, judged by the
             DLC pellet likelihood in the inline working-layer h5 — an
             INDEPENDENT signal, since it comes from the pose model rather than
             from template matching. Only frames the h5 actually covers count.

    python3 scripts/acceptance2.py            # every Tag=Done video
    python3 scripts/acceptance2.py banh-mi    # substring filter
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import (config, intervals, notes, pellet_model as pm,  # noqa: E402
                 stereo, store, sweep2, tracked)

PROJECT = os.environ.get(
    "SAM_TRAINING_PROJECT",
    "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07")
CACHE = Path(os.environ.get("SAM_TRAINING_CACHE", "/tmp/sam-training-pairs"))
H5_SUFFIX = "DLC_HrnetW48_DREADDJan7shuffle1_iter28_snapshot_best-120.h5"
PELLET_LIKELIHOOD = 0.6


def cached_pair(video0, video1, model, cal):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (Path(video0).stem[:60] + ".pair.npz")
    if key.is_file():
        d = np.load(key)
        return sweep2.PairSweep(d["frames"], d["s0"], d["s1"], d["d"],
                                d["present"].astype(bool), int(d["n"])), 0.0
    t0 = time.time()
    sw = sweep2.sweep_pair(video0, video1, model, cal)
    np.savez_compressed(key, frames=sw.frames, s0=sw.score0, s1=sw.score1,
                        d=sw.dist3d, present=sw.present, n=sw.n_frames)
    return sw, time.time() - t0


def dlc_pellet_likelihood(video):
    """Per-frame pellet likelihood from the working-layer h5, or None."""
    h5 = os.path.splitext(str(video))[0] + H5_SUFFIX
    if not os.path.isfile(h5):
        return None
    try:
        import pandas as pd
        df = pd.read_hdf(h5)
    except Exception:
        return None
    col = [c for c in df.columns if c[-2] == "Pellet" and c[-1] == "likelihood"]
    return pd.to_numeric(df[col[0]], errors="coerce").values if col else None


def evaluate(video0):
    sib = pm.sibling_video(video0)
    if sib is None:
        return {"name": Path(video0).stem[:40], "skip": "no sibling"}
    model = pm.load(PROJECT)
    if model is None or "cam0" not in model.cameras:
        return {"name": Path(video0).stem[:40], "skip": "no pellet model"}
    cal_path = stereo.find_for_project(PROJECT)
    cal = stereo.load(cal_path) if cal_path else None
    sw, secs = cached_pair(video0, str(sib), model, cal)

    ivs = intervals.intervals_from_mask(sw.frames, sw.present)
    trials = notes.pair_trials(notes.read_notes(video0))
    wins = intervals.build_windows(trials, ivs)
    known = [w for w in wins if w.onset_frame is not None]
    recall_hits = sum(1 for w in known if w.is_candidate(w.onset_frame))

    # precision, on the armed SAMPLES the h5 can adjudicate
    lik = dlc_pellet_likelihood(video0)
    prec_n = prec_ok = 0
    if lik is not None:
        armed = sw.frames[sw.present]
        inside = armed[armed < len(lik)]
        judged = inside[np.isfinite(lik[inside])]
        prec_n = len(judged)
        prec_ok = int((lik[judged] > PELLET_LIKELIHOOD).sum())

    return {"name": Path(video0).stem[:40], "windows": len(wins),
            "known": len(known), "recall": recall_hits,
            "prec_n": prec_n, "prec_ok": prec_ok,
            "armed_pct": 100.0 * sw.present.mean() if len(sw) else 0.0,
            "secs": secs}


def main() -> int:
    needle = sys.argv[1] if len(sys.argv) > 1 else ""
    vids = [config.to_local(p) for p in tracked.tag_done_videos(PROJECT)]
    vids = [v for v in vids if needle in v and Path(v).is_file()]
    if not vids:
        print("no Tag=Done videos matched", file=sys.stderr)
        return 2

    tot = {"known": 0, "recall": 0, "prec_n": 0, "prec_ok": 0, "windows": 0}
    for v in vids:
        r = evaluate(v)
        if "skip" in r:
            print(f"{r['name']:40s}  skipped: {r['skip']}", flush=True)
            continue
        for k in tot:
            tot[k] += r[k]
        rec = 100 * r["recall"] / max(1, r["known"])
        pre = 100 * r["prec_ok"] / max(1, r["prec_n"])
        print(f"{r['name']:40s} win={r['windows']:4d} armed={r['armed_pct']:4.0f}% "
              f"recall={rec:5.1f}% ({r['recall']}/{r['known']}) "
              f"precision={pre:5.1f}% (n={r['prec_n']}) {r['secs']:.0f}s", flush=True)

    rec = 100 * tot["recall"] / max(1, tot["known"])
    pre = 100 * tot["prec_ok"] / max(1, tot["prec_n"])
    print(f"\nTOTAL over {tot['windows']} windows")
    print(f"  RECALL    {tot['recall']}/{tot['known']} ({rec:.1f}%)   <- onsets kept")
    print(f"  PRECISION {tot['prec_ok']}/{tot['prec_n']} ({pre:.1f}%)   <- armed frames "
          f"with a confident DLC pellet")
    return 0 if (rec >= 90.0 and pre >= 80.0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
