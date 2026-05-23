# Inline 3D Viewer — clip-cutter Control Parity — Design

**Date:** 2026-05-23
**Status:** Approved (pending implementation plan)
**Repo:** `deeplabcut-webapp-docker-supports/dlc-3D` (+ one parent-repo template-mount check), branch `feat/viewer-3d-onto-library`

## Context

The inline 3D analysis card (`src/static/inline_analysis_3d.js`, `card_inline_analysis_3d.html`) was migrated onto the shared VideoViewer library (Phase 4c). The migration targeted parity with the *old* inline card, which never had clip-cutter's full viewer control set. The user wants the inline card to have clip-cutter's complete video-viewer capability.

Gap analysis (verified against `clip-cutter/templates/clip_cutter.html` + the library):
- **Keyboard:** the library `controls.mjs` `resolveKey` only maps `Space`, `←/→`, `Ctrl+←/→`; it is not shift-aware and has no play-backward. The viewer mount isn't auto-focused, so even existing keys feel dead.
- **Multi-level skip:** inline has step ±1 + one configurable skip-N; clip-cutter also has a second level (±step-size) with quick presets.
- **Note/status viewer:** `statusNoteTimeline` is composed, but its bars live inside the collapsed-by-default Dataset Curation panel, so they're never seen.
- **Play fwd/back:** play-backward button + frame-jump were added in the prior turn; keyboard bindings are still missing.
- **Clip creation:** the library has a tested `clipExtractor` (Phase 3c) but the inline card never composed it, and the dlc-3d backend has **no** clip-creation (ffmpeg trim) route — only a clip-*folder* data model (`<stem>/clip_NNN/`).

**Scope (user decision):** the inline card only. Shared keyboard-map changes naturally benefit all cards (acceptable/additive); the timeline-surfacing and clip-extract wiring land only in the inline card.

**Guiding principle:** compose the existing library + extend it minimally — do NOT fork clip-cutter's player (forbidden by `docs/policies/video-viewer-component.md`).

## Components

### 1. Keyboard parity (library: `internal/controls.mjs` + `video_viewer.js`)
Make `resolveKey` shift-aware and add a play-backward intent, matching clip-cutter:

| Key | Intent |
|-----|--------|
| `Space` | play/pause forward |
| `Shift+Space` | play/pause **backward** |
| `←` / `→` | step ∓1 |
| `Shift+←` / `Shift+→` | step ∓ skip-N (also keep `Ctrl+←/→` as an alias) |

- `resolveKey({key, ctrlKey, shiftKey})` returns a new intent `{type:"playPauseDir", dir:-1}` for `Shift+Space`; `{type:"stepSkip", dir}` for `Shift+arrow`.
- `VideoViewer._handleKeyDown` handles `playPauseDir{dir}` as "play `dir` / pause": **if already playing → pause; else `setPlayDir(dir)` then `play()`**. (`Space` keeps its current toggle: if playing → pause; else set dir +1 then play.) This matches clip-cutter's "Space = play forward/pause, Shift+Space = play backward/pause."
- Auto-focus: `VideoViewer` focuses its `mount` after `load()` (mount already has `tabindex=0`); the keydown handler already ignores events whose target is an INPUT/TEXTAREA, so typing in fields is unaffected.
- Backward-compatible: existing consumers keep working (Space/arrows unchanged; new bindings are additive).

### 2. Play fwd/back + multi-level skip (inline card)
- Play fwd/back buttons already exist; bind `Space` / `Shift+Space` to them (handled by the base keymap above).
- Add small **skip-size preset buttons** (`1 / 5 / 10 / 30`) beside the existing `#ia3d-skip-n` input; clicking one sets skip-N (updates the input + `viewer.setSkipN`) and marks the active preset. `Shift+←/→` and the skip-back/fwd buttons use skip-N. This delivers clip-cutter's two-level skip (±1 and ±N).

### 3. Status/note timeline — surfaced (inline card)
- Relocate the status/note timeline block (`#ia3d-csv-bars` → `#ia3d-status-bar-wrap` / `#ia3d-note-bar-wrap`, with canvases, chips, prev/next nav) OUT of `#ia3d-curation-controls` into an always-present container in the viewer area, directly below the controls row.
- `statusNoteTimeline` already manages section visibility by content and is already wired to those element ids in `_ensureViewer` — only the markup moves; the JS `els` references resolve to the same ids regardless of DOM location. The metadata strip stays as-is.
- The Dataset Curation panel keeps its extract/add/batch tools; it no longer owns the timeline.

### 4. Clip creation (inline card + new backend route)
- **Frontend:** compose `clipExtractor(config)` into the inline viewer. Render its enable-checkbox **unchecked by default**; panel hidden until enabled. Inject `endpoints.extractClip / rename / del`; omit `endpoints.overlap` (no keyframes in the inline context → the overlap dialog is skipped). Extract the primary (cam0) and, when a sibling is mounted, the sibling (cam1) over the same `[start, start+length)` range. New card markup: an `#ia3d-clip-*` panel mirroring the library feature's element contract (enable checkbox, start/length/end inputs, postfix/tag input, extract/rename/delete buttons, produced-clip display).
- **Backend (`dlc-3D/src/dlc_3d_bp/routes.py`):** add `POST /dlc-3d/extract-clip` (+ `/extract-clip/rename`, `/extract-clip/delete`) porting clip-cutter's `routes.py` `/extract` ffmpeg trim. Given `{video_path, start_frame, n_frames, [sibling_video], postfix}`, ffmpeg-trim each cam's frame range into `<video_stem>/clip_NNN<postfix>.avi` under the dlc-3d clip-folder convention; return `{avi_path}`. Reuse the existing fps/frame→time resolution already in routes.py. Rename/delete operate on the produced clip path.

### 5. Per-view size slider → left (inline card)
- Change `#ia3d-viewer-mount .vv-tile-size-row` from `justify-content: flex-end` to `flex-start` so the slider aligns left, uniform with the other (seek/zoom) sliders.

### 6. Shortcuts help (inline card)
- A small `?` button near the controls toggles a tooltip/popover listing the keyboard shortcuts (mirrors clip-cutter's `#ep-help-tooltip`). Static markup + a click toggle; no library change.

## Data flow
Pose/CSV/frame data flow is unchanged. New flows:
- Keyboard → `VideoViewer._handleKeyDown` → existing seek/play methods (+ new direction handling).
- Clip extract → `clipExtractor` → injected `extractClip` endpoint → `POST /dlc-3d/extract-clip` → ffmpeg → clip folder → `{avi_path}` back to the feature for display.

## Error handling
- Keyboard: no-ops when no video is loaded; ignores INPUT/TEXTAREA targets.
- Clip extract: backend validates `video_path` exists and the range is within bounds; ffmpeg failures return `{error}` surfaced by the feature's status line. Frontend disables Extract when no video is loaded.
- Sibling-cam clip: if no sibling is mounted, extract cam0 only (don't fail).
- Never write into the protected `/user-data` fixture dirs during testing — verify clip extract against a scratch path only.

## Testing
- **node** (`tests/unit/test_viewer_controls.mjs`): extend for shift-aware `resolveKey` (Shift+Space → playPauseDir/-1; Shift+arrow → stepSkip).
- **backend** (`tests/`): test `/dlc-3d/extract-clip` request validation + output-path construction (the clip-folder naming); ffmpeg invocation mocked or asserted at the command-build level.
- **frontend contract** (`tests/test_inline_analysis_3d_ui_isolation.py`): clipExtractor composed; clip-extract enable-checkbox present + unchecked; timeline markup present OUTSIDE the curation-controls div; help affordance present; size-row left-aligned.
- **live verify** (Playwright, OM-2 fixture): keyboard (Space/Shift+Space/arrows/Shift+arrows), skip presets, play fwd/back, status/note timeline visible without opening curation, clip-extract panel reveals on enable. Clip extraction exercised only against a scratch video path (no `/user-data` writes), or the backend route unit-tested instead.

## Out of scope
- Other cards (View Analyzed, 3D-Extract) — they inherit only the shared keyboard changes.
- Keyframe/detection overlap for clips (no keyframes in the inline analysis context).
- clip-cutter's candidate-review shortcuts (`Tab`/`X`/`Shift+S`/`Shift+E`) — those are clip-cutter's detection workflow, not applicable here.
