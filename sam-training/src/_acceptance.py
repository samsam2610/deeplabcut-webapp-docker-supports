"""Leave-one-session-out acceptance measurement.

Not a module of the pipeline — a harness that drives it, kept under src/ only
because that is what is mounted into the container. Run detached:

    docker compose exec -d sam-training python -m src._acceptance

Ground truth is the human `start-*` tag on the ten Tag=Done videos. Holding a
session out is automatic: `exemplars.for_query(..., exclude_video=stem)` already
excludes the session being scored, and DINOv3 is frozen, so there is no training
contamination to reason around.

Three numbers, because collapsing them hides where a loss happens:

  reachable   the onset is inside an armed window at all — stage 1 is the recall
              gate, and anything it drops nothing downstream can recover
  accurate    |pick - onset| <= 5 among reachable trials — stage 2/3 quality
  end-to-end  |pick - onset| <= 5 over ALL paired trials, which is the number
              that matters when deciding whether to trust a batch

Results stream to `/app/data/sam-training/acceptance.csv` as they are produced,
so a run that is stopped early still yields everything up to that point.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

from src import (api_sam, config, exemplars, notes, pellet_model as pm,  # noqa: E402
                 pipeline, stereo, sweep2, sweep_cache, tracked)

PROJECT = "/user-data/Parra-Data/Disk/DLC-Projects/DREADD-Ali-2026-01-07"
OUT = Path("/app/data/sam-training/acceptance.csv")
LOG = Path("/app/data/sam-training/acceptance.log")

# Trials scored per session, evenly spaced. 40 x 10 sessions is ~400 trials,
# which pins the end-to-end rate to about +-2.5 % — ample to decide with, at a
# quarter of the cost of all 1304. Raise it to re-run wider.
PER_SESSION = 40
PROMPT = "right paw"
TOPK = 5
TOLERANCE = 5

COLUMNS = ["session", "marker", "onset", "pick", "error", "reachable",
           "n_candidates", "mode", "seconds"]


def say(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ensure_sweep(video, sibling):
    """Sweep the pair if it is not already cached, with THIS video's geometry."""
    model = pm.load(PROJECT)
    if sweep_cache.load_pair(video, model, []) is not None:
        return "cached"
    cal = stereo.load(stereo.find_for_video(PROJECT, video))
    resolved = pm.with_centres(model, {})          # project-default box
    # The reference must live in this calibration's frame, so derive it the same
    # way a placed box would: triangulate the two default centres.
    marks = [{"frame": 1, "kind": "box", "cam": c,
              "x": resolved.cameras[c].cx, "y": resolved.cameras[c].cy}
             for c in ("cam0", "cam1") if c in resolved.cameras]
    resolved = pipeline.with_reference(resolved, cal, marks)
    t0 = time.time()
    sw = sweep2.sweep_pair(video, str(sibling), resolved, cal,
                           stride=config.SWEEP_STRIDE)
    sweep_cache.save_pair(video, sw.frames, sw.score0, sw.score1, sw.dist3d,
                          sw.n_frames, model=model, marks=[])
    return f"swept in {time.time() - t0:.0f}s"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not OUT.exists():
        with open(OUT, "w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()
    done = set()
    with open(OUT, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            done.add((r["session"], r["marker"]))

    videos = [config.to_local(p) for p in sorted(tracked.tag_done_videos(PROJECT))]
    say(f"=== acceptance over {len(videos)} sessions, "
        f"{PER_SESSION}/session, tolerance +-{TOLERANCE} ===")

    for vi, video in enumerate(videos, 1):
        stem = Path(video).stem
        short = stem[:34]
        sibling = pm.sibling_video(video)
        if sibling is None:
            say(f"[{vi}/{len(videos)}] {short}: no cam1, skipped")
            continue
        say(f"[{vi}/{len(videos)}] {short}: {ensure_sweep(video, sibling)}")

        st = pipeline.windows_for(PROJECT, video)
        if st is None:
            say(f"    no sweep after all — skipped")
            continue
        paired = [w for w in st.windows if w.onset_frame is not None]
        if not paired:
            say("    no paired trials")
            continue
        step = max(1, len(paired) // PER_SESSION)
        sample = paired[::step][:PER_SESSION]
        say(f"    {len(paired)} paired trials, scoring {len(sample)}")

        hits = reach = n = 0
        for w in sample:
            if (stem, str(w.end)) in done:
                continue
            t0 = time.time()
            try:
                res = api_sam._score_window(None, video, w.start, w.end,
                                            w.outcome, PROMPT, TOPK)
                pick = int(res["pick"])
            except Exception as exc:                        # noqa: BLE001
                say(f"    marker {w.end}: {type(exc).__name__}: {exc}"[:160])
                continue
            err = pick - w.onset_frame
            ok_reach = w.is_candidate(w.onset_frame)
            n += 1
            reach += int(ok_reach)
            hits += int(abs(err) <= TOLERANCE)
            with open(OUT, "a", newline="", encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=COLUMNS).writerow({
                    "session": stem, "marker": w.end, "onset": w.onset_frame,
                    "pick": pick, "error": err, "reachable": int(ok_reach),
                    "n_candidates": w.n_candidates, "mode": "2d",
                    "seconds": round(time.time() - t0, 1)})
        if n:
            say(f"    -> reachable {reach}/{n} ({100*reach/n:.0f}%), "
                f"within +-{TOLERANCE}: {hits}/{n} ({100*hits/n:.0f}%)")

    say("=== done ===")


if __name__ == "__main__":
    main()
