# Inline 3D — `_analyzed` Coverage Bar in the Finalize Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Show a separate "FINALIZED" coverage bar in the Finalize panel painting which frames exist in the canonical `_analyzed` file (presence-only, no threshold), refreshed after each Finalize-Add.

**Architecture:** Add a `mode=presence` param to the existing `/dlc/viewer/pose-coverage`; factor the main-timeline draw + seek wiring into reusable inline helpers; add a finalize canvas that reuses them (amber marks) + a fetch that resolves the `_analyzed` h5 via the existing `analysis-file/status`.

**Tech Stack:** Browser ESM; Flask + NumPy; pytest static-analysis + Playwright.

**Spec:** `docs/superpowers/specs/2026-05-23-inline-3d-finalize-coverage-bar-design.md`

**Repos:** dlc-3D under `deeplabcut-webapp-docker-supports/dlc-3D/` (git root `deeplabcut-webapp-docker-supports/`, commit `dlc-3D/...`); backend in the SEPARATE repo `deeplabcut-webapp-docker/`. Backend route served by flask → `docker compose restart flask`; inline template change → `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d`. JS/CSS hot-reload. No `/user-data` writes.

---

## File Structure
- `deeplabcut-webapp-docker/src/dlc/viewer.py` — `_coverage_buckets` gains a `mode` kwarg; route passes it. [Task 1]
- `deeplabcut-webapp-docker/tests/test_pose_coverage.py` — presence-mode test. [Task 1]
- `dlc-3D/src/static/inline_analysis_3d.js` — factor `_drawCoverageBar` + `_wireSeekCanvas` (Task 2); finalize bar state + `_refreshFinalizeCoverage` + wiring (Task 3).
- `dlc-3D/src/templates/partials/card_inline_analysis_3d.html` — finalize canvas. [Task 3]
- `dlc-3D/src/static/inline_analysis_3d.css` — finalize canvas style. [Task 3]
- `dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py` — contract. [Tasks 2,3]

---

## Task 1: Backend `mode=presence` on `/dlc/viewer/pose-coverage`

**Files:** `deeplabcut-webapp-docker/src/dlc/viewer.py`; `deeplabcut-webapp-docker/tests/test_pose_coverage.py`.

Context: existing `def _coverage_buckets(poses_np, threshold, n_buckets)` computes `(poses_np[:,:,2] >= threshold).any(axis=1)` then downsamples; existing route `viewer_pose_coverage()` reads `h5`/`threshold`/`buckets`. numpy alias is `_np`. The existing test `test_coverage_buckets_thresholds_and_downsamples` calls `_coverage_buckets(poses, threshold=0.6, n_buckets=3)` — its signature must stay valid.

- [ ] **Step 1: Failing test** — append to `tests/test_pose_coverage.py`:
```python
def test_coverage_buckets_presence_mode_ignores_threshold():
    poses = np.zeros((4, 2, 3), dtype=np.float32)
    # x finite for a bodypart → covered, regardless of likelihood (which is 0 here)
    poses[:, 0, 0] = [1.0, np.nan, 5.0, np.nan]  # bp0 x
    poses[:, 1, 0] = [np.nan, np.nan, np.nan, 2.0]  # bp1 x
    poses[:, :, 2] = 0.0  # all likelihoods 0 — would be uncovered in likelihood mode
    # presence: frame covered iff >=1 finite x → [T, F, T, T]; 4 frames→4 buckets
    assert v._coverage_buckets(poses, threshold=0.6, n_buckets=4, mode="presence") == [1, 0, 1, 1]
    # likelihood mode (default) with these zero likelihoods → none covered
    assert v._coverage_buckets(poses, threshold=0.6, n_buckets=4) == [0, 0, 0, 0]
```
- [ ] **Step 2: Run, verify fail** — `cd deeplabcut-webapp-docker && python -m pytest tests/test_pose_coverage.py -q` → FAIL (`mode` unexpected kwarg).
- [ ] **Step 3: Implement** — edit `_coverage_buckets` in `src/dlc/viewer.py` to add the `mode` kwarg (keep all positional params):
```python
def _coverage_buckets(poses_np, threshold, n_buckets, mode="likelihood"):
    """Per-frame coverage downsampled to n_buckets (capped at n_frames). Returns 0/1 list.
    mode='likelihood' (default): >=1 bodypart with likelihood >= threshold (NaN→False).
    mode='presence': >=1 bodypart with a finite x (threshold ignored) — for finalized
    _analyzed files where 'has a label' is x-presence, not a confidence."""
    n = int(poses_np.shape[0]) if poses_np is not None else 0
    if n == 0:
        return []
    if mode == "presence":
        covered = (~_np.isnan(poses_np[:, :, 0])).any(axis=1)
    else:
        covered = (poses_np[:, :, 2] >= float(threshold)).any(axis=1)
    b = max(1, min(int(n_buckets), n))
    idx = (_np.arange(n) * b) // n
    out = _np.zeros(b, dtype=bool)
    _np.logical_or.at(out, idx, covered)
    return out.astype(int).tolist()
```
  And in `viewer_pose_coverage()`, read + pass mode:
```python
    mode = request.args.get("mode", "likelihood")
    buckets  = _coverage_buckets(poses_np, threshold, n_buckets, mode=mode)
```
  (Keep the rest of the route identical.)
- [ ] **Step 4: Run, verify pass** — `python -m pytest tests/test_pose_coverage.py -q` → all pass (the new test + the 2 existing).
- [ ] **Step 5: Commit (main webapp repo)**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/viewer.py tests/test_pose_coverage.py
git commit -m "feat(viewer): pose-coverage mode=presence (finite-x, threshold-ignored)"
```
Then `docker compose restart flask`.

---

## Task 2: Factor reusable coverage-bar draw + seek helpers (inline)

**Files:** `dlc-3D/src/static/inline_analysis_3d.js`; test `tests/test_inline_analysis_3d_ui_isolation.py`. Behavior-preserving refactor of the main timeline (must keep working).

Context: `_wireViewerChrome(v)` currently defines a closure `_drawSeekTimeline()` (uses `seekCanvas`, `v`, `_coverageBuckets`) + inline mousedown/`_seekToX`/document mousemove+mouseup seek wiring, and sets `_redrawSeekTimeline = _drawSeekTimeline`. Module-level `_viewer` holds the viewer; `let _coverageBuckets`/`let _redrawSeekTimeline` exist. Reducer imports `coverageRects`, `xToFrame` exist.

- [ ] **Step 1: Failing contract test** — append:
```python
def test_coverage_bar_draw_and_seek_helpers_factored():
    js = JS.read_text()
    assert "function _drawCoverageBar(" in js, "shared coverage-bar draw helper missing"
    assert "function _wireSeekCanvas(" in js, "shared seek-canvas wiring helper missing"
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — in `inline_analysis_3d.js`:
  1. Add these MODULE-LEVEL functions (near the other module-level helpers, e.g. just above `_wireViewerChrome`):
```javascript
// Draw a coverage bar onto `canvas`: dark track is the CSS bg; paint covered
// buckets in markColor, then the playhead at the viewer's current frame.
function _drawCoverageBar(canvas, buckets, markColor) {
  if (!canvas || !_viewer) return;
  const w = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
  canvas.width = w;
  const h = canvas.height || 14;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  if (buckets && buckets.length) {
    ctx.fillStyle = markColor;
    for (const r of coverageRects(buckets, w)) ctx.fillRect(r.x, 0, r.w, h);
  }
  const fc = _viewer.frameCount();
  if (fc > 0) {
    const x = Math.round((_viewer.currentFrame() / Math.max(fc - 1, 1)) * w);
    ctx.save(); ctx.globalAlpha = 0.85; ctx.fillStyle = "#fff"; ctx.fillRect(x, 0, 2, h); ctx.restore();
  }
}
// Wire click + drag-to-seek on a coverage/seek canvas.
function _wireSeekCanvas(canvas) {
  if (!canvas) return;
  let dragging = false;
  const toX = (e) => {
    const r = canvas.getBoundingClientRect();
    _viewer?.seek(xToFrame(e.clientX - r.left, r.width, _viewer.frameCount()));
  };
  canvas.addEventListener("mousedown", (e) => { dragging = true; _viewer?.pause(); toX(e); });
  document.addEventListener("mousemove", (e) => { if (dragging) toX(e); });
  document.addEventListener("mouseup", () => { dragging = false; });
}
const _accentColor = () => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#6ee7b7";
```
  2. In `_wireViewerChrome(v)`, DELETE the old `function _drawSeekTimeline() {…}` closure, the `let _seekDragging`/`const _seekToX`/`seekCanvas.addEventListener("mousedown"…)`/`document.addEventListener("mousemove"…)`/`document.addEventListener("mouseup"…)` lines, and the `_redrawSeekTimeline = _drawSeekTimeline;` line. REPLACE that whole block with:
```javascript
  const seekCanvas = $("ia3d-seek-canvas");
  _wireSeekCanvas(seekCanvas);
  _redrawSeekTimeline = () => _drawCoverageBar(seekCanvas, _coverageBuckets, _accentColor());
  v.on("videoLoad", () => _redrawSeekTimeline());
  v.on("frameChange", () => _redrawSeekTimeline());
```
  (Keep any OTHER `v.on("frameChange", …)` handlers that update counters/icons — only the seek-draw wiring is replaced. If the previous code already had `v.on("videoLoad"/"frameChange", () => _drawSeekTimeline())`, replace those two with the `_redrawSeekTimeline()` versions above; don't duplicate.)
- [ ] **Step 4: Run + verify** — contract PASS; `node --input-type=module --check < src/static/inline_analysis_3d.js`; grep confirms no leftover `_drawSeekTimeline` references. Then (behavior check) `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d` is NOT needed (JS only) — the parent will live-verify the main timeline still seeks + paints in Task 4.
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/static/inline_analysis_3d.js dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "refactor(dlc-3d): factor _drawCoverageBar + _wireSeekCanvas (shared by both timelines)"
```

---

## Task 3: Finalize coverage bar (`_analyzed`, presence)

**Files:** `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`, `dlc-3D/src/static/inline_analysis_3d.js`, `dlc-3D/src/static/inline_analysis_3d.css`, test `tests/test_inline_analysis_3d_ui_isolation.py`.

Context: `_cam0Path()` returns the cam0 video path. The finalize toggle handler (in `_wireViewerChrome`/`_wireOverlayChrome`) toggles `#ia3d-finalize-controls`. `_onFinalizeAddClick` writes the range then sets `#ia3d-finalize-status`. `_resetForOpen` resets per-card state. `analysis-file/status?video_path=` returns `{initialized, h5_path}`.

- [ ] **Step 1: Failing contract test** — append:
```python
def test_finalize_coverage_bar_present_and_wired():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    # canvas lives inside the finalize controls
    fc = html.index('id="ia3d-finalize-controls"')
    cov = html.index('id="ia3d-finalize-coverage"')
    assert cov > fc, "finalize coverage canvas must be inside the finalize controls"
    js = JS.read_text()
    assert "_refreshFinalizeCoverage" in js, "finalize coverage refresh helper missing"
    assert "mode=presence" in js, "must request presence-mode coverage"
    assert "/dlc/project/analysis-file/status" in js, "must resolve the _analyzed h5 via analysis-file/status"
    # refreshed from the finalize toggle AND after finalize-add
    ti = js.find("ia3dFinalizeToggle?.addEventListener")
    assert ti > 0 and "_refreshFinalizeCoverage" in js[ti:ti+400], "toggle must refresh finalize coverage"
    fi = js.find("async function _onFinalizeAddClick")
    assert fi > 0 and "_refreshFinalizeCoverage" in js[fi:fi+2600], "finalize-add must refresh coverage"
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3a: Markup** — in `card_inline_analysis_3d.html`, inside `#ia3d-finalize-controls`, immediately AFTER the start/frames/add-button row's closing `</div>` and BEFORE `<div id="ia3d-finalize-status" …>`, insert:
```html
            <div style="font-size:.7rem;color:var(--text-dim);font-family:var(--mono);margin:.1rem 0 .15rem">Finalized frames (_analyzed)</div>
            <canvas id="ia3d-finalize-coverage" height="14" title="Finalized frames — click or drag to seek"
              style="width:100%;display:block;margin-bottom:.4rem;cursor:pointer"></canvas>
```
- [ ] **Step 3b: CSS** — append to `inline_analysis_3d.css`:
```css
#inline-analysis-3d-card #ia3d-finalize-coverage {
  background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
}
```
- [ ] **Step 3c: JS** — in `inline_analysis_3d.js`:
  1. Module-level state (near `_coverageBuckets`): `let _finalizeCoverageBuckets = null; let _redrawFinalizeCoverage = () => {};`
  2. Add the refresh helper (module scope, near `_refreshCoverage`):
```javascript
  // Coverage of the canonical _analyzed file (presence, no threshold) for the
  // finalize bar. Resolves the _analyzed h5 via analysis-file/status. Always
  // refetches on its triggers (toggle-on, after each finalize-add) — the file
  // changes, and the backend's mtime-keyed cache returns fresh data.
  async function _refreshFinalizeCoverage() {
    const on = $("ia3d-finalize-toggle")?.checked;
    const cam0Video = _cam0Path();
    if (!on || !cam0Video) { _finalizeCoverageBuckets = null; _redrawFinalizeCoverage(); return; }
    try {
      const st = await (await fetch(`/dlc/project/analysis-file/status?video_path=${encodeURIComponent(cam0Video)}`)).json();
      if (!st.initialized || !st.h5_path) { _finalizeCoverageBuckets = null; _redrawFinalizeCoverage(); return; }
      const w = Math.max(200, Math.round($("ia3d-finalize-coverage")?.getBoundingClientRect().width || 600));
      const data = await (await fetch(
        `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(st.h5_path)}&mode=presence&buckets=${w}`,
      )).json();
      _finalizeCoverageBuckets = data.buckets || [];
      _redrawFinalizeCoverage();
    } catch (_) { _finalizeCoverageBuckets = null; _redrawFinalizeCoverage(); }
  }
```
  3. In `_wireViewerChrome(v)` (right after the main-timeline `_wireSeekCanvas(seekCanvas)` block from Task 2), wire the finalize canvas:
```javascript
  const finalizeCanvas = $("ia3d-finalize-coverage");
  _wireSeekCanvas(finalizeCanvas);
  _redrawFinalizeCoverage = () => _drawCoverageBar(finalizeCanvas, _finalizeCoverageBuckets, "#fbbf24");
  v.on("frameChange", () => _redrawFinalizeCoverage());
```
  4. In the finalize-toggle change handler (`ia3dFinalizeToggle?.addEventListener("change", () => {…})`), add at the end of the callback: `_refreshFinalizeCoverage();`
  5. In `_onFinalizeAddClick`, after the status text is set in the success path inside the `try` (right after the `ia3dFinalizeStatus.textContent = ...` block that reports `cam0 ✓`), add: `_refreshFinalizeCoverage();`
  6. In `_resetForOpen`, add: `_finalizeCoverageBuckets = null;`
- [ ] **Step 4: Run + restart + verify** — contract PASS; `node --input-type=module --check`; `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d` (markup change).
- [ ] **Step 5: Commit**
```bash
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/inline_analysis_3d.css dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): _analyzed coverage bar in the Finalize panel (presence, refresh-after-add)"
```

---

## Task 4: Full live verification

**Files:** none. Restart flask + dlc-3d. Drive the live app (OM-2 fixture).

- [ ] **Step 1: Main timeline still works** (Task 2 refactor regression) — open inline card, select OM-2 cam0, overlay on + pick h5: the main timeline still paints coverage + playhead; click/drag still seeks.
- [ ] **Step 2: Finalize bar appears** — turn the Finalize toggle on. Assert `#ia3d-finalize-coverage` is visible. Fetch its rendered state: if OM-2 already has an `_analyzed` file, the bar paints amber coverage; if not initialized, the bar is just the track (no error). Capture a screenshot.
- [ ] **Step 3: presence endpoint** — directly hit `/dlc/viewer/pose-coverage?h5=<an _analyzed h5 if one exists, else the working h5>&mode=presence&buckets=400` and confirm it returns buckets (covered count independent of threshold). (This validates the wire path without needing a finalize write.)
- [ ] **Step 4: Seek on finalize bar** — click at 50% of `#ia3d-finalize-coverage` → `window.__iaViewer.currentFrame()` ≈ 0.5·frameCount.
- [ ] **Step 5: Refresh-after-add** — ONLY if a scratch (non-`/user-data`) project/video is available, run a Finalize-Add over a small range and assert the bar gains coverage in that range. Otherwise SKIP with a note (do not write `_analyzed` into the protected fixtures); the refresh wiring is covered by the contract test + the presence-endpoint check.
- [ ] **Step 6: No-regression** — `node --test tests/unit/*.mjs`; `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`; `python -m pytest tests/e2e/test_analyzed_viewer.py -q` (15).
- [ ] **Step 7: Report** with screenshot + the seek/endpoint numbers.

---

## Self-Review

**Spec coverage:** §1 backend presence → Task 1. §2 finalize bar (markup/CSS/amber/seek) → Task 3 (+ Task 2 helpers). §3 shared draw helper → Task 2. §4 data flow (status→h5_path→presence; refresh on toggle + after add; reset) → Task 3. Testing → per-task + Task 4. Covered.

**Placeholder scan:** none — full code in every step.

**Type/name consistency:** `_drawCoverageBar(canvas,buckets,markColor)` + `_wireSeekCanvas(canvas)` defined in Task 2, used by both timelines in Tasks 2 & 3. `_refreshFinalizeCoverage`/`_finalizeCoverageBuckets`/`_redrawFinalizeCoverage` consistent across Task 3. Backend `_coverage_buckets(…, mode=)` kwarg matches the route call + both tests.

**Deviation from spec (noted):** the spec mentioned a frontend cache keyed by `_analyzed` path; the plan drops it (always refetch on the two infrequent triggers) — simpler and avoids stale-after-finalize, since the file changes on every add. Backend mtime-keyed cache still prevents redundant h5 reloads.

**Flagged for implementers:** (a) Task 1 is the SEPARATE `deeplabcut-webapp-docker` repo — commit there + `restart flask`. (b) Task 2 is a behavior-preserving refactor — the main timeline must still seek + paint (Task 4 Step 1 verifies). (c) Task 3 Step 3c.5 — place the `_refreshFinalizeCoverage()` call on the SUCCESS path of `_onFinalizeAddClick` (after the range is written), not before.
