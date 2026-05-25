# Frame-Labeler Editing Mechanics in the Shared `markerEditor` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port `frame_labeler_3d.js`'s proven labeling interaction model (auto-advance, Lock-BP, click-to-select, hover cursor, Space-visibility, decoupled edit gate, focus persistence) into the shared `markerEditor` feature so the inline-3D analysis card feels like the labeler — without forking the player or changing the analysis-h5 data layer.

**Architecture:** Enhance the shared `markerEditor` feature (`features/marker_editor.js`) consumed by BOTH `inline_analysis_3d.js` (edits, opts in) and `viewer_3d.js` (read-only, must not regress). Extract DOM-free cycle logic into a new `internal/bodypart_cycle.mjs` reducer (node:test). The edit/render gate decouples from `overlayEnabled` to `overlayEnabled || editingAllowed` so read-only consumers (which never call `setEditable(true)`) are unchanged. The inline consumer wires a Lock-BP checkbox, passes `autoAdvance: true`, and simplifies `_applyOverlayPrimary` to stop force-enabling the overlay. No backend, no new routes, no player fork.

**Tech Stack:** Vanilla browser ESM (no bundler; `.js` features + `.mjs` internal reducers), Node v16 `node:test` for pure logic, pytest static-source assertions for DOM/feature contracts, `playwright.sync_api` for read-only live verification.

---

## Grounding facts (verified — do not re-discover)

- Repo: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`. Branch `feat/marker-editor-labeler-mechanics` is already checked out (HEAD `cb28368`, the design-spec commit). Frontend only.
- `marker_editor.js` is SHARED by `inline_analysis_3d.js` (edits) and `viewer_3d.js` (read-only — confirmed: `viewer_3d.js` only ever calls `setOverlayEnabled`, never `setEditable(true)`, lines 442/948).
- Policy `tests/test_video_viewer_policy.py` forbids `class Tile` / `const Controller =` in consumers and mandates composing `VideoViewer` + a feature. It MUST stay green.
- `L` key is taken by the keyframe range-lock (`keyframe_window_ui.js`). Lock-BP is a CHECKBOX, no `L` shortcut.
- Data layer UNCHANGED: per-edit auto-flush via `endpoints.saveMarker()` → edit-cache → h5/csv. Do not touch the save path.
- Node v16 is installed. JS unit tests: `cd dlc-3D && node --test tests/unit/<f>.mjs` (file-level TAP). pytest: `cd dlc-3D && python -m pytest tests/<f>.py -q`.
- JS is bind-mounted (live, no restart). Templates/py need `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`. Auth: `GET http://localhost:5000/?token=deeplabcut`.
- NEVER click Save Adjustments / Add range / Extract / Finalize / Delete against `/user-data` fixtures. In-memory marker edits (no save) are OK.

### Ambiguities resolved (read before starting)

1. **Per-frame vs global visibility (B6 Space).** The spec's Behaviors §B6 says "per-frame visibility" and Error-handling says "per-(frame,bp) in-memory state". But the existing `markerEditor` `hiddenParts` is a **global** `Set` (bp-keyed, all-frames) wired to the bp-chip double-click + the `.vis-hidden` chip class. The labeler reference (`frame_labeler_3d.js:1551 _flToggleVisibility`) IS per-frame (`_flHidden[fname][bp]`). **Resolution:** implement Space as a **per-frame** hide store (`hiddenByFrame: { [frame]: Set<bp> }`) to match the labeler feel and the spec's explicit "per-(frame,bp)" wording, while KEEPING the existing global `hiddenParts` double-click behavior untouched (a bp is hidden if EITHER the global set or the current frame's set contains it). This is additive — no regression to the existing chip double-click. Task 8 implements this; the `.vv-bp-chip.vis-hidden` chip reflects the union for the current frame.

2. **Auto-advance "no finite pose" using edits.** B2 says advance to the next bp with no finite pose "using `posedBodyparts(curPoses)`". `posedBodyparts` reads the RAW poses, not the in-memory edits. A freshly-placed marker is an edit, not yet in `curPoses`. **Resolution:** auto-advance computes the labeled set as the union of `posedBodyparts(curPoses())` AND the bps present (non-deleted) in the current frame's edits (`frameEditsOf(editsFor(focusedCam), currentFrame)`), so a just-placed bp counts as labeled and is skipped. The reducer `nextUnlabeledBodypart` takes the precomputed `posedSet` so it stays DOM-free; the caller builds the union. This mirrors the labeler (`_flAutoAdvanceBp` reads `_flLabels[fname]`, which holds just-placed points).

3. **Focus clamp on `videoLoad` (B7).** Spec says "do NOT reset focusedCam to 0" but "clamp to a valid tile index if the new video has fewer cams". **Resolution:** on `videoLoad`, keep `focusedCam` as-is, then after re-wiring tiles, count tiles and if `focusedCam >= tileCount` set `focusedCam = 0`. Then apply the `.vv-tile-focused` class to whichever tile is now focused.

---

## File structure

- **Create** `src/static/components/viewer/internal/bodypart_cycle.mjs` — DOM-free reducers `nextUnlabeledBodypart(bodyparts, posedSet, current, lock)` and `cycleBodypart(bodyparts, current, dir)`. One responsibility: bodypart selection math.
- **Create** `tests/unit/test_bodypart_cycle.mjs` — node:test for the two reducers.
- **Modify** `src/static/components/viewer/features/marker_editor.js` — B1–B7 interaction enhancements.
- **Modify** `tests/test_marker_editor_feature.py` — extend the static-source feature contract for the new API/behaviors.
- **Modify** `src/static/inline_analysis_3d.js` — consumer wiring (`autoAdvance: true`, Lock-BP checkbox wire, simplified `_applyOverlayPrimary`).
- **Modify** `src/templates/partials/card_inline_analysis_3d.html` — Lock-BP checkbox in the marker-edit controls.
- **Modify** `src/static/inline_analysis_3d.css` — Lock-BP control style + (optional) stronger focused-tile emphasis using existing tokens.
- **Modify** `tests/test_inline_analysis_3d_ui_isolation.py` — assertions for the Lock-BP control + edit-mode decoupling wiring; loosen the now-obsolete `test_overlay_auto_enables_for_editing_when_finalize_on` to the new (no-forced-overlay) contract.

---

## How `tests/test_marker_editor_feature.py` currently tests (match this style)

It is a **static-analysis contract**: it reads `marker_editor.js` source as text (`_src()`) and runs `re.search` / substring assertions over it — browser ESM cannot be imported under Node. Examples in the file:
- `re.search(r"export\s+function\s+markerEditor\b", _src())` — factory export.
- `@pytest.mark.parametrize("name", [...])` over imported reducer names, asserting each appears in an `import { … } from ".../marker_overlay.mjs"` line.
- `assert '"videoLoad"' in src or "'videoLoad'" in src` — hook subscription by literal.
- `assert re.search(r"isEditable", _src())` — presence of a gating identifier.
- `for cls in (...): assert cls in src` — chip markup substrings.

**Implementers MUST match this:** new feature-contract assertions are `re.search`/substring checks over the source string (identifier present, gate-expression present, hook present), NOT runtime/jsdom. Pure logic goes in `bodypart_cycle.mjs` + node:test instead.

---

## Task 1: Pure reducer `bodypart_cycle.mjs` + node:test

**Files:**
- Create: `src/static/components/viewer/internal/bodypart_cycle.mjs`
- Test: `tests/unit/test_bodypart_cycle.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bodypart_cycle.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { nextUnlabeledBodypart, cycleBodypart }
  from "../../src/static/components/viewer/internal/bodypart_cycle.mjs";

const BPS = ["Snout", "Ear", "Tail"];

test("nextUnlabeledBodypart: skips placed, advances to the next unlabeled (wrapping)", () => {
  // Snout placed, current=Snout → next unplaced is Ear.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Snout"]), "Snout", false), "Ear");
  // Snout+Ear placed, current=Ear → wrap past Tail? Tail unplaced → Tail.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Snout", "Ear"]), "Ear", false), "Tail");
  // Tail placed last, current=Tail, Snout still unplaced → wraps to Snout.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Tail"]), "Tail", false), "Snout");
});

test("nextUnlabeledBodypart: all placed → stays on current", () => {
  assert.equal(
    nextUnlabeledBodypart(BPS, new Set(["Snout", "Ear", "Tail"]), "Ear", false), "Ear");
});

test("nextUnlabeledBodypart: lock=true → stays on current (no advance)", () => {
  assert.equal(nextUnlabeledBodypart(BPS, new Set(["Snout"]), "Snout", true), "Snout");
});

test("nextUnlabeledBodypart: empty / non-array list → returns current unchanged", () => {
  assert.equal(nextUnlabeledBodypart([], new Set(), "Snout", false), "Snout");
  assert.equal(nextUnlabeledBodypart(null, new Set(), "Snout", false), "Snout");
});

test("nextUnlabeledBodypart: current not in list → scans from start", () => {
  // current unknown, nothing placed → first bp.
  assert.equal(nextUnlabeledBodypart(BPS, new Set(), "ZZZ", false), "Snout");
});

test("cycleBodypart: forward wraps, backward wraps", () => {
  assert.equal(cycleBodypart(BPS, "Snout", 1), "Ear");
  assert.equal(cycleBodypart(BPS, "Tail", 1), "Snout");   // forward wrap
  assert.equal(cycleBodypart(BPS, "Snout", -1), "Tail");  // backward wrap
  assert.equal(cycleBodypart(BPS, "Ear", -1), "Snout");
});

test("cycleBodypart: empty list → null; current not found → first", () => {
  assert.equal(cycleBodypart([], "x", 1), null);
  assert.equal(cycleBodypart(BPS, "ZZZ", 1), "Snout");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_bodypart_cycle.mjs`
Expected: FAIL — `Cannot find module '.../bodypart_cycle.mjs'` (module not created yet).

- [ ] **Step 3: Write minimal implementation**

Create `src/static/components/viewer/internal/bodypart_cycle.mjs`:

```javascript
// Pure bodypart-selection reducers for the MarkerEditor feature. No DOM, no fetch.
// `posedSet` is the set of bodyparts considered "already labeled in this frame"
// (the caller unions raw posed bps + just-placed edits — see marker_editor.js).

// Advance selection to the next bodypart with NO label in this frame, wrapping
// once. Used after a successful place (auto-advance). When `lock` is true (Lock-BP),
// stay on `current` so the next click re-places the same bp. If every bodypart is
// labeled, or the list is empty/not-an-array, stay on `current`.
export function nextUnlabeledBodypart(bodyparts, posedSet, current, lock = false) {
  if (lock) return current;
  if (!Array.isArray(bodyparts) || bodyparts.length === 0) return current;
  const set = posedSet || new Set();
  const start = bodyparts.indexOf(current); // -1 → scan begins at index 0
  for (let i = 1; i <= bodyparts.length; i++) {
    const cand = bodyparts[(start + i + bodyparts.length) % bodyparts.length];
    if (!set.has(cand)) return cand;
  }
  return current; // all placed → stay
}

// Step selection by `dir` (+1 forward, -1 backward) with wraparound. Returns null
// for an empty list; if `current` is not in the list, returns the first element.
export function cycleBodypart(bodyparts, current, dir) {
  if (!Array.isArray(bodyparts) || bodyparts.length === 0) return null;
  const idx = bodyparts.indexOf(current);
  if (idx < 0) return bodyparts[0];
  const n = (idx + dir + bodyparts.length) % bodyparts.length;
  return bodyparts[n];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_bodypart_cycle.mjs`
Expected: PASS — `# pass 7  # fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/internal/bodypart_cycle.mjs tests/unit/test_bodypart_cycle.mjs
git commit -m "feat(dlc-3d): pure bodypart-cycle reducers (auto-advance + tab) + node:test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: B1 — Decouple render/edit gate to `overlayEnabled || editingAllowed`

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` (gate sites: `renderTile` :170, `onFrame` :324, the three canvas handlers :381/396/410/427, `onKeyDown` :427)
- Test: `tests/test_marker_editor_feature.py`

**Rationale:** `setEditable(true)` must make markers render + edits live with NO `setOverlayEnabled(true)`. Read-only consumers (`viewer_3d.js`) never call `setEditable(true)`, so `editingAllowed` is whatever its default is — see Step 1 caveat.

> **IMPORTANT caveat about the current default:** `marker_editor.js:52` declares `let editingAllowed = true;` (default ON). For B1, if we change the render gate to `overlayEnabled || editingAllowed`, a read-only consumer that never touches `setEditable` would start rendering markers with the overlay OFF — a REGRESSION for View Analyzed. **Therefore B1 also flips the default to `editingAllowed = false`** so the gate stays equivalent to today's `overlayEnabled`-only behavior until a consumer opts in via `setEditable(true)`. The inline consumer already calls `setEditable(false)` then `setEditable(true)` on Finalize, so it is unaffected. `viewer_3d.js` never enables editing, so with the new default it renders exactly as before (keyed on `overlayEnabled`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_marker_editor_feature.py` (append after the existing tests):

```python
def test_b1_render_edit_gate_decoupled_from_overlay():
    """B1: render + edit are gated on `overlayEnabled || editingAllowed`, not
    overlayEnabled alone, so setEditable(true) makes markers render + edits live
    with no overlay toggle. Read-only consumers (no setEditable(true)) keep the
    default editingAllowed=false, so their rendering stays keyed on overlayEnabled."""
    src = _src()
    # the combined gate expression must appear (render + handlers reuse it)
    assert "overlayEnabled || editingAllowed" in src, \
        "render/edit gate must be `overlayEnabled || editingAllowed`"
    # default must be OFF so read-only consumers don't start rendering with overlay off
    assert re.search(r"editingAllowed\s*=\s*false", src), \
        "editingAllowed must default to false (read-only consumers unchanged)"
    # the bare `if (!overlayEnabled) return;` render short-circuit must be gone
    assert "if (!overlayEnabled) return;" not in src, \
        "renderTile must not short-circuit on overlayEnabled alone"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py::test_b1_render_edit_gate_decoupled_from_overlay -q`
Expected: FAIL — the combined gate string is absent; the bare short-circuit still present.

- [ ] **Step 3: Implement the gate decouple**

In `src/static/components/viewer/features/marker_editor.js`:

3a. Flip the default (line 52):

```javascript
  let editingAllowed = false; // master edit gate; default OFF — read-only consumers stay overlay-keyed
```

3b. Add a single combined-gate helper just below `curPoses` (after line 78):

```javascript
  // Markers render + edits are live when the overlay is shown OR editing is armed.
  // Decouples editing from the overlay toggle (B1): setEditable(true) renders without it.
  const renderActive = () => overlayEnabled || editingAllowed;
```

3c. `renderTile` (line 170) — replace:

```javascript
    if (!overlayEnabled) return;
```

with:

```javascript
    if (!renderActive()) return;
```

3d. `onFrame` (line 324) — replace:

```javascript
    if (!overlayEnabled) { renderAll(); return; }
```

with:

```javascript
    if (!renderActive()) { renderAll(); return; }
```

3e. `wireTileCanvas` mousedown (line 381) — replace:

```javascript
      if (!overlayEnabled || e.button !== 0 || cam !== focusedCam || !isEditableCam(cam)) return;
```

with:

```javascript
      if (!renderActive() || e.button !== 0 || cam !== focusedCam || !isEditableCam(cam)) return;
```

3f. `wireTileCanvas` click (line 396) — replace:

```javascript
      if (!overlayEnabled || cam !== focusedCam || !isEditableCam(cam) || !selectedBp) return;
```

with:

```javascript
      if (!renderActive() || cam !== focusedCam || !isEditableCam(cam) || !selectedBp) return;
```

3g. `wireTileCanvas` contextmenu (line 410) — replace:

```javascript
      if (!overlayEnabled || cam !== focusedCam || !isEditableCam(cam) || !selectedBp) return;
```

with:

```javascript
      if (!renderActive() || cam !== focusedCam || !isEditableCam(cam) || !selectedBp) return;
```

3h. `onKeyDown` (line 427) — replace:

```javascript
    if (!overlayEnabled) return;
```

with:

```javascript
    if (!renderActive()) return;
```

3i. `setEditable` (line 539-547) — it calls `renderAll()`; ensure markers fetch when armed without the overlay. After setting `editingAllowed`, fetch the current frame's poses so they paint immediately. Replace the body:

```javascript
    setEditable(on) {
      editingAllowed = !!on;
      const t = viewer && viewer.getTile(focusedCam);
      if (t && t.canvasEl) {
        t.canvasEl.style.cursor = editingAllowed && selectedBp && isEditableCam(focusedCam) ? "crosshair" : "default";
      }
      updateEditBanner();
      if (editingAllowed && !overlayEnabled) onFrame(currentFrame); else renderAll();
    },
```

- [ ] **Step 4: Run the feature contract + the existing overlay node test**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q && node --test tests/unit/test_viewer_marker_overlay.mjs`
Expected: PASS — all marker-editor feature tests green (new B1 test included); overlay reducer test unaffected (pure math untouched).

- [ ] **Step 5: Keep the policy green**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_policy.py -q`
Expected: PASS — no fork introduced.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "feat(dlc-3d): markerEditor B1 — decouple render/edit gate to overlayEnabled||editingAllowed

Default editingAllowed=false keeps read-only consumers (View Analyzed) unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: B2 auto-advance (`autoAdvance` config) + B3 Lock-BP (`setLockBp`)

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` (import the reducer; add `autoAdvance` config + `lockBp` state; advance after place; add `setLockBp`)
- Test: `tests/test_marker_editor_feature.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_marker_editor_feature.py`:

```python
def test_b2_b3_autoadvance_and_lockbp():
    """B2: an `autoAdvance` config (default off) advances selectedBp after a place
    using nextUnlabeledBodypart over (posedBodyparts ∪ frame edits). B3: setLockBp
    state + API; when locked, no advance (re-place same bp)."""
    src = _src()
    # imports the new reducer
    assert re.search(
        r"import\s*\{[^}]*\bnextUnlabeledBodypart\b[^}]*\}\s*from\s*[\"'][^\"']*bodypart_cycle\.mjs[\"']", src), \
        "must import nextUnlabeledBodypart from internal/bodypart_cycle.mjs"
    # autoAdvance read from config, default off
    assert re.search(r"autoAdvance\s*=\s*!!\s*config\.autoAdvance", src) or \
        re.search(r"config\.autoAdvance", src), "must read autoAdvance from config"
    # Lock-BP state + public setter
    assert re.search(r"setLockBp\s*\(", src), "must expose setLockBp(bool)"
    assert "lockBp" in src, "must track lockBp state"
    # the auto-advance call passes the lock flag (so Lock-BP suppresses advance)
    assert "nextUnlabeledBodypart(" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py::test_b2_b3_autoadvance_and_lockbp -q`
Expected: FAIL — reducer import + `setLockBp` + `autoAdvance` absent.

- [ ] **Step 3: Implement auto-advance + Lock-BP**

In `src/static/components/viewer/features/marker_editor.js`:

3a. Extend the reducer import (lines 24-29). Add `nextUnlabeledBodypart` from the new module just below the existing `marker_overlay.mjs` import block (after line 29):

```javascript
import { nextUnlabeledBodypart } from "../internal/bodypart_cycle.mjs";
```

3b. Read the config flag + add lock state. After line 39 (`let globalThreshold = ...`):

```javascript
  const autoAdvance = !!config.autoAdvance; // B2: advance to next unlabeled bp after a place (inline opts in)
  let lockBp = false;                        // B3: when true, placing does NOT auto-advance (re-place same bp)
```

3c. Add a helper that computes the "labeled in this frame" set as the union of posed bps + just-placed edits, then advances. Add just below `selectBp` (after line 277):

```javascript
  // B2 auto-advance: after a successful place, jump to the next bodypart with no
  // label in this frame. "Labeled" = finite raw pose OR a non-deleted edit (so a
  // just-placed marker counts). Suppressed when Lock-BP (B3) is on.
  function advanceAfterPlace(cam) {
    if (!autoAdvance) return;
    const labeled = posedBodyparts(curPosesForCam(cam));
    const fEdits = frameEditsOf(editsFor(cam), currentFrame);
    for (const [bp, e] of Object.entries(fEdits)) {
      if (e && e.x != null && e.y != null) labeled.add(bp);
    }
    const next = nextUnlabeledBodypart(allBodyParts, labeled, selectedBp, lockBp);
    if (next !== selectedBp) selectBp(next);
  }
```

3d. Call it after the click-place flush in `wireTileCanvas` click handler. In the click handler (lines 402-407), after `updateBpChips();` add the advance:

```javascript
      const { x, y } = canvasToVideo(cx, cy, tileScale(tile));
      editsByCam[cam] = setEdit(editsFor(cam), currentFrame, selectedBp, x, y);
      flushEdit(cam, currentFrame, selectedBp, x, y);
      renderTile(tile, currentFrame);
      updateEditBanner();
      updateBpChips();
      advanceAfterPlace(cam);
```

(Note: `advanceAfterPlace` calls `selectBp`, which re-renders + re-updates chips, so the order is correct: edit committed first, then advance.)

3e. Add the public `setLockBp` setter. In the returned object, just after `setFocusedCam,` / `getFocusedCam` (after line 534):

```javascript
    // B3 Lock-BP: when on, placing does not auto-advance (re-place the same bp to
    // correct a marker). UI is a checkbox in the consumer (no `L` shortcut — taken).
    setLockBp(on) { lockBp = !!on; },
    getLockBp: () => lockBp,
```

- [ ] **Step 4: Run the feature contract + reducer test**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q && node --test tests/unit/test_bodypart_cycle.mjs`
Expected: PASS — feature contract green; reducer test still green.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "feat(dlc-3d): markerEditor B2 auto-advance (autoAdvance config) + B3 Lock-BP (setLockBp)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: B4 click-near-marker selects + B5 hover cursor

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` (mousedown hit-test already selects — verify under B1; add a mousemove cursor-feedback handler)
- Test: `tests/test_marker_editor_feature.py`

**Note on B4:** click-near-marker-selects is ALREADY implemented — `wireTileCanvas` mousedown (line 383-384) hit-tests and on a hit sets `dragging`, `dragBp`, and calls `selectBp(hit)`. After Task 2 the gate is `renderActive()`, so it works the instant edit-mode is on (no overlay precondition). B4's only requirement is to confirm + cover it with a test; no new code unless the test reveals a gap. B5 (hover cursor) is the new code.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_marker_editor_feature.py`:

```python
def test_b4_b5_hit_select_and_hover_cursor():
    """B4: mousedown hit-tests existing markers and selects on a hit (already
    present; must stay gated on renderActive, not overlayEnabled). B5: a mousemove
    handler updates the focused tile's cursor — pointer over a marker, crosshair
    when a bp is selected + editable, else default."""
    src = _src()
    # B4: hit-test on mousedown selects (selectBp(hit))
    assert re.search(r"hitTest\([^)]*\)[\s;].*selectBp\(hit\)", src, re.S) or \
        "selectBp(hit)" in src, "mousedown must select the hit bodypart"
    # B5: a hover handler that sets the cursor based on a hover hit-test
    assert "mousemove" in src
    # cursor strings used for hover feedback
    for cur in ('"pointer"', '"crosshair"', '"default"'):
        assert cur in src, f"hover cursor logic must use {cur}"
    # a dedicated hover handler name (so the drag mousemove stays separate)
    assert "updateHoverCursor" in src, "must factor a hover-cursor updater"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py::test_b4_b5_hit_select_and_hover_cursor -q`
Expected: FAIL — `updateHoverCursor` / `"pointer"` absent.

- [ ] **Step 3: Implement the hover cursor (B5)**

In `src/static/components/viewer/features/marker_editor.js`, add a hover-cursor updater just below `advanceAfterPlace` (from Task 3). Insert after that function:

```javascript
  // B5 hover cursor: on the focused, editable tile, show `pointer` when hovering an
  // existing marker, `crosshair` when a bp is selected (ready to place), else default.
  function updateHoverCursor(tile, cx, cy) {
    if (!tile || !tile.canvasEl) return;
    if (tile.cam !== focusedCam || !isEditableCam(tile.cam)) { tile.canvasEl.style.cursor = "default"; return; }
    const hit = hitTest(curPosesForCam(tile.cam), cx, cy, tileScale(tile), markerSize,
      frameEditsOf(editsFor(tile.cam), currentFrame), 8);
    tile.canvasEl.style.cursor = hit ? "pointer" : (selectedBp ? "crosshair" : "default");
  }
```

Then wire it into the existing `mousemove` listener in `wireTileCanvas` (lines 386-393). The existing handler only runs the drag branch; extend it so non-drag moves update the cursor. Replace the whole mousemove listener:

```javascript
    canvas.addEventListener("mousemove", (e) => {
      const { cx, cy } = canvasPos(canvas, e);
      if (dragging && dragCam === cam) {
        didDrag = true;
        const { x, y } = canvasToVideo(cx, cy, tileScale(tile));
        editsByCam[cam] = setEdit(editsFor(cam), currentFrame, dragBp, x, y);
        renderTile(tile, currentFrame);
        return;
      }
      if (renderActive()) updateHoverCursor(tile, cx, cy);
    }, sig);
```

- [ ] **Step 4: Run the feature contract**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "feat(dlc-3d): markerEditor B4 verify hit-select + B5 hover cursor (pointer/crosshair/default)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: B6 — Space toggles per-frame visibility of the selected bp

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` (per-frame hidden store; Space handler in `onKeyDown`; render + chip reflect it)
- Test: `tests/test_marker_editor_feature.py`

**Resolution (see Ambiguities §1):** add a per-frame `hiddenByFrame` store ALONGSIDE the existing global `hiddenParts`. A bp is hidden for the current frame if it is in the global `hiddenParts` OR in `hiddenByFrame[currentFrame]`. The double-click chip toggle (global) is untouched.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_marker_editor_feature.py`:

```python
def test_b6_space_toggles_per_frame_visibility():
    """B6: Space toggles the selected bp's per-frame visibility (a per-(frame,bp)
    store), reflected in render + the `.vv-bp-chip.vis-hidden` chip. Arrows stay
    VideoViewer frame-nav (no arrow handling added here)."""
    src = _src()
    # a per-frame hidden store (distinct from the global hiddenParts Set)
    assert "hiddenByFrame" in src, "must track per-frame visibility (hiddenByFrame)"
    # Space key handled in the keyboard handler
    assert re.search(r'e\.key\s*===\s*"\s"', src) or 'e.key === " "' in src, \
        "Space (' ') must be handled for visibility toggle"
    # the union helper that render + chips consult
    assert "isHiddenAt" in src, "must factor an isHiddenAt(frame, bp) union helper"
    # arrows are NOT intercepted (frame-nav stays VideoViewer's)
    assert "ArrowLeft" not in src and "ArrowRight" not in src, \
        "markerEditor must not intercept arrow keys (frame-nav is VideoViewer's)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py::test_b6_space_toggles_per_frame_visibility -q`
Expected: FAIL — `hiddenByFrame` / `isHiddenAt` absent.

- [ ] **Step 3: Implement per-frame visibility**

In `src/static/components/viewer/features/marker_editor.js`:

3a. Add the per-frame store next to `hiddenParts` (line 47). After line 47:

```javascript
  const hiddenByFrame = new Map(); // B6: { frame -> Set<bp> } per-frame visibility (Space toggle)
```

3b. Add the union helper just below `curPoses` (after the `renderActive` helper added in Task 2):

```javascript
  // A bp is hidden at a frame if globally hidden (chip double-click) OR per-frame
  // hidden (Space toggle). Render + chip 'vis-hidden' both consult this.
  const isHiddenAt = (frame, bp) => hiddenParts.has(bp) || (hiddenByFrame.get(frame)?.has(bp) ?? false);
```

3c. In `renderTile` (line 187), replace the per-pose hide check:

```javascript
        if (hiddenParts.has(pose.bp)) continue;
```

with:

```javascript
        if (isHiddenAt(frame, pose.bp)) continue;
```

3d. In `updateBpChips` (line 267), replace the chip `.vis-hidden` toggle so it reflects the per-frame union for the current frame:

```javascript
      chip.classList.toggle("vis-hidden", isHiddenAt(currentFrame, bp));
```

3e. Add the Space handler in `onKeyDown`. Insert just after the Tab block (after line 435, before the `if (!isEditableCam...` guard) so Space works whenever a bp is selected + the tile is editable. Add:

```javascript
    if (e.key === " ") {
      if (!isEditableCam(focusedCam) || !selectedBp) return;
      e.preventDefault();
      let set = hiddenByFrame.get(currentFrame);
      if (!set) { set = new Set(); hiddenByFrame.set(currentFrame, set); }
      if (set.has(selectedBp)) set.delete(selectedBp); else set.add(selectedBp);
      renderAll();
      updateBpChips();
      return;
    }
```

- [ ] **Step 4: Run the feature contract**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "feat(dlc-3d): markerEditor B6 — Space toggles per-frame bp visibility (+chip)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: B7 — Focus persistence across videoLoad (drop the cam-0 reset, clamp)

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` (the `videoLoad` handler at lines 466-476)
- Test: `tests/test_marker_editor_feature.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_marker_editor_feature.py`:

```python
def test_b7_focus_persists_across_videoload_with_clamp():
    """B7: videoLoad must NOT reset focusedCam to 0; it preserves the last focused
    cam and only clamps to a valid tile index when the new video has fewer tiles."""
    src = _src()
    i = src.find('v.on("videoLoad"')
    if i < 0:
        i = src.find("v.on('videoLoad'")
    assert i > 0, "videoLoad subscription not found"
    # capture the handler body up to the next v.on subscription
    body = src[i:i + 700]
    assert "focusedCam = 0" not in body, \
        "videoLoad must not unconditionally reset focusedCam to 0"
    # there must be a clamp guarding a stale focusedCam against the tile count
    assert ">= " in body or ">=" in body, "videoLoad must clamp focusedCam to tile count"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py::test_b7_focus_persists_across_videoload_with_clamp -q`
Expected: FAIL — the handler still has `focusedCam = 0`.

- [ ] **Step 3: Implement focus persistence + clamp**

In `src/static/components/viewer/features/marker_editor.js`, replace the entire `videoLoad` handler (lines 466-476):

```javascript
        v.on("videoLoad", () => {
          // tiles are freshly recreated on load — reset focus to cam0 + re-wire ALL tiles'
          // canvases (each self-gates on focusedCam, so only the focused tile edits)
          focusedCam = 0;
          for (let i = 0; ; i++) {
            const t = v.getTile(i);
            if (!t) break;
            wireTileCanvas(t, sig);
            if (t.rootEl) t.rootEl.classList.toggle("vv-tile-focused", t.cam === focusedCam);
          }
        }),
```

with (B7 — preserve focus, clamp to tile count):

```javascript
        v.on("videoLoad", () => {
          // tiles are freshly recreated on load — re-wire ALL tiles' canvases (each
          // self-gates on focusedCam, so only the focused tile edits). B7: PRESERVE the
          // last focused cam across frame steps + video switches; only clamp it to a
          // valid tile when the new video has fewer cams.
          let tileCount = 0;
          for (let i = 0; ; i++) {
            const t = v.getTile(i);
            if (!t) break;
            tileCount++;
            wireTileCanvas(t, sig);
          }
          if (focusedCam >= tileCount) focusedCam = 0;
          for (let i = 0; ; i++) {
            const t = v.getTile(i);
            if (!t) break;
            if (t.rootEl) t.rootEl.classList.toggle("vv-tile-focused", t.cam === focusedCam);
          }
        }),
```

- [ ] **Step 4: Run the feature contract + policy**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py tests/test_video_viewer_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "feat(dlc-3d): markerEditor B7 — persist focusedCam across videoLoad (clamp, no cam0 reset)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Consumer wiring (inline_analysis_3d.js + template + css + UI-isolation tests)

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (markerEditor config `autoAdvance: true`; Lock-BP wire; simplify `_applyOverlayPrimary`)
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (Lock-BP checkbox in `#ia3d-marker-edit-controls`)
- Modify: `src/static/inline_analysis_3d.css` (Lock-BP control style)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

### Step 1 — Template: add the Lock-BP checkbox

- [ ] **Step 1: Write the failing test (markup contract)**

Add to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_lock_bp_checkbox_present_in_marker_edit_controls():
    """B3 consumer: a Lock-BP checkbox lives in the marker-edit controls (NOT an
    `L` shortcut — L is the keyframe range-lock). It must sit inside
    #ia3d-marker-edit-controls."""
    html = CARD.read_text()
    assert 'id="ia3d-lock-bp"' in html, "Lock-BP checkbox id missing"
    ctrls = html.index('id="ia3d-marker-edit-controls"')
    lock  = html.index('id="ia3d-lock-bp"')
    nxt   = html.find('id="ia3d-curation-panel"')
    assert ctrls < lock < nxt, "Lock-BP checkbox must sit inside the marker-edit controls block"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_lock_bp_checkbox_present_in_marker_edit_controls -q`
Expected: FAIL — `ia3d-lock-bp` absent.

- [ ] **Step 3: Add the checkbox markup**

In `src/templates/partials/card_inline_analysis_3d.html`, inside `#ia3d-marker-edit-controls` (after the Clear Frame button, line 298, before the closing `</div>` at line 299), add:

```html
          <label class="ia3d-lock-bp-label" title="Keep the selected body-part after placing (re-place to correct it) — does not auto-advance">
            <input type="checkbox" id="ia3d-lock-bp"> Lock BP
          </label>
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_lock_bp_checkbox_present_in_marker_edit_controls -q`
Expected: PASS.

### Step 5 — CSS: style the Lock-BP control

- [ ] **Step 5: Write the failing test (css contract)**

Add to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_lock_bp_label_styled():
    css = CSS.read_text()
    assert ".ia3d-lock-bp-label" in css, "Lock-BP label needs a style rule"
```

- [ ] **Step 6: Run to verify fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_lock_bp_label_styled -q`
Expected: FAIL.

- [ ] **Step 7: Add the CSS rule**

In `src/static/inline_analysis_3d.css`, after the `.vv-bp-chip.vis-hidden` rule (line 126), add:

```css
/* Lock-BP checkbox in the marker-edit controls — small inline pill matching the
   controls row typography (reuses existing tokens). */
#inline-analysis-3d-card .ia3d-lock-bp-label {
  display: inline-flex; align-items: center; gap: .3rem;
  font-size: .77rem; color: var(--text-dim); user-select: none; cursor: pointer;
}
#inline-analysis-3d-card .ia3d-lock-bp-label input { accent-color: var(--accent); cursor: pointer; }
```

- [ ] **Step 8: Run to verify pass**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_lock_bp_label_styled -q`
Expected: PASS.

### Step 9 — JS: autoAdvance config, Lock-BP wire, simplified `_applyOverlayPrimary`

- [ ] **Step 9: Write the failing tests (JS wiring)**

Add to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_inline_passes_autoadvance_and_wires_lock_bp():
    """Consumer passes autoAdvance:true to markerEditor and wires the Lock-BP
    checkbox to setLockBp."""
    js = JS.read_text()
    # autoAdvance in the markerEditor config
    i = js.find("_markerEditor = markerEditor({")
    assert i > 0, "markerEditor config not found"
    cfg = js[i:i + 1400]
    assert re.search(r"autoAdvance\s*:\s*true", cfg), "must pass autoAdvance:true"
    # Lock-BP checkbox wired to setLockBp
    assert "ia3d-lock-bp" in js, "Lock-BP checkbox must be referenced in JS"
    assert "setLockBp(" in js, "Lock-BP checkbox must drive markerEditor.setLockBp"


def test_apply_overlay_primary_no_longer_force_enables_overlay():
    """B1 consumer simplification: when Finalize is on, _applyOverlayPrimary just
    arms editing via setEditable(true); it must NOT force-enable the overlay
    (dispatch the overlay-toggle change) — B1 makes editing render without it."""
    js = JS.read_text()
    i = js.index("async function _applyOverlayPrimary")
    rest = js[i + 1:]
    ends = [x for x in (rest.find("\nasync function "), rest.find("\nfunction ")) if x != -1]
    window = js[i: i + 1 + min(ends)]
    assert "setEditable(true)" in window, "must still arm editing when Finalize is on"
    # the forced overlay-enable (toggle dispatch) must be gone from this function
    assert "ia3d-overlay-toggle" not in window, \
        "_applyOverlayPrimary must NOT force-enable the overlay (B1 decouples editing from overlay)"
    assert "dispatchEvent" not in window, \
        "_applyOverlayPrimary must not dispatch the overlay-toggle change anymore"
```

Also UPDATE the now-obsolete existing test `test_overlay_auto_enables_for_editing_when_finalize_on` (it asserts the OPPOSITE of the new B1 contract). Replace its body so it only asserts the surviving behavior — editing is armed when Finalize is on — and drops the overlay-force assertions:

```python
def test_overlay_auto_enables_for_editing_when_finalize_on():
    # B1 (2026-05-24): editing no longer hard-gates on the overlay. When Finalize is
    # on, _applyOverlayPrimary arms editing via setEditable(true) WITHOUT force-
    # enabling the overlay (the overlay toggle is now a show/hide convenience only).
    js = JS.read_text()
    i = js.index("async function _applyOverlayPrimary")
    rest = js[i + 1:]
    ends = [x for x in (rest.find("\nasync function "), rest.find("\nfunction ")) if x != -1]
    window = js[i: i + 1 + min(ends)]
    assert 'ia3d-finalize-toggle' in window, "_applyOverlayPrimary must consult the finalize toggle"
    assert 'setEditable(true)' in window, \
        "_applyOverlayPrimary must arm the edit master gate when Finalize is on"
```

- [ ] **Step 10: Run to verify fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_inline_passes_autoadvance_and_wires_lock_bp tests/test_inline_analysis_3d_ui_isolation.py::test_apply_overlay_primary_no_longer_force_enables_overlay -q`
Expected: FAIL — `autoAdvance:true` / `setLockBp` absent; `_applyOverlayPrimary` still dispatches the overlay toggle.

- [ ] **Step 11: Add `autoAdvance: true` to the markerEditor config**

In `src/static/inline_analysis_3d.js`, in the `markerEditor({...})` config (lines 162-164), add `autoAdvance: true` next to the existing options. Replace:

```javascript
    markerSize: 6,
    globalThreshold: 0.6,
    poseWindow: 30,
  });
```

with:

```javascript
    markerSize: 6,
    globalThreshold: 0.6,
    poseWindow: 30,
    autoAdvance: true, // B2: advance to next unlabeled bp after a place (labeler feel)
  });
```

- [ ] **Step 12: Wire the Lock-BP checkbox**

In `src/static/inline_analysis_3d.js`, in `_wireOverlayChrome()` (after the Save Adjustments wire, line 778), add:

```javascript
  // Lock-BP checkbox → markerEditor.setLockBp. When checked, placing re-places the
  // same bodypart (no auto-advance) — used to correct a marker. (`L` is the keyframe
  // range-lock, so this is a checkbox, not a shortcut.)
  const lockBp = $("ia3d-lock-bp");
  lockBp?.addEventListener("change", () => _markerEditor?.setLockBp(!!lockBp.checked));
```

- [ ] **Step 13: Simplify `_applyOverlayPrimary`**

In `src/static/inline_analysis_3d.js`, replace the Finalize block at the end of `_applyOverlayPrimary` (lines 874-890):

```javascript
  // Marker editing hard-gates on BOTH the editable master gate AND the overlay
  // being enabled (marker_editor.js). Finalize is on by default, but at open the
  // overlay is left off, and on the FIRST open after a page load _ensureViewer's
  // setEditable(false) (line ~171) runs AFTER _resetForOpen's setEditable(true) —
  // leaving editing off. Now that a primary h5 + bodypart are resolved (videoLoad,
  // or a manual primary pick) and the markerEditor exists, re-arm both gates when
  // Finalize is checked so editing is live without a manual toggle — parity with
  // label-frame-3d. Reuse the overlay-toggle change handler (reveals controls +
  // chips + refreshes coverage) for the overlay side.
  if ($("ia3d-finalize-toggle")?.checked) {
    _markerEditor.setEditable(true);
    const _ovToggle = $("ia3d-overlay-toggle");
    if (_ovToggle && !_ovToggle.checked) {
      _ovToggle.checked = true;
      _ovToggle.dispatchEvent(new Event("change"));
    }
  }
  _refreshCoverage();
```

with (B1 — editing renders without the overlay, so drop the forced overlay-enable):

```javascript
  // B1 (2026-05-24): marker editing no longer hard-gates on the overlay being
  // enabled — setEditable(true) makes markers render + edits live on its own. So
  // when a primary h5 + bodypart are resolved and Finalize is checked, just re-arm
  // the edit master gate (this also handles the first-open race where _ensureViewer's
  // setEditable(false) ran after _resetForOpen's setEditable(true)). The overlay
  // toggle stays a manual show/hide convenience.
  if ($("ia3d-finalize-toggle")?.checked) {
    _markerEditor.setEditable(true);
  }
  _refreshCoverage();
```

- [ ] **Step 14: Run the full inline UI-isolation + policy suite + the feature contract**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_policy.py tests/test_marker_editor_feature.py -q`
Expected: PASS — all green (including the rewritten `test_overlay_auto_enables_for_editing_when_finalize_on`).

- [ ] **Step 15: Restart the container so the template/css changes take effect, then commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d
```

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js src/templates/partials/card_inline_analysis_3d.html src/static/inline_analysis_3d.css tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): inline consumer — autoAdvance, Lock-BP checkbox, simplified _applyOverlayPrimary (B1)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Holistic verification — full suite + read-only live check + View-Analyzed regression

**Files:** none (verification only — do NOT change code; if a check fails, open a fix as a new task).

- [ ] **Step 1: Run the full JS unit + pytest suites that touch this work**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && \
  node --test tests/unit/test_bodypart_cycle.mjs tests/unit/test_viewer_marker_overlay.mjs && \
  python -m pytest tests/test_marker_editor_feature.py tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_policy.py -q
```
Expected: PASS — every selected test green.

- [ ] **Step 2: Live read-only verification of the inline card (no destructive saves)**

Write and run a throwaway `playwright.sync_api` script (do NOT commit it) that:
1. Opens `http://localhost:5000/?token=deeplabcut`, navigates into the dlc-3D module, opens the Inline Analysis 3D card on a posed fixture (e.g. DREADD-Ali / khoai-lang-1 cam0 with an existing `.h5`).
2. With Finalize checked (default) and the overlay toggle LEFT OFF, asserts markers paint (canvas has non-empty pixels / bp chips show `labeled`) — confirms B1.
3. Clicks empty space on the focused tile to place a marker, asserts the active bp chip advances to the next unlabeled bp — confirms B2.
4. Checks the Lock-BP checkbox, places again, asserts the active bp does NOT change — confirms B3.
5. Hovers an existing marker, asserts the focused canvas cursor is `pointer`; moves to empty space with a bp selected, asserts `crosshair` — confirms B5.
6. With the focused card, presses Tab (chip advances), W/A/S/D (selected marker nudges), Backspace (marker removed), Space (selected bp chip toggles `.vis-hidden`) — confirms B6.
7. Steps a frame forward then back, asserts the focused tile (`.vv-tile-focused`) is unchanged — confirms B7 focus persistence.
8. Clicks the cam1 tile, asserts `.vv-tile-focused` moves to cam1 and a subsequent click edits cam1 — confirms B7 click-to-focus.
9. **Does NOT click Save Adjustments / Add range / Extract / Finalize / Delete.** In-memory edits only.

Expected: every assertion passes. If any fail, STOP and open a fix task (do not paper over with test edits).

- [ ] **Step 3: View-Analyzed regression check (read-only consumer)**

Verify `viewer_3d.js` (View Analyzed) is unchanged in feel:
1. Static: `grep -n "setEditable\|setOverlayEnabled" src/static/viewer_3d.js` — confirm it still NEVER calls `setEditable(true)` (only `setOverlayEnabled`). With B1's `editingAllowed=false` default, its render stays keyed on `overlayEnabled` (no change).
2. Live: open View Analyzed on a posed fixture, toggle the overlay ON — markers paint; toggle OFF — markers clear. Confirm no markers paint with the overlay OFF (proves the default gate is unchanged). Confirm focus/selection behave as before.

Expected: View Analyzed behaves exactly as before B1.

- [ ] **Step 4: Final commit (if any verification-driven doc note is warranted)**

No code change expected here. If Steps 2-3 are clean, the branch is complete — proceed to the finishing-a-development-branch skill. If a defect surfaced, append a new numbered task above this one rather than editing completed tasks.

---

## Self-review

**1. Spec coverage** (each spec section → task):
- B1 decouple gate → Task 2. B2 auto-advance → Tasks 1+3. B3 Lock-BP → Task 3 (+ consumer Task 7). B4 hit-select → Task 4 (verify). B5 hover cursor → Task 4. B6 Space visibility → Task 5; arrows stay frame-nav → Task 5 test asserts no ArrowLeft/Right. B7 focus persistence + clamp → Task 6; click-to-focus highlight → existing (`setFocusedCam`) + verified Task 8. B8 save model unchanged → no task touches the save path (asserted by leaving `saveMarker`/flush untouched; verification Step 2 avoids saves). Consumer wiring (autoAdvance, Lock-BP markup+css+wire, simplified `_applyOverlayPrimary`, UI-isolation tests) → Task 7. View-Analyzed regression guard → Task 8 Step 3. Pure reducer + node:test → Task 1. Testing section (node:test, three pytest files, policy green, live read-only) → Tasks 1-8. Error handling (empty list, all-placed, clamp, per-(frame,bp) visibility) → Task 1 tests + Task 5 store + Task 6 clamp.
- No spec requirement is left without a task.

**2. Placeholder scan:** No "TBD/TODO/handle edge cases/similar to Task N". Every code step shows complete code; every run step shows the exact command + expected output. The live-verification script (Task 8 Step 2) is described step-by-step with concrete assertions and the named fixture — it is intentionally throwaway/uncommitted, consistent with the spec's "Live verification (read-only)" being a manual acceptance gate, not an automated test.

**3. Type/name consistency:**
- Reducer signatures: `nextUnlabeledBodypart(bodyparts, posedSet, current, lock=false)` and `cycleBodypart(bodyparts, current, dir)` — defined in Task 1, imported + called identically in Task 3 (`nextUnlabeledBodypart(allBodyParts, labeled, selectedBp, lockBp)`). `cycleBodypart` is exported/tested but the markerEditor Tab handler already uses the existing `nextBodypart` from `marker_overlay.mjs` (unchanged) — `cycleBodypart` is provided as the spec-named reducer and node-tested; it is not force-substituted into the working Tab path (don't refactor working code). This is intentional and noted here so a later reader doesn't "fix" a perceived unused export.
- markerEditor new API: `setLockBp(on)` / `getLockBp()` (Task 3) — consumer calls `setLockBp(...)` (Task 7). `autoAdvance` config key (Task 3 reads `config.autoAdvance`) — consumer passes `autoAdvance: true` (Task 7). Helper names `renderActive` (Task 2), `advanceAfterPlace` (Task 3), `updateHoverCursor` (Task 4), `isHiddenAt`/`hiddenByFrame` (Task 5) are each used in the same or later task exactly as defined.
- Gate expression `overlayEnabled || editingAllowed` (Task 2 helper `renderActive`) is consistent across renderTile/onFrame/handlers/onKeyDown.

All consistent — no fixes needed.
