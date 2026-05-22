# Inline 3D Focused-Tile Marker Editing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the sibling camera tile(s) in the inline 3D card hand-editable (drag/place/delete markers), so cam1 can be corrected like cam0, persisting per-camera. Minimal-change: tile-0's working editing and the entire render pipeline's canvas-sizing are left untouched.

**Architecture:** Add sibling-tile edit handlers that mirror tile-0's existing handlers but operate on the sibling `Tile`'s own `canvasEl`/`imgEl`/`pendingEdits`/`layers[0].path`, via new per-tile coord/hit-test/flush helpers. Each tile edits the canvas you click (no cross-tile focus gate). Sibling marker display (`_renderTileMarkers`) is extended to overlay pending edits + the selected-bp ring. Save Adjustments persists every tile's edits.

**Tech Stack:** Vanilla JS (`inline_analysis_3d.js`); pytest static source-assertions (`tests/test_inline_analysis_3d_ui_isolation.py`).

---

## Conventions

- **Repo / dir:** all commands from `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D` (branch `feat/3d-inline-analysis` — do NOT branch).
- **No worker/backend change:** `/dlc/viewer/marker-edit` and `/dlc/viewer/save-marker-edits` already exist (per-h5). No container restart needed (Flask serves the static JS fresh).
- **Tests are static source-assertions** — read `inline_analysis_3d.js` text and assert substrings. No DOM runtime. The 3D guard file is `tests/test_inline_analysis_3d_ui_isolation.py` (constants `JS`, `CARD`, `PAGE`; `JS = ROOT/"src"/"static"/"inline_analysis_3d.js"`).
- **Reference — tile-0's existing handlers** live at `inline_analysis_3d.js:1418-1527` (click/mousedown/mousemove/mouseup/mouseleave/mouseenter/contextmenu). The sibling handlers mirror these, swapping globals for the tile's members. Read them before implementing.
- **Key existing pieces:** `class Tile` (line 5) with `canvasEl`/`imgEl`/`pendingEdits` (Map) / `layers`; `Controller` (line 129) with `focusTile`/`_wireFocus`/`_renderTileMarkers`/`seek`; sibling add path wires focus at lines ~234 and ~246; tile-0 globals `_iaCurrentFrame`, `_iaSelectedBp`, `_iaMarkerSize`, `_iaIsEditable()` (line 610: `_iaLayers.length === 1`), `_iaCanvasToVideo` (1331), `_iaHitTestWithEdits` (1340), `_iaSelectBp`, `_iaUpdateEditBanner`, `_iaUpdateBpChipStatus`.

---

## Task 1: Per-tile helpers + per-tile drag state

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (add helpers near `_iaCanvasToVideo`/`_iaHitTestWithEdits` ~line 1330-1358; add drag fields to `Tile` constructor ~line 5-26)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_per_tile_edit_helpers_exist():
    js = JS.read_text()
    assert "_ia3dTileCanvasToVideo" in js, "per-tile coord helper missing"
    assert "_ia3dTileHitTest" in js, "per-tile hit-test helper missing"
    assert "_ia3dFlushTileEdit" in js and "_ia3dFlushTileDelete" in js, "per-tile flush helpers missing"
    # helpers read the tile's own elements, not the tile-0 globals
    assert "tile.canvasEl" in js and "tile.imgEl" in js
    # per-tile drag state lives on the Tile instance
    assert "this.dragging" in js and "this.dragBp" in js
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_per_tile_edit_helpers_exist -v
```
Expected: FAIL.

- [ ] **Step 3a: Add per-tile drag state to the `Tile` constructor**

In `class Tile`'s constructor (after the `this.pendingEdits = new Map();` line ~26), add:

```javascript
    this.dragging = false;   // per-tile drag state (so tiles don't cross-trigger)
    this.dragBp   = null;
```

- [ ] **Step 3b: Add the per-tile helpers**

Add these functions adjacent to `_iaCanvasToVideo` / `_iaHitTestWithEdits` (around line 1358, same scope):

```javascript
    // Per-tile coord/hit-test/flush — same math as the tile-0 globals, but
    // reading the given tile's own canvas/img/layer/pendingEdits.
    function _ia3dTileCanvasToVideo(tile, cx, cy) {
      const natW = tile.imgEl.naturalWidth  || 1;
      const natH = tile.imgEl.naturalHeight || 1;
      const sx   = tile.canvasEl.width  / natW;
      const sy   = tile.canvasEl.height / natH;
      return { x: cx / sx, y: cy / sy };
    }

    function _ia3dTileHitTest(tile, cx, cy) {
      const layer = tile.layers && tile.layers[0];
      if (!layer) return null;
      const cached = layer.posesCache.get(_iaCurrentFrame);
      if (!cached) return null;
      const natW = tile.imgEl.naturalWidth  || 1;
      const natH = tile.imgEl.naturalHeight || 1;
      const sx   = tile.canvasEl.width  / natW;
      const sy   = tile.canvasEl.height / natH;
      const hitR = (_iaMarkerSize + 8) * Math.max(sx, sy);
      const frameEdits = tile.pendingEdits.get(_iaCurrentFrame) || {};
      for (const pose of cached.poses) {
        const edited = pose.bp in frameEdits;
        const px = (edited ? frameEdits[pose.bp].x : pose.x) * sx;
        const py = (edited ? frameEdits[pose.bp].y : pose.y) * sy;
        if (Math.hypot(px - cx, py - cy) <= hitR) return pose.bp;
      }
      return null;
    }

    async function _ia3dFlushTileEdit(tile, frame, bp, x, y) {
      if (!_iaIsEditable()) return;
      const layer = tile.layers && tile.layers[0];
      if (!layer) return;
      try {
        await fetch("/dlc/viewer/marker-edit", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ h5: layer.path, frame, bp, x, y }),
        });
      } catch (_) {}
    }

    async function _ia3dFlushTileDelete(tile, frame, bp) {
      return _ia3dFlushTileEdit(tile, frame, bp, null, null);
    }
```

- [ ] **Step 4: Run, verify PASS**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_per_tile_edit_helpers_exist -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): per-tile marker-edit coord/hit-test/flush helpers + tile drag state

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `Controller._wireSiblingEditing(tile)` + wire on sibling add

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (add `_wireSiblingEditing` to `Controller`; call it where siblings are wired ~lines 234 and 246; update the scope-note comment ~1403-1417)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

Note: `_wireSiblingEditing` is a `Controller` method, so its body uses arrow functions / refers to the module helpers `_ia3dTileCanvasToVideo`, `_ia3dTileHitTest`, `_ia3dFlushTileEdit`, `_ia3dFlushTileDelete`, `_iaSelectBp`, `_iaIsEditable`, `_iaSelectedBp`, `_iaCurrentFrame`, `_iaUpdateEditBanner`, `_iaUpdateBpChipStatus`, and `this._renderTileMarkers(tile)`. Those are all in scope (module-level / Controller). `_iaSelectedBp`/`_iaCurrentFrame` are read-only here.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_sibling_editing_wired():
    js = JS.read_text()
    assert "_wireSiblingEditing" in js, "sibling editing method missing"
    # called when a sibling tile is added (near the _wireFocus calls)
    assert js.count("_wireSiblingEditing(") >= 2, "must be defined and called at least once"
    # sibling handlers use the tile's own canvas + per-tile pendingEdits + flush
    i = js.find("_wireSiblingEditing(tile)")
    body = js[i:i + 2600]
    assert "tile.canvasEl.addEventListener" in body
    assert "tile.pendingEdits" in body
    assert "_ia3dFlushTileEdit(tile" in body
    assert "_ia3dTileHitTest(tile" in body
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_sibling_editing_wired -v
```
Expected: FAIL.

- [ ] **Step 3a: Add `_wireSiblingEditing` to `Controller`**

Add this method to the `Controller` object (e.g. right after `_wireFocus`, ~line 261). It mirrors tile-0's handlers (`inline_analysis_3d.js:1418-1527`) for the sibling tile:

```javascript
  _wireSiblingEditing(tile) {
    if (tile.cam === 0 || tile._editWired) return;   // tile-0 keeps its own handlers
    tile._editWired = true;
    const canvas = tile.canvasEl;
    if (!canvas) return;
    canvas.style.pointerEvents = "auto";

    canvas.addEventListener("click", e => {
      if (typeof _iaOverlayEnabled === "undefined" || !_iaOverlayEnabled) return;
      const rect = canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      const hit = _ia3dTileHitTest(tile, cx, cy);
      if (hit) { _iaSelectBp(hit); return; }
      if (!_iaIsEditable() || !_iaSelectedBp) return;
      const { x, y } = _ia3dTileCanvasToVideo(tile, cx, cy);
      if (!tile.pendingEdits.has(_iaCurrentFrame)) tile.pendingEdits.set(_iaCurrentFrame, {});
      tile.pendingEdits.get(_iaCurrentFrame)[_iaSelectedBp] = { x, y };
      this._renderTileMarkers(tile);
      _ia3dFlushTileEdit(tile, _iaCurrentFrame, _iaSelectedBp, x, y);
      _iaUpdateEditBanner(); _iaUpdateBpChipStatus();
    });

    canvas.addEventListener("mousedown", e => {
      if (!_iaIsEditable() || !_iaOverlayEnabled || e.button !== 0) return;
      const rect = canvas.getBoundingClientRect();
      const hit = _ia3dTileHitTest(tile, e.clientX - rect.left, e.clientY - rect.top);
      if (!hit) return;
      e.preventDefault();
      tile.dragBp = hit; tile.dragging = true;
      canvas.style.cursor = "grabbing";
    });

    canvas.addEventListener("mousemove", e => {
      if (!_iaOverlayEnabled) return;
      const rect = canvas.getBoundingClientRect();
      const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
      if (tile.dragging && tile.dragBp) {
        if (!_iaIsEditable()) return;
        const { x, y } = _ia3dTileCanvasToVideo(tile, cx, cy);
        if (!tile.pendingEdits.has(_iaCurrentFrame)) tile.pendingEdits.set(_iaCurrentFrame, {});
        tile.pendingEdits.get(_iaCurrentFrame)[tile.dragBp] = { x, y };
        this._renderTileMarkers(tile);
        return;
      }
      const hit = _ia3dTileHitTest(tile, cx, cy);
      canvas.style.cursor = hit ? "pointer" : (_iaSelectedBp ? "crosshair" : "default");
    });

    canvas.addEventListener("mouseup", async e => {
      if (!tile.dragging || !tile.dragBp) return;
      tile.dragging = false;
      const rect = canvas.getBoundingClientRect();
      const { x, y } = _ia3dTileCanvasToVideo(tile, e.clientX - rect.left, e.clientY - rect.top);
      await _ia3dFlushTileEdit(tile, _iaCurrentFrame, tile.dragBp, x, y);
      _iaUpdateEditBanner(); _iaUpdateBpChipStatus();
      tile.dragBp = null;
      canvas.style.cursor = _iaSelectedBp ? "crosshair" : "default";
    });

    canvas.addEventListener("mouseleave", () => {
      if (tile.dragging && tile.dragBp) {
        const edits = tile.pendingEdits.get(_iaCurrentFrame);
        if (edits && tile.dragBp in edits) {
          const { x, y } = edits[tile.dragBp];
          _ia3dFlushTileEdit(tile, _iaCurrentFrame, tile.dragBp, x, y);
          _iaUpdateEditBanner();
        }
        tile.dragging = false; tile.dragBp = null;
      }
      canvas.style.cursor = _iaSelectedBp ? "crosshair" : "default";
    });

    canvas.addEventListener("contextmenu", e => {
      e.preventDefault();
      if (!_iaIsEditable() || !_iaOverlayEnabled || !_iaSelectedBp) return;
      if (!tile.layers || !tile.layers[0]) return;
      if (!tile.pendingEdits.has(_iaCurrentFrame)) tile.pendingEdits.set(_iaCurrentFrame, {});
      tile.pendingEdits.get(_iaCurrentFrame)[_iaSelectedBp] = { x: null, y: null };
      this._renderTileMarkers(tile);
      _ia3dFlushTileDelete(tile, _iaCurrentFrame, _iaSelectedBp);
      _iaUpdateEditBanner(); _iaUpdateBpChipStatus();
    });
  },
```

- [ ] **Step 3b: Call `_wireSiblingEditing` where siblings are wired**

Find the two places a sibling's focus is wired (`this._wireFocus(this._pendingSibling);` ~line 234, and `this._wireFocus(tile);` ~line 246). Add directly after each:

```javascript
      this._wireSiblingEditing(this._pendingSibling);   // after the line ~234 _wireFocus(this._pendingSibling)
```
and
```javascript
    this._wireSiblingEditing(tile);   // after the line ~246 _wireFocus(tile)
```
(Match the exact variable used by each `_wireFocus` call. The `_editWired` guard makes a double-call harmless.)

- [ ] **Step 3c: Update the scope-note comment**

Replace the "Per-cam editing scope note" comment block (`inline_analysis_3d.js:1403-1417`, the paragraph beginning `// The canvas edit handlers below ... target tile-0's overlay canvas`) with a short note:

```javascript
    // ── Per-cam editing ─────────────────────────────────────────────────
    // The handlers below target tile-0's overlay canvas (#ia3d-overlay-canvas-0)
    // and write to _iaLocalEdits (aliased to Controller.tiles[0].pendingEdits).
    // Sibling tiles get equivalent edit handlers via Controller._wireSiblingEditing,
    // which operate on each sibling's own canvas + pendingEdits + layers[0].path.
```

- [ ] **Step 4: Run, verify PASS**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_sibling_editing_wired -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): sibling-tile marker editing (edit cam1 on its own canvas)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Overlay pending edits + selected ring on sibling display

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (`_renderTileMarkers`, the primary-draw block ~line 469-477)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

Today `_renderTileMarkers` draws the sibling primary layer read-only (no pending-edit override, no selected-bp ring). Extend the PRIMARY draw so a pending edit for a bodypart overrides its drawn position and the selected bp gets a ring (mirrors how tile-0's `_iaDrawPoseMarkers` shows edits).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_sibling_render_overlays_pending_edits():
    js = JS.read_text()
    i = js.find("async _renderTileMarkers(tile)")
    assert i > 0
    body = js[i:i + 2200]
    # the primary draw consults the tile's pendingEdits for the current frame
    assert "tile.pendingEdits.get(" in body, "render must apply pending edits for the focused/edited tile"
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_sibling_render_overlays_pending_edits -v
```
Expected: FAIL.

- [ ] **Step 3: Apply pending edits in the primary draw loop**

In `_renderTileMarkers`, the primary-layer draw loop (the block after `const cached = primary.posesCache.get(frame);` ~line 469, which iterates `cached.poses` and draws each at `pose.x*sx, pose.y*sy`), change it to consult the tile's pending edits. Read the exact loop and adapt it to:

```javascript
    const cached = primary.posesCache.get(frame);
    if (cached) {
      const total = cached.n_bodyparts || primary.bodyparts.length || 1;
      const frameEdits = tile.pendingEdits.get(frame) || {};
      for (const pose of cached.poses) {
        if (_iaHiddenParts.has(pose.bp)) continue;
        const edited = pose.bp in frameEdits;
        // A deleted edit (x===null) hides the marker.
        if (edited && (frameEdits[pose.bp].x == null)) continue;
        const vx = edited ? frameEdits[pose.bp].x : pose.x;
        const vy = edited ? frameEdits[pose.bp].y : pose.y;
        const cx = Math.round(vx * sx);
        const cy = Math.round(vy * sy);
        const color = _iaPaletteColor(pose.color_idx, total);
        // ...preserve the rest of the existing primary-draw body (the marker
        // shape draw + any selected-bp ring), using cx/cy/color computed here.
      }
    }
```
Preserve everything else in the existing primary-draw body (the actual `ctx.beginPath()`/shape draw and any ring). If the existing code draws a selected-bp ring keyed on `_iaSelectedBp`, keep it. Do NOT change the comparison-layer loop above it, the canvas sizing, or `sx/sy`.

- [ ] **Step 4: Run, verify PASS**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_sibling_render_overlays_pending_edits -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): sibling marker render applies pending edits

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Save Adjustments persists every tile

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (`iaSaveAdjBtn` click handler ~line 1530)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

The existing Save Adjustments handler saves only `_iaPrimary()` (tile-0). Generalize it to also save each sibling tile that has pending edits, to that tile's `layers[0].path`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_save_adjustments_persists_all_tiles():
    js = JS.read_text()
    i = js.find("iaSaveAdjBtn")
    assert i > 0
    body = js[i:i + 2000]
    # the save handler iterates the tiles (so cam1's edits persist too)
    assert "Controller.tiles" in body
    assert "/dlc/viewer/save-marker-edits" in body
```

- [ ] **Step 2: Run, verify FAIL**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_save_adjustments_persists_all_tiles -v
```
Expected: FAIL (handler saves only the tile-0 primary; no `Controller.tiles` loop).

- [ ] **Step 3: Generalize the save handler**

Read the existing `iaSaveAdjBtn` click handler (`inline_analysis_3d.js:1530+`). It currently POSTs `/dlc/viewer/save-marker-edits` for `_iaPrimary()` (tile-0). After that tile-0 save (keep it as-is), add a loop over the sibling tiles that have pending edits, saving each to its own layer:

```javascript
        // Persist sibling tiles' edits too (cam1+ each to their own h5).
        for (let i = 1; i < Controller.tiles.length; i++) {
          const t = Controller.tiles[i];
          if (!t.layers || !t.layers[0] || t.pendingEdits.size === 0) continue;
          try {
            await fetch("/dlc/viewer/save-marker-edits", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ h5: t.layers[0].path }),
            });
          } catch (_) {}
        }
```
Place this inside the existing `try` block, after the tile-0 save call and before the existing success/reload handling. Do not change the button-disable/finally/status logic.

- [ ] **Step 4: Run, verify PASS**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_save_adjustments_persists_all_tiles -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): Save Adjustments persists every camera tile's edits

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Full 3D guard-suite sweep

**Files:** none (verification only).

- [ ] **Step 1: Run the 3D guard suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -v
```
Expected: all pass (the 15 existing + 4 new from Tasks 1-4 = 19). The e2e file `tests/e2e/test_analyzed_viewer.py` is NOT part of this run.

- [ ] **Step 2: If any failure, fix in the owning task's file and re-run. No commit for this task.**

---

## Self-review notes (author)

- **Spec coverage:** §2 (sibling wiring) → Task 2. §3 (per-tile coord/hit-test/writes) → Task 1 + Task 2. §4 (scope-note + render overlay) → Task 2 (comment) + Task 3 (render). §5 (save both) → Task 4. Render-pipeline-unchanged invariant → no task touches `_iaSyncCanvas` or the `sx = iaOverlayCanvas.width/natW` draw functions; only `_renderTileMarkers`'s primary-draw values change (Task 3).
- **Name consistency:** `_ia3dTileCanvasToVideo`, `_ia3dTileHitTest`, `_ia3dFlushTileEdit`, `_ia3dFlushTileDelete`, `_wireSiblingEditing`, `tile.dragging`/`tile.dragBp`, `tile._editWired` — consistent across tasks.
- **Minimal-change:** tile-0's handlers (1418-1527) are untouched; sibling editing is purely additive; no canvas-sizing change.
