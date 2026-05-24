# Inline 3D — Keyframe-Window Finalize Range (keyframe / before / after / length + lock) — Design

**Date:** 2026-05-24
**Status:** Approved (pre-approved through implementation)
**Repo:** `deeplabcut-webapp-docker-supports/dlc-3D`. Frontend-only (no backend changes).

## Context

The inline-3D "Finalize analysis" panel currently selects the range to copy into the `_analyzed` files with two inputs: **Start frame** (`#ia3d-finalize-start`) + **Frames** count (`#ia3d-finalize-count`) → range `[start, start+count−1]`. `_onFinalizeAddClick` saves marker edits to both cameras' layers, then calls `finalize-range {video_path, source_h5, start_frame, n_frames}` for cam0 (and cam1 if present).

Port clip-cutter's keyframe concept: a **keyframe** anchors the range; **before** (N) frames before it and **after** (M) frames after it define an exact **length**; a **lock** (checkbox + `l` shortcut) freezes the keyframe while you navigate. Keyframe = the current frame.

**User decisions:**
- All three of before/after/length are editable (last-edited wins; invariant `length = before + after + 1`).
- Replace the Start-frame + Frames inputs with the keyframe model (derive `start_frame`/`n_frames` under the hood for the unchanged backend call).

## Components

### UI (`card_inline_analysis_3d.html`)
Replace the Start/Frames row inside `#ia3d-finalize-controls` with:
- `#ia3d-finalize-keyframe` — read-only keyframe display (the current frame when unlocked).
- `#ia3d-finalize-lock` — checkbox, label "Lock (l)".
- `#ia3d-finalize-before`, `#ia3d-finalize-after`, `#ia3d-finalize-length` — `type=number`, min 0 (length min 1).
- `#ia3d-finalize-range` — live "frames start–end (n)" readout.
- The existing **Add range to _analyzed** button (`#ia3d-finalize-add-btn`) and the finalized-coverage bar/nav stay.
The old `#ia3d-finalize-start` / `#ia3d-finalize-count` inputs are removed.

### Pure logic (`components/viewer/internal/keyframe_window.mjs`, new, node-tested)
- `syncWindow(edited, { before, after, length })` → normalized `{ before, after, length }` with invariant `length === before + after + 1`:
  - `edited === "before"` or `"after"`: `length = before + after + 1`.
  - `edited === "length"`: `before` pinned; `after = max(0, length − before − 1)`; then `length = before + after + 1` (re-sync if `after` was clamped).
  - All values coerced to non-negative integers (`before, after ≥ 0`, `length ≥ 1`).
- `finalizeRange(keyframe, before, after, frameCount)` → `{ start, end, n }`:
  - `start = clamp(keyframe − before, 0, frameCount−1)`, `end = clamp(keyframe + after, 0, frameCount−1)`, `n = end − start + 1`. (Window clamps to the valid frame range; `n` reflects the clamped span.)

### Glue (`inline_analysis_3d.js`)
- Module state: `_finalizeKeyframe` (number), `_finalizeLocked` (bool, default false).
- **Keyframe tracking:** on the viewer `frameChange` event, when `!_finalizeLocked`, set `_finalizeKeyframe = currentFrame`; refresh the keyframe display + range readout. (Subscribe via `_viewer.on("frameChange", …)`.)
- **Field sync:** `before`/`after`/`length` `input` handlers read the three values, call `syncWindow(editedFieldName, …)`, write the normalized values back to the inputs, and refresh the range readout.
- **Lock:** the `#ia3d-finalize-lock` `change` handler and an `l` keydown (document-scoped, gated: finalize toggle on + viewer visible + target not INPUT/TEXTAREA) both toggle `_finalizeLocked`; on lock, freeze `_finalizeKeyframe` at the current frame; on unlock, set it to the current frame. Keep checkbox and state in sync; refresh displays.
- **Finalize:** `_onFinalizeAddClick` computes `{start, n}` via `finalizeRange(_finalizeKeyframe, before, after, _viewer.frameCount())` and calls the existing `_ia3dFinalizeOne(video, h5, start, n)` for both cams (unchanged confirm/save flow; the overwrite-confirm message uses `start`–`start+n−1`).
- **Defaults / reset:** on finalize-toggle-on (and in `_ia3dPopulateFinalizeFields`'s replacement), set `_finalizeKeyframe = currentFrame`, `_finalizeLocked = false` (checkbox unchecked), `before = after = 200` (length 401); refresh displays. Remove the now-moot `_ia3dLastRunStart/N` finalize autopopulate. `_resetForOpen` resets `_finalizeLocked = false`.

## Data flow / error handling
- Unlocked: every seek updates the keyframe + range. Locked: keyframe fixed; seeking only moves the playhead. The finalized range always derives from `_finalizeKeyframe` (not the live current frame) at click time, so locking lets the user verify the window edges before committing.
- `finalizeRange` clamps to `[0, frameCount−1]`; if the keyframe is near an edge the window is truncated (n shrinks) — acceptable and explicit in the readout.
- `l` is unused by the base viewer (space/arrows) and markerEditor (Tab/Delete/WASD-nudge/arrows); the focus guard prevents typing conflicts.

## Testing
- **node** (`tests/unit/test_viewer_keyframe_window.mjs`): `syncWindow` for each edited field (before/after → length; length → after pinned-before; clamping when length < before+1); `finalizeRange` normal + near-0 + near-end clamping + n correctness.
- **inline contract** (`tests/test_inline_analysis_3d_ui_isolation.py`): new ids present (`ia3d-finalize-keyframe`, `-lock`, `-before`, `-after`, `-length`, `-range`); old `ia3d-finalize-start` / `ia3d-finalize-count` absent; `inline_analysis_3d.js` imports + uses `syncWindow` and `finalizeRange`; an `l`/`"l"` keydown lock toggle is wired; `frameChange` updates the keyframe.
- **live verify** (MAPS fixture, read-only): keyframe follows current frame; toggling lock (checkbox and `l`) freezes it while scrubbing; editing before/after updates length and the range readout, editing length adjusts after; the readout shows `[kf−before, kf+after]`; Add finalizes that range (verify against the coverage bar — without writing to protected data, confirm the computed start/n in the confirm dialog / status).

## Out of scope (YAGNI)
- Applying the keyframe model to the working-layer clip extractor.
- A draggable keyframe overlay/marker on the timeline.
- Directly typing the keyframe number (lock + navigation covers it).
