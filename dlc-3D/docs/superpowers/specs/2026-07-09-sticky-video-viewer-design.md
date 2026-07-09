# Inline-3D — pin the video viewer while scrolling

**Date:** 2026-07-09
**Branch:** `feat/sticky-video-viewer` (repo: `deeplabcut-webapp-docker-supports`)
**Module:** `dlc-3D`

## Goal

In the inline-3D card, keep the video tile visible while the user scrolls down through
the controls / timelines below it — so the frame being edited stays on screen. The
pinned video releases naturally at the end of the card.

## Context

The card body is a two-column split (`.ia3d-split`, `align-items: flex-start`):

- `.ia3d-left` (`flex: 1; position: relative`) — video mount, seek bar, controls,
  chips, marker-edit controls, status/note timelines, finalize-coverage bar.
- `.ia3d-right` (`width: 300px`) — the Finalize-analysis sub-card.

The video is `#ia3d-viewer-mount` at the top of `.ia3d-left`. The page scrolls on the
window (no inner scroll container clips the card; the only `overflow` rules in the
module CSS are on unrelated `.lp-result` / ellipsis labels). `--bg` is the card's
background token.

Decision (from brainstorming): **pin the video only.** The scrubber + playback controls
scroll with the rest; frame navigation while scrolled still works via the `←`/`→` and
`Ctrl+Arrow` keyboard shortcuts (document-scoped). No height cap initially — the user
controls video size via the zoom / per-tile sliders.

## Design

CSS-only, in `src/static/inline_analysis_3d.css` (served live from the `src/static`
directory mount — no template edit, no container restart):

```css
/* Keep the video tile in view while scrolling the controls/timelines below it.
   Sticks within .ia3d-left, so it releases at the end of the card. Video-only:
   the scrubber/controls scroll; ←/→ and Ctrl+Arrow still navigate frames. */
#inline-analysis-3d-card #ia3d-viewer-mount {
  position: sticky;
  top: .5rem;
  z-index: 5;
  background: var(--bg);
}
```

Rationale:
- **Sticky inside `.ia3d-left`** — the sticky reference is the window scroll; the
  element stays pinned until `.ia3d-left`'s bottom scrolls past, i.e. "until the end
  of the card".
- **`z-index: 5` + opaque `background: var(--bg)`** — the pinned mount must paint above
  and hide the controls/timelines scrolling beneath it, or they would show through the
  transparent tile gaps.
- **`top: .5rem`** — a small gap from the viewport top. If a fixed page nav is found to
  overlap during the live check, bump this to the nav height.
- **Marker editing still maps correctly** — the per-tile overlay canvas lives inside
  the mount, so it sticks with the video; pointer→frame mapping uses
  `getBoundingClientRect`, which tracks the sticky box.

## Testing

- **`tests/test_sticky_video_viewer.py`** (new, source-pattern): the CSS defines a
  `position: sticky` rule for `#ia3d-viewer-mount` with a `top` and an opaque
  `background`.
- Sticky behavior itself needs a real browser — **manual live check** (CSS is live on
  hard-refresh): open a video, enable finalize, scroll down → the video stays pinned
  and the controls/timelines scroll beneath it; it releases at the card's end.
- Playwright e2e auto-skips without the OM-2 fixture.

## Non-goals

- No change to the viewer-3D or dlc-3D cards (inline-3D only, as requested).
- No sticky scrubber/controls and no video height cap (can be added later if wanted).
- No template change (pure CSS).
