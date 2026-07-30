# Reprojection rollout checklist

The `dlc-3d` container has NOT been restarted. Everything below is loaded on the
next restart, which is the user's call.

## What is already live without a restart

`src/static/` is a whole-directory bind mount, so the three cloned static files
and the card fragment are already inside the container. They do nothing yet:
nothing loads `inline_analysis_3d_reprojection.js` until the template is re-read.

## What the restart turns on

1. `src/dlc_3d_bp/` is a whole-directory mount, so `epipolar_core.py` and
   `reprojection.py` are present, but gunicorn must reload before the four
   `/dlc-3d/reproject/*` routes are registered.
2. `src/templates/dlc_3d.html` is individually mounted, but Flask caches
   templates in production, so the new `<script>` line needs the reload too.

No `docker-compose.yml` change is required — that is why the card markup ships
as a static fragment instead of a Jinja partial.

## Restart, when the tool is idle

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
# NOTE: `up -d` is a NO-OP here. With no docker-compose.yml change it just
# reports "Container ... Running" and does not reload gunicorn, so the new
# routes stay unregistered. `restart` is what actually reloads the app.
docker compose restart dlc-3d
```

## Smoke test after restart

1. Open `http://localhost:5000/dlc-3d/`.
2. Confirm **3D Inline Analysis - Reprojection** appears directly below
   **3D Inline Analysis** in the launcher list.
3. Open the original card first and confirm it still works — it must be
   untouched.
4. Open the reprojection card. Load the `070126` session, pick the
   `snapshot_best-180` overlay h5 on cam0.
5. Click **Estimate thresholds**. Expect a per-bodypart table with `t_ok`
   roughly 3–22 px and `source` = `self` for most bodyparts. Expected values
   for the reference 070126 session: all 16 bodyparts self-calibrate, t_ok spans
   roughly 3.3 px (Pellet) to 21.5 px (Wrist).
6. Tick **Show epipolar lines** and scrub. Lines should appear on the judged
   camera's tile and pass through well-tracked markers.
7. Click **Run**. Expect `_reprojected.h5` for both cameras plus the `.json`
   and `.npz` beside the source h5 files.
8. Re-open the original 3D Inline Analysis card and confirm its 3D background
   colour and view prefs are unchanged — proof the `ui-setting` namespacing
   holds.

## Known behaviour after rollout

The cloned card deliberately never calls `/dlc/project/inline-analysis/session/stop`, because `snap_key` is shared with the original card and a stop from the clone could kill a warm session the original card is still using. Consequence: a warm analysis session started from the reprojection card lingers until its own `ttl_seconds` expires rather than being torn down when the card closes. This is intended.

## Reading the numbers

Verdict counts in the audit JSON are computed over ALL frames x bodyparts. The design spec's Evidence table quoted percentages over a smaller denominator (only frames where BOTH cameras had a detection), so the same result reads as a smaller percentage here. On the reference 070126 session the engine reports RESCUE 125,524 and REJECT 106,965 out of 4,026,240 total verdicts. Absolute counts are the number to compare, not percentages.

## Rollback

Remove the one `<script>` line from `dlc_3d.html` and restart. The cloned static
files become inert; no data written by a run is removed, since every artifact is
a new `_reprojected.*` file and no original was modified.
