# DLC-3D Frame Labeler — Sync Frame (Side-by-Side Multi-Cam) Design

**Date:** 2026-05-01
**Module:** `dlc-3D`
**Scope:** Front-end only. No new server endpoints, no Python changes, no Docker changes.

---

## Goal

Add a "Sync Frame" mode to the dlc-3D Frame Labeler card. When enabled, the labeler displays the primary frame side-by-side with its matching sibling frames from other cameras. Each tile supports the full body-part labeling toolset; the focused tile receives all input. All controls (zoom, marker size, show-names, save, clear, delete, keyboard shortcuts, frame nav) are shared and operate on the focused tile (or globally where appropriate).

The feature is dlc-3D-specific. The main webapp's Frame Labeler is untouched.

## Architectural choice — fork the partial and JS

The dlc-3D module owns its own copy of the Frame Labeler partial and JS. The main webapp's `partials/card_frame_labeler.html` and `static/js/frame_labeler.js` are not modified. Override is achieved through Flask blueprint template resolution: the dlc-3D blueprint's `templates/` directory is searched before the main app's, so dropping `partials/card_frame_labeler.html` into `dlc-3D/src/templates/partials/` shadows the main partial only when rendering pages from the dlc-3D blueprint.

**Tradeoff (accepted):** ~1334 lines of JS are duplicated. Future bug-fixes in the main labeler do not propagate automatically.

## File layout

| File | Action | Purpose |
|------|--------|---------|
| `dlc-3D/src/templates/partials/card_frame_labeler.html` | **Create** (forked copy) | Shadows the main partial when rendered from dlc_3d.html. All `fl-*` IDs renamed to `fl3d-*`. Adds `#fl3d-sync-frame` checkbox in the marker-display row. Replaces the single `<canvas>` with a `<div class="fl3d-canvas-row" id="fl3d-canvas-row">` flex container. |
| `dlc-3D/src/static/frame_labeler_3d.js` | **Create** (forked copy) | Forked from the main `frame_labeler.js`. All IDs and CSS class names retargeted to `fl3d-*`. Adds sync-frame state, sibling tile rendering, focus management, pair map. |
| `dlc-3D/src/static/dlc_3d.css` | **Modify** | Add `.fl3d-canvas-row`, `.fl3d-tile`, `.fl3d-tile.focused`, `.fl3d-tile-label`, `.fl3d-tile-canvas`, `.fl3d-tile-empty`. |
| `dlc-3D/src/templates/dlc_3d.html` | **Modify** | Add `<script type="module" src="…/frame_labeler_3d.js">` to `{% block scripts %}`. The existing `{% include "partials/card_frame_labeler.html" %}` resolves to the dlc-3D-local partial because the blueprint's loader is consulted first; verify in implementation. |

The dlc-3D Dockerfile already inherits the main webapp image and overlays `src/`, so no Docker changes are needed. Restarting the dlc-3D container picks up the forked JS and template via the mounted overlay.

## Data model — client-side state

Added to the forked JS (in-memory, session-only — no localStorage):

```js
_fl3dSyncOn        // boolean, sync-frame checkbox state
_fl3dPairMap       // Map<frameNumber, Array<{cam, fname, order}>>
_fl3dCamSet        // Array<int>, sorted cam indices present in the session
_fl3dPrimaryCam    // int, the cam the user originally selected
_fl3dFocusedCam    // int, currently focused tile (receives input)
_fl3dHoveredCam    // int|null, tile currently under the cursor
_fl3dFrameNumbers  // Array<int>, sorted unique frame numbers (nav axis when sync ON)
_fl3dFrameNumIdx   // int, index into _fl3dFrameNumbers
```

Existing labeler state (`_flLabels`, `_flBodyparts`, `_flSelectedBp`, `_flMarkerRadius`, `_flShowNames`, `_flZoom`, `_flHidden`, `_flDirty`) is reused unchanged. Labels remain keyed by full frame filename, so multi-cam frames coexist as separate rows in the same `CollectedData_<scorer>.csv` (existing DLC-expected layout).

## Pair-map build (filename parsing)

Runs whenever the session's frame list refreshes (`_flLoadFrames`):

```js
const RE = /^img_cam(\d+)_(\d{4})_(\d+)\.png$/;
_fl3dPairMap = new Map();
const camSet = new Set();
for (const fname of _flFrames) {
  const m = RE.exec(fname); if (!m) continue;
  const cam = +m[1], order = +m[2], frame = +m[3];
  camSet.add(cam);
  if (!_fl3dPairMap.has(frame)) _fl3dPairMap.set(frame, []);
  _fl3dPairMap.get(frame).push({ cam, fname, order });
}
_fl3dCamSet = [...camSet].sort((a, b) => a - b);
_fl3dFrameNumbers = [..._fl3dPairMap.keys()].sort((a, b) => a - b);
```

Non-conforming filenames are silently skipped. If `_fl3dCamSet.length < 2`, the Sync Frame checkbox is hidden.

## Navigation axis

| Sync state | Nav axis | Step semantics |
|------------|----------|----------------|
| OFF | `_flFrames` (existing) | One step = next file in folder, regardless of cam. |
| ON  | `_fl3dFrameNumbers` | One step = next unique frame number. All tiles re-resolve simultaneously to whatever cams have a frame at that frame number; cams that don't get an empty placeholder. |

This guarantees lock-step movement even when cam0 and cam1 have unequal frame counts (the OM-2 fixture has exactly this situation).

## DOM structure

### Marker-display row addition

Inserted between Marker size and Show names in the forked partial:

```html
<label style="display:flex;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim);cursor:pointer;user-select:none">
  <input type="checkbox" id="fl3d-sync-frame" style="accent-color:var(--accent)">
  Sync Frame
</label>
```

The label container is hidden via `style="display:none"` initially and shown by JS only when `_fl3dCamSet.length >= 2`.

### Canvas wrapper

```html
<div class="fl3d-canvas-row" id="fl3d-canvas-row">
  <!-- one tile per cam in _fl3dCamSet, generated/managed by JS -->
  <div class="fl3d-tile focused" data-cam="0" data-fname="img_cam0_0000_30281.png">
    <div class="fl3d-tile-label">cam0</div>
    <canvas class="fl3d-tile-canvas" data-cam="0" data-fname="img_cam0_0000_30281.png"></canvas>
    <div class="fl3d-tile-empty hidden"></div>
  </div>
  <!-- cam1, cam2, … added on sync-on -->
</div>
```

When sync is OFF, the row contains exactly one tile (the focused cam's). When sync is ON, JS appends one tile per other cam in `_fl3dCamSet`; on sync-off, sibling tiles are removed.

### CSS

```css
.fl3d-canvas-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
.fl3d-tile {
  flex: 1 1 0;
  min-width: 0;
  border: 2px solid var(--border);
  border-radius: 6px;
  padding: 4px;
  position: relative;
  cursor: pointer;
  box-sizing: border-box;
}
.fl3d-tile.focused {
  border-color: var(--accent);
}
.fl3d-tile-label {
  font-size: .7rem;
  color: var(--text-dim);
  margin-bottom: 2px;
  font-family: var(--mono);
}
.fl3d-tile-canvas {
  display: block;
  width: 100%;
  height: auto;
}
.fl3d-tile-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-2);
  color: var(--text-dim);
  aspect-ratio: 16 / 9;
  font-size: .82rem;
  text-align: center;
  padding: .5rem;
}
```

### Overflow / break-out

Repurposes the existing `_flFitCanvas` wrapper-margin trick (currently in `frame_labeler.js:871-898`) at the *row* level when sync is ON:

- `baseW = card inner width` (card content area at 100% zoom).
- `targetRowW = min(baseW * (zoom/100), window.innerWidth - 32)`.
- Each tile's `<canvas>` is sized at `(targetRowW - totalGaps) / N` wide, height preserved by image aspect ratio.
- Wrapper element gets `width: targetRowW; margin-left: -(targetRowW - baseW) / 2` when `targetRowW > baseW`.
- When viewport cannot fit `N` tiles at minimum width, tiles shrink instead of overflow-scrolling. No horizontal scrollbar appears.

## Focus and input routing

Exactly one tile is focused at any time when sync is ON. State lives in `_fl3dFocusedCam`. On sync-on, focus = `_fl3dPrimaryCam`. Click any tile (canvas or wrapper) → `_fl3dFocusedCam = tile.dataset.cam`, re-render to swap `.focused` class, refresh chip status / label count from focused tile's frame.

| Action | Today (single-canvas) | Forked (sync-aware) |
|--------|------------------------|---------------------|
| Marker placement (canvas click) | writes `_flLabels[currentFname][bp]` | writes `_flLabels[focusedTile.fname][bp]` |
| Marker delete (right-click / Backspace / Del) | same | reads focused tile's fname |
| W/A/S/D nudge | gated by `_flCursorInCanvas` | gated by `_fl3dHoveredCam === _fl3dFocusedCam` |
| Tab / Shift+Tab (next/prev bp) | unchanged | unchanged (chip selection is global) |
| Space (toggle visibility) | toggles selected bp on current frame | toggles on focused tile's frame |
| Clear Frame button | clears current fname | clears focused tile's fname only |
| Delete Frame button | deletes one img + CSV row | deletes focused tile's fname only |
| Save Labels | flushes all dirty frames | flushes all dirty frames (unchanged) |

Clicking an empty placeholder tile sets focus (border flips), but a subsequent canvas click on it is a no-op (no image to label against). Useful for navigating to a frame number where the cam *does* have a frame.

Hover-gated keyboard shortcuts (W/A/S/D etc.) only fire when the cursor is inside the **focused** tile. Each tile sets `_fl3dHoveredCam` on `mouseenter` / clears on `mouseleave`. Prevents accidentally nudging cam0's marker while reviewing cam1.

Shared state, unchanged on toggle:
- Selected body-part chip (`_flSelectedBp`) — one chip selected, applies to whichever tile receives the click.
- Marker size, viewer-size zoom, show-names — apply to all tiles uniformly.
- Frame nav buttons (prev/next/keyboard ←/→) — advance the frame-number axis; all tiles re-resolve simultaneously.
- ML pre-labeling and TAPNet panels — completely untouched. They operate on the session folder as a whole, so sequential per-cam frames are processed naturally; the resulting labels show up in their respective tiles after refresh.

## Toggle behavior

### Sync-on transition

1. Read current focused frame's filename → parse cam + frame_number.
2. Build `_fl3dPairMap` and `_fl3dCamSet` from `_flFrames`.
3. If `_fl3dCamSet.length < 2`: log warning, uncheck the box, show a one-line status under the row (`"Sync Frame needs at least 2 cams in this folder."`). Do not proceed.
4. `_fl3dPrimaryCam = _fl3dFocusedCam = currentCam`.
5. Find current frame_number's index in `_fl3dFrameNumbers` → `_fl3dFrameNumIdx`.
6. Append sibling tiles to `#fl3d-canvas-row` for every cam in `_fl3dCamSet` except the focused one.
7. Load images for each tile (or render empty placeholder when missing), re-fit row.
8. Set `_fl3dSyncOn = true`.

### Sync-off transition

1. Remove all sibling tiles from the row, leaving only the focused cam's tile.
2. Re-resolve `_flFrameIdx` so prev/next walks `_flFrames` again, starting at the focused tile's current fname.
3. Re-fit the canvas to single-tile width.
4. Set `_fl3dSyncOn = false`.

## Edge cases

- **Single-cam folder.** Checkbox hidden. Recomputed on every frame-list refresh.
- **Folder gains/loses cams during session** (e.g., user extracts new sibling frames mid-labeling and refreshes). Pair map rebuilds on `_flLoadFrames`; tile row re-renders if sync is on.
- **Save while sync is on.** No special-case — `_flLabels` is keyed by filename; dirty frames flush regardless of which tile they came from.
- **TAPNet / ML pre-label runs while sync is on.** They operate on the session folder; both cams' frames are processed in sequence. Pair map and tiles re-render after the run (existing post-run refresh path).
- **Window resize.** Existing `ResizeObserver` on the card triggers row-fit logic.
- **Zoom slider while sync is on.** Operates on row width per the overflow rules above. Re-fits all tiles equally.

## Test debug surface

The forked JS exposes a small read-only debug object on `window.__fl3d` for assertion-friendly testing:

```js
window.__fl3d = {
  syncOn,
  focusedCam,
  primaryCam,
  hoveredCam,
  camSet,            // sorted array
  pairMapSize,
  frameNumberIdx,
  selectedBp,
  markerRadius,
  showNames,
  zoom,
  dirtyFrames,       // Array<string>
  labels,            // reference to _flLabels (read-only intent)
};
```

Each tile root carries `[data-cam]`, `[data-fname]`, `class="fl3d-tile [focused]"`. The tile's `<canvas>` mirrors `[data-cam]` and `[data-fname]` for direct selector queries. These attributes are the primary assertion surface; `window.__fl3d` is for cases where DOM isn't enough (dirty-set inspection, cam-set ordering verification).

## Testing — Playwright + unit

### Fixture

- **DLC project (in-app path):** `data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07`
- **Session folder under test:** `OM-2_20260424`
- **On-disk root resolves to:** `/home/sam/Parra-Lab-Data-NAS/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07/labeled-data/OM-2_20260424/` (NAS mount). Folder contains 240 `img_cam{0,1}_*_*.png` files plus `CollectedData_Ali.csv` and `calibration.toml`.

### Pre-flight skip

Each Playwright test's `beforeEach` makes a single GET to `/dlc-3d/labeled-stems` and confirms `OM-2_20260424` is listed with at least 2 cams. If not, `test.describe.skip` the entire suite with a clear message: `"Skipping: OM-2_20260424 not present or has no multi-cam frames extracted."`.

### Test file & harness

- `dlc-3D/tests/e2e/sync_frame.spec.ts` — Playwright suite.
- `dlc-3D/tests/e2e/playwright.config.ts` — `baseURL: http://localhost:5000`, headless Chromium project.
- `dlc-3D/tests/unit/pair_map.test.js` — pair-map builder unit tests (use `node:test` if no other JS runner exists in dlc-3D; otherwise match the existing one).

### Test groups

**A. Visibility gate**
1. Sync checkbox visible when `camSet.length >= 2`.
2. Sync checkbox hidden when `camSet.length < 2`. (Use any single-cam or non-`img_cam` folder; `test.fixme` with note if no such fixture is available.)

**B. Initial state with sync OFF**
1. `#fl3d-canvas-row` has exactly one child `.fl3d-tile`.
2. Sole tile has `.focused`; its `[data-cam]` matches the cam of the first frame in `_flFrames`.
3. Tile width ≈ card inner width at zoom 100% (within 1px tolerance).

**C. Sync ON transition**
1. Click `#fl3d-sync-frame` → `#fl3d-canvas-row` child count === `window.__fl3d.camSet.length` (== 2 for OM-2).
2. Tiles ordered ascending by `[data-cam]`.
3. Exactly one `.fl3d-tile.focused`; its `[data-cam]` === `window.__fl3d.primaryCam` (lowest cam index).
4. Computed `border-color` of `.focused` matches `--accent` CSS var; unfocused tiles match `--border`.
5. Every tile either has `<canvas>` with non-empty `data-fname` and `naturalWidth > 0`, or has `.fl3d-tile-empty` visible with text matching `/^No frame extracted for cam\d+ @ \d+$/`.

**D. Focus switching**
1. Click an unfocused tile → it gains `.focused`; previous loses it. Border colors flip per C.4.
2. Clicking the focused tile is a no-op (no class flicker; verify via `MutationObserver` count).
3. `window.__fl3d.focusedCam` reflects the click target's `[data-cam]`.

**E. Lock-step navigation**
1. Capture `[data-fname]` for every tile. Click `#fl3d-btn-next` (or send `→`). All tiles' `data-fname` advances; their parsed frame_number == previous frame_number's successor.
2. Click `#fl3d-btn-prev` → returns to original frame_numbers.
3. Navigate to a frame_number where one cam is missing → that tile shows `.fl3d-tile-empty`; the other shows a real canvas. Click the empty tile → it gains focus, but a subsequent canvas click on it is a no-op (marker count unchanged).

**F. Marker placement & input routing (focused tile only)**
1. Select the first body-part chip. Click center of focused tile's canvas → marker added on focused tile only; sibling marker count unchanged. Verified via `window.__fl3d.dirtyFrames` and `window.__fl3d.labels[focusedFname][bp]`.
2. Switch focus to sibling tile, click its canvas → marker added on sibling's frame; original tile's markers unchanged.
3. Right-click focused tile's canvas → marker for selected bp removed on focused frame only.
4. Press `Backspace` while cursor is **inside** focused tile → marker removed. While cursor is outside any tile → no-op.
5. Press `W`/`A`/`S`/`D` while hovering focused tile → focused-tile marker shifts by 1px in image-space (assert via `labels[fname][bp]` deltas).
6. Press `Shift+W` → 10px shift.
7. Press `W` while hovering a sibling (unfocused) tile → no-op (focused tile's marker unchanged, sibling unchanged).
8. Press `Tab` → next chip highlighted; selection is global (`window.__fl3d.selectedBp`).
9. Press `Space` → focused-tile marker visibility toggles; chip status badge updates; sibling unchanged.

**G. Shared display controls**
1. Drag `#fl3d-zoom` to 200% → row width grows; `marginLeft` becomes negative; each tile's canvas width grows proportionally.
2. Drag `#fl3d-zoom` to 50% → row width shrinks below card inner width; no negative margin.
3. Drag `#fl3d-marker-size` from 4 → 12 → `window.__fl3d.markerRadius` updates; both tiles re-rendered.
4. Toggle `#fl3d-show-names` off → both tiles re-render without name labels.

**H. Save round-trip (single CSV, multi-cam dirty frames)**
1. Navigate to a frame_number where both cams have a tile. Place a marker on cam0 (focused), switch focus, place a marker on cam1. `window.__fl3d.dirtyFrames` contains both filenames.
2. Click `#fl3d-btn-save` → wait for `#fl3d-save-status` success. `dirtyFrames` becomes empty.
3. Hard-reload the page; reopen Frame Labeler at the same session; navigate back with sync ON → both markers persist on their respective tiles, read from the same `CollectedData_Ali.csv`.
4. Cleanup: remove the test markers via right-click + save again. (Idempotency required; gate the destructive write behind env flag `FL3D_E2E_WRITE=1` if there's any concern about polluting the fixture.)

**I. Clear / Delete frame (focused-tile only)**
1. With markers placed on both cams, double-click `#fl3d-btn-clear-frame` → focused tile loses its markers; sibling tile's markers unchanged.
2. (Behind `FL3D_E2E_WRITE=1` — destructive.) Double-click `#fl3d-btn-delete-frame` → focused tile's image returns 404 on subsequent fetch; sibling tile still shows.

**J. Sync OFF transition**
1. With sync ON and focus on cam1, uncheck `#fl3d-sync-frame` → row has exactly 1 child; remaining tile's `[data-cam]` === 1 (focused cam preserved); `[data-fname]` matches what was on cam1 at toggle time.
2. Prev/next now walks `_flFrames`: pressing next advances `data-fname` to the next entry in the cam1-only filtered list.

**K. Window resize**
1. With sync ON at zoom 100%, `page.setViewportSize({ width: 800, height: 720 })`. `#fl3d-canvas-row` width ≤ 800 - 32; tiles shrink; no horizontal scrollbar (`document.documentElement.scrollWidth === clientWidth`).
2. Resize back to wider → tiles re-fit larger.

**L. Pair-map rebuild on refresh**
1. Click `#fl3d-refresh-btn` while sync is ON → `window.__fl3d.pairMapSize` re-counted; tile row stays consistent; focused cam preserved.

**M. Non-regression — ML & TAPNet panels untouched**
1. Both panels render and their checkboxes still toggle their option blocks open/closed (no JS console errors from sync mode interfering). Don't run actual jobs in e2e — UI smoke only.

**N. Pair-map unit tests** (`dlc-3D/tests/unit/pair_map.test.js`):
1. Empty `_flFrames` → empty pair map, empty cam set.
2. Single cam (5 `img_cam0_*` files) → cam set `[0]`, pair map size 5.
3. Two cams equal counts, all matching frame numbers → pair map size N, every entry length 2.
4. Two cams mismatched (3 cam0, 2 cam1, 1 unmatched frame number) → pair map size 3, one entry length 1.
5. Three cams sparse → cam set `[0, 1, 2]`; pair map keys are the union; entries vary in length.
6. Non-conforming filenames mixed in (`img0001.png`) silently skipped.

### Run commands

```bash
# Stack must be running (from main webapp dir):
docker compose up -d flask dlc-3d

# E2E:
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
npm install
npx playwright test tests/e2e/sync_frame.spec.ts

# Unit:
node --test tests/unit/pair_map.test.js
```

## Out of scope (deferred)

- "Extract sibling now" button on empty placeholder tiles.
- Persistence of the Sync Frame checkbox state across reloads (matches current behavior of all other display controls).
- Per-tile independent frame index (siblings are always lock-stepped to the focused-cam frame number).
- Side-by-side ML pre-labeling controls (the existing single-flow ML/TAPNet panels remain primary-cam-agnostic and operate over the whole session folder).
- Visual badges or per-tile "labeled" status indicators (could be added later by reading `dirtyFrames` + `labels` per tile).
