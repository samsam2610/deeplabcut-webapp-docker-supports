# Inline-3D — pin the Finalize-analysis card while scrolling

**Date:** 2026-07-09
**Branch:** `feat/sticky-video-viewer` (repo: `deeplabcut-webapp-docker-supports`)
**Module:** `dlc-3D`

## Goal

In the inline-3D card, keep the **Finalize-analysis sub-card** (Keyframe / Lock /
before / after / length / Add range / postfix tags / clip buttons) in view while the
user scrolls down through the taller left column below it. The pinned sub-card releases
naturally at the end of the card.

> Note: an earlier revision pinned the video tile instead — corrected here to pin the
> finalize sub-card per the user's clarification.

## Context

The card body is a two-column split (`.ia3d-split`, `align-items: flex-start`):

- `.ia3d-left` (`flex: 1; position: relative`) — video mount, seek bar, controls,
  chips, marker-edit controls, status/note timelines, finalize-coverage bar (tall).
- `.ia3d-right` (`width: 300px`) — the Finalize-analysis sub-card (the element to pin).

The page scrolls on the window (no inner scroll container clips the card; the only
`overflow` rules in the module CSS are on unrelated `.lp-result` / ellipsis labels).

## Design

CSS-only, in `src/static/inline_analysis_3d.css` (served live from the `src/static`
directory mount — no template edit, no container restart):

```css
#inline-analysis-3d-card .ia3d-right {
  width: 300px;
  flex-shrink: 0;
  position: sticky;
  top: .5rem;
  align-self: flex-start;
  max-height: calc(100vh - 1rem);
  overflow-y: auto;
}
```

Rationale:
- **`position: sticky` on `.ia3d-right`** — a sticky sidebar: it stays pinned to the
  top of the viewport while the taller `.ia3d-left` column scrolls, releasing when the
  split's bottom scrolls past ("until the end of the card").
- **`align-self: flex-start`** — the split is already `align-items: flex-start`, but
  setting it explicitly guarantees the column keeps its natural height (a stretched
  full-height flex item can't stick).
- **`max-height: calc(100vh - 1rem)` + `overflow-y: auto`** — if the finalize panel is
  taller than the viewport, its own content scrolls so the whole panel stays reachable
  while pinned.
- **`top: .5rem`** — small gap from the viewport top; bump to a fixed nav's height if
  the live check shows overlap.
- No `z-index`/opaque background needed — the sticky sidebar sits in its own column
  beside the scrolling one, so there's no overlap/bleed.

## Testing

- **`tests/test_sticky_video_viewer.py`** (source-pattern): `.ia3d-right` is
  `position: sticky` with a `top`, `align-self: flex-start`, and a
  `max-height` + `overflow-y: auto`; and the video mount is NOT sticky.
- Sticky behavior needs a real browser — **manual live check** (CSS is live on
  hard-refresh): open a video, enable finalize, scroll down → the finalize sub-card
  stays pinned and releases at the card's end; if the panel is very tall it scrolls
  internally.
- Playwright e2e auto-skips without the OM-2 fixture.

## Non-goals

- No change to the viewer-3D or dlc-3D cards (inline-3D only).
- No template change (pure CSS).
