# Inline 3D — Pair Skip Buttons + Timelines Match Zoomed Video Width — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the existing forward-skip button from being orphaned by the controls-row wrap, and make the four inline-3D timeline canvases track the zoomed video row's width + offset for finer click precision.

**Architecture:** Frontend-only, dlc-3D module. (1) Wrap the skip controls in one non-wrapping `.ia3d-skip-group` (HTML+CSS, no JS). (2) `VideoViewer.setZoom` returns the `{width, marginLeft}` it applies; `statusNoteTimeline` exposes a public `redraw()`; the inline card's `_applyTimelineWidth` mirrors that geometry onto its four timeline canvases (`#ia3d-seek-canvas`, `#ia3d-status-canvas`, `#ia3d-note-canvas`, `#ia3d-finalize-coverage`) and redraws them.

**Tech Stack:** Vanilla ES modules (browser), Jinja2 partial, CSS. Tests are static-analysis pytest contracts (regex over source — these modules are browser ESM and don't import under Node). Run with `python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-23-inline-3d-skip-pair-and-timeline-zoom-width-design.md`

**Working dir for all commands:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

---

### Task 1: Pair the skip buttons in a non-wrapping group (HTML + CSS)

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html:219-234`
- Modify: `src/static/inline_analysis_3d.css` (append a rule)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_inline_analysis_3d_ui_isolation.py`, add a module-level CSS path constant next to the existing `JS` / `CARD` / `PAGE` constants (after the line `PAGE = ROOT / "src" / "templates" / "dlc_3d.html"`):

```python
CSS  = ROOT / "src" / "static" / "inline_analysis_3d.css"
```

Then append these two test functions at the end of the file:

```python
def test_skip_buttons_paired_in_one_group():
    html = CARD.read_text()
    # Both skip buttons + the N input + presets live inside one .ia3d-skip-group
    # so the controls-row wrap can't orphan skip-forward on a second line.
    m = re.search(r'<span class="ia3d-skip-group">(.*?)</span>\s*</span>', html, re.S)
    assert m, "skip controls must be wrapped in a single .ia3d-skip-group span"
    group = m.group(1)
    assert 'id="ia3d-btn-skip-back"' in group
    assert 'id="ia3d-btn-skip-fwd"' in group
    assert 'id="ia3d-skip-n"' in group
    assert 'class="ia3d-skip-presets"' in group
    # skip-forward sits immediately after skip-back (the chosen pairing)
    assert group.index('id="ia3d-btn-skip-back"') < group.index('id="ia3d-btn-skip-fwd"') \
        < group.index('id="ia3d-skip-n"')


def test_skip_group_css_keeps_it_together():
    css = CSS.read_text()
    m = re.search(r"\.ia3d-skip-group\s*\{([^}]*)\}", css)
    assert m, "missing .ia3d-skip-group CSS rule"
    body = m.group(1)
    assert "inline-flex" in body and "flex-shrink: 0" in body, \
        "group must be an inline-flex item that does not shrink (so it wraps as a unit)"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_skip_buttons_paired_in_one_group tests/test_inline_analysis_3d_ui_isolation.py::test_skip_group_css_keeps_it_together -q`
Expected: FAIL — no `.ia3d-skip-group` in the card / no CSS rule.

- [ ] **Step 3: Wrap + reorder the skip controls in the card**

In `src/templates/partials/card_inline_analysis_3d.html`, replace the existing block (from the `<!-- Multi-frame skip -->` comment through the `</button>` that closes `#ia3d-btn-skip-fwd`, currently lines 219-234) with:

```html
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
```

(The element ids are unchanged, so the existing JS handlers stay wired. Only the wrapper + order changed.)

- [ ] **Step 4: Add the CSS rule**

In `src/static/inline_analysis_3d.css`, append after the existing `.ia3d-skip-preset` rules (the block ending around line 148):

```css
/* Keep the multi-frame skip controls together as one unit so .fe-controls wraps
   the whole group — never orphaning skip-forward (»») onto a second line. */
#inline-analysis-3d-card .ia3d-skip-group {
  display: inline-flex; align-items: center; gap: .3rem; flex-shrink: 0;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS (all tests, including the two new ones).

- [ ] **Step 6: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html src/static/inline_analysis_3d.css tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): pair skip-back/skip-fwd in a non-wrapping .ia3d-skip-group

The forward N-frame button existed but the controls row wrapped and orphaned it
on a second line. Wrap «/»/N/presets in one inline-flex group so it wraps as a
unit and the back/forward pair stays together.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: `setZoom` returns the row geometry

**Files:**
- Modify: `src/static/components/viewer/video_viewer.js:275-285` (the `setZoom` method)
- Test: `tests/test_video_viewer_base.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_video_viewer_base.py`:

```python
def test_setzoom_returns_row_geometry():
    src = _src()
    assert "setZoom" in src
    # returns the geometry it applied (the destructuring `const { width, marginLeft }
    # = fitViewerSize(...)` uses `=`, not `return`, so this only matches the return).
    assert re.search(r"return\s*\{\s*width\s*,\s*marginLeft\s*\}", src), \
        "setZoom must return { width, marginLeft }"
    # and returns null on the no-image early-out — scoped to the span between the
    # method open and its geometry return, so it's robust to indentation.
    m = re.search(r"setZoom\s*\([^)]*\)\s*\{(.*?)return\s*\{\s*width", src, re.S)
    assert m and re.search(r"return\s+null", m.group(1)), \
        "setZoom must return null on the no-image early-out (so callers can reset)"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_video_viewer_base.py::test_setzoom_returns_row_geometry -q`
Expected: FAIL — `setZoom` currently returns nothing.

- [ ] **Step 3: Make `setZoom` return the geometry**

In `src/static/components/viewer/video_viewer.js`, replace the `setZoom` method body so it returns `null` on the early-out and `{ width, marginLeft }` at the end:

```javascript
  setZoom(pct) {
    this._zoom = pct;
    const primary = this.getTile(0);
    if (!primary || !primary.imgEl || !primary.imgEl.naturalWidth) return null;
    const baseW = this.mount.clientWidth || primary.imgEl.naturalWidth;
    const view = this.mount.ownerDocument.defaultView || window;
    const maxW = Math.max(baseW, (view.innerWidth || baseW) - 32);
    const { width, marginLeft } = fitViewerSize({ baseW, maxW, zoom: pct });
    this.rowEl.style.width = width + "px";
    this.rowEl.style.marginLeft = marginLeft < 0 ? `${marginLeft}px` : "";
    return { width, marginLeft };   // consumers mirror this onto their own timelines
  }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_video_viewer_base.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/video_viewer.js tests/test_video_viewer_base.py
git commit -m "feat(viewer): setZoom returns the {width,marginLeft} it applied

Lets consumers mirror the zoomed video-row geometry onto their own timelines.
Returns null on the no-image early-out so callers can reset. Existing callers
ignore the return value.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: `statusNoteTimeline` exposes a public `redraw()`

**Files:**
- Modify: `src/static/components/viewer/features/status_notes.js:204-225` (the returned API object)
- Test: `tests/test_status_notes_feature.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_notes_feature.py`:

```python
def test_exposes_public_redraw():
    src = _src()
    # the feature returns a redraw() method so consumers can force a re-render
    # after they resize the status/note canvases (viewer zoom widens the bars)
    assert re.search(r"\bredraw\s*\(\s*\)\s*\{", src), \
        "factory result must expose a public `redraw()` method"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_status_notes_feature.py::test_exposes_public_redraw -q`
Expected: FAIL — the returned object only has `attach`.

- [ ] **Step 3: Add `redraw()` to the returned API**

In `src/static/components/viewer/features/status_notes.js`, the factory currently returns:

```javascript
  return {
    attach(v) {
      // … existing body …
    },
  };
```

Change it to add a `redraw()` method after `attach` (the inner `redraw` / `curFrame` are the existing module-scope function declarations — the method name does not shadow them):

```javascript
  return {
    attach(v) {
      // … existing body unchanged …
    },
    // Force a redraw at the current frame — consumers call this after resizing
    // the status/note canvases (e.g. when viewer zoom widens the timelines).
    redraw() { redraw(curFrame()); },
  };
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_status_notes_feature.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/components/viewer/features/status_notes.js tests/test_status_notes_feature.py
git commit -m "feat(viewer): statusNoteTimeline exposes a public redraw()

Lets a consumer force a status/note re-render after resizing those canvases
(used when viewer zoom widens the inline-3D timelines).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Inline card mirrors zoomed geometry onto its timelines

**Files:**
- Modify: `src/static/inline_analysis_3d.js` — capture the `statusNoteTimeline` handle; add `_applyTimelineWidth`; call it from the `#ia3d-zoom` handler; reset on video switch.
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

**Context for the implementer:**
- `_redrawSeekTimeline` and `_redrawFinalizeCoverage` are module-level `let`s (assigned the real draw fns in `_wireViewerChrome`). `$(id)` is the module's `document.getElementById` helper.
- The four timeline canvas ids are `ia3d-seek-canvas`, `ia3d-status-canvas`, `ia3d-note-canvas`, `ia3d-finalize-coverage`.
- The status/note feature is currently created inline as `_viewer.use(statusNoteTimeline({ … }))` — the return value is not captured. We need a module-level handle to call `.redraw()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_zoom_mirrors_geometry_onto_timelines():
    js = JS.read_text()
    # a helper that applies the row geometry to the timeline canvases
    assert js.count("_applyTimelineWidth") >= 2, \
        "_applyTimelineWidth must be defined and called"
    # the zoom handler feeds setZoom's return into it
    assert re.search(r"v\.setZoom\([^)]*\)", js)
    assert re.search(r"_applyTimelineWidth\(\s*g\s*\)", js), \
        "zoom handler must pass setZoom's returned geometry to _applyTimelineWidth"
    # all four timeline canvases are mirrored
    for cid in ["ia3d-seek-canvas", "ia3d-status-canvas", "ia3d-note-canvas", "ia3d-finalize-coverage"]:
        assert cid in js
    # the status/note feature handle is captured and redrawn
    assert "_snTimeline" in js
    assert re.search(r"_snTimeline\s*\.\s*redraw\s*\(", js), \
        "must call the status/note feature's redraw() after resizing"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_zoom_mirrors_geometry_onto_timelines -q`
Expected: FAIL — `_applyTimelineWidth` / `_snTimeline` don't exist yet.

- [ ] **Step 3: Add a module-level `_snTimeline` handle**

In `src/static/inline_analysis_3d.js`, near the other module-level state (e.g. just after `let _redrawFinalizeCoverage = () => {};`), add:

```javascript
let _snTimeline = null;   // statusNoteTimeline feature handle (for .redraw() on resize)
```

- [ ] **Step 4: Capture the feature handle at the use site**

Find the current call (around line 174):

```javascript
  _viewer.use(statusNoteTimeline({
    // … config …
  }));
```

Change it to capture the handle:

```javascript
  _snTimeline = statusNoteTimeline({
    // … config UNCHANGED …
  });
  _viewer.use(_snTimeline);
```

(Keep the entire `{ endpoints, els, fps, frameBase }` config object exactly as-is — only the assignment wrapper changes.)

- [ ] **Step 5: Add `_applyTimelineWidth` at module level**

In `src/static/inline_analysis_3d.js`, add this function next to `_drawCoverageBar` (module level):

```javascript
// Mirror the zoomed video-row geometry (from VideoViewer.setZoom) onto every
// timeline canvas, so the bars span the videos exactly → more pixels/frame =
// finer click precision. Only pin when the row overflows the card (marginLeft<0,
// i.e. zoom>100%); at 100% (or null geometry) reset to the responsive card width.
function _applyTimelineWidth(g) {
  const overflowing = !!(g && g.marginLeft < 0);
  for (const id of ["ia3d-seek-canvas", "ia3d-status-canvas", "ia3d-note-canvas", "ia3d-finalize-coverage"]) {
    const c = $(id);
    if (!c) continue;
    c.style.width = overflowing ? g.width + "px" : "";
    c.style.marginLeft = overflowing ? g.marginLeft + "px" : "";
  }
  _redrawSeekTimeline();
  _redrawFinalizeCoverage();
  if (_snTimeline) _snTimeline.redraw();
}
```

- [ ] **Step 6: Feed setZoom's return into it from the zoom handler**

Find the zoom handler (around line 432):

```javascript
  zoom?.addEventListener("input", () => {
    v.setZoom(parseInt(zoom.value, 10) || 100);
    const val = $("ia3d-zoom-val");
    if (val) val.textContent = zoom.value + " %";
  });
```

Replace it with:

```javascript
  zoom?.addEventListener("input", () => {
    const g = v.setZoom(parseInt(zoom.value, 10) || 100);
    _applyTimelineWidth(g);
    const val = $("ia3d-zoom-val");
    if (val) val.textContent = zoom.value + " %";
  });
```

- [ ] **Step 7: Reset timeline widths on video switch**

In `_resetForOpen` (where coverage state is cleared — search for `_coverageFrames = null;`), add right after the coverage resets so a freshly opened video starts at card width even if the previous one was zoomed:

```javascript
  _applyTimelineWidth(null);   // reset any pinned timeline widths from a prior zoom
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS.

- [ ] **Step 9: Run the full affected suites**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_base.py tests/test_status_notes_feature.py tests/test_video_viewer_policy.py -q && node --test tests/unit/*.mjs`
Expected: all PASS (pytest green; node `# fail 0`).

- [ ] **Step 10: Live verify** (the static tests can't observe layout)

The dlc-3D `src/static` is bind-mounted into the running container, so a browser hard-refresh picks up the JS/CSS. With the inline-3D card open on a video + overlay:
1. Feature 1: confirm `«` and `»` sit together as a pair on the same line (resize the card narrow → the whole skip group wraps together, never splitting the pair).
2. Feature 2: drag the zoom slider to ~150% → the main seek bar, status bar, note bar, and (if a finalized file exists) the finalize bar all widen to the video-row width and shift left to stay under the videos; clicking a coverage mark still lands exactly on its frame; set zoom back to 100% → bars return to card width with no offset.

(If driving headless: `python3` + Playwright as in prior sessions — set the DLC project via `POST /dlc/project`, open the card, select a video + primary h5, then compare `#ia3d-seek-canvas` `getBoundingClientRect().width` to the `.vv-tile-row` width at zoom 150%.)

- [ ] **Step 11: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): timelines track the zoomed video-row width

Mirror setZoom's {width,marginLeft} onto the four timeline canvases (seek,
status, note, finalize) so they span the enlarged videos → more pixels/frame
for finer click precision. Resets to card width at 100% and on video switch.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Notes / out of scope (YAGNI)
- No coverage re-fetch at higher bucket resolution when zoomed (marks just rescale; click precision is continuous via `xToFrame`).
- Not applied to View Analyzed / frame-labeler.
- Only the zoom slider triggers re-fit (not plain window resizes); per-view weight sliders are intentionally not tracked (they don't change the row total).
