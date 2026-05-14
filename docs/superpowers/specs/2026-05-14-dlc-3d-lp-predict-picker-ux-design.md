---
name: DLC-3D LP Predict — Analyze-style video/output picker
description: Replace the plain textarea in the LP Predict card with the same video/folder picker UX the main webapp's Analyze card uses (tree browser, queue, output folder), reusing `/fs/ls`
type: project
---

# DLC-3D LP Predict — Analyze-style video/output picker

**Date:** 2026-05-14
**Scope:** Bring the LP Predict card's video selection in line with the main webapp's `card_analyze.html` UX. Add an optional output folder field that defaults to each video's parent directory.

**Why:** Users already know the Analyze card's flow. Mirroring it removes a context switch and makes the LP pipeline feel native.

---

## 1. UX parity with the Analyze card

Inside `card_lp_predict.html`, replace the existing `<textarea id="lp-predict-videos">` block with a near-1:1 copy of the Analyze card's target + browser + batch markup. ID prefix is `lp-predict-` instead of `av-`.

### Target (file or folder path)

- Text input `#lp-predict-target` with monospace font + placeholder hint
- `↑ Up` button `#lp-predict-browse-up` — navigates one level up
- `Browse` button `#lp-predict-browse-btn` — toggles the tree open/closed
- Inline browser pane `#lp-predict-browser` — 240px max height, hidden by default

### Batch queue

- `+ Add to queue` button `#lp-predict-batch-add-btn` — adds the typed target OR the highlighted entry
- `✕ Clear queue` button `#lp-predict-batch-clear-btn` — empties the queue
- Helper text: "Single-click to highlight · double-click to add instantly"
- Queued paths list `#lp-predict-batch-list` — monospace lines, each row with a small `×` button to remove

### Output folder (NEW relative to the current Predict card)

- Label: "Output folder *(default: same folder as each video)*"
- Text input `#lp-predict-destfolder`
- `↑ Up` button `#lp-predict-dest-up`
- `Browse` button `#lp-predict-dest-browse-btn`
- Inline browser pane `#lp-predict-dest-browser`
- `✕` clear button `#lp-predict-dest-clear-btn` (clears to the default)

Empty value = default behaviour (one folder per video).

---

## 2. Behaviour — mirrors `analyze.js`

A small helper inside `lp_cards.js`, written from scratch (not imported from analyze.js — that module is bound to many DLC-specific elements):

| Interaction | Source mirror | Behaviour |
|---|---|---|
| Click `Browse` (closed) | `avBrowseBtn` | Open the pane at the typed target, OR at the active LP project (`<dlc>-LP/`) if the field is empty, OR at `/user-data` if no DLC project loaded |
| Click `Browse` (open) | same | Close the pane |
| Click row (dir or file) | `_avSetHighlight` | Highlight the row, copy its full path into the target input |
| Click row (dir) | `_avMakeEntry` | Also expand/collapse the dir in-place (lazy fetch via `/fs/ls`) |
| Double-click row | `_avMakeEntry dblclick` | Add the path to the queue, copy into target input, close the pane |
| `Enter` in target input | analyze.js keydown | Browse the typed path |
| `↑ Up` button | `avBrowseUp` | Browse the parent of the typed/current path |
| `+ Add to queue` | `avBatchAddBtn` | Push highlighted-or-typed path onto the queue; no-op on duplicates |
| `✕ Clear queue` | `avBatchClearBtn` | Empty queue + DOM list |
| Row `×` in queue list | (new) | Remove that one entry |

Same allowlist as analyze.js for what shows up in the tree:
- Directories visible if `has_media !== false` (server-provided hint), and
- Files visible if extension is in `_AV_VIDEO_EXTS ∪ _AV_IMAGE_EXTS`

A `has_media` hint is whatever `/fs/ls` returns — we don't second-guess it.

### Endpoint

`/fs/ls?path=<absolute>` — served by the main webapp (already used by analyze.js). The dlc-3D page loads on the same origin (`localhost:5000`), so the same-origin `fetch("/fs/ls?…")` reaches the main Flask without any reverse-proxy plumbing on our side.

---

## 3. Output folder semantics

`litpose predict` writes everything to `<model_dir>/video_preds/` and gives no `--output_dir` flag. To honour the user's choice (and to match the Analyze card's "outputs land next to the video by default" expectation), the Celery task post-processes the predict run:

1. Run `litpose predict <model_dir> <video...>` as today.
2. For each input video, locate the produced files under `<model_dir>/video_preds/`:
   - `<video_stem>.csv` (predictions)
   - `<video_stem>_<metric>.csv` (zero or more per-frame loss CSVs)
   - `labeled_videos/<video_stem>_labeled.mp4` (only if `--skip_viz` was not passed)
3. Move each file to the chosen destination:
   - If the request supplied a `dest_dir`, move all outputs there (creating it under `/user-data/` if missing).
   - If `dest_dir` is empty, move outputs into **each video's parent directory** (per-video dest). The labeled mp4 lands next to its source video as `<source>_labeled.mp4`.
4. If `<model_dir>/video_preds/labeled_videos/` is empty after the moves, remove it. Same for `video_preds/`. Leaving the canonical LP output dirs in place if any unrelated files remain.

If a target file already exists at the destination and `overwrite=false`, skip with a warning recorded in the task meta (the LP `--overwrite` flag controls re-running predict over an existing CSV in `video_preds/`; our move step uses its own check so we don't silently clobber the user's existing outputs).

---

## 4. Backend changes

### Route

`POST /dlc-3d/lp/predict` — accepts a new optional field:

```json
{
  "lp_project": "...",        // optional, as today
  "model_dir":  "...",        // optional, as today
  "videos":     ["...", ...],
  "skip_viz":   false,
  "overwrite":  false,
  "dest_dir":   ""             // NEW; empty = per-video parent folder
}
```

Validation:
- `dest_dir` if non-empty must resolve under `/user-data/`.

### Task

`dlc_3d_lp.predict(model_dir, videos, skip_viz, overwrite, dest_dir)` — extended with `dest_dir`. The relocation step is implemented in a new helper `predict_runner.relocate_predictions(model_dir, videos, dest_dir)` so it stays test-friendly.

---

## 5. Files touched

```
dlc-3D/src/templates/partials/card_lp_predict.html   ← markup swap
dlc-3D/src/static/lp_cards.js                        ← initPredictCard() rewrite of the videos section + dest section
dlc-3D/src/dlc_3d_bp/lp/predict_runner.py            ← + relocate_predictions(); reuse run_predict_subprocess as-is
dlc-3D/src/dlc_3d_bp/lp/tasks.py                     ← lp_predict gains dest_dir; calls relocate after subprocess
dlc-3D/src/dlc_3d_bp/lp_routes.py                    ← /lp/predict accepts/validates dest_dir; forwards to task
dlc-3D/tests/test_lp_routes.py                       ← + dest_dir-related route tests
dlc-3D/tests/test_lp_predict_runner.py               ← NEW: unit tests for relocate_predictions
```

No new packages. No compose changes (every file above is already on a live-mount).

---

## 6. Testing

| Test | Scope |
|---|---|
| `test_predict_endpoint_rejects_dest_dir_outside_user_data` | 403 when `dest_dir` is set to `/etc` |
| `test_predict_endpoint_accepts_empty_dest_dir` | 202; payload forwarded with `dest_dir=""` |
| `test_predict_endpoint_forwards_dest_dir` | 202; task `apply_async` receives `dest_dir` arg verbatim |
| `test_relocate_per_video_default` | Synthetic `<model_dir>/video_preds/` with CSVs + labeled mp4; assert files move to each video's parent |
| `test_relocate_to_explicit_dest_dir` | Synthetic; assert all outputs land in the chosen dir, dirs created |
| `test_relocate_skips_on_conflict_without_overwrite` | Pre-existing destination file → relocation skipped, warning returned |

No new browser/e2e tests. Live smoke is the user clicking through the Predict card after this lands.

---

## 7. Out of scope

- Multi-cam pairing (predict on a primary video and auto-include its sibling cam). Plausible follow-up, but distinct.
- Reusing the analyze card's snapshot/shuffle/batch_size/GPU fields. They don't apply to LP.
- Hooking the picker into an "active video" the user already chose elsewhere in the dlc-3D UI. Could be added later if asked.
