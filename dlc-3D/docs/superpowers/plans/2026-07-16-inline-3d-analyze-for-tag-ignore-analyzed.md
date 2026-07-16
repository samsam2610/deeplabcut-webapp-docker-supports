# Inline 3D "Analyze for tag" — Ignore frames already in _analyzed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `ignore frames already in _analyzed` checkbox (checked by default) to the "Analyze for tag" batch that skips frames finalized in `<stem>_analyzed.h5`, with priority over the existing `override existing labels` flag.

**Architecture:** A new `ignore_analyzed` boolean flows frontend checkbox → `/range` POST body → Redis payload → warm worker, exactly like `overwrite`. In the worker, when set, `_run_range` reads `<stem>_analyzed.h5` and excludes frames "marked" in the coverage timeline (any bodypart with a finite x), even under `overwrite`. Backend in `deeplabcut-webapp-docker`; frontend in `dlc-3D`.

**Tech Stack:** Flask + Celery (Python); vanilla ES module + Jinja partial. Tests: pytest (backend units + routes; frontend static guards), Playwright (frontend e2e).

## Global Constraints

- Backend repo: `deeplabcut-webapp-docker`, branch `feat/inline-analysis-overwrite-flag` (already holds the `overwrite` work this extends). Frontend: `deeplabcut-webapp-docker-supports`/`dlc-3D`, branch `feat/inline-3d-panel-consolidation`.
- "Marked in `_analyzed`" = a frame whose `<stem>_analyzed.h5` row has a finite x for any bodypart (presence rule; mirrors `viewer._coverage_buckets`, `viewer.py:355-356`). Reuse this rule, do not invent a different one.
- **Priority: `ignore_analyzed` wins over `overwrite`.** A finalized frame is skipped even when `overwrite=True`.
- Default `ignore_analyzed=False` at the backend (payload/worker) so old clients and the other two analyze buttons are unchanged. The frontend tag checkbox is **checked by default**, so the tag batch sends `true` normally.
- Read `<stem>_analyzed.h5` only when `ignore_analyzed` is set (avoid needless I/O). The worker still writes only the per-scorer h5 — never `_analyzed`.
- Scope: the "Analyze for tag" batch only. The current-frame and for-range buttons keep submitting without `ignore_analyzed` (default false).
- Backend host note: PyTables/numpy ABI mismatch — real `to_hdf` fails on the host; tests mock `pandas.read_hdf` and/or patch `_atomic_write_h5` (see existing patterns in `tests/test_inline_analysis_worker.py`). Run backend tests from `deeplabcut-webapp-docker/`.
- Frontend: Node 16 (`node --test tests/unit/*.mjs`); e2e read-only against the live stack; dlc-3D `.html` needs `docker restart deeplabcut-webapp-docker-dlc-3d-1` to serve markup changes.

---

### Task 1: Backend — `labeled_frames` helper + `ignore_analyzed` in filter/worker/route

**Files:**
- Modify: `deeplabcut-webapp-docker/src/dlc/canonical.py` (after `canonical_csv_path`, ~line 28)
- Modify: `deeplabcut-webapp-docker/src/dlc/tasks.py` (`_filter_skip_already_done` ~2783, `_run_range` ~3038)
- Modify: `deeplabcut-webapp-docker/src/dlc/inline_analysis.py` (`range_submit` payload ~283)
- Test: `deeplabcut-webapp-docker/tests/test_canonical_analysis_file.py`, `deeplabcut-webapp-docker/tests/test_inline_analysis_worker.py`, `deeplabcut-webapp-docker/tests/test_inline_analysis_routes.py`

**Interfaces:**
- Consumes: `canonical.canonical_h5_path`, `canonical.build_empty_dense_df`, `_resolve_h5_path`, `_ia_pd` (pandas), test helpers `_df_with_index`, `_stub_create_df`, `_run_range_kw`, `ia_client`.
- Produces: `canonical.labeled_frames(df) -> set[int]`; `_filter_skip_already_done(target, existing_df, overwrite=False, analyzed_labeled=None, ignore_analyzed=False)`; the enqueued payload gains `"ignore_analyzed": bool`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_canonical_analysis_file.py`, append:

```python
def test_labeled_frames_finite_x_included():
    df = canonical.build_empty_dense_df("S", ["nose", "tail"], 4)  # all NaN
    df.loc[1, ("S", "nose", "x")] = 5.0   # frame 1 finalized (finite x)
    df.loc[3, ("S", "tail", "x")] = 9.0   # frame 3 finalized via a different bodypart
    assert canonical.labeled_frames(df) == {1, 3}

def test_labeled_frames_all_nan_excluded():
    df = canonical.build_empty_dense_df("S", ["nose"], 3)  # all NaN
    assert canonical.labeled_frames(df) == set()

def test_labeled_frames_none_or_empty():
    assert canonical.labeled_frames(None) == set()
    assert canonical.labeled_frames(canonical.build_empty_dense_df("S", ["nose"], 0)) == set()

def test_labeled_frames_ignores_likelihood_only():
    # presence keys on x, not likelihood — a finite likelihood with NaN x is NOT labeled
    df = canonical.build_empty_dense_df("S", ["nose"], 2)
    df.loc[0, ("S", "nose", "likelihood")] = 0.9
    assert canonical.labeled_frames(df) == set()
```

In `tests/test_inline_analysis_worker.py`, add to `class TestFilterSkipAlreadyDone`:

```python
    def test_ignore_analyzed_wins_over_overwrite(self):
        # overwrite would re-run everything, but finalized frames stay skipped
        result = dlc_tasks._filter_skip_already_done(
            [100, 101, 102], existing_df=None, overwrite=True,
            analyzed_labeled={101}, ignore_analyzed=True)
        assert result == [100, 102]

    def test_ignore_analyzed_plus_existing_skip(self):
        df = _df_with_index([100])  # frame 100 already predicted (finite)
        result = dlc_tasks._filter_skip_already_done(
            [100, 101, 102], existing_df=df, overwrite=False,
            analyzed_labeled={101}, ignore_analyzed=True)
        assert result == [102]      # 100 already-done, 101 finalized, 102 analyze

    def test_ignore_flag_off_does_not_protect(self):
        result = dlc_tasks._filter_skip_already_done(
            [100, 101, 102], existing_df=None, overwrite=True,
            analyzed_labeled={101}, ignore_analyzed=False)
        assert result == [100, 101, 102]

    def test_ignore_analyzed_empty_set_is_noop(self):
        result = dlc_tasks._filter_skip_already_done(
            [100, 101], existing_df=None, overwrite=True,
            analyzed_labeled=set(), ignore_analyzed=True)
        assert result == [100, 101]
```

In `tests/test_inline_analysis_worker.py`, add to `class TestRunRange`:

```python
    def test_run_range_ignore_analyzed_protects_finalized_under_overwrite(self, tmp_path):
        video_path = tmp_path / "v.mp4"
        video_path.write_bytes(b"")
        runner = MagicMock()
        # per-scorer h5: all three target frames already predicted (finite)
        scorer_seed = _df_with_index([100, 101, 102])
        # _analyzed h5: only frame 101 finalized (100 and 102 all-NaN)
        analyzed_seed = _df_with_index([100, 101, 102], all_nan_rows={100, 102})
        h5_path = dlc_tasks._resolve_h5_path(str(video_path), "scorer")
        h5_path.write_bytes(b"placeholder")
        an_path = dlc_tasks_canonical_path(str(video_path))
        an_path.write_bytes(b"placeholder")

        def _read_router(path, *a, **k):
            return analyzed_seed if str(path).endswith("_analyzed.h5") else scorer_seed

        analyzed_indices = []

        def fake_video_inference(vit, pose_runner):
            frames = list(vit)
            analyzed_indices.extend(frames)
            return [{} for _ in frames]

        with _mock_to_hdf_writes_bytes(), \
             patch("pandas.read_hdf", side_effect=_read_router), \
             patch.object(dlc_tasks, "video_inference", fake_video_inference), \
             patch.object(dlc_tasks, "_dlc_create_df_from_prediction", _stub_create_df), \
             patch.object(dlc_tasks, "_RangeVideoIterator",
                          lambda p, indices: iter(list(indices))):
            req = {
                "req_id": "r1", "video_path": str(video_path),
                "start_frame": 100, "n_frames": 3, "batch_size": 8,
                "save_as_csv": False, "snapshot_path": "snap.pt",
                "overwrite": True, "ignore_analyzed": True,
            }
            n_analyzed, n_skipped = dlc_tasks._run_range(
                runner, req=req, **_run_range_kw(scorer="scorer")
            )
        # frame 101 is finalized in _analyzed → protected even though overwrite=True
        assert n_analyzed == 2
        assert n_skipped == 1
        assert 101 not in analyzed_indices
        assert sorted(analyzed_indices) == [100, 102]
```

Add this helper near the top of `tests/test_inline_analysis_worker.py` (below the existing helpers, e.g. after `_df_with_index`):

```python
def dlc_tasks_canonical_path(video_path):
    """<stem>_analyzed.h5 next to the video — matches canonical.canonical_h5_path."""
    from pathlib import Path as _P
    p = _P(video_path)
    return p.with_name(p.stem + "_analyzed.h5")
```

In `tests/test_inline_analysis_routes.py`, add to `class TestRangeSubmit`:

```python
    def test_ignore_analyzed_flows_into_payload(self, ia_client):
        client, _app, redis, project = ia_client
        v = project / "videos" / "ign.mp4"
        v.parent.mkdir(parents=True, exist_ok=True)
        v.write_bytes(b"")
        resp = client.post("/dlc/project/inline-analysis/range", json={
            "snap_key": "k1", "video_path": str(v),
            "start_frame": 0, "n_frames": 5, "batch_size": 8, "ignore_analyzed": True,
        })
        assert resp.status_code == 202, resp.get_json()
        payload = json.loads(redis._lists.get("inline:queue:u1:k1", [])[0])
        assert payload["ignore_analyzed"] is True

    def test_ignore_analyzed_defaults_false(self, ia_client):
        client, _app, redis, project = ia_client
        v = project / "videos" / "ign2.mp4"
        v.parent.mkdir(parents=True, exist_ok=True)
        v.write_bytes(b"")
        resp = client.post("/dlc/project/inline-analysis/range", json={
            "snap_key": "k1", "video_path": str(v),
            "start_frame": 0, "n_frames": 5, "batch_size": 8,
        })
        assert resp.status_code == 202, resp.get_json()
        payload = json.loads(redis._lists.get("inline:queue:u1:k1", [])[0])
        assert payload["ignore_analyzed"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```
python -m pytest tests/test_canonical_analysis_file.py -q -k labeled_frames
python -m pytest "tests/test_inline_analysis_worker.py::TestFilterSkipAlreadyDone" "tests/test_inline_analysis_worker.py::TestRunRange::test_run_range_ignore_analyzed_protects_finalized_under_overwrite" "tests/test_inline_analysis_routes.py::TestRangeSubmit" -q
```
Expected: FAIL — `labeled_frames` missing (AttributeError); `_filter_skip_already_done` rejects the new kwargs (TypeError); `payload["ignore_analyzed"]` KeyError.

- [ ] **Step 3a: Add `labeled_frames` to canonical.py**

In `src/dlc/canonical.py`, after `canonical_csv_path` (line 28):

```python
def labeled_frames(analyzed_df) -> set:
    """Frame indices 'marked' in the _analyzed coverage timeline: any bodypart
    with a finite x (presence mode; mirrors viewer._coverage_buckets). Used by the
    range worker to skip frames finalized in <stem>_analyzed.h5."""
    if analyzed_df is None or not len(analyzed_df):
        return set()
    x = analyzed_df.xs("x", level="coords", axis=1)
    return set(analyzed_df.index[x.notna().any(axis=1)].tolist())
```

- [ ] **Step 3b: Extend `_filter_skip_already_done`**

In `src/dlc/tasks.py`, replace the function (lines ~2783-2798):

```python
def _filter_skip_already_done(target_frames, existing_df, overwrite=False,
                              analyzed_labeled=None, ignore_analyzed=False):
    """Return the subset of target_frames that need re-analysis.

    A frame needs re-analysis if it's missing from existing_df or if every value
    in its row is NaN (matches DLC's dynamic-cropping semantics). overwrite=True
    re-analyzes every frame regardless of existing data. ignore_analyzed=True
    (with analyzed_labeled = frames finalized in <stem>_analyzed.h5) excludes
    those finalized frames with HIGHER PRIORITY than overwrite — a finalized frame
    is never re-analyzed while ignore_analyzed is set.
    """
    labeled = analyzed_labeled if (ignore_analyzed and analyzed_labeled) else set()
    if overwrite:
        return [f for f in target_frames if f not in labeled]
    have = existing_df.index if existing_df is not None else []
    return [
        f for f in target_frames
        if f not in labeled
        and (existing_df is None or f not in have or existing_df.loc[f].isna().all())
    ]
```

- [ ] **Step 3c: Read `_analyzed` + pass the new args in `_run_range`**

In `src/dlc/tasks.py`, replace the `target`/`to_analyze` block (lines ~3038-3039):

```python
    target     = list(range(req["start_frame"], req["start_frame"] + req["n_frames"]))
    ignore_analyzed = req.get("ignore_analyzed", False)
    analyzed_labeled = None
    if ignore_analyzed:
        from dlc import canonical
        an_path = canonical.canonical_h5_path(req["video_path"])
        if an_path.exists():
            analyzed_labeled = canonical.labeled_frames(_ia_pd.read_hdf(str(an_path)))
    to_analyze = _filter_skip_already_done(
        target, existing, req.get("overwrite", False),
        analyzed_labeled=analyzed_labeled, ignore_analyzed=ignore_analyzed,
    )
```

- [ ] **Step 3d: Add `ignore_analyzed` to the payload in `range_submit`**

In `src/dlc/inline_analysis.py`, add after the `overwrite` line (line 283):

```python
        "overwrite":     bool(body.get("overwrite", False)),
        "ignore_analyzed": bool(body.get("ignore_analyzed", False)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```
python -m pytest tests/test_canonical_analysis_file.py tests/test_inline_analysis_worker.py tests/test_inline_analysis_routes.py -q
```
Expected: PASS for the new tests; pre-existing failures (`TestRangeVideoIterator::test_non_contiguous_skip_list_preserves_order`, `TestSessionStart::test_dispatches_celery_task_with_snap_key`) and teardown "Working outside of request context" errors are unchanged environmental noise — do NOT attribute them to this change. Confirm your new tests are green and the pass count rose.

- [ ] **Step 5: Commit**

```bash
git add src/dlc/canonical.py src/dlc/tasks.py src/dlc/inline_analysis.py \
  tests/test_canonical_analysis_file.py tests/test_inline_analysis_worker.py tests/test_inline_analysis_routes.py
git commit -m "feat(inline-analysis): ignore_analyzed skips frames finalized in _analyzed

New ignore_analyzed flag (route->payload->worker) excludes frames marked in
<stem>_analyzed.h5 (finite-x presence rule, via canonical.labeled_frames), with
priority over overwrite. Read only when the flag is set.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Frontend — `ignore frames in _analyzed` checkbox + wiring

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_inline_analysis_3d.html` (`.ia3d-tag-batch`)
- Modify: `dlc-3D/src/static/inline_analysis_3d.js` (`_submitRange`, `_onAnalyzeTagClick`)
- Test: `dlc-3D/tests/test_inline_3d_ignore_analyzed.py` (create)

**Interfaces:**
- Consumes: `.ia3d-tag-batch`, `#ia3d-override-labels`, the `_onAnalyzeTagClick` batch loop.
- Produces: `#ia3d-ignore-analyzed` checkbox (checked); `_submitRange(sk, videoPath, startFrame, nFrames, overwrite = false, ignoreAnalyzed = false)` forwards `ignore_analyzed`.

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/test_inline_3d_ignore_analyzed.py`:

```python
"""Static guards for the "ignore frames in _analyzed" control on the Analyze-for-tag
batch. See docs/superpowers/specs/2026-07-16-inline-3d-analyze-for-tag-ignore-analyzed-design.md.
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


def test_ignore_checkbox_in_tag_batch_checked_and_enabled():
    html = CARD.read_text()
    batch = _idx(html, 'class="ia3d-tag-batch"')
    after = _idx(html, 'id="ia3d-add-frame-nomarkers-btn"')
    i = _idx(html, 'id="ia3d-ignore-analyzed"')
    assert batch < i < after, "ignore checkbox must live inside .ia3d-tag-batch"
    start = html.rindex("<input", 0, i)
    tag = html[start:html.index(">", start)]
    assert 'type="checkbox"' in tag, "ignore control must be a checkbox"
    assert "checked" in tag, "ignore checkbox must be CHECKED by default"
    assert "disabled" not in tag, "ignore checkbox must be enabled"


def test_submitRange_forwards_ignore_analyzed():
    js = JS.read_text()
    assert re.search(
        r"async function _submitRange\(sk, videoPath, startFrame, nFrames, overwrite = false, ignoreAnalyzed = false\)", js), \
        "_submitRange must take an ignoreAnalyzed param defaulting to false"
    assert re.search(r"ignore_analyzed:\s*!!ignoreAnalyzed", js), "_submitRange body must send ignore_analyzed"


def test_onAnalyzeTag_reads_and_passes_ignore_analyzed():
    js = JS.read_text()
    assert re.search(r'\$\("ia3d-ignore-analyzed"\)\?\.checked', js), \
        "_onAnalyzeTagClick must read the ignore-analyzed checkbox"
    assert re.search(r"_submitRange\(sk, cam0, r\.start, r\.n, overwrite, ignoreAnalyzed\)", js), \
        "cam0 submit must pass ignoreAnalyzed"
    assert re.search(r"_submitRange\(sk, _siblingPath, r\.start, r\.n, overwrite, ignoreAnalyzed\)", js), \
        "sibling submit must pass ignoreAnalyzed"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `dlc-3D/`): `python -m pytest tests/test_inline_3d_ignore_analyzed.py -q`
Expected: FAIL — `#ia3d-ignore-analyzed` absent; `_submitRange` lacks the param.

- [ ] **Step 3a: Add the checkbox to the template**

In `dlc-3D/src/templates/partials/card_inline_analysis_3d.html`, insert inside `.ia3d-tag-batch`, immediately after the `override existing labels` label's closing `</label>` and before the `#ia3d-btn-analyze-tag` button:

```html
                override existing labels
              </label>
              <label class="ia3d-tag-lock-label" title="When ON (default), skip frames already finalized in the _analyzed timeline — even if 'override existing labels' is on. Protects human-curated frames.">
                <input type="checkbox" id="ia3d-ignore-analyzed" checked style="accent-color:var(--accent);width:14px;height:14px"/>
                ignore frames in _analyzed
              </label>
              <button id="ia3d-btn-analyze-tag" class="btn-sm btn-create" disabled
```

- [ ] **Step 3b: Forward `ignoreAnalyzed` from `_submitRange`**

In `dlc-3D/src/static/inline_analysis_3d.js`, change the `_submitRange` signature:

```javascript
async function _submitRange(sk, videoPath, startFrame, nFrames, overwrite = false, ignoreAnalyzed = false) {
```

and add `ignore_analyzed` to the JSON body, right after the `overwrite: !!overwrite,` line:

```javascript
      overwrite: !!overwrite,
      ignore_analyzed: !!ignoreAnalyzed,
    }),
```

- [ ] **Step 3c: Read the checkbox, pass it, and refine the warning in `_onAnalyzeTagClick`**

In `dlc-3D/src/static/inline_analysis_3d.js`, add the read right after the existing `const overwrite = ...` line:

```javascript
  const overwrite = !!$("ia3d-override-labels")?.checked;
  const ignoreAnalyzed = !!$("ia3d-ignore-analyzed")?.checked;
```

Replace the confirm block so the override warning reflects `_analyzed` protection:

```javascript
  const ok = window.confirm(
    `Analyze note tag "${tagValue}":\n` +
    `${frames.length} tagged frame(s) → ${ranges.length} range(s) → ${totalFrames} frames × 2 cameras.` +
    (overwrite
      ? `\n\n⚠️ Override is ON: this will OVERWRITE existing predictions AND human corrections` +
        (ignoreAnalyzed ? ` (except frames already finalized in _analyzed, which stay protected).` : `.`)
      : ``) +
    `\n\nProceed?`
  );
```

Pass `ignoreAnalyzed` to both submits in the batch loop:

```javascript
    const [q0, q1] = await Promise.all([
      _submitRange(sk, cam0, r.start, r.n, overwrite, ignoreAnalyzed),
      _submitRange(sk, _siblingPath, r.start, r.n, overwrite, ignoreAnalyzed),
    ]);
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `dlc-3D/`): `python -m pytest tests/test_inline_3d_ignore_analyzed.py -q`
Expected: PASS (3 tests).

Regression (must stay green): `python -m pytest tests/test_inline_3d_override_labels.py tests/test_inline_3d_analyze_for_tag_wiring.py -q && node --test tests/unit/*.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html src/static/inline_analysis_3d.js tests/test_inline_3d_ignore_analyzed.py
git commit -m "feat(inline-3d): 'ignore frames in _analyzed' checkbox on Analyze-for-tag

Checked by default; the batch forwards ignore_analyzed to every range submit and
the override warning notes finalized frames stay protected.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Frontend e2e — checkbox present + checked by default

**Files:**
- Test: `dlc-3D/tests/e2e/test_inline_3d_ignore_analyzed.py` (create)

**Interfaces:**
- Consumes: the shared e2e conftest `page`/`base_url` fixtures + the card-open pattern from `tests/e2e/test_inline_3d_override_labels.py`.

**Note:** Read-only — never triggers analysis. Requires the running stack AND `docker restart deeplabcut-webapp-docker-dlc-3d-1` so the container serves the new markup.

- [ ] **Step 1: Write the test**

Create `dlc-3D/tests/e2e/test_inline_3d_ignore_analyzed.py`:

```python
"""Live read-only check for the "ignore frames in _analyzed" checkbox on the
Analyze-for-tag batch: present and CHECKED by default. NEVER triggers analysis.
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


def test_ignore_analyzed_checkbox_present(page: Page):
    expect(page.locator("#ia3d-ignore-analyzed")).to_be_visible()


def test_ignore_analyzed_checked_by_default(page: Page):
    assert page.locator("#ia3d-ignore-analyzed").is_checked() is True
```

- [ ] **Step 2: Run the test**

Run (from `dlc-3D/`, after `docker restart deeplabcut-webapp-docker-dlc-3d-1`): `python -m pytest tests/e2e/test_inline_3d_ignore_analyzed.py -q`
Expected: PASS (2 tests). If the stack isn't running here, note it and run where available.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_inline_3d_ignore_analyzed.py
git commit -m "test(inline-3d): e2e presence + checked-default for ignore-analyzed checkbox

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Backend (from `deeplabcut-webapp-docker/`):

```bash
python -m pytest tests/test_canonical_analysis_file.py tests/test_inline_analysis_worker.py tests/test_inline_analysis_routes.py -q
```

- [ ] Frontend (from `dlc-3D/`):

```bash
python -m pytest tests/test_inline_3d_ignore_analyzed.py tests/test_inline_3d_override_labels.py tests/test_inline_3d_analyze_for_tag_wiring.py -q
node --test tests/unit/*.mjs
docker restart deeplabcut-webapp-docker-dlc-3d-1
python -m pytest tests/e2e/test_inline_3d_ignore_analyzed.py -q
```

Expected: new tests PASS; only the documented pre-existing backend failures/teardown-noise remain.

- [ ] Manual smoke (running app, a video with a finalized `_analyzed` range + note tags): activate one note tag → Lock tag → check "override existing labels", leave "ignore frames in _analyzed" checked → Analyze for tag → confirm the ⚠️ line says finalized frames stay protected → run against a non-protected project and verify the finalized range was NOT overwritten (its finalized frames were skipped) while other window frames were re-analyzed. Then uncheck "ignore frames in _analyzed" + keep override → confirm the finalized frames get overwritten.

## Self-Review notes

- **Spec coverage:** `labeled_frames` finite-x rule → Task 1 (canonical + tests); priority over overwrite → Task 1 (`_filter_skip_already_done` + truth-table tests + `_run_range` test); read `_analyzed` only when flag set → Task 1 (Step 3c); payload flow + default false → Task 1 (route tests); checkbox checked-by-default + scoped to tag batch → Task 2 (`_submitRange` default false keeps other buttons unchanged); confirm-warning refinement → Task 2 (Step 3c); e2e checked-default → Task 3; edge cases (no `_analyzed`, flag off, empty set) → Task 1 filter tests.
- **Type consistency:** `ignore_analyzed` is a bool across the seam — JS `!!ignoreAnalyzed` → route `bool(body.get("ignore_analyzed", False))` → worker `req.get("ignore_analyzed", False)`. `labeled_frames` returns a `set`; `_filter_skip_already_done`'s `analyzed_labeled` is that set (or None). `_submitRange`'s new 6th arg is optional; the two existing callers pass neither new arg and are unaffected.
