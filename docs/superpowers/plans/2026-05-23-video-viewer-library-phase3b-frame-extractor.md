# Video-Viewer Library — Phase 3b (FrameExtractor feature) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `FrameExtractor` feature module — save the current frame (and batches of frames) into DLC `labeled-data/` via an injected save-frame endpoint, with sibling-cam support. This is what the dlc-3D 3D-Extract card actually does; it gets migrated onto this in Phase 4.

**Architecture:** Same split as the other features: a pure reducer `internal/frame_extract.mjs` (batch planning + payload building — node-tested) and the DOM feature module `features/frame_extractor.js` (`frameExtractor(config)` → `{ attach(viewer) }`) verified by a pytest static-analysis contract + code review. Reads frame count / current frame / sibling from the `VideoViewer` (no re-fetch of video-info). Follows the feature-teardown pattern established in Phase 3a (capture disposers + `AbortController`, dispose on `"teardown"`).

**Context — two distinct extract features:** *FrameExtractor* (this phase) adds frames to `labeled-data/` for DLC training; *ClipExtractor* (Phase 3c) trims the master clip (the clip-cutter gold standard) and is gated behind a separate checkbox that is unchecked by default. They are independent composable features.

**Tech Stack:** Vanilla ES modules; `node:test` for the reducer; pytest regex contract for the feature.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.4 ExtractModule).

**Source of truth (the real consumer):** `dlc-3D/src/static/dlc_3d.js` `_extractFrame` (333-379) and `_extractBatch` (249-331). Save endpoint `/dlc-3d/save-frame`, payload `{ primary_video, primary_frame_number, extract_sibling, sibling_video?, sibling_frame_number? }`, response `{ saved:[], skipped:[], calibration_copied:bool, error? }`. Batch: `requested = max(2, parseInt||10)`, `step = max(1, parseInt||1)`, `maxCount = floor((frameCount-1-startFrame)/step)+1`, `count = min(requested, maxCount)`, `targetFrame = startFrame + i*step`, advances the player to `targetFrame+step` between saves, stop button aborts.

**Commands:**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_frame_extract.mjs           # Task 1
python -m pytest tests/test_frame_extractor_feature.py -q       # Task 2 (static; launches no app)
```

---

## Task 1: `frame_extract.mjs` — pure batch planning + payload

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/frame_extract.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_frame_extract.mjs`

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_frame_extract.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  parseBatchCount, parseBatchStep, planBatch, buildSaveFramePayload,
} from "../../src/static/components/viewer/internal/frame_extract.mjs";

test("parseBatchCount: >=2, default 10 on NaN", () => {
  assert.equal(parseBatchCount("5"), 5);
  assert.equal(parseBatchCount("1"), 2);   // floor of 2
  assert.equal(parseBatchCount("abc"), 10);
  assert.equal(parseBatchCount(""), 10);
});

test("parseBatchStep: >=1, default 1 on NaN", () => {
  assert.equal(parseBatchStep("3"), 3);
  assert.equal(parseBatchStep("0"), 1);
  assert.equal(parseBatchStep("xyz"), 1);
});

test("planBatch: full count when room, frames = start + i*step", () => {
  assert.deepEqual(planBatch({ startFrame: 0, step: 1, requested: 5, frameCount: 100 }),
    { count: 5, frames: [0, 1, 2, 3, 4], clamped: false });
});

test("planBatch: clamps count to what fits at the given step", () => {
  // maxCount = floor((99-95)/2)+1 = 3
  assert.deepEqual(planBatch({ startFrame: 95, step: 2, requested: 10, frameCount: 100 }),
    { count: 3, frames: [95, 97, 99], clamped: true });
});

test("planBatch: last frame only when at the end", () => {
  assert.deepEqual(planBatch({ startFrame: 99, step: 1, requested: 5, frameCount: 100 }),
    { count: 1, frames: [99], clamped: true });
});

test("buildSaveFramePayload: omits sibling fields unless extracting a sibling", () => {
  assert.deepEqual(
    buildSaveFramePayload({ primaryVideo: "a.avi", frameNumber: 7, extractSibling: false, siblingVideo: "b.avi" }),
    { primary_video: "a.avi", primary_frame_number: 7, extract_sibling: false });
  assert.deepEqual(
    buildSaveFramePayload({ primaryVideo: "a.avi", frameNumber: 7, extractSibling: true, siblingVideo: "b.avi" }),
    { primary_video: "a.avi", primary_frame_number: 7, extract_sibling: true,
      sibling_video: "b.avi", sibling_frame_number: 7 });
  // extractSibling true but no sibling path → no sibling fields
  assert.deepEqual(
    buildSaveFramePayload({ primaryVideo: "a.avi", frameNumber: 7, extractSibling: true, siblingVideo: null }),
    { primary_video: "a.avi", primary_frame_number: 7, extract_sibling: true });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_frame_extract.mjs`
Expected: FAIL — cannot find module `frame_extract.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/frame_extract.mjs`:

```js
// Pure frame-extraction logic for the FrameExtractor feature: batch planning and the
// save-frame request payload. Ported from dlc_3d.js _extractBatch / _extractFrame.

export function parseBatchCount(v, def = 10) {
  const n = parseInt(v, 10);
  return Math.max(2, isNaN(n) ? def : n);
}

export function parseBatchStep(v, def = 1) {
  const n = parseInt(v, 10);
  return Math.max(1, isNaN(n) ? def : n);
}

// Clamp `requested` so frames stay within [startFrame, frameCount-1] at the given step,
// and list the target frames. Returns { count, frames, clamped }.
export function planBatch({ startFrame, step, requested, frameCount }) {
  const maxCount = Math.floor((frameCount - 1 - startFrame) / step) + 1;
  const count = Math.min(requested, maxCount);
  const frames = [];
  for (let i = 0; i < count; i++) frames.push(startFrame + i * step);
  return { count, frames, clamped: count < requested };
}

export function buildSaveFramePayload({ primaryVideo, frameNumber, extractSibling, siblingVideo }) {
  const body = {
    primary_video: primaryVideo,
    primary_frame_number: frameNumber,
    extract_sibling: extractSibling,
  };
  if (extractSibling && siblingVideo) {
    body.sibling_video = siblingVideo;
    body.sibling_frame_number = frameNumber;
  }
  return body;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_frame_extract.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/frame_extract.mjs dlc-3D/tests/unit/test_viewer_frame_extract.mjs
git commit -m "feat(dlc-3d viewer-lib): frame_extract.mjs (batch planning + save payload) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `features/frame_extractor.js` — the FrameExtractor feature module

**Files:**
- Create: `dlc-3D/src/static/components/viewer/features/frame_extractor.js`
- Test: `dlc-3D/tests/test_frame_extractor_feature.py`

- [ ] **Step 1: Write the failing contract test**

Create `dlc-3D/tests/test_frame_extractor_feature.py`:

```python
"""Static-analysis contract for the FrameExtractor feature module (Phase 3b).

Browser ESM cannot import under Node; like the other viewer .js modules it is enforced
by regex over source + code review. The pure batch/payload logic is node-tested
separately (test_viewer_frame_extract.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FE = ROOT / "src" / "static" / "components" / "viewer" / "features" / "frame_extractor.js"


def _src():
    assert FE.is_file(), f"missing frame_extractor feature at {FE}"
    return FE.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+frameExtractor\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bframeExtractor\b[^}]*\}", _src()), \
        "must export `frameExtractor`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name", ["parseBatchCount", "parseBatchStep", "planBatch", "buildSaveFramePayload"])
def test_imports_reducer(name):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*frame_extract\.mjs[\"']", _src()), \
        f"must import {name} from internal/frame_extract.mjs (no re-implementation)"


def test_reads_viewer_state():
    src = _src()
    for accessor in ("currentFrame", "videoPath", "frameCount"):
        assert re.search(rf"\.{accessor}\s*\(", src), f"must read viewer.{accessor}()"


def test_disposes_on_teardown():
    src = _src()
    assert '"teardown"' in src or "'teardown'" in src, "must subscribe to the viewer 'teardown' hook"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_frame_extractor_feature.py -q`
Expected: FAIL — `missing frame_extractor feature at ...`.

- [ ] **Step 3: Write the feature module**

Create `dlc-3D/src/static/components/viewer/features/frame_extractor.js`:

```js
// FrameExtractor — feature module for VideoViewer.
// Saves the current frame (and batches of frames) into DLC labeled-data via an injected
// save-frame endpoint, with optional sibling-cam extraction. Reads frame count / current
// frame / sibling video from the viewer (no video-info re-fetch). All endpoints/elements
// injected; follows the feature-teardown pattern.
//
// Usage:
//   viewer.use(frameExtractor({
//     endpoints: { saveFrame: (payload) => fetchPromise },
//     els: { extractBtn?, batchBtn?, batchStopBtn?, batchCount?, batchStep?,
//            extractSibling?, statusDisplay? },
//     onSaved?: () => void,   // called after a save/batch completes (e.g. refresh labeled list)
//   }));

import {
  parseBatchCount, parseBatchStep, planBatch, buildSaveFramePayload,
} from "../internal/frame_extract.mjs";

export function frameExtractor(config = {}) {
  const els = config.els || {};
  const endpoints = config.endpoints || {};

  let viewer = null;
  let stopRequested = false;
  let running = false;

  const setStatus = (msg) => { if (els.statusDisplay) els.statusDisplay.textContent = msg; };
  const siblingPath = () => {
    const t = viewer && viewer.getTile(1);
    return t ? t.videoRel : null;
  };
  const wantSibling = () => Boolean(siblingPath()) && (els.extractSibling ? els.extractSibling.checked : true);

  function setBatchRunning(on) {
    if (els.extractBtn) els.extractBtn.disabled = on;
    if (els.batchBtn) els.batchBtn.disabled = on;
    if (els.batchStopBtn) els.batchStopBtn.classList.toggle("hidden", !on);
  }

  async function saveFrame() {
    if (!viewer || running || !endpoints.saveFrame) return;
    const primaryVideo = viewer.videoPath();
    const frame = viewer.currentFrame();
    if (!primaryVideo || frame == null) return;
    if (els.extractBtn) els.extractBtn.disabled = true;
    setStatus("Saving…");
    try {
      const payload = buildSaveFramePayload({
        primaryVideo, frameNumber: frame, extractSibling: wantSibling(), siblingVideo: siblingPath(),
      });
      const data = await (await endpoints.saveFrame(payload)).json();
      if (data.error) { setStatus(data.error); return; }
      const calib = data.calibration_copied ? " — calibration.toml copied" : "";
      if (data.saved && data.saved.length) setStatus(`Saved: ${data.saved.join(", ")}${calib}`);
      else if (data.skipped && data.skipped.length) setStatus(`Frame ${frame} already extracted — skipped.${calib}`);
      if (config.onSaved) config.onSaved();
    } catch (e) {
      setStatus("Network error: " + e.message);
    } finally {
      if (els.extractBtn) els.extractBtn.disabled = false;
    }
  }

  async function saveBatch() {
    if (!viewer || running || !endpoints.saveFrame) return;
    const primaryVideo = viewer.videoPath();
    if (!primaryVideo) return;
    const startFrame = viewer.currentFrame();
    const requested = parseBatchCount(els.batchCount ? els.batchCount.value : undefined);
    const step = parseBatchStep(els.batchStep ? els.batchStep.value : undefined);
    const { count, frames, clamped } = planBatch({ startFrame, step, requested, frameCount: viewer.frameCount() });
    if (!frames.length) { setStatus("No frames available from this position."); return; }

    const extractSibling = wantSibling();
    const sib = siblingPath();
    stopRequested = false;
    running = true;
    setBatchRunning(true);

    let saved = 0, skipped = 0, aborted = false, errored = false, calibCopied = false;
    for (let i = 0; i < frames.length; i++) {
      if (stopRequested) { aborted = true; break; }
      const targetFrame = frames[i];
      setStatus(`Saving… ${i + 1}/${count}`);
      try {
        const payload = buildSaveFramePayload({
          primaryVideo, frameNumber: targetFrame, extractSibling, siblingVideo: sib,
        });
        const data = await (await endpoints.saveFrame(payload)).json();
        if (data.error) { setStatus(`Server error at frame ${targetFrame}: ${data.error}`); errored = true; break; }
        saved += (data.saved || []).length;
        skipped += (data.skipped || []).length;
        if (data.calibration_copied) calibCopied = true;
      } catch (e) {
        setStatus(`Network error at frame ${targetFrame}: ${e.message}`);
        errored = true;
        break;
      }
      if (i < frames.length - 1) await viewer.seek(targetFrame + step);
    }

    running = false;
    setBatchRunning(false);
    if (!errored) {
      const sibTag = (extractSibling && sib) ? " (×2 sibling)" : "";
      const clampTag = clamped ? ` (clamped from ${requested})` : "";
      const calibTag = calibCopied ? " — calibration.toml copied" : "";
      setStatus(aborted
        ? `Stopped — saved ${saved}${sibTag}, skipped ${skipped}${clampTag}${calibTag}`
        : `Done — saved ${saved}${sibTag}, skipped ${skipped}${clampTag}${calibTag}`);
    }
    if (config.onSaved) config.onSaved();
  }

  return {
    attach(v) {
      viewer = v;
      const ac = new AbortController();
      const sig = { signal: ac.signal };
      if (els.extractBtn) els.extractBtn.addEventListener("click", saveFrame, sig);
      if (els.batchBtn) els.batchBtn.addEventListener("click", saveBatch, sig);
      if (els.batchStopBtn) els.batchStopBtn.addEventListener("click", () => { stopRequested = true; }, sig);
      v.on("teardown", () => ac.abort());
    },
  };
}
```

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_frame_extractor_feature.py -q`
Expected: PASS — all cases green.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/features/frame_extractor.js dlc-3D/tests/test_frame_extractor_feature.py
git commit -m "feat(dlc-3d viewer-lib): FrameExtractor feature module + contract test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Phase-3b wrap-up — suites green, no consumer touched

**Files:** none (verification only)

- [ ] **Step 1: Full viewer unit suite (now incl. frame_extract)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs \
  tests/unit/test_viewer_frame_pacer.mjs tests/unit/test_viewer_clip_naming.mjs \
  tests/unit/test_viewer_tile_layout.mjs tests/unit/test_viewer_seek_plan.mjs \
  tests/unit/test_viewer_fit_viewer.mjs tests/unit/test_viewer_controls.mjs \
  tests/unit/test_viewer_event_bus.mjs tests/unit/test_viewer_csv_annotations.mjs \
  tests/unit/test_viewer_frame_extract.mjs tests/unit/test_pair_map.mjs
```
Expected: `# fail 0`.

- [ ] **Step 2: All contract tests (base + status_notes + frame_extractor)**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_base.py tests/test_status_notes_feature.py tests/test_frame_extractor_feature.py -q`
Expected: all green.

- [ ] **Step 3: Confirm no consumer/origin file modified**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~2 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js dlc-3D/src/static/dlc_3d.js clip-cutter/`
Expected: empty output.

---

## Phase-3b exit criteria

- `internal/frame_extract.mjs` added with passing node tests; full viewer unit suite green.
- `features/frame_extractor.js` exports `frameExtractor`, imports the reducer (no re-implementation), reads viewer state (`currentFrame`/`videoPath`/`frameCount`), disposes on `teardown`, and hardcodes no endpoint paths.
- `tests/test_frame_extractor_feature.py` passes.
- No consumer/origin file modified.

**Next:** Phase 3c — `ClipExtractor` (the clip-cutter gold standard: clip start/length/end via `clip_naming.mjs`, queue+SSE status, rename, delete, postfix quick-tags, keyframe-overlap), gated behind a "clip extract" checkbox that is unchecked by default. Then `MarkerEditor`, `CurationModule`. Phase 4 migrates the consumers; Phase 5 adds the policy doc + enforcement test.
