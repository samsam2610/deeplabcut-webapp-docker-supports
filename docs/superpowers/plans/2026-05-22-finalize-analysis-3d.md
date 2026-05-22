# Finalize Analysis (3D inline, both cameras) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Finalize analysis" minicard to the inline 3D card that gates marker editing and copies a chosen frame range from each camera's working layer into that camera's `_analyzed` file. 3D mirror of Spec 1; reuses Spec 1's `finalize-range` endpoint (called once per camera) and Spec 2's sibling editing.

**Architecture:** A finalize toggle drives `_ia3dFinalizeEnabled`; `_iaIsEditable()` gains `&& _ia3dFinalizeEnabled` so all-camera mutation editing is gated behind it in one place. The marker-edit controls relocate below the bodypart list (finalize-driven visibility). The "Add range to _analyzed" button commits both cameras' edits then POSTs `finalize-range` for cam0 and cam1. Frontend-only.

**Tech Stack:** Vanilla JS + Jinja partial; pytest static source-assertions.

---

## Conventions

- **Repo / dir:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D` (branch `feat/3d-inline-analysis` — do NOT branch).
- **No backend / no restart:** `finalize-range` + `save-marker-edits` already exist; static assets serve fresh.
- **Tests** = static source-assertions in `tests/test_inline_analysis_3d_ui_isolation.py` (constants `JS`, `CARD`, `PAGE`).
- **Scope structure (verified):** `inline_analysis_3d.js` is an outer player IIFE (holds `_iaOverlayEnabled` line 691, `_iaCurrentVideoPath` 697, `_iaIsEditable` 723, `_iaUpdateEditBanner` 1413, the marker-edit-banner const 1383, the overlay toggle ~1939) with nested sub-IIFEs: Dataset Curation (ends 3316), Video Metadata (ends 3376), **STEREO ANALYSIS DISPATCH (3384-3696)** which holds `framesEl` (3389), `_siblingPath` (3401), and the analyze-submit handler (3567, with `startFrame`/`nFrames` at 3573-3574, last-run text at 3592). `window.__va3dRefreshMarkerBanner` (1441) calls `_iaUpdateEditBanner` from any scope.
- Line numbers are approximate (shift as tasks land) — locate by quoted code.
- **Reference:** the 2D equivalents are in `deeplabcut-webapp-docker/src/static/js/inline_analysis_player.js` (Spec 1) — this plan is the 3D mirror.

---

## Task 1: HTML — Finalize minicard below the curation panel

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (after the `<!-- ── end Dataset Curation Panel ── -->` comment ~line 420, before the `</div>` closing `#ia3d-player-section`)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_finalize3d_minicard_present_after_curation():
    html = CARD.read_text()
    for needed in ["ia3d-finalize-toggle", "ia3d-finalize-controls", "ia3d-finalize-start",
                   "ia3d-finalize-count", "ia3d-finalize-add-btn", "ia3d-finalize-status"]:
        assert f'id="{needed}"' in html, f"missing {needed!r}"
    assert html.find('id="ia3d-curation-panel"') < html.find('id="ia3d-finalize-toggle"')
```

- [ ] **Step 2: Run, verify FAIL**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize3d_minicard_present_after_curation -v
```

- [ ] **Step 3: Insert the minicard**

Immediately AFTER the `<!-- ── end Dataset Curation Panel ──────────────────────────── -->` comment line, insert:

```html

        <!-- ── Finalize Analysis Panel ─────────────────────────────── -->
        <div id="ia3d-finalize-panel" style="margin-top:.65rem;padding:.5rem .65rem;background:var(--surface-2);border:1px solid var(--border);border-radius:7px">
          <label style="display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:500;cursor:pointer;user-select:none">
            <input type="checkbox" id="ia3d-finalize-toggle" style="accent-color:var(--accent);width:14px;height:14px"/>
            Finalize analysis
          </label>
          <div id="ia3d-finalize-controls" class="hidden" style="margin-top:.5rem">
            <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;margin-bottom:.4rem">
              <label style="font-size:.76rem;color:var(--text-dim);white-space:nowrap">Start frame</label>
              <input type="number" id="ia3d-finalize-start" value="0" min="0"
                style="width:5rem;font-size:.76rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.22rem .4rem" />
              <label style="font-size:.76rem;color:var(--text-dim);white-space:nowrap">Frames</label>
              <input type="number" id="ia3d-finalize-count" value="500" min="1" max="10000"
                style="width:5rem;font-size:.76rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.22rem .4rem" />
              <button class="btn-sm btn-create" id="ia3d-finalize-add-btn"
                title="Save marker edits to both cameras' layers, then copy this frame range into each camera's _analyzed file">
                Add range to _analyzed
              </button>
            </div>
            <div id="ia3d-finalize-status" class="fe-extract-status"></div>
          </div>
        </div>
        <!-- ── end Finalize Analysis Panel ─────────────────────────── -->
```

- [ ] **Step 4: Run, verify PASS** (same command as Step 2). Then `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q` (all pass).

- [ ] **Step 5: Commit**
```bash
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): add Finalize analysis minicard (3D)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: HTML — relocate marker-edit controls below the marker list

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (remove `#ia3d-marker-edit-banner` block ~182-198; add `#ia3d-marker-edit-controls` after `#ia3d-bp-list-wrap` ~281, before `#ia3d-status` ~283)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test + check the existing guard**

First, `grep -n "ia3d-marker-edit-banner" tests/test_inline_analysis_3d_ui_isolation.py` — if any existing test asserts that id, update it to `ia3d-marker-edit-controls`. Then append:

```python
def test_marker_edit3d_controls_moved_below_marker_list():
    html = CARD.read_text()
    assert 'id="ia3d-marker-edit-banner"' not in html, "old top banner must be removed"
    assert 'id="ia3d-marker-edit-controls"' in html
    pos_list  = html.find('id="ia3d-bp-list-wrap"')
    pos_ctrls = html.find('id="ia3d-marker-edit-controls"')
    pos_cur   = html.find('id="ia3d-curation-panel"')
    assert 0 < pos_list < pos_ctrls < pos_cur
    for needed in ["ia3d-marker-edit-count", "ia3d-save-adjustments-btn",
                   "ia3d-discard-adjustments-btn", "ia3d-clear-frame-btn"]:
        assert f'id="{needed}"' in html
```

- [ ] **Step 2: Run, verify FAIL**
```bash
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_marker_edit3d_controls_moved_below_marker_list -v
```

- [ ] **Step 3: Move + restyle**

(a) DELETE the entire `<div id="ia3d-marker-edit-banner" class="hidden" ...> ... </div>` block (~lines 182-198, the marker-adjustment banner before the tile row), plus its preceding comment if present.

(b) INSERT after the `#ia3d-bp-list-wrap` block's closing `</div>` (~line 281) and before `<span id="ia3d-status" ...>` (~283):

```html
        <!-- Marker-edit controls — shown only when Finalize analysis is on -->
        <div id="ia3d-marker-edit-controls" class="hidden"
          style="display:flex;align-items:center;gap:.55rem;flex-wrap:wrap;margin-top:.35rem;margin-bottom:.2rem;font-size:.77rem">
          <span id="ia3d-marker-edit-count" style="color:var(--accent);font-weight:500">0 frames edited</span>
          <button class="btn-sm" id="ia3d-save-adjustments-btn"
            style="background:var(--accent);color:#fff;font-weight:500;padding:.28rem .7rem"
            title="Write marker adjustments back to the .h5 and .csv files">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="margin-right:.3rem"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>Save Adjustments
          </button>
          <button class="btn-sm" id="ia3d-discard-adjustments-btn"
            style="opacity:.75;padding:.28rem .6rem" title="Discard all pending marker adjustments">Discard</button>
          <button class="btn-sm" id="ia3d-clear-frame-btn"
            style="opacity:.65;padding:.28rem .6rem" title="Double-click to erase all markers on the current frame">Clear Frame</button>
        </div>
```

Preserve the four ids exactly. If the original banner had extra inner markup (an icon/“unsaved” text), drop it — keep only count + the three buttons.

- [ ] **Step 4: Run, verify PASS** (the new test + any updated existing test). Then full file.

- [ ] **Step 5: Commit**
```bash
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): relocate marker-edit controls below the marker list (3D)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: JS — edit-gating flag + `_iaIsEditable` + banner retarget

**Files:**
- Modify: `src/static/inline_analysis_3d.js`
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_js3d_edit_gated_on_finalize():
    js = JS.read_text()
    assert "_ia3dFinalizeEnabled" in js
    # editability requires the finalize flag
    i = js.find("function _iaIsEditable")
    seg = js[i:i + 120]
    assert "_ia3dFinalizeEnabled" in seg, "_iaIsEditable must require _ia3dFinalizeEnabled"
    # the relocated controls element id is referenced (old banner id gone)
    assert 'getElementById("ia3d-marker-edit-controls")' in js
    assert 'getElementById("ia3d-marker-edit-banner")' not in js
```

- [ ] **Step 2: Run, verify FAIL**
```bash
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_js3d_edit_gated_on_finalize -v
```

- [ ] **Step 3: Edits**

(a) Just after `let _iaCurrentVideoPath = null;` (~line 697, outer scope), add:
```javascript
    let _ia3dFinalizeEnabled = false;   // marker editing gated on the Finalize toggle
    let _ia3dLastRunStart    = null;    // start_frame of the last submitted range
    let _ia3dLastRunN        = null;    // n_frames of the last submitted range
```

(b) Change `_iaIsEditable` (~line 723):
```javascript
    function _iaIsEditable()  { return _iaLayers.length === 1 && _ia3dFinalizeEnabled; }
```

(c) Retarget the banner const (~line 1383): change the id string only:
```javascript
    const iaMarkerEditBanner  = document.getElementById("ia3d-marker-edit-controls");
```

(d) Make `_iaUpdateEditBanner` (~line 1413) finalize-driven (read the current body first to preserve the per-cam `cam0: N · cam1: M` count text). Replace its show/hide logic so it toggles on the finalize flag, then keeps the existing count-text computation:
```javascript
    function _iaUpdateEditBanner() {
      if (!iaMarkerEditBanner) return;
      iaMarkerEditBanner.classList.toggle("hidden", !_ia3dFinalizeEnabled);
      // ...preserve the EXISTING per-cam count-text computation here (the
      // tiles[0]/tiles[1] pendingEdits sizes → "cam0: N · cam1: M frames edited"
      // or single-cam "N frames edited"), assigning into iaMarkerEditCount.
    }
```
Read the current `_iaUpdateEditBanner` and keep its count-text branch verbatim; only the visibility line changes (from count-based to finalize-based).

- [ ] **Step 4: Run, verify PASS** (the new test). Then full file (all pass).

- [ ] **Step 5: Commit**
```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): gate 3D marker editing on the Finalize toggle

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: JS — finalize toggle + both-cams copy button + autopopulate

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (inside the STEREO ANALYSIS DISPATCH IIFE, ~3384-3696)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

The finalize wiring goes in the DISPATCH IIFE because it needs `_siblingPath` (3401) and `framesEl` (3389). It sets the outer `_ia3dFinalizeEnabled`/`_ia3dLastRun*`, refreshes the banner via `window.__va3dRefreshMarkerBanner()`, auto-enables the overlay via `getElementById`, and uses `_iaPrimary()` / `Controller` (outer/global).

- [ ] **Step 1: Write the failing test**

```python
def test_js3d_finalize_flow_and_autopopulate():
    js = JS.read_text()
    assert 'getElementById("ia3d-finalize-toggle")' in js
    assert 'getElementById("ia3d-finalize-add-btn")' in js
    assert "/dlc/project/inline-analysis/finalize-range" in js
    assert "/dlc/viewer/save-marker-edits" in js
    assert "_ia3dLastRunStart" in js and "_ia3dLastRunN" in js
    assert "_ia3dPopulateFinalizeFields" in js
    # both-cams copy references the sibling path
    i = js.find('getElementById("ia3d-finalize-add-btn")')
    body = js[i:i + 2600]
    assert "_siblingPath" in body
```

- [ ] **Step 2: Run, verify FAIL**
```bash
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_js3d_finalize_flow_and_autopopulate -v
```

- [ ] **Step 3a: Add finalize wiring inside the DISPATCH IIFE**

Place this block inside the STEREO ANALYSIS DISPATCH IIFE (e.g. right after the `analyzeBtn.addEventListener("click", …)` handler, before the IIFE's closing `})();` at ~3696):

```javascript
      // ── Finalize Analysis: toggle (gates editing) + both-cams range copy ──
      const ia3dFinalizeToggle   = document.getElementById("ia3d-finalize-toggle");
      const ia3dFinalizeControls = document.getElementById("ia3d-finalize-controls");
      const ia3dFinalizeAddBtn   = document.getElementById("ia3d-finalize-add-btn");
      const ia3dFinalizeStatus   = document.getElementById("ia3d-finalize-status");

      function _ia3dPopulateFinalizeFields() {
        const s = document.getElementById("ia3d-finalize-start");
        const c = document.getElementById("ia3d-finalize-count");
        const fpc = document.getElementById("ia3d-frames-per-click");
        if (s) s.value = (_ia3dLastRunStart != null ? _ia3dLastRunStart : (_iaCurrentFrame || 0));
        if (c) c.value = (_ia3dLastRunN != null ? _ia3dLastRunN : (parseInt(fpc?.value, 10) || 500));
      }

      ia3dFinalizeToggle?.addEventListener("change", () => {
        _ia3dFinalizeEnabled = ia3dFinalizeToggle.checked;
        ia3dFinalizeControls?.classList.toggle("hidden", !_ia3dFinalizeEnabled);
        const ov = document.getElementById("ia3d-overlay-toggle");
        if (_ia3dFinalizeEnabled && ov && !ov.checked) { ov.checked = true; ov.dispatchEvent(new Event("change")); }
        if (_ia3dFinalizeEnabled) _ia3dPopulateFinalizeFields();
        if (typeof window.__va3dRefreshMarkerBanner === "function") window.__va3dRefreshMarkerBanner();
      });

      async function _ia3dSaveLayer(h5) {
        try {
          await fetch("/dlc/viewer/save-marker-edits", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ h5 }),
          });
        } catch (_) {}
      }
      async function _ia3dFinalizeOne(videoPath, sourceH5, startFrame, nFrames) {
        const r = await fetch("/dlc/project/inline-analysis/finalize-range", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_path: videoPath, source_h5: sourceH5, start_frame: startFrame, n_frames: nFrames }),
        });
        const d = await r.json().catch(() => ({}));
        return r.ok ? { ok: true, n: d.n_frames_written } : { ok: false, err: d.error || r.status };
      }

      ia3dFinalizeAddBtn?.addEventListener("click", async () => {
        const cam0Layer = (typeof _iaPrimary === "function") ? _iaPrimary() : null;
        const cam0Video = _iaCurrentVideoPath || _iaBrowseVideoPath;
        if (!cam0Layer || !cam0Video) {
          if (ia3dFinalizeStatus) { ia3dFinalizeStatus.textContent = "Select a video/layer first."; ia3dFinalizeStatus.className = "fe-extract-status err"; }
          return;
        }
        const startFrame = parseInt(document.getElementById("ia3d-finalize-start")?.value, 10) || 0;
        const nFrames    = parseInt(document.getElementById("ia3d-finalize-count")?.value, 10) || 0;
        const cam1Tile   = (typeof Controller !== "undefined") ? Controller.tiles[1] : null;
        const cam1Layer  = cam1Tile && cam1Tile.primaryH5Path;
        ia3dFinalizeAddBtn.disabled = true;
        if (ia3dFinalizeStatus) { ia3dFinalizeStatus.textContent = "Finalizing…"; ia3dFinalizeStatus.className = "fe-extract-status"; }
        try {
          // 1) commit edits on both cameras' layers
          await _ia3dSaveLayer(cam0Layer.path);
          if (cam1Layer) await _ia3dSaveLayer(cam1Layer);
          // 2) copy the range into each camera's _analyzed
          const r0 = await _ia3dFinalizeOne(cam0Video, cam0Layer.path, startFrame, nFrames);
          let r1 = null;
          if (_siblingPath && cam1Layer) r1 = await _ia3dFinalizeOne(_siblingPath, cam1Layer, startFrame, nFrames);
          if (ia3dFinalizeStatus) {
            const p0 = r0.ok ? `cam0 ✓ ${r0.n}` : `cam0 ⚠ ${r0.err}`;
            const p1 = r1 ? (r1.ok ? ` · cam1 ✓ ${r1.n}` : ` · cam1 ⚠ ${r1.err}`) : "";
            ia3dFinalizeStatus.textContent = `${p0}${p1}`;
            ia3dFinalizeStatus.className = (r0.ok && (!r1 || r1.ok)) ? "fe-extract-status" : "fe-extract-status err";
          }
        } catch (e) {
          if (ia3dFinalizeStatus) { ia3dFinalizeStatus.textContent = `Error: ${e}`; ia3dFinalizeStatus.className = "fe-extract-status err"; }
        } finally {
          ia3dFinalizeAddBtn.disabled = false;
        }
      });
```

- [ ] **Step 3b: Capture last-run in the submit handler**

In the `analyzeBtn.addEventListener("click", …)` handler, right after `const startFrame = _iaCurrentFrame || 0;` and `const nFrames = parseInt(framesEl?.value, 10) || 500;` (~3573-3574), add:
```javascript
        _ia3dLastRunStart = startFrame;
        _ia3dLastRunN     = nFrames;
```
And right after the "Last run: cam0 …" status text is set (~3592), add:
```javascript
        if (typeof _ia3dPopulateFinalizeFields === "function") _ia3dPopulateFinalizeFields();
```

- [ ] **Step 4: Run, verify PASS** (new test). Then full file (all pass).

- [ ] **Step 5: Commit**
```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): wire 3D Finalize toggle + both-cams range copy + autopopulate

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Full 3D guard-suite sweep

**Files:** none.

- [ ] **Step 1:**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -v
```
Expected: all pass (19 from Specs before + 4 new = 23).

- [ ] **Step 2:** If any failure other than the new tests, fix in the owning task's file and re-run. No commit.

---

## Self-review notes (author)

- **Spec coverage:** F1 minicard → Task 1. F2 edit-gating (`_ia3dFinalizeEnabled` + `_iaIsEditable`) → Task 3. F3 relocate controls → Task 2 + Task 3 (banner retarget + finalize-driven `_iaUpdateEditBanner`). F4 both-cams button → Task 4. F5 autopopulate → Task 4 (3a populate + 3b capture).
- **Scope/scoping:** flag declared in outer scope (so `_iaIsEditable` sees it); finalize wiring in the DISPATCH IIFE (so `_siblingPath`/`framesEl` are visible); banner refresh via the `window.__va3dRefreshMarkerBanner` hook; overlay auto-enable via `getElementById`.
- **Name consistency:** `_ia3dFinalizeEnabled`, `_ia3dLastRunStart`/`_ia3dLastRunN`, `_ia3dPopulateFinalizeFields`, ids `ia3d-finalize-*`, `ia3d-marker-edit-controls`. Reuses endpoint `/dlc/project/inline-analysis/finalize-range`.
- **No backend change; tile-0 + sibling editing both gated via the single `_iaIsEditable` change.**
