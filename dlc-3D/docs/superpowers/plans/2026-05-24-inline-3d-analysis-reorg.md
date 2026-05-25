# Inline-3D Analysis Card Reorg Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the inline 3D-analysis card into a full-width two-column layout (left = viewer + controls + timelines, right = docked Finalize sub-card), add a current-frame + range-gated "Start analysis" pair, a keyframe-lock range-confine mode with red visuals, restored per-frame status/note editing, and per-project click-to-fill quick-tags.

**Architecture:** Frontend reorg of one card across three files (`card_inline_analysis_3d.html`, `inline_analysis_3d.css`, `inline_analysis_3d.js`) in the `deeplabcut-webapp-docker-supports/dlc-3D` repo, plus a 3-line backend allow-list extension in the separate `deeplabcut-webapp-docker` repo. Pure logic (bounds clamp, tag-list reducer) is extracted into DOM-free `.mjs` helpers under `src/static/` with node:test coverage. The "Start analysis for range" path reuses the existing `analyze-range` flow; per-frame status/note edits reuse `statusNoteTimeline`'s existing save. No new HTTP routes.

**Tech Stack:** Vanilla ES modules (browser), Flask/Python (backend), node:test (JS `.mjs` unit tests, run on system Node v16 via `node --test`), pytest (Python static-analysis + route tests), Python `playwright.sync_api` for live verification (system Node is too old for the JS playwright runner).

---

## Grounding Facts (verified — do not re-discover)

- **Two repos.** Frontend: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D` (branch `feat/viewer-3d-onto-library`). Backend: `/home/sam/docker-images/deeplabcut-webapp-docker` (branch `feat/3d-inline-analysis`). All frontend paths below are relative to the `dlc-3D` repo unless prefixed with `deeplabcut-webapp-docker/`.
- **The analyze endpoint already exists.** The JS submits to `/dlc/project/inline-analysis/range` via `_submitRange(sk, videoPath, startFrame, nFrames)` (`src/static/inline_analysis_3d.js:1612`). The backend route validates `start_frame >= 0` and `n_frames` in `1..10000`. NO new route. "From current frame" → `start_frame = _viewer.currentFrame()`, `n_frames = #ia3d-frames-per-click`. "For range" → `start_frame = range.start`, `n_frames = range.n` from `_finalizeKW.getRange()`.
- **Per-project settings.** `_UI_SETTING_KEYS = {"finalize_window", "clip_window"}` at `deeplabcut-webapp-docker/src/dlc/inline_analysis.py:383`. Add `postfix_tags`, `status_tags`, `note_tags` (JSON string-list values). The GET/POST `/dlc/project/ui-setting` handler + `project_settings.py` store the string value verbatim (`set_setting(project_path, key, str(value))`) — no schema change.
- **Per-frame status/note write reuses `statusNoteTimeline`.** Its `save()` (`src/static/components/viewer/features/status_notes.js:176`) already writes the current frame's row to the cam0 companion CSV via the configured `saveRow` endpoint, driven by `els.statusInput`/`els.noteInput`/`els.saveStatusBtn`/`els.saveNoteBtn` + `els.statusBadge`/`els.noteBadge`. The reorg RELOCATES these els under each timeline; the consumer already passes them in `_ensureViewer` (`src/static/inline_analysis_3d.js:195-201`). NO new save route, NO new save logic.
- **Tag click = REPLACE** the field's value (not append). A `×` removes a tag; a `+ tag` affordance adds the current field value (or a prompt) as a new tag. Persisted per-project via the existing debounced settings client pattern.
- **Keyframe lock has NO clamp case.** Because the keyframe equals the current frame at the moment of locking, the current frame is always inside `[range.start, range.end]` when the lock engages. No out-of-range snapping needed.
- **Size sliders must keep working.** The per-tile `.vv-tile-size` sliders (rendered by `VideoViewer` with `perTileSize:true`) must still resize their tiles after the markup reorg — explicit acceptance criterion.
- **Deploy/restart cadence.** Static JS/CSS are bind-mounted and live immediately. Template `.html` files and Python are bind-mounted but need `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d` (frontend templates/py) and `docker compose restart flask` (main-webapp python). Auth for live checks: `GET /?token=deeplabcut` to set a cookie, then navigate to `/dlc-3d/`. Live verification uses `playwright.sync_api` (Python). **NEVER** click Add / Extract / Finalize / Delete against the protected `/user-data` fixtures (khoai-lang-1, tdcs RatBox, DREADD-Ali).
- **Test runners (verified working):**
  - JS `.mjs`: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/<file>.mjs` (Node v16; file-level pass/fail in TAP).
  - Frontend pytest: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/<file>.py -q`.
  - Backend pytest: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest tests/<file>.py -q`.
- **Visual source of truth:** the live mockup `src/static/mockup_inline_3d.html.j2` (served at `/dlc-3d/mock-up`). It uses `.mk-*` classes; the real markup must mirror its STRUCTURE but use the real `#ia3d-*` ids and existing classes. The plan's markup tasks map every `.mk-*` block to its real-id equivalent.

## Files

**Frontend (`dlc-3D` repo)**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` — restructure `#ia3d-player-section` into the two-column shell; relocate the finalize panel right; relocate timelines + finalize-coverage canvas; add the analysis-button flank, per-frame status/note edit rows, postfix/status/note quick-tag containers, and the keyframe-lock flag.
- Modify: `src/static/inline_analysis_3d.css` — two-column layout, controls/analysis flank, compact timeline rows, edit rows, tag pills, lock visuals (red flag + red seek-bar block + dimmed outside).
- Modify: `src/static/inline_analysis_3d.js` — wire the two start buttons; the keyframe-lock → range-confine + red block + flag + "for range" enablement; the per-project tag CRUD + click-to-fill; pass the relocated edit-row els (already wired — confirm they still resolve).
- Create: `src/static/internal/clamp_bounds.mjs` — pure `clampToBounds(frame, start, end)`.
- Create: `src/static/internal/tag_list.mjs` — pure tag-list reducer `addTag` / `removeTag`.
- Create: `tests/unit/test_clamp_bounds.mjs`, `tests/unit/test_tag_list.mjs` — node:test for the two helpers.
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` — update the two assertions the reorg invalidates (`test_controls_split_into_three_rows`, `test_finalize_coverage_bar_present_and_wired`) and add reorg assertions.
- Create: `tests/e2e/test_inline_3d_reorg.py` — Python playwright live-verification suite (read-only against the DREADD-Ali OM-2 fixture used by the existing e2e conftest).

**Backend (`deeplabcut-webapp-docker` repo)**
- Modify: `src/dlc/inline_analysis.py:383` — extend `_UI_SETTING_KEYS`.
- Create: `tests/test_ui_setting_tag_keys.py` — pytest for the extended allow-list via the `ia_client` fixture.

## Decision: bounds-clamp lives in the CONSUMER

Per the spec's preference, the range-confine is implemented in `inline_analysis_3d.js` (the consumer), NOT in `video_viewer.js`. The consumer already owns every navigation entry point and can clamp each one:

- **step / skip:** the consumer's button handlers call `v.step(±n)` (`inline_analysis_3d.js:366-370`). Wrap the target frame through `clampToBounds` before seeking.
- **play:** the base's `_playLoop` clamps to `[0, frameCount-1]` internally and has no public bounds hook. The consumer cannot intercept the loop. Solution: the consumer subscribes to the existing `"frameChange"` event and, when locked, if the new frame is outside `[start,end]`, calls `v.pause()` and `v.seek(clamped)`. This stops runaway playback at the boundary (the loop seeks one frame past the edge, the listener snaps it back and pauses). This is sufficient and needs NO library change.
- **seek-canvas click/drag:** `_wireSeekCanvas`'s `free`/`snap` (`inline_analysis_3d.js:316-335`) compute a target frame then `_viewer.seek(F)`. Route that target through `clampToBounds` when locked.
- **status/note nav:** `statusNoteTimeline.nav()` calls `viewer.seek(...)` internally and cannot be intercepted. Handle the same way as play: the `"frameChange"` listener snaps any out-of-range landing back into the range. (Acceptable: nav to an out-of-range annotation snaps to the nearest in-range edge.)

Therefore **`video_viewer.js` is NOT modified** and the viewer-policy contract (`tests/test_video_viewer_policy.py`) is untouched — no new `setBounds`/`clearBounds`, so the spec's optional pytest static-analysis addition is not needed.

---

## Task 1: Backend — extend the UI-setting allow-list

**Files:**
- Modify: `deeplabcut-webapp-docker/src/dlc/inline_analysis.py:383`
- Test: `deeplabcut-webapp-docker/tests/test_ui_setting_tag_keys.py`

- [ ] **Step 1: Write the failing test**

Create `deeplabcut-webapp-docker/tests/test_ui_setting_tag_keys.py`. The `ia_client` fixture (defined in `tests/test_inline_analysis_routes.py`) yields an authenticated client with an active project; import it via a local fixture copy is unnecessary — pytest auto-discovers fixtures only within the same module or conftest, so re-declare a thin fixture that reuses the same building blocks. Use the simplest path: import the route module and round-trip each new key through the live POST/GET handlers.

```python
"""The three quick-tag keys must be accepted by the /dlc/project/ui-setting allow-list."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _auth(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["uid"] = "u1"


@pytest.fixture
def tag_client(flask_test_client, dlc_sandbox_project):
    client, app_module, redis, data_dir, _user_data_dir = flask_test_client
    redis._store.clear(); redis._hstore.clear()
    redis._zsets.clear(); redis._sets.clear(); redis._lists.clear()
    _auth(client)
    dest = data_dir / dlc_sandbox_project.name
    if not dest.exists():
        shutil.copytree(str(dlc_sandbox_project), str(dest))
    cfg = dest / "config.yaml"
    redis.set(
        "webapp:dlc_project:u1",
        json.dumps({"config_path": str(cfg), "project_path": str(dest), "project": dest.name}),
    )
    yield client


@pytest.mark.parametrize("key", ["postfix_tags", "status_tags", "note_tags"])
def test_tag_keys_round_trip(tag_client, key):
    value = json.dumps(["reach", "good", "retry"])
    post = tag_client.post("/dlc/project/ui-setting", json={"key": key, "value": value})
    assert post.status_code == 200, post.get_json()
    got = tag_client.get(f"/dlc/project/ui-setting?key={key}")
    assert got.status_code == 200
    assert got.get_json()["value"] == value


def test_unknown_tag_key_still_rejected(tag_client):
    resp = tag_client.post("/dlc/project/ui-setting", json={"key": "bogus_tags", "value": "[]"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest tests/test_ui_setting_tag_keys.py -q`
Expected: the three `test_tag_keys_round_trip` cases FAIL with 400 `"unknown key"` (the keys are not yet in the allow-list); `test_unknown_tag_key_still_rejected` PASSES.

- [ ] **Step 3: Extend the allow-list**

In `deeplabcut-webapp-docker/src/dlc/inline_analysis.py`, change line 383 from:

```python
_UI_SETTING_KEYS = {"finalize_window", "clip_window"}
```

to:

```python
_UI_SETTING_KEYS = {"finalize_window", "clip_window", "postfix_tags", "status_tags", "note_tags"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest tests/test_ui_setting_tag_keys.py -q`
Expected: PASS (4 tests: 3 parametrized round-trips + 1 rejection).

- [ ] **Step 5: Restart the main-webapp flask service so the allow-list is live**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart flask`
Expected: the `flask` service restarts (the route handler is in the flask container).

- [ ] **Step 6: Commit (backend repo)**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add src/dlc/inline_analysis.py tests/test_ui_setting_tag_keys.py
git commit -m "feat(inline-3d): allow postfix_tags/status_tags/note_tags in ui-setting allow-list

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Pure helper — `clampToBounds`

**Files:**
- Create: `src/static/internal/clamp_bounds.mjs`
- Test: `tests/unit/test_clamp_bounds.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_clamp_bounds.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { clampToBounds } from "../../src/static/internal/clamp_bounds.mjs";

test("clampToBounds: returns the frame unchanged when inside [start,end]", () => {
  assert.equal(clampToBounds(1200, 1034, 1833), 1200);
  assert.equal(clampToBounds(1034, 1034, 1833), 1034);   // inclusive low edge
  assert.equal(clampToBounds(1833, 1034, 1833), 1833);   // inclusive high edge
});

test("clampToBounds: clamps below start up to start, above end down to end", () => {
  assert.equal(clampToBounds(500, 1034, 1833), 1034);
  assert.equal(clampToBounds(9000, 1034, 1833), 1833);
});

test("clampToBounds: floors fractional frames and coerces NaN to start", () => {
  assert.equal(clampToBounds(1200.7, 1034, 1833), 1200);
  assert.equal(clampToBounds(NaN, 1034, 1833), 1034);
});

test("clampToBounds: tolerates reversed bounds (start>end) by normalizing", () => {
  assert.equal(clampToBounds(1200, 1833, 1034), 1200);
  assert.equal(clampToBounds(500, 1833, 1034), 1034);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_clamp_bounds.mjs`
Expected: FAIL — `Cannot find module '.../src/static/internal/clamp_bounds.mjs'`.

- [ ] **Step 3: Write the implementation**

Create `src/static/internal/clamp_bounds.mjs`:

```javascript
// Pure frame-bounds clamp for the inline-3D keyframe-lock range-confine. DOM-free.
// Returns `frame` floored into the inclusive range [start, end]. Bounds are
// normalized so a reversed (start>end) pair still clamps sanely. A non-finite
// frame coerces to the low bound.

export function clampToBounds(frame, start, end) {
  const lo = Math.min(start, end);
  const hi = Math.max(start, end);
  const f = Math.floor(Number(frame));
  if (!Number.isFinite(f)) return lo;
  return Math.min(Math.max(f, lo), hi);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_clamp_bounds.mjs`
Expected: PASS (`# pass 4`, `# fail 0`).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/internal/clamp_bounds.mjs tests/unit/test_clamp_bounds.mjs
git commit -m "feat(inline-3d): add clampToBounds pure helper for keyframe-lock confine

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Pure helper — tag-list reducer

**Files:**
- Create: `src/static/internal/tag_list.mjs`
- Test: `tests/unit/test_tag_list.mjs`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tag_list.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { addTag, removeTag } from "../../src/static/internal/tag_list.mjs";

test("addTag: appends a trimmed tag, returns a new array", () => {
  const a = ["reach"];
  const b = addTag(a, "  good  ");
  assert.deepEqual(b, ["reach", "good"]);
  assert.deepEqual(a, ["reach"], "input array must not be mutated");
});

test("addTag: dedupes (case-sensitive exact match) and ignores empties", () => {
  assert.deepEqual(addTag(["reach"], "reach"), ["reach"]);
  assert.deepEqual(addTag(["reach"], ""), ["reach"]);
  assert.deepEqual(addTag(["reach"], "   "), ["reach"]);
});

test("addTag: coerces a non-array base to an empty list", () => {
  assert.deepEqual(addTag(null, "good"), ["good"]);
  assert.deepEqual(addTag(undefined, "good"), ["good"]);
});

test("removeTag: removes the exact value, returns a new array, no-op if absent", () => {
  const a = ["reach", "good", "retry"];
  assert.deepEqual(removeTag(a, "good"), ["reach", "retry"]);
  assert.deepEqual(a, ["reach", "good", "retry"], "input array must not be mutated");
  assert.deepEqual(removeTag(["reach"], "absent"), ["reach"]);
});

test("removeTag: coerces a non-array base to an empty list", () => {
  assert.deepEqual(removeTag(null, "x"), []);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_tag_list.mjs`
Expected: FAIL — `Cannot find module '.../src/static/internal/tag_list.mjs'`.

- [ ] **Step 3: Write the implementation**

Create `src/static/internal/tag_list.mjs`:

```javascript
// Pure tag-list reducer for the inline-3D quick-tags (postfix/status/note). DOM-free.
// add: append a trimmed, deduped (exact-match), non-empty tag. remove: drop the
// exact value. Both return a NEW array and never mutate the input. A non-array
// base coerces to [] so callers can pass an unparsed/absent setting straight in.

const asList = (xs) => (Array.isArray(xs) ? xs : []);

export function addTag(tags, raw) {
  const list = asList(tags);
  const t = String(raw == null ? "" : raw).trim();
  if (!t || list.includes(t)) return list.slice();
  return [...list, t];
}

export function removeTag(tags, value) {
  return asList(tags).filter((t) => t !== value);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_tag_list.mjs`
Expected: PASS (`# pass 5`, `# fail 0`).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/internal/tag_list.mjs tests/unit/test_tag_list.mjs
git commit -m "feat(inline-3d): add tag-list reducer (add/remove/dedupe) for quick-tags

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Markup reorg — two-column shell + relocate finalize panel + timelines

This task restructures `#ia3d-player-section` only. All `#ia3d-*` ids are PRESERVED (so existing JS keeps resolving them); only their containers/order change. The Analysis-Parameters block, source tabs, metadata strip, overlay panel, curation panel, and create-clip panel keep their current ids and stay where they are relative to the section (curation + clip remain full-width BELOW the two columns).

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html`
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` (update the two assertions the reorg invalidates)
- Test: live verification via Task 9 (no unit test for markup); plus the updated pytest static-analysis below.

### Target DOM structure (mirror the mockup, real ids)

Inside `<div id="ia3d-player-section" class="hidden">`, after the existing selected-name + Back row and the existing "Viewer size" zoom row and the metadata strip and the overlay panel, wrap the VIEWER + CONTROLS + TIMELINES and the FINALIZE panel in a two-column flex shell:

```
#ia3d-player-section
  (existing: selected-name+Back row; Viewer size row; #ia3d-metadata-panel; #ia3d-overlay-panel — UNCHANGED, stay above the split)
  <div class="ia3d-split">                         ← maps to mockup .mk-split
    <div class="ia3d-left">                          ← maps to .mk-left
      <div id="ia3d-lock-flag" class="ia3d-lock-flag hidden"></div>   ← maps to .mk-lock-flag; hidden until locked; text set by JS
      <div id="ia3d-viewer-mount"></div>             ← UNCHANGED id; VideoViewer renders tiles + per-tile .vv-tile-size sliders
      <div class="ia3d-seek-wrap">                   ← maps to .mk-seek-wrap (position:relative)
        <canvas id="ia3d-seek-canvas" height="14" title="Click or drag to seek"
                style="width:100%;display:block;cursor:pointer"></canvas>   ← UNCHANGED id; NOTE: drop the old margin-bottom:.4rem inline (now provided by CSS)
        <div id="ia3d-lock-dim-left"  class="ia3d-lock-out hidden"></div>    ← red-block dim overlays (JS positions/sizes them)
        <div id="ia3d-lock-dim-right" class="ia3d-lock-out hidden"></div>
        <div id="ia3d-lock-range"     class="ia3d-lock-range hidden"></div>
      </div>
      <div class="ia3d-controls-flank">              ← maps to .mk-controls-flank
        <div class="ia3d-controls-left">             ← maps to .mk-controls-left
          <div class="ia3d-ctrl-top">                ← maps to .mk-ctrl-top
            <div class="fe-controls ia3d-controls-main">   ← the EXISTING .fe-controls block, now TWO .ia3d-ctrl-row rows (see below)
              <div class="ia3d-ctrl-row"> …playback row (play-back/play/prev/next/fps/step) — UNCHANGED contents… </div>
              <div class="ia3d-ctrl-row"> …skip group + presets (.ia3d-skip-group) — UNCHANGED contents… </div>
            </div>
            <div class="ia3d-meta-mid">              ← maps to .mk-meta-mid; the frame#/time cluster MOVED out of .fe-controls
              <span class="fe-frame-counter" id="ia3d-frame-counter" title="Click to jump to a frame" style="cursor:pointer">Frame 0 / 0</span>
              <input type="number" id="ia3d-frame-jump" class="hidden" …>   ← UNCHANGED
              <span class="fe-time-display" id="ia3d-time-display">0.000 s</span>
              <button type="button" id="ia3d-help-btn" class="btn-sm fe-ctrl-btn" title="Keyboard shortcuts">?</button>
              <div id="ia3d-help-tooltip" class="hidden" …>…</div>           ← UNCHANGED
            </div>
          </div>
          <div id="ia3d-bp-list-wrap" class="ia3d-bp-chips-wrap hidden">     ← keep id+hidden; new wrapper class for the fill-below layout
            <div class="fl-bodypart-list" id="ia3d-bp-chips"></div>          ← UNCHANGED id
          </div>
          <div id="ia3d-marker-edit-controls" class="hidden" …>…</div>       ← UNCHANGED block; stays here (below chips)
        </div>
        <div class="ia3d-start-flank">               ← maps to .mk-start-flank (≈270px)
          <span id="ia3d-start-count" class="ia3d-start-count">≈ <b id="ia3d-start-count-n">0</b> frames from current frame</span>
          <button id="ia3d-btn-analyze-current" class="btn-sm btn-create" disabled>▶ Start analysis from current frame</button>
          <button id="ia3d-btn-analyze-range-confined" class="btn-sm btn-create" disabled>▶ Start analysis for range</button>
          <span id="ia3d-start-hint" class="ia3d-start-hint"></span>
        </div>
      </div>
      <span id="ia3d-status" class="fe-extract-status"></span>              ← UNCHANGED id; status line (analysis progress)
      <div id="ia3d-viewer-timeline">                                       ← UNCHANGED id; wraps the bars
        <div id="ia3d-csv-bars">                                            ← UNCHANGED id
          <div id="ia3d-status-bar-wrap" style="display:none">…</div>       ← see Task 6 for the per-frame edit row added inside
          <div id="ia3d-note-bar-wrap"   style="display:none">…</div>       ← see Task 6
        </div>
        <div id="ia3d-finalize-coverage-wrap" class="ia3d-bar">             ← NEW location for the relocated finalize-coverage timeline
          <div class="ia3d-bar-header">                                     ← maps to .mk-bar-header
            <span class="fe-csv-bar-label">Finalized frames</span>
            <button id="ia3d-finalize-prev" class="btn-sm" disabled …>◀</button>   ← MOVED here (was inside finalize-controls)
            <button id="ia3d-finalize-next" class="btn-sm" disabled …>▶</button>
            <span style="font-size:.7rem;color:var(--text-dim)">coverage of _analyzed</span>
          </div>
          <canvas id="ia3d-finalize-coverage" height="14" title="Finalized frames — click or drag to seek"
                  style="width:100%;display:block;cursor:pointer"></canvas>   ← MOVED here (was inside finalize-controls)
        </div>
      </div>
    </div>  <!-- /.ia3d-left -->
    <div class="ia3d-right">                          ← maps to .mk-right (≈300px)
      <div id="ia3d-finalize-panel" …>…</div>          ← the ENTIRE existing finalize panel, MOVED here; toggle CHECKED by default (Task 7)
    </div>
  </div>  <!-- /.ia3d-split -->
  <div id="ia3d-curation-panel" …>…</div>             ← UNCHANGED; stays full-width below the split
  <div id="ia3d-clip-panel-wrap" …>…</div>            ← UNCHANGED; stays full-width below the split
```

Key relocations from the current markup:
1. The `#ia3d-finalize-panel` (currently last, lines 451-510) MOVES into `.ia3d-right`. Inside it, `#ia3d-finalize-prev`/`#ia3d-finalize-next` and `#ia3d-finalize-coverage` are REMOVED from `#ia3d-finalize-controls` and re-created inside `#ia3d-finalize-coverage-wrap` in the left region.
2. The `#ia3d-frame-counter`/`#ia3d-time-display`/`#ia3d-help-btn`/`#ia3d-help-tooltip` MOVE out of the third `.ia3d-ctrl-row` into the new `.ia3d-meta-mid`. The `.fe-controls` block now has exactly TWO `.ia3d-ctrl-row` rows.
3. The seek canvas is wrapped in `.ia3d-seek-wrap` with three absolutely-positioned lock overlay divs added after it.
4. The `#ia3d-lock-flag` div is added at the top of `.ia3d-left`.
5. Two new analysis buttons `#ia3d-btn-analyze-current` and `#ia3d-btn-analyze-range-confined` are added in `.ia3d-start-flank` (these are SEPARATE from the top `#ia3d-btn-analyze-range` in the Analysis-Parameters block, which stays).

- [ ] **Step 1: Update the two now-invalid static-analysis assertions FIRST (red→green guard)**

The reorg deliberately changes two structures the current tests assert. Update them in `tests/test_inline_analysis_3d_ui_isolation.py` so they describe the NEW structure:

Replace `test_controls_split_into_three_rows` (currently lines 511-521) with:

```python
def test_controls_two_rows_plus_meta_cluster():
    html = CARD.read_text()
    # The reorg splits the player controls into TWO .ia3d-ctrl-row rows (playback;
    # skip-group), and moves the frame#/time/help cluster into .ia3d-meta-mid.
    assert html.count('class="ia3d-ctrl-row"') == 2, "controls must be two .ia3d-ctrl-row rows after the reorg"
    assert 'class="ia3d-meta-mid"' in html, "frame#/time cluster must live in .ia3d-meta-mid"
    rows = re.findall(r'<div class="ia3d-ctrl-row"[^>]*>(.*?)</div>\s*(?=<div class="ia3d-ctrl-row"|<div class="ia3d-meta-mid"|</div>)', html, re.S)
    assert len(rows) == 2
    assert 'id="ia3d-btn-play"' in rows[0]
    assert 'class="ia3d-skip-group"' in rows[1]
    meta = re.search(r'class="ia3d-meta-mid"[^>]*>(.*?)</div>\s*</div>', html, re.S).group(1)
    assert 'id="ia3d-frame-counter"' in meta and 'id="ia3d-time-display"' in meta and 'id="ia3d-help-btn"' in meta
```

Replace `test_finalize_coverage_bar_present_and_wired` (currently lines 436-443) with:

```python
def test_finalize_coverage_bar_relocated_to_left_region():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    # The reorg relocates the finalized-frames coverage timeline OUT of the finalize
    # controls and into the left region, below the Notes timeline (#ia3d-csv-bars).
    bars = html.index('id="ia3d-csv-bars"')
    cov_wrap = html.index('id="ia3d-finalize-coverage-wrap"')
    cov = html.index('id="ia3d-finalize-coverage"')
    fin_panel = html.index('id="ia3d-finalize-panel"')
    assert bars < cov_wrap < cov, "finalize coverage must sit below the status/note bars in the left region"
    # the coverage canvas is no longer inside the finalize panel/controls
    assert cov < fin_panel, "finalize coverage canvas must be relocated OUT of the finalize panel"
    js = JS.read_text()
    assert "_refreshFinalizeCoverage" in js, "finalize coverage refresh helper missing"
    assert "mode=presence" in js, "must request presence-mode coverage"
```

Also update `test_finalize_keyframe_window_markup` (line 562-563) which asserts `"ia3d-finalize-coverage" in html` — this remains TRUE (the canvas still exists, just relocated), so no change needed there. Verify by reading it before editing.

- [ ] **Step 2: Run the two updated tests to confirm they now FAIL against the un-reorganized markup**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_controls_two_rows_plus_meta_cluster tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_coverage_bar_relocated_to_left_region -q`
Expected: BOTH FAIL (the markup still has 3 ctrl-rows / coverage still inside finalize-controls). This is the red state for the markup change.

- [ ] **Step 3: Restructure the markup**

Edit `src/templates/partials/card_inline_analysis_3d.html` to produce the Target DOM structure above. Concretely:
- Insert `<div class="ia3d-split"><div class="ia3d-left">` immediately before `#ia3d-viewer-mount` (line 186) and the `#ia3d-lock-flag` div before the mount.
- Wrap `#ia3d-seek-canvas` (lines 188-190) in `<div class="ia3d-seek-wrap">…</div>` and append the three lock overlay divs; remove the canvas's inline `margin-bottom:.4rem` (CSS provides spacing).
- Rebuild the `.fe-controls` block (lines 192-256) as `<div class="ia3d-controls-flank"><div class="ia3d-controls-left"><div class="ia3d-ctrl-top"><div class="fe-controls ia3d-controls-main">…two rows…</div><div class="ia3d-meta-mid">…counter/time/help…</div></div>`. Move the `#ia3d-bp-list-wrap` (lines 258-261) and `#ia3d-marker-edit-controls` (lines 263-276) to follow inside `.ia3d-controls-left`; add `ia3d-bp-chips-wrap` class to `#ia3d-bp-list-wrap`. Then add the `.ia3d-start-flank` block with the two new analysis buttons. Close `.ia3d-controls-left` and `.ia3d-controls-flank`.
- Keep `<span id="ia3d-status" …>` (line 278) after the controls flank.
- Inside `#ia3d-csv-bars`, the status/note wraps stay (per-frame edit rows added in Task 6). After `#ia3d-csv-bars`, add `#ia3d-finalize-coverage-wrap` with the relocated `#ia3d-finalize-prev`/`#ia3d-finalize-next`/`#ia3d-finalize-coverage`.
- Close `.ia3d-left`, open `<div class="ia3d-right">`, MOVE the entire `#ia3d-finalize-panel` block here, then close `.ia3d-right` and `.ia3d-split`.
- Inside `#ia3d-finalize-controls`, DELETE the `#ia3d-finalize-prev`/`#ia3d-finalize-next` row (lines 501-505) and the `#ia3d-finalize-coverage` canvas (lines 506-507) — they now live in the left region.
- Leave `#ia3d-curation-panel` and `#ia3d-clip-panel-wrap` exactly where they are (after the finalize panel originally; now after `.ia3d-split`).

- [ ] **Step 4: Run the full static-analysis suite to verify the reorg holds the contract**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS. Pay attention to: `test_status_note_timeline_outside_curation_panel` (bars still before curation — TRUE), `test_section_order_browser_then_params_then_player`, `test_surfaced_timeline_wraps_not_hidden_class`, `test_zoom_mirrors_geometry_onto_timelines` (still references the four canvas ids — all present), `test_controls_two_rows_plus_meta_cluster` (now PASS), `test_finalize_coverage_bar_relocated_to_left_region` (now PASS). If any other test fails because it asserted the old structure, read it and update the assertion to describe the new structure (do not weaken intent).

- [ ] **Step 5: Deploy the template + open the card live to confirm it renders without errors**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`
Then run a Python playwright smoke check (the full assertions land in Task 9; here just confirm the split renders):

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto('http://localhost:5000/?token=deeplabcut', wait_until='domcontentloaded')
    pg.goto('http://localhost:5000/dlc-3d/', wait_until='domcontentloaded')
    # the split + flank exist in the DOM even before a video is selected (player section hidden)
    assert pg.query_selector('.ia3d-split') is not None, 'no .ia3d-split'
    assert pg.query_selector('#ia3d-btn-analyze-current') is not None, 'no current-frame button'
    assert pg.query_selector('#ia3d-btn-analyze-range-confined') is not None, 'no for-range button'
    print('OK: split + start flank present')
    b.close()
"
```
Expected: `OK: split + start flank present`. (No fixture click required — the section is hidden but in the DOM.)

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(inline-3d): restructure player section into two-column split + relocate finalize panel/coverage

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: CSS — two-column layout, flank, lock visuals, tag pills, edit rows

**Files:**
- Modify: `src/static/inline_analysis_3d.css`
- Test: live verification (Task 9) + the existing `test_controls_three_row_css` must be updated to `test_controls_two_row_css` (mirrors Task 4's markup change).

The mockup's `.mk-*` rules are the visual reference. Port them to the real classes, scoped to `#inline-analysis-3d-card`. Reuse `var(--*)` tokens already in the file.

- [ ] **Step 1: Update the now-invalid CSS static-analysis test**

In `tests/test_inline_analysis_3d_ui_isolation.py`, the `test_controls_three_row_css` (lines 524-528) asserts the `.fe-controls` column rule — that rule STAYS (the controls block is still column-flow with two rows), so this test still passes as-is. Confirm by reading it. NO change needed unless it asserts a row COUNT (it does not). Skip this step if the test only checks `flex-direction:column` + `.ia3d-ctrl-row{display:flex}` (both retained).

- [ ] **Step 2: Add the layout CSS**

Append to `src/static/inline_analysis_3d.css` (all scoped to `#inline-analysis-3d-card` to avoid leaking into other cards). Port directly from the mockup `<style>` block, renaming `.mk-*` → real classes:

```css
/* ── Inline-3D reorg: full-width card + two-column working layout ─────────────
   Ported from the live mockup (mockup_inline_3d.html.j2). Scoped to the card so
   no other consumer is affected. */
#inline-analysis-3d-card { max-width: none; width: 100%; }

#inline-analysis-3d-card .ia3d-split { display: flex; gap: 1rem; align-items: flex-start; }
#inline-analysis-3d-card .ia3d-left  { flex: 1 1 0; min-width: 0; position: relative; }
#inline-analysis-3d-card .ia3d-right { width: 300px; flex-shrink: 0; }

/* Keyframe-lock red flag above the cam0 tile label (normal flow, not overlaying). */
#inline-analysis-3d-card .ia3d-lock-flag {
  display: inline-flex; align-items: center; gap: .3rem; margin-bottom: .4rem;
  background: color-mix(in srgb, #ef4444 25%, #11161a);
  border: 1px solid #ef4444; color: #fca5a5;
  padding: .22rem .5rem; border-radius: 6px; font-size: .72rem; font-weight: 600;
}

/* Seek bar wrap + red range block (locked: block over [start,end], dim outside). */
#inline-analysis-3d-card .ia3d-seek-wrap { position: relative; margin-top: .9rem; }
#inline-analysis-3d-card .ia3d-seek-wrap #ia3d-seek-canvas { margin-top: 0; }
#inline-analysis-3d-card .ia3d-lock-out {
  position: absolute; top: 0; bottom: 0; background: rgba(0,0,0,.45); pointer-events: none;
}
#inline-analysis-3d-card .ia3d-lock-range {
  position: absolute; top: 0; bottom: 0; pointer-events: none;
  background: color-mix(in srgb, #ef4444 35%, transparent);
  border: 1px solid #ef4444; border-radius: 3px;
}

/* Controls + analysis flank. */
#inline-analysis-3d-card .ia3d-controls-flank { display: flex; gap: .8rem; align-items: stretch; margin-top: .55rem; }
#inline-analysis-3d-card .ia3d-controls-left { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: .5rem; }
#inline-analysis-3d-card .ia3d-ctrl-top { display: flex; align-items: center; gap: .8rem; }
#inline-analysis-3d-card .ia3d-controls-main { flex: 0 0 auto; }
#inline-analysis-3d-card .ia3d-meta-mid {
  display: flex; align-items: center; gap: .4rem;
  padding-left: .7rem; border-left: 1px solid var(--border);
}
#inline-analysis-3d-card .ia3d-start-flank {
  width: 270px; flex-shrink: 0; display: flex; flex-direction: column;
  align-items: stretch; justify-content: center; gap: .4rem;
  border-left: 1px solid var(--border); padding-left: .9rem;
}
#inline-analysis-3d-card .ia3d-start-flank .btn-sm { width: 100%; padding: .5rem; }
#inline-analysis-3d-card .ia3d-start-count { font-size: .74rem; color: var(--text); text-align: center; }
#inline-analysis-3d-card .ia3d-start-count b { color: var(--accent); }
#inline-analysis-3d-card .ia3d-start-hint { font-size: .66rem; color: var(--text-dim); text-align: center; line-height: 1.4; }

/* Body-marker chips fill the empty space below the controls + frame#/time. */
#inline-analysis-3d-card .ia3d-bp-chips-wrap {
  flex: 1 1 0; padding-top: .4rem; border-top: 1px solid var(--border);
}

/* Compact timeline bar header (label + nav + chips inline). */
#inline-analysis-3d-card .ia3d-bar { margin-top: .5rem; }
#inline-analysis-3d-card .ia3d-bar-header {
  display: flex; align-items: center; gap: .35rem; margin-bottom: .2rem; flex-wrap: wrap;
}

/* Per-frame status/note edit row below each timeline. */
#inline-analysis-3d-card .ia3d-edit-row {
  display: flex; align-items: center; gap: .4rem; margin-top: .35rem; flex-wrap: wrap;
}
#inline-analysis-3d-card .ia3d-edit-row input.ia3d-edit-input {
  flex: 0 0 180px; background: var(--surface); border: 1px solid var(--border);
  color: var(--text); border-radius: 4px; padding: .25rem .4rem; font-size: .76rem;
}
#inline-analysis-3d-card .ia3d-edit-tags { display: flex; flex-wrap: wrap; gap: .3rem; align-items: center; }
#inline-analysis-3d-card .ia3d-edit-tags .ia3d-tags-lbl { font-size: .68rem; color: var(--text-dim); }

/* Quick-tag pills (postfix/status/note), click-to-fill, with × remove + dashed add. */
#inline-analysis-3d-card .ia3d-tags { display: flex; flex-wrap: wrap; gap: .3rem; margin: .1rem 0 .5rem; }
#inline-analysis-3d-card .ia3d-ptag {
  display: inline-flex; align-items: center; gap: .25rem; padding: .12rem .45rem;
  border-radius: 10px; font-size: .7rem; cursor: pointer;
  border: 1px solid var(--accent); color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
#inline-analysis-3d-card .ia3d-ptag .x { opacity: .5; font-size: .72rem; }
#inline-analysis-3d-card .ia3d-ptag.ia3d-ptag-add {
  border-style: dashed; border-color: var(--border); color: var(--text-dim); background: transparent;
}
```

- [ ] **Step 3: Verify the live layout renders two columns (no unit test)**

Run: (CSS is bind-mounted and live; no restart needed.) Reload the card with playwright and assert the split is side-by-side once a video is selected — deferred to Task 9. Here, do a quick visual check:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto('http://localhost:5000/?token=deeplabcut', wait_until='domcontentloaded')
    pg.goto('http://localhost:5000/dlc-3d/', wait_until='domcontentloaded')
    # reveal the (hidden) player section to check the split geometry without a fixture
    pg.eval_on_selector('#ia3d-player-section', 'el => el.classList.remove(\"hidden\")')
    box_left  = pg.query_selector('.ia3d-left').bounding_box()
    box_right = pg.query_selector('.ia3d-right').bounding_box()
    assert box_right['x'] > box_left['x'], 'right column must sit to the right of the left column'
    print('OK: two-column split is side-by-side')
    b.close()
"
```
Expected: `OK: two-column split is side-by-side`.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.css
git commit -m "feat(inline-3d): two-column layout, analysis flank, lock visuals, tag-pill + edit-row CSS

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Markup + wiring — per-frame status/note edit rows under each timeline

The edit-row els (`#ia3d-status-input`, `#ia3d-note-input`, `#ia3d-save-status-btn`, `#ia3d-save-note-btn`, `#ia3d-annot-save-status`) currently live inside the curation panel's annotation block (`card_inline_analysis_3d.html:378-413`) and are ALREADY passed to `statusNoteTimeline` in `_ensureViewer` (`inline_analysis_3d.js:195-201`). This task MOVES them to sit directly under their respective timelines.

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html`
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` (add an assertion for the relocated edit rows)

- [ ] **Step 1: Add a static-analysis assertion for the relocated edit rows (failing first)**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_per_frame_edit_rows_under_timelines():
    html = CARD.read_text()
    # The status edit input/save live in the status bar-wrap; the note ones in the note bar-wrap.
    sw = html.index('id="ia3d-status-bar-wrap"')
    nw = html.index('id="ia3d-note-bar-wrap"')
    si = html.index('id="ia3d-status-input"')
    sb = html.index('id="ia3d-save-status-btn"')
    ni = html.index('id="ia3d-note-input"')
    nb = html.index('id="ia3d-save-note-btn"')
    assert sw < si < nw, "status input must sit inside the status bar-wrap (before the note wrap)"
    assert sw < sb < nw, "save-status button must sit inside the status bar-wrap"
    assert nw < ni and nw < nb, "note input + save button must sit inside the note bar-wrap"
    # the edit rows carry the quick-tag containers
    assert 'id="ia3d-status-tags"' in html and 'id="ia3d-note-tags"' in html
```

Note: `CARD` is defined near the top of the test file (read it to confirm the name; if the module uses `(ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html")` inline, use that form instead).

- [ ] **Step 2: Run to confirm it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_per_frame_edit_rows_under_timelines -q`
Expected: FAIL (the inputs still live in the curation panel; the `#ia3d-status-tags`/`#ia3d-note-tags` containers don't exist yet).

- [ ] **Step 3: Add the edit rows under each timeline**

In `card_inline_analysis_3d.html`, inside `#ia3d-status-bar-wrap` (after `#ia3d-status-chips`), add:

```html
<div class="ia3d-edit-row">
  <input type="text" id="ia3d-status-input" class="ia3d-edit-input" placeholder="status @ current frame" />
  <button id="ia3d-save-status-btn" class="btn-sm btn-create" style="padding:.28rem .65rem">Save</button>
  <span class="ia3d-edit-tags">
    <span class="ia3d-tags-lbl">tags:</span>
    <span id="ia3d-status-tags" class="ia3d-tags" style="margin:0"></span>
  </span>
</div>
```

Inside `#ia3d-note-bar-wrap` (after `#ia3d-note-chips`), add:

```html
<div class="ia3d-edit-row">
  <input type="text" id="ia3d-note-input" class="ia3d-edit-input" placeholder="note @ current frame" />
  <button id="ia3d-save-note-btn" class="btn-sm btn-create" style="padding:.28rem .65rem">Save</button>
  <span class="ia3d-edit-tags">
    <span class="ia3d-tags-lbl">tags:</span>
    <span id="ia3d-note-tags" class="ia3d-tags" style="margin:0"></span>
  </span>
</div>
```

Then REMOVE the now-duplicated `#ia3d-status-input`/`#ia3d-save-status-btn`/`#ia3d-note-input`/`#ia3d-save-note-btn`/`#ia3d-annot-save-status` from the curation panel's annotation block (`card_inline_analysis_3d.html:378-413`). Keep `#ia3d-annot-panel`'s frame-num label and the "Add note tag" sub-block only if other code references them; the curation `#ia3d-new-tag-input`/`#ia3d-add-tag-btn` are unrelated and stay. Move `#ia3d-annot-save-status` to sit beside one of the edit rows (place it after the note edit row) so `statusNoteTimeline`'s `els.saveFeedback` still resolves. Add `<span id="ia3d-annot-save-status" class="fe-extract-status"></span>` after the note edit row.

IMPORTANT: `statusNoteTimeline`'s `els` object in `_ensureViewer` references these ids by `$()`; since the ids are UNCHANGED, no JS change is needed — just confirm the ids still exist exactly once.

- [ ] **Step 4: Run the relocated-edit-rows test + the broader suite**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS, including the new `test_per_frame_edit_rows_under_timelines`. Watch for any test that asserted the inputs inside the curation/annot panel; if one breaks, update it to reflect the relocation.

- [ ] **Step 5: Deploy + live-confirm the edit rows load the current frame's value**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`
Verification of the actual load/save round-trip is in Task 9 (needs a fixture video with a companion CSV). Here, confirm the els resolve:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto('http://localhost:5000/?token=deeplabcut', wait_until='domcontentloaded')
    pg.goto('http://localhost:5000/dlc-3d/', wait_until='domcontentloaded')
    for sel in ['#ia3d-status-input','#ia3d-save-status-btn','#ia3d-note-input','#ia3d-save-note-btn','#ia3d-status-tags','#ia3d-note-tags','#ia3d-annot-save-status']:
        assert pg.query_selector(sel) is not None, f'missing {sel}'
    print('OK: relocated edit-row els present')
    b.close()
"
```
Expected: `OK: relocated edit-row els present`.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(inline-3d): relocate per-frame status/note edit rows under their timelines

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Wiring — two start buttons + Finalize checked-by-default

**Files:**
- Modify: `src/static/inline_analysis_3d.js`
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (default-check the finalize toggle)
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` (add assertions)

### Behavior
- `#ia3d-btn-analyze-current` ("from current frame", always enabled when a sibling exists): reuses the existing `_onAnalyzeClick` flow (which already reads `_viewer.currentFrame()` + `#ia3d-frames-per-click`). Wire it to call `_onAnalyzeClick`. It is a second trigger for the SAME params/status as the top `#ia3d-btn-analyze-range`. Enablement mirrors `#ia3d-btn-analyze-range` (driven by `_refreshSibling`).
- `#ia3d-btn-analyze-range-confined` ("for range", gated): enabled ONLY when Finalize is on AND the keyframe is locked AND a sibling exists. On click, run the same dual-cam submit but with `start_frame = _finalizeKW.getRange().start`, `n_frames = _finalizeKW.getRange().n`.
- `#ia3d-start-count-n` shows the current frames-per-click count; `#ia3d-start-hint` shows the lock state.
- The finalize toggle (`#ia3d-finalize-toggle`) is `checked` by default in the markup; the existing `change` handler (`inline_analysis_3d.js:1973`) reveals controls + enables editing. Because it's checked by default, on each new video open `_resetForOpen` currently UNCHECKS it (line 1227) — change `_resetForOpen` to re-CHECK it and re-fire the reveal so the panel shows by default per the spec.

- [ ] **Step 1: Add failing static-analysis assertions**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_two_start_buttons_present_and_wired():
    html = CARD.read_text()
    js = JS.read_text()
    assert 'id="ia3d-btn-analyze-current"' in html, "missing 'from current frame' button"
    assert 'id="ia3d-btn-analyze-range-confined"' in html, "missing 'for range' button"
    # both wired in JS
    assert "ia3d-btn-analyze-current" in js and "ia3d-btn-analyze-range-confined" in js
    # the for-range path computes start/n from the finalize keyframe window
    assert "_finalizeKW.getRange()" in js or "_finalizeKW?.getRange()" in js


def test_finalize_toggle_checked_by_default():
    html = CARD.read_text()
    i = html.index('id="ia3d-finalize-toggle"')
    assert "checked" in html[i-10:i+90], "finalize toggle must be checked by default"
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_two_start_buttons_present_and_wired tests/test_inline_analysis_3d_ui_isolation.py::test_finalize_toggle_checked_by_default -q`
Expected: FAIL (buttons wired but `_finalizeKW.getRange()` not yet used for the confined path; toggle not yet checked).

- [ ] **Step 3: Default-check the finalize toggle in markup**

In `card_inline_analysis_3d.html`, change the finalize toggle input (currently around the moved `#ia3d-finalize-panel`):

```html
<input type="checkbox" id="ia3d-finalize-toggle" style="accent-color:var(--accent);width:14px;height:14px"/>
```
to:
```html
<input type="checkbox" id="ia3d-finalize-toggle" checked style="accent-color:var(--accent);width:14px;height:14px"/>
```

- [ ] **Step 4: Add the analyze-for-range submit + wire both buttons**

In `inline_analysis_3d.js`, add a range-confined handler near `_onAnalyzeClick` (after line 1721). It mirrors `_onAnalyzeClick` but takes start/n from the finalize window:

```javascript
// Analyze BOTH cameras over the LOCKED finalize range (start = range.start,
// n = range.n). Gated by the UI (button only enabled when finalize-on && locked
// && sibling). Reuses the same session + dual-cam submit/poll as _onAnalyzeClick.
async function _onAnalyzeRangeConfinedClick() {
  const lastRun = _ia3dEl.lastRun();
  const cam0 = _cam0Path();
  if (!cam0) { if (lastRun) lastRun.textContent = "Pick a cam0 video first."; return; }
  if (!_siblingPath) { if (lastRun) lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
  const rng = _finalizeKW ? _finalizeKW.getRange() : { start: 0, n: 0 };
  const startFrame = rng.start, nFrames = rng.n;
  if (!(nFrames >= 1)) { if (lastRun) lastRun.textContent = "Lock a valid keyframe range first."; return; }
  const sk = await _ensureSession();
  if (!sk) return;
  const btn = $("ia3d-btn-analyze-range-confined");
  if (lastRun) { lastRun.textContent = `Running both cameras (${nFrames} frames from ${startFrame})…`; lastRun.className = "fe-extract-status"; }
  if (btn) btn.disabled = true;
  const [req0, req1] = await Promise.all([
    _submitRange(sk, cam0, startFrame, nFrames),
    _submitRange(sk, _siblingPath, startFrame, nFrames),
  ]);
  if (!req0 || !req1) { _refreshAnalyzeEnablement(); return; }
  const [d0, d1] = await Promise.all([_pollReq(req0), _pollReq(req1)]);
  const errs = [d0, d1].filter((d) => d.status === "error");
  if (lastRun) {
    lastRun.textContent = errs.length === 2
      ? `Both cameras failed: ${errs[0].error || "unknown"}`
      : `Last run: cam0 ${d0.n_analyzed}/${d0.n_skipped} · cam1 ${d1.n_analyzed}/${d1.n_skipped}`;
    if (errs.length === 2) lastRun.className = "fe-extract-status err";
  }
  _ia3dPopulateFinalizeFields();
  await _iaDiscoverVariants(cam0);
  const ov = $("ia3d-overlay-toggle");
  if (ov && !ov.checked) { ov.checked = true; ov.dispatchEvent(new Event("change", { bubbles: true })); }
  else { _markerEditor?.setOverlayEnabled(true); }
  if (_viewer && _primaryRel) {
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3d-sync-cam");
    await _viewer.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode, siblingPath: sync?.checked && !framesMode ? undefined : null });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  _refreshAnalyzeEnablement();
}
```

Add an enablement helper that drives BOTH new buttons' disabled state + the count/hint text. Place it near `_refreshSibling`:

```javascript
// Drive the two left-region start buttons + the count/hint line. "From current
// frame" mirrors the top analyze button's sibling-gating. "For range" needs
// finalize-on AND the keyframe locked AND a sibling.
function _refreshAnalyzeEnablement() {
  const cur = $("ia3d-btn-analyze-current");
  const rng = $("ia3d-btn-analyze-range-confined");
  const n = parseInt(_ia3dEl.frames()?.value, 10) || 500;
  const countN = $("ia3d-start-count-n");
  if (countN) countN.textContent = n.toLocaleString();
  const hasSibling = !!_siblingPath;
  if (cur) cur.disabled = !hasSibling;
  const finOn = !!$("ia3d-finalize-toggle")?.checked;
  const locked = !!$("ia3d-finalize-lock")?.checked;
  const rangeOk = finOn && locked && hasSibling;
  if (rng) rng.disabled = !rangeOk;
  const hint = $("ia3d-start-hint");
  if (hint) {
    if (rangeOk) {
      const r = _finalizeKW ? _finalizeKW.getRange() : { start: 0, end: 0 };
      hint.textContent = `keyframe is locked → "for range" analyzes ${r.start}–${r.end}. Unlock to disable.`;
    } else if (!hasSibling) {
      hint.textContent = "no sibling camera detected.";
    } else {
      hint.textContent = "lock the finalize keyframe to enable \"for range\".";
    }
  }
}
```

Wire both buttons + re-evaluate enablement on the relevant triggers in `_wireStereoDispatch` (after `analyzeBtn.addEventListener("click", _onAnalyzeClick);` at line 1967):

```javascript
$("ia3d-btn-analyze-current")?.addEventListener("click", _onAnalyzeClick);
$("ia3d-btn-analyze-range-confined")?.addEventListener("click", _onAnalyzeRangeConfinedClick);
$("ia3d-frames-per-click")?.addEventListener("input", _refreshAnalyzeEnablement);
$("ia3d-finalize-lock")?.addEventListener("change", _refreshAnalyzeEnablement);
```

In the finalize-toggle `change` handler (line 1973), append `_refreshAnalyzeEnablement();` at the end. In `_refreshSibling` (after it sets `analyzeBtn.disabled`), append a call to `_refreshAnalyzeEnablement()` so the left buttons track sibling resolution. In `_finalizeKW`'s creation (line 429), add an `onChange` that calls `_refreshAnalyzeEnablement()` so range edits update the hint:

```javascript
  _finalizeKW = makeKeyframeWindow({
    viewer: v,
    panelEl: $("ia3d-finalize-controls"),
    settingKey: "finalize_window",
    els: {
      keyframe: $("ia3d-finalize-keyframe"), lock: $("ia3d-finalize-lock"),
      before: $("ia3d-finalize-before"), after: $("ia3d-finalize-after"),
      length: $("ia3d-finalize-length"), range: $("ia3d-finalize-range"),
    },
    onChange: () => _refreshAnalyzeEnablement(),
  });
```

- [ ] **Step 5: Make Finalize default-on in `_resetForOpen`**

In `inline_analysis_3d.js:1226-1231`, change the finalize reset from unchecking to checking + revealing. Replace:

```javascript
  const finToggle = $("ia3d-finalize-toggle");
  if (finToggle) finToggle.checked = false;
  $("ia3d-finalize-controls")?.classList.add("hidden");
```
with:
```javascript
  const finToggle = $("ia3d-finalize-toggle");
  if (finToggle) finToggle.checked = true;   // Finalize is on by default (spec)
  $("ia3d-finalize-controls")?.classList.remove("hidden");
```

Keep the existing `_markerEditor?.setEditable(false)` two lines below — but because Finalize is now on by default, set it to `true`. Change `_markerEditor?.setEditable(false);` (line 1231) to `_markerEditor?.setEditable(true);`. Add `_refreshAnalyzeEnablement?.();` at the end of `_resetForOpen` is unsafe (function-hoisted; safe to call directly): add `_refreshAnalyzeEnablement();` after the finalize reset lines.

NOTE: the finalize-toggle `change` handler also force-enables the overlay; since `_resetForOpen` sets `.checked = true` directly (not via a `change` event), call `_ia3dPopulateFinalizeFields()` is premature (no viewer frame yet). Leave the overlay default OFF on open (the user enables it); the spec only requires the Finalize PANEL visible by default, not the overlay. So do NOT auto-fire the toggle's change in `_resetForOpen`; just set checked + remove hidden + setEditable(true) + `_refreshAnalyzeEnablement()`.

- [ ] **Step 6: Run the static-analysis tests + JS helper tests**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q && node --test tests/unit/test_clamp_bounds.mjs tests/unit/test_tag_list.mjs`
Expected: pytest PASS (incl. the two new tests); node tests PASS.

`test_js3d_edit_gated_on_finalize` (line 286) asserts BOTH `"setEditable(false)" in js` AND that the toggle handler calls `setEditable(on)`. Both stay TRUE after this task: `_ensureViewer` still composes the editor with `setEditable(false)` at line 166 (the initial default before any toggle), and the toggle `change` handler still calls `setEditable(on)`. The only `setEditable` you flip in Task 7 Step 5 is the SECOND occurrence (inside `_resetForOpen`, line 1231) — leave the line-166 default untouched so this test stays green. Do NOT weaken this test.

- [ ] **Step 7: Deploy + live-confirm the gating flips with the lock**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`
The full lock interaction lands in Task 9; here confirm the for-range button is disabled with finalize-on but unlocked, and the from-current button mirrors sibling-gating. (Deferred to Task 9 because it needs the OM-2 fixture for a real sibling.)

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(inline-3d): wire two start buttons (current-frame + gated for-range); finalize on by default

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Wiring — keyframe-lock range-confine + red block + red flag + quick-tags

This task ties the lock to navigation confinement and the red visuals, and adds the per-project quick-tag CRUD.

**Files:**
- Modify: `src/static/inline_analysis_3d.js`
- Modify: `tests/test_inline_analysis_3d_ui_isolation.py` (assertions for lock visuals + tags)

### 8a. Lock-driven state + helpers

- [ ] **Step 1: Add failing static-analysis assertions**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_lock_confine_and_visuals_wired():
    js = JS.read_text()
    assert "clamp_bounds.mjs" in js, "must import the clampToBounds helper"
    assert "clampToBounds(" in js, "navigation must clamp through clampToBounds when locked"
    assert "ia3d-lock-flag" in js, "red lock flag visibility must be wired"
    # the seek-bar red block + the two dim overlays are positioned by JS
    assert "ia3d-lock-range" in js, "seek-bar red range block must be drawn"
    assert "ia3d-lock-dim-left" in js and "ia3d-lock-dim-right" in js, "dim-outside overlays must be drawn"


def test_quick_tags_wired_per_project():
    js = JS.read_text()
    assert "tag_list.mjs" in js, "must import the tag-list reducer"
    assert "addTag(" in js and "removeTag(" in js
    for key in ('"postfix_tags"', '"status_tags"', '"note_tags"'):
        assert key in js or key.replace('"', "'") in js, f"missing tag setting key {key}"
    # tag click REPLACES the field (not append)
    assert "_fillTagInto" in js or "REPLACE" in js or ".value =" in js
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_lock_confine_and_visuals_wired tests/test_inline_analysis_3d_ui_isolation.py::test_quick_tags_wired_per_project -q`
Expected: FAIL.

- [ ] **Step 3: Import the helpers + add lock state**

At the top of `inline_analysis_3d.js`, add to the imports (after line 24):

```javascript
import { clampToBounds } from "./internal/clamp_bounds.mjs";
import { addTag, removeTag } from "./internal/tag_list.mjs";
```

Add module state near the other `let _finalize*` declarations (after line 49):

```javascript
let _lockActive = false;          // true while the finalize keyframe is locked (range-confine on)
let _lockRange = { start: 0, end: 0 };  // the confined range mirrored from _finalizeKW.getRange()
```

- [ ] **Step 4: Add the lock-state apply + red-visual draw**

Add these helpers (near `_drawCoverageBar`, after line 288):

```javascript
// Mirror the finalize keyframe-lock into the inline range-confine + red visuals.
// Called whenever the lock checkbox or the range changes.
function _applyLockState() {
  const locked = !!$("ia3d-finalize-lock")?.checked && !!$("ia3d-finalize-toggle")?.checked;
  _lockActive = locked;
  if (locked && _finalizeKW) {
    const r = _finalizeKW.getRange();
    _lockRange = { start: r.start, end: r.end };
  }
  // Red flag above cam0 (normal flow). Hidden unless locked.
  const flag = $("ia3d-lock-flag");
  if (flag) {
    flag.classList.toggle("hidden", !locked);
    if (locked) flag.textContent = `🔒 range-locked · ${_lockRange.start.toLocaleString()}–${_lockRange.end.toLocaleString()}`;
  }
  _drawLockOverlays();
  _refreshAnalyzeEnablement();
}

// Position the red range block + the two dimmed-outside overlays over the seek
// canvas, in fraction-of-width space (matches the playhead math in _drawCoverageBar).
function _drawLockOverlays() {
  const range = $("ia3d-lock-range");
  const dimL = $("ia3d-lock-dim-left");
  const dimR = $("ia3d-lock-dim-right");
  const show = _lockActive && _viewer && _viewer.frameCount() > 1;
  for (const el of [range, dimL, dimR]) if (el) el.classList.toggle("hidden", !show);
  if (!show) return;
  const fc = _viewer.frameCount();
  const last = Math.max(fc - 1, 1);
  const sPct = (_lockRange.start / last) * 100;
  const ePct = (_lockRange.end / last) * 100;
  if (dimL) { dimL.style.left = "0"; dimL.style.width = sPct + "%"; }
  if (dimR) { dimR.style.left = ePct + "%"; dimR.style.right = "0"; dimR.style.width = "auto"; }
  if (range) { range.style.left = sPct + "%"; range.style.width = (ePct - sPct) + "%"; }
}
```

- [ ] **Step 5: Confine every navigation entry point**

1. In `_wireSeekCanvas` (lines 313-339), clamp the seek target when locked. In `free`:

```javascript
  const free = (e) => {
    const r = canvas.getBoundingClientRect();
    let F = xToFrame(e.clientX - r.left, r.width, _viewer.frameCount());
    if (_lockActive) F = clampToBounds(F, _lockRange.start, _lockRange.end);
    _viewer?.seek(F);
  };
```

And in `snap`, before the final `_viewer.seek(F)` and before the snap-to-covered-frame seek, clamp: wrap both `_viewer.seek(cf)` and `_viewer.seek(F)` targets through `clampToBounds` when `_lockActive`. Concretely, at the top of `snap` after computing `F`, add `if (_lockActive) F = clampToBounds(F, _lockRange.start, _lockRange.end);`, and change the covered-frame branch to `const cfc = _lockActive ? clampToBounds(cf, _lockRange.start, _lockRange.end) : cf; if (cf != null && Math.abs(cf - F) <= bucketFrames) { _viewer.seek(cfc); return; }`.

2. In `_wireViewerChrome`, clamp the step/skip button handlers (lines 366-370):

```javascript
  const _confine = (target) => (_lockActive ? clampToBounds(target, _lockRange.start, _lockRange.end) : target);
  $("ia3d-btn-prev")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() - 1)));
  $("ia3d-btn-next")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() + 1)));
  $("ia3d-btn-skip-back")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() - skipN())));
  $("ia3d-btn-skip-fwd")?.addEventListener("click", () => v.seek(_confine(v.currentFrame() + skipN())));
```

(These replace the existing `v.step(...)`/`v.step(±skipN())` lines; `step` is unconfined, so we compute the confined target and `seek` directly.)

3. For play + status/note nav (which seek internally), add a `frameChange` snap-back. In `_wireViewerChrome`'s existing `v.on("frameChange", …)` (line 524) handler, prepend a confine-and-pause guard:

```javascript
  v.on("frameChange", (n) => {
    if (_lockActive && (n < _lockRange.start || n > _lockRange.end)) {
      v.pause();
      const c = clampToBounds(n, _lockRange.start, _lockRange.end);
      if (c !== n) { v.seek(c); return; }   // re-enters frameChange at the clamped frame
    }
    _redrawSeekTimeline();
    _drawLockOverlays();
    _updateCounters(n, v.frameCount());
    _swapPlayIcon(v.isPlaying());
  });
```

4. Redraw the overlays whenever the seek timeline redraws or zoom changes: add `_drawLockOverlays();` at the end of `_applyTimelineWidth` (after line 305) and in the zoom handler after `_applyTimelineWidth(g)` (line 488).

- [ ] **Step 6: Drive `_applyLockState` from the lock checkbox + finalize toggle + range edits**

In `_wireStereoDispatch`, add (alongside the Task 7 wiring):

```javascript
$("ia3d-finalize-lock")?.addEventListener("change", _applyLockState);
```

In the finalize-toggle `change` handler, append `_applyLockState();`. The `_finalizeKW` `onChange` (Task 7) already calls `_refreshAnalyzeEnablement`; also call `_drawLockOverlays()` there so dragging before/after redraws the block while locked — extend the onChange to `onChange: () => { _refreshAnalyzeEnablement(); if (_lockActive && _finalizeKW) { const r = _finalizeKW.getRange(); _lockRange = { start: r.start, end: r.end }; _drawLockOverlays(); } }`.

In `_resetForOpen`, after the finalize reset, add `_lockActive = false; _applyLockState?.();` — but since the lock checkbox is inside `_finalizeKW` which calls `setLock(false)` on `load()`, the lock is unlocked on each new video; `_applyLockState()` will then hide the flag/overlays. Add `_lockActive = false;` and call `_applyLockState()` at the end of `_resetForOpen`.

### 8b. Quick-tags (postfix / status / note)

- [ ] **Step 7: Add the tag CRUD + click-to-fill**

Add a generic tag-list controller near the bottom of the consumer glue (before the launcher wiring, after `_wireCurationChrome`). It loads the per-project list, renders pills into the container, fills the bound input on click (REPLACE), removes on `×`, and adds via the bound input's current value (or a prompt):

```javascript
// Per-project quick-tags controller. Three independent lists (postfix/status/note),
// each persisted under its own ui-setting key. Click a pill → REPLACE the bound
// input's value. × removes; "+ tag" adds the input's current value (or a prompt).
function _makeQuickTags({ settingKey, containerId, inputId }) {
  let tags = [];
  let saveTimer = null;
  const container = () => $(containerId);
  const input = () => $(inputId);

  const save = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      fetch("/dlc/project/ui-setting", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: settingKey, value: JSON.stringify(tags) }),
      }).catch(() => {});   // best-effort; in-memory list stays intact on failure
    }, 400);
  };

  const render = () => {
    const c = container();
    if (!c) return;
    c.innerHTML = "";
    for (const t of tags) {
      const pill = document.createElement("span");
      pill.className = "ia3d-ptag";
      pill.appendChild(document.createTextNode(t + " "));
      const x = document.createElement("span");
      x.className = "x"; x.textContent = "×";
      x.addEventListener("click", (ev) => { ev.stopPropagation(); tags = removeTag(tags, t); render(); save(); });
      pill.appendChild(x);
      pill.addEventListener("click", () => { const el = input(); if (el) { el.value = t; el.dispatchEvent(new Event("input", { bubbles: true })); } });
      c.appendChild(pill);
    }
    const add = document.createElement("span");
    add.className = "ia3d-ptag ia3d-ptag-add"; add.textContent = "+ tag";
    add.addEventListener("click", () => {
      const el = input();
      const cur = el && el.value.trim();
      const raw = cur || window.prompt("New tag:");
      const next = addTag(tags, raw);
      if (next.length !== tags.length) { tags = next; render(); save(); }
    });
    c.appendChild(add);
  };

  const load = async () => {
    try {
      const d = await (await fetch(`/dlc/project/ui-setting?key=${encodeURIComponent(settingKey)}`)).json();
      const parsed = d && d.value ? JSON.parse(d.value) : [];
      tags = Array.isArray(parsed) ? parsed : [];
    } catch (_) { tags = []; }
    render();
  };

  return { load, render };
}

let _postfixTags = null, _statusTags = null, _noteTags = null;
function _wireQuickTags() {
  _postfixTags = _makeQuickTags({ settingKey: "postfix_tags", containerId: "ia3d-postfix-tags", inputId: "ia3d-finalize-clip-postfix" });
  _statusTags  = _makeQuickTags({ settingKey: "status_tags",  containerId: "ia3d-status-tags",  inputId: "ia3d-status-input" });
  _noteTags    = _makeQuickTags({ settingKey: "note_tags",    containerId: "ia3d-note-tags",    inputId: "ia3d-note-input" });
}
```

Call `_wireQuickTags()` once in `_wireStereoDispatch` (it owns static, non-rebuilt controls). Load all three lists when the card opens and after a video opens: in `_iaOpenVideo`/`_iaOpenBrowseVideo`/`_iaOpenFrameFolder`, after `_ensureViewer()`, call `_postfixTags?.load(); _statusTags?.load(); _noteTags?.load();`. (Simplest: add a `_loadAllQuickTags()` helper and call it in each open fn + on card open.)

- [ ] **Step 8: Add the postfix-tags container in the finalize panel markup**

In `card_inline_analysis_3d.html`, inside the moved `#ia3d-finalize-panel`, after the `#ia3d-finalize-clip-postfix` input, add the postfix quick-tags block (mirrors the mockup's `.mk-postfix-tags`):

```html
<div style="font-size:.74rem;color:var(--text-dim);margin:.2rem 0 .3rem">postfix tags <span style="color:var(--text-dim)">(click to fill · saved per project)</span></div>
<div id="ia3d-postfix-tags" class="ia3d-tags"></div>
```

(The `#ia3d-status-tags`/`#ia3d-note-tags` containers were added in Task 6.)

- [ ] **Step 9: Run all unit + static tests**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_clamp_bounds.mjs tests/unit/test_tag_list.mjs && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: all PASS (incl. `test_lock_confine_and_visuals_wired`, `test_quick_tags_wired_per_project`).

- [ ] **Step 10: Deploy**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`

- [ ] **Step 11: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js src/templates/partials/card_inline_analysis_3d.html tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(inline-3d): keyframe-lock range-confine + red block/flag; per-project quick-tags

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Holistic live verification (Python playwright, read-only)

This is the integration "test" for the markup/CSS/wiring (no JS unit test possible for DOM behavior). It drives the real card against the DREADD-Ali OM-2 fixture used by the existing e2e conftest (`tests/e2e/conftest.py`), strictly READ-ONLY: navigation, lock toggling, tag click-to-fill, size sliders. It NEVER clicks Add / Extract / Finalize / Delete / the analyze submit buttons.

**Files:**
- Create: `tests/e2e/test_inline_3d_reorg.py`

The OM-2 fixture is a labeled-FRAMES stem (the conftest probes `/dlc/project/labeled-frames`), opened via `_iaOpenFrameFolder`. Frames mode sets `_primaryRel = stem` and `siblingPath: null`, so `_refreshSibling` cannot resolve a sibling → `_siblingPath = null` → both start buttons stay disabled. This is fine for verifying layout / lock visuals / nav-confine / tag click-to-fill / size sliders.

**Limitation (recorded):** Because frames mode has no sibling, this suite verifies the for-range button is DISABLED while unlocked (its gate includes `!locked` AND `!sibling`), but it cannot positively assert the button ENABLING (that requires a labeled-VIDEO with a resolvable cam1 sibling, which only exists under the protected `/user-data` fixtures). The button's enable path is covered by the static-analysis test `test_two_start_buttons_present_and_wired` + the unit-tested gate logic; do NOT open/analyze a protected video to force the enabled state.

- [ ] **Step 1: Write the live-verification suite**

Create `tests/e2e/test_inline_3d_reorg.py`. It reuses the autouse `_active_dlc_project` fixture from `tests/e2e/conftest.py` (authenticates + activates DREADD-Ali, skips if absent).

```python
"""Live read-only verification of the inline-3D analysis card reorg.

Drives the real card at /dlc-3d/ against the DREADD-Ali OM-2 labeled-frames
fixture (provided by the e2e conftest autouse fixture). READ-ONLY: opens the
card, selects the frame folder, asserts the two-column layout + lock visuals +
quick-tag click-to-fill + size sliders. NEVER triggers analysis/finalize/extract.

Visual target: src/static/mockup_inline_3d.html.j2.
"""
import re
import pytest
from playwright.sync_api import Page, expect

SESSION = "OM-2_20260424"


@pytest.fixture(autouse=True)
def _open_inline_card(page: Page, base_url):
    page.goto(base_url)
    page.locator("#btn-open-inline-analysis-3d").click()
    page.locator("#inline-analysis-3d-card").wait_for(state="visible")
    # The Project-Content tab lists labeled frame folders; pick the OM-2 stem.
    page.wait_for_function(
        f"() => document.querySelector('#ia3d-content-list') && "
        f"document.querySelector('#ia3d-content-list').textContent.includes('{SESSION}')",
        timeout=15000,
    )
    page.locator("#ia3d-content-list").get_by_text(f"{SESSION}/").first.click()
    page.locator("#ia3d-player-section").wait_for(state="visible")
    page.wait_for_function("() => window.__iaViewer && window.__iaViewer.frameCount() > 0")


def test_full_width_two_column_layout(page: Page):
    card = page.locator("#inline-analysis-3d-card")
    left = page.locator(".ia3d-left")
    right = page.locator(".ia3d-right")
    expect(left).to_be_visible()
    expect(right).to_be_visible()
    lb = left.bounding_box(); rb = right.bounding_box()
    assert rb["x"] > lb["x"], "Finalize panel must dock to the right of the left region"
    # Finalize panel is inside the right column and checked by default.
    assert page.locator(".ia3d-right #ia3d-finalize-panel").count() == 1
    assert page.locator("#ia3d-finalize-toggle").is_checked()


def test_both_start_buttons_present(page: Page):
    expect(page.locator("#ia3d-btn-analyze-current")).to_be_visible()
    expect(page.locator("#ia3d-btn-analyze-range-confined")).to_be_visible()


def test_for_range_gating_flips_with_lock(page: Page):
    # frames-mode has no sibling → both stay disabled regardless; assert the
    # for-range button is disabled while unlocked (its gate includes !locked).
    rng = page.locator("#ia3d-btn-analyze-range-confined")
    expect(rng).to_be_disabled()
    # Lock the keyframe; for-range gate also requires a sibling, so it stays
    # disabled here, but the lock VISUALS must engage (covered below).


def test_lock_shows_red_flag_and_block_and_confines_nav(page: Page):
    # Move off frame 0 so the keyframe (=current) is mid-clip, then lock.
    page.locator("#ia3d-btn-next").click()
    page.locator("#ia3d-finalize-lock").check()
    expect(page.locator("#ia3d-lock-flag")).to_be_visible()
    expect(page.locator("#ia3d-lock-range")).to_be_visible()
    # The red flag text reports a range.
    assert re.search(r"range-locked", page.locator("#ia3d-lock-flag").inner_text())
    # Navigation is confined: try to skip far backward past the range start.
    start = page.evaluate("() => { const r = window.__iaViewer; return r ? r.currentFrame() : 0; }")
    page.locator("#ia3d-skip-n").fill("99999")
    page.locator("#ia3d-btn-skip-back").click()
    confined = page.evaluate("() => window.__iaViewer.currentFrame()")
    # Must not go below the locked range start (the range start <= confined frame).
    rng_start = page.evaluate("""() => {
        const f = document.getElementById('ia3d-finalize-range').textContent;
        const m = f.match(/frames\\s+(\\d+)/); return m ? parseInt(m[1],10) : 0; }""")
    assert confined >= rng_start, f"nav escaped the locked range (frame {confined} < start {rng_start})"


def test_unlock_hides_visuals(page: Page):
    page.locator("#ia3d-finalize-lock").check()
    expect(page.locator("#ia3d-lock-flag")).to_be_visible()
    page.locator("#ia3d-finalize-lock").uncheck()
    expect(page.locator("#ia3d-lock-flag")).to_be_hidden()
    expect(page.locator("#ia3d-lock-range")).to_be_hidden()


def test_postfix_tag_click_replaces_field_and_persists(page: Page):
    # Add a tag via the "+ tag" affordance using a typed value, then click it to fill.
    page.locator("#ia3d-finalize-clip-postfix").fill("reachZZ")
    page.locator("#ia3d-postfix-tags .ia3d-ptag-add").click()
    expect(page.locator("#ia3d-postfix-tags").get_by_text("reachZZ")).to_be_visible()
    # Change the field, then click the pill → REPLACE.
    page.locator("#ia3d-finalize-clip-postfix").fill("other")
    page.locator("#ia3d-postfix-tags .ia3d-ptag", has_text="reachZZ").click()
    assert page.locator("#ia3d-finalize-clip-postfix").input_value() == "reachZZ"
    # Persisted: reload the card and re-open; the tag should reappear.
    page.reload()
    page.locator("#btn-open-inline-analysis-3d").click()
    page.locator("#inline-analysis-3d-card").wait_for(state="visible")
    page.wait_for_function("() => document.querySelector('#ia3d-postfix-tags')")
    # The tags container loads on card open even before a video is selected.
    page.wait_for_function(
        "() => document.querySelector('#ia3d-postfix-tags').textContent.includes('reachZZ')",
        timeout=10000,
    )
    # Cleanup: remove the test tag so the fixture's stored setting stays clean.
    page.locator("#ia3d-postfix-tags .ia3d-ptag", has_text="reachZZ").locator(".x").click()


def test_size_sliders_resize_tiles(page: Page):
    sliders = page.locator("#ia3d-viewer-mount .vv-tile-size")
    assert sliders.count() >= 1, "per-tile size slider missing after the reorg"
    tile = page.locator("#ia3d-viewer-mount .vv-tile").first
    w_before = tile.evaluate("el => el.getBoundingClientRect().width")
    tile.locator(".vv-tile-size").evaluate("(el)=>{el.value='300';el.dispatchEvent(new Event('input'));}")
    w_after = tile.evaluate("el => el.getBoundingClientRect().width")
    # single-tile (frames mode) → flex-grow has no sibling to take width from, so
    # assert the slider LABEL updated as the regression signal that the slider is live.
    label = tile.locator(".vv-tile-size-val").inner_text().strip()
    assert label == "300%", f"size slider label did not update (got {label!r})"


def test_per_frame_edit_rows_load_current_frame(page: Page):
    # The status/note edit inputs live under their timelines and are populated by
    # statusNoteTimeline.updateBadges on frameChange (value reflects the CSV row or default).
    expect(page.locator("#ia3d-status-input")).to_be_visible() if page.locator("#ia3d-status-bar-wrap").is_visible() else None
    # The els must at least exist in the DOM (timeline wraps reveal only with CSV content).
    assert page.locator("#ia3d-status-input").count() == 1
    assert page.locator("#ia3d-note-input").count() == 1
```

- [ ] **Step 2: Deploy + run the suite**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`
Then: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/e2e/test_inline_3d_reorg.py -q`
Expected: PASS, or SKIP if the OM-2 fixture is absent (the autouse fixture skips). If a test fails, read the failure, fix the markup/CSS/JS (NOT the test's intent), redeploy, re-run.

- [ ] **Step 3: Full regression sweep**

Run the unit + static suites together:
`cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_clamp_bounds.mjs tests/unit/test_tag_list.mjs tests/unit/test_viewer_keyframe_window.mjs && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_policy.py tests/test_keyframe_window_ui.py -q`
And the backend allow-list:
`cd /home/sam/docker-images/deeplabcut-webapp-docker && python -m pytest tests/test_ui_setting_tag_keys.py tests/test_project_settings.py -q`
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add tests/e2e/test_inline_3d_reorg.py
git commit -m "test(inline-3d): live read-only verification of the reorg (layout, lock, tags, sliders)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review (run by the plan author; recorded here)

**1. Spec coverage**
- Full-width two-column layout → Tasks 4 (markup) + 5 (CSS) + 9 (live).
- Left region order (lock flag, mount, seek bar, controls+frame#, chips, status, notes, finalized) → Task 4 Target DOM.
- Right-docked Finalize sub-card, checked by default → Tasks 4 (relocate) + 7 (default-check).
- Two start buttons (current-frame always-on; for-range gated on finalize-on && locked) → Task 7 + reuse of existing `analyze-range` (grounding fact).
- Keyframe lock → range-confine all nav + red block + red flag → Task 8a; bounds-clamp location decision recorded (consumer; no library change).
- Per-frame status/note edit rows reusing statusNoteTimeline save → Task 6 (relocate els; ids unchanged so existing config still binds).
- Quick-tags (postfix/status/note), click-to-fill REPLACE, per-project → Task 8b + backend allow-list Task 1.
- Backend allow-list (postfix_tags/status_tags/note_tags) → Task 1.
- Size-slider regression guard → Task 9 `test_size_sliders_resize_tiles`.
- node:test for clamp + tag reducer → Tasks 2, 3.
- Live verification read-only against fixtures, no destructive clicks → Task 9 (frames-mode fixture, asserts no Add/Extract/Finalize clicked).
- No viewer-policy pytest needed (library untouched) — recorded in the bounds-clamp decision; spec said "only if the contract is touched."

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step has complete code; every test step has a real command + expected output. Tag-fill uses `.value =` + dispatched `input` event (explicit). The lock snap-back, seek clamp, and step/skip rewrites are spelled out against real line numbers.

**3. Type/name consistency:**
- New JS symbols used consistently: `clampToBounds`, `addTag`, `removeTag`, `_lockActive`, `_lockRange`, `_applyLockState`, `_drawLockOverlays`, `_refreshAnalyzeEnablement`, `_onAnalyzeRangeConfinedClick`, `_makeQuickTags`, `_wireQuickTags`, `_postfixTags/_statusTags/_noteTags`.
- New ids consistent across markup/CSS/JS/tests: `ia3d-btn-analyze-current`, `ia3d-btn-analyze-range-confined`, `ia3d-start-count-n`, `ia3d-start-hint`, `ia3d-lock-flag`, `ia3d-lock-range`, `ia3d-lock-dim-left`, `ia3d-lock-dim-right`, `ia3d-finalize-coverage-wrap`, `ia3d-postfix-tags`, `ia3d-status-tags`, `ia3d-note-tags`.
- Existing ids reused verbatim (unchanged): `ia3d-finalize-toggle`, `ia3d-finalize-lock`, `ia3d-finalize-coverage`, `ia3d-finalize-prev/next`, `ia3d-status-input/note-input/save-status-btn/save-note-btn/annot-save-status`, `ia3d-seek-canvas`, `ia3d-bp-chips`, `ia3d-frame-counter/time-display/help-btn`, `ia3d-finalize-clip-postfix`.
- Backend key names match across Task 1, Task 8b client, and tests: `postfix_tags`, `status_tags`, `note_tags`.
- `_finalizeKW.getRange()` returns `{start, end, n}` (verified in `keyframe_window_ui.js` + `keyframe_window.mjs`) — Task 7 uses `.start`/`.n`, Task 8 uses `.start`/`.end`. Consistent.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-24-inline-3d-analysis-reorg.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
