# Inline 3D — Keyframe-Window Finalize Range — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inline-3D Finalize panel's "Start frame + Frames" inputs with a clip-cutter-style keyframe window: keyframe (= current frame), `before`/`after`/`length` (all editable, `length = before + after + 1`), and a lock (checkbox + `l` shortcut) that freezes the keyframe while navigating. The finalized range = `[keyframe − before, keyframe + after]`.

**Architecture:** Frontend-only, dlc-3D. New pure module `keyframe_window.mjs` (`syncWindow`, `finalizeRange`) — node-tested. Markup swap in `card_inline_analysis_3d.html`. Glue in `inline_analysis_3d.js` (state, frameChange tracking, field sync, lock + `l`, finalize derivation). Backend `finalize-range {start_frame, n_frames}` unchanged.

**Tech Stack:** Vanilla ES modules, Jinja2 partial. node:test for the pure module; static-analysis pytest for DOM/glue contracts.

**Spec:** `docs/superpowers/specs/2026-05-24-inline-3d-finalize-keyframe-window-design.md`

**Working dir for all commands:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

**Run only the test files named in each task — never the whole pytest suite.**

---

### Task 1: Pure keyframe-window math (`keyframe_window.mjs`)

**Files:**
- Create: `src/static/components/viewer/internal/keyframe_window.mjs`
- Test: `tests/unit/test_viewer_keyframe_window.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_viewer_keyframe_window.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { syncWindow, finalizeRange } from "../../src/static/components/viewer/internal/keyframe_window.mjs";

test("syncWindow: editing before/after recomputes length (=before+after+1)", () => {
  assert.deepEqual(syncWindow("before", { before: 50, after: 200, length: 401 }), { before: 50, after: 200, length: 251 });
  assert.deepEqual(syncWindow("after", { before: 200, after: 50, length: 401 }), { before: 200, after: 50, length: 251 });
});

test("syncWindow: editing length keeps `before`, recomputes after (clamped >= 0)", () => {
  assert.deepEqual(syncWindow("length", { before: 100, after: 50, length: 400 }), { before: 100, after: 299, length: 400 });
  // length below before+1 → after clamps to 0, length re-syncs up to before+1
  assert.deepEqual(syncWindow("length", { before: 200, after: 200, length: 100 }), { before: 200, after: 0, length: 201 });
});

test("syncWindow: coerces to non-negative ints", () => {
  assert.deepEqual(syncWindow("before", { before: -5, after: 10, length: 1 }), { before: 0, after: 10, length: 11 });
});

test("finalizeRange: window around the keyframe, clamped to [0, frameCount-1]", () => {
  assert.deepEqual(finalizeRange(1234, 200, 200, 3000), { start: 1034, end: 1434, n: 401 });
  assert.deepEqual(finalizeRange(100, 200, 200, 3000), { start: 0, end: 300, n: 301 });     // clamp low
  assert.deepEqual(finalizeRange(2950, 200, 200, 3000), { start: 2750, end: 2999, n: 250 }); // clamp high (last=2999)
  assert.deepEqual(finalizeRange(50, 0, 0, 3000), { start: 50, end: 50, n: 1 });             // single frame
});
```

- [ ] **Step 2: Run to verify FAIL**

Run: `node --test tests/unit/test_viewer_keyframe_window.mjs`
Expected: FAIL (module/exports missing).

- [ ] **Step 3: Implement the module**

Create `src/static/components/viewer/internal/keyframe_window.mjs`:

```javascript
// Pure keyframe-window math for the inline-3D Finalize panel: a keyframe with N
// frames before + M frames after defines an exact-length window (keyframe
// inclusive, so length = before + after + 1). No DOM.

const toInt = (v, min) => {
  const n = Math.floor(Number(v));
  return Number.isFinite(n) ? Math.max(min, n) : min;
};

// Keep before/after/length consistent after the user edits one field.
// `edited` is "before" | "after" | "length":
//  - before/after edited → recompute length.
//  - length edited       → keep `before`, recompute after = max(0, length-before-1),
//                          then re-sync length (so a too-small length clamps up).
export function syncWindow(edited, { before, after, length }) {
  let b = toInt(before, 0), a = toInt(after, 0), l = toInt(length, 1);
  if (edited === "length") a = Math.max(0, l - b - 1);
  l = b + a + 1;
  return { before: b, after: a, length: l };
}

// Finalized range for a keyframe: [keyframe-before, keyframe+after], clamped to
// [0, frameCount-1]. n is the (clamped) inclusive frame count.
export function finalizeRange(keyframe, before, after, frameCount) {
  const k = toInt(keyframe, 0), b = toInt(before, 0), a = toInt(after, 0);
  const last = Math.max(0, (Number(frameCount) | 0) - 1);
  const start = Math.min(Math.max(k - b, 0), last);
  const end = Math.min(Math.max(k + a, 0), last);
  return { start, end, n: end - start + 1 };
}
```

- [ ] **Step 4: Run to verify PASS**

Run: `node --test tests/unit/test_viewer_keyframe_window.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/internal/keyframe_window.mjs tests/unit/test_viewer_keyframe_window.mjs
git commit -m "feat(viewer): pure keyframe-window math (syncWindow + finalizeRange)

before/after/length stay consistent (length=before+after+1); finalizeRange maps
a keyframe window to a clamped [start,end,n] frame range. Node-tested.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Finalize panel markup (`card_inline_analysis_3d.html`)

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (the Start/Frames row inside `#ia3d-finalize-controls`)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_finalize_keyframe_window_markup():
    html = CARD.read_text()
    for need in ["ia3d-finalize-keyframe", "ia3d-finalize-lock", "ia3d-finalize-before",
                 "ia3d-finalize-after", "ia3d-finalize-length", "ia3d-finalize-range"]:
        assert need in html, f"missing finalize keyframe element id {need!r}"
    # the old start/count inputs are gone
    assert "ia3d-finalize-start" not in html, "old finalize Start-frame input must be removed"
    assert "ia3d-finalize-count" not in html, "old finalize Frames-count input must be removed"
    # the Add button + finalized coverage bar are kept
    assert "ia3d-finalize-add-btn" in html and "ia3d-finalize-coverage" in html
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_keyframe_window_markup -q`
Expected: FAIL.

- [ ] **Step 3: Replace the Start/Frames row**

In `src/templates/partials/card_inline_analysis_3d.html`, find the row inside `#ia3d-finalize-controls` that currently holds the Start-frame input, Frames input, and the Add button (the `<div style="display:flex;…margin-bottom:.4rem">` containing `#ia3d-finalize-start`, `#ia3d-finalize-count`, `#ia3d-finalize-add-btn`). Replace that ONE `<div>…</div>` block with these three rows (keep everything else in `#ia3d-finalize-controls` — the "Finalized frames" nav row, the coverage canvas, and the status div — unchanged):

```html
            <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.35rem">
              <span style="font-size:.76rem;color:var(--text-dim)">Keyframe</span>
              <span id="ia3d-finalize-keyframe" style="font-family:var(--mono);font-size:.78rem;color:var(--text);min-width:3rem">0</span>
              <label style="display:flex;align-items:center;gap:.3rem;font-size:.74rem;color:var(--text-dim);cursor:pointer;user-select:none">
                <input type="checkbox" id="ia3d-finalize-lock" style="accent-color:var(--accent);width:13px;height:13px"/>
                Lock (l)
              </label>
            </div>
            <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;margin-bottom:.35rem">
              <label style="font-size:.74rem;color:var(--text-dim)">before</label>
              <input type="number" id="ia3d-finalize-before" value="200" min="0"
                style="width:4.4rem;font-size:.76rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.22rem .4rem" />
              <label style="font-size:.74rem;color:var(--text-dim)">after</label>
              <input type="number" id="ia3d-finalize-after" value="200" min="0"
                style="width:4.4rem;font-size:.76rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.22rem .4rem" />
              <label style="font-size:.74rem;color:var(--text-dim)">length</label>
              <input type="number" id="ia3d-finalize-length" value="401" min="1"
                style="width:4.9rem;font-size:.76rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.22rem .4rem" />
            </div>
            <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.4rem">
              <span id="ia3d-finalize-range" style="flex:1;font-size:.72rem;color:var(--text-dim);font-family:var(--mono)">frames 0–0 (0)</span>
              <button class="btn-sm btn-create" id="ia3d-finalize-add-btn"
                title="Save marker edits to both cameras' layers, then copy this keyframe window into each camera's _analyzed file">
                Add range to _analyzed
              </button>
            </div>
```

- [ ] **Step 4: Update the existing finalize-markup test**

An existing test asserts the OLD ids exist and will now break. In `tests/test_inline_analysis_3d_ui_isolation.py`, find `test_finalize3d_minicard_present_after_curation` and edit its `needed` list to drop `"ia3d-finalize-start"` and `"ia3d-finalize-count"` (keep the rest):

```python
    for needed in ["ia3d-finalize-toggle", "ia3d-finalize-controls",
                   "ia3d-finalize-add-btn", "ia3d-finalize-status"]:
        assert f'id="{needed}"' in html, f"missing {needed!r}"
```

- [ ] **Step 5: Run to verify PASS**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_keyframe_window_markup tests/test_inline_analysis_3d_ui_isolation.py::test_finalize3d_minicard_present_after_curation -q`
Expected: PASS. (Other tests in the file may still fail until Task 3 removes the JS refs to the old ids — that's expected; do not run the whole file yet.)

- [ ] **Step 6: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): finalize panel — keyframe/before/after/length/lock markup

Replaces the Start-frame + Frames inputs with a keyframe display + lock checkbox,
before/after/length number inputs, and a live range readout. JS wiring lands next.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Finalize keyframe glue (`inline_analysis_3d.js`)

**Files:**
- Modify: `src/static/inline_analysis_3d.js`
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

**Context:** All four control ids from Task 2 exist. The backend call `_ia3dFinalizeOne(video, h5, startFrame, nFrames)` and the save/confirm flow in `_onFinalizeAddClick` stay; only the start/n derivation changes. The viewer emits `frameChange`; `$(id)` = `getElementById`; `_viewer.currentFrame()` / `_viewer.frameCount()` exist. `_ia3dLastRunStart` / `_ia3dLastRunN` (6 refs) exist solely to autopopulate the old finalize fields and must be removed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_finalize_keyframe_glue_wired():
    js = JS.read_text()
    # pure module imported + used
    assert re.search(r"import\s*\{[^}]*\bsyncWindow\b[^}]*\bfinalizeRange\b[^}]*\}\s*from\s*[\"'][^\"']*keyframe_window\.mjs[\"']", js) \
        or ("syncWindow" in js and "finalizeRange" in js and "keyframe_window.mjs" in js), \
        "must import syncWindow + finalizeRange from keyframe_window.mjs"
    assert "finalizeRange(" in js and "syncWindow(" in js
    # keyframe + lock state
    assert "_finalizeKeyframe" in js and "_finalizeLocked" in js
    # 'l' shortcut toggles the lock
    assert re.search(r'e\.key\s*===\s*"l"', js) or re.search(r"\.key\s*===\s*'l'", js), \
        "must wire an 'l' key shortcut for the finalize lock"
    # old start/count refs and last-run autopopulate state are gone
    assert "ia3d-finalize-start" not in js and "ia3d-finalize-count" not in js
    assert "_ia3dLastRun" not in js, "old last-run finalize autopopulate state must be removed"
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_keyframe_glue_wired -q`
Expected: FAIL.

- [ ] **Step 3: Import the pure module**

At the top of `src/static/inline_analysis_3d.js`, with the other `components/viewer/internal/*` imports, add:

```javascript
import { syncWindow, finalizeRange } from "./components/viewer/internal/keyframe_window.mjs";
```

- [ ] **Step 4: Replace the last-run state with keyframe state**

Find the declarations (near the top):

```javascript
let _ia3dLastRunStart = null;
let _ia3dLastRunN = null;
```

Replace with:

```javascript
let _finalizeKeyframe = 0;     // keyframe frame# for the finalize window (= current frame unless locked)
let _finalizeLocked = false;   // when true the keyframe is frozen while navigating
```

- [ ] **Step 5: Add the finalize-window helpers (module level)**

Add these functions near `_ia3dPopulateFinalizeFields` (module scope):

```javascript
// Read before/after/length from the inputs.
function _finalizeWindowVals() {
  return {
    before: parseInt($("ia3d-finalize-before")?.value, 10) || 0,
    after:  parseInt($("ia3d-finalize-after")?.value, 10) || 0,
    length: parseInt($("ia3d-finalize-length")?.value, 10) || 1,
  };
}

// Refresh the keyframe display + the range readout from current state.
function _refreshFinalizeWindow() {
  const kfEl = $("ia3d-finalize-keyframe");
  if (kfEl) kfEl.textContent = String(_finalizeKeyframe);
  const { before, after } = _finalizeWindowVals();
  const r = finalizeRange(_finalizeKeyframe, before, after, _viewer ? _viewer.frameCount() : 0);
  const rng = $("ia3d-finalize-range");
  if (rng) rng.textContent = `frames ${r.start}–${r.end} (${r.n})`;
}

// A before/after/length edit → normalize via syncWindow, write back, refresh.
function _onFinalizeWindowInput(edited) {
  const out = syncWindow(edited, _finalizeWindowVals());
  const b = $("ia3d-finalize-before"), a = $("ia3d-finalize-after"), l = $("ia3d-finalize-length");
  if (b) b.value = out.before;
  if (a) a.value = out.after;
  if (l) l.value = out.length;
  _refreshFinalizeWindow();
}

// Lock/unlock the keyframe (checkbox + 'l' share this). Unlocking snaps the
// keyframe to the current frame; locking freezes it where it is.
function _setFinalizeLock(on) {
  _finalizeLocked = !!on;
  const cb = $("ia3d-finalize-lock");
  if (cb) cb.checked = _finalizeLocked;
  if (!_finalizeLocked && _viewer) _finalizeKeyframe = _viewer.currentFrame();
  _refreshFinalizeWindow();
}
```

- [ ] **Step 6: Track the keyframe on frameChange**

In `_wireViewerChrome`, right after the existing `v.on("frameChange", (n) => { _redrawSeekTimeline(); _updateCounters(n, v.frameCount()); _swapPlayIcon(v.isPlaying()); });` block, add:

```javascript
  v.on("frameChange", (n) => {
    if (!_finalizeLocked) { _finalizeKeyframe = n; _refreshFinalizeWindow(); }
  });
```

- [ ] **Step 7: Wire the inputs, lock checkbox, and `l` shortcut**

In the finalize wiring area (right after `$("ia3d-finalize-add-btn")?.addEventListener("click", _onFinalizeAddClick);`), add:

```javascript
  $("ia3d-finalize-before")?.addEventListener("input", () => _onFinalizeWindowInput("before"));
  $("ia3d-finalize-after")?.addEventListener("input", () => _onFinalizeWindowInput("after"));
  $("ia3d-finalize-length")?.addEventListener("input", () => _onFinalizeWindowInput("length"));
  ["ia3d-finalize-before", "ia3d-finalize-after", "ia3d-finalize-length"].forEach((id) =>
    $(id)?.addEventListener("keydown", (e) => e.stopPropagation()));  // don't bubble arrows to viewer keynav
  $("ia3d-finalize-lock")?.addEventListener("change", (e) => _setFinalizeLock(e.target.checked));
  // 'l' toggles the finalize lock — only when Finalize is on, the card is visible,
  // and focus isn't in a text field (so it won't clash with viewer/marker keys).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "l" && e.key !== "L") return;
    if (!$("ia3d-finalize-toggle")?.checked) return;
    const card = $("inline-analysis-3d-card");
    if (!card || card.offsetParent === null) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    e.preventDefault();
    _setFinalizeLock(!_finalizeLocked);
  });
```

- [ ] **Step 8: Replace `_ia3dPopulateFinalizeFields` body**

Replace the whole function:

```javascript
function _ia3dPopulateFinalizeFields() {
  const s = $("ia3d-finalize-start"), c = $("ia3d-finalize-count"), fpc = $("ia3d-frames-per-click");
  const curFrame = _viewer ? _viewer.currentFrame() : 0;
  if (s) s.value = (_ia3dLastRunStart != null ? _ia3dLastRunStart : (curFrame || 0));
  if (c) c.value = (_ia3dLastRunN != null ? _ia3dLastRunN : (parseInt(fpc?.value, 10) || 500));
}
```

with:

```javascript
function _ia3dPopulateFinalizeFields() {
  // keyframe = current frame, unlocked; before/after keep their input defaults.
  _setFinalizeLock(false);   // sets _finalizeKeyframe = current frame + refreshes the range
}
```

- [ ] **Step 9: Use `finalizeRange` in `_onFinalizeAddClick`**

In `_onFinalizeAddClick`, replace:

```javascript
  const startFrame = parseInt($("ia3d-finalize-start")?.value, 10) || 0;
  const nFrames = parseInt($("ia3d-finalize-count")?.value, 10) || 0;
```

with:

```javascript
  const { before, after } = _finalizeWindowVals();
  const _rng = finalizeRange(_finalizeKeyframe, before, after, _viewer ? _viewer.frameCount() : 0);
  const startFrame = _rng.start, nFrames = _rng.n;
```

(The rest of `_onFinalizeAddClick` — the overwrite confirm using `startFrame`/`nFrames`, the save, the two `_ia3dFinalizeOne` calls — is unchanged.)

- [ ] **Step 10: Remove the two `_ia3dLastRun` assignments + the reset**

Find and delete the assignment lines in the analysis-run-start handler:

```javascript
  _ia3dLastRunStart = startFrame;
  _ia3dLastRunN     = nFrames;
```

(Leave the surrounding `startFrame`/`nFrames` locals and the `lastRun.textContent = …` line; only remove these two assignments.) Also delete the reset lines in `_resetForOpen`:

```javascript
  _ia3dLastRunStart = null;
  _ia3dLastRunN = null;
```

and replace them with:

```javascript
  _finalizeLocked = false;
```

- [ ] **Step 11: Run to verify PASS + full affected suites**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q && node --test tests/unit/*.mjs`
Expected: pytest PASS (all, including Task 2's markup test and this glue test); node `# fail 0`.

Then confirm no stray references remain:
Run: `grep -n "_ia3dLastRun\|ia3d-finalize-start\|ia3d-finalize-count" src/static/inline_analysis_3d.js`
Expected: no output.

- [ ] **Step 12: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): wire finalize keyframe window (before/after/length + lock + 'l')

Keyframe follows the current frame (unless locked); before/after/length stay
consistent via syncWindow; the lock checkbox and 'l' shortcut freeze the keyframe
while scrubbing. Add-range derives start/n via finalizeRange. Removes the old
start/count inputs and the last-run autopopulate state.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Live verification (controller, after all tasks; restart dlc-3d for the template change)
With the inline card open on a video + overlay, Finalize toggled on:
1. Keyframe display = current frame; scrubbing updates it and the range readout.
2. Check the Lock box (or press `l`) → scrub → keyframe stays frozen; range readout unchanged. Uncheck/`l` again → keyframe snaps to current frame.
3. Edit `before`/`after` → `length` updates (=before+after+1) and the readout shows `[kf−before, kf+after]`; edit `length` → `after` adjusts (before pinned).
4. Click **Add range to _analyzed** → the confirm dialog / status shows the keyframe-derived `start–end` (do NOT confirm a write to protected data; cancel after verifying the numbers).

## Out of scope (YAGNI)
- Keyframe model for the working-layer clip extractor.
- Draggable keyframe overlay on the timeline.
- Typing the keyframe number directly.
