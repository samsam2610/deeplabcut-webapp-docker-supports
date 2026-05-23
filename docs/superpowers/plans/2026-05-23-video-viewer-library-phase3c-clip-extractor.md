# Video-Viewer Library — Phase 3c (ClipExtractor feature) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `ClipExtractor` feature module — trim the master clip (clip-cutter gold standard): start/length/end inputs, postfix + quick-tags, keyframe-overlap check, synchronous extract of the primary (and optionally the sibling cam over the same frame range), plus rename/delete of the produced clip. Gated behind an "enable clip extract" checkbox that is **unchecked by default**.

**Architecture:** Same split as the other features: pure reducer `internal/clip_extract.mjs` (request builders + postfix-tag list ops, reusing `clip_naming.mjs` — node-tested) + DOM feature `features/clip_extractor.js` (`clipExtractor(config)` → `{ attach(viewer) }`) verified by a pytest contract + code review. All endpoints/elements injected. Follows the feature-teardown pattern.

**Scope note:** v1 is a *direct* synchronous trim (overlap-check → extract → optional sibling). clip-cutter's queue+SSE machinery is intentionally NOT ported — it is tied to clip-cutter's detection-list batch workflow (app-specific), not to trimming a master clip. Queue support can be a future extension.

**Tech Stack:** Vanilla ES modules; `node:test` for the reducer; pytest regex contract for the feature.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.4 ExtractModule).

**Source of truth (clip-cutter gold standard, frozen):** `clip-cutter/static/enhanced_player.js` — extract payload (1699-1725), end calc `start+frames-1` (349-352), keyframe = `start+200` (1708), rename (1871-1900), delete (1818-1868), overlap check (1643-1696), postfix quick-tags localStorage (40-46, 725-756, add 1997-2005). `clip-cutter/routes.py` — `/extract` accepts `{video_path, key_frame, start_fn, end_fn, postfix}` → `{avi_path, csv_path}` (1132-1157); `/extract/rename` `{avi_path, postfix}` → `{avi_path}`; `/extract/delete` `{avi_path}`; `/check-keyframe-overlap` `{video_path, key_frame}` → `{overlaps, conflicts:[{name, overlap_frames}]}`. Sibling trim = a second `/extract` on the sibling video over the SAME frame range. The clip geometry (`clipWindow`, `computeEnd`, `sanitizePostfix`, `buildClipStem`, `parseClipStem`) already lives in the tested `clip_naming.mjs` (Phase 1).

**Commands:**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_clip_extract.mjs          # Task 1
python -m pytest tests/test_clip_extractor_feature.py -q      # Task 2 (static; launches no app)
```

---

## Task 1: `clip_extract.mjs` — pure request builders + tag-list ops

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/clip_extract.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_clip_extract.mjs`

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_clip_extract.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  keyFrameForStart, buildExtractRequest, buildRenameRequest,
  buildDeleteRequest, buildOverlapRequest, addTag, removeTagAt,
} from "../../src/static/components/viewer/internal/clip_extract.mjs";

test("keyFrameForStart = start + preWindow (default 200)", () => {
  assert.equal(keyFrameForStart(300), 500);
  assert.equal(keyFrameForStart(300, 100), 400);
});

test("buildExtractRequest: end = start+frames-1, keyframe, sanitized postfix", () => {
  assert.deepEqual(
    buildExtractRequest({ videoPath: "v.avi", start: 301, frames: 800, postfix: "go od!" }),
    { video_path: "v.avi", key_frame: 501, start_fn: 301, end_fn: 1100, postfix: "good" });
});

test("buildRenameRequest sanitizes the postfix", () => {
  assert.deepEqual(buildRenameRequest({ aviPath: "/c.avi", postfix: "a b#c" }),
    { avi_path: "/c.avi", postfix: "abc" });
});

test("buildDeleteRequest / buildOverlapRequest shapes", () => {
  assert.deepEqual(buildDeleteRequest({ aviPath: "/c.avi" }), { avi_path: "/c.avi" });
  assert.deepEqual(buildOverlapRequest({ videoPath: "v.avi", start: 300 }),
    { video_path: "v.avi", key_frame: 500 });
});

test("addTag: trims, dedups, ignores empty; returns a new array", () => {
  assert.deepEqual(addTag(["a"], "b"), ["a", "b"]);
  assert.deepEqual(addTag(["a"], "  a  "), ["a"]);   // dedup after trim
  assert.deepEqual(addTag(["a"], "   "), ["a"]);     // empty ignored
  const base = ["a"];
  addTag(base, "b");
  assert.deepEqual(base, ["a"]);                      // no mutation
});

test("removeTagAt: removes by index, ignores out-of-range, new array", () => {
  assert.deepEqual(removeTagAt(["a", "b", "c"], 1), ["a", "c"]);
  assert.deepEqual(removeTagAt(["a"], 5), ["a"]);
  const base = ["a", "b"];
  removeTagAt(base, 0);
  assert.deepEqual(base, ["a", "b"]);                 // no mutation
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_clip_extract.mjs`
Expected: FAIL — cannot find module `clip_extract.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/clip_extract.mjs`:

```js
// Pure clip-trim request builders + postfix quick-tag list ops for the ClipExtractor
// feature. Clip geometry/naming lives in clip_naming.mjs (Phase 1); this reuses it.

import { computeEnd, sanitizePostfix } from "./clip_naming.mjs";

// clip-cutter convention: the keyframe sits `preWindow` frames after the clip start.
export function keyFrameForStart(start, preWindow = 200) {
  return start + preWindow;
}

export function buildExtractRequest({ videoPath, start, frames, postfix, preWindow = 200 }) {
  return {
    video_path: videoPath,
    key_frame: keyFrameForStart(start, preWindow),
    start_fn: start,
    end_fn: computeEnd(start, frames),
    postfix: sanitizePostfix(postfix),
  };
}

export function buildRenameRequest({ aviPath, postfix }) {
  return { avi_path: aviPath, postfix: sanitizePostfix(postfix) };
}

export function buildDeleteRequest({ aviPath }) {
  return { avi_path: aviPath };
}

export function buildOverlapRequest({ videoPath, start, preWindow = 200 }) {
  return { video_path: videoPath, key_frame: keyFrameForStart(start, preWindow) };
}

// postfix quick-tag list operations (pure; the feature persists to localStorage).
export function addTag(tags, tag) {
  const t = (tag || "").trim();
  if (!t || tags.includes(t)) return tags.slice();
  return [...tags, t];
}

export function removeTagAt(tags, idx) {
  const next = tags.slice();
  if (idx >= 0 && idx < next.length) next.splice(idx, 1);
  return next;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_clip_extract.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/clip_extract.mjs dlc-3D/tests/unit/test_viewer_clip_extract.mjs
git commit -m "feat(dlc-3d viewer-lib): clip_extract.mjs (clip request builders + tag ops) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `features/clip_extractor.js` — the ClipExtractor feature module

**Files:**
- Create: `dlc-3D/src/static/components/viewer/features/clip_extractor.js`
- Test: `dlc-3D/tests/test_clip_extractor_feature.py`

- [ ] **Step 1: Write the failing contract test**

Create `dlc-3D/tests/test_clip_extractor_feature.py`:

```python
"""Static-analysis contract for the ClipExtractor feature module (Phase 3c).

Browser ESM cannot import under Node; enforced by regex over source + code review.
The pure request/tag logic is node-tested separately (test_viewer_clip_extract.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
CE = ROOT / "src" / "static" / "components" / "viewer" / "features" / "clip_extractor.js"


def _src():
    assert CE.is_file(), f"missing clip_extractor feature at {CE}"
    return CE.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+clipExtractor\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bclipExtractor\b[^}]*\}", _src()), \
        "must export `clipExtractor`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name,module", [
    ("buildExtractRequest", "clip_extract"),
    ("buildRenameRequest", "clip_extract"),
    ("buildDeleteRequest", "clip_extract"),
    ("buildOverlapRequest", "clip_extract"),
    ("addTag", "clip_extract"),
    ("removeTagAt", "clip_extract"),
    ("computeEnd", "clip_naming"),
])
def test_imports_reducer(name, module):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*{module}\.mjs[\"']", _src()), \
        f"must import {name} from internal/{module}.mjs (no re-implementation)"


def test_disposes_on_teardown():
    src = _src()
    assert '"teardown"' in src or "'teardown'" in src, "must subscribe to the viewer 'teardown' hook"


def test_storage_key_namespaced_by_prefix():
    # the postfix-tags localStorage key must derive from storagePrefix, not be a literal
    assert re.search(r"storagePrefix", _src()), "postfix-tag storage key must use storagePrefix"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_clip_extractor_feature.py -q`
Expected: FAIL — `missing clip_extractor feature at ...`.

- [ ] **Step 3: Write the feature module**

Create `dlc-3D/src/static/components/viewer/features/clip_extractor.js`:

```js
// ClipExtractor — feature module for VideoViewer.
// Trims the master clip (clip-cutter gold standard): start/length/end inputs, postfix +
// quick-tags, keyframe-overlap check, synchronous extract of the primary (and optionally
// the sibling cam over the same frame range), plus rename/delete of the produced clip.
// Gated behind an "enable clip extract" checkbox that is UNCHECKED by default (the consumer
// renders it unchecked; the panel starts hidden until enabled). All endpoints/elements
// injected; follows the feature-teardown pattern.
//
// Usage:
//   viewer.use(clipExtractor({
//     endpoints: {
//       extractClip: (payload) => fetchPromise,  // → { avi_path }
//       rename?:     (payload) => fetchPromise,  // → { avi_path }
//       del?:        (payload) => fetchPromise,
//       overlap?:    (payload) => fetchPromise,  // → { overlaps, conflicts:[{name,overlap_frames}] }
//     },
//     els: { enable, panel, startInput, framesInput, endDisplay, postfixInput,
//            extractBtn, renameBtn, deleteBtn, extractSibling?,
//            tagsContainer?, addTagBtn?, newTagInput?, statusDisplay?, warning? },
//     storagePrefix?: "vv", preWindow?: 200, defaultFrames?: 800,
//     onExtracted?: ({ primary, sibling }) => void,
//   }));

import {
  buildExtractRequest, buildRenameRequest, buildDeleteRequest,
  buildOverlapRequest, addTag, removeTagAt,
} from "../internal/clip_extract.mjs";
import { computeEnd } from "../internal/clip_naming.mjs";

export function clipExtractor(config = {}) {
  const els = config.els || {};
  const endpoints = config.endpoints || {};
  const storagePrefix = config.storagePrefix || "vv";
  const preWindow = config.preWindow ?? 200;
  const defaultFrames = config.defaultFrames || 800;
  const TAGS_KEY = `${storagePrefix}:clip-postfix-tags`;

  let viewer = null;
  let tags = [];
  let activeTag = null;
  let lastPrimaryAvi = null;
  let lastSiblingAvi = null;

  const setStatus = (m) => { if (els.statusDisplay) els.statusDisplay.textContent = m; };
  const siblingPath = () => { const t = viewer && viewer.getTile(1); return t ? t.videoRel : null; };
  const wantSibling = () => Boolean(siblingPath()) && (els.extractSibling ? els.extractSibling.checked : false);
  const readStart = () => parseInt(els.startInput && els.startInput.value, 10) || 1;
  const readFrames = () => parseInt(els.framesInput && els.framesInput.value, 10) || defaultFrames;
  const readPostfix = () => (els.postfixInput ? els.postfixInput.value : "");

  function updateEnd() {
    if (els.endDisplay) els.endDisplay.value = computeEnd(readStart(), readFrames());
  }

  // ── postfix quick-tags (localStorage, namespaced by storagePrefix) ──
  function loadTags() {
    try { tags = JSON.parse(localStorage.getItem(TAGS_KEY)) || []; } catch (_) { tags = []; }
  }
  function persistTags() {
    try { localStorage.setItem(TAGS_KEY, JSON.stringify(tags)); } catch (_) { /* ignore */ }
  }
  function renderTags() {
    const c = els.tagsContainer;
    if (!c) return;
    c.innerHTML = "";
    tags.forEach((tag, idx) => {
      const pill = c.ownerDocument.createElement("span");
      pill.className = "vv-postfix-tag" + (activeTag === tag ? " active" : "");
      const label = c.ownerDocument.createElement("span");
      label.textContent = tag;
      const del = c.ownerDocument.createElement("span");
      del.className = "vv-tag-del";
      del.textContent = "×";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        tags = removeTagAt(tags, idx);
        if (activeTag === tag) { activeTag = null; if (els.postfixInput) els.postfixInput.value = ""; }
        persistTags();
        renderTags();
      });
      pill.appendChild(label);
      pill.appendChild(del);
      pill.addEventListener("click", () => {
        if (activeTag === tag) { activeTag = null; if (els.postfixInput) els.postfixInput.value = ""; }
        else { activeTag = tag; if (els.postfixInput) els.postfixInput.value = tag; }
        renderTags();
      });
      c.appendChild(pill);
    });
  }
  function addNewTag() {
    const next = addTag(tags, els.newTagInput ? els.newTagInput.value : "");
    if (next.length !== tags.length) { tags = next; persistTags(); renderTags(); }
    if (els.newTagInput) els.newTagInput.value = "";
  }

  // ── enable gate (panel hidden until the checkbox is checked) ──
  function applyEnabled() {
    const on = els.enable ? els.enable.checked : true;
    if (els.panel) els.panel.classList.toggle("hidden", !on);
  }

  function updateExtractActions() {
    const has = Boolean(lastPrimaryAvi);
    if (els.renameBtn) els.renameBtn.disabled = !has;
    if (els.deleteBtn) els.deleteBtn.disabled = !has;
  }

  // ── overlap warning (resolve true to proceed) ──
  function confirmOverlap(conflicts) {
    return new Promise((resolve) => {
      const w = els.warning;
      if (!w) { resolve(true); return; }
      w.innerHTML = "";
      const c = conflicts && conflicts[0];
      const msg = w.ownerDocument.createElement("div");
      msg.textContent = c ? `⚠ Overlaps ${c.name} by ${c.overlap_frames} fr` : "⚠ Overlap detected";
      const cancel = w.ownerDocument.createElement("button");
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", () => { w.classList.add("hidden"); resolve(false); });
      const keep = w.ownerDocument.createElement("button");
      keep.textContent = "Keep anyway";
      keep.addEventListener("click", () => { w.classList.add("hidden"); resolve(true); });
      w.appendChild(msg);
      w.appendChild(cancel);
      w.appendChild(keep);
      w.classList.remove("hidden");
    });
  }

  async function doExtract() {
    if (!viewer || !endpoints.extractClip) return;
    const videoPath = viewer.videoPath();
    if (!videoPath) return;
    const start = readStart();
    const frames = readFrames();
    const postfix = readPostfix();

    if (endpoints.overlap) {
      try {
        const ov = await (await endpoints.overlap(buildOverlapRequest({ videoPath, start, preWindow }))).json();
        if (ov.overlaps && !(await confirmOverlap(ov.conflicts))) return;
      } catch (_) { /* overlap check best-effort */ }
    }

    setStatus("Extracting…");
    try {
      const primary = await (await endpoints.extractClip(
        buildExtractRequest({ videoPath, start, frames, postfix, preWindow }))).json();
      if (primary.error) { setStatus(primary.error); return; }
      lastPrimaryAvi = primary.avi_path || null;
      lastSiblingAvi = null;
      if (wantSibling()) {
        const sib = await (await endpoints.extractClip(
          buildExtractRequest({ videoPath: siblingPath(), start, frames, postfix, preWindow }))).json();
        lastSiblingAvi = sib.avi_path || null;
      }
      setStatus("Extracted" + (lastSiblingAvi ? " (+sibling)" : ""));
      updateExtractActions();
      if (config.onExtracted) config.onExtracted({ primary: lastPrimaryAvi, sibling: lastSiblingAvi });
    } catch (e) {
      setStatus("Network error: " + e.message);
    }
  }

  async function doRename() {
    if (!lastPrimaryAvi || !endpoints.rename) return;
    const postfix = readPostfix();
    try {
      const r = await (await endpoints.rename(buildRenameRequest({ aviPath: lastPrimaryAvi, postfix }))).json();
      if (r.avi_path) lastPrimaryAvi = r.avi_path;
      if (lastSiblingAvi) {
        const rs = await (await endpoints.rename(buildRenameRequest({ aviPath: lastSiblingAvi, postfix }))).json();
        if (rs.avi_path) lastSiblingAvi = rs.avi_path;
      }
      setStatus("Renamed");
    } catch (e) {
      setStatus("Network error: " + e.message);
    }
  }

  async function doDelete() {
    if (!lastPrimaryAvi || !endpoints.del) return;
    try {
      await endpoints.del(buildDeleteRequest({ aviPath: lastPrimaryAvi }));
      if (lastSiblingAvi) await endpoints.del(buildDeleteRequest({ aviPath: lastSiblingAvi }));
      lastPrimaryAvi = null;
      lastSiblingAvi = null;
      updateExtractActions();
      setStatus("Deleted");
    } catch (e) {
      setStatus("Network error: " + e.message);
    }
  }

  return {
    attach(v) {
      viewer = v;
      loadTags();
      renderTags();
      updateEnd();
      applyEnabled();
      updateExtractActions();
      const ac = new AbortController();
      const sig = { signal: ac.signal };
      if (els.enable) els.enable.addEventListener("change", applyEnabled, sig);
      if (els.startInput) els.startInput.addEventListener("input", updateEnd, sig);
      if (els.framesInput) els.framesInput.addEventListener("input", updateEnd, sig);
      if (els.extractBtn) els.extractBtn.addEventListener("click", doExtract, sig);
      if (els.renameBtn) els.renameBtn.addEventListener("click", doRename, sig);
      if (els.deleteBtn) els.deleteBtn.addEventListener("click", doDelete, sig);
      if (els.addTagBtn) els.addTagBtn.addEventListener("click", addNewTag, sig);
      v.on("teardown", () => ac.abort());
    },
  };
}
```

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_clip_extractor_feature.py -q`
Expected: PASS — all cases green.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/features/clip_extractor.js dlc-3D/tests/test_clip_extractor_feature.py
git commit -m "feat(dlc-3d viewer-lib): ClipExtractor feature module + contract test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Phase-3c wrap-up — suites green, no consumer touched

**Files:** none (verification only)

- [ ] **Step 1: Full viewer unit suite (now incl. clip_extract)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs \
  tests/unit/test_viewer_frame_pacer.mjs tests/unit/test_viewer_clip_naming.mjs \
  tests/unit/test_viewer_tile_layout.mjs tests/unit/test_viewer_seek_plan.mjs \
  tests/unit/test_viewer_fit_viewer.mjs tests/unit/test_viewer_controls.mjs \
  tests/unit/test_viewer_event_bus.mjs tests/unit/test_viewer_csv_annotations.mjs \
  tests/unit/test_viewer_frame_extract.mjs tests/unit/test_viewer_clip_extract.mjs \
  tests/unit/test_pair_map.mjs
```
Expected: `# fail 0`.

- [ ] **Step 2: All contract tests**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_base.py tests/test_status_notes_feature.py tests/test_frame_extractor_feature.py tests/test_clip_extractor_feature.py -q`
Expected: all green.

- [ ] **Step 3: Confirm no consumer/origin file modified**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~2 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js dlc-3D/src/static/dlc_3d.js clip-cutter/`
Expected: empty output.

---

## Phase-3c exit criteria

- `internal/clip_extract.mjs` added with passing node tests; full viewer unit suite green.
- `features/clip_extractor.js` exports `clipExtractor`, imports the reducers + `computeEnd` (no re-implementation), namespaces its localStorage key by `storagePrefix`, disposes on `teardown`, and hardcodes no endpoint paths.
- `tests/test_clip_extractor_feature.py` passes.
- No consumer/origin file modified.

**Next:** `MarkerEditor` — the large overlay + multi-layer pose + marker-editing feature (the bulk of the viewer_3d / inline_analysis_3d duplication). Then `CurationModule`. Phase 4 migrates the three forks onto the library (smallest-first, guarded by existing E2E); Phase 5 adds the policy doc + enforcement test.
