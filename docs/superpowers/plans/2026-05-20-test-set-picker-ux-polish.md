# Test-set Picker UX Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three small UX improvements to the Test-set Picker: (1) auto-populated splits dropdown for the inspect dialog, (2) shared color palette so picker dots match the Frame Labeler, (3) per-folder `marked/total` counter in the picker's labeled-frames dropdown.

**Architecture:** One new backend route lists every available split on disk (mirrors the labeler's snapshot picker). Frontend swaps two number inputs for a `<select>` populated from that route. The shared overlay JS module gains an exported `DEFAULT_PALETTE` constant the picker now imports. Stem-dropdown options get a `xx/yy` suffix wired from the existing per-folder counts response.

**Tech Stack:** Python 3 / Flask / vanilla ES modules / pytest. All work on top of `feat/test-set-picker` (currently published to origin) in the main webapp repo.

**Reference spec:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports/docs/superpowers/specs/2026-05-20-test-set-picker-ux-polish-design.md`.

**Two repositories are involved:**
- Spec + plan (already committed) live in `/home/sam/docker-images/deeplabcut-webapp-docker-supports/`. **No code is added there.**
- All implementation code lives in `/home/sam/docker-images/deeplabcut-webapp-docker/`. All `git` commands in this plan run there unless explicitly stated.

---

## Task 0: Branch hygiene + baseline

**Files:**
- None modified — branch + baseline confirmation only.

- [ ] **Step 1: Confirm branch state**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git fetch origin
git checkout feat/test-set-picker
git status
git log --oneline -5
```

Expected: on branch `feat/test-set-picker`, clean working tree, HEAD shows the most recent picker-related commits. If anything is dirty, surface it and stop.

- [ ] **Step 2: Confirm test baseline is green**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_marks_store.py tests/test_test_set_split.py tests/test_test_set_picker_routes.py tests/test_test_set_picker_inspect.py tests/test_dlc_create_training_dataset_split_modes.py tests/test_dlc_training_routes.py tests/test_frame_overlay_module_exists.py tests/test_test_set_picker_ui_presence.py -q
```

Expected: all green. If any tests fail, stop and surface before continuing — every later task assumes this baseline.

- [ ] **Step 3: Confirm disk is healthy and cleanup hooks are in place**

```bash
df -h /tmp | tail -1
grep -c "pytest_sessionfinish\|atexit.register" /home/sam/docker-images/deeplabcut-webapp-docker/src/tests/conftest.py
```

Expected: at least a few GB free on `/`; grep returns `2` (atexit register + pytest_sessionfinish hook). If either guard is missing, restore it from commit `c4fe949` before continuing — those guards prevent disk-fill from repeated test runs.

---

## Task 1: Backend — `GET /dlc/project/training-dataset/splits` endpoint

**Files:**
- Modify: `src/dlc/test_set_picker.py` (append the new route + helper)
- Test: `src/tests/test_test_set_picker_splits_route.py` (new)

The existing `_DOC_PICKLE_RE` and `_active_project()` helpers in
`test_set_picker.py` are reused. No other backend code changes.

- [ ] **Step 1: Write the failing tests**

Create `src/tests/test_test_set_picker_splits_route.py`:

```python
"""Tests for GET /dlc/project/training-dataset/splits — auto-populated splits list."""
from __future__ import annotations
import json
import pickle
from pathlib import Path

import numpy as np
import pytest


def _write_doc_pickle(folder: Path, scorer: str, train_pct: int, shuffle: int,
                      train_idx: list[int], test_idx: list[int]) -> Path:
    """Minimal Documentation_data-*.pickle (payload[0] left empty — only the
    filename is parsed by the splits endpoint)."""
    folder.mkdir(parents=True, exist_ok=True)
    payload = [
        [],
        np.array(train_idx, dtype=np.int64),
        np.array(test_idx, dtype=np.int64),
        train_pct / 100.0,
    ]
    out = folder / f"Documentation_data-{scorer}_{train_pct}shuffle{shuffle}.pickle"
    with open(out, "wb") as f:
        pickle.dump(payload, f)
    return out


def _client(flask_test_client):
    return flask_test_client[0]


def _redis(flask_test_client):
    return flask_test_client[2]


def _activate(client, fake_redis, project_path: Path):
    with client.session_transaction() as sess:
        sess["uid"] = "test-uid"
    fake_redis.set(
        "webapp:dlc_project:test-uid",
        json.dumps({
            "project_path": str(project_path),
            "config_path": str(project_path / "config.yaml"),
            "engine": "pytorch",
        }),
    )


@pytest.fixture
def splits_project(tmp_path):
    proj = tmp_path / "SplitsTest-2026-05-20"
    proj.mkdir()
    (proj / "config.yaml").write_text(
        "scorer: T\nproject_path: " + str(proj) + "\niteration: 0\n"
    )
    return proj


def test_splits_empty_project(flask_test_client, splits_project):
    client = _client(flask_test_client)
    fake_redis = _redis(flask_test_client)
    _activate(client, fake_redis, splits_project)
    rv = client.get("/dlc/project/training-dataset/splits")
    assert rv.status_code == 200
    assert rv.get_json() == {"splits": []}


def test_splits_single_iteration_single_shuffle(flask_test_client, splits_project):
    _write_doc_pickle(
        splits_project / "training-datasets" / "iteration-0" / "UnaugmentedDataSet_T0",
        scorer="T", train_pct=80, shuffle=1, train_idx=[0, 1], test_idx=[2],
    )
    client = _client(flask_test_client)
    fake_redis = _redis(flask_test_client)
    _activate(client, fake_redis, splits_project)
    rv = client.get("/dlc/project/training-dataset/splits")
    body = rv.get_json()
    assert rv.status_code == 200
    assert len(body["splits"]) == 1
    s = body["splits"][0]
    assert s["iteration"] == 0
    assert s["shuffle"] == 1
    assert s["train_fraction"] == 0.8
    assert s["pickle"].startswith("Documentation_data-")
    assert s["label"] == "iteration-0 • shuffle-1 • trainset 80%"


def test_splits_sorted_iteration_desc_shuffle_asc(flask_test_client, splits_project):
    # Two iterations, multiple shuffles, written out of order to verify sorting
    _write_doc_pickle(
        splits_project / "training-datasets" / "iteration-1" / "UnaugmentedDataSet_T0",
        scorer="T", train_pct=80, shuffle=2, train_idx=[0], test_idx=[1],
    )
    _write_doc_pickle(
        splits_project / "training-datasets" / "iteration-0" / "UnaugmentedDataSet_T0",
        scorer="T", train_pct=70, shuffle=1, train_idx=[0], test_idx=[1],
    )
    _write_doc_pickle(
        splits_project / "training-datasets" / "iteration-1" / "UnaugmentedDataSet_T0",
        scorer="T", train_pct=80, shuffle=1, train_idx=[0], test_idx=[1],
    )
    _write_doc_pickle(
        splits_project / "training-datasets" / "iteration-0" / "UnaugmentedDataSet_T0",
        scorer="T", train_pct=70, shuffle=2, train_idx=[0], test_idx=[1],
    )
    client = _client(flask_test_client)
    fake_redis = _redis(flask_test_client)
    _activate(client, fake_redis, splits_project)
    rv = client.get("/dlc/project/training-dataset/splits")
    body = rv.get_json()
    pairs = [(s["iteration"], s["shuffle"]) for s in body["splits"]]
    # Iteration DESC, shuffle ASC within iteration
    assert pairs == [(1, 1), (1, 2), (0, 1), (0, 2)]


def test_splits_skip_malformed_filenames(flask_test_client, splits_project):
    folder = splits_project / "training-datasets" / "iteration-0" / "UnaugmentedDataSet_T0"
    folder.mkdir(parents=True)
    # Valid one
    _write_doc_pickle(folder, scorer="T", train_pct=80, shuffle=1,
                      train_idx=[0], test_idx=[1])
    # Decoy filenames that should NOT show up
    (folder / "Documentation_data-wrong_format.pickle").write_bytes(b"junk")
    (folder / "not-a-doc.pickle").write_bytes(b"junk")
    (folder / "Documentation_data-T_80shuffle1.txt").write_text("nope")
    client = _client(flask_test_client)
    fake_redis = _redis(flask_test_client)
    _activate(client, fake_redis, splits_project)
    rv = client.get("/dlc/project/training-dataset/splits")
    body = rv.get_json()
    assert len(body["splits"]) == 1
    assert body["splits"][0]["pickle"].endswith("_80shuffle1.pickle")


def test_splits_no_active_project_returns_400(flask_test_client):
    client = _client(flask_test_client)
    rv = client.get("/dlc/project/training-dataset/splits")
    assert rv.status_code == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_splits_route.py -q
```

Expected: all 5 tests fail (the route doesn't exist yet — 404 on the GET).

- [ ] **Step 3: Append the route to the blueprint**

Open `src/dlc/test_set_picker.py`. Append to the end of the file (do NOT replace existing content; this is purely additive):

```python
# ── List available frozen splits (for inspect dropdown) ───────────────────────

_ITER_FOLDER_RE = _re.compile(r"^iteration-(\d+)$")


@bp.route("/dlc/project/training-dataset/splits", methods=["GET"])
def get_splits():
    """List every Documentation_data-*.pickle on disk so the inspect UI can
    populate its dropdown without users guessing iteration/shuffle numbers.

    Returns: {"splits": [{iteration, shuffle, train_fraction, pickle, label}, ...]}
    sorted by (iteration DESC, shuffle ASC).
    """
    project_path, err = _active_project()
    if err:
        return err

    ts_root = project_path / "training-datasets"
    if not ts_root.is_dir():
        return jsonify({"splits": []})

    splits: list[dict] = []
    for iter_dir in ts_root.iterdir():
        if not iter_dir.is_dir():
            continue
        iter_match = _ITER_FOLDER_RE.match(iter_dir.name)
        if not iter_match:
            continue
        iteration = int(iter_match.group(1))
        for pickle_path in iter_dir.glob("UnaugmentedDataSet_*/Documentation_data-*.pickle"):
            m = _DOC_PICKLE_RE.match(pickle_path.name)
            if not m:
                continue
            try:
                train_pct = int(m.group("frac"))
                shuffle = int(m.group("shuffle"))
            except (TypeError, ValueError):
                continue
            train_fraction = train_pct / 100.0
            splits.append({
                "iteration": iteration,
                "shuffle": shuffle,
                "train_fraction": train_fraction,
                "pickle": pickle_path.name,
                "label": f"iteration-{iteration} • shuffle-{shuffle} • trainset {train_pct}%",
            })

    splits.sort(key=lambda s: (-s["iteration"], s["shuffle"]))
    return jsonify({"splits": splits})
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_splits_route.py -q
```

Expected: 5 tests pass.

- [ ] **Step 5: Regression check — neighboring routes still green**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_routes.py tests/test_test_set_picker_inspect.py -q
```

Expected: all green. No previously-green test may regress.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/test_set_picker.py src/tests/test_test_set_picker_splits_route.py
git commit -m "feat(dlc): add /dlc/project/training-dataset/splits endpoint

Returns every Documentation_data-*.pickle on disk so the inspect UI
can populate a dropdown instead of asking users to type iteration +
shuffle numbers. Sorted (iteration DESC, shuffle ASC). Reuses the
existing _DOC_PICKLE_RE for shuffle/train-percent parsing."
```

---

## Task 2: Frontend — share DEFAULT_PALETTE from frame_overlay.js

**Files:**
- Modify: `src/static/js/frame_overlay.js`
- Modify: `src/static/js/test_set_picker.js`
- Test: `src/tests/test_test_set_picker_ui_presence.py`

The labeler keeps its private `FL_COLORS` array unchanged (it's
intertwined with already-merged lock-BP work and not worth touching).
The new shared `DEFAULT_PALETTE` is identical in value; the picker
imports it.

- [ ] **Step 1: Write the failing presence tests**

Append to `src/tests/test_test_set_picker_ui_presence.py`:

```python


def test_frame_overlay_exports_default_palette():
    text = (SRC / "static" / "js" / "frame_overlay.js").read_text()
    assert "export const DEFAULT_PALETTE" in text, (
        "frame_overlay.js should export a DEFAULT_PALETTE shared with the picker"
    )
    # Palette is napari-inspired; cross-check a few canonical entries
    for hex_color in ("#f87171", "#fb923c", "#fbbf24"):
        assert hex_color in text, f"missing {hex_color} from DEFAULT_PALETTE"


def test_picker_js_imports_default_palette():
    text = (SRC / "static" / "js" / "test_set_picker.js").read_text()
    assert "DEFAULT_PALETTE" in text, (
        "test_set_picker.js should import DEFAULT_PALETTE from frame_overlay.js"
    )
    # And should NOT keep the old TS_DEFAULT_PALETTE local array
    assert "TS_DEFAULT_PALETTE" not in text, (
        "TS_DEFAULT_PALETTE local array should have been removed in favor of "
        "the shared DEFAULT_PALETTE"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py::test_frame_overlay_exports_default_palette tests/test_test_set_picker_ui_presence.py::test_picker_js_imports_default_palette -q
```

Expected: both fail (`DEFAULT_PALETTE` not exported; `TS_DEFAULT_PALETTE` still present).

- [ ] **Step 3: Add the exported palette to frame_overlay.js**

Edit `src/static/js/frame_overlay.js`. Find the JSDoc comment at the top
that ends with `*/`. After the `*/` and BEFORE the first `export function`,
insert:

```javascript
/**
 * Canonical napari-inspired bodypart color palette.
 * The Frame Labeler defines its own private FL_COLORS array with identical
 * values; if either changes, the picker is the canonical consumer of this
 * constant.
 */
export const DEFAULT_PALETTE = [
    "#f87171", "#fb923c", "#fbbf24", "#a3e635", "#34d399",
    "#22d3ee", "#818cf8", "#e879f9", "#f43f5e", "#10b981",
    "#3b82f6", "#ec4899", "#f59e0b", "#84cc16", "#06b6d4",
];

```

- [ ] **Step 4: Replace TS_DEFAULT_PALETTE in test_set_picker.js**

Edit `src/static/js/test_set_picker.js`.

First, change the import line at the top. Find:

```javascript
import { drawFrame, drawBodyparts } from "./frame_overlay.js";
```

Replace with:

```javascript
import { drawFrame, drawBodyparts, DEFAULT_PALETTE } from "./frame_overlay.js";
```

Then find the local palette definition and helper (around line 41):

```javascript
const TS_DEFAULT_PALETTE = [
  "#ff5050", "#50c8ff", "#a0e040", "#ffa040", "#c060ff",
  "#40e0c0", "#ff7090", "#80c080", "#f0c020", "#60a0ff",
];

function _buildPalette(bps) {
  const out = {};
  bps.forEach((bp, i) => { out[bp] = TS_DEFAULT_PALETTE[i % TS_DEFAULT_PALETTE.length]; });
  return out;
}
```

Replace with:

```javascript
function _buildPalette(bps) {
  const out = {};
  bps.forEach((bp, i) => { out[bp] = DEFAULT_PALETTE[i % DEFAULT_PALETTE.length]; });
  return out;
}
```

(The `TS_DEFAULT_PALETTE` constant goes away; `_buildPalette` now reads
from the imported `DEFAULT_PALETTE`.)

- [ ] **Step 5: Run the new tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py::test_frame_overlay_exports_default_palette tests/test_test_set_picker_ui_presence.py::test_picker_js_imports_default_palette -q
```

Expected: both pass.

- [ ] **Step 6: Regression check**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_frame_overlay_module_exists.py tests/test_test_set_picker_ui_presence.py -q
```

Expected: all green. `frame_labeler.js` is intentionally untouched in
this task — confirm:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git diff HEAD -- src/static/js/frame_labeler.js | wc -l
```

Expected: `0`.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/frame_overlay.js src/static/js/test_set_picker.js src/tests/test_test_set_picker_ui_presence.py
git commit -m "feat(static): share DEFAULT_PALETTE so picker matches labeler colors

frame_overlay.js now exports DEFAULT_PALETTE (15 napari-inspired
colors identical to the labeler's private FL_COLORS). test_set_picker.js
drops its 10-color TS_DEFAULT_PALETTE in favor of the shared import,
so the same bodypart now renders the same hue in both views."
```

---

## Task 3: Frontend — inspect dialog becomes a dropdown

**Files:**
- Modify: `src/templates/partials/card_test_set_picker.html`
- Modify: `src/static/js/test_set_picker.js`
- Test: `src/tests/test_test_set_picker_ui_presence.py`

- [ ] **Step 1: Write the failing presence tests**

Append to `src/tests/test_test_set_picker_ui_presence.py`:

```python


def test_inspect_dialog_uses_dropdown():
    text = (SRC / "templates" / "partials" / "card_test_set_picker.html").read_text()
    # New IDs
    assert 'id="ts-inspect-select"' in text, (
        "inspect dialog should have a ts-inspect-select dropdown"
    )
    assert 'id="ts-inspect-refresh"' in text, (
        "inspect dialog should have a ts-inspect-refresh button"
    )
    # Old IDs gone
    assert 'id="ts-inspect-iter"' not in text, (
        "inspect dialog should no longer use ts-inspect-iter number input"
    )
    assert 'id="ts-inspect-shuffle"' not in text, (
        "inspect dialog should no longer use ts-inspect-shuffle number input"
    )


def test_picker_js_calls_splits_endpoint():
    text = (SRC / "static" / "js" / "test_set_picker.js").read_text()
    assert "/dlc/project/training-dataset/splits" in text, (
        "test_set_picker.js should fetch /dlc/project/training-dataset/splits "
        "to populate the inspect dropdown"
    )
    assert "_loadInspectSplits" in text, (
        "picker JS should have a _loadInspectSplits helper"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py::test_inspect_dialog_uses_dropdown tests/test_test_set_picker_ui_presence.py::test_picker_js_calls_splits_endpoint -q
```

Expected: both fail.

- [ ] **Step 3: Replace the inspect dialog inputs with a dropdown**

Edit `src/templates/partials/card_test_set_picker.html`. Find the existing
inspect dialog's two `<div class="scorer-row">` rows containing
`ts-inspect-iter` and `ts-inspect-shuffle`. They look like this:

```html
          <div class="scorer-row" style="margin-bottom:.55rem">
            <label for="ts-inspect-iter">Iteration</label>
            <input type="number" id="ts-inspect-iter" min="0" value="0" style="width:5rem">
          </div>
          <div class="scorer-row" style="margin-bottom:.85rem">
            <label for="ts-inspect-shuffle">Shuffle</label>
            <input type="number" id="ts-inspect-shuffle" min="1" value="1" style="width:5rem">
          </div>
```

Replace those two `<div>` blocks with a single `<div>`:

```html
          <div class="scorer-row" style="margin-bottom:.85rem;gap:.5rem">
            <label for="ts-inspect-select">Split</label>
            <select id="ts-inspect-select" style="flex:1;min-width:0">
              <option value="">— loading… —</option>
            </select>
            <button class="btn-sm" id="ts-inspect-refresh" title="Refresh splits list">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            </button>
          </div>
```

- [ ] **Step 4: Wire the dropdown in test_set_picker.js**

Edit `src/static/js/test_set_picker.js`. Replace the inspect-mode DOM
lookups + helpers. Find this block (near the bottom of the file, in the
"Inspect mode" section):

```javascript
// ── Inspect mode ────────────────────────────────────────────────
const tsInspectDialog = document.getElementById("ts-inspect-dialog");
const tsInspectIter   = document.getElementById("ts-inspect-iter");
const tsInspectShuffle= document.getElementById("ts-inspect-shuffle");
const tsInspectCancel = document.getElementById("ts-inspect-cancel");
const tsInspectGo     = document.getElementById("ts-inspect-go");
const tsInspectBanner = document.getElementById("ts-inspect-banner");
const tsInspectBannerTxt = document.getElementById("ts-inspect-banner-text");
const tsInspectExit   = document.getElementById("ts-inspect-exit");
```

Replace with:

```javascript
// ── Inspect mode ────────────────────────────────────────────────
const tsInspectDialog  = document.getElementById("ts-inspect-dialog");
const tsInspectSelect  = document.getElementById("ts-inspect-select");
const tsInspectRefresh = document.getElementById("ts-inspect-refresh");
const tsInspectCancel  = document.getElementById("ts-inspect-cancel");
const tsInspectGo      = document.getElementById("ts-inspect-go");
const tsInspectBanner  = document.getElementById("ts-inspect-banner");
const tsInspectBannerTxt = document.getElementById("ts-inspect-banner-text");
const tsInspectExit    = document.getElementById("ts-inspect-exit");
```

Then find the existing `_openInspectDialog` and `_runInspect` functions
(in the same block). Replace BOTH with these new versions:

```javascript
async function _loadInspectSplits() {
  if (!tsInspectSelect) return;
  tsInspectSelect.innerHTML = '<option value="">— loading… —</option>';
  if (tsInspectGo) tsInspectGo.disabled = true;
  try {
    const body = await _fetchJson("/dlc/project/training-dataset/splits");
    const splits = (body && body.splits) || [];
    if (splits.length === 0) {
      tsInspectSelect.innerHTML = '<option value="" disabled selected>— no splits found —</option>';
      return;
    }
    tsInspectSelect.innerHTML = "";
    for (const s of splits) {
      const opt = document.createElement("option");
      opt.value = JSON.stringify({ iteration: s.iteration, shuffle: s.shuffle });
      opt.textContent = s.label;
      tsInspectSelect.appendChild(opt);
    }
    // Enable "Inspect" once a valid value is selected (the first option, by default)
    if (tsInspectGo) tsInspectGo.disabled = !tsInspectSelect.value;
  } catch (e) {
    tsInspectSelect.innerHTML = '<option value="" disabled selected>— failed to load —</option>';
    console.error("loadInspectSplits failed:", e);
  }
}

function _openInspectDialog() {
  if (tsInspectDialog) tsInspectDialog.classList.remove("hidden");
  _loadInspectSplits();
}

async function _runInspect() {
  if (!tsInspectSelect || !tsInspectSelect.value) return;
  let parsed;
  try {
    parsed = JSON.parse(tsInspectSelect.value);
  } catch {
    return;
  }
  const iter = parseInt(parsed.iteration);
  const shuffle = parseInt(parsed.shuffle);
  try {
    const body = await _fetchJson(
      `/dlc/project/training-dataset/inspect?iteration=${iter}&shuffle=${shuffle}`,
    );
    const ds = (body.datasets || []).find(d => d.shuffle === shuffle)
            || (body.datasets || [])[0];
    if (!ds) {
      alert(`No frozen split found for iteration ${iter} / shuffle ${shuffle}.`);
      return;
    }
    const trainSet = new Set(ds.train.map(d => `${d.video_stem}|${d.image_name}`));
    const testSet  = new Set(ds.test.map(d  => `${d.video_stem}|${d.image_name}`));
    _tsInspect = {
      iteration: iter, shuffle, trainSet, testSet,
      trainFraction: ds.train_fraction,
    };
    if (tsInspectBanner) tsInspectBanner.classList.remove("hidden");
    if (tsInspectBannerTxt) tsInspectBannerTxt.textContent =
      `Inspecting iteration-${iter} / shuffle-${shuffle} ` +
      `(trainset${Math.round(ds.train_fraction * 100)}) — read-only`;
    _closeInspectDialog();
    _renderFrameInspectAware();
  } catch (e) {
    alert(`Inspect failed: ${e.message || e}`);
  }
}
```

Then find this existing line near the bottom of the inspect-mode block:

```javascript
if (tsInspectBtn)    tsInspectBtn.addEventListener("click", _openInspectDialog);
```

Add this NEW line immediately after it (wires the refresh button + enables the Inspect button when the user picks an option):

```javascript
if (tsInspectRefresh) tsInspectRefresh.addEventListener("click", _loadInspectSplits);
if (tsInspectSelect)  tsInspectSelect.addEventListener("change", () => {
  if (tsInspectGo) tsInspectGo.disabled = !tsInspectSelect.value;
});
```

- [ ] **Step 5: Run the dropdown tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py::test_inspect_dialog_uses_dropdown tests/test_test_set_picker_ui_presence.py::test_picker_js_calls_splits_endpoint -q
```

Expected: both pass.

- [ ] **Step 6: Run all picker tests to confirm nothing regressed**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py tests/test_test_set_picker_inspect.py tests/test_test_set_picker_routes.py tests/test_test_set_picker_splits_route.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/templates/partials/card_test_set_picker.html src/static/js/test_set_picker.js src/tests/test_test_set_picker_ui_presence.py
git commit -m "feat(ui): inspect dialog now uses an auto-populated dropdown

Replaces the two type-a-number inputs (ts-inspect-iter,
ts-inspect-shuffle) with a single ts-inspect-select dropdown plus a
refresh button. On dialog open the picker calls the new splits
endpoint and renders one option per split as
'iteration-N • shuffle-K • trainset XX%'. Inspect button is disabled
until a valid split is chosen. No more guessing values."
```

---

## Task 4: Frontend — per-folder marked/total counter in stem dropdown

**Files:**
- Modify: `src/static/js/test_set_picker.js`
- Test: `src/tests/test_test_set_picker_ui_presence.py`

The endpoint `GET /dlc/project/test-set/marks` already returns
`counts.per_folder`. This task wires it into the stem dropdown's
option labels and keeps them in sync after each toggle.

- [ ] **Step 1: Write the failing presence test**

Append to `src/tests/test_test_set_picker_ui_presence.py`:

```python


def test_picker_js_renders_folder_counter():
    text = (SRC / "static" / "js" / "test_set_picker.js").read_text()
    assert "_stemOptionLabel" in text, (
        "picker JS should have a _stemOptionLabel helper that builds 'stem — xx/yy' option text"
    )
    assert "_refreshStemOptionLabel" in text, (
        "picker JS should have a _refreshStemOptionLabel helper to update one option in place after a toggle"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py::test_picker_js_renders_folder_counter -q
```

Expected: fails (the helpers don't exist).

- [ ] **Step 3: Add the helpers + reorder loads + refresh-on-toggle**

Edit `src/static/js/test_set_picker.js`.

**3a — Add the helper functions** near the top of the file, immediately
after the `_buildPalette` function definition:

```javascript
function _stemOptionLabel(stem, totalFrames) {
  const marked = (_tsMarks[stem] || new Set()).size;
  return `${stem} — ${marked}/${totalFrames}`;
}

function _refreshStemOptionLabel(stem) {
  if (!tsStemSelect) return;
  const opt = tsStemSelect.querySelector(`option[value="${CSS.escape(stem)}"]`);
  if (!opt) return;
  const found = _tsStems.find(s => (s.video_stem || s) === stem);
  const total = (found && found.frames) ? found.frames.length : 0;
  opt.textContent = _stemOptionLabel(stem, total);
}
```

**3b — Update `_loadStems`** so it uses the new label. Find:

```javascript
async function _loadStems() {
  // dlc_list_labeled_frames returns { video_stems: [{video_stem, frames[]}, ...] }
  const body = await _fetchJson("/dlc/project/labeled-frames");
  _tsStems = body.video_stems || body.frames || (Array.isArray(body) ? body : []);
  tsStemSelect.innerHTML = '<option value="">— select video —</option>';
  for (const s of _tsStems) {
    const stem = s.video_stem || s;
    const opt = document.createElement("option");
    opt.value = stem; opt.textContent = stem;
    tsStemSelect.appendChild(opt);
  }
}
```

Replace with:

```javascript
async function _loadStems() {
  // dlc_list_labeled_frames returns { video_stems: [{video_stem, frames[]}, ...] }
  const body = await _fetchJson("/dlc/project/labeled-frames");
  _tsStems = body.video_stems || body.frames || (Array.isArray(body) ? body : []);
  tsStemSelect.innerHTML = '<option value="">— select video —</option>';
  for (const s of _tsStems) {
    const stem  = s.video_stem || s;
    const total = (s.frames || []).length;
    const opt   = document.createElement("option");
    opt.value       = stem;
    opt.textContent = _stemOptionLabel(stem, total);
    tsStemSelect.appendChild(opt);
  }
}
```

**3c — Reorder loads in `_openPicker`** so marks arrive before stems. Find:

```javascript
async function _openPicker() {
  if (tsCard) tsCard.classList.remove("hidden");
  await Promise.all([_loadBodyparts(), _loadStems(), _loadMarks()]);
}
```

Replace with:

```javascript
async function _openPicker() {
  if (tsCard) tsCard.classList.remove("hidden");
  // Marks first, so _loadStems can render per-folder counters from _tsMarks.
  await _loadMarks();
  await Promise.all([_loadBodyparts(), _loadStems()]);
}
```

**3d — Refresh the active option after each toggle**. Find
`_toggleCurrentMark`. At its very end, INSIDE the function but AFTER
the optimistic state update and counter refresh, add ONE new line —
just before the closing `}` of the success path:

The function currently ends like this (rough excerpt — find the actual closing):

```javascript
  try {
    await _fetchJson(
      `/dlc/project/test-set/marks/${encodeURIComponent(_tsStem)}/${encodeURIComponent(name)}`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ marked: willBeMarked }) },
    );
  } catch (e) {
    …rollback…
  }
}
```

Just after the `_updateCounters({});` call earlier in the function (right
after the optimistic add/remove block, before the `try`), and ALSO at
the end of the catch's rollback block, add the call to refresh the
option's text. Concretely, find this section:

```javascript
  // Optimistic
  if (willBeMarked) (_tsMarks[_tsStem] ||= new Set()).add(name);
  else _tsMarks[_tsStem]?.delete(name);
  _updateToggleButton();
  _updateCounters({});
```

Replace it with:

```javascript
  // Optimistic
  if (willBeMarked) (_tsMarks[_tsStem] ||= new Set()).add(name);
  else _tsMarks[_tsStem]?.delete(name);
  _updateToggleButton();
  _updateCounters({});
  _refreshStemOptionLabel(_tsStem);
```

And find the rollback block inside the catch:

```javascript
  } catch (e) {
    // Rollback on error
    if (willBeMarked) _tsMarks[_tsStem]?.delete(name);
    else (_tsMarks[_tsStem] ||= new Set()).add(name);
    _updateToggleButton();
    _updateCounters({});
    console.error("toggle failed:", e);
  }
```

Replace it with:

```javascript
  } catch (e) {
    // Rollback on error
    if (willBeMarked) _tsMarks[_tsStem]?.delete(name);
    else (_tsMarks[_tsStem] ||= new Set()).add(name);
    _updateToggleButton();
    _updateCounters({});
    _refreshStemOptionLabel(_tsStem);
    console.error("toggle failed:", e);
  }
```

**3e — Also refresh after `Clean stale`** so any stale-mark removals
show up in the dropdown immediately. Find the clean-stale handler:

```javascript
if (tsCleanStale) tsCleanStale.addEventListener("click", async () => {
  await _fetchJson("/dlc/project/test-set/marks/clean-stale", { method: "POST" });
  await _loadMarks();
  _updateCounters({});
});
```

Replace with:

```javascript
if (tsCleanStale) tsCleanStale.addEventListener("click", async () => {
  await _fetchJson("/dlc/project/test-set/marks/clean-stale", { method: "POST" });
  await _loadMarks();
  // Refresh every visible stem option since several may have been affected.
  if (tsStemSelect) {
    for (const opt of tsStemSelect.querySelectorAll('option[value]')) {
      if (opt.value) _refreshStemOptionLabel(opt.value);
    }
  }
  _updateCounters({});
});
```

- [ ] **Step 4: Run the new test**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_test_set_picker_ui_presence.py::test_picker_js_renders_folder_counter -q
```

Expected: passes.

- [ ] **Step 5: Full picker regression**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/test_marks_store.py tests/test_test_set_split.py tests/test_test_set_picker_routes.py tests/test_test_set_picker_inspect.py tests/test_test_set_picker_splits_route.py tests/test_dlc_create_training_dataset_split_modes.py tests/test_dlc_training_routes.py tests/test_frame_overlay_module_exists.py tests/test_test_set_picker_ui_presence.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/test_set_picker.js src/tests/test_test_set_picker_ui_presence.py
git commit -m "feat(ui): show marked/total counter next to each folder in stem dropdown

Each labeled-frames folder is now rendered as 'stem — xx/yy' where
xx is the number of test-set marks in that folder and yy is the
total frame count. Loads marks before stems so the initial render
has counts; refreshes the active folder's option text on every
toggle, and refreshes all of them after Clean stale. No backend
change — counts.per_folder was already in the marks response."
```

---

## Task 5: Final manual smoke + push

**Files:** none added; verification + push.

- [ ] **Step 1: Restart the running containers so templates and Python pick up changes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart flask worker worker-tf
docker ps --format '{{.Names}}\t{{.Status}}' | grep deeplabcut
```

Expected: all three containers reported `Up` (a few seconds old).

- [ ] **Step 2: Manual browser smoke**

In a browser at `http://localhost:5000`:

1. Open Test-set Picker.
2. Click the labeled-frames folder dropdown — confirm each entry shows `stem — xx/yy` where `yy` is the folder's frame count.
3. Mark one frame with `T`; the dropdown's currently-selected option's `xx` should update immediately by 1.
4. Click **Inspect splits ↗** — confirm a dropdown labelled `Split` appears with options like `iteration-4 • shuffle-1 • trainset 80%`. The Inspect button is disabled if `— no splits found —` shows. Pick the first option, click Inspect; the picker enters inspect mode and shows TRAIN/TEST badges as before.
5. Exit inspect mode.
6. Open Frame Labeler — confirm bodypart dots use the SAME colors as the picker did. (If frame_labeler.js still uses `FL_COLORS`, colors will match because the new `DEFAULT_PALETTE` is byte-identical.)

If any of those don't behave, surface immediately — do not push.

- [ ] **Step 3: Full host-side regression once more**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker/src
pytest tests/ -q -m "not gpu and not e2e" --no-header 2>&1 | tail -3
```

Expected: passed count equals previous baseline (299) + 4 new tests from this plan (Task 1 = 5 new but one was already counted, Task 2 = 2 new, Task 3 = 2 new, Task 4 = 1 new). Concretely target: ≥309 passed, 38 failed (unchanged pre-existing). Any green-to-red flip is a blocker.

- [ ] **Step 4: Confirm disk is still healthy**

```bash
df -h /tmp | tail -1
du -sh /tmp/pytest-of-sam /tmp/dlc_test_session_* 2>/dev/null | head -3
```

Expected: `/tmp/pytest-of-sam` is empty or 4 KB; `/tmp/dlc_test_session_*` shows at most the currently-running session.

- [ ] **Step 5: Push the branch**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git status
git log --oneline origin/feat/test-set-picker..HEAD
git push origin feat/test-set-picker
```

Expected: 4 new commits (one per Task 1-4) push cleanly as a fast-forward to `origin/feat/test-set-picker`. No force push needed.

---

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §2 Inspect-splits dropdown — backend | T1 |
| §2 Inspect-splits dropdown — frontend | T3 |
| §3 Color palette parity | T2 |
| §4 Folder dropdown counter | T4 |
| §5 Tests | T1 (5 cases) + T2 (2 cases) + T3 (2 cases) + T4 (1 case) |
| §6 Preserving existing behavior | T2 step 6 guard + T0 baseline check |
| §7 Out of scope | (none — explicitly excluded) |
