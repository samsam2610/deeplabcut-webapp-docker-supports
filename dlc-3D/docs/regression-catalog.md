# Regression Catalog — inline-3D analysis card (May 2026)

Every bug fixed during the inline-3D / shared-`markerEditor` work, with its **symptom**,
**root cause**, **fix** (commit), and the **regression test** that now guards it. Read the
**Cross-cutting lessons** first — most of these bugs are instances of a handful of recurring
traps; new code in this area should be checked against them.

**Repos:** frontend = `deeplabcut-webapp-docker-supports/dlc-3D` (branch `feat/marker-editor-labeler-mechanics`); backend = `deeplabcut-webapp-docker` (branch `fix/h5-info-fixed-format`). Tests run with `python -m pytest tests/<f>.py -q` and `node --test tests/unit/<f>.mjs`.

---

## Cross-cutting lessons (the traps behind most of these bugs)

1. **Fixed-format vs table-format HDF5.** DLC analysis files come in two HDF5 layouts. *Fixed*
   format (`pandas_type='frame'` — the curated `_analyzed.h5` and some `snapshot_best-*.h5`) has
   `storer.nrows is None` and does **not** support `start`/`stop` row slicing. Any backend code
   that reads an h5 must work for **both**. *(Bug K)* — guarded by
   `test_viewer_h5_endpoints_survive_both_hdf_formats` (parametrized over all 3 h5-reading
   endpoints × both formats).
2. **Client caches keyed by `(h5 path, threshold)` go stale on in-place overwrite.** Inline
   analysis **overwrites the same h5** in place. `markerEditor.posesCache` and `_coverageCache`
   have no mtime/version, so they must be **explicitly invalidated** after an analysis run.
   *(Bugs D, E)*
3. **State cleared on switch/reset must be re-established.** `_resetForOpen` clears overlay/
   coverage/primary state for a clean switch; anything that should re-appear (the finalized-frames
   timeline, the overlay primary after analysis) must be **re-fetched on the right event**
   (`videoLoad`, post-analysis) — clearing without re-establishing = silent emptiness.
   *(Bugs E, L)*
4. **Unify index sources.** A bodypart's color/identity must come from **one** source. Markers use
   the backend `pose.color_idx`; chips iterate `allBodyParts` (from `h5-info`). Deriving a marker's
   color from `allBodyParts.indexOf(pose.bp)` couples it to a *different* source whose strings/
   population can differ → wrong/uniform colors. *(Bug F)*
5. **Keyboard collisions with the base player.** The shared `VideoViewer` owns `Space`
   (play/pause), `Shift+Space`, arrows. Feature keybindings must avoid these. *(Bug H)*
6. **Don't swallow backend errors silently.** `markerEditor.loadLayerInfo` catches an h5-info
   failure and sets `bodyparts = []` with no surfacing — a backend 500 then manifested only as a
   missing chip list, which took an exhaustive repro to trace. *(Bug K)* Prefer guarding the
   backend so it can't fail; if a catch must stay, it hid the root cause for a long time.
7. **Reproduce in the *stateful* flow, not a fresh open.** Several bugs only appeared after
   analyze→finalize→switch→reopen with a specific file format. Fresh-open repros showed everything
   working. When you can't reproduce, gather runtime evidence from the actual failing scenario —
   don't pattern-match to your most recent change. *(Bugs F, K — two fixes missed before the real
   cause was found.)*

---

### Traps found while building the reprojection engine (July 2026)

- **`cv2.undistortPoints` without `P=K` returns NORMALIZED coords, not pixels.** Mixing those
  with a pixel-space fundamental matrix produces a *near-constant* residual (~101.7 px for every
  bodypart) that looks like plausible data rather than an error. Cost a full debugging cycle on
  the first probe. Guard: `test_undistort_to_pixels_differs_from_normalized`.
- **Assigning the scalar `np.nan` upcasts a float32 column to float64.** DLC pose h5 columns are
  `float32`; writing corrections back must assign a float32 *array*
  (`arr.astype(dtype)`), never the bare scalar. The `.astype(dtype)` calls in
  `reprojection.run_reprojection` are load-bearing — do not "simplify" them away. Breaks the
  dtype-preservation checks in `test_reprojection_io.py` and `scripts/verify_reprojection.py`.
- **Assigning a verdict "first-match-wins" only works if the bands cannot overlap.**
  `epipolar_core.classify` originally wrote REJECT before RESCUE/CONFIRM, which silently lost
  REJECT precedence whenever `t_ok > t_bad` — reachable because the UI exposes `k1` and `k2` as
  independent inputs. A marker 12 px off its epipolar line was kept and had its likelihood forced
  to 0.9. Fixed by applying REJECT *last*. Guard:
  `test_classify_reject_wins_even_when_thresholds_are_inverted`. Lesson: a per-function review
  cannot see the UI that supplies the arguments — check the input ranges, not just the defaults.
- **Verdict percentages are denominator-dependent.** Counting over all frames x bodyparts vs only
  frames where both views had a detection changes 8.9% into 3.1% for the same result. Always state
  the denominator; compare absolute counts.

---

## Bug table

| # | Layer | Symptom | Root cause | Fix | Guard test |
|---|-------|---------|------------|-----|------------|
| A | FE | Can't edit/add markers with Finalize checked | editing gated on overlay-on; overlay off at open + first-open `setEditable` race | `2a4818b`, `be6e8f5` (decouple `renderActive = overlayEnabled \|\| editingAllowed`) | `test_b1_render_edit_gate_decoupled_from_overlay`, `test_overlay_auto_enables_for_editing_when_finalize_on` |
| B | FE | View Analyzed editing silently dead | flipping `editingAllowed` default → `false` broke VA, which never calls `setEditable` | `f5db314` (VA mirrors `setEditable`→overlay) | `test_viewer_3d_mirrors_setEditable_to_overlay_enabled_state` |
| C | FE | Marker placed on a *missing* (below-threshold) bodypart records the edit but never draws / can't be grabbed | render + hit-test iterate `cached.poses` only; backend omits below-threshold bps; edits-only bps dropped | `7920f24` (`editedOnlyBodyparts` merged into render + `hitPoses`) | `test_renders_and_hittests_edits_only_markers`; node `test_viewer_marker_overlay::editedOnlyBodyparts*` |
| D | FE | After re-analysis, new markers + timeline don't refresh until manual h5 re-select | client caches `(h5,thr)` not invalidated on in-place overwrite | `8532be6`+`56e7616` (`invalidatePoses()` + `_coverageCache.clear()`) | `test_post_analysis_reestablishes_primary_and_refreshes` |
| E | FE | After "Start analysis", model "unloaded": dropdown blank, markers on stale layer, timeline stale | clean-switch repopulate (`videoLoad`+`_iaDiscoverVariants`) cleared the primary; overlay already on → toggle auto-pick didn't fire | `c780684` (`_reloadPrimaryAfterAnalysis`) | `test_post_analysis_reestablishes_primary_and_refreshes` |
| F | FE | **All markers the same color** | colored by `allBodyParts.indexOf(pose.bp)` → `-1` (string/format mismatch or empty `allBodyParts`) → `labelerColor(0)` | `446a75f` (color by `pose.color_idx`) | `test_primary_markers_use_labelerColor_chips_too` |
| G | FE | Hidden marker still blocks placing near it | `hitPoses` didn't exclude hidden bps | `db84524` (`hitPoses` filters `isHiddenAt`) | `test_hitposes_excludes_hidden_bodyparts` |
| H | FE | `Space` to hide a marker is a no-op | `Space` collides with base player play/pause | `c2c2673` (remap per-frame hide → `h`) | `test_b6_h_toggles_per_frame_visibility` |
| I | FE | Marker hit-zone over-sensitive when placing nearby | default marker size 6 (large hit radius) | `c42a24b` (default size 4) | `test_inline_default_marker_size_is_4` |
| J | FE | Overlay auto-snaps to `_analyzed`; then (over-fix) empty dropdown → no chips for `_analyzed`-only videos | backend lists `_analyzed` as a "Raw" variant; first fix filtered it out of the list entirely | `fe73c40`→`8d2ce0f` (keep selectable; exclude only from auto-pick, fallback if sole) | `test_inline_excludes_analyzed_from_autopick_not_dropdown` |
| K | **BE** | **Bodypart chip list missing** (and shared the all-one-color cause) | `/dlc/viewer/h5-info` did `int(storer.nrows)` → **500 on fixed-format h5** → `loadLayerInfo` silently `bodyparts=[]` | `c8340f2` (h5-info tolerates `nrows is None`) | `test_h5_info_handles_both_hdf_formats`, `test_viewer_h5_endpoints_survive_both_hdf_formats` |
| L | FE | Previously-finalized frames not shown on the "Finalized frames" timeline on reopen | `videoLoad` didn't refresh finalize coverage; `_resetForOpen` cleared it; toggle-`change` (which refreshes) doesn't fire on open | `ae75b44` (`videoLoad` → `_refreshFinalizeCoverage()`) | `test_videoload_refreshes_finalize_coverage` |
| M | FE | (hardening) `clampToBounds` could return `NaN` | non-finite bounds not guarded | `69e9b27` | node `test_clamp_bounds` (non-finite-bounds case) |

---

## Notes on non-bugs (verified, kept for the record)

- **"Marker size adjustment doesn't work"** — *not a bug.* Verified live (size 2→16px … 25→541px);
  `setMarkerSize` + the slider work. The default was just large; lowered to 4 (Bug I), which makes
  the effect feel right.
- **"Finalize wrote 697/800 frames"** — *not a bug.* The working h5 is sparse; `_analyzed` only
  receives the analyzed frames in the range. Surfaced via the status line
  (`cam0 ✓ 697/800 (103 frames in range not yet analyzed)`, commit `af619da`) so it's no longer
  silent. Guard: `test_finalize_status_surfaces_unanalyzed_gap`.
- **"`_analyzed` already-exists popup fired when those frames weren't there"** — the confirm checks
  whether the `_analyzed` *file* exists, not whether the specific frames are populated (acknowledged;
  reword/frame-level check is a future improvement, not yet done).

---

## Where the guard tests live

- **Frontend static-analysis** (`dlc-3D/tests/`): `test_inline_analysis_3d_ui_isolation.py` (card
  wiring/markup), `test_marker_editor_feature.py` (shared feature contract),
  `test_video_viewer_policy.py` (no player fork). These parse the source — they catch wiring/
  contract regressions, not runtime behavior.
- **Frontend pure logic** (`dlc-3D/tests/unit/*.mjs`, `node --test`): `test_viewer_marker_overlay.mjs`
  (`editedOnlyBodyparts`, `posedBodyparts`, hit-test), `test_clamp_bounds.mjs`, `test_tag_list.mjs`,
  `test_bodypart_cycle.mjs`, `test_pick_latest_variant.mjs`, `test_name_label.mjs`.
- **Backend route tests** (`deeplabcut-webapp-docker/tests/`): `test_dlc_viewer_routes.py`
  (h5-info + the parametrized fixed/table guard), `test_ui_setting_tag_keys.py`.
- **Runtime behavior** is verified by driving the live app read-only (Python `playwright.sync_api`);
  these are not in CI (they need the Docker stack + fixtures) but were run for each fix.

Run all: `cd dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_marker_editor_feature.py tests/test_video_viewer_policy.py -q && node --test tests/unit/*.mjs` and `cd deeplabcut-webapp-docker && python -m pytest tests/test_dlc_viewer_routes.py tests/test_ui_setting_tag_keys.py -q`.

## Candidate-peak screen

- **Sidecar path must match on both sides.** `dlc/peaks_emit.py` (main webapp)
  writes it and `dlc_3d_bp/peaks_io.py` reads it. The rule is
  `<pose_h5_stem>_peaks.npz`. A mismatch is silent: the screen simply finds
  nothing and every rescue stands. Guarded by `test_peaks_emit_parity.py`.
- **Absence of peaks is not absence of evidence.** An uncovered frame keeps its
  geometry verdict. Treating absence as `NO_EVIDENCE` would void every rescue in
  every analysis predating the feature.
- **The screen only downgrades `RESCUE`.** Widening it to `CONFIRM` would let
  heatmap noise delete confident markers.
- **Refused rescues make output sparser.** That is the feature working. The audit
  coverage line is what distinguishes it from a fault — this project has twice
  diagnosed a working change as broken because output got sparser.
- **`_run_range` must never gain peak emission.** It is the production inline-3D
  card's inference path. Verify with
  `git diff -U0 src/dlc/tasks.py | grep '^-' | grep -v '^---'` returning nothing.
- **The inference pipeline's five constants are measured, not chosen.** Native
  resolution (never resized), ImageNet normalisation, nested output keys,
  `STRIDE = 2.0`, and locref refinement. Getting any one wrong gave 186–427 px.
