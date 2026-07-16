# Inline 3D "Analyze for tag": Override existing labels — Design

**Date:** 2026-07-16
**Repos:** `deeplabcut-webapp-docker` (backend worker) + `deeplabcut-webapp-docker-supports` / `dlc-3D` (frontend)
**Status:** Approved design, ready for implementation plan
**Extends:** [[2026-07-16-inline-3d-analyze-for-tag-batch-design]]

## Goal

Give the "Analyze for tag" batch an opt-in **override existing labels** mode. By
default the batch preserves every frame that already has data in the selected
model's h5 (today's behavior — those frames might be human-corrected). When the
new checkbox is checked, the batch re-runs the selected model over **every** frame
in the tagged-frame windows and overwrites what's there, including human
corrections — after an explicit confirmation.

## Background (verified on disk)

- The range worker `_run_range` (`deeplabcut-webapp-docker/src/dlc/tasks.py:3022`)
  reads the selected model's per-scorer h5
  (`_resolve_h5_path(video_path, scorer)` → `<stem><scorer>.h5`,
  `tasks.py:2858`) and filters the requested frames through
  `_filter_skip_already_done(target, existing)` (`tasks.py:2783`), which **skips
  any frame whose existing row is not all-NaN** — human OR machine, no
  distinction.
- Human corrections live in that same `<stem><scorer>.h5`, written by the
  marker-edit save with `likelihood == 1.0`
  (`deeplabcut-webapp-docker/src/dlc/viewer.py:186`). (Not used for detection
  here — see YAGNI.)
- The merge in `_run_range` is
  `df_merge = df_range.combine_first(existing)` (`tasks.py:3080`).
  `combine_first` keeps `df_range`'s non-NaN values (the freshly analyzed
  frames win) and fills the rest from `existing`. So once a frame is
  re-analyzed, its new prediction already overwrites the old value — **no merge
  change is needed to overwrite; only the skip must be bypassed.**
- The request payload is built in `range_submit`
  (`deeplabcut-webapp-docker/src/dlc/inline_analysis.py:274`) and consumed by the
  warm worker via Redis.
- Frontend: `_submitRange` (`dlc-3D/src/static/inline_analysis_3d.js`) POSTs
  `/dlc/project/inline-analysis/range`; `_onAnalyzeTagClick` builds the batch
  ranges and dual-cam submits them with a `window.confirm` summary. The tag
  controls live in `.ia3d-tag-batch` next to `#ia3d-tag-lock`.

## Behavior

### New control — `#ia3d-override-labels`

- Checkbox in `.ia3d-tag-batch`, next to `Lock tag`, **unchecked by default**,
  always enabled (independent of the tag-lock state). Label: "override existing
  labels". Title explains it overwrites existing predictions and human
  corrections.
- Modifies **only** the "Analyze for tag" batch. The current-frame and for-range
  analyze buttons are unchanged (they submit with `overwrite=false`).

### Semantics

- **Unchecked (default):** unchanged — the worker skips any frame in the analyzed
  windows that already has data (human or machine). Already-analyzed frames are
  left untouched.
- **Checked:** the batch re-runs the selected model over every frame in the
  tagged-frame windows and overwrites existing rows, including human corrections.

### Confirmation

When Analyze for tag is clicked with override checked, the existing batch-summary
`window.confirm` gains an explicit warning line, e.g.
*"⚠️ Override is ON: this will OVERWRITE existing predictions AND human
corrections in these frames."* Single prompt (folded into the summary confirm).
The warning is generic — an exact already-labeled count is only known inside the
worker.

## Architecture & changes

The two repos are wired only by the `overwrite` JSON field; they can land
independently.

### Backend — `deeplabcut-webapp-docker`

1. `src/dlc/inline_analysis.py` — `range_submit`: add
   `"overwrite": bool(body.get("overwrite", False))` to the enqueued `payload`.
2. `src/dlc/tasks.py`:
   - `_filter_skip_already_done(target_frames, existing_df, overwrite=False)` —
     when `overwrite` is true, return `list(target_frames)` (skip nothing);
     otherwise unchanged.
   - `_run_range` — pass `req.get("overwrite", False)` into
     `_filter_skip_already_done`. No other change (the `combine_first` merge
     already lets re-analyzed frames win).

### Frontend — `dlc-3D`

3. `src/templates/partials/card_inline_analysis_3d.html` — add
   `#ia3d-override-labels` checkbox in `.ia3d-tag-batch`, next to
   `#ia3d-tag-lock`, unchecked.
4. `src/static/inline_analysis_3d.js`:
   - `_submitRange(sk, videoPath, startFrame, nFrames, overwrite = false)` —
     include `overwrite` in the POST body. The two existing callers pass the
     default `false`.
   - `_onAnalyzeTagClick` — read `#ia3d-override-labels`; pass it to both
     `_submitRange` calls; when checked, append the warning line to the confirm
     message.

## Testing

### Backend (`deeplabcut-webapp-docker/tests`)

- `tests/test_inline_analysis_worker.py`: with `existing` holding finite data for
  the target frames —
  - `overwrite=False` → those frames skipped (`n_skipped > 0`, existing values
    retained) — pins current behavior;
  - `overwrite=True` → all frames analyzed (`n_skipped == 0`) and the merged h5
    carries the new values over the old.
- `tests/test_inline_analysis_routes.py`: `overwrite` in the POST body reaches
  the enqueued Redis payload (and defaults to `False` when absent).

### Frontend (`dlc-3D/tests`)

- pytest static guards: `#ia3d-override-labels` present in `.ia3d-tag-batch`,
  unchecked by default; `_submitRange` includes `overwrite` in its body;
  `_onAnalyzeTagClick` reads `#ia3d-override-labels` and adds the warning line to
  the confirm.
- e2e (`tests/e2e/`): checkbox present and unchecked by default (read-only).

## Edge cases

- Override + a tagged window that is entirely un-analyzed → identical to a normal
  run (nothing to overwrite).
- Override unchecked on an already-analyzed window → no-op (all skipped), today's
  behavior.
- `_run_range`'s empty-`to_analyze` branch is unaffected: with `overwrite=True`
  and `n_frames >= 1`, `to_analyze` is non-empty, so inference proceeds.

## Out of scope (YAGNI)

- No likelihood inspection / human-vs-machine distinction (preserve-all was
  chosen, so override is all-or-nothing per window).
- No override on the current-frame or for-range analyze buttons.
- No per-frame already-labeled count surfaced in the prompt.
- No change to the `combine_first` merge.
