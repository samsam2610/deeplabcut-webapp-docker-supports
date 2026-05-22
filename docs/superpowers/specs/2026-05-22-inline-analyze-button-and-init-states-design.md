# Inline Analysis: "Start Analysis" button restyle + Init-button states

**Date:** 2026-05-22
**Status:** Approved (pending implementation plan)

## Summary

Two UI changes applied to **both** the 2D and 3D inline-analysis cards:

1. **Restyle the inline "Analyze…" button** to exactly match the "Start Analysis"
   button in the Analyze Video/Frames card — accent `btn-create` styling, an
   outline play-triangle icon, and the static label **"Start Analysis"**.
2. **Refine the Initialize-analysis-file button** so that when the analysis
   file(s) already exist the button is unclickable with an explanatory note,
   and (3D only) the asymmetric "one camera has a file, the other doesn't" case
   is detected and surfaced to the user.

## Scope & affected files

This work spans **two separate git repositories**:

| Concern | Repo | Files |
|---------|------|-------|
| 2D inline analysis | `deeplabcut-webapp-docker` (main webapp) | `src/templates/partials/card_inline_analysis.html`, `src/static/js/inline_analysis_player.js` |
| 3D inline analysis | `deeplabcut-webapp-docker-supports/dlc-3D` (this repo) | `src/templates/partials/card_inline_analysis_3d.html`, `src/static/inline_analysis_3d.js` |

The reference button lives in the main webapp at
`src/templates/partials/card_analyze.html:136` (`#btn-run-analyze`, "Start
Analysis"). The `btn-create` style is defined in the main webapp's
`src/static/css/layout.css:110` / `src/static/style.css:186` and is available to
the 3D card because the 3D partial is injected into the main webapp page.

## Change 1 — Analyze button matches "Start Analysis"

### Reference markup (`card_analyze.html:136`)

```html
<button id="btn-run-analyze" class="btn-sm btn-create">
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2.2" stroke-linecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
  Start Analysis
</button>
```

### Target — both cards

The inline analyze button adopts the reference exactly:

- Class becomes `btn-sm btn-create` (was plain `btn-sm`).
- Content becomes the outline play-triangle SVG above + the static text
  `Start Analysis` (replacing the `▶ …` text glyph).
- Drop the `width:100%` inline style so the button is auto-width like the
  reference; keep `margin-top:.3rem` for vertical spacing.

### 2D — `card_inline_analysis.html:79` + `inline_analysis_player.js`

- HTML: `#ia-btn-analyze-range` → `class="btn-sm btn-create"`, SVG + `Start
  Analysis`, no `width:100%`.
- JS: **remove the dynamic-label machinery** that rewrote the button text:
  - `_iaSyncLabel()` (`inline_analysis_player.js:2231-2235`)
  - its `iaFramesPerCk` `input` listener (`:2236`)
  - the `MutationObserver` on `iaFrameCounter` that called it (`:2238-2241`)

  Rationale: `_iaSyncLabel` set `iaBtnAnalyze.textContent`, which would erase the
  new SVG icon. The "N frames from frame K" information is not lost — the click
  handler already writes `Running (${nFrames} frames from ${startFrame})…` to the
  separate status line `#ia-last-run-status` (`:2326`). The click handler reads
  `iaFramesPerCk.value` and `_iaCurrentFrame` directly at click time, so it is
  unaffected.

### 3D — `card_inline_analysis_3d.html:80`

- Markup-only: `#ia3d-btn-analyze-range` → `class="btn-sm btn-create"`, SVG +
  `Start Analysis`, no `width:100%`.
- No JS change: the 3D button label is static; the JS only toggles
  `analyzeBtn.disabled` (sibling gating and run state), never its text/content,
  so the icon is safe.

## Change 2 — Initialize-analysis-file button states

### 2D — single video (`inline_analysis_player.js:2403`, `_iaRefreshInitFileBtn`)

Two states, driven by the existing `/dlc/project/analysis-file/status` check:

| File exists | Button | Label |
|-------------|--------|-------|
| no (or no video selected) | enabled (disabled if no video) | `○ Initialize analysis file` |
| yes | **disabled** | `Analysis file exist` |

Only the ready-state wording changes (`"✓ Analysis file ready"` →
`"Analysis file exist"`); the button is already set `disabled = true` in that
state today. No other behavior changes.

### 3D — stereo pair (`inline_analysis_3d.js:3465`, `_refreshInitFileBtn`)

Detection uses the existing per-camera `_initStatus()` results — `a` (cam0) and
`b` (cam1, the resolved sibling). Partial-state messaging only applies when a
sibling actually resolved (`_siblingPath` truthy); otherwise today's single-cam
behavior is preserved. Messages are written to the existing note line
`#ia3d-init-file-status`.

| cam0 (`a`) | cam1 (`b`) | Button | Label | Note (`#ia3d-init-file-status`) |
|------------|------------|--------|-------|---------------------------------|
| no video selected | — | disabled | (unchanged) | (cleared) |
| ✓ | ✓ | **disabled** | `Analysis files exist` | (cleared) |
| ✗ | ✗ | enabled | `○ Initialize analysis files (both cameras)` | (cleared) |
| ✓ | ✗ | **enabled** | `○ Initialize cam1 analysis file` | `cam0 already has an analysis file — Initialize will generate cam1 only.` |
| ✗ | ✓ | **enabled** | `○ Initialize cam0 analysis file` | `cam1 already has an analysis file — Initialize will generate cam0 only.` |

The click handler (`inline_analysis_3d.js:3486`) needs **no change**: it calls
`_initOne(cam0)` and `_initOne(_siblingPath)`, and `_initOne` already treats HTTP
409 ("already initialized") as success. Clicking in a partial state therefore
re-confirms the camera that already has a file and generates only the missing
one; `_refreshInitFileBtn` then re-runs and transitions the row to the "both
exist" state.

Camera labels use `cam0` / `cam1`, matching the existing UI convention (the
post-click result line already prints `cam0 ✓ · cam1 ✓`).

## Testing

Both modules already have button-wiring guard tests (see recent commits, e.g.
`e9d2e11` for the 3D init button). Keep these green and extend them where they
already cover these buttons to assert:

- The analyze button carries `btn-create` and the label `Start Analysis`.
- 2D init button: disabled + `Analysis file exist` when the status endpoint
  reports `initialized: true`.
- 3D init button: the three-way state table above — in particular the partial
  case (one camera initialized) leaves the button **enabled** and writes the
  correct "will generate camN only" note.

## Out of scope

- The Init button's own width/styling (unchanged — only the Analyze button is
  restyled).
- The no-sibling 3D edge case (keeps current behavior).
- Any server/endpoint changes — all four endpoints used already exist.
