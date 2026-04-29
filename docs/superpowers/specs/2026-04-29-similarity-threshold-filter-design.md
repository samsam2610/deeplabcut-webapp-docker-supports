# Similarity Threshold Filter — Design Spec

**Date:** 2026-04-29
**Module:** clip-cutter
**Status:** Approved

---

## Overview

Add a small similarity-threshold slider + editable number field to the Detections panel header. Cards whose similarity score falls below the threshold are hidden. Tab/Shift+Tab navigation skips hidden cards. A reset button (`×`) restores the threshold to 0 (no filter).

---

## UI Layout

The `results-pane-header` row becomes:

```
[Detections] [N found] [≥ ——●—— 0.70 ×] [✓ sensor+CLIP] [CLIP only] [All]
```

**Elements added:**

- `<div id="sim-filter">` — wrapper, inserted between `#results-count` and `#source-filter`
- `<input type="range" id="sim-slider">` — min=0, max=1, step=0.01, value=0
- `<input type="number" id="sim-value">` — min=0, max=1, step=0.01, value=0, width≈42px
- `<button id="sim-reset">×</button>` — hidden when threshold=0, visible otherwise

**Styling:**

- Inline with existing header elements using `display:flex; align-items:center; gap:4px`
- Slider width: ~70px. Matches the compact aesthetic of the existing filter buttons.
- Reset button styled as a plain small icon button (no background, muted color, hover red)
- A label `≥` prefix (non-interactive text) makes the control self-explanatory

---

## Data Layer

In `buildResultCard(d, idx)`, add:

```js
card.dataset.similarity = d.similarity;
```

This stores the float on the DOM element so `applyFilter()` can read it without parsing `.sim-pill` text.

---

## Filter Logic

`applyFilter()` is extended to combine source filter AND similarity threshold:

```js
function applyFilter() {
  const threshold = parseFloat(document.getElementById("sim-slider")?.value || 0);
  document.querySelectorAll(".result-card").forEach(card => {
    const src = card.dataset.source || "";
    const sim = parseFloat(card.dataset.similarity || 0);
    const sourceOk =
      currentFilter === "all" ||
      (currentFilter === "sensor+clip" && src === "sensor+clip") ||
      (currentFilter === "clip_only" && src === "clip_only");
    card.style.display = (sourceOk && sim >= threshold) ? "" : "none";
  });
}
```

Both filters combine with AND. Threshold=0 means no similarity filtering (all pass).

---

## Two-Way Sync (slider ↔ field)

- `sim-slider` `input` event → update `sim-value.value`, call `applyFilter()`
- `sim-value` `input` event → clamp to [0,1], update `sim-slider.value`, call `applyFilter()`
- Both fire `applyFilter()` immediately (no debounce needed — DOM ops are fast)

---

## Reset Button

- Hidden (`display:none`) when threshold=0
- Shown whenever threshold>0
- On click: set both inputs to 0, call `applyFilter()`, hide self

The reset is purely cosmetic/UX — no card data is modified, so it's fully reversible by design.

---

## Tab Navigation

The existing keydown handler is updated to skip hidden cards:

```js
const cards = Array.from(document.querySelectorAll("#results-list .result-card"))
  .filter(c => c.style.display !== "none");
```

This ensures Tab/Shift+Tab cycles only through candidates that pass the current combined filter (source + similarity). Behaviour is otherwise unchanged.

---

## Files Changed

| File | Change |
|---|---|
| `clip-cutter/templates/clip_cutter.html` | Add `#sim-filter` HTML + CSS in `results-pane-header` |
| `clip-cutter/static/clip_cutter.js` | `buildResultCard`: add `dataset.similarity`; `applyFilter`: add threshold check; Tab handler: filter by visibility; wire up slider/field/reset events |

---

## Non-Goals

- No persistence of threshold across page reloads (ephemeral UI state)
- No per-video threshold memory
- No changes to the backend or detection data format
