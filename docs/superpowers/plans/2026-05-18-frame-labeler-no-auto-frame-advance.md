# Frame Labeler: Drop Auto-Frame-Advance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `_flAutoAdvanceBp()` from advancing the frame when every BP on the current frame is labeled, in both the main webapp's `frame_labeler.js` and the 3D module's `frame_labeler_3d.js`. Same-frame next-missing-BP walk after a click is preserved unchanged.

**Architecture:** Two-line deletion in main, ~5-line deletion in 3D. Each deletion removes a fall-through `_flShowFrame(...)` at the end of `_flAutoAdvanceBp`. Coverage: TDD-ordered — write the failing tests first (source-text regression on both files; Playwright e2e on the 3D module in both sync-off and sync-on modes), then delete the offending code, then watch them go green.

**Tech Stack:** Vanilla JS in two static files; pytest for source-text regression tests; pytest-playwright for the 3D e2e tests (existing infra at `dlc-3D/tests/e2e/conftest.py`).

**Spec:** `deeplabcut-webapp-docker-supports/docs/superpowers/specs/2026-05-18-frame-labeler-no-auto-frame-advance-design.md`

---

## File Map

**Production code (deletions only):**
- Modify: `deeplabcut-webapp-docker/src/static/js/frame_labeler.js` (delete 2 lines inside `_flAutoAdvanceBp`, declared at line 1116)
- Modify: `deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js` (delete ~8 lines inside `_flAutoAdvanceBp`, declared at line 1629)

**New tests:**
- Create: `deeplabcut-webapp-docker/tests/test_frame_labeler_no_auto_frame_advance.py` (source-text regression)
- Create: `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_frame_labeler_3d_no_auto_frame_advance.py` (source-text regression)
- Create: `deeplabcut-webapp-docker-supports/dlc-3D/tests/e2e/test_labeler_no_auto_frame_advance.py` (Playwright e2e, two tests: sync-off and sync-on)

**Why the test split:** the Playwright tests prove runtime behavior on the 3D side where infra exists. The source-text regressions are cheap guards that run in plain unit-test jobs and cover both the main webapp (no Playwright infra for the labeler) and 3D (defense in depth).

---

## Task 1: Source-text regression test for the main webapp

**Why first:** The main webapp has no Playwright infra for the labeler. The source-text test is the only automated guard there, and it must fail before the deletion lands (proving it actually checks the right thing).

**Files:**
- Create: `deeplabcut-webapp-docker/tests/test_frame_labeler_no_auto_frame_advance.py`

- [ ] **Step 1: Write the failing test**

Create `deeplabcut-webapp-docker/tests/test_frame_labeler_no_auto_frame_advance.py` with this content:

```python
"""Regression guard: _flAutoAdvanceBp must not advance the frame when every
BP on the current frame is already labeled. The user owns frame navigation.

This test reads the source of frame_labeler.js and asserts the body of the
_flAutoAdvanceBp function contains no call to _flShowFrame. It's a cheap
static guard against the deleted fall-through being reintroduced.
"""
import re
from pathlib import Path

FRAME_LABELER_JS = (
    Path(__file__).parent.parent / "src" / "static" / "js" / "frame_labeler.js"
)


def _extract_function_body(src: str, fn_name: str) -> str:
    """Return the body (between the outermost { }) of `function fn_name(...)`.

    Walks braces from the opening { to its matching close. Raises AssertionError
    if the function isn't found or the braces don't balance.
    """
    m = re.search(r"function\s+" + re.escape(fn_name) + r"\s*\([^)]*\)\s*\{", src)
    assert m, f"function {fn_name} not found in source"
    start = m.end()              # first char after the opening {
    depth = 1
    i = start
    while i < len(src) and depth:
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"unbalanced braces while scanning {fn_name}"
    return src[start : i - 1]    # exclude the closing }


def test_auto_advance_bp_does_not_call_show_frame():
    src = FRAME_LABELER_JS.read_text()
    body = _extract_function_body(src, "_flAutoAdvanceBp")
    assert "_flShowFrame" not in body, (
        "_flAutoAdvanceBp must not call _flShowFrame — the auto-frame-advance "
        "fall-through was reintroduced. Frame navigation belongs to the user."
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
pytest tests/test_frame_labeler_no_auto_frame_advance.py -v
```

Expected: **FAIL** with the assertion error `"_flAutoAdvanceBp must not call _flShowFrame …"`. The current code at `src/static/js/frame_labeler.js:1125` contains `_flShowFrame(_flFrameIdx + 1)` inside the function, so the body string will contain `_flShowFrame`.

- [ ] **Step 3: Commit the failing test**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add tests/test_frame_labeler_no_auto_frame_advance.py
git commit -m "test: regression guard for frame-labeler auto-frame-advance removal"
```

---

## Task 2: Source-text regression test for the 3D module

**Files:**
- Create: `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_frame_labeler_3d_no_auto_frame_advance.py`

- [ ] **Step 1: Write the failing test**

Create `deeplabcut-webapp-docker-supports/dlc-3D/tests/test_frame_labeler_3d_no_auto_frame_advance.py` with this content:

```python
"""Regression guard: _flAutoAdvanceBp in frame_labeler_3d.js must not advance
the frame when every BP on the current frame is already labeled.

Same approach as the main webapp's equivalent test — static source scan, so
it runs without the browser/fixture stack.
"""
import re
from pathlib import Path

FRAME_LABELER_3D_JS = (
    Path(__file__).parent.parent / "src" / "static" / "frame_labeler_3d.js"
)


def _extract_function_body(src: str, fn_name: str) -> str:
    """Return the body (between the outermost { }) of `function fn_name(...)`.

    Walks braces from the opening { to its matching close. Raises AssertionError
    if the function isn't found or the braces don't balance.
    """
    m = re.search(r"function\s+" + re.escape(fn_name) + r"\s*\([^)]*\)\s*\{", src)
    assert m, f"function {fn_name} not found in source"
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth:
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"unbalanced braces while scanning {fn_name}"
    return src[start : i - 1]


def test_auto_advance_bp_does_not_call_show_frame():
    src = FRAME_LABELER_3D_JS.read_text()
    body = _extract_function_body(src, "_flAutoAdvanceBp")
    assert "_flShowFrame" not in body, (
        "_flAutoAdvanceBp must not call _flShowFrame — the auto-frame-advance "
        "fall-through (sync-aware curIdx/total block) was reintroduced. "
        "Frame navigation belongs to the user."
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_frame_labeler_3d_no_auto_frame_advance.py -v
```

Expected: **FAIL** with the assertion error `"_flAutoAdvanceBp must not call _flShowFrame …"`. The current code at `src/static/frame_labeler_3d.js:1644` contains `_flShowFrame(curIdx + 1)`.

- [ ] **Step 3: Commit the failing test**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add tests/test_frame_labeler_3d_no_auto_frame_advance.py
git commit -m "test: regression guard for 3D frame-labeler auto-frame-advance removal"
```

---

## Task 3: Playwright e2e test for the 3D module (sync-off + sync-on)

**Why before the deletion:** TDD discipline. The e2e tests must fail (asserting the frame did NOT advance, while it currently DOES) so that deleting the code is the thing that makes them pass.

**Files:**
- Create: `deeplabcut-webapp-docker-supports/dlc-3D/tests/e2e/test_labeler_no_auto_frame_advance.py`

**Background (so the next engineer can read this cold):**
- `dlc-3D/tests/e2e/conftest.py` provides an autouse fixture `_active_dlc_project` that authenticates the browser context to the main flask app and activates the `OM-2_20260424` DLC project. Tests get a `page: Page` fixture from pytest-playwright and a `base_url` fixture from `conftest.py`. If the OM-2 fixture isn't reachable, the whole module is skipped.
- `frame_labeler_3d.js` exposes a debug proxy at `window.__fl3d` with `labels`, `selectedBp`, `syncOn`, `frameNumberIdx`, etc. (see `src/static/frame_labeler_3d.js:1870-1890`).
- The focused tile's `data-fname` attribute is the canonical "current frame" indicator across both sync modes.
- The OM-2 fixture has pre-existing labels on most BPs, so a canvas click near an existing marker takes the "select existing marker" hit-test path instead of placing a new one. We wipe `window.__fl3d.labels[fname]` to force fresh placements on the focused frame only (in-memory only; auto-save fires only on frame switch + dirty=true, which we explicitly avoid by not switching frames during the test).

- [ ] **Step 1: Write the two failing tests**

Create `deeplabcut-webapp-docker-supports/dlc-3D/tests/e2e/test_labeler_no_auto_frame_advance.py` with this content:

```python
"""e2e: labeling every BP on a frame must NOT auto-advance to the next frame.

Two tests cover both sync modes — _flAutoAdvanceBp's fall-through used to
call _flShowFrame using either _flFrameIdx/_flFrames (sync off) or
_fl3dFrameNumIdx/_fl3dFrameNumbers (sync on). Both code paths must stay put.
"""
import pytest
from playwright.sync_api import Page

SESSION = "OM-2_20260424"


@pytest.fixture(autouse=True)
def _open_labeler(page: Page, base_url):
    """Same opening dance as test_sync_frame.py: open the labeler card,
    wait for the SESSION option to appear, select it, wait for the first
    tile's data-fname to be populated.
    """
    page.goto(base_url)
    page.locator("#btn-open-frame-labeler").click()
    page.locator("#frame-labeler-card").wait_for(state="visible")
    page.wait_for_function(
        f"() => Array.from(document.getElementById('fl3d-stem-select').options)"
        f".some(o => o.value === '{SESSION}')",
        timeout=10000,
    )
    page.locator("#fl3d-stem-select").select_option(SESSION)
    page.wait_for_function(
        '() => document.querySelector("#fl3d-canvas-row .fl3d-tile")?.dataset?.fname'
    )


def _label_every_bp_on_focused_frame(page: Page, starting_fname: str) -> list[str]:
    """For each BP chip in DOM order, click the chip and click the canvas at
    a unique offset, waiting for the label to land in window.__fl3d.labels.

    Returns the list of BP names (in chip DOM order) for the caller's assertions.
    """
    # Wipe any pre-existing labels on this frame so every chip click is a
    # fresh placement (mirrors _select_unlabeled_chip in test_sync_frame.py).
    page.evaluate(f"window.__fl3d.labels['{starting_fname}'] = {{}}")

    bps: list[str] = page.eval_on_selector_all(
        "#fl3d-bodypart-list .fl-bp-chip",
        "chips => chips.map(c => c.getAttribute('data-bp'))",
    )
    assert bps, "no BP chips rendered — fixture mismatch"

    canvas = page.locator("#fl3d-canvas-row .fl3d-tile.focused canvas")
    box = canvas.bounding_box()
    assert box is not None, "focused tile canvas has no bounding box"

    for i, bp in enumerate(bps):
        page.locator(f'.fl-bp-chip[data-bp="{bp}"]').click()
        page.wait_for_function(f"window.__fl3d.selectedBp === '{bp}'")
        # Spread offsets so we never hit-test a marker we just placed and
        # accidentally take the select-only path.
        x = box["x"] + box["width"] * 0.2 + i * 6
        y = box["y"] + box["height"] * 0.2 + i * 6
        page.mouse.click(x, y)
        page.wait_for_function(
            f"window.__fl3d.labels['{starting_fname}']?.['{bp}']"
        )

    return bps


def test_no_auto_advance_when_last_bp_labeled_sync_off(page: Page):
    starting_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _label_every_bp_on_focused_frame(page, starting_fname)

    # Every BP is now labeled. The fall-through (deleted) used to call
    # _flShowFrame(_flFrameIdx + 1) here; with the fix it must not fire.
    final_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    assert final_fname == starting_fname, (
        f"Frame auto-advanced unexpectedly (sync off): "
        f"{starting_fname} -> {final_fname}"
    )


def test_no_auto_advance_when_last_bp_labeled_sync_on(page: Page):
    page.locator("#fl3d-sync-frame").check()
    page.wait_for_function("window.__fl3d.syncOn === true")

    starting_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    starting_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    _label_every_bp_on_focused_frame(page, starting_fname)

    # Sync-on uses _fl3dFrameNumIdx / _fl3dFrameNumbers; assert both surfaces
    # of "current frame" stayed put.
    final_idx = page.evaluate("window.__fl3d.frameNumberIdx")
    final_fname = page.eval_on_selector(
        "#fl3d-canvas-row .fl3d-tile.focused", "t => t.dataset.fname"
    )
    assert final_idx == starting_idx, (
        f"frameNumberIdx auto-advanced unexpectedly (sync on): "
        f"{starting_idx} -> {final_idx}"
    )
    assert final_fname == starting_fname, (
        f"Focused tile fname auto-advanced unexpectedly (sync on): "
        f"{starting_fname} -> {final_fname}"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_labeler_no_auto_frame_advance.py -v
```

Expected: both tests **FAIL** at the final assertion (`Frame auto-advanced unexpectedly …`) because the current `_flAutoAdvanceBp` fall-through calls `_flShowFrame(curIdx + 1)` once every BP is labeled. The failure message must mention the frame name change — that's the proof the test is exercising the right path.

**If the tests are SKIPPED instead of failing,** the OM-2 fixture isn't reachable from this environment. The conftest pre-flight (`om2_fixture_present`) requires the main flask app at `http://localhost:5000/dlc-3d/` to be up with the OM-2_20260424 project on disk. Do not "fix" that here — note the skip, proceed with the deletion tasks, and the source-text tests (Tasks 1 & 2) remain the active guards. The e2e tests will run cleanly in the environment that hosts the fixture.

- [ ] **Step 3: Commit the failing tests**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add tests/e2e/test_labeler_no_auto_frame_advance.py
git commit -m "test(e2e): assert frame labeler does not auto-advance on last BP"
```

---

## Task 4: Delete the auto-frame-advance in the main webapp

**Files:**
- Modify: `deeplabcut-webapp-docker/src/static/js/frame_labeler.js:1116-1126` (delete lines 1124-1125 only — the comment and the if-statement at the end of `_flAutoAdvanceBp`)

- [ ] **Step 1: Apply the deletion**

The current function body, for context:

```js
// Auto-advance to the next unlabeled body part (napari behavior)
function _flAutoAdvanceBp() {
  const fname       = _flFrames[_flFrameIdx];
  const frameLabels = _flLabels[fname] || {};
  const cur         = _flBodyparts.indexOf(_flSelectedBp);
  for (let i = 1; i <= _flBodyparts.length; i++) {
    const next = _flBodyparts[(cur + i) % _flBodyparts.length];
    if (!frameLabels[next]) { _flSelectBp(next); return; }
  }
  // All body parts labeled on this frame → move to next frame
  if (_flFrameIdx < _flFrames.length - 1) _flShowFrame(_flFrameIdx + 1);
}
```

Use the `Edit` tool on `deeplabcut-webapp-docker/src/static/js/frame_labeler.js`. Replace:

```js
      for (let i = 1; i <= _flBodyparts.length; i++) {
        const next = _flBodyparts[(cur + i) % _flBodyparts.length];
        if (!frameLabels[next]) { _flSelectBp(next); return; }
      }
      // All body parts labeled on this frame → move to next frame
      if (_flFrameIdx < _flFrames.length - 1) _flShowFrame(_flFrameIdx + 1);
    }
```

With:

```js
      for (let i = 1; i <= _flBodyparts.length; i++) {
        const next = _flBodyparts[(cur + i) % _flBodyparts.length];
        if (!frameLabels[next]) { _flSelectBp(next); return; }
      }
    }
```

Net effect: the trailing comment line and the `if (_flFrameIdx < ...) _flShowFrame(...)` line are gone; nothing else changes.

- [ ] **Step 2: Run the source-text regression to verify it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
pytest tests/test_frame_labeler_no_auto_frame_advance.py -v
```

Expected: **PASS**.

- [ ] **Step 3: Sanity-check no other tests broke**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
pytest tests/test_frontend_assets.py -v
```

Expected: all PASS. The frontend-assets test just serves `frame_labeler.js` over HTTP and asserts 200; the deletion doesn't break anything it checks.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/static/js/frame_labeler.js
git commit -m "fix(frame-labeler): do not auto-advance frame when last BP labeled

Frame navigation belongs to the user. The fall-through inside
_flAutoAdvanceBp that called _flShowFrame once every BP on the current
frame was labeled silently moved the user off the frame they were
working on. Same-frame next-missing-BP walk is preserved."
```

---

## Task 5: Delete the auto-frame-advance in the 3D module

**Files:**
- Modify: `deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js:1629-1645` (delete the comment block and the sync-aware `curIdx`/`total`/`_flShowFrame` lines at the end of `_flAutoAdvanceBp`)

- [ ] **Step 1: Apply the deletion**

The current function body, for context:

```js
// Auto-advance to the next unlabeled body part (napari behavior)
function _flAutoAdvanceBp() {
  const fname       = _fl3dActiveFname();
  const frameLabels = _flLabels[fname] || {};
  const cur         = _flBodyparts.indexOf(_flSelectedBp);
  for (let i = 1; i <= _flBodyparts.length; i++) {
    const next = _flBodyparts[(cur + i) % _flBodyparts.length];
    if (!frameLabels[next]) { _flSelectBp(next); return; }
  }
  // All body parts labeled on this frame → move to next frame.
  // Use the right axis index for sync mode — _flFrameIdx is the
  // single-canvas axis and stays at its sync-on-time value while sync nav
  // advances _fl3dFrameNumIdx, so falling through here with the wrong
  // axis sends the user back to ~frame 1 of the frame-number list.
  const curIdx = _fl3dSyncOn ? _fl3dFrameNumIdx     : _flFrameIdx;
  const total  = _fl3dSyncOn ? _fl3dFrameNumbers.length : _flFrames.length;
  if (curIdx < total - 1) _flShowFrame(curIdx + 1);
}
```

Use the `Edit` tool on `deeplabcut-webapp-docker-supports/dlc-3D/src/static/frame_labeler_3d.js`. Replace:

```js
      for (let i = 1; i <= _flBodyparts.length; i++) {
        const next = _flBodyparts[(cur + i) % _flBodyparts.length];
        if (!frameLabels[next]) { _flSelectBp(next); return; }
      }
      // All body parts labeled on this frame → move to next frame.
      // Use the right axis index for sync mode — _flFrameIdx is the
      // single-canvas axis and stays at its sync-on-time value while sync nav
      // advances _fl3dFrameNumIdx, so falling through here with the wrong
      // axis sends the user back to ~frame 1 of the frame-number list.
      const curIdx = _fl3dSyncOn ? _fl3dFrameNumIdx     : _flFrameIdx;
      const total  = _fl3dSyncOn ? _fl3dFrameNumbers.length : _flFrames.length;
      if (curIdx < total - 1) _flShowFrame(curIdx + 1);
    }
```

With:

```js
      for (let i = 1; i <= _flBodyparts.length; i++) {
        const next = _flBodyparts[(cur + i) % _flBodyparts.length];
        if (!frameLabels[next]) { _flSelectBp(next); return; }
      }
    }
```

- [ ] **Step 2: Run the source-text regression to verify it passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_frame_labeler_3d_no_auto_frame_advance.py -v
```

Expected: **PASS**.

- [ ] **Step 3: Run the e2e tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_labeler_no_auto_frame_advance.py -v
```

Expected: both **PASS** (or both SKIP with the same fixture-unavailable reason as Task 3 step 2 — in which case the source-text test is the active guard).

- [ ] **Step 4: Sanity-check the existing e2e suite still passes**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/e2e/test_sync_frame.py -v -k "marker or f1 or f2"
```

Expected: PASS. These tests place markers and don't rely on the auto-frame-advance behavior, but they're the closest neighbors of the change so they're the most likely to surface an unintended interaction. Specifically, `test_f7_keyboard_nudge_only_when_hover_focused` (line 290) has a comment about `_flAutoAdvanceBp` switching the selected chip after placement — it still re-selects the chip explicitly via `.fl-bp-chip[data-bp="{bp}"]` click, so it must continue to pass.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/frame_labeler_3d.js
git commit -m "fix(dlc-3d frame-labeler): do not auto-advance frame when last BP labeled

Mirrors the main webapp fix. The sync-aware fall-through in
_flAutoAdvanceBp that called _flShowFrame once every BP on the current
frame was labeled silently moved the user off their working frame.
Same-frame next-missing-BP walk preserved in both sync modes."
```

---

## Self-Review Summary

- **Spec coverage:** Behavior change (Tasks 4, 5), main-webapp source-text test (Task 1), 3D source-text test (Task 2), 3D Playwright e2e for both sync modes (Task 3). Out-of-scope items (no main-webapp Playwright infra, no feature flag, no other refactors) are honored — no tasks for them.
- **Placeholder scan:** Every test step shows the full code, every edit step shows the exact before/after. No TBDs, no "similar to Task N", no "add error handling."
- **Type consistency:** `_extract_function_body` has the same signature in Tasks 1 and 2 (intentional duplication — each test stands alone, no shared helper module to avoid coupling the two codebases). `_flAutoAdvanceBp`, `_flShowFrame`, `_flBodyparts`, `_flLabels`, `_flSelectedBp`, `_flSelectBp`, `_flFrameIdx`, `_flFrames`, `_fl3dActiveFname`, `_fl3dSyncOn`, `_fl3dFrameNumIdx`, `_fl3dFrameNumbers`, `window.__fl3d.{labels,selectedBp,syncOn,frameNumberIdx}` — all spelled identically wherever referenced and all verified against the live source during plan writing.
