#!/usr/bin/env python3
"""Stage-1 acceptance: are the human onsets actually candidate frames?

This is THE gate on stage 1. Anything the sweep and window logic drop, stages 2
and 3 can never recover, so a regression here is silent and fatal. Run it after
touching intervals.py, ncc.py or the tuned constants.

    python3 scripts/acceptance.py                 # every Tag=Done video
    python3 scripts/acceptance.py banh-mi         # substring filter

Sweeps are cached, so the first run costs ~3.5 min per video and later runs are
seconds. Set SAM_TRAINING_PATH_MAP when running outside the container.

Reference numbers, 2026-08-11, on the tuned defaults: the worst-case session
(banh-mi-1 Jul 2) retains 82/82. Falling much below ~95% overall means the
window logic regressed.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, intervals, ncc, notes, rig, store, tracked  # noqa: E402

PROJECT = os.environ.get(
    "SAM_TRAINING_PROJECT",
    "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07")
CACHE = Path(os.environ.get("SAM_TRAINING_CACHE", "/tmp/sam-training-sweeps"))


def sweep_cached(video: str):
    got = store.load_sweep(video, config.SWEEP_STRIDE, root=CACHE)
    if got is not None:
        return got, 0.0
    calib = rig.calibrate(video)
    template = rig.load_template(calib)
    t0 = time.time()
    sw = ncc.sweep_video(video, template, calib.search_box)
    store.save_sweep(video, config.SWEEP_STRIDE, sw.frames, sw.scores,
                     sw.n_frames, root=CACHE)
    return (sw.frames, sw.scores, sw.n_frames), time.time() - t0


def evaluate(video: str) -> dict:
    (frames, scores, _n), elapsed = sweep_cached(video)
    ivs = intervals.present_intervals(frames, scores)
    rows = notes.read_notes(video)
    trials = notes.pair_trials(rows)
    wins = intervals.build_windows(trials, ivs)
    known = [w for w in wins if w.onset_frame is not None]
    return {
        "name": Path(video).stem[:40],
        "trials": len(trials),
        "windows": len(wins),
        "known": len(known),
        "in_span": sum(1 for w in known if w.start <= w.onset_frame <= w.end),
        "candidate": sum(1 for w in known if w.is_candidate(w.onset_frame)),
        "med_cands": int(np.median([w.n_candidates for w in wins])) if wins else 0,
        "sweep_s": elapsed,
    }


def main() -> int:
    needle = sys.argv[1] if len(sys.argv) > 1 else ""
    videos = [config.to_local(p) for p in tracked.tag_done_videos(PROJECT)]
    videos = [v for v in videos if needle in v]
    if not videos:
        print("no Tag=Done videos matched", file=sys.stderr)
        return 2

    total = {"known": 0, "in_span": 0, "candidate": 0, "windows": 0}
    for video in videos:
        if not Path(video).is_file():
            print(f"{Path(video).stem[:40]:40s}  MISSING", flush=True)
            continue
        r = evaluate(video)
        for k in total:
            total[k] += r[k]
        pct = 100 * r["candidate"] / max(1, r["known"])
        print(f"{r['name']:40s} trials={r['trials']:4d} win={r['windows']:4d} "
              f"span={100*r['in_span']/max(1,r['known']):5.1f}% "
              f"cand={pct:5.1f}% med_cands={r['med_cands']:5d} "
              f"sweep={r['sweep_s']:.0f}s", flush=True)

    known = max(1, total["known"])
    pct = 100 * total["candidate"] / known
    print(f"\n{total['windows']} windows over {total['known']} tagged trials")
    print(f"  onset inside window span : {total['in_span']}/{total['known']} "
          f"({100*total['in_span']/known:.1f}%)")
    print(f"  onset IS a candidate     : {total['candidate']}/{total['known']} "
          f"({pct:.1f}%)   <-- the gate")
    # Non-zero exit on a clear regression so this can gate CI later.
    return 0 if pct >= 90.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
