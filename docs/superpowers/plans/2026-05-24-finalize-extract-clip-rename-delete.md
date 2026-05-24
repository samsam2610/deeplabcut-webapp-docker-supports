# Finalize-and-Extract Clip (+ Rename / Delete w/ un-finalize) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add to the inline-3D finalize sub-card: a "Finalize and extract clip" button (finalize the keyframe-window range AND cut a clip), plus Rename/Delete of that clip — where Delete also un-finalizes (NaNs) the range from `_analyzed`.

**Architecture:** Backend (main webapp): `canonical.unfinalize_range` + `POST …/unfinalize-range`. Frontend (dlc-3D): refactor the finalize core into `_doFinalizeAdd()`, add postfix/both-cams/3 buttons + handlers + last-clip state. Reuses existing `/dlc-3d/extract-clip[/rename|/delete]` endpoints.

**Tech Stack:** Python/Flask + pandas/h5 (backend); vanilla ES modules + Jinja (frontend). pytest (backend + static contracts).

**Spec:** `docs/superpowers/specs/2026-05-24-finalize-extract-clip-rename-delete-design.md`

**Two repos:** backend `/home/sam/docker-images/deeplabcut-webapp-docker`; frontend `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`.

**Run only the test files named in each task.**

---

### Task 1: Backend un-finalize (main webapp)

**Work from:** `/home/sam/docker-images/deeplabcut-webapp-docker`

**Files:**
- Modify: `src/dlc/canonical.py` (add `unfinalize_range`)
- Modify: `src/dlc/inline_analysis.py` (add the route)
- Test: `tests/test_canonical_unfinalize.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canonical_unfinalize.py`:

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import pandas as pd
from dlc import canonical as C


def test_unfinalize_clears_range_only(tmp_path):
    video = tmp_path / "vidcam0.mp4"
    df = C.build_empty_dense_df("DLC_test", ["a", "b"], 10)
    df.loc[2:5, :] = 1.0     # frames 2,3,4,5 "finalized" (finite); label slice includes 5
    C._atomic_write_h5(C.canonical_h5_path(video), df)
    C._atomic_write_csv(C.canonical_csv_path(video), df)

    n = C.unfinalize_range(video, 3, 2)   # clear frames 3,4
    assert n == 2
    out = pd.read_hdf(str(C.canonical_h5_path(video)))
    assert out.loc[3].isna().all() and out.loc[4].isna().all()       # cleared
    assert not out.loc[2].isna().all() and not out.loc[5].isna().all()  # outside range untouched
    assert C.canonical_csv_path(video).is_file()                      # csv regenerated


def test_unfinalize_missing_file_is_noop(tmp_path):
    assert C.unfinalize_range(tmp_path / "novid.mp4", 0, 5) == 0
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_canonical_unfinalize.py -q` → FAIL (no `unfinalize_range`).

(If the test errors at `df.loc[2:5, :] = 1.0` or `build_empty_dense_df`, first READ `build_empty_dense_df` to confirm its signature/columns and adjust the fill — but the generic `.loc[rows, :] = 1.0` should work on any column layout.)

- [ ] **Step 3: Implement `unfinalize_range` in `src/dlc/canonical.py`**

Add (after `write_to_canonical`; `pd` is imported at module top — add `import numpy as np` at the top if not already present):

```python
def unfinalize_range(video_path, start_frame: int, n_frames: int) -> int:
    """Un-finalize: set rows [start_frame, start_frame+n_frames) to NaN in the
    canonical _analyzed file (the inverse of write_to_canonical for that range).
    Rows outside the range are untouched; the .h5 and .csv are rewritten
    atomically so they stay consistent. Missing file -> 0. Returns rows cleared."""
    import numpy as np
    h5 = canonical_h5_path(video_path)
    if not h5.exists():
        return 0
    df = pd.read_hdf(str(h5))
    wanted = range(int(start_frame), int(start_frame) + int(n_frames))
    mask = df.index.isin(wanted)
    n = int(mask.sum())
    if n:
        df.loc[mask, :] = np.nan
        _atomic_write_h5(h5, df)
        csv = canonical_csv_path(video_path)
        if csv.exists():
            _atomic_write_csv(csv, df)
    return n
```

- [ ] **Step 4: Run to verify the canonical tests PASS**

Run: `python -m pytest tests/test_canonical_unfinalize.py -q` → 2 passed.

- [ ] **Step 5: Add the route in `src/dlc/inline_analysis.py`**

`_canonical` is already imported (used by `_finalize_range_to_canonical`); `_active_project()`, `request`, `jsonify`, `bp` exist. Add near `finalize_range`:

```python
@bp.route("/dlc/project/inline-analysis/unfinalize-range", methods=["POST"])
def unfinalize_range():
    project = _active_project()
    if not project:
        return jsonify({"error": "No active DLC project."}), 400
    body = request.get_json(silent=True) or {}
    video_path = (body.get("video_path") or "").strip()
    start_frame = body.get("start_frame")
    n_frames = body.get("n_frames")
    if not video_path or start_frame is None or n_frames is None:
        return jsonify({"error": "video_path, start_frame, n_frames required"}), 400
    try:
        n = _canonical.unfinalize_range(video_path, int(start_frame), int(n_frames))
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 500
    return jsonify({"n_frames_cleared": n})
```

- [ ] **Step 6: Verify import + tests**

Run: `python -c "import sys; sys.path.insert(0,'src'); import dlc.inline_analysis"` → clean.
Run: `python -m pytest tests/test_canonical_unfinalize.py -q` → 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/dlc/canonical.py src/dlc/inline_analysis.py tests/test_canonical_unfinalize.py
git commit -m "feat(dlc): canonical.unfinalize_range + unfinalize-range endpoint

NaNs rows [start, start+n) in the _analyzed h5+csv (inverse of finalize-range for
that range), atomically; missing file is a no-op. Endpoint exposes it for the
finalize-clip Delete action. Round-trip tested.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Finalize-clip markup (dlc-3D)

**Work from:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html`
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_finalize_clip_controls_present():
    html = CARD.read_text()
    for need in ["ia3d-finalize-clip-postfix", "ia3d-finalize-clip-sibling",
                 "ia3d-finalize-clip-btn", "ia3d-finalize-clip-rename-btn",
                 "ia3d-finalize-clip-delete-btn"]:
        assert need in html, f"missing finalize-clip element {need!r}"
    # rename + delete start disabled
    assert re.search(r'id="ia3d-finalize-clip-rename-btn"[^>]*\bdisabled', html) or \
           re.search(r'\bdisabled[^>]*id="ia3d-finalize-clip-rename-btn"', html)
    assert re.search(r'id="ia3d-finalize-clip-delete-btn"[^>]*\bdisabled', html) or \
           re.search(r'\bdisabled[^>]*id="ia3d-finalize-clip-delete-btn"', html)
    # existing Add-range button kept
    assert "ia3d-finalize-add-btn" in html
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_clip_controls_present -q` → FAIL.

- [ ] **Step 3: Add the markup**

In `src/templates/partials/card_inline_analysis_3d.html`, find the Add-range row (the `<div …>` containing `#ia3d-finalize-range` + `#ia3d-finalize-add-btn`) inside `#ia3d-finalize-controls`. Immediately AFTER that closing `</div>` (and BEFORE the "Finalized frames (_analyzed)" nav row), insert:

```html
            <div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.35rem">
              <input type="text" id="ia3d-finalize-clip-postfix" placeholder="postfix (optional)"
                style="flex:1;min-width:110px;font-size:.76rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.22rem .4rem" />
              <label style="display:flex;align-items:center;gap:.3rem;font-size:.74rem;color:var(--text-dim);cursor:pointer;user-select:none">
                <input type="checkbox" id="ia3d-finalize-clip-sibling" checked style="accent-color:var(--accent);width:13px;height:13px"/> both cams
              </label>
            </div>
            <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;margin-bottom:.4rem">
              <button class="btn-sm btn-create" id="ia3d-finalize-clip-btn"
                title="Finalize this range into _analyzed AND extract a clip from it">Finalize and extract clip</button>
              <button class="btn-sm" id="ia3d-finalize-clip-rename-btn" disabled style="opacity:.8"
                title="Rename the extracted clip with the postfix">Rename clip</button>
              <button class="btn-sm" id="ia3d-finalize-clip-delete-btn" disabled style="opacity:.7"
                title="Delete the clip AND un-finalize its frames from _analyzed">Delete clip</button>
            </div>
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_clip_controls_present -q` → PASS. (Other tests may fail until Task 3 wires the handlers — that's expected; don't run the whole file yet.)

- [ ] **Step 5: Commit**

```bash
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): finalize-clip controls markup (postfix, both-cams, 3 buttons)

Adds a postfix field + both-cams checkbox + Finalize-and-extract / Rename / Delete
buttons to the finalize sub-card (rename/delete start disabled). JS wiring next.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Finalize-clip glue (dlc-3D)

**Files:**
- Modify: `src/static/inline_analysis_3d.js`
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

**Context:** the current `_onFinalizeAddClick` (read it) does: select-guard → `_finalizeKW.getRange()` → overwrite-confirm → save layers → `_ia3dFinalizeOne` both cams → status → `_refreshFinalizeCoverage`. We extract its core into `_doFinalizeAdd()` returning `{ok, start, n}`, shared by both finalize buttons. `_cam0Path()` = cam0 video; `_siblingPath` = cam1 video; `_overlayPrimaryH5`/`_siblingPrimaryH5` = the layers; `_ia3dSaveLayer`, `_ia3dFinalizeOne`, `_initStatus`, `_refreshFinalizeCoverage` exist.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_finalize_clip_glue_wired():
    js = JS.read_text()
    assert "_doFinalizeAdd" in js, "finalize core must be factored into _doFinalizeAdd"
    assert "_lastFinalizeClip" in js
    assert "/dlc-3d/extract-clip" in js                  # extract
    assert "/dlc-3d/extract-clip/rename" in js           # rename
    assert "/dlc-3d/extract-clip/delete" in js           # delete file
    assert "/dlc/project/inline-analysis/unfinalize-range" in js  # delete un-finalizes _analyzed
    assert "_onFinalizeAndExtractClick" in js and "_onFinalizeClipRename" in js and "_onFinalizeClipDelete" in js
    # delete confirms first (destructive)
    assert re.search(r"_onFinalizeClipDelete[\s\S]{0,400}window\.confirm", js)
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_clip_glue_wired -q` → FAIL.

- [ ] **Step 3: Refactor `_onFinalizeAddClick` → `_doFinalizeAdd()` + thin click**

Replace the entire current `async function _onFinalizeAddClick() { … }` with these two functions:

```javascript
// Finalize the current keyframe-window range into both cams' _analyzed.
// Returns { ok, start, n }. Shared by the Add-range and Finalize-and-extract
// buttons; callers manage their own button disabled-state.
async function _doFinalizeAdd() {
  const st = $("ia3d-finalize-status");
  const cam0H5 = _overlayPrimaryH5, cam0Video = _cam0Path();
  if (!cam0H5 || !cam0Video) {
    if (st) { st.textContent = "Select a video/layer first."; st.className = "fe-extract-status err"; }
    return { ok: false, start: 0, n: 0 };
  }
  const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
  const startFrame = rng.start, nFrames = rng.n;
  const cam1Layer = _siblingPrimaryH5;
  try {
    const e0 = await _initStatus(cam0Video);
    const e1 = (_siblingPath && cam1Layer) ? await _initStatus(_siblingPath) : false;
    if ((e0 || e1) && !window.confirm(
        `Overwrite frames ${startFrame}–${startFrame + nFrames - 1} in the existing _analyzed file(s)` +
        `${e0 && e1 ? " on both cameras" : (e0 ? " on cam0" : " on cam1")}?\n\nThis replaces any curated values already saved for those frames.`)) {
      if (st) { st.textContent = "Cancelled."; st.className = "fe-extract-status"; }
      return { ok: false, start: startFrame, n: nFrames };
    }
  } catch (_) { /* status check failed — proceed */ }
  if (st) { st.textContent = "Finalizing…"; st.className = "fe-extract-status"; }
  const sv0 = await _ia3dSaveLayer(cam0H5);
  const sv1 = cam1Layer ? await _ia3dSaveLayer(cam1Layer) : true;
  if (!sv0 || !sv1) {
    if (st) { st.textContent = `Could not save edits (${!sv0 ? "cam0" : "cam1"}) — finalize aborted`; st.className = "fe-extract-status err"; }
    return { ok: false, start: startFrame, n: nFrames };
  }
  const r0 = await _ia3dFinalizeOne(cam0Video, cam0H5, startFrame, nFrames);
  let r1 = null;
  if (_siblingPath && cam1Layer) r1 = await _ia3dFinalizeOne(_siblingPath, cam1Layer, startFrame, nFrames);
  if (st) {
    const p0 = r0.ok ? `cam0 ✓ ${r0.n}` : `cam0 ⚠ ${r0.err}`;
    const p1 = r1 ? (r1.ok ? ` · cam1 ✓ ${r1.n}` : ` · cam1 ⚠ ${r1.err}`) : "";
    st.textContent = `${p0}${p1}`;
    st.className = (r0.ok && (!r1 || r1.ok)) ? "fe-extract-status" : "fe-extract-status err";
  }
  _refreshFinalizeCoverage();
  return { ok: !!(r0.ok && (!r1 || r1.ok)), start: startFrame, n: nFrames };
}

async function _onFinalizeAddClick() {
  const btn = $("ia3d-finalize-add-btn");
  if (btn) btn.disabled = true;
  try { await _doFinalizeAdd(); }
  finally { if (btn) btn.disabled = false; }
}
```

- [ ] **Step 4: Add state + clip handlers (module level, near `_onFinalizeAddClick`)**

```javascript
let _lastFinalizeClip = null;   // { start, n, cams: [{ video, avi }, …] } from the last Finalize-and-extract

function _finalizeClipBtnsEnabled(on) {
  const r = $("ia3d-finalize-clip-rename-btn"), d = $("ia3d-finalize-clip-delete-btn");
  if (r) r.disabled = !on;
  if (d) d.disabled = !on;
}

async function _onFinalizeAndExtractClick() {
  const st = $("ia3d-finalize-status"), btn = $("ia3d-finalize-clip-btn");
  if (btn) btn.disabled = true;
  try {
    const r = await _doFinalizeAdd();
    if (!r.ok) return;
    const postfix = $("ia3d-finalize-clip-postfix")?.value || "";
    const both = $("ia3d-finalize-clip-sibling")?.checked;
    const cams = [{ video: _cam0Path() }];
    if (both && _siblingPath) cams.push({ video: _siblingPath });
    let okCount = 0;
    for (const c of cams) {
      try {
        const resp = await (await fetch("/dlc-3d/extract-clip", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_path: c.video, start_frame: r.start, n_frames: r.n, postfix }),
        })).json();
        c.avi = resp.avi_path || null;
        if (c.avi) okCount++;
      } catch (_) { c.avi = null; }
    }
    _lastFinalizeClip = { start: r.start, n: r.n, cams };
    _finalizeClipBtnsEnabled(true);
    if (st) st.textContent = `${st.textContent} · clip ✓ (${okCount} cam${okCount !== 1 ? "s" : ""})`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _onFinalizeClipRename() {
  if (!_lastFinalizeClip) return;
  const st = $("ia3d-finalize-status");
  const postfix = $("ia3d-finalize-clip-postfix")?.value || "";
  for (const c of _lastFinalizeClip.cams) {
    if (!c.avi) continue;
    try {
      const resp = await (await fetch("/dlc-3d/extract-clip/rename", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avi_path: c.avi, postfix }),
      })).json();
      if (resp.avi_path) c.avi = resp.avi_path;
    } catch (_) { /* best effort */ }
  }
  if (st) { st.textContent = "Clip renamed."; st.className = "fe-extract-status"; }
}

async function _onFinalizeClipDelete() {
  if (!_lastFinalizeClip) return;
  const { start, n, cams } = _lastFinalizeClip;
  if (!window.confirm(
      `Delete the extracted clip and REMOVE frames ${start}–${start + n - 1} from the _analyzed file(s)?\n\nThis un-finalizes those frames (sets them back to no-data).`)) return;
  const st = $("ia3d-finalize-status");
  for (const c of cams) {
    if (c.avi) {
      try { await fetch("/dlc-3d/extract-clip/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ avi_path: c.avi }) }); } catch (_) { /* best effort */ }
    }
    try {
      await fetch("/dlc/project/inline-analysis/unfinalize-range", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ video_path: c.video, start_frame: start, n_frames: n }) });
    } catch (_) { /* best effort */ }
  }
  _refreshFinalizeCoverage();
  _lastFinalizeClip = null;
  _finalizeClipBtnsEnabled(false);
  if (st) { st.textContent = "Clip deleted; frames un-finalized."; st.className = "fe-extract-status"; }
}
```

- [ ] **Step 5: Wire the three buttons + reset**

Find where `$("ia3d-finalize-add-btn")?.addEventListener("click", _onFinalizeAddClick);` is registered, and add right after:

```javascript
  $("ia3d-finalize-clip-btn")?.addEventListener("click", _onFinalizeAndExtractClick);
  $("ia3d-finalize-clip-rename-btn")?.addEventListener("click", _onFinalizeClipRename);
  $("ia3d-finalize-clip-delete-btn")?.addEventListener("click", _onFinalizeClipDelete);
```

In `_resetForOpen`, add (near the finalize resets):
```javascript
  _lastFinalizeClip = null;
  _finalizeClipBtnsEnabled(false);
```

- [ ] **Step 6: Run to verify PASS + full affected suites**

Run: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q` → all PASS.
Then: `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_keyframe_window_ui.py tests/test_video_viewer_base.py tests/test_status_notes_feature.py -q && node --test tests/unit/*.mjs`
Expected: pytest all PASS; node `# fail 0`.

- [ ] **Step 7: Commit**

```bash
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): finalize-and-extract clip + rename/delete (delete un-finalizes)

Factor the finalize core into _doFinalizeAdd(); Finalize-and-extract runs it then
cuts a clip (both cams, postfix) from the same range, tracking _lastFinalizeClip.
Rename renames the clip; Delete (with confirm) deletes the clip files AND posts
unfinalize-range to clear those frames from _analyzed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Live verification (controller, after all tasks)
Restart `flask` (backend route) + `dlc-3d` (template): `docker compose restart flask dlc-3d`. With the finalize panel open on a video+overlay:
1. The postfix field + both-cams + three buttons render; **Rename/Delete are disabled**.
2. Do NOT click Finalize-and-extract or Delete (they write `_analyzed` + create/delete clip files). The un-finalize correctness is proven by the backend round-trip unit tests.
3. (Optional, safe) Confirm `_finalizeKW.getRange()` drives the range readout as before.

## Out of scope (YAGNI)
- Redo/history stack (single last-op undo).
- Persisting `_lastFinalizeClip` across reloads.
