# Inline 3D — Pair Skip Buttons + Timelines Match Zoomed Video Width — Design

**Date:** 2026-05-23
**Status:** Approved (pending implementation plan)
**Repo:** `deeplabcut-webapp-docker-supports/dlc-3D`. Frontend-only (no backend changes).

## Context

Two refinements to the inline 3D card, reported from the live card:

1. **Forward N-frame skip "missing".** `#ia3d-btn-skip-fwd` (the `»` skip-forward button) already exists in `card_inline_analysis_3d.html` and is wired in `inline_analysis_3d.js`. But the `.fe-controls` row wraps at the card's normal width, pushing skip-forward onto a second line — separated from skip-back (`«`) by the `#ia3d-skip-n` input and the preset chips. The pair looks broken, so the forward button reads as missing.

2. **Timelines don't track the zoomed video.** The card has a global zoom slider (`#ia3d-zoom`, 50–300%) that calls `VideoViewer.setZoom(pct)`, which widens the video row (`rowEl`) — potentially beyond the card, centered via a negative `marginLeft`. The four timeline canvases (`#ia3d-seek-canvas`, `#ia3d-status-canvas`, `#ia3d-note-canvas`, `#ia3d-finalize-coverage`) are fixed at `width:100%` of the card, so when zoomed they no longer span the videos. Matching the timeline width to the displayed video row gives more pixels-per-frame → finer click precision.

**User decisions:**
- #1: pair the two skip buttons — order `« » [N] [presets]`, kept together as one unit.
- #2: the **global zoom** drives it (not the per-view weight sliders, which only redistribute width between the two tiles). Timelines grow to the **same width** as the video row and **mirror its horizontal offset**; at 100% they are unchanged.

## Components

### Feature 1 — pair the skip buttons (HTML + CSS only)

- **`card_inline_analysis_3d.html`:** wrap the four skip controls in one inline-flex unit and reorder them:
  ```html
  <span class="ia3d-skip-group">
    <button id="ia3d-btn-skip-back" …>«</button>
    <button id="ia3d-btn-skip-fwd"  …>»</button>
    <input  id="ia3d-skip-n" …>
    <span class="ia3d-skip-presets">…(1)(5)(10)(30)…</span>
  </span>
  ```
  `#ia3d-btn-skip-fwd` moves to sit immediately after `#ia3d-btn-skip-back`; the `#ia3d-skip-n` input and presets keep their existing markup, just inside the new wrapper.
- **`inline_analysis_3d.css`:** `#inline-analysis-3d-card .ia3d-skip-group { display:inline-flex; align-items:center; gap:.3rem; flex-shrink:0; }`. Because the group is a single flex item, `flex-wrap` on `.fe-controls` wraps it as a whole — `«` and `»` are never split across lines.
- **No JS change.** The handlers for `#ia3d-btn-skip-back` / `#ia3d-btn-skip-fwd` / presets / `#ia3d-skip-n` already exist and stay wired (the elements keep their ids).

### Feature 2 — timelines match the zoomed video row

The video row's rendered geometry is computed privately inside `VideoViewer.setZoom` (`fitViewerSize` → `rowEl.style.width` / `marginLeft`). The consumer needs that geometry to mirror it.

- **`video_viewer.js`:** `setZoom(pct)` returns the geometry it applied — `{ width, marginLeft }` — or `null` when it early-returns (no primary image yet). Pure addition; existing callers ignore the return value.
- **`status_notes.js`:** add `redraw()` to the feature's returned API (currently only `{ attach }`). It calls the existing internal `redraw(curFrame())`, letting a consumer force a re-render after resizing the status/note canvases. No behavior change otherwise.
- **`inline_analysis_3d.js`:**
  - Keep a handle to the status/note feature: `const _snTimeline = statusNoteTimeline({…}); _viewer.use(_snTimeline);`
  - In the existing `#ia3d-zoom` input handler, after `const g = v.setZoom(pct)`, call `_applyTimelineWidth(g)`.
  - `_applyTimelineWidth(g)`: for each of the four timeline canvases, set
    - `style.width  = (g && g.width)      ? g.width + "px"      : ""`
    - `style.marginLeft = (g && g.marginLeft < 0) ? g.marginLeft + "px" : ""`
    (both reset to `""` at 100% / when `g` is null → back to CSS `width:100%`, no offset.)
    Then redraw all bars: `_redrawSeekTimeline()`, `_redrawFinalizeCoverage()`, `_snTimeline.redraw()`.

**Why per-canvas, not a wrapper:** the four canvases are not contiguous in the DOM (the controls row sits between `seek` and `status`/`note`; `finalize` is in a separate panel). But each lives in a card-width container, so the same `width + marginLeft` aligns every one exactly under the centered, overflowing video row.

## Data flow / behavior / error handling

- **At zoom 100%** (or before an image loads → `g` null): timelines reset to `width:100%`, `marginLeft:""` — current behavior, unchanged.
- **Above 100%:** each timeline canvas widens to `g.width` and shifts by `g.marginLeft`, tracking the video row. On redraw, `canvas.width = getBoundingClientRect().width` (the new width) for every bar; coverage marks (`coverageFrameRects`), the playhead, and clicks (`xToFrame`) all recompute from that width, so marks stay aligned with seeks (frame-space fix already shipped). Status/note bars redraw via `_snTimeline.redraw()` at the new width.
- **Coverage data is not re-fetched** — marks rescale to the new width; bucket granularity is unchanged. Click precision still improves because `xToFrame` is continuous in pixels.
- **Overflow:** the video row already overflows the card via negative `marginLeft` (the zoom feature works today), so ancestors don't clip — the timelines overflow identically and stay aligned.
- **Per-view weight sliders** are intentionally not tracked: they redistribute width between the two tiles without changing the row total, so the timelines need not react.

## Testing

- **Feature 1** — inline UI-isolation contract (`tests/test_inline_analysis_3d_ui_isolation.py`): assert `.ia3d-skip-group` exists in the card and contains both `#ia3d-btn-skip-back` and `#ia3d-btn-skip-fwd` plus `#ia3d-skip-n`; assert the `.ia3d-skip-group` CSS rule is present.
- **Feature 2** —
  - Inline contract: `_applyTimelineWidth` is defined and called from the `#ia3d-zoom` handler (passing `v.setZoom(...)`'s return); `status_notes.js` returns a `redraw` method.
  - **Live verify** (OM-2 / any video + h5): zoom to 150% → each timeline canvas's rendered width equals the video-row width and its `marginLeft` matches; clicking a coverage mark still lands exactly on its frame; set back to 100% → timelines return to card width with no offset.

## Out of scope (YAGNI)

- Re-fetching coverage at higher bucket resolution when zoomed.
- Applying timeline-width matching to View Analyzed / frame-labeler.
- Reacting to plain window resizes (only the zoom slider triggers re-fit).
