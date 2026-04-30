# DLC-3D Extract Card Redesign — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Redesign `card_3d_extract.html` to match the visual style and UX flow of the main webapp's `card_frame_extractor.html`. Single-column layout: source section on top, dual-camera player below, extract controls at the bottom. The card opens via the existing "Extract Frames" button in the DLC Project card.

---

## Section 1: Card Trigger

`dlc_3d.js` removes its own session-bar button injection and instead attaches a listener to `btn-open-frame-extractor` (already in the DOM via `card_dlc_project.html`). Clicking "Extract Frames" in the DLC Project card calls `_openCard()` which hides all other cards and shows `#dlc-3d-extract-card`. The Close button inside the card calls `_closeCard()` to restore the grid.

`_cardsWereVisible` snapshot/restore logic is removed — the same simple show/hide pattern used by every other card in `main.js` is sufficient.

---

## Section 2: `card_3d_extract.html` Structure

Single-column card following the exact `card_frame_extractor.html` pattern.

### 2a. Card header
Identical to current: `<h2>3D Frame Extractor</h2>` + Close `btn-sm` button on the right.

### 2b. Source section (always visible)
No tabs — one source only.

```html
<div id="dlc3d-source-section">
  <label style="display:block;margin-bottom:.5rem">DLC Project</label>
  <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.8rem">
    <button class="btn-sm" id="dlc3d-btn-open-project">Browse Server</button>
    <span id="dlc3d-project-path" ...>No project loaded</span>
    <button class="btn-sm" id="dlc3d-btn-rescan" style="display:none">↺ Rescan</button>
  </div>

  <!-- Session / camera list — styled like fe-video-list -->
  <div id="dlc3d-video-list" class="fe-video-list" style="display:none">
    <!-- Populated by dlc_3d.js: session headers + cam rows -->
  </div>
  <p id="dlc3d-session-empty" class="explorer-empty">Load a project to see sessions.</p>
</div>
```

Session list rendering (JS side): sessions are non-clickable `<div class="fe-video-group-header">` labels; each camera beneath is a `<div class="fe-video-item">` row with the camera stem name and a sibling badge if a paired camera exists. Clicking a cam row loads that video pair.

### 2c. Player section (hidden until camera row selected)
```html
<div id="dlc3d-player-section" style="display:none">

  <!-- Dual cameras side-by-side -->
  <div id="cam-displays" style="display:flex;gap:.5rem;margin-bottom:.5rem">
    <div class="cam-wrap" id="cam1-wrap" style="flex:1;min-width:0">
      <div class="cam-label" id="cam1-label">cam0</div>
      <div class="cam-frame-wrap" id="cam1-frame-wrap">
        <img id="ep-frame" src="" alt="" style="display:none;width:100%">
        <span id="no-video-msg">Select a camera from the list above.</span>
      </div>
    </div>
    <div class="cam-wrap" id="ep-cam2-wrap" style="flex:1;min-width:0;display:none">
      <div class="cam-label" id="cam2-label">cam1</div>
      <div class="cam-frame-wrap">
        <img id="ep-cam2-frame" src="" alt="" style="width:100%">
      </div>
    </div>
  </div>

  <!-- Controls — matching fe-controls pattern -->
  <div class="fe-controls">
    <button id="ep-skip-start" class="btn-sm fe-ctrl-btn" title="Jump to start">⏮</button>
    <button id="ep-step-back" class="btn-sm fe-ctrl-btn" title="Previous frame">◀◀</button>
    <button id="ep-play"      class="btn-sm fe-ctrl-btn" title="Play / pause">▶</button>
    <button id="ep-step-fwd"  class="btn-sm fe-ctrl-btn" title="Next frame">▶▶</button>
    <button id="ep-skip-end"  class="btn-sm fe-ctrl-btn" title="Jump to end">⏭</button>
    <input type="number" id="ep-step" value="10" min="1" max="9999"
      title="Skip N frames" style="width:72px;..." />
    <span class="fe-frame-counter">Frame <span id="ep-frame-num">—</span> / <span id="ep-frame-total">—</span></span>
  </div>

  <!-- Seek slider -->
  <input type="range" id="ep-seek" class="fe-seek" min="0" max="0" value="0">

  <!-- Sync cam row -->
  <div style="display:flex;align-items:center;gap:1rem;margin:.4rem 0;font-size:.78rem">
    <label class="toggle">
      <input type="checkbox" id="ep-sync-cam"> Sync Cam
    </label>
    <label class="toggle" id="ep-extract-sibling-label" style="display:none">
      <input type="checkbox" id="ep-extract-sibling" checked> Extract Sibling
    </label>
  </div>

  <!-- Extract section — matching main webapp layout -->
  <div style="display:flex;flex-direction:column;gap:.5rem;margin-top:.75rem">
    <div style="display:flex;align-items:center;gap:.8rem">
      <button id="ep-extract-btn" class="btn-sm btn-create" disabled
        style="flex:1;justify-content:center;padding:.5rem 1rem">
        Extract Frame
      </button>
      <span id="extract-count" class="fe-extract-count">0 frames saved</span>
    </div>
  </div>

  <span id="extract-status" class="fe-extract-status" style="font-size:.75rem;color:var(--text-dim);min-height:1.1em;display:block;margin-top:.3rem"></span>

  <!-- Labeled frames chip list -->
  <div id="labeled-wrap" style="display:none;border-top:1px solid var(--border);padding-top:.4rem;margin-top:.4rem">
    <div id="labeled-header" style="font-size:.75rem;font-weight:600;margin-bottom:.25rem">
      Extracted frames: <span id="labeled-count">0</span>
    </div>
    <div id="labeled-list" style="font-size:.72rem;color:var(--text-dim);max-height:90px;overflow-y:auto;display:flex;flex-wrap:wrap;gap:.2rem"></div>
  </div>

</div><!-- /dlc3d-player-section -->
```

### 2d. Filesystem browser modal
Unchanged — same fixed-overlay `#dlc3d-browser-modal` structure.

---

## Section 3: JS Changes — `dlc_3d.js`

### Removed
- `DOMContentLoaded` injection of "3D Frame Extractor" button into `#dlc-bar .session-btns`
- `_cardsWereVisible` snapshot/restore pattern in `_openCard` / `_closeCard`

### Added / Changed
- Wire `document.getElementById("btn-open-frame-extractor")` → `_openCard()` in `DOMContentLoaded`
- `_openCard()`: `document.querySelectorAll(".card:not(.hidden)").forEach(c => c.classList.add("hidden"))` then remove `hidden` from `#dlc-3d-extract-card`
- `_closeCard()`: `document.getElementById("dlc-3d-extract-card").classList.add("hidden")`
- **Session list render** (`_renderSessions(sessions)`): builds `fe-video-list` markup — `<div class="fe-video-group-header">` per session key, `<div class="fe-video-item" data-video="..." data-session="...">` per camera. Adds sibling badge if session has >1 camera. Attaches click → `_selectCamera(videoRel, sessionKey)`.
- **`_selectCamera(videoRel, sessionKey)`**: replaces the old per-cam-row click logic; calls `_loadVideo(videoRel)` and shows `#dlc3d-player-section`.
- **`_loadProject(path)`**: shows `#dlc3d-video-list`, hides `#dlc3d-session-empty`, calls `_renderSessions()`.
- Remove `#dlc3d-session-panel` / `#dlc3d-session-empty` (old sidebar) references — replaced by `#dlc3d-video-list` / `#dlc3d-session-empty` (inline list).
- `extract-count` span updated on each successful extract (mirrors `fe-extract-count` pattern).

### Unchanged
- All `enhanced_player.js` interactions (seek, play, step, sync-cam, extract)
- All `/dlc-3d/` API calls (project, frame, sibling-camera, save-frame, labeled-frames)
- Filesystem browser logic

---

## Section 4: CSS Changes — `dlc_3d.css`

### Removed
- `.dlc3d-layout` (flex-row split)
- `#dlc3d-session-panel` and all sidebar rules
- `.session-group`, `.session-header`, `.session-body`, `.cam-row`, `.clip-row`, `.cam-badge`, `.clip-section`, `.clip-header` — all old sidebar tree styles

### Added / Kept (scoped under `#dlc-3d-extract-card`)
- `#cam-displays` — `display:flex; gap:.5rem` (side-by-side cameras)
- `.cam-wrap` — `flex:1; min-width:0; overflow:hidden`
- `.cam-label` — `font-size:.75rem; color:var(--text-dim); margin-bottom:.2rem`
- `.cam-frame-wrap img` — `width:100%; display:block; height:auto`
- `.fe-controls` scoped styles (inherit from main webapp CSS, override only if needed)
- `.fe-seek` full-width rule scoped to `#dlc-3d-extract-card`
- `#dlc3d-browser-modal` fixed-overlay rules — unchanged
- `.frame-chip` — unchanged

### Card width
`#dlc-3d-extract-card { max-width: none; width: 100%; }` — kept.

---

## File Map

| Action | Path |
|--------|------|
| Replace | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Replace | `dlc-3D/src/static/dlc_3d.js` |
| Replace | `dlc-3D/src/static/dlc_3d.css` |

`enhanced_player.js`, `dlc_3d.html`, `routes.py`, `docker-compose.yml` — no changes.

---

## Testing

1. `docker compose restart dlc-3d` (live-mounted files, no rebuild)
2. Navigate to `/dlc-3d/` — DLC Project card visible
3. Click "Extract Frames" in DLC Project card — 3D Frame Extractor card opens
4. Browse Server → load a project — session/camera list appears
5. Click a camera row — player section appears, frame loads
6. Seek, step, play — frame navigation works
7. Enable Sync Cam — sibling camera appears side-by-side
8. Extract Frame — count increments, chip appears in labeled-list
9. Close card — returns to card grid
10. All 26 existing pytest tests pass: `python -m pytest tests/ -q`
