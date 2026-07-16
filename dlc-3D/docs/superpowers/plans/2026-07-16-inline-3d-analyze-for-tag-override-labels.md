# Inline 3D "Analyze for tag" — Override Existing Labels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in "override existing labels" mode to the "Analyze for tag" batch: default preserves already-populated frames (today's behavior); checked re-runs the model over every tagged-window frame and overwrites existing data (incl. human corrections), after a confirmation.

**Architecture:** A single `overwrite` boolean flows from a new frontend checkbox → the `/dlc/project/inline-analysis/range` POST body → the Redis payload → the warm worker, where it bypasses the skip filter. No merge change: `df_range.combine_first(existing)` already lets freshly re-analyzed frames win. Backend lives in the **`deeplabcut-webapp-docker`** repo; frontend in the **`dlc-3D`** module. The two are wired only by the `overwrite` field and can land independently.

**Tech Stack:** Flask + Celery (Python) backend; vanilla ES module + Jinja partial frontend. Tests: pytest (backend units + routes; frontend static guards), Playwright (frontend e2e).

## Global Constraints

- Backend repo: `deeplabcut-webapp-docker` (branch off `main` — the worker is not on a feature branch; use e.g. `feat/inline-analysis-overwrite-flag`). Frontend repo/module: `deeplabcut-webapp-docker-supports` / `dlc-3D`, on branch `feat/inline-3d-panel-consolidation`.
- Default (`overwrite=False`) must be **byte-for-byte the current behavior**: `_filter_skip_already_done` skips any frame whose existing row is not all-NaN. Only `overwrite=True` changes anything.
- Override is scoped to the **"Analyze for tag" batch only**. The current-frame and for-range analyze buttons must keep submitting with `overwrite=False` (the `_submitRange` default).
- The checkbox `#ia3d-override-labels` is **unchecked by default** and always enabled (independent of the tag-lock).
- The confirm is a **single** `window.confirm` (the existing batch-summary prompt) with an added ⚠️ warning line when override is on.
- No merge change; no likelihood inspection (human-vs-machine distinction is out of scope).
- Backend host note: host Python has a PyTables/numpy ABI mismatch — real `to_hdf` fails on the host. Tests mock `pandas.read_hdf` / patch `_atomic_write_h5` (see the existing patterns in `tests/test_inline_analysis_worker.py`). Run backend tests from `deeplabcut-webapp-docker/`: `python -m pytest tests/test_inline_analysis_worker.py tests/test_inline_analysis_routes.py -q`.
- Frontend node/e2e: Node is v16 (use `node --test tests/unit/*.mjs`, not a bare dir); e2e is read-only against the live stack; the dlc-3D `.html` template is a single-file bind-mount — needs `docker restart deeplabcut-webapp-docker-dlc-3d-1` to serve markup changes.

---

### Task 1: Backend — thread `overwrite` through route → worker → skip filter

**Files:**
- Modify: `deeplabcut-webapp-docker/src/dlc/tasks.py` (`_filter_skip_already_done` ~2783, `_run_range` line 3036)
- Modify: `deeplabcut-webapp-docker/src/dlc/inline_analysis.py` (`range_submit` payload ~275-283)
- Test: `deeplabcut-webapp-docker/tests/test_inline_analysis_worker.py`, `deeplabcut-webapp-docker/tests/test_inline_analysis_routes.py`

**Interfaces:**
- Consumes: existing `_run_range`, `combine_first` merge, `_resolve_h5_path`, the route's `body`/`payload`, and the test helpers `_df_with_index`, `_stub_create_df`, `_run_range_kw`, the `ia_client` fixture.
- Produces: `_filter_skip_already_done(target_frames, existing_df, overwrite=False)`; the enqueued payload gains `"overwrite": bool`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_inline_analysis_worker.py`, add to `class TestFilterSkipAlreadyDone`:

```python
    def test_overwrite_returns_all_target_even_when_present(self):
        df = _df_with_index([0, 1, 2, 3, 4])  # all rows finite
        assert dlc_tasks._filter_skip_already_done([1, 2, 3], df, overwrite=True) == [1, 2, 3]

    def test_overwrite_false_default_still_skips(self):
        df = _df_with_index([0, 1, 2, 3, 4])
        assert dlc_tasks._filter_skip_already_done([1, 2, 3], df) == []
```

In `tests/test_inline_analysis_worker.py`, add to `class TestRunRange`:

```python
    def test_run_range_overwrite_reanalyzes_and_overwrites_existing(self, tmp_path):
        video_path = tmp_path / "v.mp4"
        video_path.write_bytes(b"")
        runner = MagicMock()
        # Existing h5 already has finite (1.0) data for all target frames.
        seed_df = _df_with_index([100, 101, 102])  # scorer level == "scorer"
        h5_path = dlc_tasks._resolve_h5_path(str(video_path), "scorer")
        h5_path.write_bytes(b"placeholder")

        captured = {}

        def _capture_write(path, df):
            captured["df"] = df

        def fake_video_inference(vit, pose_runner):
            return [{}, {}, {}]  # 3 predictions → all 3 target frames

        with patch("pandas.read_hdf", return_value=seed_df), \
             patch.object(dlc_tasks, "_atomic_write_h5", _capture_write), \
             patch.object(dlc_tasks, "video_inference", fake_video_inference), \
             patch.object(dlc_tasks, "_dlc_create_df_from_prediction", _stub_create_df), \
             patch.object(dlc_tasks, "_RangeVideoIterator",
                          lambda p, indices: iter([None] * len(indices))):
            req = {
                "req_id": "r1", "video_path": str(video_path),
                "start_frame": 100, "n_frames": 3, "batch_size": 8,
                "save_as_csv": False, "snapshot_path": "snap.pt",
                "overwrite": True,
            }
            n_analyzed, n_skipped = dlc_tasks._run_range(
                runner, req=req, **_run_range_kw(scorer="scorer")
            )
        assert n_analyzed == 3
        assert n_skipped == 0
        # _stub_create_df writes 0.0; the seed was 1.0 → overwrite means the
        # merged rows carry the NEW (0.0) values, not the old ones.
        df = captured["df"]
        assert float(df.loc[100, ("scorer", "nose", "x")]) == 0.0
```

In `tests/test_inline_analysis_routes.py`, add to `class TestRangeSubmit`:

```python
    def test_overwrite_flag_flows_into_payload(self, ia_client):
        client, _app, redis, project = ia_client
        v = project / "videos" / "ovr.mp4"
        v.parent.mkdir(parents=True, exist_ok=True)
        v.write_bytes(b"")
        resp = client.post("/dlc/project/inline-analysis/range", json={
            "snap_key": "k1", "video_path": str(v),
            "start_frame": 0, "n_frames": 5, "batch_size": 8, "overwrite": True,
        })
        assert resp.status_code == 202, resp.get_json()
        payload = json.loads(redis._lists.get("inline:queue:u1:k1", [])[0])
        assert payload["overwrite"] is True

    def test_overwrite_defaults_false_when_absent(self, ia_client):
        client, _app, redis, project = ia_client
        v = project / "videos" / "noovr.mp4"
        v.parent.mkdir(parents=True, exist_ok=True)
        v.write_bytes(b"")
        resp = client.post("/dlc/project/inline-analysis/range", json={
            "snap_key": "k1", "video_path": str(v),
            "start_frame": 0, "n_frames": 5, "batch_size": 8,
        })
        assert resp.status_code == 202, resp.get_json()
        payload = json.loads(redis._lists.get("inline:queue:u1:k1", [])[0])
        assert payload["overwrite"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_inline_analysis_worker.py::TestFilterSkipAlreadyDone tests/test_inline_analysis_worker.py::TestRunRange::test_run_range_overwrite_reanalyzes_and_overwrites_existing "tests/test_inline_analysis_routes.py::TestRangeSubmit" -q`
Expected: the new tests FAIL — `_filter_skip_already_done` takes no `overwrite` kwarg (TypeError) and `payload["overwrite"]` KeyError.

- [ ] **Step 3a: Add the `overwrite` param to `_filter_skip_already_done`**

In `src/dlc/tasks.py`, replace the function (currently lines ~2783-2795):

```python
def _filter_skip_already_done(target_frames, existing_df, overwrite=False):
    """Return the subset of target_frames that need re-analysis.

    A frame needs re-analysis if it's missing from existing_df or if every
    value in its row is NaN (matches DLC's own dynamic-cropping semantics).
    When overwrite is True, every target frame is re-analyzed regardless of any
    existing data (the "override existing labels" batch option) — the
    combine_first merge in _run_range then lets the fresh predictions win.
    """
    if overwrite or existing_df is None:
        return list(target_frames)
    have = existing_df.index
    return [
        f for f in target_frames
        if f not in have or existing_df.loc[f].isna().all()
    ]
```

- [ ] **Step 3b: Pass `overwrite` from the request in `_run_range`**

In `src/dlc/tasks.py`, change line 3036 from:

```python
    to_analyze = _filter_skip_already_done(target, existing)
```

to:

```python
    to_analyze = _filter_skip_already_done(target, existing, req.get("overwrite", False))
```

- [ ] **Step 3c: Add `overwrite` to the enqueued payload in `range_submit`**

In `src/dlc/inline_analysis.py`, change the `payload` dict tail from:

```python
        "save_as_csv":   bool(body.get("save_as_csv", False)),
        "snapshot_path": body.get("snapshot_path", ""),
    }
```

to:

```python
        "save_as_csv":   bool(body.get("save_as_csv", False)),
        "snapshot_path": body.get("snapshot_path", ""),
        "overwrite":     bool(body.get("overwrite", False)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_inline_analysis_worker.py tests/test_inline_analysis_routes.py -q`
Expected: PASS (new tests green; all pre-existing worker/route tests still pass — the default path is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/dlc/tasks.py src/dlc/inline_analysis.py tests/test_inline_analysis_worker.py tests/test_inline_analysis_routes.py
git commit -m "feat(inline-analysis): overwrite flag bypasses skip filter for range analysis

overwrite=True re-analyzes every target frame regardless of existing data; the
combine_first merge then overwrites the existing rows. Default False preserves
current skip behavior. Threaded route -> payload -> worker.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Frontend — override checkbox + wire into the tag batch

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_inline_analysis_3d.html` (`.ia3d-tag-batch`, ~lines 420-430)
- Modify: `dlc-3D/src/static/inline_analysis_3d.js` (`_submitRange` ~1896, `_onAnalyzeTagClick` ~2071-2108)
- Test: `dlc-3D/tests/test_inline_3d_override_labels.py` (create)

**Interfaces:**
- Consumes: `#ia3d-tag-batch`, `#ia3d-tag-lock`, `#ia3d-btn-analyze-tag`, the existing `_onAnalyzeTagClick` batch loop.
- Produces: `#ia3d-override-labels` checkbox; `_submitRange(sk, videoPath, startFrame, nFrames, overwrite = false)` now forwards `overwrite` in the POST body.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/test_inline_3d_override_labels.py`:

```python
"""Static guards for the "override existing labels" control on the Analyze-for-tag
batch. See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-override-labels-design.md.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
JS = ROOT / "src" / "static" / "inline_analysis_3d.js"


def _idx(hay, needle):
    i = hay.find(needle)
    assert i >= 0, f"not found: {needle}"
    return i


def test_override_checkbox_in_tag_batch_unchecked_and_enabled():
    html = CARD.read_text()
    batch = _idx(html, 'class="ia3d-tag-batch"')
    # end of the tag-batch div: the add-frame button follows it
    after = _idx(html, 'id="ia3d-add-frame-nomarkers-btn"')
    i = _idx(html, 'id="ia3d-override-labels"')
    assert batch < i < after, "override checkbox must live inside .ia3d-tag-batch"
    # the full <input ...> tag that carries this id
    start = html.rindex("<input", 0, i)
    tag = html[start:html.index(">", start)]
    assert 'type="checkbox"' in tag, "override control must be a checkbox"
    assert "checked" not in tag, "override checkbox must be unchecked by default"
    assert "disabled" not in tag, "override checkbox must be enabled (independent of tag-lock)"


def test_submitRange_forwards_overwrite():
    js = JS.read_text()
    assert re.search(r"async function _submitRange\(sk, videoPath, startFrame, nFrames, overwrite = false\)", js), \
        "_submitRange must take an overwrite param defaulting to false"
    assert re.search(r"overwrite:\s*!!overwrite", js), "_submitRange body must send overwrite"


def test_onAnalyzeTag_reads_checkbox_warns_and_passes_overwrite():
    js = JS.read_text()
    tag_fn = js[_idx(js, "async function _onAnalyzeTagClick()"): _idx(js, "async function _onAnalyzeTagClick()") + 2000]
    assert 'ia3d-override-labels' in tag_fn, "batch handler must read the override checkbox"
    assert re.search(r"overwrite\s*\?", tag_fn), "confirm must add a warning when override is on"
    assert re.search(r"_submitRange\(sk, cam0, r\.start, r\.n, overwrite\)", tag_fn), \
        "batch must pass overwrite to cam0 submit"
    assert re.search(r"_submitRange\(sk, _siblingPath, r\.start, r\.n, overwrite\)", tag_fn), \
        "batch must pass overwrite to sibling submit"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `dlc-3D/`): `python -m pytest tests/test_inline_3d_override_labels.py -q`
Expected: FAIL — `#ia3d-override-labels` absent and `_submitRange` has no `overwrite` param.

- [ ] **Step 3a: Add the checkbox to the template**

In `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`, insert the override checkbox inside `.ia3d-tag-batch`, immediately after the `Lock tag` label's closing `</label>` (line 424) and before the `#ia3d-btn-analyze-tag` button (line 425):

```html
                Lock tag
              </label>
              <label class="ia3d-tag-lock-label" title="When ON, re-run the model over every frame in the tagged windows and OVERWRITE existing predictions AND human corrections. Default OFF preserves already-labeled frames.">
                <input type="checkbox" id="ia3d-override-labels" style="accent-color:var(--danger,#e66);width:14px;height:14px"/>
                override existing labels
              </label>
              <button id="ia3d-btn-analyze-tag" class="btn-sm btn-create" disabled
```

- [ ] **Step 3b: Forward `overwrite` from `_submitRange`**

In `dlc-3D/src/static/inline_analysis_3d.js`, change the `_submitRange` signature (line 1896) and add `overwrite` to the body. Replace:

```javascript
async function _submitRange(sk, videoPath, startFrame, nFrames) {
```
with:
```javascript
async function _submitRange(sk, videoPath, startFrame, nFrames, overwrite = false) {
```

and, inside the JSON body, add `overwrite` after the `trainingsetindex` line:

```javascript
      shuffle: parseInt(_ia3dEl.shuffle()?.value, 10) || 1,
      trainingsetindex: parseInt(_ia3dEl.tsi()?.value, 10) || 0,
      overwrite: !!overwrite,
    }),
```

- [ ] **Step 3c: Read the checkbox, warn, and pass `overwrite` in `_onAnalyzeTagClick`**

In `dlc-3D/src/static/inline_analysis_3d.js`, in `_onAnalyzeTagClick`:

First, read the checkbox — add after `const tagValue = activeNotes[0];` (line 2078):

```javascript
  const tagValue = activeNotes[0];
  const overwrite = !!$("ia3d-override-labels")?.checked;
```

Then replace the confirm block (lines 2089-2092):

```javascript
  const ok = window.confirm(
    `Analyze note tag "${tagValue}":\n` +
    `${frames.length} tagged frame(s) → ${ranges.length} range(s) → ${totalFrames} frames × 2 cameras.` +
    (overwrite
      ? `\n\n⚠️ Override is ON: this will OVERWRITE existing predictions AND human corrections in these frames.`
      : ``) +
    `\n\nProceed?`
  );
```

Then pass `overwrite` to both submits in the loop (lines 2102-2105):

```javascript
    const [q0, q1] = await Promise.all([
      _submitRange(sk, cam0, r.start, r.n, overwrite),
      _submitRange(sk, _siblingPath, r.start, r.n, overwrite),
    ]);
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `dlc-3D/`): `python -m pytest tests/test_inline_3d_override_labels.py -q`
Expected: PASS (3 tests).

Regression (must stay green): `python -m pytest tests/test_inline_3d_analyze_for_tag_wiring.py tests/test_inline_3d_analyze_for_tag_markup.py -q && node --test tests/unit/*.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html src/static/inline_analysis_3d.js tests/test_inline_3d_override_labels.py
git commit -m "feat(inline-3d): 'override existing labels' checkbox on Analyze-for-tag

Unchecked by default; when checked the batch passes overwrite=true to every
range submit and the confirm gains an explicit overwrite warning.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Frontend e2e — override checkbox present + unchecked by default

**Files:**
- Test: `dlc-3D/tests/e2e/test_inline_3d_override_labels.py` (create)

**Interfaces:**
- Consumes: the shared e2e conftest `page`/`base_url` fixtures and the card-open pattern from `tests/e2e/test_inline_3d_reorg.py` / `tests/e2e/test_inline_3d_analyze_for_tag.py`.

**Note:** Read-only — never triggers analysis. Requires the running stack AND a `docker restart deeplabcut-webapp-docker-dlc-3d-1` so the restarted container serves the new markup (single-file HTML bind-mount).

- [ ] **Step 1: Write the test**

Create `dlc-3D/tests/e2e/test_inline_3d_override_labels.py`:

```python
"""Live read-only check for the "override existing labels" checkbox on the
Analyze-for-tag batch: present and unchecked by default. NEVER triggers analysis.
"""
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"
PROJECT_PATH_IN_CONTAINER = (
    "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07"
)
BROWSE_VIDEO = f"{PROJECT_PATH_IN_CONTAINER}/videos/{SESSION}.mp4"


@pytest.fixture(autouse=True)
def _open_inline_card(page: Page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-inline-analysis-3d").click()
    page.locator("#inline-analysis-3d-card").wait_for(state="visible")
    page.locator("#ia3d-tab-browse").click()
    page.locator("#ia3d-browse-breadcrumb").fill(BROWSE_VIDEO)
    page.locator("#ia3d-browse-breadcrumb").press("Enter")
    page.locator("#ia3d-player-section").wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        "() => window.__iaViewer && document.querySelector('#ia3d-viewer-mount .vv-tile')"
    )


def test_override_checkbox_present(page: Page):
    expect(page.locator("#ia3d-override-labels")).to_be_visible()


def test_override_checkbox_unchecked_by_default(page: Page):
    assert page.locator("#ia3d-override-labels").is_checked() is False
```

- [ ] **Step 2: Run the test**

Run (from `dlc-3D/`, after `docker restart deeplabcut-webapp-docker-dlc-3d-1`): `python -m pytest tests/e2e/test_inline_3d_override_labels.py -q`
Expected: PASS (2 tests). If the stack isn't running in this environment, note it and run where available (same precondition as the existing `tests/e2e/` suite).

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_inline_3d_override_labels.py
git commit -m "test(inline-3d): e2e presence + unchecked-default for override-labels checkbox

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Backend (from `deeplabcut-webapp-docker/`):

```bash
python -m pytest tests/test_inline_analysis_worker.py tests/test_inline_analysis_routes.py -q
```

- [ ] Frontend (from `dlc-3D/`):

```bash
python -m pytest tests/test_inline_3d_override_labels.py tests/test_inline_3d_analyze_for_tag_wiring.py tests/test_inline_3d_analyze_for_tag_markup.py -q
node --test tests/unit/*.mjs
docker restart deeplabcut-webapp-docker-dlc-3d-1  # serve new markup
python -m pytest tests/e2e/test_inline_3d_override_labels.py -q
```

Expected: all PASS.

- [ ] Manual smoke (running app, labeled video with a cam1 sibling + note tags): open the inline-3D card → activate one note tag → Lock tag → check "override existing labels" → Analyze for tag → confirm the dialog shows the ⚠️ override warning → run against a non-protected project and verify previously-existing predictions in the windows were overwritten. Then repeat with override unchecked and confirm already-analyzed frames are skipped.

## Self-Review notes

- **Spec coverage:** overwrite flag route→worker→filter → Task 1; no merge change (verified `combine_first` self-wins) → Task 1 (value assertion in `test_run_range_overwrite_reanalyzes_and_overwrites_existing`); checkbox unchecked/enabled + scoped to tag batch → Task 2; single confirm with warning → Task 2 (Step 3c); default unchanged → Task 1 (`test_overwrite_false_default_still_skips`, plus all pre-existing worker/route tests) and Task 2 (`_submitRange` default `false`, other callers unchanged); e2e presence/default → Task 3.
- **Type consistency:** `overwrite` is a bool everywhere — JS `!!overwrite` in the body, Python `bool(body.get("overwrite", False))` in the route and `req.get("overwrite", False)` in the worker, `_filter_skip_already_done(..., overwrite=False)`. `_submitRange`'s new 5th arg is optional (`= false`), so the two existing callers are unaffected.
