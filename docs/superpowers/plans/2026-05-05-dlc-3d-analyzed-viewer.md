# dlc-3D Analyzed Frame/Video Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fork the main webapp's "View Analyzed Videos / Frames" card into a dlc-3D-aware variant that handles paired sync-cam videos with per-cam tiles, auto-paired overlay layers, per-cam editing, primary-cam-only companion CSV, and a "Both cams" extract/add/batch checkbox.

**Architecture:** Copy `card_viewer.html` and `static/js/viewer.js` from the main webapp into the dlc-3D module under new names (`card_viewer_3d.html`, `viewer_3d.js`), rename ids `va-*` → `va3d-*`, replace the include in `dlc_3d.html`. Refactor the player section around a `Tile` abstraction so 1 or 2 tiles can render uniformly. A small new endpoint (`/dlc-3d/analyzed/sibling-h5`) supports the layer-pair resolver. All other endpoints (`/dlc/curator/*`, `/dlc/viewer/*`, `/annotate/*`) are reused as-is — the dlc-3D container is built on the flask image and shares the same Flask app, so those URLs are reachable directly.

**Tech Stack:** Flask + Jinja templates, vanilla ES modules (no build step), Playwright pytest e2e tests against the live stack at `http://localhost:5000/dlc-3d/`, OM-2_20260424 fixture with multi-cam frames.

**Reference spec:** `docs/superpowers/specs/2026-05-05-dlc-3d-analyzed-viewer-design.md`

---

## File Structure

**New files:**

| Path | Purpose |
|---|---|
| `dlc-3D/src/templates/partials/card_viewer_3d.html` | Forked card markup, ids prefixed `va3d-*`, player section restructured into a tile row. |
| `dlc-3D/src/static/viewer_3d.js` | Forked viewer module, refactored around `Tile` + `ViewerController`. |
| `dlc-3D/src/static/viewer_3d.css` | Sync-cam / per-tile additions only; reuses `fl3d-tile` rules. |
| `dlc-3D/tests/unit/test_sibling_h5.py` | Unit tests for the sibling-h5 path resolver. |
| `dlc-3D/tests/e2e/test_analyzed_viewer.py` | Playwright e2e: single-cam parity, dual-cam load, frame lock, layer pairing, edits, curation. |

**Edited files:**

| Path | Change |
|---|---|
| `dlc-3D/src/templates/dlc_3d.html` | Replace `card_viewer.html` include with `card_viewer_3d.html`; load `viewer_3d.js` (and `viewer_3d.css`). |
| `dlc-3D/src/dlc_3d_bp/routes.py` | Add `/dlc-3d/analyzed/sibling-h5` endpoint and helper `_resolve_sibling_h5`. |

**Deliberately untouched:**
- `dlc-3D/src/static/viewer.js` does not exist (no fork needed); the main webapp's `static/js/viewer.js` is the source we copy from.
- `deeplabcut-webapp-docker/...` — main webapp project is untouched.

---

## Conventions

- Every commit message uses the Conventional Commits style already used in this repo: `feat(dlc-3d): …`, `fix(dlc-3d): …`, `test(dlc-3d): …`, `refactor(dlc-3d): …`.
- After any code edit that touches the dlc-3d image, rebuild before re-running e2e: `docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d && docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d` (this command is referenced as "rebuild dlc-3d" below).
- Run unit tests from the support repo root: `pytest dlc-3D/tests/unit/ -v`.
- Run e2e tests from the support repo root: `pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v` (requires the stack running at `http://localhost:5000`).
- Trailing `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` on every commit.

---

## Task 1: Backend — `/dlc-3d/analyzed/sibling-h5` endpoint

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py` — add helper + route
- Create: `dlc-3D/tests/unit/test_sibling_h5.py`

The frontend layer-pair resolver needs server help: given a primary cam's h5 path and a target cam index, find the sibling cam's matching h5 in the same directory by substituting `_cam{N}_` in the basename. Mirrors the substitution rule already used by `_find_sibling_video` and `pair_map.mjs`.

- [ ] **Step 1: Write the failing unit test**

```python
# dlc-3D/tests/unit/test_sibling_h5.py
"""Unit tests for the sibling-h5 path resolver."""
from pathlib import Path

from dlc_3d_bp.routes import _resolve_sibling_h5


def test_substitutes_cam_token_in_basename(tmp_path: Path):
    cam0 = tmp_path / "OM-2_cam0_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    cam1 = tmp_path / "OM-2_cam1_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    cam0.write_bytes(b"")
    cam1.write_bytes(b"")
    out = _resolve_sibling_h5(str(cam0), 1)
    assert out == {"path": str(cam1), "exists": True}


def test_returns_path_with_exists_false_when_sibling_missing(tmp_path: Path):
    cam0 = tmp_path / "OM-2_cam0_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    cam0.write_bytes(b"")
    expected_sibling = tmp_path / "OM-2_cam1_20260424_DLC_resnet50_DREADDApr27shuffle1_50000.h5"
    out = _resolve_sibling_h5(str(cam0), 1)
    assert out == {"path": str(expected_sibling), "exists": False}


def test_no_cam_token_in_path_returns_none(tmp_path: Path):
    f = tmp_path / "no_cam_token.h5"
    f.write_bytes(b"")
    assert _resolve_sibling_h5(str(f), 0) == {"path": None, "exists": False}


def test_same_cam_index_returns_input_path(tmp_path: Path):
    cam0 = tmp_path / "OM-2_cam0_20260424.h5"
    cam0.write_bytes(b"")
    out = _resolve_sibling_h5(str(cam0), 0)
    assert out == {"path": str(cam0), "exists": True}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest dlc-3D/tests/unit/test_sibling_h5.py -v`
Expected: FAIL — `cannot import name '_resolve_sibling_h5'`

- [ ] **Step 3: Implement helper + route**

Append to `dlc-3D/src/dlc_3d_bp/routes.py` (after `_find_sibling_on_filesystem`):

```python
# ── Sibling h5 resolver (for analyzed-viewer layer pairing) ──────────────────

def _resolve_sibling_h5(primary_h5: str, target_cam: int) -> dict:
    """Substitute `_cam{N}_` in the basename of primary_h5 to point at target_cam.

    Returns {"path": <str>, "exists": bool} or {"path": None, "exists": False}
    when the input has no `_cam\\d+_` token.
    """
    p = Path(primary_h5)
    m = _CAM_RE.search(p.name)
    if not m:
        return {"path": None, "exists": False}
    sibling_name = _CAM_RE.sub(f"_cam{int(target_cam)}_", p.name, count=1)
    sibling = p.with_name(sibling_name)
    return {"path": str(sibling), "exists": sibling.is_file()}
```

Then add the route (place after `/sibling-camera`):

```python
@bp.route("/analyzed/sibling-h5")
def analyzed_sibling_h5():
    primary = (request.args.get("primary_h5") or "").strip()
    cam = request.args.get("cam", type=int)
    if not primary or cam is None:
        return jsonify({"error": "primary_h5 and cam required"}), 400
    # Path security: must resolve under /user-data/
    resolved = Path(primary).resolve()
    if not str(resolved).startswith(_USER_DATA_ROOT + "/"):
        return jsonify({"error": "path outside /user-data"}), 403
    return jsonify(_resolve_sibling_h5(primary, cam))
```

- [ ] **Step 4: Run to verify passing**

Run: `pytest dlc-3D/tests/unit/test_sibling_h5.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/unit/test_sibling_h5.py
git commit -m "$(cat <<'EOF'
feat(dlc-3d): add sibling-h5 resolver endpoint for analyzed viewer

Substitutes _cam{N}_ in the basename of a primary cam h5 to locate the
sibling cam's matching h5 in the same directory. Used by the analyzed
viewer's layer-pair resolver.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Fork the card markup (`card_viewer_3d.html`)

**Files:**
- Create: `dlc-3D/src/templates/partials/card_viewer_3d.html`
- Modify: `dlc-3D/src/templates/dlc_3d.html`

Verbatim copy of upstream `card_viewer.html` with two mechanical changes: id prefix swap and section id swap. Player-section restructure happens later (Task 5). This task only ensures we have a clean fork that behaves identically to upstream for the single-cam case.

- [ ] **Step 1: Copy and rename ids**

```bash
cp /home/sam/docker-images/deeplabcut-webapp-docker/src/templates/partials/card_viewer.html \
   /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_viewer_3d.html
sed -i 's/\bva-/va3d-/g; s/view-analyzed-card/view-analyzed-3d-card/g; s/btn-close-view-analyzed/btn-close-view-analyzed-3d/g' \
   /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_viewer_3d.html
```

- [ ] **Step 2: Swap the include in `dlc_3d.html`**

Edit `dlc-3D/src/templates/dlc_3d.html` line 21:

```diff
-    {% include "partials/card_viewer.html" %}
+    {% include "partials/card_viewer_3d.html" %}
```

- [ ] **Step 3: Sanity-check the rename was complete**

Run from the support repo root:

```bash
grep -nE '\bva-' dlc-3D/src/templates/partials/card_viewer_3d.html
```

Expected: no output (every `va-` is now `va3d-`). If any matches, inspect and fix.

- [ ] **Step 4: Rebuild dlc-3d image**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
```

Expected: build succeeds; `docker compose ps` shows dlc-3d running.

- [ ] **Step 5: Manual smoke — card markup loads**

Visit `http://localhost:5000/dlc-3d/` in a browser, click the View-Analyzed nav button. The forked card should open. The card body will be inert (no JS wired yet) — this is expected.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_viewer_3d.html dlc-3D/src/templates/dlc_3d.html
git commit -m "$(cat <<'EOF'
feat(dlc-3d): fork card_viewer.html as card_viewer_3d.html (id rename only)

Mechanical fork of the upstream View Analyzed Videos / Frames card. All
va-* ids → va3d-*; section id → view-analyzed-3d-card. No behavior
change; viewer_3d.js wiring lands in the next task.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Fork the viewer module (`viewer_3d.js`) — single-cam parity

**Files:**
- Create: `dlc-3D/src/static/viewer_3d.js`
- Modify: `dlc-3D/src/templates/dlc_3d.html`
- Create: `dlc-3D/tests/e2e/test_analyzed_viewer.py` (single-cam parity test only)

Mechanical fork of `static/js/viewer.js` with the same id rename. After this task the dlc-3D analyzed card behaves identically to the upstream card for single-cam videos.

- [ ] **Step 1: Copy and rename**

```bash
cp /home/sam/docker-images/deeplabcut-webapp-docker/src/static/js/viewer.js \
   /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/viewer_3d.js
sed -i 's/\bva-/va3d-/g; s/view-analyzed-card/view-analyzed-3d-card/g; s/btn-close-view-analyzed/btn-close-view-analyzed-3d/g' \
   /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/viewer_3d.js
```

- [ ] **Step 2: Wire the new module in the template**

Edit `dlc-3D/src/templates/dlc_3d.html` `{% block scripts %}` — add the viewer_3d.js script tag after `enhanced_player.js`:

```diff
 <script type="module" src="{{ url_for('dlc_3d.static', filename='enhanced_player.js') }}"></script>
+<script type="module" src="{{ url_for('dlc_3d.static', filename='viewer_3d.js') }}"></script>
 <script type="module" src="{{ url_for('dlc_3d.static', filename='dlc_3d.js') }}"></script>
```

Note: the main webapp's `viewer.js` is loaded by `base.html`. Because it queries the upstream `va-*` ids and we renamed them all to `va3d-*`, the upstream module will silently no-op on this page — which is the desired isolation. Do not edit `base.html`.

- [ ] **Step 3: Write the single-cam parity e2e test**

```python
# dlc-3D/tests/e2e/test_analyzed_viewer.py
"""E2E tests for the dlc-3D analyzed frame/video viewer."""
import pytest

OPEN_BTN_TEXT = "View Analyzed"  # nav button label in base.html


def _open_card(page):
    page.click(f"button:has-text('{OPEN_BTN_TEXT}')")
    page.wait_for_selector("#view-analyzed-3d-card:not(.hidden)", timeout=5000)


def test_card_opens_and_lists_project_content(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    # Project Content tab is the default; list should populate.
    page.wait_for_selector("#va3d-content-list a, #va3d-content-list .explorer-empty",
                           timeout=10000)
    # Must NOT be the "Loading…" placeholder anymore.
    initial_text = page.text_content("#va3d-content-list")
    assert "Loading…" not in initial_text


def test_close_button_hides_card(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    page.click("#btn-close-view-analyzed-3d")
    page.wait_for_selector("#view-analyzed-3d-card.hidden", timeout=2000)
```

- [ ] **Step 4: Rebuild and run the e2e test**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: 2 passed. If skipped, check that the OM-2 fixture project is reachable per `tests/e2e/conftest.py`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/viewer_3d.js dlc-3D/src/templates/dlc_3d.html dlc-3D/tests/e2e/test_analyzed_viewer.py
git commit -m "$(cat <<'EOF'
feat(dlc-3d): fork viewer.js as viewer_3d.js (id rename only)

Mechanical fork of the upstream viewer module. Every va-* id is renamed
to va3d-*; the upstream module on base.html silently no-ops on the
dlc-3D page because its queryselectors miss. Single-cam parity verified
by new e2e test.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Restructure the player section into a tile row

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_viewer_3d.html` — replace single `va3d-video-wrap` with a `va3d-tile-row` containing one tile.
- Create: `dlc-3D/src/static/viewer_3d.css`
- Modify: `dlc-3D/src/templates/dlc_3d.html` — load the new css.
- Modify: `dlc-3D/src/static/viewer_3d.js` — query the tile-scoped img/canvas via the primary tile.

This task introduces the markup but keeps a single tile (cam0). No behavior change. Sets up the DOM for Task 5 to drop in the sibling tile.

- [ ] **Step 1: Replace the video wrap markup**

In `card_viewer_3d.html`, find the block:

```html
<div id="va3d-video-wrap" style="position:relative;background:#000;border-radius:8px;border:1px solid var(--border);margin-bottom:.25rem">
  <img id="va3d-frame-img" alt="" draggable="false" style="width:100%;display:block;height:auto" />
  <canvas id="va3d-overlay-canvas" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none"></canvas>
  <div id="va3d-frame-spinner" class="fe-frame-spinner hidden"></div>
</div>
```

Replace it with:

```html
<div id="va3d-tile-row" class="va3d-tile-row">
  <div class="va3d-tile focused" data-cam="0" data-weight="100" style="flex-grow:100">
    <div class="va3d-tile-header">
      <span class="va3d-tile-label" id="va3d-tile-label-0"></span>
      <span class="va3d-tile-pill hidden" id="va3d-tile-pill-0"></span>
      <input type="range" class="va3d-tile-size" min="50" max="500" step="25" value="100">
      <span class="va3d-tile-size-val">100%</span>
    </div>
    <div class="va3d-tile-canvas-wrap" id="va3d-video-wrap-0"
         style="position:relative;background:#000;border-radius:8px;border:1px solid var(--border)">
      <img id="va3d-frame-img-0" class="va3d-frame-img" alt="" draggable="false"
           style="width:100%;display:block;height:auto" />
      <canvas id="va3d-overlay-canvas-0" class="va3d-overlay-canvas"
              style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none"></canvas>
      <div id="va3d-frame-spinner-0" class="fe-frame-spinner hidden"></div>
    </div>
  </div>
</div>
```

Add an Equalize button next to the Viewer-size controls row (find the existing `va3d-zoom` label block and append):

```html
<button id="va3d-equalize-btn" class="btn-sm hidden" title="Reset all per-camera viewer sizes to equal" style="font-size:.75rem;padding:.2rem .55rem;margin-left:.4rem">
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
  Equalize
</button>
```

- [ ] **Step 2: Create the tile CSS**

```css
/* dlc-3D/src/static/viewer_3d.css */
.va3d-tile-row {
  display: flex;
  gap: .5rem;
  margin-bottom: .25rem;
  align-items: flex-start;
}
.va3d-tile {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex-basis: 0;
  flex-grow: 100;
}
.va3d-tile-header {
  display: flex;
  align-items: center;
  gap: .35rem;
  font-size: .72rem;
  color: var(--text-dim);
  margin-bottom: .2rem;
  min-height: 1.4rem;
}
.va3d-tile-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--mono);
}
.va3d-tile-pill {
  font-size: .65rem;
  padding: .05rem .35rem;
  border-radius: 3px;
  background: var(--surface);
  color: var(--text-dim);
  border: 1px solid var(--border);
  flex-shrink: 0;
}
.va3d-tile-size { width: 70px; accent-color: var(--accent); }
.va3d-tile-size-val { min-width: 2.6rem; text-align: right; font-family: var(--mono); }
.va3d-tile.focused .va3d-tile-canvas-wrap {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
```

- [ ] **Step 3: Load the new CSS**

In `dlc-3D/src/templates/dlc_3d.html` `{% block extra_head %}`:

```diff
 <link rel="stylesheet" href="{{ url_for('dlc_3d.static', filename='dlc_3d.css') }}">
+<link rel="stylesheet" href="{{ url_for('dlc_3d.static', filename='viewer_3d.css') }}">
```

- [ ] **Step 4: Repoint id queries in viewer_3d.js**

The forked module currently queries `#va3d-frame-img`, `#va3d-overlay-canvas`, `#va3d-frame-spinner`. Update each unique reference to the tile-0 suffix. Use a single targeted edit:

```bash
sed -i \
  -e "s/getElementById('va3d-frame-img')/getElementById('va3d-frame-img-0')/g" \
  -e "s/getElementById(\"va3d-frame-img\")/getElementById(\"va3d-frame-img-0\")/g" \
  -e "s/getElementById('va3d-overlay-canvas')/getElementById('va3d-overlay-canvas-0')/g" \
  -e "s/getElementById(\"va3d-overlay-canvas\")/getElementById(\"va3d-overlay-canvas-0\")/g" \
  -e "s/getElementById('va3d-frame-spinner')/getElementById('va3d-frame-spinner-0')/g" \
  -e "s/getElementById(\"va3d-frame-spinner\")/getElementById(\"va3d-frame-spinner-0\")/g" \
  -e "s/getElementById('va3d-video-wrap')/getElementById('va3d-video-wrap-0')/g" \
  -e "s/getElementById(\"va3d-video-wrap\")/getElementById(\"va3d-video-wrap-0\")/g" \
  /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/viewer_3d.js

grep -nE "va3d-(frame-img|overlay-canvas|frame-spinner|video-wrap)['\"]" \
  /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/viewer_3d.js
```

Expected from the grep: only matches with `-0` suffix. If any unsuffixed remain, fix manually.

- [ ] **Step 5: Rebuild + e2e**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: existing 2 tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D/src/templates dlc-3D/src/static
git commit -m "$(cat <<'EOF'
refactor(dlc-3d): restructure analyzed-viewer player into tile row

Wraps the single img+canvas in a flex tile-row with one tile (cam0),
header (label · size slider · pill), and a focus-ring style. No
behavior change — sets up DOM for sync-cam sibling tile.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Tile abstraction + sibling tile + Sync Cam toggle

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js` — extract `Tile` and `ViewerController`.
- Modify: `dlc-3D/src/templates/partials/card_viewer_3d.html` — add Sync Cam toggle in the controls row.
- Modify: `dlc-3D/tests/e2e/test_analyzed_viewer.py` — add dual-cam load test.

The existing forked module is monolithic. Introduce `class Tile` (per-cam DOM + state) and `class ViewerController` (singleton holding `tiles[]`). The first tile clones from the existing tile-0 markup; the second tile is created by cloning a `<template>` when sibling is detected.

- [ ] **Step 1: Add a hidden tile `<template>` to the markup**

After the `va3d-tile-row` div in `card_viewer_3d.html`:

```html
<template id="va3d-tile-template">
  <div class="va3d-tile" data-cam="" data-weight="100" style="flex-grow:100">
    <div class="va3d-tile-header">
      <span class="va3d-tile-label"></span>
      <span class="va3d-tile-pill hidden"></span>
      <input type="range" class="va3d-tile-size" min="50" max="500" step="25" value="100">
      <span class="va3d-tile-size-val">100%</span>
    </div>
    <div class="va3d-tile-canvas-wrap"
         style="position:relative;background:#000;border-radius:8px;border:1px solid var(--border)">
      <img class="va3d-frame-img" alt="" draggable="false" style="width:100%;display:block;height:auto" />
      <canvas class="va3d-overlay-canvas" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none"></canvas>
      <div class="fe-frame-spinner va3d-frame-spinner hidden"></div>
    </div>
  </div>
</template>
```

Add a Sync Cam checkbox in the existing controls row (next to Marker size). Find the `va3d-zoom` label block and append:

```html
<label id="va3d-sync-cam-label" style="display:none;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim);cursor:pointer;user-select:none">
  <input type="checkbox" id="va3d-sync-cam">
  Sync Cam
</label>
```

- [ ] **Step 2: Refactor viewer_3d.js — introduce Tile and ViewerController**

Add near the top of `viewer_3d.js` (after imports, before existing code):

```javascript
// ─── Tile abstraction ───────────────────────────────────────────────────────
class Tile {
  constructor(cam, rootEl) {
    this.cam      = cam;                    // 0 or 1
    this.rootEl   = rootEl;                 // .va3d-tile
    this.imgEl    = rootEl.querySelector('.va3d-frame-img');
    this.canvasEl = rootEl.querySelector('.va3d-overlay-canvas');
    this.wrapEl   = rootEl.querySelector('.va3d-tile-canvas-wrap');
    this.labelEl  = rootEl.querySelector('.va3d-tile-label');
    this.pillEl   = rootEl.querySelector('.va3d-tile-pill');
    this.spinnerEl= rootEl.querySelector('.va3d-frame-spinner');
    this.sliderEl = rootEl.querySelector('.va3d-tile-size');
    this.sliderValEl = rootEl.querySelector('.va3d-tile-size-val');
    this.weight   = 100;
    this.videoRel = null;
    this.primaryH5Path = null;
    this.comparisonLayers = [];
    this.pendingEdits = new Map();   // frame → { bodypart → {x,y} }
    this.markersByFrame = new Map(); // frame → markers
  }
  setLabel(text) { this.labelEl.textContent = text; }
  setPill(text) {
    if (text) { this.pillEl.textContent = text; this.pillEl.classList.remove('hidden'); }
    else      { this.pillEl.classList.add('hidden'); }
  }
  setWeight(w) {
    this.weight = w;
    this.rootEl.dataset.weight = String(w);
    this.rootEl.style.flexGrow = String(w);
    this.sliderEl.value = String(w);
    this.sliderValEl.textContent = `${w}%`;
  }
}

// ─── ViewerController singleton ────────────────────────────────────────────
const Controller = {
  tiles: [],
  currentFrame: 0,
  syncOn: false,
  primaryVideoRel: null,
  siblingVideoRel: null,

  init() {
    const tile0Root = document.querySelector('#va3d-tile-row .va3d-tile');
    if (!tile0Root) return;
    this.tiles = [new Tile(0, tile0Root)];
    this._wireFocus(this.tiles[0]);
  },

  async loadVideo(videoRel) {
    this.primaryVideoRel = videoRel;
    this.tiles[0].videoRel = videoRel;
    this.tiles[0].setLabel(videoRel.split('/').pop());
    // Probe sibling
    const r = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoRel)}`);
    const j = await r.json();
    this.siblingVideoRel = j.sibling_video_path || null;
    this._renderSiblingTile();
  },

  _renderSiblingTile() {
    const lbl = document.getElementById('va3d-sync-cam-label');
    const cb  = document.getElementById('va3d-sync-cam');
    const eq  = document.getElementById('va3d-equalize-btn');
    if (!this.siblingVideoRel) {
      // Hide sibling tile if present
      if (this.tiles.length > 1) {
        this.tiles[1].rootEl.remove();
        this.tiles = this.tiles.slice(0, 1);
      }
      lbl.style.display = 'inline-flex';
      cb.checked = false;
      cb.disabled = true;
      lbl.title = 'no sibling cam detected';
      eq.classList.add('hidden');
      this.syncOn = false;
      return;
    }
    lbl.style.display = 'inline-flex';
    cb.checked = true;
    cb.disabled = false;
    lbl.title = '';
    this.syncOn = true;
    eq.classList.remove('hidden');
    this._ensureSiblingTile();
  },

  _ensureSiblingTile() {
    if (this.tiles.length === 2) return;
    const tpl = document.getElementById('va3d-tile-template');
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.cam = '1';
    document.getElementById('va3d-tile-row').appendChild(node);
    const tile = new Tile(1, node);
    tile.videoRel = this.siblingVideoRel;
    tile.setLabel(this.siblingVideoRel.split('/').pop());
    this.tiles.push(tile);
    this._wireFocus(tile);
  },

  _removeSiblingTile() {
    if (this.tiles.length < 2) return;
    this.tiles[1].rootEl.remove();
    this.tiles = this.tiles.slice(0, 1);
  },

  _wireFocus(tile) {
    tile.rootEl.addEventListener('mousedown', () => this.focusTile(tile.cam));
  },
  focusTile(cam) {
    this.tiles.forEach(t => t.rootEl.classList.toggle('focused', t.cam === cam));
  },
};

window.__va3dController = Controller;  // for e2e introspection
document.addEventListener('DOMContentLoaded', () => Controller.init());
```

Wire the Sync Cam checkbox at the end of the existing init block in `viewer_3d.js`:

```javascript
document.getElementById('va3d-sync-cam')?.addEventListener('change', (e) => {
  if (e.target.checked && Controller.siblingVideoRel) {
    Controller._ensureSiblingTile();
    Controller.syncOn = true;
  } else {
    Controller._removeSiblingTile();
    Controller.syncOn = false;
  }
});
```

Hook `Controller.loadVideo(videoRel)` into the existing `va3d-` "select a video" code path. Find the existing function that runs after the user picks a video from the project-content list (search for `va3d-frame-img-0` assignment; the function setting `img.src` for the first frame is the entry point) and call `await Controller.loadVideo(videoPath)` immediately before the first frame load.

- [ ] **Step 3: Add the dual-cam e2e test**

Append to `dlc-3D/tests/e2e/test_analyzed_viewer.py`:

```python
SYNC_VIDEO_HINT = "OM-2_cam0_20260424"  # picks the cam0 video from the OM-2 fixture


def _select_sync_video(page):
    """Click the first cam0 video in the Project Content list."""
    page.click(f"#va3d-content-list a:has-text('{SYNC_VIDEO_HINT}')")
    page.wait_for_function(
        "() => window.__va3dController && window.__va3dController.tiles.length > 0",
        timeout=10000,
    )


def test_sync_cam_auto_on_when_sibling_exists(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    # Wait for sibling probe + tile creation
    page.wait_for_function(
        "() => window.__va3dController.tiles.length === 2",
        timeout=5000,
    )
    assert page.is_checked("#va3d-sync-cam")
    tiles = page.query_selector_all("#va3d-tile-row .va3d-tile")
    assert len(tiles) == 2


def test_sync_cam_toggle_collapses_to_single_tile(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.uncheck("#va3d-sync-cam")
    page.wait_for_function("() => window.__va3dController.tiles.length === 1", timeout=2000)
```

- [ ] **Step 4: Rebuild + run all e2e tests**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: 4 passed. (If the Project Content list does not show OM-2 cam0, ensure the DLC project is the OM-2 fixture path from `tests/e2e/conftest.py`.)

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D/src
git commit -m "$(cat <<'EOF'
feat(dlc-3d): sibling tile auto-spawns on sync-cam videos

Adds Tile + ViewerController abstractions to viewer_3d.js. On video
load the controller probes /dlc-3d/sibling-camera and clones the tile
template when a sibling is found. Sync Cam checkbox toggles
sibling tile presence; auto-on when sibling detected, disabled when
none.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frame-locked seek and play across tiles

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js` — route the existing seek/play code through `Controller.seek(n)` so all tiles tick together.
- Modify: `dlc-3D/tests/e2e/test_analyzed_viewer.py` — add frame-lock test.

The forked module already drives a single tile's frame loading via the seek slider, prev/next buttons, play loop, and skip-N. Wrap each of those handlers so they call `Controller.seek(n)` instead of touching tile-0 directly.

- [ ] **Step 1: Implement Controller.seek and Tile.loadFrame**

Add to `viewer_3d.js`, in the Controller object:

```javascript
async seek(n) {
  this.currentFrame = n;
  await Promise.all(this.tiles.map(t => this._loadFrameOnTile(t, n)));
},

async _loadFrameOnTile(tile, frame) {
  if (!tile.videoRel) return;
  tile.spinnerEl.classList.remove('hidden');
  try {
    const url = `/dlc-3d/frame?video=${encodeURIComponent(tile.videoRel)}&n=${frame}`;
    tile.imgEl.src = url;
    await new Promise((res, rej) => {
      tile.imgEl.onload  = res;
      tile.imgEl.onerror = rej;
    });
  } catch (e) {
    tile.setPill('frame load failed');
  } finally {
    tile.spinnerEl.classList.add('hidden');
  }
},
```

- [ ] **Step 2: Replace single-tile frame-load calls with Controller.seek**

Search `viewer_3d.js` for the existing places that set `imgEl.src` or push a new frame number after seek/play/skip. Replace each with `await Controller.seek(newFrame)`. The existing frame-counter / time-display update code can keep reading `Controller.currentFrame` — leave it as-is and just stop touching the tile-0 img directly.

- [ ] **Step 3: Add frame-lock e2e test**

```python
# Append to dlc-3D/tests/e2e/test_analyzed_viewer.py
def test_seek_advances_both_tiles(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Wait for both tiles' first frames to load
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img'))"
        ".every(img => img.complete && img.naturalWidth > 0)",
        timeout=10000,
    )
    # Click the next-frame button several times; both tile imgs should advance
    src_before = page.evaluate("() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img')).map(i => i.src)")
    for _ in range(3):
        page.click("#va3d-btn-next")
    page.wait_for_function(
        "(prev) => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-frame-img'))"
        ".every((img, i) => img.src !== prev[i])",
        arg=src_before, timeout=5000,
    )
    # Both tiles must agree on the controller's currentFrame
    assert page.evaluate("() => window.__va3dController.currentFrame") > 0
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): frame-locked seek/play across analyzed-viewer tiles

Routes all seek/play/skip handlers through Controller.seek so both cam
tiles advance together. Verified by e2e test that clicks next-frame
three times and asserts both tile imgs change in lockstep.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Per-tile size sliders + Equalize

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js`
- Modify: `dlc-3D/tests/e2e/test_analyzed_viewer.py`

Mirrors the frame-labeler's per-tile `flex-grow` weight pattern. Each tile's slider sets its weight; Equalize resets both to 100. Weights persist across `loadFrame`/`setVideo` until Equalize.

- [ ] **Step 1: Wire per-tile slider changes**

Add to `Tile` constructor:

```javascript
this.sliderEl.addEventListener('input', (e) => this.setWeight(parseInt(e.target.value, 10)));
```

(Method `setWeight` already exists from Task 5.)

- [ ] **Step 2: Wire Equalize button**

In `viewer_3d.js` init:

```javascript
document.getElementById('va3d-equalize-btn')?.addEventListener('click', () => {
  Controller.tiles.forEach(t => t.setWeight(100));
});
```

- [ ] **Step 3: Add e2e for tile-weight independence**

```python
def test_per_tile_size_slider_updates_flex_grow(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Drag tile-1's slider to 200%
    page.evaluate("""() => {
      const s = document.querySelectorAll('#va3d-tile-row .va3d-tile-size')[1];
      s.value = 200;
      s.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    weights = page.evaluate(
      "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-tile')).map(t => t.style.flexGrow)"
    )
    assert weights == ['100', '200']
    # Click Equalize, both should return to 100
    page.click("#va3d-equalize-btn")
    weights = page.evaluate(
      "() => Array.from(document.querySelectorAll('#va3d-tile-row .va3d-tile')).map(t => t.style.flexGrow)"
    )
    assert weights == ['100', '100']
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): per-tile size sliders + Equalize on analyzed viewer

Each cam tile has its own size slider (50-500%, step 25) wired to
flex-grow weight; Equalize resets all tiles to 100. Mirrors the
fl3d-tile pattern from the frame labeler.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Layer-pair resolver — primary picker

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js`
- Modify: `dlc-3D/tests/e2e/test_analyzed_viewer.py`

When the user picks the primary h5, each tile should auto-resolve to its cam-specific h5 via `/dlc-3d/analyzed/sibling-h5`. If sibling resolution fails, the sibling tile shows a "no sibling h5 — overlay off" pill.

- [ ] **Step 1: Add the resolver helper**

Add to Controller:

```javascript
async _resolveLayerForTile(primaryH5Path, tile) {
  if (tile.cam === 0) return { path: primaryH5Path, exists: true };
  const r = await fetch(
    `/dlc-3d/analyzed/sibling-h5?primary_h5=${encodeURIComponent(primaryH5Path)}&cam=${tile.cam}`
  );
  return await r.json();
},

async setPrimaryLayer(primaryH5Path) {
  for (const tile of this.tiles) {
    const res = await this._resolveLayerForTile(primaryH5Path, tile);
    if (res.exists) {
      tile.primaryH5Path = res.path;
      tile.setPill('');
      // Trigger the existing single-tile h5-load logic for this tile
      await this._loadH5OnTile(tile);
    } else {
      tile.primaryH5Path = null;
      tile.setPill('no sibling h5 — overlay off');
    }
  }
},
```

`_loadH5OnTile(tile)` is the per-tile equivalent of the existing single-tile h5 load. The forked module already has the body — extract it into a helper that takes a tile and uses `tile.primaryH5Path` instead of the global path. Keep the existing global `va3d-overlay-h5-path` input synced with tile-0's path so the visible UI continues to reflect what the user picked.

- [ ] **Step 2: Hook the primary picker change**

Find the existing handler for `va3d-overlay-primary-select` change. Replace its body with:

```javascript
await Controller.setPrimaryLayer(selectedPath);
```

- [ ] **Step 3: e2e — pick a primary, both tiles get a pill or load**

```python
def test_primary_layer_pairs_to_both_tiles(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    # Toggle overlay on
    page.check("#va3d-overlay-toggle")
    # Pick the first option in the primary select (any cam0 h5 from the OM-2 fixture)
    has_h5 = page.evaluate("() => document.querySelectorAll('#va3d-overlay-primary-select option').length > 1")
    if not has_h5:
        pytest.skip("OM-2 fixture has no analyzed h5 to pick")
    page.evaluate("""() => {
      const s = document.getElementById('va3d-overlay-primary-select');
      s.selectedIndex = 1;
      s.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    # Wait until the controller has assigned a primary path to each tile (or set a pill)
    page.wait_for_function(
      "() => window.__va3dController.tiles.every(t => t.primaryH5Path !== undefined)",
      timeout=5000,
    )
    states = page.evaluate(
      "() => window.__va3dController.tiles.map(t => ({path: t.primaryH5Path, pill: t.pillEl.textContent}))"
    )
    # cam0 must have a path; cam1 must have either a path or the pill text
    assert states[0]['path'], states
    assert states[1]['path'] or 'no sibling h5' in states[1]['pill'], states
```

- [ ] **Step 4: Rebuild + test**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: 7 passed (1 may skip if the fixture lacks h5 files).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): pair primary overlay h5 across analyzed-viewer tiles

setPrimaryLayer auto-resolves the cam-specific h5 for each tile via
/dlc-3d/analyzed/sibling-h5 and triggers per-tile load. Missing sibling
h5 shows a pill in the sibling tile header; primary tile keeps
rendering.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Layer-pair resolver — comparison layers

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js`

Apply the same pairing logic to comparison layers (the "+ add comparison…" select and the comparison list rows).

- [ ] **Step 1: Generalize the resolver**

Refactor `setPrimaryLayer` and add `addComparisonLayer(layerPath)` / `removeComparisonLayer(layerPath)` on the Controller; each calls `_resolveLayerForTile` per tile and updates `tile.comparisonLayers[]`.

- [ ] **Step 2: Hook the existing add/remove comparison handlers**

Find the existing `va3d-overlay-add-compare` change handler. Replace `addLayerToList(...)` calls with `await Controller.addComparisonLayer(path)`. Same for the remove buttons in the comparison list rows: route through `Controller.removeComparisonLayer(path)`.

For each tile, comparison rendering loops over `tile.comparisonLayers` instead of a global list.

- [ ] **Step 3: Manual verify**

Rebuild, open a sync video, enable overlay, pick a primary, then add a comparison from the dropdown. The comparison should render on both tiles (with sibling pill if its sibling h5 missing).

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): pair comparison overlay layers across analyzed-viewer tiles

Each comparison layer is added/removed via the controller, which
resolves the cam-specific h5 per tile and renders independently.
Mirrors the primary-layer pairing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Per-cam editing on each tile

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js`
- Modify: `dlc-3D/tests/e2e/test_analyzed_viewer.py`

Each tile is independently editable. Marker placement / drag / right-click delete acts on whichever tile is focused (the `focused` class set by mousedown). Pending edits are stored per tile.

- [ ] **Step 1: Generalize the existing edit handlers**

The forked module currently attaches edit handlers to `va3d-overlay-canvas-0` directly. Instead, in the `Tile` constructor, attach those same handlers to `tile.canvasEl`, with all reads/writes going through `tile.pendingEdits` and `tile.markersByFrame`.

- [ ] **Step 2: Combined banner**

Update the marker-edit banner update function so its count text is:

```javascript
const c0 = Controller.tiles[0]?.pendingEdits.size || 0;
const c1 = Controller.tiles[1]?.pendingEdits.size || 0;
const text = Controller.tiles.length > 1
  ? `cam0: ${c0} · cam1: ${c1} frames edited`
  : `${c0} frames edited`;
document.getElementById('va3d-marker-edit-count').textContent = text;
document.getElementById('va3d-marker-edit-banner').classList.toggle('hidden', (c0 + c1) === 0);
```

- [ ] **Step 3: Per-tile "edit disabled while comparing" banner**

The forked module already shows `va3d-overlay-edit-disabled-banner` when comparison layers exist. Make this per-tile by injecting a small `<span>` into each tile header when `tile.comparisonLayers.length > 0`. Keep the original global banner in place too (it documents the rule even when both tiles are comparing).

- [ ] **Step 4: e2e — edit on each tile, banner shows split**

```python
def test_per_cam_edits_show_split_count(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.check("#va3d-overlay-toggle")
    # Need a primary picked + a body part selected — skip if fixture lacks h5
    has_h5 = page.evaluate("() => document.querySelectorAll('#va3d-overlay-primary-select option').length > 1")
    if not has_h5:
        pytest.skip("OM-2 fixture has no analyzed h5")
    page.evaluate("""() => {
      const s = document.getElementById('va3d-overlay-primary-select');
      s.selectedIndex = 1;
      s.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    page.wait_for_function("() => Array.from(document.querySelectorAll('#va3d-bp-chips .bp-chip')).length > 0", timeout=5000)
    page.click("#va3d-bp-chips .bp-chip:first-child")
    # Click on each tile's canvas to add an edit
    canvases = page.query_selector_all("#va3d-tile-row .va3d-overlay-canvas")
    canvases[0].click(position={"x": 50, "y": 50})
    canvases[1].click(position={"x": 60, "y": 60})
    page.wait_for_function(
      "() => /cam0: \\d+ . cam1: \\d+/.test(document.getElementById('va3d-marker-edit-count').textContent)",
      timeout=2000,
    )
```

- [ ] **Step 5: Rebuild + test, commit**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: 8 passed (one may skip).

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): per-cam editing on each analyzed-viewer tile

Each tile's canvas owns its own edit handlers and pendingEdits map.
The combined marker-edit banner shows split counts: 'cam0: N · cam1:
M frames edited'.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Save Adjustments — parallel per-cam writes

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js`

Save Adjustments collects pending edits from each tile and posts to `/dlc/viewer/save-marker-edits` once per tile (per h5/csv pair). Discards clears both. Status message reports per-cam success or failure.

- [ ] **Step 1: Implement parallel save**

Replace the existing `va3d-save-adjustments-btn` click handler body with:

```javascript
async function saveAdjustments() {
  const status = document.getElementById('va3d-status');
  status.textContent = 'Saving…';
  const results = await Promise.allSettled(Controller.tiles.map(async (tile) => {
    if (tile.pendingEdits.size === 0) return { cam: tile.cam, ok: true, skipped: true };
    if (!tile.primaryH5Path) return { cam: tile.cam, ok: false, error: 'no h5 for this cam' };
    const body = {
      h5: tile.primaryH5Path,
      edits: Array.from(tile.pendingEdits.entries()).map(([frame, parts]) => ({ frame, parts })),
    };
    const r = await fetch('/dlc/viewer/save-marker-edits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) return { cam: tile.cam, ok: false, error: await r.text() };
    return { cam: tile.cam, ok: true };
  }));
  // Clear pending for cams that succeeded
  results.forEach((res, i) => {
    if (res.status === 'fulfilled' && res.value.ok && !res.value.skipped) {
      Controller.tiles[i].pendingEdits.clear();
    }
  });
  // Re-render banner
  refreshMarkerBanner();
  // Status
  const summary = results.map((res, i) => {
    const v = res.status === 'fulfilled' ? res.value : { cam: i, ok: false, error: res.reason };
    return v.ok ? `cam${v.cam} ✓` : `cam${v.cam} ✗ ${v.error || ''}`;
  }).join(' · ');
  status.textContent = summary;
}
document.getElementById('va3d-save-adjustments-btn').addEventListener('click', saveAdjustments);
```

`refreshMarkerBanner()` is the function from Task 10 step 2.

- [ ] **Step 2: Discard clears both**

```javascript
document.getElementById('va3d-discard-adjustments-btn').addEventListener('click', () => {
  Controller.tiles.forEach(t => t.pendingEdits.clear());
  refreshMarkerBanner();
});
```

- [ ] **Step 3: Manual verify**

Rebuild. Place an edit on each tile, click Save Adjustments, confirm the status reads `cam0 ✓ · cam1 ✓`, banner clears. Then place an edit on cam1 only with no h5 (simulate by clearing the primary), click Save, confirm status shows `cam0 ✓ · cam1 ✗ no h5 for this cam`.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): parallel per-cam Save Adjustments on analyzed viewer

Save Adjustments fans out to one /dlc/viewer/save-marker-edits call per
tile in parallel and aggregates results into a per-cam status line.
Discard clears both tiles' pendingEdits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Companion CSV — primary cam only

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js`
- Modify: `dlc-3D/src/templates/partials/card_viewer_3d.html`

Per the spec, the companion CSV stays single-source on the primary cam. The forked code already drives a single CSV from a single video path; we just need to keep it pointing at `Controller.primaryVideoRel` rather than any per-tile state.

- [ ] **Step 1: Audit references**

Search `viewer_3d.js` for any place where the video path used for `/annotate/csv?path=...` or `/annotate/save-row` is derived. Confirm it reads from a single source (e.g. a `currentVideoPath` variable or directly from the project-content list selection). If any post-Task-5 refactor leaks tile-specific paths in, fix to always use `Controller.primaryVideoRel`.

```bash
grep -n "annotate/csv\|annotate/save-row\|annotate/create-csv" dlc-3D/src/static/viewer_3d.js
```

For each match, verify the video path argument is the primary cam path.

- [ ] **Step 2: Confirm metadata strip / status / note bars are global (single)**

In `card_viewer_3d.html`, the markup for `va3d-metadata-panel`, `va3d-status-bar-wrap`, `va3d-note-bar-wrap`, and `va3d-annot-panel` should remain outside the `va3d-tile-row` (not duplicated per tile). If the Task 4/5 restructure accidentally moved any of these inside the tile, move them back to the position they have in the upstream `card_viewer.html` (above/below the tile row, not inside it).

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
chore(dlc-3d): keep companion CSV single-source on primary cam

Verifies the analyzed-viewer's /annotate/* calls always use the
primary cam's video path; metadata / status / note / annotate panels
remain outside the tile row (no per-tile duplication).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Dataset Curation — Both cams checkbox + paired calls

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_viewer_3d.html` — add Both-cams checkbox.
- Modify: `dlc-3D/src/static/viewer_3d.js`
- Modify: `dlc-3D/tests/e2e/test_analyzed_viewer.py`

In sync mode, Extract Frame / +Add to Dataset / Batch Add each become two parallel calls to the existing `/dlc/curator/extract-frame` (and `/dlc/curator/add-to-dataset`) endpoints — one per cam — when "Both cams" is checked. The checkbox lives in the curation panel header, only visible when sync is on, default checked.

- [ ] **Step 1: Add the checkbox markup**

In `card_viewer_3d.html`, find the `va3d-curation-toggle` row inside `va3d-curation-panel`. Append after that row:

```html
<label id="va3d-both-cams-label" style="display:none;align-items:center;gap:.45rem;font-size:.78rem;color:var(--text-dim);cursor:pointer;user-select:none;margin-top:.4rem">
  <input type="checkbox" id="va3d-both-cams" checked style="accent-color:var(--accent);width:13px;height:13px"/>
  Extract from both cams
</label>
```

- [ ] **Step 2: Toggle visibility when sync changes**

Add to Controller, in `_renderSiblingTile`:

```javascript
const both = document.getElementById('va3d-both-cams-label');
both.style.display = this.siblingVideoRel ? 'inline-flex' : 'none';
```

Also wire the Sync Cam checkbox (from Task 5) to update this:

```javascript
document.getElementById('va3d-sync-cam')?.addEventListener('change', (e) => {
  // ... existing body ...
  document.getElementById('va3d-both-cams-label').style.display =
    e.target.checked ? 'inline-flex' : 'none';
});
```

- [ ] **Step 3: Wrap the curation calls**

For each of the three handlers (`va3d-extract-frame-btn`, `va3d-add-to-dataset-btn`, `va3d-batch-add-btn`), wrap the existing single-call body in a per-cam loop:

```javascript
async function curatorCall(endpoint, body) {
  const r = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return r.ok ? { ok: true, body: await r.json() } : { ok: false, error: await r.text() };
}

async function extractFrameClick() {
  const both = document.getElementById('va3d-both-cams').checked && Controller.tiles.length > 1;
  const targets = both ? Controller.tiles : [Controller.tiles[0]];
  const results = await Promise.allSettled(targets.map(t =>
    curatorCall('/dlc/curator/extract-frame', {
      video: t.videoRel,
      frame_number: Controller.currentFrame,
    })
  ));
  showCurationStatus(results, targets);
}
```

`showCurationStatus(results, targets)` writes a per-cam summary into `va3d-curation-status` (e.g. `cam0 ✓ · cam1 ✓ — 2 frames saved`). Apply the same wrapper to `add-to-dataset` and `batch-add` (Batch posts with the count/step body fields the existing endpoint already expects).

For Batch Add: stop on first sibling-side failure (per the spec edge case). Implement by awaiting the per-cam call sequentially inside the batch loop and breaking on `!ok`.

- [ ] **Step 4: e2e — Both cams default checked, click extract calls twice**

```python
def test_both_cams_checkbox_default_checked_in_sync(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.check("#va3d-curation-toggle")
    assert page.is_visible("#va3d-both-cams-label")
    assert page.is_checked("#va3d-both-cams")


def test_extract_frame_calls_endpoint_per_cam(page, base_url):
    page.goto(base_url, wait_until="domcontentloaded")
    _open_card(page)
    _select_sync_video(page)
    page.wait_for_function("() => window.__va3dController.tiles.length === 2", timeout=5000)
    page.check("#va3d-curation-toggle")
    # Intercept the curator endpoint
    calls = []
    page.route("**/dlc/curator/extract-frame", lambda route: (
      calls.append(route.request.post_data_json),
      route.fulfill(status=201, content_type="application/json", body='{"saved":[]}'),
    ))
    page.click("#va3d-extract-frame-btn")
    page.wait_for_function("() => true", timeout=500)  # let promises settle
    videos = sorted({c.get("video") for c in calls})
    assert len(videos) == 2, calls
```

- [ ] **Step 5: Rebuild + test**

```bash
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml build dlc-3d
docker compose -f /home/sam/docker-images/deeplabcut-webapp-docker/docker-compose.yml up -d dlc-3d
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): Both cams checkbox + paired curation calls

Sync mode adds an 'Extract from both cams' checkbox (default checked)
that gates Extract Frame, +Add to Dataset, and Batch Add. Each
operation fans out to one /dlc/curator/* call per cam. Per-cam
results are collated into the curation status line. Batch Add stops
on first sibling-side failure.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Edge cases and polish

**Files:**
- Modify: `dlc-3D/src/static/viewer_3d.js`

Cover the spec's edge cases that are not yet handled.

- [ ] **Step 1: Sibling video unreadable**

In `_loadFrameOnTile`, if the sibling tile's image errors AND `tile.cam !== 0`, show an inline error placeholder over the canvas (`tile.setPill('frame load failed')`) and do not break the primary tile's playback.

- [ ] **Step 2: Frame number out of range on sibling**

If `tile.cam !== 0` and the frame fetch returns 416 / 404, set `tile.setPill('frame N/A on sibling')` and stop trying to load further frames for that tile until the user changes video. Primary continues normally.

- [ ] **Step 3: Toggle Sync off mid-edit preserves pending edits**

When `_removeSiblingTile` is called, do NOT clear `tiles[1].pendingEdits` — instead detach the tile from the DOM but keep the Tile instance in a `_pendingSibling` slot. When `_ensureSiblingTile` runs next, restore that instance instead of creating a fresh one (only for the same `siblingVideoRel`; if the video changed, prompt for confirmation if `pendingEdits.size > 0` before discarding).

- [ ] **Step 4: Keyboard tile focus (1 / 2)**

Add a global keydown listener (scoped to when the analyzed-viewer card is open) that responds to digit-1 / digit-2 by calling `Controller.focusTile(0)` / `Controller.focusTile(1)`. Skip the listener if the event target is an input/textarea (existing pattern in viewer_3d.js).

```javascript
document.addEventListener('keydown', (e) => {
  if (document.getElementById('view-analyzed-3d-card').classList.contains('hidden')) return;
  if (e.target.matches('input, textarea, select')) return;
  if (e.key === '1') Controller.focusTile(0);
  if (e.key === '2' && Controller.tiles.length > 1) Controller.focusTile(1);
});
```

- [ ] **Step 5: Manual smoke through edge cases**

Rebuild. Reproduce each scenario by hand:
- Open a video with no sibling — Sync Cam checkbox is shown but disabled.
- Pick a primary h5 that has no sibling — sibling tile shows pill `no sibling h5 — overlay off`.
- Place an edit on cam1, toggle Sync off, toggle back on — banner still shows `cam1: 1`.

Document any edge case that doesn't behave as the spec describes by adding a TODO comment in viewer_3d.js next to the relevant function and surfacing it in the Task 15 final-smoke notes.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add -A dlc-3D
git commit -m "$(cat <<'EOF'
feat(dlc-3d): handle sibling-tile edge cases on analyzed viewer

Sibling video unreadable / frame out of range surface as per-tile
pills without breaking primary playback. Toggling Sync off mid-edit
preserves pending edits; reopening restores them. Switching the
primary video while sibling has unsaved edits prompts for confirm.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Final smoke checklist + cleanup

**Files:**
- (none new — verification only)

Walk the spec's testing checklist top to bottom against the running stack. File any deferred follow-ups as new commits or open items in `docs/superpowers/plans/` (do not silently skip).

- [ ] **Step 1: Single-cam parity**

Open a non-sync-cam video. Card behaves identically to upstream `card_viewer.html` (overlay, edit, save, extract, batch, annotation). Sibling tile must NOT appear; Both-cams checkbox hidden.

- [ ] **Step 2: Sync video — both tiles, frame lock, layer pair**

Open OM-2 cam0 video. Two tiles appear, frame-locked. Pick a primary h5; both tiles show overlay (or sibling pill). Threshold and marker-size sliders apply to both.

- [ ] **Step 3: Extract / Add / Batch with Both cams**

With Both-cams checked, click Extract Frame — both labeled-data folders gain a PNG. Click +Add to Dataset — both CSVs gain a row. Run Batch Add count=2 step=10 — four PNGs total.

- [ ] **Step 4: Annotate writes only to primary cam CSV**

Save a status and a note. Verify only `<primary>_annotations.csv` (or whichever the upstream convention is) contains the row; the sibling cam's labeled-data does not.

- [ ] **Step 5: Per-cam edit + Save Adjustments**

Place an edit on each tile. Banner shows `cam0: 1 · cam1: 1`. Save Adjustments writes both files; status shows `cam0 ✓ · cam1 ✓`. Discard clears both.

- [ ] **Step 6: Missing sibling h5**

Pick a primary h5 whose sibling does not exist on disk. Primary tile renders overlay; sibling tile shows the `no sibling h5 — overlay off` pill.

- [ ] **Step 7: Toggle sync off and on with pending edits**

Sync off → tile collapses, banner still shows cam1's count. Sync on → tile reappears with edits intact.

- [ ] **Step 8: Run all automated tests one more time**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
pytest dlc-3D/tests/unit/ -v
pytest dlc-3D/tests/e2e/test_analyzed_viewer.py -v
```

Expected: all green.

- [ ] **Step 9: Final commit (if any cleanup)**

If any small fix is needed during smoke, commit it with a `fix(dlc-3d): ...` message. Otherwise no-op.

---
