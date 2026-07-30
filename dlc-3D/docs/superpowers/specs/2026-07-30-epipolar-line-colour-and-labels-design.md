# Epipolar line colour and edge labels

**Date:** 2026-07-30
**Status:** design approved, not yet implemented
**Module:** `dlc-3D`
**Builds on:** [2026-07-29-inline-3d-reprojection-design.md](2026-07-29-inline-3d-reprojection-design.md)

## Problem

With "Show epipolar lines" ticked, every line is drawn in the same colour
(`rgba(120,200,255,.85)`) and carries no label. On a 16-bodypart session that is
sixteen indistinguishable blue lines. You cannot tell which line belongs to which
marker, which is most of what the overlay is for: checking whether *this* marker
sits on *its own* epipolar line.

## Scope

1. Each line takes the colour of its bodypart's marker.
2. Each line is labelled with its bodypart name at the frame edge, staggered
   along the line so labels do not overlap.
3. Lines follow the marker overlay's per-bodypart visibility.

### Non-goals

- Changing which bodyparts have poses, or the epipolar maths.
- Labels on both ends, or collision-measured label placement.
- Any change to the shared viewer library under `components/viewer/`.

## Colour

`markerEditor` colours a primary-layer marker with `labelerColor(pose.color_idx)`
and sets the same value on that bodypart's chip:
`chip.style.setProperty("--bp-color", labelerColor(idx))`. The chip is therefore
an authoritative, already-rendered source for a bodypart's colour.

```js
_reprojBodypartColor(bp) -> css colour string
```

reads the inline `--bp-color` from that bodypart's chip and falls back to the
current blue when no chip exists (the overlay can be on before poses load).

This deliberately avoids three worse options: duplicating the palette logic,
re-deriving `color_idx` (which is server-supplied and could drift from a locally
computed index), and extending the shared `markerEditor` API, which the live
original card also loads.

### The chip query MUST be scoped to this card

`.vv-bp-chip` is created by the shared `markerEditor`, so **both cards' chips
exist in the same document** when both are open. The containers differ —
`ia3d-bp-chips` for the original, `ia3dr-bp-chips` for this clone.

A document-wide `document.querySelector('.vv-bp-chip[data-bp="Snout"]')` would
match whichever card rendered first and silently read the *other* card's colours
and visibility. Every chip query must be rooted at `#ia3dr-bp-chips`. This is the
exact collision the `ia3dr-` namespacing exists to prevent, and it would stay
invisible until someone opened both cards.

## Visibility

`markerEditor` marks hidden bodyparts on the chip:
`chip.classList.toggle("vis-hidden", isHiddenAt(currentFrame, bp))`.

A bodypart whose chip carries `vis-hidden` gets no line. Because `isHiddenAt`
covers both the double-click hide and per-frame hiding, the lines follow both
without any extra work. Hiding a marker and keeping its line would be
contradictory; this keeps lines and markers telling the same story, and reuses a
control that already exists rather than adding one.

## Label placement

Pure geometry, in a new module so it can be tested properly:

```js
// src/static/internal/epiline_label.mjs
export function labelAnchor(segment, order, step) -> {x, y, ux, uy} | null
```

- `segment` is `[[x1,y1],[x2,y2]]`, the line already clipped to the frame.
- The anchor endpoint is whichever end has the smaller `x + y`, i.e. nearer the
  frame's top-left. A deterministic choice keeps labels from jumping between
  edges while scrubbing.
- The label is then walked `order * step` pixels along the line, towards the
  other endpoint. `ux, uy` is that unit direction.
- `order` is the bodypart's index **among currently visible bodyparts**, so the
  staircase compacts when parts are hidden rather than leaving gaps.
- `step` defaults to 14 px, matching the 14 px label-box height already used for
  marker names, so consecutive labels sit flush rather than overlapping.
- Returns `null` for a degenerate (zero-length) or non-finite segment.

Offsetting *along the line* rather than perpendicular to it means a label always
sits on the line it names, even where several lines converge near the epipole.

## Drawing

Labels reuse `nameLabelBox` from `components/viewer/internal/name_label.mjs`,
called with `r = 0` at the anchor point, so an epipolar label is visually
identical to a marker name label: `NAME_LABEL_FONT`, an `rgba(12,13,16,.65)`
backing box, and the text in the bodypart's own colour.

Draw order per tile stays as it is — lines and labels are painted after
`markerEditor` has cleared the canvas and drawn its markers, so they sit on top.

## Testing

**Pure geometry** (`tests/unit/test_epiline_label.mjs`, run with `node --test`,
matching the repo's existing `tests/unit/*.mjs` convention):

- the anchor is the endpoint nearer the top-left, whichever order the endpoints
  are supplied in
- `order = 0` anchors exactly at that endpoint
- the returned point lies on the segment's line (cross-product ≈ 0)
- spacing is monotonic: successive `order` values move strictly further along
- `ux, uy` is a unit vector pointing at the far endpoint
- a zero-length or non-finite segment returns `null`

This matters more than usual here. The panel's other tests assert only that
strings appear in the source, and that convention already allowed a completely
unwired overlay to ship earlier in this project. Geometry is pure, so it can
carry real assertions — and it is the part most likely to be subtly wrong.

**Wiring** (`tests/test_reproj_panel_wiring.py`), string assertions as per repo
convention, but on the invariants that actually bite:

- the chip query is rooted at `#ia3dr-bp-chips` and is NOT a bare
  `document.querySelector('.vv-bp-chip')` — the cross-card guard
- `vis-hidden` is consulted before a line is drawn
- the drawing code imports `labelAnchor` and `nameLabelBox` rather than
  reimplementing either

## Risks

- **Cross-card chip reads.** Covered by a test asserting the scoped query, but a
  future edit could reintroduce it. The failure is silent and only manifests with
  both cards open.
- **Chip colour and marker colour could in principle disagree.** The chips use
  `labelerColor(idx)` over the bodypart list while markers use
  `labelerColor(pose.color_idx)` from the server payload. The shared module's own
  comment states `color_idx` "matches the chips' order", so they are intended to
  agree. If they ever diverge that is a pre-existing bug in the shared library,
  and this feature would make it visible rather than cause it.
- **Sixteen labels is still a lot of text.** The staircase keeps them legible and
  hiding bodyparts thins them out, but a dense session will still look busy. No
  cap is imposed; decluttering is the user's call via the chips.
