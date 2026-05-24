# Inline 3D — Zoom-Aware Coverage Resolution + 3-Row Controls + 100 Preset — Design

**Date:** 2026-05-24
**Status:** Approved (pre-approved through implementation)
**Repo:** `deeplabcut-webapp-docker-supports/dlc-3D`. Frontend-only (no backend changes).

## Context

Three independent inline-3D refinements (one spec, three tasks):

1. **Coverage marks bleed onto unlabeled frames when zoomed.** Coverage is fetched once at the base canvas width (`nB` buckets). `coverageFrameRects` draws each covered bucket as a mark `ceil(canvasWidth / nB)` px wide so dense runs stay continuous. When the viewer zooms, `canvasWidth` grows but `nB` does not, so each mark widens (measured 1px @100% → 3px @200% → 5px @300%). A single labeled frame's mark then spans several frames' worth of pixels, so unlabeled neighbors appear marked. Reproduced on the MAPS fixture (read-only).
2. **Crowded single controls row.** The player controls live in one wrapping `.fe-controls` row, which wraps unpredictably. The user wants three deliberate rows.
3. **No 100-frame skip preset.** Presets are 1/5/10/30.

**User decisions:**
- Item 1: re-fetch coverage at the zoomed width (marks stay 1px-precise and continuous; buckets get finer with zoom; frame-exact once the bar is wider than the video).
- Item 2: Row 1 = playback; Row 2 = frame-jumping only; Row 3 = frame counter + time, with the `?` help button pushed to the far right of row 3.
- Item 3: add a `100` preset on the jump row.

## Components

### Item 1 — re-fetch coverage at the zoomed width (`inline_analysis_3d.js`)

- **Cache key includes width.** `_coverageCache` is currently keyed `${_overlayPrimaryH5}:${thr.toFixed(2)}`. Change to `${_overlayPrimaryH5}:${thr.toFixed(2)}:${w}` (where `w` is the bucket count = rounded canvas width used in the fetch). Update the set, the get, and the "is this still the current request" guard so all use the width-keyed form. Each zoom level then caches its own resolution and returns the matching `nB`.
- **Re-fetch on zoom.** In the `#ia3d-zoom` input handler, after `_applyTimelineWidth(g)` (which resizes the canvases), call a debounced refresh of both bars: `_refreshCoverage()` (working layer, likelihood) and `_refreshFinalizeCoverage()` (finalize, presence). Both already read their canvas's current `getBoundingClientRect().width` and fetch `buckets=${w}`, so after the resize they fetch at the zoomed width. Use a single debounced helper (`~200ms`) to coalesce slider drags.
- **Reset path unaffected.** `_applyTimelineWidth(null)` in `_resetForOpen` does NOT trigger a re-fetch (the normal open flow fetches coverage already).
- **Result:** `nB` tracks the displayed width → `markW = ceil(width/nB) = 1` (or 2px once `nB` caps at the frame count, where each bucket is one frame → no unlabeled frame can share a covered bucket). The `_refreshFinalizeCoverage` function has no cache today (it always refetches, mtime-keyed on the backend), so it needs no key change — only the new zoom trigger.

### Item 2 — 3-row controls layout (`card_inline_analysis_3d.html` + `inline_analysis_3d.css`)

Split the single `.fe-controls` content into three explicit row containers `<div class="ia3d-ctrl-row">`:
- **Row 1 (playback):** `#ia3d-btn-play-back`, `#ia3d-btn-play`, `#ia3d-btn-prev`, `#ia3d-btn-next`, the `fps` label+input, the `step` label+input.
- **Row 2 (frame jumping):** the existing `.ia3d-skip-group` span (skip-back, skip-fwd, `#ia3d-skip-n`, `.ia3d-skip-presets`).
- **Row 3 (status):** `#ia3d-frame-counter`, `#ia3d-frame-jump` (hidden input), `#ia3d-time-display`, and `#ia3d-help-btn` with `margin-left:auto` to push it right. The `#ia3d-help-tooltip` div stays in row 3 (it is `position:absolute`).

CSS, scoped to the card so other `.fe-controls` consumers are unaffected:
```css
#inline-analysis-3d-card .fe-controls { flex-direction: column; align-items: stretch; gap: .35rem; }
#inline-analysis-3d-card .ia3d-ctrl-row { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; }
```
The existing inline `style="flex:none;min-height:2.4rem;align-items:center"` on `.fe-controls` is replaced by `style="flex:none"` (the `min-height` and `align-items:center` no longer apply to a 3-row column; the CSS rule governs layout). No JS change — every control is looked up by id/class, so wrapping in row divs keeps all handlers wired (including `querySelectorAll("#inline-analysis-3d-card .ia3d-skip-preset")`).

### Item 3 — `100` skip preset (`card_inline_analysis_3d.html`)

Add `<button type="button" class="ia3d-skip-preset" data-n="100">100</button>` immediately after the `data-n="30"` button inside `.ia3d-skip-presets` (row 2). It auto-wires via the existing preset click handler and `_syncSkipPresets` (both use `.ia3d-skip-preset` + `data-n`). `#ia3d-skip-n` has `max="9999"`, so 100 is valid.

## Data flow / error handling

- Item 1: on zoom, the canvases resize and redraw immediately with the existing (coarse) buckets, then the debounced re-fetch updates to fine resolution and redraws again (brief coarse → fine; no flicker of position since marks are frame-space). If overlay/finalize is off, the refresh functions early-return (no fetch). Width-keyed cache prevents refetching a previously-seen zoom level.
- Items 2 & 3: pure markup/CSS; no new data flow.

## Testing

- **Static contract** (`tests/test_inline_analysis_3d_ui_isolation.py`):
  - Item 1: the coverage cache key in `inline_analysis_3d.js` includes a width component (e.g. assert the key template contains `:${w}` or the refactored key builder), and the `#ia3d-zoom` handler triggers a coverage refresh (assert the zoom handler region references `_refreshCoverage`/the debounced zoom-refresh helper).
  - Item 2: the card contains three `class="ia3d-ctrl-row"` containers; `#ia3d-frame-counter` and `#ia3d-time-display` are in the last row; the CSS file has the `#inline-analysis-3d-card .fe-controls { ... flex-direction: column ... }` and `.ia3d-ctrl-row` rules.
  - Item 3: a `data-n="100"` preset button exists in the card.
- **Live verify** (MAPS fixture, read-only): zoom to 300% → coverage marks are 1px and sit only on labeled frames; navigate to a known-unlabeled frame → no mark under the playhead. Controls render as three tidy rows (playback / jump / counter+time+help-right). Clicking the `100` preset sets `#ia3d-skip-n` to 100 and `«`/`»` jump 100 frames.

## Out of scope (YAGNI)
- Re-fetching coverage on plain window resizes (only the zoom slider triggers re-fit + re-fetch).
- Applying any of this to View Analyzed / frame-labeler.
- Changing the bucketing/markW algorithm itself (re-fetch at the right width is sufficient).
