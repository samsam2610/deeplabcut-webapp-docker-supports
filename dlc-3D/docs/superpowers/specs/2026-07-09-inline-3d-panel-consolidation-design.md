# Inline-3D — consolidate analyze + finalize panel, relocate marker area

**Date:** 2026-07-09
**Branch:** `feat/inline-3d-panel-consolidation` (repo: `deeplabcut-webapp-docker-supports`)
**Module:** `dlc-3D`

## Goal (pure GUI rearrangement + one reused button)

1. **Merge** the standalone analysis-start flank (count + "Start from current" +
   "Start for range" + hint) *into* the right-column Finalize sub-card, producing one
   unified panel in this order: keyframe block → analyze buttons → new extract button →
   Add range to _analyzed → postfix/clip.
2. **Add** a button "Add current frame to labeled-data (no markers)" — reuses the
   existing Dataset-Curation Extract-Frame logic.
3. **Relocate** the marker area (bodypart chips + marker-edit controls) from *below*
   the playback controls into the 270px flank the analyze buttons vacated, so the four
   timelines (seek / status / note / finalized) pack up compactly.
4. **Preserve** the sticky behavior of the right panel (it must still follow the scroll).

## Decisions (from brainstorming)

- **Toggle gating:** the two analyze buttons + the new extract button are **always
  visible**. Only the keyframe block and the finalize outputs (Add range / postfix /
  clip) stay gated behind the "Finalize analysis" toggle.
- **New button placement:** immediately after the two analyze buttons.
- **Marker-edit controls:** move into the flank *with* the bodypart chips (fully clear
  the space below the controls).

## Current structure (template: card_inline_analysis_3d.html)

```
.ia3d-split
  .ia3d-left
    seek canvas
    .ia3d-controls-flank
      .ia3d-controls-left  → .ia3d-ctrl-top (controls+meta), #ia3d-bp-list-wrap, #ia3d-marker-edit-controls
      .ia3d-start-flank    → #ia3d-start-count, #ia3d-btn-analyze-current, #ia3d-btn-analyze-range-confined, #ia3d-start-hint
    #ia3d-viewer-timeline (status/note bars)
    #ia3d-finalize-coverage-wrap
  .ia3d-right  (sticky)
    #ia3d-finalize-panel → toggle + #ia3d-finalize-controls (keyframe, before/after/length, range, Add range, postfix, clip)
```

## Design

### Template moves (IDs preserved → existing JS keeps working)

`.ia3d-left / .ia3d-controls-flank`:
- Repurpose the right flank: replace class `.ia3d-start-flank` with `.ia3d-marker-flank`
  and move `#ia3d-bp-list-wrap` (bodypart chips) + `#ia3d-marker-edit-controls` into it.
- Remove the analyze block from the flank (it moves to the right panel).
- `.ia3d-controls-left` now holds only `.ia3d-ctrl-top` (controls + frame/time).

`.ia3d-right / #ia3d-finalize-panel`, new order under the toggle:
1. **`#ia3d-finalize-controls`** (gated, KEEPS this id — it is the `l`-shortcut's
   `panelEl` and the keyframe-window panel): Keyframe + Lock + before/after/length +
   range readout.
2. **Always-visible analyze block** (moved from `.ia3d-start-flank`, ids unchanged):
   `#ia3d-start-count`, `#ia3d-btn-analyze-current`, `#ia3d-btn-analyze-range-confined`,
   `#ia3d-start-hint`, then the **new** `#ia3d-add-frame-nomarkers-btn`.
3. **`#ia3d-finalize-outputs`** (new gated wrapper): Add range to _analyzed, postfix +
   both-cams, postfix tags, clip/rename/delete buttons, `#ia3d-finalize-status`.

### JS

- Finalize toggle handler (`inline_analysis_3d.js` ~L2348) and `_resetForOpen` (~L1477):
  drive **both** gated groups — toggle/show `#ia3d-finalize-controls` **and**
  `#ia3d-finalize-outputs` together (add the second element to the existing calls).
- New button: refactor the Extract-Frame click handler body (~L1167) into a reusable
  `async function _extractCurrentFrame()` and wire **both** `#ia3d-extract-frame-btn`
  (curation) and the new `#ia3d-add-frame-nomarkers-btn` to it.

### CSS (`inline_analysis_3d.css`)

- Add `.ia3d-marker-flank` (repurposed 270px right flank): holds the chips + edit
  controls, with `max-height` + `overflow-y: auto` so a long bodypart list stays
  compact; keep the left border/padding of the old `.ia3d-start-flank`.
- `.ia3d-bp-chips-wrap` no longer needs `flex:1` below the controls.
- **Keep** the `.ia3d-right` sticky rule (position:sticky, top, align-self:flex-start,
  max-height:calc(100vh - 1rem), overflow-y:auto) — the extra analyze content is
  absorbed by the existing max-height/scroll, so the panel still follows the scroll.

## Testing

- **`tests/test_inline_3d_panel_consolidation.py`** (source-pattern):
  - analyze buttons (`#ia3d-btn-analyze-current`, `#ia3d-btn-analyze-range-confined`)
    now live inside `#ia3d-finalize-panel`, not in a `.ia3d-start-flank`.
  - `#ia3d-finalize-outputs` exists and both gated groups are driven by the toggle
    (JS toggles both ids).
  - new `#ia3d-add-frame-nomarkers-btn` exists and JS wires it to the shared extract fn.
  - marker area (`#ia3d-bp-list-wrap`, `#ia3d-marker-edit-controls`) is inside the
    `.ia3d-marker-flank`.
  - `.ia3d-right` still has `position: sticky` (scroll-follow preserved).
- Run `pytest`. Manual: **container restart** (template = single-file bind mount), then
  verify the merged panel, gating, new button (extracts current frame PNG to
  labeled-data), relocated marker list, and that the panel still sticks on scroll.

## Non-goals

- No behavioral change to analysis, finalize, or extract logic (relocation + reuse only).
- No change to the Dataset Curation panel (its Extract Frame/Add-to-Dataset stay).
- Inline-3D card only.
