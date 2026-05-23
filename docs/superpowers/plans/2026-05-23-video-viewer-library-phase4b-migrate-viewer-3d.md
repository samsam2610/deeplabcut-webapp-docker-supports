# Video-Viewer Library — Phase 4b (migrate viewer_3d.js / View Analyzed card) Plan

> **For agentic workers:** This is the largest, riskiest migration in the project — it rewrites the 3223-line `viewer_3d.js` + `card_viewer_3d.html` onto the shared library AND co-evolves the E2E guard. Execute as a focused effort. Correctness gate = the co-evolved `test_analyzed_viewer.py` (behavioral) + live-app driving against the `tdcs` sync-cam data. Do NOT delete old code until both pass.

**Goal:** Move the "View Analyzed" card off its private 3223-line `viewer_3d.js` onto `VideoViewer` + `statusNoteTimeline` + `markerEditor` (+ thin consumer glue), eliminating the half of the ~7000-line `viewer_3d`↔`inline_analysis_3d` duplication that lives in `viewer_3d.js`. (4c migrates `inline_analysis_3d.js` the same way, completing the dedup.)

**Branch:** `feat/3d-inline-analysis`. **Baseline (recorded 2026-05-23):** `test_analyzed_viewer.py` = 12 pass / 1 fail (the 1 is the white-box `…banner_uses_split_format…` canary). Library node suite + 5 contracts green.

---

## Why this is hard (findings from investigation)

1. **E2E is white-box + DOM-coupled.** Most `test_analyzed_viewer.py` tests use `window.__va3dController.{tiles[],currentFrame,tiles[].primaryH5Path,tiles[].pendingEdits}` and target `va3d-*` DOM. The migration replaces both the internals (library structures) and the DOM (`vv-*`). **Tests must co-evolve with the migration — they can't be hardened in advance.**
2. **Library gap — per-tile sizing.** The card has per-tile weight sliders (`.va3d-tile-size`) + Equalize (`#va3d-equalize-btn`) → `flex-grow` (guarded by `test_per_tile_size_slider_updates_flex_grow`). `VideoViewer` has a single zoom, no per-tile sizing. **Resolution (this plan): add an optional per-tile weight to `VideoViewer`** (`tile.setWeight(pct)` → `flex-grow`; `viewer.equalizeTiles()`), exposed because 4c needs it too. Small, backward-compatible enhancement + its own node-testable reducer if any math.
3. **Per-cam h5 pairing** (`/dlc-3d/analyzed/sibling-h5`) is consumer-specific → glue: the consumer resolves the sibling h5 and calls `markerEditor.setSibling(h5)`. `markerEditor` already renders `siblingLayers` read-only on cam1 via `onDrawTile` ✓.
4. **Split edit banner** ("cam0: X · cam1: Y"): `markerEditor` shows a single count. Since tile-1 editing is deferred in the fork too, cam1 is always 0. **Resolution:** accept the single-count banner (minor behavior change) OR have the consumer format the split from `markerEditor.getEditCount()`. Recommend single-count; update the test accordingly.
5. **What maps cleanly:** multi-tile frame-locked seek (VideoViewer), 3 frame modes (injected `endpoints.frame`), overlay + cam0 editing + bp chips + threshold + marker size (markerEditor), CSV annotation with save (statusNoteTimeline with `saveRow`), curation + content-list/tabs/browse launcher (consumer glue, per the curation decision).

---

## Mapping: viewer_3d.js → library + glue

| Responsibility | → |
|---|---|
| Controller multi-tile + frame-locked seek; 3 frame modes | **VideoViewer** (`load({videoPath, siblingPath, frameCount, framesMode})`, `seek`), injected `endpoints.frame/videoInfo/sibling` |
| Per-tile size sliders + Equalize | **VideoViewer enhancement** (`tile.setWeight`, `equalizeTiles`) + consumer wires the `.vv-tile`-injected sliders |
| Playback/seek/zoom/skip/frame-counter chrome | consumer `_wireViewerChrome` (like 4a) |
| Overlay: layers, poses, prefetch, editing, bp chips, threshold, marker size, edit banner | **markerEditor** (`setPrimary/addCompare/clearCompare/setSibling/setThreshold/setOverlayEnabled/selectBp`, els for chips/banner/threshold) |
| Per-cam sibling-h5 resolution | consumer glue: fetch `/dlc-3d/analyzed/sibling-h5`, call `markerEditor.setSibling(resolvedH5)` |
| CSV status/note timeline + chips + nav + save-row + create-csv | **statusNoteTimeline** (els incl. wraps; `endpoints.csv`, `saveRow`) + consumer create-csv glue |
| Content list, Project/Browse tabs, folder browser, `_vaOpenVideo/FrameFolder/BrowseVideo` | consumer glue (launcher) |
| Curation (extract/add-to-dataset/batch, both-cams) + Finalize | consumer glue (compose; per the curation-is-composition decision) |
| `window.__va3dController` globals | replace: expose a minimal `window.__vaViewer` (the `VideoViewer` instance) for any test hook still needed; rewrite tests to behavioral where possible |

---

## Execution sequence

**Step 0 — per-tile sizing enhancement (library, additive, do first):**
Add to `VideoViewer`: each tile gets an optional weight (`flex-grow`); `viewer.setTileWeight(i, pct)` + `viewer.equalizeTiles()`; and (optional) render a per-tile size slider into each `.vv-tile` when `config.perTileSize` is set, OR expose the tiles so the consumer injects sliders. Add/extend the contract test. Node-test any pure math. Keep backward-compatible (4a's extract card unaffected). Verify node suite + contracts green; smoke 4a still works.

**Step 1 — card markup → mounts:** Restructure `card_viewer_3d.html`: replace the `#va3d-tile-row` + per-tile template with a `#va3d-viewer-mount` (VideoViewer generates tiles). Keep all controls/overlay/CSV/curation/tab markup; re-point ids as feature `els`. CSS parity for `vv-tile` (incl. per-tile size sliders + the overlap lessons from 4a: no forced aspect-ratio; tiles share width; `max-height`).

**Step 2 — rewrite `viewer_3d.js` → consumer module:** Build the composition (`VideoViewer` + `statusNoteTimeline` + `markerEditor`), wire chrome + overlay controls + CSV panel + per-cam h5 resolution + sync-cam toggle (calibration-gated, frame-preserving — reuse 4a's pattern) + content-list/tabs/browse launcher + curation glue. Keep the 3 frame modes via injected `endpoints.frame`. Expose `window.__vaViewer` for tests.

**Step 3 — co-evolve `test_analyzed_viewer.py`:** Rewrite each test to the new `vv-*` DOM + behavioral assertions:
- `tiles.length` waits → count `#va3d-viewer-mount .vv-tile`.
- `currentFrame` → `#va3d-frame-counter` text.
- per-tile-size → new slider DOM + `flex-grow`.
- `primaryH5Path` pairing (test 8) / sibling markers (test 13) → assert markers actually render on both tile canvases (pixel check, already partly behavioral).
- split banner (test 11) → assert single-count banner after a real edit (or drop if behavior changed; document).
- curation/both-cams/save-frame-routing (tests 9,10,14) → unchanged (curation stays glue; route-interception is robust).
Run against the rewritten card; all green except any intentionally-changed behavior (documented).

**Step 4 — live verification** (drive the app vs `tdcs/050926` sync-cam pair + an analyzed h5): tiles, frame-locked seek, overlay markers on BOTH tiles, marker editing on cam0, bp chips, threshold, status/note timeline + save, per-tile size, sync-cam toggle. Do NOT click curation Extract (writes data). Screenshot.

**Step 5 — delete dead `viewer_3d.js` code** only after Steps 3+4 pass. Note: `inline_analysis_3d.js` still references the shared patterns until 4c; do not break it.

---

## Risks / decisions to confirm during execution

- **Per-tile sizing**: chosen to be a `VideoViewer` enhancement (needed by 4b+4c). If it balloons, fall back to consumer-glue sliders over `vv-tile`s.
- **Split banner**: recommend single-count (accept minor change) — confirm acceptable, update the test.
- **`window.__va3dController` removal**: expose `window.__vaViewer` for the minimal hooks tests still need; prefer behavioral assertions.
- **Frame modes**: the consumer's `endpoints.frame` closure must dispatch video/frames/browse exactly as `_vaFrameUrl` did.
- **inline_analysis_3d (4c)** shares ~95% with viewer_3d; once 4b lands, 4c should be a near-mechanical repeat (compose the same library + add the curation toggle). The real dedup payoff lands when both are done.

---

## Exit criteria

- View Analyzed card runs on `VideoViewer` + `statusNoteTimeline` + `markerEditor` + thin glue; dead `viewer_3d.js` code removed.
- Co-evolved `test_analyzed_viewer.py` green (behavioral); per-tile-size + sync + seek + overlay + CSV verified.
- Live-app checklist passes against real sync-cam + h5 data.
- Library node suite + all contracts green; 4a extract card still works (per-tile-size enhancement backward-compatible).

**Next:** Phase 4c (`inline_analysis_3d.js` → same composition + curation toggle) — completes the ~7000-line dedup. Phase 5 — policy doc + enforcement test.
