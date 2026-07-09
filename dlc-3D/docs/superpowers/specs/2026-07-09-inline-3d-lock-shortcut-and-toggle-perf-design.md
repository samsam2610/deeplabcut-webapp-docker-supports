# Inline-3D — keyframe-lock shortcut fix + toggle-perf hardening

**Date:** 2026-07-09
**Branch:** `debug` (repo: `deeplabcut-webapp-docker-supports`)
**Module:** `dlc-3D`

## Problem

Two bugs in the inline-3D analysis card's finalize keyframe-lock:

1. **The `l`/`L` shortcut doesn't lock the timeline.** Pressing the shortcut ticks the
   lock checkbox but playback is not confined to the finalize range.
2. **Toggling the lock repeatedly makes playback extremely slow** (reproduced on a
   single open video, no Back/reopen).

## Root cause

Lock state is owned in **three** places, kept in sync only by the checkbox's DOM
`change` event:

| Owner | Location |
|-------|----------|
| Keyframe window's internal `locked` | `src/static/keyframe_window_ui.js` |
| `#ia3d-finalize-lock.checked` | template checkbox |
| `_lockActive` (actually confines the timeline) | `src/static/inline_analysis_3d.js`, set by the `change`→`_applyLockState` listener |

- **Bug 1:** the shortcut calls `setLock()`, which sets `els.lock.checked`
  *programmatically*. A programmatic `.checked` assignment does **not** fire a
  `change` event, so `_applyLockState` never runs and `_lockActive` stays `false` —
  the checkbox looks ticked but the timeline is not confined. A real mouse click
  works because it fires `change`.
- **Bug 2:** the split ownership plus per-viewer listener registration in
  `makeKeyframeWindow` (a `document` keydown listener and a checkbox `change`
  listener that are never removed) means state changes do redundant work and
  listeners can accumulate across viewer lifecycles. Exact single-viewer accumulator
  is not pinned by static reading; we harden rather than chase it (per decision).

## Design

Collapse the three owners onto **one propagation path**: the keyframe window is the
single place that flips lock state, and it notifies the consumer via a callback.

### `src/static/keyframe_window_ui.js`

1. Accept a new option `onLockChange`.
2. Make `setLock` idempotent and emitting:

   ```js
   function setLock(on) {
     const next = !!on, changed = next !== locked;
     locked = next;
     if (els.lock) els.lock.checked = locked;
     if (!locked && viewer) keyframe = viewer.currentFrame();
     refresh();
     if (changed && onLockChange) onLockChange(locked);
   }
   ```

   `setLock` writing `els.lock.checked` does not re-dispatch `change`, so there is no
   feedback loop. The `changed` guard suppresses redundant work on repeated toggles
   to the same value.

3. Extract the `document` `keydown` handler and the checkbox `change` handler into
   named references, and return a `destroy()` that `removeEventListener`s both. This
   prevents listener accumulation across viewer teardown/rebuild.

### `src/static/inline_analysis_3d.js`

1. On the finalize `makeKeyframeWindow`, pass `onLockChange: () => _applyLockState()`.
   Now **all** trigger sources — mouse click, keyframe-field typing (auto-lock), and
   the `l` shortcut — converge on `_applyLockState` through the single KW path.
2. **Remove** the fragile direct listener
   `$("ia3d-finalize-lock")?.addEventListener("change", _applyLockState)` (was the
   only thing wiring the timeline confine, and it missed the shortcut). Lock changes
   now route exclusively through the KW.
3. In `_iaBack()`, call `_finalizeKW?.destroy()` and `_clipKW?.destroy()` and null the
   references before the viewer is torn down, so the KW's document/checkbox listeners
   never accumulate across open→Back→reopen cycles.

## Testing

Existing JS is verified by source-pattern pytest (`tests/test_keyframe_window_ui.py`)
plus Playwright e2e (auto-skips without the OM-2 fixture).

- **`tests/test_keyframe_window_ui.py`** — add asserts that `keyframe_window_ui.js`:
  - accepts `onLockChange` and invokes it inside `setLock`,
  - guards `setLock` on a `changed` comparison,
  - returns `destroy` and calls `removeEventListener`.
- **Inline-module source assert** (new or existing inline test) — the direct
  `finalize-lock`→`_applyLockState` `change` listener is gone, `onLockChange` is
  wired to `_applyLockState`, and `_iaBack` calls `destroy()`.
- Run `pytest` for the module.
- Manual check: `l` shortcut confines the timeline (red range overlay + flag appear);
  rapid toggling keeps playback smooth.

## Non-goals

- No change to the keyframe math (`keyframe_window.mjs`) or the range-confine draw
  logic (`_drawLockOverlays`).
- No change to the clip-panel behavior beyond the shared `destroy()` teardown.
