# Detection List UX — Three Fixes Design

**Date:** 2026-04-28
**Module:** clip-cutter
**Status:** Approved

---

## Problem

Three independent UX issues in the detection/candidate results list:

1. **Viewer height not reflected in detection list** — dragging the video viewer taller hides more detection cards behind it with no way to scroll them into view.
2. **Selection indicator lost after extraction** — when a card is kept/rejected it fades to `opacity:0.4`, making the `active-preview` blue border near-invisible. The user loses their position in the list.
3. **Frame name clobbered on navigation during extraction** — if the user navigates to a new detection while the extract fetch is in-flight, the completion handler uses the current (wrong) `_detectionIdx`, corrupting the new card's name and disabling its buttons.

---

## Designs

### Fix 1 — Sync `#results-list` padding-bottom to player panel height

`#player-panel` is `position:fixed; bottom:0` and overlaps the results list. Increasing viewer height hides more cards with no scroll remedy.

**Approach:** Whenever the player panel height changes, set `document.getElementById("results-list").style.paddingBottom` to the panel's current height in px. The list already has `overflow-y:auto`, so this gives it scroll room to bring any card above the panel.

Trigger points:
- Panel first shown (`openPlayer`) → set padding = `panel.offsetHeight`
- Drag resize (`onMove`) → set padding = new height
- Minimize → set padding = `0`
- Restore → set padding = `savedHeight`
- Panel hidden (close) → set padding = `0`

No layout restructure needed.

---

### Fix 2 — 20px blue accent bar as persistent position indicator

Each `.result-card` gets a 20px flex-sibling accent bar as its first child:

```html
<div class="result-accent-bar"></div>
<!-- existing card content -->
```

CSS:
```css
.result-accent-bar {
  width: 20px;
  flex-shrink: 0;
  align-self: stretch;
  border-radius: 3px 0 0 3px;
  background: transparent;
  margin: -5px 4px -5px -7px; /* flush to card left edge */
}
.result-card.active-preview .result-accent-bar {
  background: #388bfd;
}
```

Because the bar is a direct child element (not a CSS border), its color is not affected by the parent card's `opacity:0.4`. It stays fully visible even when the card is grayed out.

Non-selected cards get a transparent bar as a spacer so the remaining content stays aligned.

`active-preview` is added on card click and on `epSwitchDetection` / `openPlayer` calls. It is **not** removed when the card is kept or rejected — only when the user selects a different card.

---

### Fix 3 — Capture detection index before async extract

**Root cause:** The `ep-extract` click handler reads `_detectionIdx` and `_videoPath` *after* `await fetch(...)`. If the user navigates to a new detection during the fetch, `_detectionIdx` now points to the new card, not the one being extracted.

**Fix:** Capture both values before the await:

```js
const capturedIdx = _detectionIdx;
const capturedVideoPath = _videoPath;
```

After the fetch completes:
- Use `capturedIdx` for all `detections[]` mutations and card DOM updates.
- Only update the player UI (hide extract button, disable set-kf/reject) if `_detectionIdx === capturedIdx` (i.e., the user hasn't navigated away).

The same capture pattern applies to the `ep-rename-extract` handler, which also reads `_detectionIdx` after an await.

---

## Files Changed

| File | Change |
|---|---|
| `static/clip_cutter.js` | `buildResultCard`: add `.result-accent-bar` div; CSS for `.result-accent-bar` and `.result-card.active-preview .result-accent-bar` |
| `static/enhanced_player.js` | Drag-resize handler: sync `#results-list` paddingBottom; openPlayer/minimize/close: sync padding; ep-extract handler: capture idx/videoPath before await |
| `templates/clip_cutter.html` | Add `.result-accent-bar` CSS |
| `tests/test_ui.py` | Tests for: padding sync on resize; accent bar visible when card kept+active; captured-idx extraction race condition |

---

## Out of Scope

- Scrolling the selected card into view automatically (not requested)
- Changing the `opacity:0.4` value for kept/rejected cards
- Any changes to the player panel layout beyond padding-bottom sync
