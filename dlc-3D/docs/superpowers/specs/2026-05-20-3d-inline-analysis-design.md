# 3D Inline Analysis — Design Spec

**Date:** 2026-05-20
**Status:** Approved for implementation planning
**Module:** `dlc-3D` (repo: `deeplabcut-webapp-docker-supports`, branch `main`)
**Depends on:** the main webapp's 2D inline-analysis backend (`deeplabcut-webapp-docker`), used as-is.

## Goal

Add a **3D Inline Analysis** card to the `dlc-3D` page that lets a user scrub a
stereo (two-camera) recording, run DLC pose inference on **both** camera videos
over the same frame range against a warm in-memory model, and view the
just-produced markers on both camera views immediately — mirroring the 2D
Inline Analysis card built in the main webapp.

It is the stereo analogue of the main webapp's Inline Analysis card. Two
behavioural differences from the 2D version:

1. **One Analyze click analyzes both cameras** (cam0 + cam1) at the same
   `start_frame` for the same `n_frames`.
2. **Viewing reuses the 3D view-analyzed viewer** (`viewer_3d.js`'s dual-tile,
   per-camera marker overlay).

## Key constraints (discovered during exploration)

- **dlc-3D cannot run DLC inference.** Its worker (`dlc-3d-worker`, queue
  `lp_3d`) only has Lightning-Pose — no `deeplabcut`/torch DLC stack. DLC
  inference can only run in the **main webapp's `worker`** (queue `pytorch`),
  which already hosts the `dlc_inline_session` warm-worker + `_run_range`.
- **Same-origin reuse works.** The dlc-3D page is reverse-proxied under
  `localhost:5000/dlc-3d/`, so its browser JS can call the main webapp's
  `/dlc/project/inline-analysis/*` and `/dlc/project/snapshots` directly, with
  the shared Flask session cookie (consistent `user_id` for warm-session keying).
- **`viewer_3d.js` already consumes the main webapp's viewer endpoints.** It
  fetches poses from `/dlc/viewer/frame-poses`, `/dlc/viewer/frame-poses-batch`,
  `/dlc/viewer/h5-info`, `/dlc/viewer/h5-variants`, `/dlc/viewer/edit-cache`;
  only frame **images** (`/dlc-3d/frame`) and sibling resolution
  (`/dlc-3d/sibling-camera`, `/dlc-3d/analyzed/sibling-h5`) come from dlc-3D.
  **Consequence:** all the 2D pose-overlay invariants (dense h5, mtime-cache
  invalidation, errored-clears-on-success) are enforced at the main webapp's
  viewer endpoints and are inherited for free. dlc-3D caches no h5s itself.

## Approved decisions

1. **Project source:** the feature uses the **main webapp's active DLC project +
   snapshot**. The user must have the same DLC project active in the main webapp
   (as they already do for 2D Analyze). The snapshot dropdown is populated from
   `/dlc/project/snapshots`.
2. **UI placement:** **one combined card** — a clone of `card_viewer_3d.html` +
   `viewer_3d.js` with an analysis-params block added. Analyze + dual-camera
   marker viewing happen in the same card.
3. **Stereo semantics:** **require a sibling.** If the picked cam0 video has no
   resolvable sibling cam1, the Analyze button is disabled with a clear message.
4. **Viewing scope:** **per-camera 2D markers on both tiles.** No triangulated
   3D plot, no calibration/Anipose wiring.

## Approach: A — frontend-orchestrated, zero new main-webapp backend

The new card's JS calls the main webapp's existing inline-analysis API directly:
one `session/start`, then **two** `/range` POSTs (cam0, cam1) against the one
warm session, polling both `req_id`s. The warm worker processes its queue
sequentially, so two range requests "just work." No server code is added to the
main webapp; the only new server-side need (if any) is in dlc-3D for sibling
resolution, which already exists.

Rejected: a new `/range-stereo` endpoint in the main webapp (one call instead of
two, but adds backend code to another repo for marginal benefit).

## Components (all new code in the `dlc-3D` module)

| Path | Action |
|---|---|
| `src/templates/partials/card_inline_analysis_3d.html` | **new** — clone of `card_viewer_3d.html` (dual cam0/cam1 tiles + overlay) with `va3d-*` → `ia3d-*` renamed, plus an analysis-params block at the top. Section id `inline-analysis-3d-card`, class `card dlc-theme hidden`. |
| `src/static/inline_analysis_3d.js` | **new** — clone of `viewer_3d.js` (`va3d`→`ia3d` rename) + a **stereo analysis-dispatch IIFE** appended at the bottom. |
| `src/templates/dlc_3d.html` | edit — `{% include "partials/card_inline_analysis_3d.html" %}` after the viewer-3d include; add `<script type="module" src=".../inline_analysis_3d.js">` after the viewer_3d.js tag. |
| nav entry-point button | edit — add a "3D Inline Analysis" open button next to the existing card-open buttons (mirror `btn-open-frame-extractor` in `dlc_3d.js`); the clone wires its own open handler (toggle `.hidden` + `scrollIntoView`), matching how `view-analyzed-3d-card` opens. |

### Analysis-params block (top of the new card)

Mirrors the 2D card's params, with `ia3d-` ids:
`ia3d-snapshot` (populated from `/dlc/project/snapshots`), `ia3d-shuffle`,
`ia3d-trainingsetindex`, `ia3d-batch-size`, `ia3d-frames-per-click`,
`ia3d-keep-warm-seconds`, `ia3d-save-csv`, `ia3d-btn-analyze-range`,
`ia3d-last-run-status`, `ia3d-warm-indicator`, `ia3d-refresh-snapshots`,
plus a `ia3d-sibling-status` line showing the resolved cam1 (or "no sibling —
analysis disabled").

## Data flow (one Analyze click)

1. User picks a cam0 video in the card's browser (dlc-3D's existing browse
   path). The card calls `/dlc-3d/sibling-camera?video=…` to resolve cam1.
   - **No sibling ⇒ disable `ia3d-btn-analyze-range`** with a message
     (decision 3).
2. Snapshot dropdown populated from `/dlc/project/snapshots` (decision 1). If the
   main webapp has no active project, the list is empty and the card shows a
   "activate the DLC project in the main webapp" hint.
3. User scrubs to frame K, clicks Analyze:
   a. `POST /dlc/project/inline-analysis/session/start` → `snap_key`
      (one warm session for the model; both cameras share it).
   b. `POST /dlc/project/inline-analysis/range` for **cam0**
      `{snap_key, video_path: cam0, start_frame: K, n_frames: N, …}` → `req0`.
   c. `POST …/range` for **cam1** `{…, video_path: cam1, start_frame: K,
      n_frames: N}` → `req1`.
   d. Poll `GET …/range/status?req_id=…` for **both** until both report `done`
      (or surface `error`).
4. On both `done`: re-resolve each camera's h5
   (`/dlc-3d/analyzed/sibling-h5`), set them as each tile's primary layer, and
   render markers on both tiles at frame K via viewer_3d's existing overlay
   path. Then force a full frame reload so markers paint deterministically
   (the 2D "force `_iaLoadFrame` after analyze" invariant, ported as
   `_ia3dLoadFrame`).

## Reused invariants (inherited; see main webapp policy doc)

Because pose reading goes through the main webapp's viewer endpoints, these are
already enforced and need no new work here — but the clone must not break them:

- **Dense h5** — the main worker writes dense h5s; both cameras' positional
  lookups work.
- **mtime cache invalidation** — `viewer_load_h5` reloads on mtime change, so
  re-analyzing a chunk shows fresh markers (resolved upstream; dlc-3D adds no
  caching of its own).
- **errored clears on success** — carried into the clone's per-layer fetch.
- **chips build in the primary discover/select flow** — carried into the clone.
- **overlay canvas `pointer-events:none` + `width/height:100%`** — preserved
  from `card_viewer_3d.html`.

## Edge cases

- **No sibling camera:** Analyze disabled; message names the file checked.
- **Main webapp project not active / wrong project:** snapshot list empty →
  inline hint; `session/start` returns 409 → surface it in `ia3d-last-run-status`.
- **One camera finishes before the other:** poll both; only render + force-reload
  once both are `done`. If one errors, show which camera failed and still render
  the camera that succeeded.
- **Frame K beyond a camera's length** (cameras slightly different lengths):
  clamp per camera; the range endpoint already clamps `n_frames`.
- **Warm session idle-TTL:** two `/range` submits bump `last_activity` twice;
  no special handling.

## Out of scope (explicit)

- No triangulated 3D plot, no calibration/Anipose triangulation.
- No changes to the main webapp repo (`deeplabcut-webapp-docker`) — Approach A
  reuses its API unchanged.
- No new DLC inference in the dlc-3D worker.
- Single-animal only (matches 2D inline-analysis v1).
- No `/range-stereo` convenience endpoint (frontend submits two `/range` calls).

## Testing

1. **Static guards** (pytest, source-parse — no runtime), in
   `tests/test_inline_analysis_3d_ui_isolation.py` (the module already has a
   `tests/` dir + `conftest.py`):
   - clone parity: `inline_analysis_3d.js` contains the viewer_3d pattern
     symbols, no leftover `va3d` identifiers.
   - stereo dispatch wiring: the dispatch IIFE submits two `/range` calls and
     polls two `req_id`s; calls `session/start` + `/dlc/project/snapshots`.
   - sibling-required: the card disables Analyze when no sibling.
   - canonical endpoints only (same guard family as 2D).
2. **Live Playwright stereo smoke** against the running dlc-3D page
   (`localhost:5000/dlc-3d/?…`): activate a DLC project in the main webapp,
   open the 3D Inline Analysis card, browse to a cam0 video that has a cam1
   sibling, pick a snapshot, scrub to a frame, click Analyze, wait for
   "Last run:", and assert **both** overlay canvases (`ia3d-overlay-canvas-0`
   and `-1`) paint > 100 non-transparent pixels.
3. **No console errors** on the card.

## Files touched (summary)

| Path | Action |
|---|---|
| `src/templates/partials/card_inline_analysis_3d.html` | create |
| `src/static/inline_analysis_3d.js` | create |
| `src/templates/dlc_3d.html` | edit (include + script tag) |
| nav open-button (in `dlc_3d.html` / its bar partial + `inline_analysis_3d.js`) | edit |
| `tests/test_inline_analysis_3d_ui_isolation.py` | create |

## Acceptance criteria

- A "3D Inline Analysis" card opens on the dlc-3D page without hiding others.
- Picking a cam0 video resolves its cam1 sibling; no sibling ⇒ Analyze disabled.
- One Analyze click runs inference on both cameras over the same [K, K+N] via the
  main webapp's warm worker.
- After both complete, markers paint on **both** camera tiles at frame K with no
  manual toggling and no flask restart.
- Static guards + the live stereo Playwright smoke pass; no console errors.
