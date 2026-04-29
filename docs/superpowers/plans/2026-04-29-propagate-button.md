# Propagate Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `ep-propagate-kf` checkbox with an explicit `↻ Propagate` button that rescans all unprocessed detections in both directions when clicked.

**Architecture:** Two files change. The HTML swap is one line. The JS changes remove auto-propagation from `_epApplyNewKF`, refactor `_epStartRescan` to accept an explicit candidate list instead of computing forward-only internally, add `_epPropagateAll()` that collects both directions, and wire the button. No backend changes.

**Tech Stack:** Vanilla JS, Jinja2 HTML templates, Playwright (pytest) UI tests

---

## File Map

| File | Change |
|---|---|
| `clip-cutter/templates/clip_cutter.html:1024-1027` | Replace `ep-propagate-kf` checkbox label with `ep-propagate-btn` button |
| `clip-cutter/static/enhanced_player.js:1054-1063` | Remove template/add block + `_epStartRescan` auto-call from `_epApplyNewKF` |
| `clip-cutter/static/enhanced_player.js:1086-1161` | Refactor `_epStartRescan(detectionIdx)` → `_epStartRescan(candidates)` |
| `clip-cutter/static/enhanced_player.js:978` | Add `ep-propagate-btn` enable/disable in `_epUpdateModeUI` |
| `clip-cutter/static/enhanced_player.js` (new) | Add `_epPropagateAll()` function + wire button click |
| `clip-cutter/tests/test_ui.py:1923` | Replace `test_propagate_row_has_two_checkboxes` with updated test; add 3 new tests |

---

### Task 1: Replace propagate checkbox with button in HTML

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html:1024-1027`
- Test: `clip-cutter/tests/test_ui.py`

The current `ep-propagate-row` (line 1019) contains two checkboxes. Replace only the `ep-propagate-kf` label+checkbox (lines 1024-1027) with a button. The `ep-add-kf-to-template` checkbox stays untouched.

- [ ] **Step 1: Write failing tests**

Open `clip-cutter/tests/test_ui.py`. Find `test_propagate_row_has_two_checkboxes` at line 1923. Replace it entirely with:

```python
def test_propagate_row_has_add_kf_checkbox_and_propagate_btn(page: Page):
    """ep-propagate-row must have ep-add-kf-to-template checkbox (checked) and ep-propagate-btn button (disabled by default)."""
    setup_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    add_kf_checked = page.evaluate(
        "document.getElementById('ep-add-kf-to-template').checked"
    )
    assert add_kf_checked is True, "ep-add-kf-to-template should be checked by default"

    propagate_kf = page.evaluate(
        "document.getElementById('ep-propagate-kf')"
    )
    assert propagate_kf is None, "ep-propagate-kf checkbox should no longer exist"

    btn = page.locator("#ep-propagate-btn")
    expect(btn).to_have_count(1)
    expect(btn).to_be_disabled()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_ui.py::test_propagate_row_has_add_kf_checkbox_and_propagate_btn -v
```

Expected: FAIL — `ep-propagate-kf` still exists, `ep-propagate-btn` does not.

- [ ] **Step 3: Update the HTML**

In `clip-cutter/templates/clip_cutter.html`, replace lines 1024-1027:

```html
      <label style="display:flex;align-items:center;gap:4px;font-size:10px;color:#adbac7;cursor:pointer;">
        <input type="checkbox" id="ep-propagate-kf" style="accent-color:#388bfd;cursor:pointer;">
        propagate
      </label>
```

With:

```html
      <button class="player-btn" id="ep-propagate-btn" disabled
        style="font-size:9px;padding:2px 7px;"
        title="Rescan all unprocessed detections in both directions">↻ Propagate</button>
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_ui.py::test_propagate_row_has_add_kf_checkbox_and_propagate_btn -v
```

Expected: PASS

- [ ] **Step 5: Run full suite to check for regressions**

```bash
python -m pytest tests/test_ui.py -q
```

Expected: all tests pass except any that reference `ep-propagate-kf` — those will be addressed in Task 2.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
git add templates/clip_cutter.html tests/test_ui.py
git commit -m "feat: replace propagate checkbox with Propagate button"
```

---

### Task 2: Refactor JS — remove auto-propagate, add `_epPropagateAll`, wire button

**Files:**
- Modify: `clip-cutter/static/enhanced_player.js:1054-1063` (`_epApplyNewKF` tail)
- Modify: `clip-cutter/static/enhanced_player.js:1086-1161` (`_epStartRescan`)
- Modify: `clip-cutter/static/enhanced_player.js:978` (`_epUpdateModeUI`)
- Modify: `clip-cutter/static/enhanced_player.js` (add `_epPropagateAll` + wire)
- Test: `clip-cutter/tests/test_ui.py`

- [ ] **Step 1: Write failing tests**

Append to `clip-cutter/tests/test_ui.py`:

```python
def test_propagate_btn_disabled_in_browse_mode(page: Page):
    """Propagate button must be disabled when no detection is active (browse mode)."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        selectedVideoPath = '/user-data/vid1.avi';
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi', unlocked: true });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    expect(page.locator("#ep-propagate-btn")).to_be_disabled()


def test_propagate_btn_enabled_when_detection_active(page: Page):
    """Propagate button must be enabled when a clip-mode detection is active."""
    _setup_browse_routes(page)
    page.goto(f"{BASE_URL}/clip-cutter/")
    page.evaluate("""() => {
        detections = [{
            video_path: '/user-data/vid1.avi', frame_number: 500,
            similarity: 0, source: 'manual', status: 'pending'
        }];
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi',
                     keyFrame1Based: 500, detectionIdx: 0 });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    expect(page.locator("#ep-propagate-btn")).not_to_be_disabled()


def test_propagate_btn_collects_both_directions(page: Page):
    """Clicking Propagate posts candidates from both before and after the active detection."""
    requests_captured = []

    def capture(req):
        if "rescan-forward" in req.url and req.method == "POST":
            requests_captured.append(req)

    _setup_browse_routes(page)
    page.route("**/clip-cutter/rescan-forward", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"job_id": "test-job-123"})
    ))
    page.on("request", capture)
    page.goto(f"{BASE_URL}/clip-cutter/")

    # Three detections: idx 0 (before), idx 1 (active), idx 2 (after)
    page.evaluate("""() => {
        detections = [
            { video_path: '/user-data/vid1.avi', frame_number: 200, similarity: 0, source: 'manual', status: 'pending' },
            { video_path: '/user-data/vid1.avi', frame_number: 500, similarity: 0, source: 'manual', status: 'pending' },
            { video_path: '/user-data/vid1.avi', frame_number: 800, similarity: 0, source: 'manual', status: 'pending' },
        ];
        openPlayer({ mode: 'clip', videoPath: '/user-data/vid1.avi',
                     keyFrame1Based: 500, detectionIdx: 1 });
    }""")
    page.wait_for_selector("#player-panel", state="visible")
    page.click("#ep-propagate-btn")

    page.wait_for_timeout(400)

    assert len(requests_captured) == 1, f"expected 1 rescan request, got {len(requests_captured)}"
    body = json.loads(requests_captured[0].post_data)
    candidate_idxs = sorted(c["idx"] for c in body["candidates"])
    assert candidate_idxs == [0, 2], f"expected candidates [0, 2], got {candidate_idxs}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ui.py::test_propagate_btn_disabled_in_browse_mode tests/test_ui.py::test_propagate_btn_enabled_when_detection_active tests/test_ui.py::test_propagate_btn_collects_both_directions -v
```

Expected: all FAIL — button state not yet wired, `_epPropagateAll` doesn't exist.

- [ ] **Step 3: Remove auto-propagate from `_epApplyNewKF`**

In `clip-cutter/static/enhanced_player.js`, remove lines 1054-1063 (the `ep-propagate-kf`-gated template/add block and the `_epStartRescan` call):

```js
  // REMOVE these lines from _epApplyNewKF (currently lines 1054-1063):
  if (document.getElementById("ep-propagate-kf")?.checked) {
    try {
      await fetch("/clip-cutter/template/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _videoPath, frame_number: kf1 }),
      });
    } catch { /* non-fatal */ }
  }
  _epStartRescan(_detectionIdx);
```

The function now ends at line 1051 (`_epDrawKfCanvas();`) and the closing `}`.

- [ ] **Step 4: Refactor `_epStartRescan` to accept explicit candidates**

Replace the entire `_epStartRescan` function (currently lines 1086-1161) with:

```js
async function _epStartRescan(candidates) {
  // Tear down any in-flight rescan before starting a new one
  if (_rescanEs) { _rescanEs.close(); _rescanEs = null; }
  if (_rescanJobId) {
    const oldJid = _rescanJobId;
    _rescanJobId = null;
    fetch(`/clip-cutter/rescan-forward/${oldJid}/cancel`, { method: "POST" }).catch(() => {});
  }

  if (!candidates || !candidates.length) return;

  const videoPath = _videoPath;
  const fineWindowEl = document.getElementById("fine-window");
  const fineWindow = fineWindowEl ? parseInt(fineWindowEl.value, 10) : 50;

  let data;
  try {
    const resp = await fetch("/clip-cutter/rescan-forward", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        video_path: videoPath,
        candidates,
        params: { fine_window: fineWindow },
      }),
    });
    if (!resp.ok) return;
    data = await resp.json();
  } catch { return; }

  _rescanJobId = data.job_id;

  const prog = document.getElementById("ep-rescan-progress");
  const textEl = document.getElementById("ep-rescan-text");
  const countEl = document.getElementById("ep-rescan-count");
  if (prog) {
    prog.style.display = "flex";
    if (textEl) textEl.textContent = `↻ Rescanning ${candidates.length} candidates…`;
    if (countEl) countEl.textContent = "";
  }

  let done = 0;
  const total = candidates.length;
  const es = new EventSource(`/clip-cutter/rescan-forward/stream?job_id=${_rescanJobId}`);
  _rescanEs = es;

  function _finishRescan() {
    _rescanEs = null;
    _rescanJobId = null;
    if (prog) prog.style.display = "none";
  }

  es.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { es.close(); _finishRescan(); return; }
    if (msg.phase) {
      es.close();
      _finishRescan();
      return;
    }
    done++;
    if (countEl) countEl.textContent = `${done} / ${total}`;
    _epApplyRescanKF(msg.idx, msg.new_frame_number);
  };
  es.onerror = () => { es.close(); _finishRescan(); };
}
```

- [ ] **Step 5: Add `_epPropagateAll` and wire button click**

Immediately after the closing `}` of `_epStartRescan`, add:

```js
function _epPropagateAll() {
  if (_detectionIdx === null || typeof detections === "undefined") return;
  const videoPath = _videoPath;
  const candidates = [];
  for (let i = 0; i < detections.length; i++) {
    if (i === _detectionIdx) continue;
    const d = detections[i];
    if (!d || d.video_path !== videoPath) continue;
    if (d.status === "kept" || d.status === "rejected") continue;
    candidates.push({ idx: i, frame_number: d.frame_number });
  }
  _epStartRescan(candidates);
}
```

Then find the `ep-rescan-cancel` event listener (currently around line 1912) and add the propagate button wire immediately after it:

```js
  document.getElementById("ep-propagate-btn")
    ?.addEventListener("click", () => _epPropagateAll());
```

- [ ] **Step 6: Enable/disable button in `_epUpdateModeUI`**

In `_epUpdateModeUI` (line 936), add the following two lines immediately before the final `_epUpdateSeekHighlight()` call (currently line 978):

```js
  const propagateBtn = document.getElementById("ep-propagate-btn");
  if (propagateBtn) propagateBtn.disabled = (_detectionIdx === null);
```

- [ ] **Step 7: Run failing tests to verify they now pass**

```bash
python -m pytest tests/test_ui.py::test_propagate_btn_disabled_in_browse_mode tests/test_ui.py::test_propagate_btn_enabled_when_detection_active tests/test_ui.py::test_propagate_btn_collects_both_directions -v
```

Expected: all PASS

- [ ] **Step 8: Run full suite**

```bash
python -m pytest tests/test_ui.py -q
```

Expected: all tests pass. Any remaining `ep-propagate-kf` references in older tests should now be gone — if any still exist from test cleanup gaps, remove them now.

- [ ] **Step 9: Commit**

```bash
git add static/enhanced_player.js tests/test_ui.py
git commit -m "feat: propagate button rescans both directions on demand"
```
