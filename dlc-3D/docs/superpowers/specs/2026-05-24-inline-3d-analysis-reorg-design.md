# Inline-3D Analysis Card Reorg — Design Spec

**Date:** 2026-05-24
**Module:** `dlc-3D` (frontend) + main webapp `deeplabcut-webapp-docker/src/dlc` (small backend additions)
**Status:** Approved (mockup-driven). Live mockup: `GET /dlc-3d/mock-up` → `src/static/mockup_inline_3d.html.j2`.

## Goal

Reorganize the inline 3D-analysis card into a full-width, two-column working layout once a
video is selected: a left region with the video viewer + controls + per-frame timelines, and a
right-docked Finalize-analysis sub-card. Add a current-frame "Start analysis for range" action
gated on a keyframe lock, a range-confined navigation mode, per-frame status/note editing under
each timeline, and per-project click-to-fill quick-tags for postfix/status/note fields.

## Scope

Frontend reorg of one card. The only backend change is extending the per-project UI-setting
allow-list with three tag keys. The "for range" analysis reuses the **existing**
`analyze-range` endpoint (no new route). The per-frame status/note write reuses the **existing**
`statusNoteTimeline` save-back (no new route). No change to triangulation, the viewer library
contract, or other cards.

## Files

**dlc-3D (frontend)**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` — restructure the player section into the two-column layout; relocate timelines; add the analysis-button flank, the per-frame edit rows, the postfix tags, and the keyframe-lock indicators.
- Modify: `src/static/inline_analysis_3d.css` — layout rules for the full-width card, the controls/analysis flank, compact timeline rows, chip-fill region, edit rows, tag pills, and the lock visuals.
- Modify: `src/static/inline_analysis_3d.js` — wire the second "Start analysis from current frame" button and the gated "Start analysis for range"; the keyframe-lock → range-confine behavior + red block/flag; the per-project tag CRUD + click-to-fill for postfix/status/note; ensure the relocated status/note edit els are passed to `statusNoteTimeline`.
- Possibly modify: `src/static/components/viewer/video_viewer.js` — add an optional seek/play **bounds** clamp (`setBounds(start,end)` / `clearBounds()`); only if the inline consumer cannot cleanly confine navigation on its own. Prefer the consumer; touch the library only if necessary, behind a no-op default so other consumers are unaffected.
- Test: `tests/` — node:test for any new pure logic (bounds clamp, tag list reducer) and/or pytest static-analysis if a viewer-policy contract is touched.

**deeplabcut-webapp-docker (backend)**
- Modify: `src/dlc/inline_analysis.py` — add `postfix_tags`, `status_tags`, `note_tags` to `_UI_SETTING_KEYS` (line ~383). Values are JSON-encoded string lists; the existing GET/POST `/dlc/project/ui-setting` handler stores them verbatim in `ui_settings.sqlite` via `project_settings.py`. No schema change.

## Layout (after a video is selected)

The card (`#inline-analysis-3d-card`) becomes full page width. Source tabs / parameters stay above
as today. The **player section** (`#ia3d-player-section`) becomes a two-column flex:

**Left region** (flex:1), top to bottom:
1. **Keyframe-lock flag** (hidden unless locked): red `🔒 range-locked · <start>–<end>` pill, rendered **above** the cam0 tile label (normal flow, not overlaying the label).
2. **Viewer mount** (`#ia3d-viewer-mount`) — unchanged VideoViewer dual-tile render, each tile keeping its per-tile **size slider** (`.vv-tile-size`).
3. **Main seek bar** (`#ia3d-seek-canvas`) — when locked, draws a **red range block** over `[start,end]` and dims the area outside it.
4. **Controls + frame#/time row** (`.mk`-equivalent of `.ia3d-controls-flank`):
   - Left: the existing **two control rows** intact (playback row; skip-group + presets row).
   - Middle: compact **frame # + time** cluster (`#ia3d-frame-counter`, `#ia3d-time-display`, help `?`) in the gap between the controls and the analysis buttons.
   - Right: **analysis-button flank** (fixed ~270px) — a frame-count line (`≈ N frames from current frame`), the **"Start analysis from current frame"** button, the gated **"Start analysis for range"** button, and a one-line hint.
5. **Body-marker chips** (`#ia3d-bp-chips`) — fill the empty space below the controls/frame# row, to the left of the analysis flank; wrap across rows (handles ~10–15 landmarks).
6. **Status timeline** (compact): one header row = label + ◀▶ nav + filter chips; canvas below; then the **per-frame status edit row** (text field + Save + quick-tags beside the field).
7. **Notes timeline** (compact): same structure; per-frame **note edit row** below.
8. **Finalized-frames timeline** (compact): label + ◀▶ nav + caption; the finalize coverage canvas (`#ia3d-finalize-coverage`) relocated here, below Notes.

**Right region** (~300px, `#ia3d-finalize-panel` docked): the Finalize-analysis sub-card, toggle
**checked by default**. Contains keyframe input + lock, before/after/length, range display,
"Add range to _analyzed", a divider, postfix field + **postfix quick-tags** (click-to-fill,
per-project), both-cams checkbox, "Add range to _analyzed and extract clip", Rename, Delete
(un-finalize), and status line.

**Below the two columns** (full card width, unchanged): Dataset Curation panel; Create Clip panel.

## Behavior

### Start analysis (two buttons)
- **From current frame** (always enabled): POST `analyze-range` with `start_frame = currentFrame`, `n_frames = frames-per-click`. This is a second copy of the top "Start analysis" button so the user need not scroll up; both stay in sync (same params, same status display).
- **For range** (gated): enabled **only when Finalize is on AND the keyframe is locked**. On click, POST `analyze-range` with `start_frame = range.start`, `n_frames = range.length`, where the range is the finalize keyframe window (`keyframe − before` → `keyframe + after`). Disabled buttons grey out via the existing `.btn-sm:disabled` rule.

### Keyframe lock (single switch)
The finalize keyframe-lock checkbox (`#ia3d-finalize-lock`) drives all of:
- **Unlocked:** the keyframe input tracks the current frame (keyframe = current frame as you navigate). Navigation is unconstrained. No lock flag, no red block. "For range" disabled.
- **Locked:** the keyframe value freezes. Navigation (play, step, skip, seek-canvas click, status/note nav) is **confined to `[range.start, range.end]`**. The main seek bar shows the red range block (outside dimmed); the red lock flag shows above cam0. "For range" enabled.
- **No clamp case:** because the keyframe equals the current frame at the moment of locking, the current frame is always inside the range when the lock engages. No out-of-range snapping is needed.

### Per-frame status/note editing (restored)
Below each of the Status and Notes timelines, an edit row exposes the current frame's value with a
Save button. These map to `statusNoteTimeline`'s existing `els.statusInput`/`els.noteInput` +
`els.saveStatusBtn`/`els.saveNoteBtn` (and badges), which already write the current frame's row to
the **cam0 companion CSV** via the configured `saveRow` endpoint. The reorg's job is to place these
els in the new location and pass them to the feature config — no new save logic.

### Quick-tags (postfix, status, note)
Three independent click-to-fill tag lists, each stored **per-project**:
- Rendered as pills next to their field; clicking a pill **replaces** the field's contents with the tag text (default; not append).
- Each pill has an `×` to remove it; a `+ tag` affordance adds the current field value (or a prompt) as a new tag.
- Persisted via GET/POST `/dlc/project/ui-setting` under keys `postfix_tags`, `status_tags`, `note_tags` (JSON string-list values), reusing the debounced settings client already used for `finalize_window`/`clip_window`.

### Size sliders (regression guard)
The per-tile video size sliders must keep functioning after the markup reorg — verified by driving
them live (slider change resizes the corresponding tile). This is an explicit acceptance criterion,
not new behavior.

## Data Flow

- **Settings:** browser ⇄ `/dlc/project/ui-setting` (allow-listed keys) ⇄ `project_settings.py` ⇄ `<project>/ui_settings.sqlite`. Tag lists join the existing `finalize_window`/`clip_window` values.
- **Analysis:** both start buttons → `analyze-range` (existing) with different `start_frame`/`n_frames`; status reflected in the shared status element.
- **CSV edits:** edit rows → `statusNoteTimeline.save()` → existing `saveRow` endpoint → cam0 CSV.
- **Lock:** lock checkbox → inline state → (a) viewer bounds confine + (b) seek-bar red block draw + (c) lock flag visibility + (d) "for range" enablement.

## Error Handling

- `analyze-range` already validates `n_frames` in 1..10000 and int params; the "for range" path must compute a valid positive `n_frames` and surface backend errors in the status line.
- Tag POSTs are best-effort (debounced); a failed save logs and leaves the in-memory list intact, matching the existing settings client.
- Disabled "for range" never fires; re-evaluate enablement on finalize-toggle and lock changes.

## Testing

- **node:test** for any extracted pure logic: a bounds-clamp helper (`clampToBounds(frame,start,end)`) and a tag-list reducer (add/remove/dedupe). Keep DOM-free logic in `components/viewer/internal/*.mjs` if it touches the library; otherwise a small inline module under `src/static/`.
- **pytest static-analysis** only if the viewer-policy contract is touched (e.g. new public `setBounds`/`clearBounds` on `VideoViewer`); add an assertion mirroring the existing policy tests.
- **Live verification (read-only)** against the khoai/tdcs fixtures: full-width layout on select; both start buttons present and "for range" gating flips with the lock; red block + flag appear and navigation is confined when locked; status/note edit rows load the current frame and tags click-to-fill; postfix tags persist across reload; **size sliders resize tiles**. Do NOT click Add/Extract/Finalize/Delete against protected dirs.

## Out of Scope

- Changes to triangulation, EKS/LP, or other cards.
- Retiring the Create Clip panel (stays full-width below, confirmed).
- Append-mode tags (replace-only for now).
- Any rework of the VideoViewer library beyond an optional, no-op-default bounds clamp.
