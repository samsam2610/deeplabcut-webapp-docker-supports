# Inline 3D — Stable Chip-List Height + Finalize-Bar Region Nav — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stop the inline 3D bp-chip list from reflowing/jumping between frames (reserve its max height), and add prev/next finalized-region nav to the FINALIZED coverage bar.

**Architecture:** Inline-only. A node-tested reducer (`nextCoveredBucket` + bucket↔frame mappers) backs the region nav; the chip-height reservation is an inline measuring-class + a `_reserveBpChipHeight()` call after `setPrimary`.

**Tech Stack:** Browser ESM + `node:test`; pytest static-analysis + Playwright. No backend changes.

**Spec:** `docs/superpowers/specs/2026-05-23-inline-3d-chip-height-and-finalize-nav-design.md`

**Repo:** all under `deeplabcut-webapp-docker-supports/dlc-3D/`; git root `deeplabcut-webapp-docker-supports/` (commit `dlc-3D/...`). Template change → `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d`; JS/CSS hot-reload. No `/user-data` writes.

---

## File Structure
- `dlc-3D/src/static/components/viewer/internal/coverage_timeline.mjs` — add `nextCoveredBucket`, `bucketToFrame`, `frameToBucket`. [Task 1]
- `dlc-3D/tests/unit/test_viewer_coverage_timeline.mjs` — reducer tests. [Task 1]
- `dlc-3D/src/static/inline_analysis_3d.css` — `.ia3d-measuring` rule. [Task 2]
- `dlc-3D/src/static/inline_analysis_3d.js` — `_reserveBpChipHeight` (Task 2); finalize nav wiring (Task 3).
- `dlc-3D/src/templates/partials/card_inline_analysis_3d.html` — finalize nav buttons. [Task 3]
- `dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py` — contract. [Tasks 2,3]

---

## Task 1: Coverage nav reducers (pure, node-tested)

**Files:** Modify `dlc-3D/src/static/components/viewer/internal/coverage_timeline.mjs`; test `dlc-3D/tests/unit/test_viewer_coverage_timeline.mjs`.

- [ ] **Step 1: Failing tests** — append to `tests/unit/test_viewer_coverage_timeline.mjs` (it already imports from the module; add the new names to its import line OR import them in the new test):
```javascript
import { nextCoveredBucket, bucketToFrame, frameToBucket }
  from "../../src/static/components/viewer/internal/coverage_timeline.mjs";

test("nextCoveredBucket jumps to covered-run starts", () => {
  const b = [1, 1, 0, 0, 1, 1, 0, 1]; // run starts at 0, 4, 7
  assert.equal(nextCoveredBucket(b, 5, 1), 7);    // forward → next run start
  assert.equal(nextCoveredBucket(b, 5, -1), 4);   // back → current run start
  assert.equal(nextCoveredBucket(b, 4, -1), 0);   // back from a run start → previous run
  assert.equal(nextCoveredBucket(b, 0, -1), null);
  assert.equal(nextCoveredBucket(b, 7, 1), null);
  assert.equal(nextCoveredBucket([0, 0, 0], 0, 1), null);
});

test("bucket<->frame mapping clamps", () => {
  assert.equal(bucketToFrame(0, 10, 1000), 0);
  assert.equal(bucketToFrame(5, 10, 1000), 500);
  assert.equal(bucketToFrame(10, 10, 1000), 999);   // clamp to last frame
  assert.equal(frameToBucket(0, 1000, 10), 0);
  assert.equal(frameToBucket(999, 1000, 10), 9);     // clamp to last bucket
  assert.equal(frameToBucket(500, 1000, 10), 5);
  assert.equal(frameToBucket(0, 0, 10), 0);          // zero frames → 0
});
```
- [ ] **Step 2: Run, verify fail** — `node --test tests/unit/test_viewer_coverage_timeline.mjs` → FAIL (undefined exports).
- [ ] **Step 3: Implement** — append to `coverage_timeline.mjs`:
```javascript
// Index of the next (dir=1) / previous (dir=-1) covered-RUN start relative to
// fromBucket, or null. A run start is a covered bucket whose predecessor is not
// covered. Forward skips the rest of the current run; backward returns the
// nearest run start strictly before fromBucket (= the current run's start if
// you're past it, else the previous run).
export function nextCoveredBucket(buckets, fromBucket, dir) {
  const n = buckets.length;
  const isStart = (i) => !!buckets[i] && (i === 0 || !buckets[i - 1]);
  if (dir < 0) {
    for (let i = Math.min(fromBucket - 1, n - 1); i >= 0; i--) if (isStart(i)) return i;
    return null;
  }
  for (let i = Math.max(fromBucket + 1, 0); i < n; i++) if (isStart(i)) return i;
  return null;
}

// Map a bucket index → frame index (clamped to 0..frameCount-1).
export function bucketToFrame(bucket, nBuckets, frameCount) {
  if (nBuckets <= 0 || frameCount <= 0) return 0;
  return Math.min(frameCount - 1, Math.max(0, Math.round((bucket / nBuckets) * frameCount)));
}

// Map a frame index → bucket index (clamped to 0..nBuckets-1).
export function frameToBucket(frame, frameCount, nBuckets) {
  if (frameCount <= 0 || nBuckets <= 0) return 0;
  return Math.min(nBuckets - 1, Math.max(0, Math.floor((frame / frameCount) * nBuckets)));
}
```
- [ ] **Step 4: Run, verify pass** — `node --test tests/unit/test_viewer_coverage_timeline.mjs` → PASS; `node --test tests/unit/*.mjs` → all pass.
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/static/components/viewer/internal/coverage_timeline.mjs dlc-3D/tests/unit/test_viewer_coverage_timeline.mjs
git commit -m "feat(viewer): coverage nav reducers (nextCoveredBucket + bucket<->frame)"
```

---

## Task 2: Reserve the bp chip-list max height (inline)

**Files:** `dlc-3D/src/static/inline_analysis_3d.css`, `dlc-3D/src/static/inline_analysis_3d.js`; test `tests/test_inline_analysis_3d_ui_isolation.py`.

Context: `async function _applyOverlayPrimary(h5)` does `await _markerEditor.setPrimary(h5);` (which builds the chips into `#ia3d-bp-chips`) then resolves the sibling + calls `_refreshCoverage()`. `_resetForOpen()` resets per-card state. The chips are `.vv-bp-chip` containing `.vv-bp-check` (shown only on `.labeled`).

- [ ] **Step 1: Failing contract test** — append:
```python
def test_bp_chip_height_reserved():
    css = (ROOT / "src" / "static" / "inline_analysis_3d.css").read_text()
    assert "ia3d-measuring" in css, "measuring class (force-show checkmarks) missing"
    js = JS.read_text()
    assert "_reserveBpChipHeight" in js, "chip-height reserve helper missing"
    # called after the primary layer (chips) is built
    i = js.find("async function _applyOverlayPrimary")
    assert i > 0 and "_reserveBpChipHeight" in js[i:i+1200], "must reserve chip height after setPrimary"
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3a: CSS** — append to `inline_analysis_3d.css`:
```css
/* Measuring helper: force every checkmark visible so we can reserve the chip
   list's tallest wrap (per project). Toggled on only during measurement. */
#inline-analysis-3d-card #ia3d-bp-chips.ia3d-measuring .vv-bp-check { display: block; }
```
- [ ] **Step 3b: JS helper** — add at module scope (near the other inline helpers, e.g. above `_applyOverlayPrimary`):
```javascript
// Reserve the bp chip list's MAX height so per-frame checkmark toggles (which
// change chip width → re-wrap) can't reflow the layout and jump everything below.
// Measure with all checkmarks forced visible (widest), then pin min-height.
function _reserveBpChipHeight() {
  const c = $("ia3d-bp-chips");
  if (!c) return;
  c.style.minHeight = "";              // reset to measure the natural tallest wrap
  c.classList.add("ia3d-measuring");   // all checkmarks shown → widest chips
  const h = c.offsetHeight;
  c.classList.remove("ia3d-measuring");
  if (h > 0) c.style.minHeight = h + "px";
}
```
- [ ] **Step 3c: Call it** — in `_applyOverlayPrimary`, immediately AFTER `await _markerEditor.setPrimary(h5);` add: `_reserveBpChipHeight();`
- [ ] **Step 3d: Reset** — in `_resetForOpen`, add: `const _bc = $("ia3d-bp-chips"); if (_bc) _bc.style.minHeight = "";`
- [ ] **Step 4: Run + verify** — contract PASS; `node --input-type=module --check < src/static/inline_analysis_3d.js`. (Live height-stability check is Task 4.)
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/static/inline_analysis_3d.css dlc-3D/src/static/inline_analysis_3d.js dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "fix(dlc-3d): reserve bp chip-list max height (no per-frame layout jump)"
```

---

## Task 3: Finalize-bar region nav buttons (inline)

**Files:** `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`, `dlc-3D/src/static/inline_analysis_3d.js`; test `tests/test_inline_analysis_3d_ui_isolation.py`.

Context: the finalize bar markup is `<div …>Finalized frames (_analyzed)</div>` then `<canvas id="ia3d-finalize-coverage" …>`. In JS: `let _finalizeCoverageBuckets`/`let _redrawFinalizeCoverage` module-level; in `_wireViewerChrome`, `const finalizeCanvas = $("ia3d-finalize-coverage"); _wireSeekCanvas(finalizeCanvas); _redrawFinalizeCoverage = () => _drawCoverageBar(finalizeCanvas, _finalizeCoverageBuckets, "#fbbf24"); v.on("frameChange", () => _redrawFinalizeCoverage());`. The reducer module already exports `nextCoveredBucket`, `bucketToFrame`, `frameToBucket` (Task 1). The inline file imports from `./components/viewer/internal/coverage_timeline.mjs` (currently `coverageRects, xToFrame`).

- [ ] **Step 1: Failing contract test** — append:
```python
def test_finalize_region_nav_present_and_wired():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'id="ia3d-finalize-prev"' in html and 'id="ia3d-finalize-next"' in html, "finalize nav buttons missing"
    js = JS.read_text()
    assert "nextCoveredBucket" in js, "finalize nav must use nextCoveredBucket"
    assert "ia3d-finalize-prev" in js and "ia3d-finalize-next" in js, "finalize nav not wired"
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3a: Markup** — in `card_inline_analysis_3d.html`, REPLACE the `<div …>Finalized frames (_analyzed)</div>` line with a flex row carrying the label + nav buttons:
```html
            <div style="display:flex;align-items:center;gap:.4rem;margin:.1rem 0 .15rem">
              <span style="flex:1;font-size:.7rem;color:var(--text-dim);font-family:var(--mono)">Finalized frames (_analyzed)</span>
              <button id="ia3d-finalize-prev" class="btn-sm" disabled title="Previous finalized region" style="padding:.12rem .4rem;font-size:.72rem;line-height:1">◀</button>
              <button id="ia3d-finalize-next" class="btn-sm" disabled title="Next finalized region" style="padding:.12rem .4rem;font-size:.72rem;line-height:1">▶</button>
            </div>
```
- [ ] **Step 3b: Import** — extend the inline file's import from `./components/viewer/internal/coverage_timeline.mjs` to include `nextCoveredBucket, bucketToFrame, frameToBucket` (alongside the existing `coverageRects, xToFrame`).
- [ ] **Step 3c: Nav wiring** — in `_wireViewerChrome`, right after the existing finalize-canvas wiring (`_redrawFinalizeCoverage = …; v.on("frameChange", …)`), REPLACE the `_redrawFinalizeCoverage = …` assignment with one that also toggles the nav buttons, and add the nav handlers:
```javascript
  _redrawFinalizeCoverage = () => {
    _drawCoverageBar(finalizeCanvas, _finalizeCoverageBuckets, "#fbbf24");
    const has = !!(_finalizeCoverageBuckets && _finalizeCoverageBuckets.length);
    const pv = $("ia3d-finalize-prev"), nx = $("ia3d-finalize-next");
    if (pv) pv.disabled = !has;
    if (nx) nx.disabled = !has;
  };
  const _finalizeNav = (dir) => {
    if (!_viewer || !_finalizeCoverageBuckets || !_finalizeCoverageBuckets.length) return;
    const nB = _finalizeCoverageBuckets.length;
    const fc = _viewer.frameCount();
    const b = nextCoveredBucket(_finalizeCoverageBuckets, frameToBucket(_viewer.currentFrame(), fc, nB), dir);
    if (b == null) return;
    _viewer.pause();
    _viewer.seek(bucketToFrame(b, nB, fc));
  };
  $("ia3d-finalize-prev")?.addEventListener("click", () => _finalizeNav(-1));
  $("ia3d-finalize-next")?.addEventListener("click", () => _finalizeNav(1));
```
  (Delete the OLD single-line `_redrawFinalizeCoverage = () => _drawCoverageBar(...)` it replaces. Keep the `v.on("frameChange", () => _redrawFinalizeCoverage());` line.)
- [ ] **Step 4: Run + restart + verify** — contract PASS; `node --input-type=module --check`; `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d` (markup change).
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/src/static/inline_analysis_3d.js dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): prev/next finalized-region nav on the FINALIZED bar"
```

---

## Task 4: Full live verification

**Files:** none. Restart dlc-3d. Drive the live app (OM-2 fixture).

- [ ] **Step 1: Chip-list height stable** — open inline, select OM-2 cam0, overlay on + pick h5. Find a frame with many labeled chips and one with none (probe several frames reading `#ia3d-bp-chips` offsetHeight). Assert the offsetHeight is IDENTICAL across those frames (reserved max) and that `#ia3d-bp-chips` has a nonzero inline `min-height`.
- [ ] **Step 2: Finalize nav disabled w/o coverage** — turn Finalize on; with OM-2's `_analyzed` not initialized, assert `#ia3d-finalize-prev`/`#ia3d-finalize-next` are `disabled`.
- [ ] **Step 3: Nav logic** — covered by the Task 1 node test (region jump on bucket fixtures), since OM-2 has no `_analyzed` to populate the bar. Note this.
- [ ] **Step 4: No-regression** — `node --test tests/unit/*.mjs`; `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`; `python -m pytest tests/e2e/test_analyzed_viewer.py -q` (15).
- [ ] **Step 5: Report** with the two offsetHeight numbers (equal) + the disabled-state result.

---

## Self-Review

**Spec coverage:** §1 chip height → Task 2 (measuring class + `_reserveBpChipHeight` after setPrimary + reset). §2 finalize region nav → Task 1 (reducers) + Task 3 (buttons + wiring). Testing → per-task + Task 4. Covered.

**Placeholder scan:** none — full code in every step.

**Type/name consistency:** `nextCoveredBucket(buckets, fromBucket, dir)` / `bucketToFrame(bucket, nBuckets, frameCount)` / `frameToBucket(frame, frameCount, nBuckets)` defined in Task 1, imported + called identically in Task 3. `_reserveBpChipHeight` defined + called (Task 2). `_finalizeCoverageBuckets`/`_redrawFinalizeCoverage` reused from the existing finalize feature.

**Flagged for implementers:** (a) Task 3 REPLACES the existing one-line `_redrawFinalizeCoverage` assignment (don't leave both). (b) Task 2's `.ia3d-measuring` only flips `display` on `.vv-bp-check` — it must NOT touch `.labeled` (markerEditor owns that per frame). (c) Live nav (Task 4 Step 3) can't be exercised on OM-2 (no `_analyzed`); the reducer node test covers the jump logic.
