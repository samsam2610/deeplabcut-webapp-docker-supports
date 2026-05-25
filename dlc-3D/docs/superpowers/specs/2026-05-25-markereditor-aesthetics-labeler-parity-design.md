# markerEditor Aesthetics → Frame-Labeler Parity (+ fix marker size) — Design Spec

**Date:** 2026-05-25
**Module:** `dlc-3D` (frontend only)
**Status:** Approved (brainstormed; decisions below).
**Branch:** `feat/marker-editor-labeler-mechanics` (continues the labeler-parity work on the shared markerEditor; not yet merged to main).

## Goal

Make the shared `markerEditor`'s marker aesthetics/options match `frame_labeler_3d.js`, and fix the
marker-size slider (currently a no-op in both curation cards). All in the shared feature so the
inline-3D card AND View Analyzed inherit it; no fork; `tests/test_video_viewer_policy.py` stays green.

## Decisions (from brainstorming)

- **Color palette:** adopt the labeler's fixed 15-color list (`FL_COLORS`), `idx % 15`, for primary-layer markers AND bp-chips, in both cards. Colors repeat past 15 parts (the labeler already does). HSV `paletteColor` stays for comparison-layer differentiation only.
- **Selected ring:** white `rgba(255,255,255,0.85)`, offset `r+3.5`, width 2. **Drop** the current amber selected ring and the white "edited" ring (exact labeler match; no edited cue).

## Scope

Frontend only. Enhance `markerEditor` + `shapes.mjs` + add a palette helper; wire the marker-size
slider and a new show-names toggle in both cards. No backend change, no new routes, no data-layer
change, no player fork. Out of scope: comparison-layer shapes (keep diamond/square/triangle), the
no-op show-all/hide-all *parts* buttons, the labeler's training-label workflow, changing the primary
marker shape (stays filled circle).

## Files

- Modify: `src/static/components/viewer/internal/palette.mjs` — add `FL_COLORS` + `labelerColor(idx)` (does NOT change `hsvToRgb`/`paletteColor`).
- Modify: `src/static/components/viewer/internal/shapes.mjs` — add the dark contrast outline (`rgba(0,0,0,0.55)`, width 1.2) under the fill.
- Modify: `src/static/components/viewer/features/marker_editor.js` — `setMarkerSize`, `setShowNames`; hovered-bp tracking + name-label rendering; white selected ring (drop amber + edited ring); FL palette for primary markers + chips; hit-pad 6.
- Create: `src/static/components/viewer/internal/name_label.mjs` (if extractable) — pure geometry for the hover/name label box (position + box rect), with node:test.
- Test: `tests/unit/test_viewer_palette.mjs` (or the existing palette test) — `labelerColor`; `tests/unit/test_name_label.mjs` — label geometry.
- Modify: `tests/test_marker_editor_feature.py` — contract for the new API + aesthetics (source assertions).
- Modify: `src/templates/partials/card_inline_analysis_3d.html` + `card_viewer_3d.html` — add a "Show names" checkbox to the overlay controls.
- Modify: `src/static/inline_analysis_3d.js` + `viewer_3d.js` — wire marker-size slider → `setMarkerSize`; wire show-names checkbox → `setShowNames`.
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` (+ the viewer_3d test file) — marker-size slider now wired (not no-op); show-names toggle present + wired.

## Behaviors

### B1 — Marker size (fix the bug)
`markerEditor.setMarkerSize(px)` sets the internal `markerSize` and re-renders. The cards' slider
`input` handlers (`#ia3d-overlay-marker-size`, `#va3d-overlay-marker-size`; range 1–30, default 6)
call it, replacing the label-only no-ops at `inline_analysis_3d.js:766-771` / `viewer_3d.js:476-482`.
Keep `markerRadius`'s responsive scaling (size × display scale, floor 1).

### B2 — Color palette → `FL_COLORS`
Add to `palette.mjs`: `FL_COLORS` (the 15 hexes from `frame_labeler_3d.js:623-627`) and
`labelerColor(idx) = FL_COLORS[((idx % n)+n)%n]`. In `markerEditor`, color the primary-layer markers
and the bp-chips by the bodypart's index via `labelerColor`. Comparison layers keep `paletteColor`
(HSV) so multiple layers stay visually distinct. Result: chips, primary markers, and the labeler all
agree on a bodypart's color.

### B3 — Selected ring → white; drop edited ring
Selected marker (primary, editable tile, `pose.bp === selectedBp`): stroke a ring at `r+3.5`,
`rgba(255,255,255,0.85)`, width 2. Remove the amber `#facc15` selected ring and the white "edited"
ring entirely (applies to both the pose-loop markers and the edits-only markers added earlier).

### B4 — Contrast outline
In `shapes.mjs`, each marker fill is followed by a dark outline stroke `rgba(0,0,0,0.55)`, width 1.2
(matches the labeler's contrast). Applies to all shapes (harmless for comparison shapes).

### B5 — Hover-to-show-name
Track `hoverBp` per focused tile (reuse the hit-test already run in `updateHoverCursor`); on change,
re-render. In `renderTile`, when a marker is the hovered bp (or show-names is on), draw its name as a
label box beside the dot — bold 11px mono, bg `rgba(12,13,16,.65)`, positioned `cx + r + ~4`,
`cy + ~4`, text = the marker's color. Extract the box geometry to `name_label.mjs` (pure) if clean.

### B6 — Show/hide names toggle
`markerEditor.setShowNames(bool)`; when true, draw all (finite, non-hidden) markers' names; when
false, names render on hover only. Add a "Show names" checkbox to both cards' overlay controls
(`#ia3d-overlay-show-names`, `#va3d-overlay-show-names`), wired to `setShowNames`.

### B7 — Selection zone
Change the hit-test pad from 8 to 6 (labeler parity) at the `markerEditor` hitTest call sites.

## View Analyzed regression guard

All changes apply to View Analyzed too (it composes the same feature). It edits via the overlay
toggle (mirrors `setEditable`, fixed earlier). Verify: markers still render with the new palette +
white ring + outline; the marker-size + show-names controls work; editing still works when overlay
on. No data-layer change.

## Testing

- **node:test:** `labelerColor` (cycling, negative-safe); `name_label` geometry (box position/rect) if extracted.
- **pytest `test_marker_editor_feature.py`** (static-source style): `setMarkerSize`/`setShowNames` exist; selected ring uses the white rgba (not `#facc15`); FL palette / `labelerColor` used for primary + chips; hover-name + show-names render paths present; hit pad 6.
- **pytest UI-isolation (both cards):** marker-size slider handler calls `setMarkerSize` (no longer label-only); `#…-overlay-show-names` present + wired to `setShowNames`.
- **pytest `test_video_viewer_policy.py`:** stays green (no fork).
- **Live verify (read-only)** on a posed video, BOTH cards, no destructive saves: dragging marker-size resizes the rendered markers; selected marker shows a white ring; markers use the FL_COLORS hexes (matching chips) with a dark outline; hovering a marker shows its name; the Show-names toggle shows/hides all names. Confirm View Analyzed unaffected beyond the new look + working controls.
