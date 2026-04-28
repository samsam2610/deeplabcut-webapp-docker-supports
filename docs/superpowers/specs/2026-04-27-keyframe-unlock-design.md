# Keyframe Unlock Design

## Goal

Allow the user to move a clip candidate's keyframe outside the original locked range (kf-200 to kf+599) by unlocking navigation in the bottom player panel.

## Background

When a clip candidate opens in the bottom player, `_clipStart = kf - 200` and `_clipEnd = kf + 599`. All frame navigation is clamped to this range. The seek bar and playback loop are also bounded by it. The lock badge shows `🔒 start–end`.

Some candidates have the correct event but the wrong keyframe position — the user needs to scrub outside the original window to find the true keyframe.

## Design

### Unlock Button

A small **🔓 Unlock** button placed next to the existing lock badge (`#ep-lock-badge`) in the player controls bar.

- Default state: button shows `🔓 Unlock`, badge shows `🔒 start–end`.
- On click → **unlocked state**:
  - `_clipStart = 0`, `_clipEnd = _frameCount - 1` (full video range).
  - Seek bar expands to full video. A **shaded overlay region** on the seek bar marks the original locked range as a visual reference (CSS background gradient or a positioned `<div>` overlay).
  - Lock badge changes to `🔓 unlocked`.
  - Button label changes to `🔒 Lock`.
- Clicking **🔒 Lock** re-engages the current keyframe's range (`kf - 200`, `kf + 599`) and returns to locked state.

### Setting a New Keyframe While Unlocked

When the user sets a new keyframe (existing KF set mechanism, keyboard shortcut or button) while in unlocked state:

- `_keyFrame` updates to the new frame.
- `_clipStart = max(0, newKf - 200)`, `_clipEnd = min(_frameCount - 1, newKf + 599)`.
- `detections[_detectionIdx].frame_number = newKf + 1` (1-based, existing path).
- Lock **automatically re-engages**: clamp restored, seek bar shrinks back, shaded overlay redraws for the new range.
- Button returns to `🔓 Unlock`.
- Lock badge updates to new `🔒 start–end`.

### Seek Bar Shaded Overlay

The seek bar (`#ep-seek-row`) gets a child `<div id="ep-lock-overlay">` absolutely positioned over it, showing the locked range as a semi-transparent highlight. Updated whenever `_clipStart` / `_clipEnd` change.

```css
#ep-lock-overlay {
  position: absolute;
  top: 0; bottom: 0;
  background: rgba(56, 139, 253, 0.15);
  pointer-events: none;
  border-radius: 2px;
}
```

Left/width computed as percentages of total frame count, same as the existing seek thumb position calculation.

### State Variable

Add `_unlocked = false` module-level. All clamp logic gates on `_unlocked`:

```js
n = _unlocked ? Math.max(0, Math.min(n, _frameCount - 1))
              : Math.max(_clipStart, Math.min(n, _clipEnd));
```

Loop boundary in the playback tick also gates on `_unlocked`.

Reset `_unlocked = false` when `openPlayer()` is called (new card opened).

## Files Changed

- `static/enhanced_player.js` — unlock button logic, state variable, clamp guard, overlay update.
- `templates/clip_cutter.html` — unlock button HTML in player controls, `#ep-lock-overlay` div, CSS.

## No Backend Changes

Keyframe updates already write through `detections[_detectionIdx].frame_number` and the existing save path. No new routes needed.

## Testing

- `test_ui.py`: add Playwright test verifying unlock button appears, clicking it enables navigation past clip boundary, setting keyframe re-engages lock.
