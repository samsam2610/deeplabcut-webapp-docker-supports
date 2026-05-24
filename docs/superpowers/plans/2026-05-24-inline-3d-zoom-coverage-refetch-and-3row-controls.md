# Inline 3D — Zoom Coverage Re-fetch + 3-Row Controls + 100 Preset — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make inline-3D coverage marks stay frame-precise when the viewer is zoomed (re-fetch at the zoomed width), reorganize the player controls into three tidy rows, and add a 100-frame skip preset.

**Architecture:** Frontend-only, dlc-3D module. Item 1 is JS (`inline_analysis_3d.js`): width-key the coverage cache and re-fetch both coverage bars on zoom (debounced). Items 2-3 are markup/CSS (`card_inline_analysis_3d.html`, `inline_analysis_3d.css`). Tests are static-analysis pytest contracts.

**Tech Stack:** Vanilla ES modules, Jinja2 partial, CSS. Tests run with `python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-24-inline-3d-zoom-coverage-refetch-and-3row-controls-design.md`

**Working dir for all commands:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

**Run only the specific test file(s) named in each task — never the whole pytest suite (some suites are heavy).**

---

### Task 1: Re-fetch coverage at the zoomed width (Item 1)

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (cache key + zoom-triggered refresh)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

**Context:** The coverage cache `_coverageCache` is keyed `${_overlayPrimaryH5}:${thr.toFixed(2)}` — no width. When zoomed, the canvas is wider but the cached coverage (fetched at the base width) has too few buckets, so `coverageFrameRects` draws each mark `ceil(width/nBuckets)` px wide and marks bleed onto unlabeled frames. Fix: include the fetch width `w` in the cache key, and trigger a re-fetch of both bars when the zoom handler resizes the canvases.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_coverage_cache_keyed_by_width_and_refetched_on_zoom():
    js = JS.read_text()
    # cache key includes the fetch width (so each zoom level caches its own
    # resolution) — the key template ends with ":${w}"
    assert ":${w}" in js, "coverage cache key must include the width component :${w}"
    # the zoom handler triggers a coverage re-fetch at the new width
    assert js.count("_refreshCoverageForZoom") >= 2, \
        "_refreshCoverageForZoom must be defined and called from the zoom handler"
    # the zoom re-fetch refreshes BOTH the working-layer and finalize bars
    m = re.search(r"function _refreshCoverageForZoom\(\)\s*\{(.*?)\n\}", js, re.S)
    assert m and "_refreshCoverage(" in m.group(1) and "_refreshFinalizeCoverage(" in m.group(1), \
        "_refreshCoverageForZoom must refresh both coverage bars"
```

- [ ] **Step 2: Run the test to verify it FAILS**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_coverage_cache_keyed_by_width_and_refetched_on_zoom -q`
Expected: FAIL.

- [ ] **Step 3: Width-key the coverage cache**

In `src/static/inline_analysis_3d.js`, replace the current `_refreshCoverage` function:

```javascript
async function _refreshCoverage() {
  const on = $("ia3d-overlay-toggle")?.checked;
  if (!on || !_overlayPrimaryH5) { _coverageBuckets = null; _coverageFrames = null; _redrawSeekTimeline(); return; }
  const thr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
  const key = `${_overlayPrimaryH5}:${thr.toFixed(2)}`;
  if (_coverageCache.has(key)) {
    const c = _coverageCache.get(key);
    _coverageBuckets = c.buckets; _coverageFrames = c.frames; _redrawSeekTimeline(); return;
  }
  const w = Math.max(200, Math.round($("ia3d-seek-canvas")?.getBoundingClientRect().width || 600));
  try {
    const data = await (await fetch(
      `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(_overlayPrimaryH5)}&threshold=${thr}&buckets=${w}`,
    )).json();
    const entry = { buckets: data.buckets || [], frames: data.frames || [] };
    _coverageCache.set(key, entry);
    const curThr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
    if (`${_overlayPrimaryH5}:${curThr.toFixed(2)}` === key) {
      _coverageBuckets = entry.buckets; _coverageFrames = entry.frames; _redrawSeekTimeline();
    }
  } catch (_) { /* leave timeline without coverage */ }
}
```

with this version (compute `w` before the key; include `w` in the key and in the "still current" guard):

```javascript
async function _refreshCoverage() {
  const on = $("ia3d-overlay-toggle")?.checked;
  if (!on || !_overlayPrimaryH5) { _coverageBuckets = null; _coverageFrames = null; _redrawSeekTimeline(); return; }
  const thr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
  const w = Math.max(200, Math.round($("ia3d-seek-canvas")?.getBoundingClientRect().width || 600));
  const key = `${_overlayPrimaryH5}:${thr.toFixed(2)}:${w}`;
  if (_coverageCache.has(key)) {
    const c = _coverageCache.get(key);
    _coverageBuckets = c.buckets; _coverageFrames = c.frames; _redrawSeekTimeline(); return;
  }
  try {
    const data = await (await fetch(
      `/dlc/viewer/pose-coverage?h5=${encodeURIComponent(_overlayPrimaryH5)}&threshold=${thr}&buckets=${w}`,
    )).json();
    const entry = { buckets: data.buckets || [], frames: data.frames || [] };
    _coverageCache.set(key, entry);
    // still the active request? (h5 + threshold + width all unchanged)
    const curThr = parseFloat($("ia3d-overlay-threshold")?.value ?? "0.6");
    const curW = Math.max(200, Math.round($("ia3d-seek-canvas")?.getBoundingClientRect().width || 600));
    if (`${_overlayPrimaryH5}:${curThr.toFixed(2)}:${curW}` === key) {
      _coverageBuckets = entry.buckets; _coverageFrames = entry.frames; _redrawSeekTimeline();
    }
  } catch (_) { /* leave timeline without coverage */ }
}
```

Also update the cache-key comment on the `_coverageCache` declaration (currently `// keyed by "<h5>:<threshold.toFixed(2)>"`) to `// keyed by "<h5>:<threshold.toFixed(2)>:<width>"`.

- [ ] **Step 4: Add the zoom-triggered re-fetch helper**

In `src/static/inline_analysis_3d.js`, add right after the existing `_refreshCoverageDebounced` function:

```javascript
let _zoomCovTimer = null;
// On zoom the canvases resize; re-fetch BOTH coverage bars at the new (wider)
// width so the bucket resolution tracks the displayed width → marks stay 1px and
// stop bleeding onto unlabeled frames. Debounced to coalesce slider drags.
function _refreshCoverageForZoom() {
  if (_zoomCovTimer) clearTimeout(_zoomCovTimer);
  _zoomCovTimer = setTimeout(() => { _refreshCoverage(); _refreshFinalizeCoverage(); }, 200);
}
```

(Confirm `_refreshFinalizeCoverage` is the existing presence-bar refresh function name; it reads the finalize canvas width and fetches `buckets=${w}` already.)

- [ ] **Step 5: Call it from the zoom handler**

Find the zoom handler:

```javascript
  zoom?.addEventListener("input", () => {
    const g = v.setZoom(parseInt(zoom.value, 10) || 100);
    _applyTimelineWidth(g);
    const val = $("ia3d-zoom-val");
    if (val) val.textContent = zoom.value + " %";
  });
```

Add the re-fetch call after `_applyTimelineWidth(g)`:

```javascript
  zoom?.addEventListener("input", () => {
    const g = v.setZoom(parseInt(zoom.value, 10) || 100);
    _applyTimelineWidth(g);
    _refreshCoverageForZoom();   // re-fetch coverage at the new width (1px-precise marks)
    const val = $("ia3d-zoom-val");
    if (val) val.textContent = zoom.value + " %";
  });
```

- [ ] **Step 6: Run the test to verify it PASSES**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "fix(dlc-3d): re-fetch coverage at the zoomed width so marks stay precise

Coverage was fetched once at the base width; when zoomed, marks widened to
ceil(width/nBuckets) px and bled onto unlabeled frames. Width-key the coverage
cache and re-fetch both bars (debounced) when the zoom handler resizes the
canvases, so bucket resolution tracks the displayed width (frame-exact once the
bar is wider than the video).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Three-row controls layout (Item 2)

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (controls row 193-248)
- Modify: `src/static/inline_analysis_3d.css` (append rules)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

**Context:** The player controls are one wrapping `.fe-controls` row. Split into three explicit `.ia3d-ctrl-row` containers: playback / frame-jump / counter+time+help. No JS change (all controls keep their ids/classes).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_controls_split_into_three_rows():
    html = CARD.read_text()
    assert html.count('class="ia3d-ctrl-row"') == 3, "controls must be three .ia3d-ctrl-row rows"
    # the last row carries the frame counter + time display (+ help)
    rows = re.findall(r'<div class="ia3d-ctrl-row"[^>]*>(.*?)</div>\s*(?=<div class="ia3d-ctrl-row"|</div>)', html, re.S)
    assert len(rows) == 3
    last = rows[2]
    assert 'id="ia3d-frame-counter"' in last and 'id="ia3d-time-display"' in last and 'id="ia3d-help-btn"' in last
    # playback row has play + step; jump row has the skip group
    assert 'id="ia3d-btn-play"' in rows[0]
    assert 'class="ia3d-skip-group"' in rows[1]


def test_controls_three_row_css():
    css = CSS.read_text()
    assert re.search(r"#inline-analysis-3d-card\s+\.fe-controls\s*\{[^}]*flex-direction:\s*column", css), \
        "missing column layout for .fe-controls in the inline card"
    assert re.search(r"\.ia3d-ctrl-row\s*\{[^}]*display:\s*flex", css), "missing .ia3d-ctrl-row flex rule"
```

(`CSS` constant was added to this test file in an earlier plan; confirm it exists — `CSS = ROOT / "src" / "static" / "inline_analysis_3d.css"`. If absent, add it next to `PAGE`.)

- [ ] **Step 2: Run the test to verify it FAILS**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_controls_split_into_three_rows tests/test_inline_analysis_3d_ui_isolation.py::test_controls_three_row_css -q`
Expected: FAIL.

- [ ] **Step 3: Restructure the controls into three rows**

In `src/templates/partials/card_inline_analysis_3d.html`, replace the entire `.fe-controls` block (the `<div class="fe-controls" ...>` opening tag through its matching `</div>` — currently lines 193-248) with the three-row version. Keep EVERY inner element (ids, SVGs, inline styles) byte-for-byte; only the wrapping `<div class="ia3d-ctrl-row">` containers and the outer `.fe-controls` style attribute change:

```html
        <!-- Controls — three rows: playback / frame-jump / status (counter+time+help) -->
        <div class="fe-controls" style="flex:none">
          <div class="ia3d-ctrl-row">
            <button id="ia3d-btn-play-back" class="btn-sm fe-ctrl-btn" title="Play backward">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="19 3 5 12 19 21 19 3"/></svg>
            </button>
            <button id="ia3d-btn-play" class="btn-sm fe-ctrl-btn" title="Play / Pause (Space)">
              <svg id="ia3d-play-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              <svg id="ia3d-pause-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none" class="hidden"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
            </button>
            <button id="ia3d-btn-prev" class="btn-sm fe-ctrl-btn" title="Previous frame (←)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="15 18 9 12 15 6"/><line x1="9" y1="6" x2="9" y2="18"/></svg>
            </button>
            <button id="ia3d-btn-next" class="btn-sm fe-ctrl-btn" title="Next frame (→)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/><line x1="15" y1="6" x2="15" y2="18"/></svg>
            </button>
            <label style="display:flex;align-items:center;gap:.3rem;font-size:.75rem;color:var(--text-dim);white-space:nowrap"
                   title="Playback rate (frames per wall-clock second)">
              fps
              <input type="number" id="ia3d-play-fps" value="5" min="1" max="120" step="1"
                     style="width:46px;text-align:center;font-family:var(--mono);font-size:.78rem;padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text)">
            </label>
            <label style="display:flex;align-items:center;gap:.3rem;font-size:.75rem;color:var(--text-dim);white-space:nowrap"
                   title="Play every N frames (1 = every frame, 2 = every other, …)">
              step
              <input type="number" id="ia3d-play-step" value="1" min="1" max="100" step="1"
                     style="width:46px;text-align:center;font-family:var(--mono);font-size:.78rem;padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text)">
            </label>
          </div>
          <div class="ia3d-ctrl-row">
            <!-- Multi-frame skip — kept together as one non-wrapping group so the
                 back/forward pair never splits across a controls-row wrap -->
            <span class="ia3d-skip-group">
              <button id="ia3d-btn-skip-back" class="btn-sm fe-ctrl-btn" title="Skip backward N frames (Ctrl+←)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polyline points="19 18 13 12 19 6"/><polyline points="13 18 7 12 13 6"/></svg>
              </button>
              <button id="ia3d-btn-skip-fwd" class="btn-sm fe-ctrl-btn" title="Skip forward N frames (Ctrl+→)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><polyline points="5 18 11 12 5 6"/><polyline points="11 18 17 12 11 6"/></svg>
              </button>
              <input type="number" id="ia3d-skip-n" value="10" min="1" max="9999" step="1"
                title="Frames to skip (Ctrl+← / Ctrl+→)"
                style="width:72px;text-align:center;font-family:var(--mono);font-size:.78rem;padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text)" />
              <span class="ia3d-skip-presets" style="display:inline-flex;gap:.2rem">
                <button type="button" class="ia3d-skip-preset" data-n="1">1</button>
                <button type="button" class="ia3d-skip-preset" data-n="5">5</button>
                <button type="button" class="ia3d-skip-preset" data-n="10">10</button>
                <button type="button" class="ia3d-skip-preset" data-n="30">30</button>
              </span>
            </span>
          </div>
          <div class="ia3d-ctrl-row">
            <span class="fe-frame-counter" id="ia3d-frame-counter" title="Click to jump to a frame" style="cursor:pointer">Frame 0 / 0</span>
            <input type="number" id="ia3d-frame-jump" class="hidden" min="0" title="Type a frame number, Enter to jump"
              style="width:5.5rem;text-align:center;font-family:var(--mono);font-size:.78rem;padding:.18rem .3rem;background:var(--surface-2);border:1px solid var(--accent);border-radius:5px;color:var(--text)" />
            <span class="fe-time-display" id="ia3d-time-display">0.000 s</span>
            <button type="button" id="ia3d-help-btn" class="btn-sm fe-ctrl-btn" title="Keyboard shortcuts" style="margin-left:auto">?</button>
            <div id="ia3d-help-tooltip" class="hidden" style="position:absolute;z-index:20;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.5rem .7rem;font-size:.72rem;font-family:var(--mono);color:var(--text-dim);box-shadow:0 4px 16px rgba(0,0,0,.4)">
              <div><b>Space</b> play/pause · <b>Shift+Space</b> play backward</div>
              <div><b>← / →</b> step ±1 · <b>Shift+← / →</b> step ±skip</div>
              <div><b>Click frame #</b> jump to frame</div>
            </div>
          </div>
        </div>
```

NOTE: This keeps the `data-n` presets at 1/5/10/30 — Task 3 adds the 100 preset. Do NOT add it here.

- [ ] **Step 4: Add the CSS**

In `src/static/inline_analysis_3d.css`, append:

```css
/* Player controls laid out as three stacked rows (playback / frame-jump /
   counter+time+help) instead of one wrapping row. Scoped to the inline card so
   other .fe-controls consumers are unaffected. */
#inline-analysis-3d-card .fe-controls { flex-direction: column; align-items: stretch; gap: .35rem; }
#inline-analysis-3d-card .ia3d-ctrl-row { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; }
```

- [ ] **Step 5: Run the tests to verify they PASS**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS (including Task 1's test and the existing skip-group tests).

- [ ] **Step 6: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html src/static/inline_analysis_3d.css tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): split player controls into three rows

Row 1 playback, row 2 frame-jump (skip group), row 3 frame counter + time with
the help button pushed right. .fe-controls becomes a column of .ia3d-ctrl-row
flex rows (scoped to the inline card). No JS change — ids/classes unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Add the 100-frame skip preset (Item 3)

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (`.ia3d-skip-presets`, now on row 2)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_skip_preset_100_exists():
    html = CARD.read_text()
    assert re.search(r'class="ia3d-skip-preset"\s+data-n="100"\s*>\s*100\s*<', html), \
        "missing the 100-frame skip preset button"
    # it lives inside the skip-presets cluster
    presets = re.search(r'class="ia3d-skip-presets"[^>]*>(.*?)</span>', html, re.S).group(1)
    assert 'data-n="100"' in presets
```

- [ ] **Step 2: Run the test to verify it FAILS**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_skip_preset_100_exists -q`
Expected: FAIL.

- [ ] **Step 3: Add the 100 preset button**

In `src/templates/partials/card_inline_analysis_3d.html`, inside `.ia3d-skip-presets`, add a `100` button immediately after the `data-n="30"` button:

```html
              <button type="button" class="ia3d-skip-preset" data-n="10">10</button>
              <button type="button" class="ia3d-skip-preset" data-n="30">30</button>
              <button type="button" class="ia3d-skip-preset" data-n="100">100</button>
```

(No JS change — the existing preset click handler and `_syncSkipPresets` both use `.ia3d-skip-preset` + `data-n`; `#ia3d-skip-n` max is 9999.)

- [ ] **Step 4: Run the test to verify it PASSES**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full affected suites**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_base.py tests/test_status_notes_feature.py tests/test_video_viewer_policy.py -q && node --test tests/unit/*.mjs`
Expected: pytest all PASS; node `# fail 0`.

- [ ] **Step 6: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): add a 100-frame skip preset

Adds a 100 quick-jump preset alongside 1/5/10/30 on the frame-jump row.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Live verification (controller, after all tasks; static tests can't observe layout/runtime)
The dlc-3D static/templates are bind-mounted; **restart the dlc-3d container** (template change) then hard-refresh. With the inline card open on a video + overlay:
1. Item 1: zoom to 300% → coverage marks are ~1px and only on labeled frames; navigate to a known-unlabeled frame → no mark under the playhead. (Compare: a known-labeled frame shows a mark.)
2. Item 2: controls render as three rows — playback / jump / counter+time with `?` at the far right of row 3.
3. Item 3: click the `100` preset → `#ia3d-skip-n` becomes 100 and `«`/`»` jump 100 frames.

## Out of scope (YAGNI)
- Re-fetch on plain window resize (only the zoom slider).
- View Analyzed / frame-labeler.
- Changing the bucketing/markW algorithm.
