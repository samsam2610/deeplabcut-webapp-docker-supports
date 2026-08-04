# Epipolar Lines in the 3D Frame Labeler — Design

**Date:** 2026-08-04
**Status:** approved, ready for planning

## Goal

While labelling a stereo frame pair in the 3D frame labeler, project every
point placed on one camera as an epipolar line onto the other camera's tile, so
the corresponding point can be placed on the line rather than guessed. Toggled
by a checkbox and the `P` key, recomputed 2 s after the labels stop changing.

## Why this is cheap to build

Three facts about the existing code make this a small feature rather than a
large one. They were verified, not assumed:

1. **Everything needed lives in one folder.** `_save_single_frame`
   (`src/dlc_3d_bp/routes.py:268`) copies `calibration.toml` into
   `labeled-data/{session_key}/` alongside the `img_cam{N}_{order}_{frame}.png`
   files. In the live `DREADD-Ali-2026-01-07` project on the NAS, all 13
   cam-paired session folders have it — a clean 1:1.
2. **The calibration format already parses.** Its sections are `[cam_0]` /
   `[cam_1]`, which `rp.load_calibration` (`reprojection.py:60`) reads as-is,
   and which map directly onto the `img_cam0_` / `img_cam1_` filename prefix.
3. **Tile canvases are at native image pixel size.** `_fl3dDrawTileMarkers`
   uses `const sx = 1, sy = 1` — label coordinates are image coordinates are
   canvas coordinates. Unlike the reprojection card's overlay, no
   `scaleFor` / `videoToCanvas` conversion is needed anywhere.

`config.toml` is **not** used. It is an Anipose project config (board, filters,
`cam_regex`); the epipolar geometry needs only the intrinsics and extrinsics in
`calibration.toml`. It also does not exist in any `labeled-data` folder, so
depending on it would break the feature.

## Architecture

### 1. `/labeled-frames` reports calibration availability

`labeled_frames()` (`routes.py:611`) gains one field:

```json
{ "frames": [...], "count": N, "session_folder": "...",
  "calibration": { "exists": true, "cams": ["cam_0", "cam_1"] } }
```

Read from `labeled-data/{session}/calibration.toml`; `{"exists": false,
"cams": []}` when absent or unparseable. The client already calls this route on
folder open, so gating the UI costs no extra round trip.

### 2. New route `GET /labeled-epilines`

Query parameters:

| param | meaning |
|---|---|
| `session` | session key, resolved under the active project's `labeled-data/` |
| `ref_cam` | reference camera index (int, e.g. `0`) |
| `tgt_cam` | target camera index (int) |
| `points` | JSON array of `{"bodypart": str, "x": float, "y": float}` |

Response:

```json
{ "segments": { "wrist": [[x1, y1], [x2, y2]], "elbow": null } }
```

`null` means the line is degenerate or misses the target image — the caller
draws nothing for that bodypart.

Body, reusing the existing primitives verbatim so the lines agree exactly with
the reprojection card's overlay:

```python
cams = rp.load_calibration(session_dir / "calibration.toml")
cam_ref, cam_tgt = cams[f"cam_{ref_cam}"], cams[f"cam_{tgt_cam}"]
F = ec.fundamental_matrix(cam_ref, cam_tgt)          # computed ONCE
for p in points:
    pt  = ec.undistort_to_pixels(cam_ref, np.array([[p["x"], p["y"]]]))[0]
    seg = ec.epiline_endpoints(F, pt, *cam_tgt.size)
```

Undistortion is mandatory: `fundamental_matrix` documents that it acts on
undistorted pixel coordinates, and `/reproject/epiline` undistorts before
applying `F`. This is also why the geometry is **not** ported to JavaScript —
`undistort_to_pixels` wraps `cv2.undistortPoints`, whose iterative solve would
be a correctness risk and would silently disagree with the reprojection card.

Errors: `400` for a missing/unparseable `calibration.toml`, an unknown camera
key, or malformed `points`; `403` if the session key escapes the project root.
An empty `points` array returns `{"segments": {}}`, not an error.

One request carries every point, so a fire costs one round trip regardless of
bodypart count.

### 3. Client block in `frame_labeler_3d.js`

Self-contained, mirroring the reprojection card's overlay section.

**Gating.** A `fl3d-epiline` checkbox beside the existing labeler toggles,
enabled only when all three hold:

- sync mode is on (`_fl3dSyncOn`) — without it there is no second tile
- the session folder has `calibration.toml`
- the current pair has both cameras

Each failing condition shows its own hint rather than a dead control:
*"turn on sync to see both cameras"*, *"no calibration.toml in this session
folder"*, *"this frame has only one camera"*.

`P` toggles the checkbox. It is ignored when the checkbox is disabled and when
focus is in an `input` / `textarea` / `select`, matching the existing handler's
guards. `P` is currently unbound: `a`/`d`/`w`/`s` nudge, and `Tab`, `Space`,
`Backspace`, `Delete` and the arrows are taken.

**Which camera is the reference.** The reference is **the camera whose labels
last changed**, not simply the focused one.

The obvious rule — project from the focused camera — breaks the workflow it
exists to serve: you label on cam0, see lines on cam1, click cam1 to use them,
and the guidance vanishes at the moment of use. Keying on last-changed means
clicking into the other tile keeps the lines on screen; they flip only once you
actually modify a label there. On frame change the reference resets to the
focused camera.

**Trigger.** The 2 s wait exists to avoid firing a request on every keystroke
while a point is being adjusted. It therefore applies to *label edits only*.
Two classes of trigger:

- **Debounced (2000 ms, constant `FL3D_EPI_DEBOUNCE_MS`)** — every label
  mutation on the reference camera: place, `w`/`a`/`s`/`d` nudge, delete, and
  visibility toggle. Each mutation resets `_fl3dEpiTimer`.
- **Immediate (no wait)** — enabling the checkbox or pressing `P`, changing
  frame, and switching sync mode on. In each case the labels are already
  settled and the user is waiting to see lines; a 2 s delay would read as the
  feature being broken.

On fire, collect `{bodypart, x, y}` for every bodypart that is labelled and not
hidden (`_flHidden[fname][bp]`) on the reference `fname`, issue one request,
and store `_fl3dEpiSegments = {bp: segment}`.

Turning the checkbox off (or pressing `P` again) clears `_fl3dEpiSegments`,
cancels any pending timer, and repaints the target tile — so no stale line can
outlive the toggle.

**Two invariants.**

- *Drawing never fetches.* Tile repaints run on zoom, pan and hover; a fetch in
  the draw path would be a request storm. The draw code paints only what is
  already stored.
- *A generation counter guards the draw*, exactly as `_reprojDrawGen` does in
  the reprojection card. A response landing after the user has moved on is
  discarded. This is a recorded regression on the sibling overlay — see
  `docs/regression-catalog.md` — not a hypothetical.

**Where the drawing hooks in.** Lines are painted inside
`_fl3dDrawTileMarkers(tile, fname)`, after its marker loop, when
`+tile.dataset.cam` is the target camera. That function already repaints the
tile's own image and markers, so the lines survive every repaint reason.

`_flDraw()` is **not** a sufficient hook on its own: in sync mode it redraws
only the focused tile (`frame_labeler_3d.js:_flDraw`, the `_fl3dSyncOn`
branch), and the lines live on the *non*-focused tile. Segment arrival and
checkbox/`P` toggles therefore repaint the target tile explicitly.

**Style**, matching the reprojection card so the two read identically:

| property | value |
|---|---|
| stroke | `_flColor(bpIndex)` — the marker's and chip's own colour |
| dash | `setLineDash([6, 4])`, `lineWidth = 1` |
| name | at the frame edge via `labelAnchor(seg, order, 14)` + `nameLabelBox` |
| stepping | `order++` only for lines actually drawn, so converging lines don't stack labels |

Both helpers are already extracted and imported directly:
`internal/epiline_label.mjs` and `components/viewer/internal/name_label.mjs`.
No new styling code.

Because tile canvases are native-size, segment coordinates from the endpoint
are canvas coordinates — no scaling.

## Failure behaviour

Missing calibration, a single-camera folder, or an endpoint error clears the
stored segments and shows a status message. Nothing in this feature blocks
labelling; the worst outcome is no lines.

## Testing

**Python** (`tests/test_labeled_epilines_route.py`):
- happy path — two points in, two segments out, cams resolved from indices
- `calibration.toml` missing → 400
- unknown camera index → 400
- session key escaping the project root → 403
- empty `points` → `{"segments": {}}`, not an error
- a point whose line misses the target image → `null`, not an omitted key
- `/labeled-frames` reports `calibration.exists` both true and false

**JS source assertions** (`tests/test_frame_labeler_epiline_wiring.py`, in the
established `test_reproj_panel_wiring.py` style):
- the checkbox and its three distinct gating hints exist
- `P` is bound, and guarded against firing while typing
- `FL3D_EPI_DEBOUNCE_MS` is 2000 and the timer is reset by label mutations
- enabling the checkbox computes immediately rather than going through the
  debounce — the difference between "works" and "looks broken for 2 s"
- toggling off clears the stored segments, so no line outlives the toggle
- the generation counter is declared, incremented, and re-checked after `await`
- **no `fetch(` appears inside the tile-draw path** — the request-storm guard
- the reference camera is chosen by last-changed, not by `_fl3dFocusedCam`

## Scope boundaries

- **Two cameras.** `buildPairMap` handles N, but sync mode renders one sibling
  tile. Three cameras would need a different tile layout; not built for now.
- **No backfill.** Session folders without `calibration.toml` (older folders,
  and projects like `sv-pretrain` that have cam pairs but no calibration at
  all) show the disabled hint. Backfilling them is separate work.
- **Read-only.** This feature never writes a label, and never modifies
  `labeled-data`.
