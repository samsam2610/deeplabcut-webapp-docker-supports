# Inline 3D — Editable Keyframe + Persisted Window (finalize + create-clip) — Design

**Date:** 2026-05-24
**Status:** Approved (pre-approved through implementation)
**Repos:** `deeplabcut-webapp-docker-supports/dlc-3D` (frontend) + `deeplabcut-webapp-docker` (main webapp backend).

## Context

The inline-3D Finalize panel now uses a keyframe window (keyframe = current frame unless locked; before/after/length with `length = before + after + 1`; lock checkbox + `l`). Three changes, applied to BOTH the Finalize panel and the create-clip panel:

1. **Editable keyframe** — the keyframe is a typeable `<input>`, not a read-only display. **Typing auto-locks** it.
2. **Default length 800, persisted per project** — defaults `before=200`, `after=599` (length 800); `before`/`after` are remembered per project in a sqlite db.
3. **Create-clip gets the same model** — replace its `start`/`length`/`end` inputs with the keyframe window.

Since both panels now share the model, build it once as a reusable controller. `clipExtractor` is used only by inline-3D, so changing the clip panel is contained.

**User decisions:** typing the keyframe auto-locks it; persist `before`+`after` (length derived) per project, independently per panel; create-clip uses the full keyframe model.

## Components

### A. Backend persistence (main webapp `deeplabcut-webapp-docker`)
- **`src/dlc/project_settings.py`** (new, pure, mirrors `marks_store.py`): per-project `<project>/ui_settings.sqlite` with a `meta(key TEXT PRIMARY KEY, value TEXT)` table. `get_setting(project_path, key, default=None) -> str|None` and `set_setting(project_path, key, value)`. Imports no Flask/DLC/Redis; unit-testable against `tmp_path`.
- **Endpoints in `src/dlc/inline_analysis.py`** (it already has `_active_project()`):
  - `GET /dlc/project/ui-setting?key=<k>` → `{"value": <str|null>}` (404/400 if no active project).
  - `POST /dlc/project/ui-setting` body `{key, value}` → `{"ok": true}`.
  - Values are opaque strings (the frontend stores JSON). Keys are validated to a small allow-list prefix (`finalize_window`, `clip_window`) to avoid arbitrary writes.

### B. Shared controller (dlc-3D `src/static/keyframe_window_ui.js`, new)
`makeKeyframeWindow({ viewer, panelEl, els, settingKey })` → controller. `els = { keyframe, lock, before, after, length, range }` (keyframe + before/after/length are `<input>`s; lock is a checkbox; range is a span). Uses the pure `components/viewer/internal/keyframe_window.mjs` (`syncWindow`, `finalizeRange`). Behavior:
- **State:** `_keyframe` (int), `_locked` (bool, default false).
- **frameChange:** `viewer.on("frameChange", n => { if (!_locked) { _keyframe = n; refresh(); } })`.
- **keyframe input** → set `_locked = true` (auto-lock; sync checkbox), `_keyframe = parsed`, `refresh()`.
- **before/after/length input** → `syncWindow(edited, vals)`, write back, `refresh()`, debounced `save()`.
- **lock checkbox `change` + `l` keydown** (document-scoped, gated: `panelEl` visible + not in INPUT/TEXTAREA/SELECT) → toggle `_locked`; on unlock set `_keyframe = viewer.currentFrame()`; `refresh()`.
- **refresh():** write `_keyframe` into `els.keyframe` (skip if it's focused, so typing isn't clobbered); update `els.range` via `finalizeRange(_keyframe, before, after, frameCount)`; fire the `onChange` hook (used by clip to mirror into hidden inputs).
- **load():** `GET ui-setting?key=settingKey` → JSON `{before, after}` (default `{200, 599}`); set inputs; `length = before+after+1`; `refresh()`. Called on panel-open.
- **save():** debounced `POST ui-setting {key: settingKey, value: JSON.stringify({before, after})}`.
- **getRange():** `finalizeRange(_keyframe, before, after, frameCount)`.
- Number inputs `stopPropagation` on keydown (don't bubble to viewer keynav).
- Each controller registers its own `l` handler gated on `panelEl` visibility; if both panels are open, `l` toggles whichever is visible (both, in the rare both-open case — acceptable).

### C. Finalize panel (dlc-3D)
- Markup: `#ia3d-finalize-keyframe` `<span>` → `<input type=number>`; default `before=200`, `after=599`, `length=800` (200+599+1). `load()` overrides before/after from the saved per-project setting.
- Glue: replace the bespoke `_finalizeWindowVals`/`_refreshFinalizeWindow`/`_onFinalizeWindowInput`/`_setFinalizeLock`/frameChange/`l` code with one `makeKeyframeWindow({…, settingKey: "finalize_window", panelEl: #ia3d-finalize-controls})` instance (`_finalizeKW`). `_onFinalizeAddClick` uses `_finalizeKW.getRange()` for `start_frame`/`n_frames`. On finalize-toggle-on, call `_finalizeKW.load()`.

### D. Create-clip panel (dlc-3D)
- Markup: replace the visible `start`/`length`/`end` inputs with keyframe-window markup (`#ia3d-clip-keyframe` input, `#ia3d-clip-lock`, `#ia3d-clip-before`, `#ia3d-clip-after`, `#ia3d-clip-length`, `#ia3d-clip-range`). Keep `#ia3d-clip-start` and `#ia3d-clip-frames` as **hidden** inputs (so the existing `clipExtractor` config that reads them is unchanged). Drop the readonly `#ia3d-clip-end` display.
- Glue: `makeKeyframeWindow({…, settingKey: "clip_window", panelEl: #ia3d-clip-panel, onChange: (range) => { #ia3d-clip-start.value = range.start; #ia3d-clip-frames.value = range.n; } })` (`_clipKW`). The existing `_viewer.use(clipExtractor({…}))` stays as-is (reads the hidden start/frames). Load `_clipKW` when the clip panel is enabled.

## Data flow / error handling
- Persistence: load on panel-open (default 200/599 if absent or fetch fails — fail open); save debounced (~400ms) on before/after change; a failed save is non-fatal (logged, state still local). The active project comes from `inline_analysis._active_project()`; if none, the endpoints 400 and the frontend keeps defaults.
- Editable keyframe clamps via `finalizeRange` at use time; a typed value out of `[0, frameCount-1]` still derives a clamped range (range readout reflects it).
- Two controllers share one viewer; both track current frame when unlocked (independent).
- Clip extraction continues through `clipExtractor` reading the hidden start/frames the controller writes; overlap-check keyframe (start+preWindow) is approximate when `before≠200` (non-critical warning) — unchanged behavior.

## Testing
- **backend** (`tests/test_project_settings.py`, main repo): `get_setting`/`set_setting` round-trip + default on tmp_path; endpoint get/set with active-project resolution + key allow-list (mock/flask test client as the repo does elsewhere).
- **pure** (existing `test_viewer_keyframe_window.mjs`): unchanged (still covers syncWindow/finalizeRange).
- **inline contract** (`test_inline_analysis_3d_ui_isolation.py`): finalize + clip keyframe are `<input>`; `makeKeyframeWindow` imported and instantiated for both panels with the two settingKeys; ui-setting load/save referenced; hidden `#ia3d-clip-start`/`#ia3d-clip-frames` present; old visible clip start/length/end visible inputs replaced.
- **controller contract** (`tests/test_keyframe_window_ui.py`, static): exports `makeKeyframeWindow`; references syncWindow/finalizeRange, frameChange, the `l` shortcut, auto-lock on keyframe input, load/save.
- **live verify** (MAPS fixture, read-only): editable keyframe auto-locks on type; before/after persist across card reopen (round-trip via sqlite); create-clip shows the keyframe window + computes start/length into the hidden inputs; defaults length 800. No real Extract/Add.

## Out of scope (YAGNI)
- View Analyzed / clip-cutter legacy player.
- Persisting the keyframe value itself (per-session only).
- A general settings UI; only before/after for these two panels are persisted.
