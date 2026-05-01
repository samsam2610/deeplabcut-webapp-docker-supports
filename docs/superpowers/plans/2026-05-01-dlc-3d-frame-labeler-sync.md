# DLC-3D Frame Labeler Sync-Frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Sync Frame" mode to the dlc-3D Frame Labeler that displays the primary frame side-by-side with its sibling-cam frames, with focus-aware input routing, lock-step navigation, and graceful overflow handling.

**Architecture:** Fork the main webapp's `card_frame_labeler.html` partial and `frame_labeler.js` into the dlc-3D blueprint. The blueprint's `templates/` and `static/` directories shadow the main webapp's at runtime. All `fl-*` IDs become `fl3d-*` in the fork to avoid collision. A pair-map (built client-side from filename parsing) drives sibling-tile rendering and lock-step navigation; labels remain in a single `CollectedData_<scorer>.csv`.

**Tech Stack:** Vanilla JS (ES modules), Jinja2 partial, CSS custom properties, pytest + pytest-playwright (existing harness in `dlc-3D/tests/e2e/`), `node:test` for one pure-JS unit test (no new package.json — invoke node directly).

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `dlc-3D/src/templates/partials/card_frame_labeler.html` | Forked partial; shadows main when rendered from dlc_3d.html. All IDs `fl-*` → `fl3d-*`. Adds `#fl3d-sync-frame` checkbox. Replaces single canvas with `#fl3d-canvas-row` tile-row. |
| Create | `dlc-3D/src/static/frame_labeler_3d.js` | Forked from main `frame_labeler.js`. All IDs `fl-*` → `fl3d-*`. Adds pair-map, sibling-tile rendering, focus management, sync toggle, hover-gated input, debug surface (`window.__fl3d`). |
| Modify | `dlc-3D/src/static/dlc_3d.css` | Append `.fl3d-canvas-row`, `.fl3d-tile`, `.fl3d-tile.focused`, `.fl3d-tile-label`, `.fl3d-tile-canvas`, `.fl3d-tile-empty` styles. |
| Modify | `dlc-3D/src/templates/dlc_3d.html` | Add `<script type="module" src="…/frame_labeler_3d.js">` to `{% block scripts %}`. |
| Create | `dlc-3D/tests/unit/test_pair_map.mjs` | Pure-JS unit test for the pair-map builder, runnable via `node --test`. |
| Create | `dlc-3D/tests/e2e/test_sync_frame.py` | pytest-playwright suite covering all interaction groups A–M from the spec. |
| Modify | `dlc-3D/tests/e2e/conftest.py` | Add `OM2_FIXTURE_PRESENT` session-scoped fixture (HTTP probe to skip whole module when fixture missing). |

The dlc-3D `Dockerfile` copies `src/` over the base image at build, so picking up the new files requires `docker compose build dlc-3d && docker compose up -d dlc-3d` from the main webapp dir. No Dockerfile or compose changes.

**Spec reference:** `docs/superpowers/specs/2026-05-01-dlc-3d-frame-labeler-sync.md`

---

## Task 1: Fork the partial — IDs renamed, no behavior change yet

Create `dlc-3D/src/templates/partials/card_frame_labeler.html` as a verbatim copy of `/home/sam/docker-images/deeplabcut-webapp-docker/src/templates/partials/card_frame_labeler.html`, then rename every `id="fl-..."` to `id="fl3d-..."` and every CSS class `fl-...` to `fl3d-...`. Do not yet add the Sync Frame checkbox or change the canvas structure. The page must render identically after this task (sibling tile + sync toggle land in later tasks).

**Files:**
- Create: `dlc-3D/src/templates/partials/card_frame_labeler.html`

- [ ] **Step 1: Copy the source partial**

```bash
cp /home/sam/docker-images/deeplabcut-webapp-docker/src/templates/partials/card_frame_labeler.html \
   /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_frame_labeler.html
```

- [ ] **Step 2: Rename IDs and CSS class names**

Open the new file. Run a careful global rename (text editor or `sed`) of:
- `id="fl-` → `id="fl3d-`
- `for="fl-` → `for="fl3d-`
- `class="fl-` → `class="fl3d-` and class lists that begin with `fl-` mid-attribute (e.g., `class="btn-sm fl-foo"` → `class="btn-sm fl3d-foo"`)
- `getElementById('fl-` and `querySelector('.fl-` inline references (none exist in this partial — scripts are external — but verify)

Use this command for an automated pass and then visually diff:

```bash
sed -i \
  -e 's/id="fl-/id="fl3d-/g' \
  -e 's/for="fl-/for="fl3d-/g' \
  -e 's/class="fl-/class="fl3d-/g' \
  -e 's/ fl-/ fl3d-/g' \
  /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_frame_labeler.html
```

Expected: every `fl-` token is now `fl3d-`. Quick verify:

```bash
grep -n 'fl-' /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_frame_labeler.html
```

Expected: zero matches (no remaining `fl-` tokens).

- [ ] **Step 3: Verify no Python imports / Jinja includes broke**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -c "
import sys; sys.path.insert(0, 'src')
from app import app
with app.test_client() as c:
    r = c.get('/dlc-3d/')
    print('status', r.status_code)
"
```

Expected: `status 200`. (At this point JS will reference IDs that no longer exist, but the page itself still renders. JS rename happens in Task 2.)

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_frame_labeler.html
git commit -m "feat(dlc-3d): fork frame_labeler partial with fl3d-* IDs"
```

---

## Task 2: Fork the JS — IDs renamed, no feature change yet

Copy `frame_labeler.js` to `dlc-3D/src/static/frame_labeler_3d.js`, rename all `fl-*` ID/class references to `fl3d-*`, add the script tag to `dlc_3d.html`, and verify the labeler still works end-to-end with no behavior change.

**Files:**
- Create: `dlc-3D/src/static/frame_labeler_3d.js`
- Modify: `dlc-3D/src/templates/dlc_3d.html`

- [ ] **Step 1: Copy the source JS**

```bash
cp /home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/frame_labeler.js \
   /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js
```

- [ ] **Step 2: Rename `fl-*` ID references in the JS**

```bash
sed -i \
  -e "s/'fl-/'fl3d-/g" \
  -e 's/"fl-/"fl3d-/g' \
  -e 's/getElementById("fl3d-/getElementById("fl3d-/g' \
  /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js
```

Then verify zero remaining `'fl-` or `"fl-` occurrences:

```bash
grep -nE "['\"]fl-" /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js
```

Expected: empty output.

- [ ] **Step 3: Add the script tag to dlc_3d.html**

Open `dlc-3D/src/templates/dlc_3d.html` and inside `{% block scripts %}` (after the existing `dlc_3d.js` line) add:

```html
<script type="module" src="{{ url_for('dlc_3d.static', filename='frame_labeler_3d.js') }}"></script>
```

The block should now look like:

```jinja
{% block scripts %}
{{ super() }}
<script type="module" src="{{ url_for('dlc_3d.static', filename='enhanced_player.js') }}"></script>
<script type="module" src="{{ url_for('dlc_3d.static', filename='dlc_3d.js') }}"></script>
<script type="module" src="{{ url_for('dlc_3d.static', filename='frame_labeler_3d.js') }}"></script>
{% endblock %}
```

- [ ] **Step 4: Disable the main labeler's script for dlc-3D pages**

The main webapp's `base.html` may already load `js/frame_labeler.js`. If both load, both will register listeners on now-non-existent IDs (the main script will fail-soft because `fl-*` IDs no longer exist on this page). Verify:

```bash
grep -n "frame_labeler" /home/sam/docker-images/deeplabcut-webapp-docker/src/templates/base.html
```

If the main labeler is loaded unconditionally in base.html and we want to suppress noise, the cleanest path is to *let it load* — every `getElementById('fl-…')` returns `null` and its `addEventListener` calls would throw, so wrap them defensively. However, the existing main labeler already guards with `if (!flStemSelect) return;` style early returns at the top of its IIFE. Confirm this:

```bash
head -50 /home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/frame_labeler.js | grep -n 'if (!fl\|return;'
```

If guards exist (early return when an `fl-*` element is missing), no further action. If they don't, add a single guard at the top of the **forked** file's IIFE entry to bail out if `fl3d-stem-select` is missing (defensive against the partial being absent on non-dlc-3d pages — though it never will be):

```js
if (!document.getElementById("fl3d-stem-select")) return;
```

- [ ] **Step 5: Rebuild and smoke-test the container**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
docker compose logs --tail=20 dlc-3d
```

Expected: dlc-3d container starts cleanly, gunicorn worker bound on `:5050`.

Then in browser:
1. Open `http://localhost:5000/dlc-3d/`.
2. Open Frame Labeler card (existing button — locate via `Open Frame Labeler` text).
3. Select any session from `#fl3d-stem-select`.
4. Confirm: stem dropdown populates, single canvas appears, body-part chips render, prev/next nav works, marker placement works.

If anything is broken: open browser devtools console and look for `Cannot read properties of null (reading 'addEventListener')` errors — those indicate an ID rename was missed. Grep the JS for the dangling token and fix.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js dlc-3D/src/templates/dlc_3d.html
git commit -m "feat(dlc-3d): fork frame_labeler JS with fl3d-* IDs and wire it up"
```

---

## Task 3: Pair-map builder — pure function + unit tests (TDD)

Add a pair-map builder function to the forked JS. Drive its design from a `node:test` unit test that runs without a browser.

**Files:**
- Create: `dlc-3D/tests/unit/test_pair_map.mjs`
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`

- [ ] **Step 1: Write the failing unit test**

```bash
mkdir -p /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/tests/unit
```

Create `dlc-3D/tests/unit/test_pair_map.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { buildPairMap } from "../../src/static/frame_labeler_3d.js";

test("empty input → empty pair map and cam set", () => {
  const out = buildPairMap([]);
  assert.equal(out.pairMap.size, 0);
  assert.deepEqual(out.camSet, []);
  assert.deepEqual(out.frameNumbers, []);
});

test("single cam, 5 frames", () => {
  const frames = [
    "img_cam0_0000_30281.png",
    "img_cam0_0001_30287.png",
    "img_cam0_0002_30331.png",
    "img_cam0_0003_30341.png",
    "img_cam0_0004_09074.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0]);
  assert.equal(out.pairMap.size, 5);
  assert.equal(out.pairMap.get(30281).length, 1);
  assert.equal(out.pairMap.get(30281)[0].cam, 0);
  assert.equal(out.pairMap.get(30281)[0].fname, "img_cam0_0000_30281.png");
  assert.deepEqual(out.frameNumbers, [9074, 30281, 30287, 30331, 30341]);
});

test("two cams equal counts, all matching frame numbers", () => {
  const frames = [
    "img_cam0_0000_100.png", "img_cam0_0001_200.png", "img_cam0_0002_300.png",
    "img_cam1_0000_100.png", "img_cam1_0001_200.png", "img_cam1_0002_300.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1]);
  assert.equal(out.pairMap.size, 3);
  for (const fnum of [100, 200, 300]) {
    assert.equal(out.pairMap.get(fnum).length, 2);
  }
});

test("two cams mismatched (3 cam0 + 2 cam1, 1 unmatched)", () => {
  const frames = [
    "img_cam0_0000_100.png", "img_cam0_0001_200.png", "img_cam0_0002_300.png",
    "img_cam1_0000_100.png", "img_cam1_0001_200.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1]);
  assert.equal(out.pairMap.size, 3);
  assert.equal(out.pairMap.get(100).length, 2);
  assert.equal(out.pairMap.get(200).length, 2);
  assert.equal(out.pairMap.get(300).length, 1);
  assert.equal(out.pairMap.get(300)[0].cam, 0);
});

test("three cams sparse", () => {
  const frames = [
    "img_cam0_0000_100.png", "img_cam0_0001_200.png",
    "img_cam1_0000_200.png",
    "img_cam2_0000_100.png", "img_cam2_0001_300.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1, 2]);
  assert.deepEqual(out.frameNumbers, [100, 200, 300]);
  assert.equal(out.pairMap.get(100).length, 2);
  assert.equal(out.pairMap.get(200).length, 2);
  assert.equal(out.pairMap.get(300).length, 1);
});

test("non-conforming filenames silently skipped", () => {
  const frames = [
    "img_cam0_0000_100.png",
    "img0001.png",            // legacy single-cam style
    "thumbs.db",
    "img_cam1_0000_100.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1]);
  assert.equal(out.pairMap.size, 1);
  assert.equal(out.pairMap.get(100).length, 2);
});
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_pair_map.mjs
```

Expected: import error or `buildPairMap is not a function` — fails at module load because the export doesn't exist yet.

- [ ] **Step 3: Add the exported builder to the forked JS**

The forked `frame_labeler_3d.js` is currently an IIFE. Convert it to an ES module that *also* exports the pair-map builder. Add this block at the **top** of `dlc-3D/src/static/frame_labeler_3d.js` (above the existing IIFE wrapper if any), or — simpler — leave the IIFE and add a separate top-level `export`:

```js
export const FL3D_FRAME_RE = /^img_cam(\d+)_(\d{4})_(\d+)\.png$/;

export function buildPairMap(frames) {
  const pairMap = new Map();
  const camSet  = new Set();
  for (const fname of frames) {
    const m = FL3D_FRAME_RE.exec(fname);
    if (!m) continue;
    const cam = +m[1], order = +m[2], frame = +m[3];
    camSet.add(cam);
    if (!pairMap.has(frame)) pairMap.set(frame, []);
    pairMap.get(frame).push({ cam, fname, order });
  }
  return {
    pairMap,
    camSet: [...camSet].sort((a, b) => a - b),
    frameNumbers: [...pairMap.keys()].sort((a, b) => a - b),
  };
}
```

The script tag in `dlc_3d.html` already uses `type="module"`, so top-level `export` is valid. The browser-side IIFE that runs on DOMContentLoaded continues to work alongside the export.

- [ ] **Step 4: Run the test and verify it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_pair_map.mjs
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js dlc-3D/tests/unit/test_pair_map.mjs
git commit -m "feat(dlc-3d): add pair-map builder with unit tests"
```

---

## Task 4: Add Sync Frame checkbox + tile-row DOM (sync OFF still works)

Restructure the canvas wrapper to a `#fl3d-canvas-row` flex container with a single `.fl3d-tile`. Add the (initially hidden) `#fl3d-sync-frame` checkbox to the marker-display row. Wire visibility of the checkbox to `_fl3dCamSet.length >= 2`. No sync behavior yet — feature stays functionally identical.

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_frame_labeler.html`
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`
- Modify: `dlc-3D/src/static/dlc_3d.css`

- [ ] **Step 1: Add checkbox to marker-display row in the partial**

In `dlc-3D/src/templates/partials/card_frame_labeler.html`, locate the marker-display row (look for `id="fl3d-show-names"` — the row that contains the existing Viewer size / Marker size / Show names labels). Insert this label as a sibling **between** the Marker size label and the Show names label:

```html
<label id="fl3d-sync-frame-label" style="display:none;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim);cursor:pointer;user-select:none">
  <input type="checkbox" id="fl3d-sync-frame" style="accent-color:var(--accent)">
  Sync Frame
</label>
```

Note `display:none` on the wrapping label — JS will flip to `display:flex` when ≥2 cams are present.

- [ ] **Step 2: Replace the `<canvas>` wrapper with a tile-row container**

In the same partial, locate the existing canvas wrapper (look for `<canvas id="fl3d-canvas">` — this is the labeling canvas). Replace its enclosing `<div class="fl3d-canvas-wrap">…</div>` with:

```html
<div class="fl3d-canvas-row" id="fl3d-canvas-row">
  <div class="fl3d-tile focused" data-cam="" data-fname="">
    <div class="fl3d-tile-label" id="fl3d-tile-label-primary"></div>
    <canvas id="fl3d-canvas" class="fl3d-tile-canvas" data-cam="" data-fname=""></canvas>
    <div class="fl3d-tile-empty hidden" id="fl3d-tile-empty-primary"></div>
    <p class="fl3d-canvas-empty hidden" id="fl3d-canvas-loading">Loading frame…</p>
  </div>
</div>
```

Keep the same `id="fl3d-canvas"` so existing JS that references it still works without renaming.

- [ ] **Step 3: Add CSS for tile row and tiles**

Append to `dlc-3D/src/static/dlc_3d.css`:

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
.fl3d-tile-empty.hidden { display: none; }
```

- [ ] **Step 4: Wire visibility of checkbox + populate primary tile attributes**

In `frame_labeler_3d.js`, find `_flLoadFrames` (or whatever function populates `_flFrames` after a stem is selected — locate by searching `_flFrames =`). At the end of that function, after `_flFrames` is assigned, add:

```js
// Build pair map and surface cam set for sync-frame UI
const _fl3dPairBuild = buildPairMap(_flFrames);
_fl3dPairMap      = _fl3dPairBuild.pairMap;
_fl3dCamSet       = _fl3dPairBuild.camSet;
_fl3dFrameNumbers = _fl3dPairBuild.frameNumbers;

const syncLbl = document.getElementById("fl3d-sync-frame-label");
if (syncLbl) {
  syncLbl.style.display = _fl3dCamSet.length >= 2 ? "flex" : "none";
}
```

Declare `_fl3dPairMap`, `_fl3dCamSet`, `_fl3dFrameNumbers` as `let` near the top of the IIFE alongside the existing `_flFrames`, `_flFrameIdx`, etc.

Also in `_flShowFrame(idx)` (the function that loads a frame image), after the line `flFrameName.textContent = fname;` add:

```js
// Mirror current frame onto the primary tile attributes for tests/assertions
const _flCurrentTile = document.querySelector('.fl3d-tile[data-cam=""], .fl3d-tile[data-cam="' + _fl3dPrimaryCam + '"]');
if (_flCurrentTile) {
  const m = FL3D_FRAME_RE.exec(fname);
  if (m) {
    _flCurrentTile.dataset.cam   = m[1];
    _flCurrentTile.dataset.fname = fname;
    flCanvas.dataset.cam         = m[1];
    flCanvas.dataset.fname       = fname;
    document.getElementById("fl3d-tile-label-primary").textContent = `cam${m[1]}`;
  }
}
```

Initialize `_fl3dPrimaryCam = 0` near the other state declarations (will be set properly when sync turns on; for now it's a placeholder so the selector above doesn't blow up).

- [ ] **Step 5: Rebuild and smoke-test**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d && docker compose up -d dlc-3d
```

In browser at `http://localhost:5000/dlc-3d/`:
1. Open Frame Labeler.
2. Select session `OM-2_20260424` (must be present on disk per spec).
3. Confirm: Sync Frame checkbox **appears** in the marker-display row.
4. Confirm: single tile renders with the canvas inside, `data-cam` and `data-fname` populated (inspect via devtools).
5. Confirm: prev/next nav still works, marker placement still works (existing single-canvas behavior unchanged).

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_frame_labeler.html dlc-3D/src/static/frame_labeler_3d.js dlc-3D/src/static/dlc_3d.css
git commit -m "feat(dlc-3d): add Sync Frame checkbox + tile-row DOM scaffold"
```

---

## Task 5: Sync ON transition — append sibling tiles, render images, focus primary

Implement the sync-on toggle: append one tile per non-primary cam, load each tile's image (or render empty placeholder), set focus to primary cam.

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`

- [ ] **Step 1: Add sync-state declarations**

Near the top of the IIFE (alongside existing `_flFrames`, `_flFrameIdx`), add:

```js
let _fl3dSyncOn        = false;
let _fl3dPrimaryCam    = 0;
let _fl3dFocusedCam    = 0;
let _fl3dHoveredCam    = null;
let _fl3dFrameNumIdx   = 0;
```

(Note: `_fl3dPairMap`, `_fl3dCamSet`, `_fl3dFrameNumbers` already declared in Task 4.)

- [ ] **Step 2: Add `_fl3dSyncRenderRow()` helper**

Add this function inside the IIFE, near the existing `_flDraw` / `_flFitCanvas` helpers:

```js
function _fl3dSyncRenderRow(currentFrameNum) {
  const row = document.getElementById("fl3d-canvas-row");
  if (!row) return;

  // Remove any sibling tiles (keep only the primary tile, which always exists)
  Array.from(row.querySelectorAll(".fl3d-tile.fl3d-tile-sibling"))
    .forEach(el => el.remove());

  // Lookup tiles for this frame number
  const entries = _fl3dPairMap.get(currentFrameNum) || [];
  const byCam   = new Map(entries.map(e => [e.cam, e]));

  // Update primary tile (cam = primaryCam)
  const primaryTile = row.querySelector(".fl3d-tile:not(.fl3d-tile-sibling)");
  _fl3dRenderTile(primaryTile, _fl3dPrimaryCam, byCam.get(_fl3dPrimaryCam) || null, currentFrameNum);

  // Append sibling tiles for every other cam in camSet
  for (const cam of _fl3dCamSet) {
    if (cam === _fl3dPrimaryCam) continue;
    const tile = document.createElement("div");
    tile.className = "fl3d-tile fl3d-tile-sibling";
    tile.dataset.cam = String(cam);
    tile.innerHTML = `
      <div class="fl3d-tile-label">cam${cam}</div>
      <canvas class="fl3d-tile-canvas" data-cam="${cam}"></canvas>
      <div class="fl3d-tile-empty hidden"></div>
    `;
    row.appendChild(tile);
    _fl3dRenderTile(tile, cam, byCam.get(cam) || null, currentFrameNum);
  }

  _fl3dApplyFocusClass();
}

function _fl3dRenderTile(tile, cam, entry, frameNum) {
  const canvas = tile.querySelector(".fl3d-tile-canvas");
  const empty  = tile.querySelector(".fl3d-tile-empty");
  const label  = tile.querySelector(".fl3d-tile-label");
  if (label) label.textContent = `cam${cam}`;

  if (!entry) {
    canvas.style.display = "none";
    empty.classList.remove("hidden");
    empty.textContent = `No frame extracted for cam${cam} @ ${String(frameNum).padStart(5, "0")}`;
    tile.dataset.fname = "";
    canvas.dataset.fname = "";
    canvas.dataset.cam   = String(cam);
    return;
  }

  canvas.style.display = "";
  empty.classList.add("hidden");
  tile.dataset.fname   = entry.fname;
  canvas.dataset.fname = entry.fname;
  canvas.dataset.cam   = String(cam);

  // Load image and draw into this tile's canvas
  const img = new Image();
  img.onload = () => {
    canvas.width  = img.naturalWidth;   // intrinsic; CSS scales to width:100%
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0);
    _fl3dDrawTileMarkers(tile, entry.fname);
  };
  img.src = `/dlc/project/frame-image/${encodeURIComponent(_flVideoStem)}/${encodeURIComponent(entry.fname)}`;

  // Stash the image on the tile for re-draw on marker-size / show-names changes
  tile._fl3dImg = img;
}

function _fl3dDrawTileMarkers(tile, fname) {
  const canvas = tile.querySelector(".fl3d-tile-canvas");
  const ctx    = canvas.getContext("2d");
  const labels = _flLabels[fname] || {};
  const r      = _flMarkerRadius;
  const sx     = 1, sy = 1;  // canvas is at native pixel size; CSS handles display scaling
  _flBodyparts.forEach((bp, i) => {
    const pt = labels[bp];
    if (!pt) return;
    if (_flHidden[fname] && _flHidden[fname][bp]) return;
    const cx = pt[0] * sx, cy = pt[1] * sy;
    const color = _flColor(i);
    if (bp === _flSelectedBp && tile.classList.contains("focused")) {
      ctx.beginPath(); ctx.arc(cx, cy, r + 3.5, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 2; ctx.stroke();
    }
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 1.2; ctx.stroke();
    if (_flShowNames) {
      ctx.font = "bold 11px 'JetBrains Mono', monospace";
      ctx.fillStyle = "rgba(12,13,16,.65)";
      const tw = ctx.measureText(bp).width;
      ctx.fillRect(cx + r + 2, cy - 7, tw + 6, 14);
      ctx.fillStyle = color;
      ctx.fillText(bp, cx + r + 5, cy + 4);
    }
  });
}

function _fl3dApplyFocusClass() {
  document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
    t.classList.toggle("focused", +t.dataset.cam === _fl3dFocusedCam);
  });
}
```

- [ ] **Step 3: Wire the checkbox change handler**

Add near the other `addEventListener` blocks:

```js
document.getElementById("fl3d-sync-frame").addEventListener("change", (e) => {
  if (e.target.checked) {
    if (_fl3dCamSet.length < 2) {
      e.target.checked = false;
      flStemStatus.textContent = "Sync Frame needs at least 2 cams in this folder.";
      return;
    }
    // Determine current cam + frame from current fname
    const fname = _flFrames[_flFrameIdx];
    const m = FL3D_FRAME_RE.exec(fname || "");
    if (!m) { e.target.checked = false; return; }
    _fl3dPrimaryCam = +m[1];
    _fl3dFocusedCam = _fl3dPrimaryCam;
    const currentFrameNum = +m[3];
    _fl3dFrameNumIdx = _fl3dFrameNumbers.indexOf(currentFrameNum);
    if (_fl3dFrameNumIdx < 0) _fl3dFrameNumIdx = 0;
    _fl3dSyncOn = true;
    _fl3dSyncRenderRow(_fl3dFrameNumbers[_fl3dFrameNumIdx]);
  } else {
    _fl3dSyncOn = false;
    // Remove sibling tiles
    document.querySelectorAll("#fl3d-canvas-row .fl3d-tile-sibling").forEach(t => t.remove());
    // Re-fit primary canvas back to single-tile width
    if (_flImgLoaded) { _flFitCanvas(); _flDraw(); }
  }
});
```

- [ ] **Step 4: Add debug surface for tests**

Near the end of the IIFE, before its closing `})();` (or equivalent), add:

```js
window.__fl3d = new Proxy({}, {
  get(_, prop) {
    const map = {
      syncOn:        _fl3dSyncOn,
      focusedCam:    _fl3dFocusedCam,
      primaryCam:    _fl3dPrimaryCam,
      hoveredCam:    _fl3dHoveredCam,
      camSet:        _fl3dCamSet,
      pairMapSize:   _fl3dPairMap ? _fl3dPairMap.size : 0,
      frameNumberIdx:_fl3dFrameNumIdx,
      frameNumbers:  _fl3dFrameNumbers,
      selectedBp:    _flSelectedBp,
      markerRadius:  _flMarkerRadius,
      showNames:     _flShowNames,
      zoom:          _flZoom,
      labels:        _flLabels,
      dirtyFrames:   Array.from(_fl3dDirtyFrames || []),
    };
    return map[prop];
  },
});
```

Also declare `let _fl3dDirtyFrames = new Set();` near the other state. Tasks 7–8 will populate it; for now it stays empty.

- [ ] **Step 5: Smoke-test sync ON in browser**

Rebuild, then in browser:
1. Open Frame Labeler at `OM-2_20260424`.
2. Click Sync Frame checkbox.
3. Expected: a second tile appears to the right of the primary; both show their respective images; primary tile has accent-colored border, sibling has default border.
4. Devtools console: `window.__fl3d.syncOn` → `true`; `window.__fl3d.camSet` → `[0, 1]`.
5. Uncheck: sibling tile disappears; primary tile re-fits to full card width.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): sync-frame ON renders sibling tiles with focused primary"
```

---

## Task 6: Tile click → focus switching

Wire click events on tiles to swap focus, with the border color flipping via the `.focused` class. Clicking the focused tile is a no-op.

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`

- [ ] **Step 1: Add tile click delegation**

Add inside the IIFE, after `_fl3dSyncRenderRow` is defined:

```js
document.getElementById("fl3d-canvas-row").addEventListener("click", (e) => {
  const tile = e.target.closest(".fl3d-tile");
  if (!tile) return;
  const cam = +tile.dataset.cam;
  if (Number.isNaN(cam)) return;
  if (cam === _fl3dFocusedCam) return;  // no-op if already focused
  _fl3dFocusedCam = cam;
  _fl3dApplyFocusClass();
  // Re-draw all tiles so the selection ring on the focused tile updates
  document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
    if (t._fl3dImg && t.dataset.fname) _fl3dDrawTileMarkers(t, t.dataset.fname);
  });
  // Also refresh chip status / label count from focused tile's frame
  _flUpdateBpChipStatus();
  _flUpdateLabelCount();
});
```

- [ ] **Step 2: Add helper to read the active fname (single source of truth)**

The existing JS reads `_flFrames[_flFrameIdx]` in many places to get the current frame name. We need a helper that returns the **focused tile's fname** when sync is ON, and the existing primary fname otherwise. Add:

```js
function _fl3dActiveFname() {
  if (!_fl3dSyncOn) return _flFrames[_flFrameIdx];
  const tile = document.querySelector(`#fl3d-canvas-row .fl3d-tile.focused`);
  return tile ? (tile.dataset.fname || "") : _flFrames[_flFrameIdx];
}
```

Existing functions (`_flUpdateBpChipStatus`, `_flUpdateLabelCount`, `_flRemoveBpLabel`, etc.) currently compute the active fname inline as `_flFrames[_flFrameIdx]`. Find each occurrence (grep `_flFrames\[_flFrameIdx\]` in the forked file) and replace with `_fl3dActiveFname()`.

```bash
grep -n '_flFrames\[_flFrameIdx\]' /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js
```

For each line, evaluate: if the line is reading the *current frame's filename* for label lookup / dirty marking / clear / delete, replace with `_fl3dActiveFname()`. If the line is for navigation/idx-arithmetic (e.g., `idx = Math.min(idx, _flFrames.length - 1)`), leave it alone.

- [ ] **Step 3: Smoke-test focus switching**

Rebuild, in browser:
1. Sync ON → click sibling tile → border flips, primary loses accent border.
2. `window.__fl3d.focusedCam` updates accordingly.
3. Click focused tile → no DOM mutation (verify via devtools Inspector that `.focused` class doesn't blink).

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): tile click switches focus and re-routes active fname"
```

---

## Task 7: Lock-step navigation in sync mode

When sync is ON, prev/next walks the frame-number axis (`_fl3dFrameNumbers`) instead of `_flFrames`. All tiles re-resolve simultaneously.

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`

- [ ] **Step 1: Wrap `_flShowFrame` to handle sync mode**

Find `_flShowFrame(idx)`. Wrap its existing body inside an `if (_fl3dSyncOn) { … sync-mode ... return; }` branch:

```js
function _flShowFrame(idx) {
  if (_fl3dSyncOn) {
    if (!_fl3dFrameNumbers.length) return;
    if (_flDirty) { _flDirty = false; _flAutoSave(); }
    idx = Math.max(0, Math.min(idx, _fl3dFrameNumbers.length - 1));
    _fl3dFrameNumIdx = idx;
    const frameNum = _fl3dFrameNumbers[idx];
    flFrameInfo.textContent = `Frame ${idx + 1} / ${_fl3dFrameNumbers.length}`;
    // Update primary fname display from the focused tile after render
    _fl3dSyncRenderRow(frameNum);
    const focusedFname = _fl3dActiveFname();
    flFrameName.textContent = focusedFname || `(no cam${_fl3dFocusedCam} @ ${String(frameNum).padStart(5, "0")})`;
    _flUpdateBpChipStatus();
    _flUpdateLabelCount();
    _flTapUpdateFrameStatus();
    return;
  }
  // ... existing single-canvas implementation unchanged ...
}
```

- [ ] **Step 2: Sync the prev/next button binding indices**

Locate the existing button bindings:

```js
flBtnPrev.addEventListener("click", () => _flShowFrame(_flFrameIdx - 1));
flBtnNext.addEventListener("click", () => _flShowFrame(_flFrameIdx + 1));
```

Replace with:

```js
flBtnPrev.addEventListener("click", () => _flShowFrame((_fl3dSyncOn ? _fl3dFrameNumIdx : _flFrameIdx) - 1));
flBtnNext.addEventListener("click", () => _flShowFrame((_fl3dSyncOn ? _fl3dFrameNumIdx : _flFrameIdx) + 1));
```

Same for the keyboard `←` / `→` handlers (search for `flBtnPrev.click()` or `flShowFrame(_flFrameIdx`); update similarly).

- [ ] **Step 3: Sync ON should also re-render via `_flShowFrame`**

In the checkbox handler from Task 5, replace the direct call:

```js
_fl3dSyncRenderRow(_fl3dFrameNumbers[_fl3dFrameNumIdx]);
```

with:

```js
_flShowFrame(_fl3dFrameNumIdx);
```

This routes through the same code path as nav, ensuring frame counter + chip status update consistently.

- [ ] **Step 4: Sync OFF should restore single-frame nav**

In the checkbox-uncheck branch, after removing sibling tiles, restore `_flFrameIdx` to the position of the focused fname inside `_flFrames`:

```js
const focusedFname = _fl3dActiveFname();
const idx = _flFrames.indexOf(focusedFname);
if (idx >= 0) _flFrameIdx = idx;
_flShowFrame(_flFrameIdx);
```

- [ ] **Step 5: Smoke-test lock-step navigation**

Rebuild, in browser:
1. Sync ON. Note `data-fname` on both tiles (devtools).
2. Click Next. Both tiles' `data-fname` advance to the next entry in `_fl3dFrameNumbers`.
3. Click Prev. Both return.
4. Navigate to a frame number where one cam is missing → that tile shows the empty placeholder; the other shows a real canvas.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): lock-step nav across tiles when sync is on"
```

---

## Task 8: Input routing — marker placement / right-click / keyboard hover-gating

Route marker placement to the focused tile's frame. Add per-tile hover tracking. Gate W/A/S/D nudges to the focused tile only.

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`

- [ ] **Step 1: Per-tile mouseenter/mouseleave for hover tracking**

Inside `_fl3dRenderTile`, after the canvas is wired, add hover listeners (delegated via tile root to avoid leaking across re-renders — actually tiles get re-created on sync ON so direct listeners on the tile element are fine):

```js
tile.addEventListener("mouseenter", () => { _fl3dHoveredCam = +tile.dataset.cam; });
tile.addEventListener("mouseleave", () => {
  if (_fl3dHoveredCam === +tile.dataset.cam) _fl3dHoveredCam = null;
});
```

Add the same to the primary tile inside the partial (since it's pre-rendered, attach listeners once at startup near the existing canvas-listener setup). One simple approach: after the IIFE state declarations, do:

```js
const _fl3dPrimaryTile = document.querySelector("#fl3d-canvas-row .fl3d-tile");
if (_fl3dPrimaryTile) {
  _fl3dPrimaryTile.addEventListener("mouseenter", () => { _fl3dHoveredCam = +_fl3dPrimaryTile.dataset.cam || 0; });
  _fl3dPrimaryTile.addEventListener("mouseleave", () => { _fl3dHoveredCam = null; });
}
```

- [ ] **Step 2: Sibling-tile canvas click → place / select marker**

Each sibling-tile canvas needs the same click logic as the primary canvas, **but** scoped to its own image dimensions and fname. Add inside `_fl3dRenderTile`, after `tile._fl3dImg = img;`:

```js
if (tile.classList.contains("fl3d-tile-sibling")) {
  canvas.addEventListener("click", (e) => {
    if (!tile.dataset.fname) return;  // empty placeholder, no-op
    if (+tile.dataset.cam !== _fl3dFocusedCam) return;  // only focused tile accepts input
    const rect = canvas.getBoundingClientRect();
    const sx = canvas.width  / rect.width;
    const sy = canvas.height / rect.height;
    const cx = (e.clientX - rect.left) * sx;
    const cy = (e.clientY - rect.top)  * sy;
    const fname = tile.dataset.fname;
    if (!_flSelectedBp) return;
    if (!_flLabels[fname]) _flLabels[fname] = {};
    _flLabels[fname][_flSelectedBp] = [cx, cy];
    _fl3dDirtyFrames.add(fname);
    _flDirty = true;
    _fl3dDrawTileMarkers(tile, fname);
    _flUpdateBpChipStatus();
    _flUpdateLabelCount();
    _flAutoAdvanceBp();
  });

  canvas.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    if (!tile.dataset.fname) return;
    if (+tile.dataset.cam !== _fl3dFocusedCam) return;
    if (!_flSelectedBp) return;
    const fname = tile.dataset.fname;
    if (!_flLabels[fname]) return;
    _flLabels[fname][_flSelectedBp] = null;
    _fl3dDirtyFrames.add(fname);
    _flDirty = true;
    _fl3dDrawTileMarkers(tile, fname);
    _flUpdateBpChipStatus();
    _flUpdateLabelCount();
  });
}
```

- [ ] **Step 3: Existing primary canvas click → also mark dirty by tile fname**

Find the existing `flCanvas.addEventListener("click", …)` handler. Inside it, replace `_flFrames[_flFrameIdx]` references for the active fname with `_fl3dActiveFname()` (most should already be done in Task 6), and add `_fl3dDirtyFrames.add(fname);` next to `_flDirty = true;`. Same for the right-click and W/A/S/D nudge handlers.

- [ ] **Step 4: Hover gate the keyboard nudge**

Find the W/A/S/D `keydown` handler (search for `case "w":` or `key === "w"` in the file). It currently checks `if (!_flCursorInCanvas) return;`. Add a sync-mode-aware additional gate:

```js
if (_fl3dSyncOn && _fl3dHoveredCam !== _fl3dFocusedCam) return;
```

If the existing handler reads the active fname inline, ensure it uses `_fl3dActiveFname()`.

- [ ] **Step 5: Smoke-test input routing**

Rebuild, in browser:
1. Sync ON. Place a marker on the primary tile (it's focused) → marker appears, `window.__fl3d.dirtyFrames` includes the primary's fname.
2. Click the sibling tile to focus it. Place a marker → marker appears on sibling, dirty set grows.
3. Click the primary tile to refocus. Try clicking on the sibling tile's canvas → no marker added (focus is on primary).
4. Hover the sibling tile and press `W` → no marker move on either tile.
5. Hover the focused tile and press `W` → focused tile's marker moves 1px.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): route marker input to focused tile + hover-gate keyboard nudge"
```

---

## Task 9: Shared display controls — zoom row break-out + marker size + show-names

Make zoom resize the row container (with break-out beyond card width when needed) and propagate marker-size / show-names changes to all tiles.

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`

- [ ] **Step 1: Sync-aware row sizing in `_flFitCanvas`**

The existing `_flFitCanvas` sizes one canvas. When sync is ON, we want the **row** to take `targetRowW`, with each tile getting an equal share. Add a sync branch at the top of `_flFitCanvas`:

```js
function _flFitCanvas() {
  if (_fl3dSyncOn) {
    _fl3dFitRow();
    return;
  }
  // ... existing single-canvas body unchanged ...
}

function _fl3dFitRow() {
  const row  = document.getElementById("fl3d-canvas-row");
  const wrap = row.parentElement;
  const cs   = getComputedStyle(flCard);
  const padL = parseFloat(cs.paddingLeft) || 0;
  const padR = parseFloat(cs.paddingRight) || 0;
  const baseW = flCard.clientWidth - padL - padR;
  const maxW  = Math.max(baseW, window.innerWidth - 32);
  const targetRowW = Math.min(Math.round(baseW * (_flZoom / 100)), Math.floor(maxW));
  row.style.width = targetRowW + "px";
  const extra = targetRowW - baseW;
  row.style.marginLeft = extra > 0 ? `-${extra / 2}px` : "";
  // CSS flex `flex: 1 1 0` with `min-width:0` already shares the width across tiles.
}
```

- [ ] **Step 2: Re-draw all tiles on marker-size / show-names change**

Find the existing handler for `#fl3d-marker-size` (input/change event). After the existing single-canvas re-draw, add:

```js
if (_fl3dSyncOn) {
  document.querySelectorAll("#fl3d-canvas-row .fl3d-tile").forEach(t => {
    if (t.dataset.fname) _fl3dDrawTileMarkers(t, t.dataset.fname);
  });
}
```

Same for the `#fl3d-show-names` handler.

- [ ] **Step 3: Re-fit row on zoom change**

The existing `#fl3d-zoom` handler calls `_flFitCanvas()`; the sync-aware branch from Step 1 already routes correctly. No additional change needed — verify by inspecting the handler.

- [ ] **Step 4: Smoke-test display controls**

Rebuild, in browser:
1. Sync ON at zoom 100%. Row width matches card inner width.
2. Drag zoom to 200%. Row width grows; row's `style.marginLeft` becomes negative; both tiles widen.
3. Drag zoom to 50%. Row shrinks; no negative margin.
4. Increase Marker size 4 → 12. Both tiles re-render with larger markers.
5. Toggle Show names off. Both tiles re-render without name labels.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): zoom/marker/show-names controls apply to all tiles in sync mode"
```

---

## Task 10: Clear Frame / Delete Frame act on focused tile only

Wire the Clear and Delete buttons to operate on the focused tile's fname (rather than the global `_flFrames[_flFrameIdx]`) when sync is ON.

**Files:**
- Modify: `dlc-3D/src/static/frame_labeler_3d.js`

- [ ] **Step 1: Update Clear Frame handler**

Find the `#fl3d-btn-clear-frame` `dblclick` handler. Replace any `_flFrames[_flFrameIdx]` references with `_fl3dActiveFname()`. After clearing labels, re-render only the focused tile:

```js
const fname = _fl3dActiveFname();
if (!fname) return;
delete _flLabels[fname];
delete _flHidden[fname];
_fl3dDirtyFrames.add(fname);
_flDirty = true;
if (_fl3dSyncOn) {
  const tile = document.querySelector(`#fl3d-canvas-row .fl3d-tile.focused`);
  if (tile) _fl3dDrawTileMarkers(tile, fname);
} else {
  _flDraw();
}
_flUpdateBpChipStatus();
_flUpdateLabelCount();
```

- [ ] **Step 2: Update Delete Frame handler**

Find `#fl3d-btn-delete-frame` `dblclick` handler. Similar pattern: read `_fl3dActiveFname()`, send the existing DELETE request keyed by that fname, then on success refresh the frame list (which calls `_flLoadFrames` and rebuilds the pair map). The existing post-delete refresh path should already trigger a re-render via `_flShowFrame`.

If sync is ON and the deleted frame leaves the row with one tile empty for that frame number, `_fl3dSyncRenderRow` will show the placeholder on next nav; no special-case here.

- [ ] **Step 3: Smoke-test clear/delete**

Rebuild, in browser:
1. Sync ON, focus primary, place markers. Sibling tile also has its own existing markers.
2. Double-click Clear Frame → primary tile loses markers; sibling tile's markers unchanged.
3. (Optional, destructive — skip if not in test fixture.) Double-click Delete Frame → primary tile's image fetch returns 404 next time; sibling's image still loads.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/frame_labeler_3d.js
git commit -m "feat(dlc-3d): clear/delete frame buttons act on focused tile only"
```

---

## Task 11: pytest-playwright e2e suite — Visibility, Initial state, Sync ON, Focus

Create `dlc-3D/tests/e2e/test_sync_frame.py` with the first four test groups (A, B, C, D from spec). Add a session-scoped fixture that probes the labeled-frames endpoint and skips the module if `OM-2_20260424` is missing or has <2 cams.

**Files:**
- Create: `dlc-3D/tests/e2e/test_sync_frame.py`
- Modify: `dlc-3D/tests/e2e/conftest.py`

- [ ] **Step 1: Add fixture-presence probe to e2e conftest**

Edit `dlc-3D/tests/e2e/conftest.py`:

```python
import pytest
import urllib.request
import json

@pytest.fixture(scope="session")
def base_url():
    return "http://172.26.0.5:5050/dlc-3d/"

@pytest.fixture(scope="session", autouse=False)
def om2_fixture_present(base_url):
    """Probe /labeled-stems for OM-2_20260424 with ≥2 cams."""
    try:
        with urllib.request.urlopen(base_url + "labeled-stems", timeout=5) as r:
            data = json.loads(r.read())
    except Exception:
        return False
    stems = data.get("stems", []) if isinstance(data, dict) else data
    return any(
        (isinstance(s, dict) and s.get("name") == "OM-2_20260424") or s == "OM-2_20260424"
        for s in stems
    )
```

If the actual endpoint path is different, adjust accordingly — the probe just needs to confirm the session shows up. Worst case, fall back to assuming present and let the test fail loudly.

- [ ] **Step 2: Write the e2e test file (groups A–D)**

Create `dlc-3D/tests/e2e/test_sync_frame.py`:

```python
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"

@pytest.fixture(autouse=True)
def _open_labeler(page: Page, base_url, om2_fixture_present):
    if not om2_fixture_present:
        pytest.skip(f"Skipping: {SESSION} not present or has no multi-cam frames.")
    page.goto(base_url)
    # Open Frame Labeler card (find the open button near the card's nav)
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#frame-labeler-card").wait_for(state="visible")
    # Select the session
    page.locator("#fl3d-stem-select").select_option(SESSION)
    # Wait for the canvas-row to populate the primary tile with a fname
    page.wait_for_function(
        '() => document.querySelector("#fl3d-canvas-row .fl3d-tile")?.dataset?.fname'
    )

# ---------- Group A: Visibility gate ----------

def test_a1_sync_checkbox_visible_when_two_cams(page: Page):
    expect(page.locator("#fl3d-sync-frame-label")).to_be_visible()
    cam_count = page.evaluate("window.__fl3d.camSet.length")
    assert cam_count >= 2

# ---------- Group B: Initial state with sync OFF ----------

def test_b1_sync_off_one_tile(page: Page):
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    assert tiles.count() == 1

def test_b2_sole_tile_focused(page: Page):
    tile = page.locator("#fl3d-canvas-row .fl3d-tile").first
    expect(tile).to_have_class(__class_re("focused"))

def test_b3_tile_width_matches_card_at_100pct(page: Page):
    card_w = page.evaluate("document.getElementById('frame-labeler-card').clientWidth")
    tile_w = page.evaluate(
        "document.querySelector('#fl3d-canvas-row .fl3d-tile').getBoundingClientRect().width"
    )
    # tile is inside card padding; allow small tolerance
    assert tile_w <= card_w
    assert tile_w >= card_w * 0.6

# ---------- Group C: Sync ON transition ----------

def test_c1_sync_on_creates_one_tile_per_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    tile_count = page.locator("#fl3d-canvas-row .fl3d-tile").count()
    cam_count = page.evaluate("window.__fl3d.camSet.length")
    assert tile_count == cam_count

def test_c2_tiles_ordered_ascending_by_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => Number(t.dataset.cam))",
    )
    assert cams == sorted(cams)

def test_c3_focused_tile_is_primary_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    focused_cam = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => Number(t.dataset.cam)"
    )
    primary = page.evaluate("window.__fl3d.primaryCam")
    assert focused_cam == primary

def test_c4_focused_border_color_matches_accent(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    accent = page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
    )
    focused_color = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused",
        "t => getComputedStyle(t).borderColor",
    )
    # Compare via canvas-rendered rgb roundtrip — both should resolve to the same rgb()
    accent_rgb = page.evaluate(
        "(c) => { const el = document.createElement('div'); el.style.color = c; "
        "document.body.appendChild(el); const got = getComputedStyle(el).color; "
        "el.remove(); return got; }",
        accent,
    )
    assert focused_color == accent_rgb

def test_c5_each_tile_has_image_or_placeholder(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    statuses = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        """tiles => tiles.map(t => {
          const c = t.querySelector('canvas');
          const e = t.querySelector('.fl3d-tile-empty');
          if (e && !e.classList.contains('hidden')) return { kind: 'empty', text: e.textContent.trim() };
          if (c && c.dataset.fname) return { kind: 'image', fname: c.dataset.fname };
          return { kind: 'unknown' };
        })""",
    )
    import re
    for s in statuses:
        if s["kind"] == "empty":
            assert re.match(r"^No frame extracted for cam\d+ @ \d+$", s["text"])
        elif s["kind"] == "image":
            assert s["fname"]
        else:
            pytest.fail(f"tile in unknown state: {s}")

# ---------- Group D: Focus switching ----------

def test_d1_click_unfocused_tile_swaps_focus(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => Number(t.dataset.cam))"
    )
    other = next(c for c in cams if c != primary)
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{other}"]').click()
    new_focused = page.evaluate("window.__fl3d.focusedCam")
    assert new_focused == other

def test_d3_focused_cam_state_reflects_click(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => Number(t.dataset.cam))"
    )
    for cam in cams:
        page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{cam}"]').click()
        assert page.evaluate("window.__fl3d.focusedCam") == cam

# ---------- helpers ----------

import re as _re
def __class_re(token):
    return _re.compile(rf"\b{token}\b")
```

- [ ] **Step 3: Run the e2e suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose up -d flask dlc-3d  # ensure stack is running

cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/test_sync_frame.py -v
```

Expected: all tests pass (or skip cleanly if fixture missing).

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/tests/e2e/test_sync_frame.py dlc-3D/tests/e2e/conftest.py
git commit -m "test(dlc-3d): e2e visibility/initial-state/sync-on/focus tests"
```

---

## Task 12: e2e suite — Lock-step nav, Marker placement, Display controls

Add the rest of the interaction tests (groups E, F, G from the spec).

**Files:**
- Modify: `dlc-3D/tests/e2e/test_sync_frame.py`

- [ ] **Step 1: Append Group E (lock-step nav) tests**

Append to `test_sync_frame.py`:

```python
# ---------- Group E: Lock-step navigation ----------

def test_e1_next_advances_all_tiles(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    before = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => ({cam: +t.dataset.cam, fname: t.dataset.fname}))",
    )
    before_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    page.locator("#fl3d-btn-next").click()
    page.wait_for_function(f"window.__fl3d.frameNumberIdx === {before_idx + 1}")
    after = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile",
        "tiles => tiles.map(t => ({cam: +t.dataset.cam, fname: t.dataset.fname}))",
    )
    # Same cams, different (or empty) fnames
    assert [t["cam"] for t in before] == [t["cam"] for t in after]
    assert before != after  # at least one tile changed

def test_e2_prev_returns_to_original(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    original = page.evaluate("window.__fl3d.frameNumberIdx")
    page.locator("#fl3d-btn-next").click()
    page.locator("#fl3d-btn-prev").click()
    assert page.evaluate("window.__fl3d.frameNumberIdx") == original

def test_e3_navigate_until_one_tile_empty(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    # Walk until at least one empty placeholder is visible (max 50 steps)
    found = False
    for _ in range(50):
        empties = page.locator("#fl3d-canvas-row .fl3d-tile-empty:not(.hidden)").count()
        if empties >= 1:
            found = True
            break
        page.locator("#fl3d-btn-next").click()
    assert found, "fixture has no frame_number with a missing sibling — pick a richer fixture"
    # Click the empty tile → focus moves but no marker placed
    empty_tile = page.locator("#fl3d-canvas-row .fl3d-tile:has(.fl3d-tile-empty:not(.hidden))").first
    empty_cam = empty_tile.evaluate("t => +t.dataset.cam")
    empty_tile.click()
    assert page.evaluate("window.__fl3d.focusedCam") == empty_cam
```

- [ ] **Step 2: Append Group F (marker placement & input routing) tests**

```python
# ---------- Group F: Marker placement ----------

def _select_first_chip(page: Page):
    chip = page.locator("#fl3d-bodypart-list .fl3d-bp-chip").first
    bp = chip.get_attribute("data-bp")
    chip.click()
    page.wait_for_function(f"window.__fl3d.selectedBp === '{bp}'")
    return bp

def _click_canvas_center(page: Page, tile_cam: int):
    canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{tile_cam}"] canvas')
    box = canvas.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

def test_f1_marker_added_on_focused_tile(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    focused = page.evaluate("window.__fl3d.focusedCam")
    focused_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _click_canvas_center(page, focused)
    page.wait_for_function(f"window.__fl3d.dirtyFrames.includes('{focused_fname}')")
    pt = page.evaluate(f"window.__fl3d.labels['{focused_fname}']?.['{bp}']")
    assert pt is not None and len(pt) == 2

def test_f2_focus_swap_then_marker_routes_to_sibling(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    sibling_cam = next(c for c in cams if c != primary)
    sibling_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling_cam}"]')
    if "empty" in (sibling_tile.locator(".fl3d-tile-empty").get_attribute("class") or ""):
        # Skip placement on empty placeholder
        pytest.skip("sibling tile is empty placeholder for current frame_number")
    sibling_tile.click()
    page.wait_for_function(f"window.__fl3d.focusedCam === {sibling_cam}")
    sibling_fname = sibling_tile.evaluate("t => t.dataset.fname")
    _click_canvas_center(page, sibling_cam)
    page.wait_for_function(f"window.__fl3d.dirtyFrames.includes('{sibling_fname}')")
    pt = page.evaluate(f"window.__fl3d.labels['{sibling_fname}']?.['{bp}']")
    assert pt is not None

def test_f7_keyboard_nudge_only_when_hover_focused(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    focused = page.evaluate("window.__fl3d.focusedCam")
    focused_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _click_canvas_center(page, focused)
    page.wait_for_function(f"window.__fl3d.labels['{focused_fname}']?.['{bp}']")
    before = page.evaluate(f"window.__fl3d.labels['{focused_fname}']['{bp}']")
    # Hover an unfocused tile and press W → should NOT move
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    other = next(c for c in cams if c != focused)
    other_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{other}"] canvas')
    other_box = other_canvas.bounding_box()
    page.mouse.move(other_box["x"] + 5, other_box["y"] + 5)
    page.keyboard.press("w")
    page.wait_for_timeout(50)
    after_unhover = page.evaluate(f"window.__fl3d.labels['{focused_fname}']['{bp}']")
    assert after_unhover == before, "nudge fired when cursor was on unfocused tile"
    # Hover focused → W should move
    focused_canvas = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{focused}"] canvas')
    fb = focused_canvas.bounding_box()
    page.mouse.move(fb["x"] + fb["width"] / 2, fb["y"] + fb["height"] / 2)
    page.keyboard.press("w")
    page.wait_for_timeout(50)
    after_hover = page.evaluate(f"window.__fl3d.labels['{focused_fname}']['{bp}']")
    assert after_hover != before
```

- [ ] **Step 3: Append Group G (display controls) tests**

```python
# ---------- Group G: Shared display controls ----------

def test_g1_zoom_200_breaks_out(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.locator("#fl3d-zoom").evaluate("(el) => { el.value = '200'; el.dispatchEvent(new Event('input')); }")
    margin = page.eval_on_selector("#fl3d-canvas-row", "el => parseFloat(el.style.marginLeft) || 0")
    assert margin < 0

def test_g2_zoom_50_no_negative_margin(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.locator("#fl3d-zoom").evaluate("(el) => { el.value = '50'; el.dispatchEvent(new Event('input')); }")
    margin = page.eval_on_selector("#fl3d-canvas-row", "el => parseFloat(el.style.marginLeft) || 0")
    assert margin >= 0

def test_g3_marker_size_updates_state(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.locator("#fl3d-marker-size").evaluate("(el) => { el.value = '12'; el.dispatchEvent(new Event('input')); }")
    page.wait_for_function("window.__fl3d.markerRadius === 12")

def test_g4_show_names_toggle_updates_state(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    before = page.evaluate("window.__fl3d.showNames")
    page.locator("#fl3d-show-names").click()
    after = page.evaluate("window.__fl3d.showNames")
    assert after != before
```

- [ ] **Step 4: Run the new tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/test_sync_frame.py -v -k "test_e or test_f or test_g"
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/tests/e2e/test_sync_frame.py
git commit -m "test(dlc-3d): e2e nav/marker-placement/display-controls tests"
```

---

## Task 13: e2e suite — Save round-trip, Sync OFF, Resize, Refresh, Non-regression

Add the remaining test groups (H, J, K, L, M from spec). Group I (clear/delete frame) is partially covered by clear-only assertion; the destructive delete is intentionally skipped behind an env flag.

**Files:**
- Modify: `dlc-3D/tests/e2e/test_sync_frame.py`

- [ ] **Step 1: Append Group H (save round-trip) tests**

```python
# ---------- Group H: Save round-trip ----------

import os

@pytest.mark.skipif(os.environ.get("FL3D_E2E_WRITE") != "1",
                    reason="Destructive write test; set FL3D_E2E_WRITE=1 to enable.")
def test_h1_h2_h3_save_persists_multi_cam_dirty(page: Page, base_url):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    sibling = next(c for c in cams if c != primary)
    sibling_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"]')
    if sibling_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty for current frame_number — pick another fixture frame")

    primary_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    sibling_fname = sibling_tile.evaluate("t => t.dataset.fname")

    _click_canvas_center(page, primary)
    sibling_tile.click()
    _click_canvas_center(page, sibling)

    page.wait_for_function(
        f"window.__fl3d.dirtyFrames.includes('{primary_fname}') && "
        f"window.__fl3d.dirtyFrames.includes('{sibling_fname}')"
    )

    page.locator("#fl3d-btn-save").click()
    page.wait_for_function("window.__fl3d.dirtyFrames.length === 0", timeout=10000)

    # Hard reload + reopen and assert markers persisted
    page.reload()
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#fl3d-stem-select").select_option(SESSION)
    page.wait_for_function("document.querySelector('#fl3d-canvas-row .fl3d-tile')?.dataset?.fname")
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    # Walk frame nav until both fnames are again on screen
    for _ in range(500):
        cur = page.eval_on_selector_all(
            "#fl3d-canvas-row .fl3d-tile", "ts => ts.map(t => t.dataset.fname)"
        )
        if primary_fname in cur and sibling_fname in cur:
            break
        page.locator("#fl3d-btn-next").click()
    p_pt = page.evaluate(f"window.__fl3d.labels['{primary_fname}']?.['{bp}']")
    s_pt = page.evaluate(f"window.__fl3d.labels['{sibling_fname}']?.['{bp}']")
    assert p_pt is not None and s_pt is not None

    # Cleanup: remove markers and save again
    page.evaluate(
        f"window.__fl3d.labels['{primary_fname}']['{bp}'] = null;"
        f"window.__fl3d.labels['{sibling_fname}']['{bp}'] = null;"
    )
    page.locator("#fl3d-btn-save").click()
```

- [ ] **Step 2: Append Group I (Clear Frame) — non-destructive only**

```python
# ---------- Group I: Clear Frame ----------

def test_i1_clear_frame_focused_tile_only(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    bp = _select_first_chip(page)
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    sibling = next(c for c in cams if c != primary)
    sibling_tile = page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{sibling}"]')
    if sibling_tile.locator(".fl3d-tile-empty:not(.hidden)").count() > 0:
        pytest.skip("sibling empty for current frame_number")
    primary_fname = page.eval_on_selector("#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname")
    sibling_fname = sibling_tile.evaluate("t => t.dataset.fname")
    _click_canvas_center(page, primary)
    sibling_tile.click()
    _click_canvas_center(page, sibling)
    # Refocus primary
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{primary}"]').click()
    # Double-click Clear Frame
    page.locator("#fl3d-btn-clear-frame").dblclick()
    p_pt = page.evaluate(f"window.__fl3d.labels['{primary_fname}']?.['{bp}']")
    s_pt = page.evaluate(f"window.__fl3d.labels['{sibling_fname}']?.['{bp}']")
    assert p_pt in (None, undefined())
    assert s_pt is not None  # sibling untouched

def undefined():
    # JS undefined → Python None via Playwright; placeholder for clarity
    return None
```

- [ ] **Step 3: Append Group J (Sync OFF transition) tests**

```python
# ---------- Group J: Sync OFF transition ----------

def test_j1_sync_off_preserves_focused_cam(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    primary = page.evaluate("window.__fl3d.primaryCam")
    cams = page.eval_on_selector_all(
        "#fl3d-canvas-row .fl3d-tile", "tiles => tiles.map(t => +t.dataset.cam)"
    )
    other = next(c for c in cams if c != primary)
    page.locator(f'#fl3d-canvas-row .fl3d-tile[data-cam="{other}"]').click()
    fname_at_toggle = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    page.locator("#fl3d-sync-frame").uncheck()
    page.wait_for_function("window.__fl3d.syncOn === false")
    tiles = page.locator("#fl3d-canvas-row .fl3d-tile")
    assert tiles.count() == 1
    sole_cam = tiles.first.evaluate("t => +t.dataset.cam")
    assert sole_cam == other
    sole_fname = tiles.first.evaluate("t => t.dataset.fname")
    assert sole_fname == fname_at_toggle
```

- [ ] **Step 4: Append Group K (window resize) tests**

```python
# ---------- Group K: Window resize ----------

def test_k1_shrink_viewport_no_horizontal_scrollbar(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.set_viewport_size({"width": 800, "height": 720})
    page.wait_for_timeout(150)
    has_scroll = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert not has_scroll

def test_k2_grow_viewport_tiles_fit(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    page.set_viewport_size({"width": 1600, "height": 900})
    page.wait_for_timeout(150)
    tile_w = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.getBoundingClientRect().width"
    )
    assert tile_w > 200
```

- [ ] **Step 5: Append Group L (refresh) and Group M (non-regression) tests**

```python
# ---------- Group L: Refresh rebuilds pair map ----------

def test_l1_refresh_preserves_sync_state(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")
    pair_size_before = page.evaluate("window.__fl3d.pairMapSize")
    focused_before = page.evaluate("window.__fl3d.focusedCam")
    page.locator("#fl3d-refresh-btn").click()
    page.wait_for_function("document.querySelector('#fl3d-canvas-row .fl3d-tile')?.dataset?.fname")
    pair_size_after = page.evaluate("window.__fl3d.pairMapSize")
    focused_after = page.evaluate("window.__fl3d.focusedCam")
    assert pair_size_after == pair_size_before
    assert focused_after == focused_before

# ---------- Group M: Non-regression ----------

def test_m1_ml_panel_toggle_still_works(page: Page):
    cb = page.locator("#fl3d-ml-checkbox")
    assert cb.is_visible()
    cb.click()
    expect(page.locator("#fl3d-ml-opts")).not_to_have_class(__class_re("hidden"))
    cb.click()
    expect(page.locator("#fl3d-ml-opts")).to_have_class(__class_re("hidden"))

def test_m2_tap_panel_toggle_still_works(page: Page):
    cb = page.locator("#fl3d-tap-checkbox")
    assert cb.is_visible()
    cb.click()
    expect(page.locator("#fl3d-tap-opts")).not_to_have_class(__class_re("hidden"))
    cb.click()
    expect(page.locator("#fl3d-tap-opts")).to_have_class(__class_re("hidden"))
```

- [ ] **Step 6: Run the full e2e suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/test_sync_frame.py -v
```

Expected: all pass except `test_h1_h2_h3_save_persists_multi_cam_dirty` (skipped without `FL3D_E2E_WRITE=1`).

To run including the destructive save test:

```bash
FL3D_E2E_WRITE=1 python -m pytest tests/e2e/test_sync_frame.py -v
```

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/tests/e2e/test_sync_frame.py
git commit -m "test(dlc-3d): e2e save/clear/sync-off/resize/refresh/non-regression tests"
```

---

## Final verification

- [ ] **Step 1: Run all unit + e2e tests one more time**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_pair_map.mjs
python -m pytest tests/e2e/ -v
```

Expected: all pass; `test_h1_h2_h3_*` skips without `FL3D_E2E_WRITE=1`.

- [ ] **Step 2: Manual end-to-end smoke**

In browser at `http://localhost:5000/dlc-3d/`:
1. Open Frame Labeler, select `OM-2_20260424`, toggle Sync Frame on.
2. Click sibling tile → border flips, focus moves.
3. Place a body-part marker on each cam by switching focus and clicking.
4. Save Labels → status shows success, dirty count returns to 0.
5. Reload page, re-open Frame Labeler, navigate to same frame number → markers persist on both tiles.
6. Toggle Sync Frame off → row collapses to focused tile only.
7. Resize the browser window narrow → tiles shrink, no horizontal scrollbar.

- [ ] **Step 3: Confirm main webapp is untouched**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git status
```

Expected: working tree clean (no changes to the main webapp). The fork lives entirely in `deeplabcut-webapp-docker-supports/dlc-3D/`.
