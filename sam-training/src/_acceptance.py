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

from src import (api_sam, config, ncc, onset_csv, pellet_model as pm,  # noqa: E402
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


def place_box(video, centres):
    """Write the box into this video's onset sidecar, as placing it would.

    Everything downstream — the cache signature, the reference, the scorer —
    reads the box from the sidecar. Threading an in-memory box through all of
    them for a measurement would mean a second code path, which is how the
    pipeline and the panel came to disagree twice already. So the harness does
    what a person does: it places the box, then runs the real path.

    Read-modify-write: any trace already in the sidecar is carried through.
    """
    build = onset_csv.Build()
    for row in onset_csv.read(video):
        if str(row.get("mark_kind") or "").strip():
            continue                              # marks are replaced wholesale
        build.rows[int(float(row["frame_number"]))] = onset_csv.row_from_csv(row)
    for cam, (x, y) in sorted((centres or {}).items()):
        build.add_mark(1, onset_csv.MARK_BOX, cam, float(x), float(y))
    onset_csv.write(video, build)


def say(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def session_pellet(video):
    """Median labelled Pellet position per camera for this recording's session.

    The box is per video pair for a reason: the pedestal moves between sessions.
    khoai-lang-1 May 6 has its cam1 pellet at (640.6, 402.3) against a project
    default of (592.7, 449.7) — 67 px away, outside the +-62 px search box. The
    first version of this harness used the default everywhere, cam1 never
    matched, nothing armed, and the session reported "no paired trials" despite
    having 132.

    The panel gets this from a human click. Here it comes from the DLC labels,
    which is where the template seed came from in the first place. Reuses
    find_for_video's ranking so "nearest session" means the same thing it does
    everywhere else.
    """
    import csv as _csv, re as _re, statistics as _st
    cal_path = stereo.find_for_video(PROJECT, video)
    if cal_path is None:
        return {}
    labels = Path(cal_path).parent / "CollectedData_Ali.csv"
    if not labels.is_file():
        return {}
    rows = list(_csv.reader(open(labels)))
    if len(rows) < 4:
        return {}
    parts, coords = rows[1][3:], rows[2][3:]
    at = [i for i, (p_, c) in enumerate(zip(parts, coords))
          if p_ == "Pellet" and c == "x"]
    if not at:
        return {}
    i = at[0]
    seen = {}
    for r in rows[3:]:
        m = _re.match(r"img_cam(\d)_", r[2] if len(r) > 2 else "")
        if not m:
            continue
        try:
            x, y = float(r[3:][i]), float(r[3:][i + 1])
        except (ValueError, IndexError):
            continue
        if x == x and y == y:                       # skip NaN
            seen.setdefault(f"cam{m.group(1)}", []).append((x, y))
    return {cam: (_st.median([p[0] for p in v]), _st.median([p[1] for p in v]))
            for cam, v in seen.items() if v}


def derive_box(video, sibling, start):
    """Find THIS session's pellet by matching, when it has no labels of its own.

    eggtart-1 Jul 5 has no labeled-data, so the harness borrowed Jul 1's pellet
    position. The 40 px search margin still found the real pellet — both cameras
    cleared threshold on 30 % of samples — but the REFERENCE derived from that
    stale box sat 2.62 away, so the 3D gate rejected all but 360 of 15 519 hits
    and the session scored 2 % end-to-end. The detections were clustered tightly
    (interquartile spread 0.41), which is what says "wrong reference" rather
    than "unreliable detector".

    A human placing the box on this video would never hit that. This is the
    harness doing the same thing for itself: sample frames, keep the confident
    matches, take their median position.
    """
    import cv2
    import numpy as np
    model = pm.with_centres(pm.load(PROJECT), start)
    out = {}
    for cam, path in (("cam0", video), ("cam1", str(sibling))):
        camera = model.cameras.get(cam)
        if camera is None:
            continue
        cap = cv2.VideoCapture(str(path))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        pts = []
        for i in range(60):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / 60))
            ok, fr = cap.read()
            if not ok:
                continue
            score, pt = pm.match(ncc.to_gray(fr), camera)
            if score >= 0.75:
                pts.append(pt)
        cap.release()
        if len(pts) >= 5:
            a = np.asarray(pts, dtype=float)
            out[cam] = (float(np.median(a[:, 0])), float(np.median(a[:, 1])))
    return out or start


def ensure_sweep(video, sibling, centres):
    """Sweep the pair if it is not already cached, with THIS video's geometry."""
    model = pm.load(PROJECT)
    marks = onset_csv.read_marks(video)
    if sweep_cache.load_pair(video, model, marks) is not None:
        return "cached"
    cal = stereo.load(stereo.find_for_video(PROJECT, video))
    resolved = pm.with_centres(model, centres)
    # The reference must live in this calibration's frame, so derive it the same
    # way a placed box would: triangulate the two default centres.
    resolved = pipeline.with_reference(resolved, cal, marks)
    t0 = time.time()
    sw = sweep2.sweep_pair(video, str(sibling), resolved, cal,
                           stride=config.SWEEP_STRIDE)
    sweep_cache.save_pair(video, sw.frames, sw.score0, sw.score1, sw.dist3d,
                          sw.n_frames, model=model, marks=marks)
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
        centres = session_pellet(video)
        # Labels from a DIFFERENT session place the search box well enough but
        # put the 3D reference in the wrong place; find this one's pellet.
        own = Path(stereo.find_for_video(PROJECT, video) or "").parent.name
        if own and not Path(video).stem.startswith(own.rsplit("_", 1)[0] + "_cam0_" + own.rsplit("_", 1)[1]):
            found = derive_box(video, pm.sibling_video(video), centres)
            if found != centres:
                say(f"    borrowed box from {own}; matched this session at "
                    + ", ".join(f"{c} ({x:.0f},{y:.0f})" for c, (x, y) in sorted(found.items())))
                centres = found
        where = ", ".join(f"{c} ({x:.0f},{y:.0f})" for c, (x, y) in sorted(centres.items()))
        say(f"[{vi}/{len(videos)}] {short}: box {where or 'PROJECT DEFAULT (no labels)'}")
        place_box(video, centres)
        say(f"    {ensure_sweep(video, sibling, centres)}")

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
