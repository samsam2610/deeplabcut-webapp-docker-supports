# Inline 3D Marker-Coverage Timeline + Frame-Labeler Chips — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the inline 3D card's seek bar into a status/note-style canvas that paints likelihood-filtered marker-coverage (recomputing as the threshold changes) with click/drag seek, and render the body-part chips with the exact frame-labeler structure.

**Architecture:** A pure node-tested reducer does the bucket→rect + x→frame math; a small additive backend route computes coverage from the already-cached `poses_np`; the inline card replaces its range input with a canvas it draws/wires; markerEditor renders the richer chip structure (shared, benefits View Analyzed).

**Tech Stack:** Browser ESM + `node:test`; Flask (`dlc/viewer.py`) + NumPy; pytest static-analysis + Playwright.

**Spec:** `docs/superpowers/specs/2026-05-23-inline-3d-marker-coverage-timeline-design.md`

**Repos & paths:** dlc-3D work is under `deeplabcut-webapp-docker-supports/dlc-3D/`; the backend route is in `deeplabcut-webapp-docker/src/dlc/viewer.py`. The git repo root for dlc-3D is `deeplabcut-webapp-docker-supports/` (commit dlc-3D paths as `dlc-3D/...`); the main webapp is a **separate git repo** at `deeplabcut-webapp-docker/` (commit there separately).

**Global constraints:** Template (`.html`) edits need `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d`; the backend route is in the **flask/main-webapp** container — `docker compose restart flask` (the `/dlc/viewer/*` routes are served by flask, proxied). JS/CSS hot-reload. No `/user-data` writes. Live: `localhost:5000/dlc-3d/`, token `deeplabcut`, project DREADD-Ali-2026-01-07, fixture `OM-2_cam0_20260424…` in `tdcs/042426` (has h5 + sibling + annotations).

---

## File Structure
- Create `dlc-3D/src/static/components/viewer/internal/coverage_timeline.mjs` — pure: `coverageRects`, `xToFrame`. [Task 1]
- `deeplabcut-webapp-docker/src/dlc/viewer.py` — add `pose-coverage` route + a pure `_coverage_buckets` helper. [Task 2]
- `deeplabcut-webapp-docker/src/dlc/viewer.py` test (its existing test module) — coverage helper test. [Task 2]
- `dlc-3D/src/templates/partials/card_inline_analysis_3d.html` — seek `<input>` → `<canvas id="ia3d-seek-canvas">`. [Task 3]
- `dlc-3D/src/static/inline_analysis_3d.js` — canvas draw + click/drag seek (Task 3), coverage fetch + threshold-debounce (Task 4).
- `dlc-3D/src/static/inline_analysis_3d.css` + `viewer_3d.css` — seek canvas + chip dot/check/eye styles. [Tasks 3,5]
- `dlc-3D/src/static/components/viewer/features/marker_editor.js` — chip sub-structure. [Task 5]
- `dlc-3D/tests/unit/test_viewer_coverage_timeline.mjs`, `tests/test_marker_editor_feature.py`, `tests/test_inline_analysis_3d_ui_isolation.py`. [Tasks 1,5,3-4]

---

## Task 1: Coverage timeline reducer (pure, node-tested)

**Files:** Create `dlc-3D/src/static/components/viewer/internal/coverage_timeline.mjs`; test `dlc-3D/tests/unit/test_viewer_coverage_timeline.mjs`.

- [ ] **Step 1: Write failing test** — create `tests/unit/test_viewer_coverage_timeline.mjs`:
```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { coverageRects, xToFrame } from "../../src/static/components/viewer/internal/coverage_timeline.mjs";

test("coverageRects maps covered buckets to merged x-rects scaled to width", () => {
  // 4 buckets, width 100 → each bucket 25px. covered = [1,1,0,1]
  const rects = coverageRects([1, 1, 0, 1], 100);
  // adjacent covered buckets merge into one rect; the lone last bucket is its own
  assert.deepEqual(rects, [{ x: 0, w: 50 }, { x: 75, w: 25 }]);
});

test("coverageRects: empty / all-zero → no rects", () => {
  assert.deepEqual(coverageRects([], 100), []);
  assert.deepEqual(coverageRects([0, 0, 0], 100), []);
});

test("xToFrame maps a pixel to a clamped frame index", () => {
  assert.equal(xToFrame(0, 100, 1000), 0);
  assert.equal(xToFrame(100, 100, 1000), 999);   // clamped to last frame
  assert.equal(xToFrame(50, 100, 1001), 500);
  assert.equal(xToFrame(-5, 100, 1000), 0);       // clamp low
  assert.equal(xToFrame(50, 0, 1000), 0);         // zero width → 0
});
```
- [ ] **Step 2: Run, verify fail** — `node --test tests/unit/test_viewer_coverage_timeline.mjs` → FAIL (module missing).
- [ ] **Step 3: Implement** — create `src/static/components/viewer/internal/coverage_timeline.mjs`:
```javascript
// Pure geometry for the marker-coverage timeline: turn a downsampled coverage
// bitmap into x-rects to fill, and map a click x back to a frame index. No DOM.

// buckets: array of 0/1 (covered). Returns merged [{x,w}] spans scaled to `width`.
export function coverageRects(buckets, width) {
  const n = buckets.length;
  if (!n || !width) return [];
  const rects = [];
  let runStart = -1;
  for (let i = 0; i <= n; i++) {
    const on = i < n && !!buckets[i];
    if (on && runStart < 0) runStart = i;
    else if (!on && runStart >= 0) {
      const x = Math.round((runStart / n) * width);
      const xEnd = Math.round((i / n) * width);
      rects.push({ x, w: Math.max(1, xEnd - x) });
      runStart = -1;
    }
  }
  return rects;
}

// Map a pixel x (0..width) to a frame index (0..frameCount-1), clamped.
export function xToFrame(px, width, frameCount) {
  if (!width || frameCount <= 0) return 0;
  const frac = Math.min(1, Math.max(0, px / width));
  return Math.min(frameCount - 1, Math.max(0, Math.round(frac * (frameCount - 1))));
}
```
- [ ] **Step 4: Run, verify pass** — `node --test tests/unit/test_viewer_coverage_timeline.mjs` → PASS.
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/static/components/viewer/internal/coverage_timeline.mjs dlc-3D/tests/unit/test_viewer_coverage_timeline.mjs
git commit -m "feat(viewer): coverage_timeline reducer (coverageRects + xToFrame)"
```

---

## Task 2: Backend `/dlc/viewer/pose-coverage` (main webapp)

**Files:** Modify `deeplabcut-webapp-docker/src/dlc/viewer.py`; test in that repo's test suite (find the module that imports from `dlc.viewer`, e.g. `deeplabcut-webapp-docker/tests/` — match its import + run style; if none exists, create `deeplabcut-webapp-docker/tests/test_pose_coverage.py`).

Context: `viewer_load_h5(h5_path)` returns `{"df","scorer","bodyparts","poses_np","mtime"}` where `poses_np` is `np.float32` shape `(n_frames, n_bps, 3)` (dim2: 0=x,1=y,2=likelihood). `_np` is the module's numpy alias. The blueprint `bp` serves `/dlc/viewer/...`. Routes use `request`/`jsonify` (already imported).

- [ ] **Step 1: Write failing test** — `deeplabcut-webapp-docker/tests/test_pose_coverage.py` (adjust import to the repo convention):
```python
import numpy as np
from dlc import viewer as v


def test_coverage_buckets_thresholds_and_downsamples():
    # 6 frames, 2 bodyparts, dim2=[x,y,likelihood]
    poses = np.zeros((6, 2, 3), dtype=np.float32)
    # likelihoods per frame (bp0,bp1): f0 .9/.1, f1 .2/.2, f2 nan/.8, f3 0/0, f4 .7/0, f5 .05/.05
    poses[:, 0, 2] = [0.9, 0.2, np.nan, 0.0, 0.7, 0.05]
    poses[:, 1, 2] = [0.1, 0.2, 0.8, 0.0, 0.0, 0.05]
    # threshold 0.6 → covered per frame: [T,F,T,F,T,F]
    out = v._coverage_buckets(poses, threshold=0.6, n_buckets=3)
    # 6 frames → 3 buckets of 2: [T|F]=1, [T|F]=1, [T|F]=1
    assert out == [1, 1, 1]
    # threshold 0.95 → none covered
    assert v._coverage_buckets(poses, threshold=0.95, n_buckets=3) == [0, 0, 0]
    # buckets capped at n_frames
    assert len(v._coverage_buckets(poses, threshold=0.6, n_buckets=100)) == 6


def test_coverage_buckets_empty():
    assert v._coverage_buckets(np.zeros((0, 2, 3), dtype=np.float32), 0.6, 10) == []
```
- [ ] **Step 2: Run, verify fail** — `cd deeplabcut-webapp-docker && python -m pytest tests/test_pose_coverage.py -q` → FAIL (helper missing). Fix the import path to the repo convention if needed.
- [ ] **Step 3: Implement** — in `src/dlc/viewer.py` add the helper (near `viewer_load_h5`) and the route (near `frame-poses`):
```python
def _coverage_buckets(poses_np, threshold: float, n_buckets: int) -> list:
    """Per-frame 'has >=1 bodypart at likelihood >= threshold', downsampled to
    n_buckets (capped at n_frames). NaN likelihoods compare False. Returns 0/1 list."""
    n = int(poses_np.shape[0]) if poses_np is not None else 0
    if n == 0:
        return []
    covered = (poses_np[:, :, 2] >= float(threshold)).any(axis=1)  # (n,) bool; NaN→False
    b = max(1, min(int(n_buckets), n))
    idx = (_np.arange(n) * b) // n            # frame → bucket
    out = _np.zeros(b, dtype=bool)
    _np.logical_or.at(out, idx, covered)
    return out.astype(int).tolist()


@bp.route("/dlc/viewer/pose-coverage")
def viewer_pose_coverage():
    h5_path   = request.args.get("h5", "")
    threshold = float(request.args.get("threshold", 0.6) or 0.6)
    n_buckets = int(request.args.get("buckets", 600) or 600)
    if not h5_path:
        return jsonify({"error": "h5 required"}), 400
    try:
        h5_data = viewer_load_h5(h5_path)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"could not load h5: {e}"}), 422
    poses_np = h5_data.get("poses_np")
    buckets  = _coverage_buckets(poses_np, threshold, n_buckets)
    return jsonify({"buckets": buckets, "n_frames": int(poses_np.shape[0]) if poses_np is not None else 0,
                    "n_buckets": len(buckets)})
```
(If `request`/`jsonify`/`_np` aren't the exact names in this file, match the file's existing imports — `frame-poses` routes show them.)
- [ ] **Step 4: Run, verify pass** — `python -m pytest tests/test_pose_coverage.py -q` → PASS (3 cases).
- [ ] **Step 5: Commit (main webapp repo)**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/viewer.py tests/test_pose_coverage.py
git commit -m "feat(viewer): /dlc/viewer/pose-coverage — likelihood-filtered per-frame coverage buckets"
```
Then `docker compose restart flask` so the route serves.

---

## Task 3: Main timeline as a canvas (replace seek slider)

**Files:** `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`, `dlc-3D/src/static/inline_analysis_3d.js`, `dlc-3D/src/static/inline_analysis_3d.css`, test `tests/test_inline_analysis_3d_ui_isolation.py`.

- [ ] **Step 1: Failing contract test** — append:
```python
def test_main_timeline_is_canvas():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'id="ia3d-seek-canvas"' in html, "main timeline must be a canvas"
    assert 'id="ia3d-seek"' not in html, "the range-input seek must be removed"
    js = JS.read_text()
    assert "coverage_timeline.mjs" in js, "must import the coverage reducer"
    assert "ia3d-seek-canvas" in js and "coverageRects" in js and "xToFrame" in js
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3a: Markup** — in `card_inline_analysis_3d.html` replace the seek line `<input type="range" id="ia3d-seek" class="fe-seek" ... />` with:
```html
        <canvas id="ia3d-seek-canvas" height="14" title="Click or drag to seek"
          style="width:100%;display:block;margin-bottom:.4rem;cursor:pointer"></canvas>
```
- [ ] **Step 3b: CSS** — append to `inline_analysis_3d.css`:
```css
#inline-analysis-3d-card #ia3d-seek-canvas {
  background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
}
```
- [ ] **Step 3c: JS — import + draw + seek** — in `inline_analysis_3d.js`:
  - Add import: `import { coverageRects, xToFrame } from "./components/viewer/internal/coverage_timeline.mjs";`
  - Add module state near the other `let _…` declarations: `let _coverageBuckets = null;` (set by Task 4).
  - Replace the old seek-slider wiring block in `_wireViewerChrome(v)` (the `const seek = $("ia3d-seek"); … seek?.addEventListener(…); … change…`) with:
```javascript
  // Main timeline canvas: dark track + marker-coverage marks + playhead; click/drag to seek.
  const seekCanvas = $("ia3d-seek-canvas");
  function _drawSeekTimeline() {
    if (!seekCanvas) return;
    const w = Math.round(seekCanvas.getBoundingClientRect().width) || seekCanvas.clientWidth || 600;
    seekCanvas.width = w;
    const h = seekCanvas.height || 14;
    const ctx = seekCanvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    // coverage marks (only when overlay on + buckets loaded)
    if (_coverageBuckets && _coverageBuckets.length) {
      ctx.fillStyle = "var(--accent)" in {} ? "#6ee7b7" : getComputedStyle(seekCanvas).getPropertyValue("--accent") || "#6ee7b7";
      for (const r of coverageRects(_coverageBuckets, w)) ctx.fillRect(r.x, 0, r.w, h);
    }
    // playhead
    const fc = v.frameCount();
    if (fc > 0) {
      const x = Math.round((v.currentFrame() / Math.max(fc - 1, 1)) * w);
      ctx.save(); ctx.globalAlpha = 0.85; ctx.fillStyle = "#fff";
      ctx.fillRect(x, 0, 2, h); ctx.restore();
    }
  }
  let _seekDragging = false;
  const _seekToX = (e) => {
    const rect = seekCanvas.getBoundingClientRect();
    v.seek(xToFrame(e.clientX - rect.left, rect.width, v.frameCount()));
  };
  seekCanvas?.addEventListener("mousedown", (e) => { _seekDragging = true; v.pause(); _seekToX(e); });
  document.addEventListener("mousemove", (e) => { if (_seekDragging) _seekToX(e); });
  document.addEventListener("mouseup", () => { _seekDragging = false; });
  // expose for Task 4 + redraw on frame/load
  _redrawSeekTimeline = _drawSeekTimeline;
  v.on("videoLoad", () => _drawSeekTimeline());
  v.on("frameChange", () => _drawSeekTimeline());
```
  - Replace the old `v.on("frameChange", (n) => { if (seek && !_seekDragging) seek.value = …; … })` block: KEEP the parts that update counters/icons, but REMOVE the `seek.value = …` line (no range input now). If that handler did `_updateCounters`/`_swapPlayIcon`, keep those.
  - Add a module-level `let _redrawSeekTimeline = () => {};` near the other `let _…` so Task 4 can call it after coverage loads.
  - The fill color: use a concrete accent. Replace the `ctx.fillStyle` coverage line with a simple resolved color to avoid the awkward expression above:
```javascript
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#6ee7b7";
```
- [ ] **Step 4: Run + restart + verify** — contract PASS; `node --input-type=module --check < src/static/inline_analysis_3d.js`; `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d`; live: open a video, the timeline shows a dark track + playhead, click/drag seeks.
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/inline_analysis_3d.css dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): main timeline canvas (dark track + playhead + click/drag seek)"
```

---

## Task 4: Coverage fetch + threshold-debounced recompute

**Files:** `dlc-3D/src/static/inline_analysis_3d.js`; test `tests/test_inline_analysis_3d_ui_isolation.py`.

Context: `_overlayPrimaryH5` holds the active cam0 h5; `_applyOverlayPrimary(h5)` runs on primary pick; the threshold slider `#ia3d-overlay-threshold` handler calls `_markerEditor.setThreshold(v)`; the overlay toggle `#ia3d-overlay-toggle` calls `_markerEditor.setOverlayEnabled`. `_redrawSeekTimeline` + `_coverageBuckets` exist from Task 3.

- [ ] **Step 1: Failing contract test** — append:
```python
def test_coverage_fetch_wired_and_threshold_recomputes():
    js = JS.read_text()
    assert "/dlc/viewer/pose-coverage" in js, "coverage endpoint not fetched"
    assert "_refreshCoverage" in js, "coverage refresh helper missing"
    # the threshold handler must trigger a coverage refresh (debounced)
    i = js.find('$("ia3d-overlay-threshold")')
    assert i > 0 and "_refreshCoverage" in js[i:i+400], "threshold change must refresh coverage"
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — in `inline_analysis_3d.js`:
  - Module state: `const _coverageCache = new Map(); let _coverageTimer = null;`
  - Add the helper:
```javascript
  // Fetch likelihood-filtered marker-coverage for the active primary h5 + current
  // threshold, cache by (h5, threshold), and redraw the main timeline. No-op unless
  // the overlay is on with a primary h5.
  async function _refreshCoverage() {
    const on = $("ia3d-overlay-toggle")?.checked;
    if (!on || !_overlayPrimaryH5) { _coverageBuckets = null; _redrawSeekTimeline(); return; }
    const thr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
    const key = `${_overlayPrimaryH5}:${thr.toFixed(2)}`;
    if (_coverageCache.has(key)) { _coverageBuckets = _coverageCache.get(key); _redrawSeekTimeline(); return; }
    const w = Math.max(200, Math.round($("ia3d-seek-canvas")?.getBoundingClientRect().width || 600));
    try {
      const data = await (await fetch(
        `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(_overlayPrimaryH5)}&threshold=${thr}&buckets=${w}`,
      )).json();
      const buckets = data.buckets || [];
      _coverageCache.set(key, buckets);
      // only apply if still the active selection (guards a superseded fetch)
      const curThr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
      if (`${_overlayPrimaryH5}:${curThr.toFixed(2)}` === key) { _coverageBuckets = buckets; _redrawSeekTimeline(); }
    } catch (_) { /* leave timeline without coverage */ }
  }
  function _refreshCoverageDebounced() {
    if (_coverageTimer) clearTimeout(_coverageTimer);
    _coverageTimer = setTimeout(_refreshCoverage, 200);
  }
```
  - Wire it: at the END of `_applyOverlayPrimary(h5)` add `_refreshCoverage();`. In the threshold handler (after `_markerEditor?.setThreshold(v)`) add `_refreshCoverageDebounced();`. In the overlay-toggle handler add `_refreshCoverage();` (covers both on→fetch and off→clear). In `_resetForOpen` add `_coverageBuckets = null; _coverageCache.clear();`.
  - Hoist the declarations: ensure `_coverageBuckets` and `_redrawSeekTimeline` are module-level `let`s (from Task 3) so both functions see them.
- [ ] **Step 4: Run + verify** — contract PASS; `node --input-type=module --check`; live: enable overlay + pick h5 → coverage marks appear on the main timeline; drag the likelihood slider → marks change (after ~200ms); cached thresholds redraw instantly.
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/static/inline_analysis_3d.js dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): marker-coverage on the main timeline (likelihood-filtered, threshold-reactive, cached)"
```

---

## Task 5: Body-part chips → exact `fl-bp-chip` structure (shared markerEditor)

**Files:** `dlc-3D/src/static/components/viewer/features/marker_editor.js`, `dlc-3D/src/static/inline_analysis_3d.css`, `dlc-3D/src/static/viewer_3d.css`, test `tests/test_marker_editor_feature.py`.

- [ ] **Step 1: Failing contract test** — append to `tests/test_marker_editor_feature.py`:
```python
def test_bp_chips_render_frame_labeler_structure():
    src = (ROOT / "src" / "static" / "components" / "viewer" / "features" / "marker_editor.js").read_text()
    for cls in ("vv-bp-dot", "vv-bp-name", "vv-bp-check", "vv-bp-eye-slash"):
        assert cls in src, f"rebuildBpChips must render a .{cls} element (frame-labeler chip parity)"
```
(Use the file's existing `ROOT`; if absent add `from pathlib import Path` + `ROOT = Path(__file__).parent.parent`.)
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3a: markerEditor** — in `features/marker_editor.js` `rebuildBpChips`, replace `chip.textContent = bp;` with:
```javascript
      chip.innerHTML =
        '<span class="vv-bp-dot"></span>' +
        '<span class="vv-bp-name"></span>' +
        '<svg class="vv-bp-check" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>' +
        '<svg class="vv-bp-eye-slash" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
      chip.querySelector(".vv-bp-name").textContent = bp;  // textContent — never inject bp into HTML
```
(Leave the `chip.className = "vv-bp-chip"`, `dataset.bp`, `--bp-color`, click/dblclick lines unchanged. `updateBpChips` already toggles `.active`/`.labeled`/`.vis-hidden`.)
- [ ] **Step 3b: CSS (both cards)** — in BOTH `inline_analysis_3d.css` and `viewer_3d.css`, replace the existing `.vv-bp-chip::before { … }` dot rule with the dot-span + check/eye rules (scope each to its card id — `#inline-analysis-3d-card` / `#view-analyzed-3d-card`):
```css
SCOPE .vv-bp-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--bp-color, var(--accent-dim)); }
SCOPE .vv-bp-name { line-height: 1; }
SCOPE .vv-bp-check { display: none; flex-shrink: 0; color: var(--bp-color, var(--accent)); }
SCOPE .vv-bp-chip.labeled .vv-bp-check { display: block; }
SCOPE .vv-bp-eye-slash { display: none; flex-shrink: 0; }
SCOPE .vv-bp-chip.vis-hidden .vv-bp-eye-slash { display: block; }
SCOPE .vv-bp-chip.vis-hidden { opacity: .5; }
```
Replace `SCOPE` with the card id. Remove the now-redundant `SCOPE .vv-bp-chip::before { … }` rule in each file (the `.vv-bp-dot` span replaces it). Keep the base `.vv-bp-chip` pill rule (and the `.vv-bp-chip.active` tint) as-is.
- [ ] **Step 4: Run + verify** — `python -m pytest tests/test_marker_editor_feature.py -q` PASS; `node --input-type=module --check < src/static/components/viewer/features/marker_editor.js`; `node --test tests/unit/*.mjs`; `python -m pytest tests/e2e/test_analyzed_viewer.py -q` (15 — markerEditor change must not regress View Analyzed). Live: chips show a checkmark on labeled parts + eye-slash when a chip is double-clicked off.
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/static/components/viewer/features/marker_editor.js dlc-3D/src/static/inline_analysis_3d.css dlc-3D/src/static/viewer_3d.css dlc-3D/tests/test_marker_editor_feature.py
git commit -m "feat(viewer): bp chips render frame-labeler structure (dot/name/check/eye-slash)"
```

---

## Task 6: Full live verification

**Files:** none. Drive the live app (Playwright) on the OM-2 fixture; restart flask + dlc-3d first (`docker compose restart flask`; `docker compose -f …/docker-compose.yml restart dlc-3d`).

- [ ] **Step 1: Coverage marks** — open inline card, select OM-2 cam0, enable overlay, pick the h5. Assert `#ia3d-seek-canvas` has non-transparent pixels beyond the playhead (coverage painted). Capture a screenshot.
- [ ] **Step 2: Threshold reactivity** — read the canvas covered-pixel count at threshold 0.1, then set `#ia3d-overlay-threshold` to 0.95 (dispatch input), wait ~400ms, re-read. Assert the covered-pixel count DECREASED (higher threshold → fewer covered frames).
- [ ] **Step 3: Seek** — click at 60% width on the canvas → `window.__iaViewer.currentFrame()` ≈ 0.6·frameCount; drag → frame follows.
- [ ] **Step 4: Chips** — pick a frame with detections; assert at least one `.vv-bp-chip.labeled .vv-bp-check` is visible; double-click a chip → it gets `.vis-hidden` + the eye-slash shows.
- [ ] **Step 5: No-regression** — `node --test tests/unit/*.mjs`; `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_marker_editor_feature.py tests/test_video_viewer_policy.py -q`; `python -m pytest tests/e2e/test_analyzed_viewer.py -q` (15).
- [ ] **Step 6: Report** results (screenshot + the threshold-reactivity numbers).

---

## Self-Review

**Spec coverage:** §1 main-timeline style → Task 3 (canvas, dark track). §2 coverage (likelihood-filtered, threshold-reactive, efficient, cached) → Task 2 (backend, `poses_np` vectorized) + Task 4 (fetch/debounce/cache) + Task 1 (reducer). §3 chips → Task 5. Testing/error-handling per task + Task 6 live. All covered.

**Placeholder scan:** none — every code step has full code.

**Type/name consistency:** reducer exports `coverageRects(buckets,width)` + `xToFrame(px,width,frameCount)` — used identically in Tasks 1, 3. Backend `_coverage_buckets(poses_np, threshold, n_buckets)` defined + tested + called in Task 2. Inline shares `_coverageBuckets` (state), `_redrawSeekTimeline` (Task 3 sets, Task 4 calls), `_refreshCoverage`/`_refreshCoverageDebounced` (Task 4). Chip classes `vv-bp-dot/name/check/eye-slash` consistent between Task 5 markerEditor render + CSS + contract test.

**Flagged for implementers:** (a) Task 2 backend is a SEPARATE git repo (`deeplabcut-webapp-docker`) — commit there + `restart flask`; match its test-import convention. (b) Task 3 must remove BOTH the seek `<input>` markup and its JS wiring (counters keep working; only the `seek.value` range-sync line goes). (c) Task 5 CSS must remove the old `.vv-bp-chip::before` dot in each card file to avoid a double dot.
