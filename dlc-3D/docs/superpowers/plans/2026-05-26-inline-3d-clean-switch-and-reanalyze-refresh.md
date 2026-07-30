# Inline-3D Clean Video-Switch + Refresh-After-Re-Analyze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make switching videos on the inline-3D analysis card a clean reset (kinematics view off, no markers, no auto-pick), auto-pick the LATEST h5 variant only when the user turns the view on, and refresh markers + coverage after an in-place re-analysis by invalidating the stale client caches.

**Architecture:** Frontend-only changes in `dlc-3D`. Bug-1 behavior lives entirely in the inline consumer (`inline_analysis_3d.js`): `_resetForOpen` clears the markerEditor layer + overlay state; `_refreshOverlayH5Variants` stops auto-picking on videoLoad; the overlay-toggle ON handler enables the overlay + auto-picks the latest variant; `_applyOverlayPrimary` drops its force-overlay-enable block (keeps `setEditable` arming). Bug-2 is fixed by an ADDITIVE shared method `markerEditor.invalidatePoses()` that clears every layer's `posesCache` and re-renders the current frame; the two post-analysis handlers call it plus invalidate `_coverageCache`. A new pure helper `pickLatestVariant()` (unit-tested) makes "latest" unambiguous. The shared `markerEditor.setPrimary(null)` is extended to clear layers (additive; no consumer regression). View Analyzed (`viewer_3d.js`) never calls `invalidatePoses()` and is unaffected.

**Tech Stack:** Vanilla ES modules (browser, bind-mounted live), Python `pytest` static-source guards, Node `node:test` for pure `.mjs` helpers, Playwright (read-only live verification).

---

## Grounding facts (state them explicitly)

- **Repo / branch:** `deeplabcut-webapp-docker-supports/dlc-3D`, branch `feat/marker-editor-labeler-mechanics`.
- **NO player fork.** `tests/test_video_viewer_policy.py` must stay green throughout (no per-card `Tile`/`Controller`; compose the shared base + features only).
- **No data/save-layer change.** No new backend routes. `invalidatePoses()` does NOT touch the edit/save path (`saveMarker`, `save-marker-edits`).
- **Bug-1 is INLINE-only** (`inline_analysis_3d.js`). The shared `marker_editor.js` changes (`invalidatePoses()`, `setPrimary(null)` clearing) are ADDITIVE: View Analyzed (`viewer_3d.js`) never calls them and must not regress. A View-Analyzed regression step is included (Task 7).
- **Bug-2 mechanism:** inline analysis OVERWRITES the same h5 in place. `markerEditor`'s per-layer `posesCache` is keyed `poseCacheKey(layer.path, threshold)` (path + threshold, no mtime) and `inline_analysis_3d.js`'s `_coverageCache` is keyed `` `${_overlayPrimaryH5}:${thr.toFixed(2)}:${w}` `` — neither carries a version, so after an in-place overwrite both serve stale data until a manual h5 re-select rebuilds the layer. Invalidating both after analysis fixes the refresh. Bug-2 is verified by code + unit/contract tests, NOT by running analysis against protected `/user-data`.

### "Latest variant" rule (determined from the variants source)

Evidence — `deeplabcut-webapp-docker/src/dlc/viewer.py` `_h5_variants_for_video` (lines 607-667) builds the array in this order:
1. **Raw companion h5(s)** in the video's parent dir (`sorted(parent.glob(f"{stem}*.h5"))`, alphabetical) — each has `"ts": None`.
2. **postproc runs** under `parent/postproc/`, iterated `sorted(pp_root.iterdir())`. Run dirs are named `<YYYYMMDD-HHMMSS>_<tag>` (`_RUN_DIR_RE`, line 559), so sorting by name == sorting by timestamp **ascending**. Each carries `"ts"` = ISO 8601 (`_ts_to_iso`, e.g. `"2026-05-02T11:36:42Z"`).

So the freshest run is the LAST element whose `ts` is set; ISO 8601 strings compare correctly lexicographically. The **rule**: `pickLatestVariant(variants)` returns the variant with the maximum non-null `ts`; if NO variant has a `ts` (all raw companions), return the LAST array element (the backend's own ordering); empty list → `null`. This is unambiguous regardless of variant count and tolerates the empty list (overlay-on then shows nothing until analysis exists). The inline working layer (overwritten in place) is a raw companion h5; with only raw variants the rule picks the last raw entry, which is the freshly-(re)written file.

### markerEditor re-fetch-current-frame path (so `invalidatePoses` reuses it)

`marker_editor.js` already has `onFrame(frame)` (lines 409-418): it sets `currentFrame`, and when `renderActive()` is true it awaits `fetchAllForFrame(frame)` (which calls `fetchLayerFrame` per visible layer — that re-fetches because the cache was cleared) then `renderAll()` + `updateBpChips()` + `prefetch(frame)`. `setThreshold` (lines 676-682) already uses exactly this idiom: it clears every layer's `posesCache` (`for (const l of layers) l.posesCache.clear()` + the same for `siblingLayers`), then calls `onFrame(currentFrame)`. **`invalidatePoses()` is the same pattern** minus the threshold change: clear every layer's `posesCache`, abort any in-flight prefetch, then `onFrame(currentFrame)` to re-fetch + re-render the current frame. No new fetch path is introduced — it reuses `onFrame`/`fetchLayerFrame`.

### Spec ambiguities resolved

- **`setPrimary(null)` does NOT already clear** (spec §Behaviors B1 and §Error handling claim it does). Reading `marker_editor.js` `setPrimary` (lines 608-618): it unconditionally builds `layers = [makeLayer(h5Path, "main")]` and calls `loadLayerInfo`/`loadEditCache` with the path, so `setPrimary(null)` would create a `{path:null}` layer and fetch garbage URLs. **Resolution:** Task 1b extends `setPrimary` to early-clear on a falsy `h5Path` (`layers = []`, `siblingLayers = []`, drop both cams' edits, rebuild empty chips, re-render). This is additive — neither consumer calls `setPrimary(null)` today (`viewer_3d.js`/`inline_analysis_3d.js` both guard `!h5` and skip the call), so no regression. `_resetForOpen` then calls `_markerEditor?.setPrimary(null)` to clear the previous video's layer.
- **`test_dispatch_runs_both_cameras_against_main_webapp_api` asserts `setOverlayEnabled(true)` and `_viewer.load(` appear in source** (existing test, lines 80-81). The post-analysis handlers (Task 5) keep calling `setOverlayEnabled(true)` (turning the view on after a run is intended) and keep the frame-preserving `_viewer.load(...)`, so this stays green; Task 5 only ADDS the two invalidation calls.

## File Structure

- **Modify** `src/static/components/viewer/features/marker_editor.js` — add `invalidatePoses()` to the public-methods block (after `setShowNames`/before `selectBp`); extend `setPrimary` to clear on null.
- **Create** `src/static/components/viewer/internal/pick_latest_variant.mjs` — pure `pickLatestVariant(variants)` helper.
- **Modify** `src/static/inline_analysis_3d.js` — import `pickLatestVariant`; `_resetForOpen` clears the markerEditor layer; `_refreshOverlayH5Variants` drops the single-variant auto-pick; the overlay-toggle change handler enables + auto-picks latest + renders; `_applyOverlayPrimary` drops the force-overlay-enable block (keeps `setEditable`); `_onAnalyzeClick` + `_onAnalyzeRangeConfinedClick` invalidate `_coverageCache` + call `invalidatePoses()` before/with the refresh.
- **Create** `tests/unit/test_pick_latest_variant.mjs` — node test for the pure helper.
- **Modify** `tests/test_marker_editor_feature.py` — contract for `invalidatePoses` + `setPrimary(null)` clearing.
- **Modify** `tests/test_inline_analysis_3d_ui_isolation.py` — clean-switch + view-on + post-analysis source guards.

## Test runners (reference for every task)

- Node unit: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/<file>.mjs`
- Pytest: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/<file>.py -q`
- JS is bind-mounted (live, no rebuild). Template changes (none in this plan) would need `cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d`.
- Live verify (read-only): Python Playwright, auth via `GET http://localhost:5000/?token=deeplabcut`, posed video DREADD-Ali / khoai-lang-1 cam0. **NEVER** run Start analysis / Add range / Extract / Finalize / Delete / Save against protected `/user-data`.

---

## Task 1: `markerEditor.invalidatePoses()` + `setPrimary(null)` clearing (shared, additive)

**Files:**
- Modify: `src/static/components/viewer/features/marker_editor.js` (public block ~693-703; `setPrimary` ~608-618)
- Test: `tests/test_marker_editor_feature.py`

- [ ] **Step 1: Write the failing contract tests**

Append to `tests/test_marker_editor_feature.py`:

```python
# ─── 2026-05-26 inline-3d clean-switch + reanalyze-refresh (Bug-2) ─────────────

def test_invalidate_poses_clears_cache_and_rerenders():
    """Bug-2: markerEditor must expose invalidatePoses() that clears every layer's
    posesCache (cam0 layers + siblingLayers) and re-fetches + re-renders the current
    frame via onFrame — so an in-place-overwritten h5 repaints with no manual
    re-select. Reuses the existing onFrame path (same idiom as setThreshold)."""
    src = _src()
    assert re.search(r"invalidatePoses\s*\(", src), "must expose invalidatePoses()"
    i = src.find("invalidatePoses")
    assert i > 0
    body = src[i:i + 400]
    # clears every layer's posesCache (both cams)
    assert re.search(r"for\s*\(const\s+l\s+of\s+layers\)\s*l\.posesCache\.clear\(\)", body), \
        "invalidatePoses must clear cam0 layers' posesCache"
    assert re.search(r"for\s*\(const\s+l\s+of\s+siblingLayers\)\s*l\.posesCache\.clear\(\)", body), \
        "invalidatePoses must clear siblingLayers' posesCache"
    # re-fetch + re-render the current frame via the existing onFrame path
    assert "onFrame(currentFrame)" in body, \
        "invalidatePoses must re-fetch+re-render the current frame via onFrame"


def test_set_primary_null_clears_layers():
    """Clean switch: setPrimary(null) must clear the primary (and sibling) layers
    rather than building a {path:null} layer that fetches garbage. Early-returns
    after emptying layers + rebuilding empty chips + re-rendering."""
    src = _src()
    i = src.find("async setPrimary(")
    assert i > 0, "setPrimary method not found"
    body = src[i:i + 600]
    # a falsy-path guard that empties the layer arrays
    assert re.search(r"if\s*\(\s*!\s*h5Path\s*\)", body), \
        "setPrimary must guard a falsy h5Path"
    assert "layers = []" in body, "setPrimary(null) must empty cam0 layers"
    assert "siblingLayers = []" in body, "setPrimary(null) must empty sibling layers"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q -k "invalidate_poses or set_primary_null"`
Expected: FAIL — both new tests fail (`invalidatePoses(` not found; `if ( !h5Path )` not found in setPrimary).

- [ ] **Step 3: Extend `setPrimary` to clear on null**

In `marker_editor.js`, replace the current `setPrimary` (lines 608-618):

```javascript
    async setPrimary(h5Path) {
      abortPrefetch();
      editsByCam[0] = {}; // drop prior cam0 edits; loadEditCache repopulates when available
      layers = [makeLayer(h5Path, "main")];
      await loadLayerInfo(layers[0]);
      recomputeBodyparts();
      rebuildBpChips();
      await loadEditCache(0, h5Path);
      updateEditBanner();
      onFrame(currentFrame);
    },
```

with the null-clearing variant:

```javascript
    async setPrimary(h5Path) {
      abortPrefetch();
      editsByCam[0] = {}; // drop prior cam0 edits; loadEditCache repopulates when available
      // Clean switch (B1): a falsy path clears the primary (and sibling) layer so
      // nothing renders and no chips show — used by the inline card's _resetForOpen.
      if (!h5Path) {
        editsByCam[1] = {};
        layers = [];
        siblingLayers = [];
        recomputeBodyparts();
        rebuildBpChips();
        updateEditBanner();
        renderAll();
        return;
      }
      layers = [makeLayer(h5Path, "main")];
      await loadLayerInfo(layers[0]);
      recomputeBodyparts();
      rebuildBpChips();
      await loadEditCache(0, h5Path);
      updateEditBanner();
      onFrame(currentFrame);
    },
```

- [ ] **Step 4: Add `invalidatePoses()` to the public-methods block**

In `marker_editor.js`, insert immediately after the `setShowNames` method (the block ending `},` at line 697, just before `selectBp,`):

```javascript
    // Bug-2: drop every layer's cached poses and re-fetch + re-render the current
    // frame. Inline analysis OVERWRITES the same h5 in place, but posesCache is keyed
    // by (path, threshold) with no version, so a re-run serves stale poses until the
    // layer is rebuilt. Consumers call this after a re-analysis completes. Reuses the
    // onFrame re-fetch path (same idiom as setThreshold). No-ops when no layers / the
    // overlay is off (onFrame renders an empty frame). Does NOT touch the save path.
    invalidatePoses() {
      abortPrefetch();
      for (const l of layers) l.posesCache.clear();
      for (const l of siblingLayers) l.posesCache.clear();
      onFrame(currentFrame);
    },
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_marker_editor_feature.py -q`
Expected: PASS (all existing + 2 new).

- [ ] **Step 6: Confirm the video-viewer policy + existing inline tests stay green**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_policy.py tests/test_inline_analysis_3d_ui_isolation.py -q`
Expected: PASS (no regression).

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/features/marker_editor.js tests/test_marker_editor_feature.py
git commit -m "feat(marker-editor): add invalidatePoses() + setPrimary(null) clearing

invalidatePoses() clears every layer's posesCache and re-fetches+re-renders
the current frame via onFrame (reuses the setThreshold idiom) so an in-place-
overwritten h5 repaints. setPrimary(null) now clears the primary+sibling layers
instead of building a {path:null} layer. Both additive — View Analyzed never
calls them.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `pickLatestVariant()` pure helper + node test

**Files:**
- Create: `src/static/components/viewer/internal/pick_latest_variant.mjs`
- Test: `tests/unit/test_pick_latest_variant.mjs`

- [ ] **Step 1: Write the failing node test**

Create `tests/unit/test_pick_latest_variant.mjs`:

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { pickLatestVariant }
  from "../../src/static/components/viewer/internal/pick_latest_variant.mjs";

test("pickLatestVariant: returns the variant with the max ISO ts", () => {
  const variants = [
    { path: "/a.h5", ts: null },
    { path: "/old.h5", ts: "2026-05-02T11:36:42Z" },
    { path: "/new.h5", ts: "2026-05-20T09:00:00Z" },
  ];
  assert.equal(pickLatestVariant(variants).path, "/new.h5");
});

test("pickLatestVariant: ISO strings compare lexicographically (no Date parse needed)", () => {
  const variants = [
    { path: "/jan.h5", ts: "2026-01-31T23:59:59Z" },
    { path: "/feb.h5", ts: "2026-02-01T00:00:00Z" },
  ];
  assert.equal(pickLatestVariant(variants).path, "/feb.h5");
});

test("pickLatestVariant: all raw (no ts) → returns the LAST array element", () => {
  const variants = [
    { path: "/raw-a.h5", ts: null },
    { path: "/raw-b.h5", ts: null },
  ];
  // backend orders raw companions alphabetically; the last is the freshly-written one
  assert.equal(pickLatestVariant(variants).path, "/raw-b.h5");
});

test("pickLatestVariant: mix → a dated variant beats undated ones", () => {
  const variants = [
    { path: "/raw.h5", ts: null },
    { path: "/run.h5", ts: "2026-05-02T11:36:42Z" },
  ];
  assert.equal(pickLatestVariant(variants).path, "/run.h5");
});

test("pickLatestVariant: empty / null → null (overlay-on shows nothing)", () => {
  assert.equal(pickLatestVariant([]), null);
  assert.equal(pickLatestVariant(null), null);
  assert.equal(pickLatestVariant(undefined), null);
});

test("pickLatestVariant: single variant → that variant", () => {
  const v = { path: "/only.h5", ts: null };
  assert.equal(pickLatestVariant([v]), v);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_pick_latest_variant.mjs`
Expected: FAIL — `Cannot find module .../pick_latest_variant.mjs`.

- [ ] **Step 3: Write the helper**

Create `src/static/components/viewer/internal/pick_latest_variant.mjs`:

```javascript
// pick_latest_variant.mjs — choose the "latest" h5 variant from a
// /dlc/viewer/h5-variants response array.
//
// Backend ordering (deeplabcut-webapp-docker/src/dlc/viewer.py
// _h5_variants_for_video): raw companion h5(s) first (alphabetical, ts=null),
// then postproc runs sorted by run-dir name == timestamp ASCENDING, each with an
// ISO-8601 `ts`. So the freshest analysis is the variant with the max `ts`; ISO
// 8601 strings compare correctly with `<`/`>` (no Date parse). When no variant
// carries a `ts` (all raw companions — the inline working layer is one of these),
// fall back to the LAST array element (the backend's own ordering puts the freshly
// written companion last alphabetically). Empty/falsy → null.
"use strict";

export function pickLatestVariant(variants) {
  if (!Array.isArray(variants) || variants.length === 0) return null;
  let best = null;
  for (const v of variants) {
    if (v && v.ts && (best === null || v.ts > best.ts)) best = v;
  }
  if (best) return best;
  return variants[variants.length - 1];
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_pick_latest_variant.mjs`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/components/viewer/internal/pick_latest_variant.mjs tests/unit/test_pick_latest_variant.mjs
git commit -m "feat(viewer): add pickLatestVariant() pure helper

Picks the freshest h5 variant: max ISO-8601 ts, else the last array element
(backend orders raw companions last alphabetically; postproc ascending by ts).
Unit-tested. Used by the inline overlay-on auto-pick.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `_resetForOpen` clears the markerEditor layer (clean base on switch)

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (`_resetForOpen` ~1343-1407, specifically the overlay reset block ~1368-1377)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing source guard**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
# ─── 2026-05-26 clean video-switch + refresh-after-re-analyze (Bug-1/Bug-2) ───

def test_reset_for_open_clears_marker_editor_layer():
    """Bug-1 clean switch: _resetForOpen must clear the previous video's
    markerEditor layer via setPrimary(null) (so a switch never leaves the prior
    layer's poses live), alongside the existing overlay-off + cache clear."""
    js = JS.read_text()
    i = js.find("function _resetForOpen(")
    assert i > 0, "_resetForOpen not found"
    body = js[i:i + 1800]
    assert "setPrimary(null)" in body, \
        "_resetForOpen must clear the markerEditor primary via setPrimary(null)"
    # the existing clean-base resets must remain
    assert "setOverlayEnabled(false)" in body, "overlay must reset off on switch"
    assert "_coverageCache.clear()" in body, "coverage cache must clear on switch"
    assert "_overlayPrimaryH5 = null" in body, "primary h5 must reset to null on switch"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k reset_for_open`
Expected: FAIL — `setPrimary(null)` not found in `_resetForOpen` body.

- [ ] **Step 3: Add the layer clear to `_resetForOpen`**

In `inline_analysis_3d.js`, the overlay reset block currently reads (lines 1368-1377):

```javascript
  _overlayPrimaryH5 = null;
  _siblingPrimaryH5 = null;
  const ovToggle = $("ia3d-overlay-toggle");
  if (ovToggle) ovToggle.checked = false;
  _markerEditor?.setOverlayEnabled(false);
  $("ia3d-overlay-controls")?.classList.add("hidden");
  $("ia3d-bp-list-wrap")?.classList.add("hidden");
  const _bc = $("ia3d-bp-chips"); if (_bc) _bc.style.minHeight = "";
  const ovStatus = $("ia3d-overlay-status");
  if (ovStatus) ovStatus.textContent = "";
```

Add the markerEditor layer clear + reset the primary `<select>` to its placeholder, immediately after `_markerEditor?.setOverlayEnabled(false);`:

```javascript
  _overlayPrimaryH5 = null;
  _siblingPrimaryH5 = null;
  const ovToggle = $("ia3d-overlay-toggle");
  if (ovToggle) ovToggle.checked = false;
  _markerEditor?.setOverlayEnabled(false);
  // Bug-1 clean switch: drop the previous video's markerEditor layer + sibling so a
  // switch never leaves the prior layer's poses live (setPrimary(null) empties the
  // layers + chips + re-renders nothing). Overlay off + no primary ⇒ nothing draws
  // even though editing is armed (no cached poses to draw, no chips).
  _markerEditor?.setPrimary(null);
  const ovPrimarySel = $("ia3d-overlay-primary-select");
  if (ovPrimarySel) ovPrimarySel.value = "";   // back to the placeholder
  $("ia3d-overlay-controls")?.classList.add("hidden");
  $("ia3d-bp-list-wrap")?.classList.add("hidden");
  const _bc = $("ia3d-bp-chips"); if (_bc) _bc.style.minHeight = "";
  const ovStatus = $("ia3d-overlay-status");
  if (ovStatus) ovStatus.textContent = "";
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k reset_for_open`
Expected: PASS.

- [ ] **Step 5: Confirm the full inline + policy suite stays green**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_policy.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "fix(dlc-3d): clear markerEditor layer + reset primary select on video switch

_resetForOpen now calls setPrimary(null) and resets the primary <select> to its
placeholder, so switching videos never leaves the previous video's poses live
(Bug-1 clean base). Overlay stays off; coverage cache still clears.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `_refreshOverlayH5Variants` stops auto-picking on videoLoad

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (`_refreshOverlayH5Variants` ~801-836, the `variants.length === 1` auto-pick block ~829-835)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing source guard**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_refresh_variants_does_not_auto_pick_on_videoload():
    """Bug-1 clean switch: _refreshOverlayH5Variants (run off videoLoad) must only
    populate the primary <select>; it must NOT auto-pick / call _applyOverlayPrimary
    (the old single-variant branch did). The selection stays on the placeholder
    until the user turns the kinematics view on."""
    js = JS.read_text()
    i = js.find("async function _refreshOverlayH5Variants(")
    assert i > 0, "_refreshOverlayH5Variants not found"
    end = js.find("\nasync function ", i + 1)
    body = js[i:end if end > 0 else i + 1500]
    assert "_applyOverlayPrimary(" not in body, \
        "_refreshOverlayH5Variants must not auto-pick (no _applyOverlayPrimary call)"
    # the single-variant auto-pick branch must be gone
    assert "variants.length === 1" not in body, \
        "the single-variant auto-pick branch must be removed (clean switch)"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k refresh_variants_does_not_auto_pick`
Expected: FAIL — `_applyOverlayPrimary(` and `variants.length === 1` still present in the body.

- [ ] **Step 3: Remove the auto-pick block**

In `inline_analysis_3d.js`, the tail of `_refreshOverlayH5Variants` currently reads (lines 829-835):

```javascript
  // Auto-pick when exactly one variant exists.
  if (variants.length === 1) {
    primarySel.value = variants[0].path;
    await _applyOverlayPrimary(variants[0].path);
  } else {
    _overlayPrimaryH5 = null;
  }
}
```

Replace it with a populate-only tail (no auto-pick; leave the selection on the placeholder):

```javascript
  // Bug-1 clean switch: populate the dropdown ONLY — do NOT auto-pick on videoLoad.
  // The user turns the kinematics view on (overlay toggle) to load + render the
  // latest variant. Leave the selection on the placeholder + clear the active primary.
  primarySel.value = "";
  _overlayPrimaryH5 = null;
}
```

Also update the docstring above `_refreshOverlayH5Variants` (lines 797-800) — replace the stale "then auto-pick when exactly one variant exists" wording:

```javascript
// Populate the primary h5 select for the current primary video (placeholder + one
// option per variant). Called off videoLoad. Does NOT auto-pick — the overlay-toggle
// ON handler picks the latest variant when the user turns the kinematics view on
// (Bug-1 clean switch). This card has no add-comparison dropdown (removed 2026-05-21).
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k refresh_variants_does_not_auto_pick`
Expected: PASS.

- [ ] **Step 5: Confirm the inline + policy suite stays green**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_policy.py -q`
Expected: PASS. (Note: `test_discover_does_not_depend_on_removed_compare_dropdown` reads `_iaDiscoverVariants`, which still calls `_refreshOverlayH5Variants` — unaffected.)

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "fix(dlc-3d): stop auto-picking the h5 variant on videoLoad (clean switch)

_refreshOverlayH5Variants now only populates the primary <select> and leaves the
selection on the placeholder; the single-variant auto-pick that snapped markers on
switch (Bug-1) is removed. The overlay-toggle ON handler picks the latest variant.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Overlay-toggle ON enables + auto-picks LATEST + renders; `_applyOverlayPrimary` drops force-enable

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (import `pickLatestVariant`; overlay-toggle change handler ~740-749; `_applyOverlayPrimary` ~861-896, the force-overlay-enable block ~886-894)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing source guards**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_overlay_toggle_on_autopicks_latest_variant():
    """Bug-1 B2: turning the kinematics view ON enables the overlay AND, if no
    primary is selected yet, auto-picks the LATEST variant (via pickLatestVariant)
    by setting the <select> + calling _applyOverlayPrimary, then refreshes coverage."""
    js = JS.read_text()
    # the pure latest-variant helper is imported
    assert "pick_latest_variant.mjs" in js, "must import the pickLatestVariant helper"
    assert "pickLatestVariant" in js, "overlay-on must use pickLatestVariant"
    # the overlay-toggle change handler enables + auto-picks + refreshes coverage
    i = js.find('$("ia3d-overlay-toggle")')
    assert i > 0
    # capture the change-handler body
    j = js.find("addEventListener", i)
    body = js[j:j + 900]
    assert "setOverlayEnabled(on)" in body, "toggle must drive setOverlayEnabled(on)"
    assert "pickLatestVariant(" in body, "toggle-ON must auto-pick the latest variant"
    assert "_applyOverlayPrimary(" in body, "toggle-ON must apply the picked primary"
    assert "_refreshCoverage()" in body, "toggle must refresh coverage"


def test_apply_overlay_primary_drops_force_enable_keeps_set_editable():
    """B1: _applyOverlayPrimary must NOT force-enable the overlay (no overlay-toggle
    dispatch); it KEEPS arming editing via setEditable(true) when Finalize is on."""
    js = JS.read_text()
    i = js.index("async function _applyOverlayPrimary")
    rest = js[i + 1:]
    ends = [x for x in (rest.find("\nasync function "), rest.find("\nfunction ")) if x != -1]
    window = js[i: i + 1 + min(ends)]
    assert "setEditable(true)" in window, "must still arm editing when Finalize is on"
    assert "ia3d-overlay-toggle" not in window, \
        "_applyOverlayPrimary must not force-enable the overlay toggle"
    assert "dispatchEvent" not in window, \
        "_applyOverlayPrimary must not dispatch the overlay-toggle change"
```

Note: `test_apply_overlay_primary_drops_force_enable_keeps_set_editable` mirrors the existing `test_apply_overlay_primary_no_longer_force_enables_overlay` (lines 731-745) — both must pass. The current `_applyOverlayPrimary` does NOT contain `ia3d-overlay-toggle`/`dispatchEvent` today (the force-enable was already replaced by `setEditable` in the 2026-05-24 work), so these two assertions already hold; this task ensures the code stays that way after the toggle-handler change and adds the explicit B2 guard.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k "overlay_toggle_on_autopicks or drops_force_enable"`
Expected: FAIL — `test_overlay_toggle_on_autopicks_latest_variant` fails (`pick_latest_variant.mjs`/`pickLatestVariant` not imported, no auto-pick in the toggle handler). (`drops_force_enable` may already pass — that is fine; the run still shows the autopick failure.)

- [ ] **Step 3: Import `pickLatestVariant`**

In `inline_analysis_3d.js`, add the import beside the other coverage/internal imports (after line 23, the `coverage_timeline.mjs` import):

```javascript
import { pickLatestVariant } from "./components/viewer/internal/pick_latest_variant.mjs";
```

- [ ] **Step 4: Rewrite the overlay-toggle change handler (enable + auto-pick latest + render)**

The current handler (lines 740-749) reads:

```javascript
  // Overlay enable toggle → markerEditor.setOverlayEnabled + reveal controls + coverage refresh.
  const toggle = $("ia3d-overlay-toggle");
  toggle?.addEventListener("change", () => {
    const on = !!toggle.checked;
    _markerEditor?.setOverlayEnabled(on);
    $("ia3d-overlay-controls")?.classList.toggle("hidden", !on);
    $("ia3d-bp-list-wrap")?.classList.toggle("hidden", !on);
    const st = $("ia3d-overlay-status");
    if (st) st.textContent = on ? "overlay on" : "overlay off";
    _refreshCoverage();
  });
```

Replace it with the auto-pick-latest-on-ON variant (async so it can await the pick):

```javascript
  // Overlay enable toggle → markerEditor.setOverlayEnabled + reveal controls + coverage.
  // B2 (Bug-1): on turning the view ON, if no primary is selected yet, auto-pick the
  // LATEST h5 variant (pickLatestVariant over the current dropdown options) and render.
  const toggle = $("ia3d-overlay-toggle");
  toggle?.addEventListener("change", async () => {
    const on = !!toggle.checked;
    _markerEditor?.setOverlayEnabled(on);
    $("ia3d-overlay-controls")?.classList.toggle("hidden", !on);
    $("ia3d-bp-list-wrap")?.classList.toggle("hidden", !on);
    const st = $("ia3d-overlay-status");
    if (st) st.textContent = on ? "overlay on" : "overlay off";
    if (on && !_overlayPrimaryH5) {
      const latest = await _pickLatestVariantForCurrentVideo();
      if (latest) {
        const sel = $("ia3d-overlay-primary-select");
        if (sel) sel.value = latest;
        await _applyOverlayPrimary(latest);   // sets primary + sibling + arms editing + coverage
      }
    }
    _refreshCoverage();
  });
```

- [ ] **Step 5: Add the `_pickLatestVariantForCurrentVideo` fetch+pick helper**

Insert this helper immediately ABOVE `_refreshOverlayH5Variants` (before line 797's docstring) so it can be reused by the toggle handler. It re-fetches the variants (cheap, server-cached) and applies the rule:

```javascript
// Fetch the current primary video's h5 variants and return the LATEST one's path
// (pickLatestVariant: max ISO ts, else the last array element; null when none). Used
// by the overlay-toggle ON handler to load the freshest analysis on demand (B2).
async function _pickLatestVariantForCurrentVideo() {
  if (!_primaryRel) return null;
  try {
    const data = await (await fetch(
      `/dlc/viewer/h5-variants?video=${encodeURIComponent(_primaryRel)}`,
    )).json();
    const latest = pickLatestVariant(data.variants || []);
    return latest ? latest.path : null;
  } catch (_) {
    return null;
  }
}
```

- [ ] **Step 6: Verify `_applyOverlayPrimary` has no force-enable block (keep `setEditable`)**

Read `_applyOverlayPrimary` (lines 861-896). The force-overlay-enable block was already removed in the 2026-05-24 work; the current tail (lines 886-895) only re-arms editing:

```javascript
  if ($("ia3d-finalize-toggle")?.checked) {
    _markerEditor.setEditable(true);
  }
  _refreshCoverage();
```

Confirm NO `ia3d-overlay-toggle` reference and NO `dispatchEvent` remain inside `_applyOverlayPrimary`. If a force-enable block is present (e.g. an older checkout), remove it — keep ONLY the `setEditable(true)` arming above. No edit is needed if the function already matches.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k "overlay_toggle_on_autopicks or drops_force_enable or no_longer_force_enables"`
Expected: PASS.

- [ ] **Step 8: Confirm the full inline + policy suite stays green**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_video_viewer_policy.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): overlay-toggle ON auto-picks the latest h5 variant + renders

Turning the kinematics view on now enables the overlay and, when no primary is
selected, auto-picks the LATEST variant via pickLatestVariant + _applyOverlayPrimary
(which arms editing when Finalize is on). _applyOverlayPrimary keeps setEditable and
does not force-enable the overlay.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Post-analysis handlers invalidate `_coverageCache` + call `invalidatePoses()`

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (`_onAnalyzeClick` ~1869-1890; `_onAnalyzeRangeConfinedClick` ~1925-1937)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the failing source guard**

Append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_post_analysis_handlers_invalidate_caches_and_refresh():
    """Bug-2: after a re-analysis completes, BOTH done handlers (_onAnalyzeClick,
    _onAnalyzeRangeConfinedClick) must invalidate the stale client caches —
    _coverageCache (cleared) + markerEditor.invalidatePoses() — and re-run the
    coverage refresh, so the in-place-overwritten h5 repaints without a manual
    re-select. Works for 1 or many variants (not gated on count)."""
    js = JS.read_text()
    for fn in ("_onAnalyzeClick", "_onAnalyzeRangeConfinedClick"):
        i = js.find(f"async function {fn}(")
        assert i > 0, f"{fn} not found"
        end = js.find("\nasync function ", i + 1)
        body = js[i:end if end > 0 else i + 2200]
        assert "_coverageCache.clear()" in body, \
            f"{fn} must clear _coverageCache after analysis (Bug-2)"
        assert "invalidatePoses()" in body, \
            f"{fn} must call markerEditor.invalidatePoses() after analysis (Bug-2)"
        assert "_refreshCoverage()" in body, \
            f"{fn} must re-run the (cache-busted) coverage refresh after analysis"
    # invalidation must NOT be gated on a single-variant branch
    assert "variants.length === 1" not in js, \
        "post-analysis refresh must not depend on variant count"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k post_analysis_handlers_invalidate`
Expected: FAIL — `_coverageCache.clear()` / `invalidatePoses()` / `_refreshCoverage()` not all present in both handlers.

- [ ] **Step 3: Add cache invalidation to `_onAnalyzeClick`**

In `_onAnalyzeClick`, the tail (lines 1877-1890) currently ends the frame-preserving reload with:

```javascript
  // Frame-preserving viewer reload so the overlay repaints over the same frame.
  if (_viewer && _primaryRel) {
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3d-sync-cam");
    await _viewer.load({
      videoPath: _primaryRel,
      frameCount: _frameCount,
      framesMode,
      siblingPath: sync?.checked && !framesMode ? undefined : null,
    });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
}
```

Append the Bug-2 invalidation after `_applyCamLabels();` (inside the `if` block, so it runs once the viewer has reloaded):

```javascript
  // Frame-preserving viewer reload so the overlay repaints over the same frame.
  if (_viewer && _primaryRel) {
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3d-sync-cam");
    await _viewer.load({
      videoPath: _primaryRel,
      frameCount: _frameCount,
      framesMode,
      siblingPath: sync?.checked && !framesMode ? undefined : null,
    });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  // Bug-2: inline analysis OVERWRITES the same h5 in place, so the client caches
  // (markerEditor.posesCache keyed by path+threshold, _coverageCache keyed by
  // path+threshold+width) serve stale data until a manual re-select. Invalidate both
  // and re-run the (now cache-busted) coverage refresh so the new poses + timeline
  // repaint. Works for 1 or many variants (not gated on count).
  _coverageCache.clear();
  _markerEditor?.invalidatePoses();
  _refreshCoverage();
}
```

- [ ] **Step 4: Add cache invalidation to `_onAnalyzeRangeConfinedClick`**

In `_onAnalyzeRangeConfinedClick`, the tail (lines 1929-1938) currently reads:

```javascript
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

Insert the same Bug-2 invalidation before `_refreshAnalyzeEnablement();`:

```javascript
  if (_viewer && _primaryRel) {
    const keepFrame = _viewer.currentFrame();
    const framesMode = _iaMode === "frames";
    const sync = $("ia3d-sync-cam");
    await _viewer.load({ videoPath: _primaryRel, frameCount: _frameCount, framesMode, siblingPath: sync?.checked && !framesMode ? undefined : null });
    if (keepFrame > 0) _viewer.seek(keepFrame);
    _applyCamLabels();
  }
  // Bug-2: same in-place-overwrite cache invalidation as _onAnalyzeClick — drop the
  // stale coverage + pose caches and repaint. Not gated on variant count.
  _coverageCache.clear();
  _markerEditor?.invalidatePoses();
  _refreshCoverage();
  _refreshAnalyzeEnablement();
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q -k post_analysis_handlers_invalidate`
Expected: PASS.

- [ ] **Step 6: Confirm the full suite stays green (inline + policy + marker-editor + unit)**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_inline_analysis_3d_ui_isolation.py tests/test_marker_editor_feature.py tests/test_video_viewer_policy.py -q && node --test tests/unit/test_pick_latest_variant.mjs`
Expected: PASS (pytest all green; node 6 tests pass). In particular `test_dispatch_runs_both_cameras_against_main_webapp_api` (asserts `setOverlayEnabled(true)` + `_viewer.load(` + `_iaDiscoverVariants(cam0)` remain) stays green — those lines are untouched.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add src/static/inline_analysis_3d.js tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "fix(dlc-3d): refresh markers + coverage after in-place re-analysis (Bug-2)

Both analyze done-handlers now clear _coverageCache, call
markerEditor.invalidatePoses(), and re-run _refreshCoverage so the
in-place-overwritten h5 repaints without a manual re-select. Works for any
variant count.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Holistic live verify (read-only) + View-Analyzed regression guard

**Files:** none modified (verification only).

- [ ] **Step 1: Full regression sweep (all tests + unit)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && \
  python -m pytest tests/ -q && \
  node --test tests/unit/test_pick_latest_variant.mjs tests/unit/test_viewer_marker_overlay.mjs
```
Expected: pytest all green; node tests pass. (JS is bind-mounted live — no rebuild needed. No template change in this plan, so no `docker compose restart dlc-3d` required.)

- [ ] **Step 2: Live verify the INLINE clean switch + view-on (read-only)**

Drive Playwright (Python). Auth: `GET http://localhost:5000/?token=deeplabcut`. DO NOT run Start analysis / Add range / Extract / Finalize / Delete / Save.

```python
# pseudo-steps — adapt to the existing playwright harness
# 1. Open the page authed, open the 3D Inline Analysis card.
# 2. Open posed video DREADD-Ali / khoai-lang-1 cam0.
# 3. Assert clean base: #ia3d-overlay-toggle UNCHECKED; #ia3d-overlay-primary-select
#    value == "" (placeholder); NO markers drawn on the cam0 tile canvas.
# 4. Switch to another posed video, then back. Re-assert the clean base
#    (toggle unchecked, select on placeholder, no markers) — the previous video's
#    layer must NOT carry over (Bug-1 fixed).
# 5. Turn the kinematics view ON (check #ia3d-overlay-toggle). Assert:
#    - #ia3d-overlay-primary-select now shows a non-empty value (the LATEST variant),
#    - markers render on the cam0 tile,
#    - editing is armed (Finalize is checked by default) — placing/selecting works.
# 6. Turn the view OFF → markers hide; controls/chips hidden.
```
Expected: clean base on every open/switch; the view-on auto-picks the latest variant + renders + edits.

- [ ] **Step 3: Live verify the VIEW ANALYZED regression (read-only)**

Open the View Analyzed card (`viewer_3d.js`) on the same posed video and confirm NO behavior change vs. before this work:
```python
# 1. Open View Analyzed; open a posed video.
# 2. Turn its overlay on → markers render (its single-variant auto-pick + overlay
#    keying are UNCHANGED — viewer_3d.js was not modified).
# 3. Edit a marker (drag/place) → edit works.
# 4. Switch videos → behaves exactly as before (View Analyzed never calls
#    invalidatePoses(); setPrimary(null) is never invoked by it).
```
Expected: View Analyzed renders on overlay-on, edits, and switches videos exactly as before — no regression. (Bug-2's `invalidatePoses()` is additive and never called by View Analyzed.)

- [ ] **Step 4: Document Bug-2 coverage**

Bug-2 (post-analysis refresh) is verified by:
- `tests/test_marker_editor_feature.py::test_invalidate_poses_clears_cache_and_rerenders` (the method clears both cams' `posesCache` + re-renders via `onFrame`),
- `tests/test_inline_analysis_3d_ui_isolation.py::test_post_analysis_handlers_invalidate_caches_and_refresh` (both handlers clear `_coverageCache` + call `invalidatePoses()` + `_refreshCoverage()`),
- code review of the in-place-overwrite cache mechanism.

It is NOT exercised by running analysis live (protected `/user-data`). Record this in the verification notes. If a safe re-analyze path against a non-protected fixture exists, it MAY be exercised; otherwise it is covered by the tests above.

- [ ] **Step 5: Final commit (if any verification notes/fixtures were added)**

If no files changed in this task, skip the commit. Otherwise:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
git add -A
git commit -m "test(dlc-3d): document Bug-2 coverage + live-verify notes for clean switch

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage**

- §Behaviors B1 (clean switch — clear markerEditor layer, reset overlay state, no auto-pick on videoLoad): Tasks 1 (`setPrimary(null)` clearing), 3 (`_resetForOpen` calls it + resets select), 4 (`_refreshOverlayH5Variants` no auto-pick). ✓
- §Behaviors B2 (view ON → enable + auto-pick LATEST + render; `_applyOverlayPrimary` drops force-enable, keeps `setEditable`): Task 5. ✓
- §Behaviors B3 (`invalidatePoses()` clears every layer's posesCache + re-renders current frame; post-analysis handlers invalidate `_coverageCache` + call `invalidatePoses()` + refresh; works for 1 or many variants): Tasks 1 + 6. ✓
- §Files (modify `inline_analysis_3d.js`, `marker_editor.js`, both test files; possibly a `.mjs` helper): all covered; the `.mjs` helper IS extracted (Task 2). ✓
- §View Analyzed regression guard: Task 7 Step 3. ✓
- §Error handling (`setPrimary(null)` safe — Task 1 makes it explicitly clear; `invalidatePoses()` no-ops without layers — `onFrame` renders empty; "latest" tolerates empty list — `pickLatestVariant([]) → null`): ✓
- §Testing (pytest inline + marker-editor guards; policy stays green; live read-only; Bug-2 by code+tests): Tasks 1,3,4,5,6 (pytest), 7 (policy + live + Bug-2 doc). ✓

**2. Placeholder scan** — No "TBD/TODO/handle edge cases/similar to". Every code step shows the full code; every test step shows the full assertions; every run step gives the exact command + expected output. The Playwright steps are pseudo-code by necessity (read-only manual verification against a live, protected environment) and are explicitly framed as adapt-to-harness, not as code to author — acceptable for a verification task.

**3. Name consistency** — `invalidatePoses()` (Task 1 defines it on the public block; Tasks 6/7 call it), `pickLatestVariant` (Task 2 defines in `pick_latest_variant.mjs`; Task 5 imports + uses it via `_pickLatestVariantForCurrentVideo`), `setPrimary(null)` (Task 1 extends; Task 3 calls), `_coverageCache.clear()` / `_refreshCoverage()` / `_applyOverlayPrimary` / `_overlayPrimaryH5` / `_refreshOverlayH5Variants` (all match the real source). The new inline helper `_pickLatestVariantForCurrentVideo` is defined in Task 5 Step 5 and referenced only by the toggle handler in Task 5 Step 4 (same task) — consistent. No signature drift found.
