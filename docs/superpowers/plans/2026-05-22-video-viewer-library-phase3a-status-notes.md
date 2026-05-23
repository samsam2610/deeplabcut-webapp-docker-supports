# Video-Viewer Library — Phase 3a (StatusNoteTimeline feature) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `StatusNoteTimeline` feature module — CSV-backed per-frame status + note browsing (timeline bars, toggle chips, prev/next-by-chip navigation, per-frame badges/inputs, optional save-back) — that attaches to a `VideoViewer` and subscribes to its hook bus.

**Architecture:** Same split as the base class: a cohesive pure reducer module `internal/csv_annotations.mjs` (value extraction, palette assignment, the next/prev frame search, badge lookup, save-back row-list logic — all node-tested), and the DOM feature module `features/status_notes.js` (`statusNoteTimeline(config)` returning `{ attach(viewer) }`) verified by a pytest static-analysis contract + code review. All endpoints/elements are injected via config — no hardcoded paths or DOM ids. Scoped to what the migrated consumers use; clip-cutter's sub-rows are intentionally out of scope (that consumer is frozen).

**Tech Stack:** Vanilla ES modules; `node:test` for the reducer; pytest regex contract for the feature.

**Spec:** `docs/superpowers/specs/2026-05-22-video-viewer-library-design.md` (§3.4 StatusNoteTimeline).

**Source of truth (current forks):** `clip-cutter/static/enhanced_player.js` (`_epBuildTagBars` ~643-689, `_epDrawTagCanvas` ~370-400, `_epRenderStatusChips` ~481-528, `_epNavByChip` ~703-721, `_epUpdateCsvStrip` ~334-347); `dlc-3D/src/static/viewer_3d.js` (`_vaCsvApplyRows` ~2947-2964, `_vaDrawCanvas` ~2870-2888, `_vaNavAnnot` ~2916-2930, `_vaCsvDoSave` ~3035-3073). Status palette `["#34d399","#f97316","#e879f9","#facc15","#f87171","#22d3ee","#a78bfa","#fb923c"]`; note palette `["#60a5fa","#f472b6","#4ade80","#38bdf8","#e879f9","#a78bfa","#facc15","#fb7185"]`. Status value `"0"` and empty values are never shown.

**Frame convention:** the reducer works purely in CSV `frame_number` space; the feature maps viewer seek-frames ↔ row frame_numbers via a `frameBase` (row.frame_number = seekFrame + frameBase; default 0).

**Commands:**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_csv_annotations.mjs        # Task 1
python -m pytest tests/test_status_notes_feature.py -q         # Task 2 (static; launches no app)
```

---

## Task 1: `csv_annotations.mjs` — pure CSV status/note logic

**Files:**
- Create: `dlc-3D/src/static/components/viewer/internal/csv_annotations.mjs`
- Test: `dlc-3D/tests/unit/test_viewer_csv_annotations.mjs`

- [ ] **Step 1: Write the failing test**

Create `dlc-3D/tests/unit/test_viewer_csv_annotations.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import {
  uniqueValues, assignColors, findMatchingFrame, rowForFrame,
  isInterestingAnnotation, applySavedRow, buildSaveRowPayload,
} from "../../src/static/components/viewer/internal/csv_annotations.mjs";

const ROWS = [
  { frame_number: 1, frame_line_status: "0", note: "" },
  { frame_number: 3, frame_line_status: "reach", note: "good" },
  { frame_number: 5, frame_line_status: "reach", note: "" },
  { frame_number: 8, frame_line_status: "grasp", note: "good" },
];

test("uniqueValues: status drops '0'/empty, keeps first-seen order, dedups", () => {
  assert.deepEqual(uniqueValues(ROWS, "frame_line_status"), ["reach", "grasp"]);
  assert.deepEqual(uniqueValues(ROWS, "note"), ["good"]);
});

test("assignColors cycles the palette by index", () => {
  assert.deepEqual(assignColors(["a", "b", "c"], ["#1", "#2"]),
    { a: "#1", b: "#2", c: "#1" });
});

test("findMatchingFrame: next/prev in frame_number space, accepts Set or array", () => {
  // next 'reach' after frame 3 is 5; after 5 is null
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", ["reach"], 3, 1), 5);
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", ["reach"], 5, 1), null);
  // prev 'reach' before frame 5 is 3
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", new Set(["reach"]), 5, -1), 3);
  // multi-value set spans both values
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", new Set(["reach", "grasp"]), 5, 1), 8);
});

test("findMatchingFrame: empty active set or no match → null", () => {
  assert.equal(findMatchingFrame(ROWS, "note", [], 0, 1), null);
  assert.equal(findMatchingFrame(ROWS, "note", ["missing"], 0, 1), null);
});

test("rowForFrame returns the row or null", () => {
  assert.equal(rowForFrame(ROWS, 3).note, "good");
  assert.equal(rowForFrame(ROWS, 999), null);
});

test("isInterestingAnnotation: note OR non-'0' status", () => {
  assert.equal(isInterestingAnnotation("hi", "0"), true);
  assert.equal(isInterestingAnnotation("", "reach"), true);
  assert.equal(isInterestingAnnotation("", "0"), false);
  assert.equal(isInterestingAnnotation("", ""), false);
});

test("applySavedRow updates existing, inserts+sorts new, deletes when not interesting", () => {
  // update existing frame 3
  const upd = applySavedRow(ROWS, { frame_number: 3, frame_line_status: "reach", note: "edited" }, true);
  assert.equal(rowForFrame(upd, 3).note, "edited");
  assert.equal(upd.length, ROWS.length);
  // insert new frame 4, kept sorted
  const ins = applySavedRow(ROWS, { frame_number: 4, frame_line_status: "x", note: "" }, true);
  assert.deepEqual(ins.map((r) => r.frame_number), [1, 3, 4, 5, 8]);
  // delete frame 3 when not interesting
  const del = applySavedRow(ROWS, { frame_number: 3 }, false);
  assert.equal(rowForFrame(del, 3), null);
  assert.equal(del.length, ROWS.length - 1);
  // not interesting + not present → unchanged length
  assert.equal(applySavedRow(ROWS, { frame_number: 99 }, false).length, ROWS.length);
});

test("applySavedRow does not mutate the input array", () => {
  const before = ROWS.length;
  applySavedRow(ROWS, { frame_number: 4, note: "z" }, true);
  assert.equal(ROWS.length, before);
});

test("buildSaveRowPayload shapes the request body", () => {
  assert.deepEqual(
    buildSaveRowPayload({ csvPath: "/x.csv", frameNumber: 7, note: "n", status: "s", fps: 30 }),
    { csv_path: "/x.csv", frame_number: 7, note: "n", frame_line_status: "s", fps: 30 },
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_csv_annotations.mjs`
Expected: FAIL — cannot find module `csv_annotations.mjs`.

- [ ] **Step 3: Write minimal implementation**

Create `dlc-3D/src/static/components/viewer/internal/csv_annotations.mjs`:

```js
// Pure CSV status/note logic shared by the StatusNoteTimeline feature.
// Operates purely in CSV frame_number space; no DOM, no fetch.
// Status value "0" and empty values are treated as "no annotation".

export function uniqueValues(rows, field) {
  const out = [];
  const seen = new Set();
  for (const r of rows) {
    const v = r[field];
    if (!v) continue;
    if (field === "frame_line_status" && v === "0") continue;
    if (!seen.has(v)) { seen.add(v); out.push(v); }
  }
  return out;
}

export function assignColors(values, palette) {
  const map = {};
  values.forEach((v, i) => { map[v] = palette[i % palette.length]; });
  return map;
}

// Nearest frame_number strictly in `dir` from `fromFrame` whose `field` value is in
// `active` (a Set or array; status "0"/empty excluded). Returns the frame_number or null.
export function findMatchingFrame(rows, field, active, fromFrame, dir) {
  const set = active instanceof Set ? active : new Set(active);
  if (!set.size) return null;
  const frames = rows
    .filter((r) => {
      const v = r[field];
      return v && !(field === "frame_line_status" && v === "0") && set.has(v);
    })
    .map((r) => Number(r.frame_number))
    .sort((a, b) => a - b);
  if (dir < 0) {
    let prev = null;
    for (const f of frames) { if (f < fromFrame) prev = f; else break; }
    return prev;
  }
  for (const f of frames) { if (f > fromFrame) return f; }
  return null;
}

export function rowForFrame(rows, frameNumber) {
  return rows.find((r) => Number(r.frame_number) === frameNumber) || null;
}

export function isInterestingAnnotation(note, status) {
  return Boolean(note) || Boolean(status && status !== "0");
}

// Return a NEW rows array with savedRow updated/inserted (sorted) when interesting,
// or the row at that frame removed when not. Never mutates the input.
export function applySavedRow(rows, savedRow, isInteresting) {
  const fn = Number(savedRow.frame_number);
  const idx = rows.findIndex((r) => Number(r.frame_number) === fn);
  const next = rows.slice();
  if (isInteresting) {
    if (idx >= 0) next[idx] = savedRow;
    else { next.push(savedRow); next.sort((a, b) => Number(a.frame_number) - Number(b.frame_number)); }
  } else if (idx >= 0) {
    next.splice(idx, 1);
  }
  return next;
}

export function buildSaveRowPayload({ csvPath, frameNumber, note, status, fps }) {
  return { csv_path: csvPath, frame_number: frameNumber, note, frame_line_status: status, fps };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && node --test tests/unit/test_viewer_csv_annotations.mjs`
Expected: PASS — `# fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/internal/csv_annotations.mjs dlc-3D/tests/unit/test_viewer_csv_annotations.mjs
git commit -m "feat(dlc-3d viewer-lib): csv_annotations.mjs (status/note pure logic) + tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `features/status_notes.js` — the StatusNoteTimeline feature module

**Files:**
- Create: `dlc-3D/src/static/components/viewer/features/status_notes.js`
- Test: `dlc-3D/tests/test_status_notes_feature.py`

TDD via a pytest static-analysis contract (browser ESM, can't run under Node): write the
contract first (fails — file missing), then write the feature to satisfy it.

- [ ] **Step 1: Write the failing contract test**

Create `dlc-3D/tests/test_status_notes_feature.py`:

```python
"""Static-analysis contract for the StatusNoteTimeline feature module (Phase 3a).

Browser ESM cannot import under Node; like file_browser.js / video_viewer.js it is
enforced by regex over source + code review. The pure CSV logic it builds on is
node-tested separately (test_viewer_csv_annotations.mjs).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SN = ROOT / "src" / "static" / "components" / "viewer" / "features" / "status_notes.js"


def _src():
    assert SN.is_file(), f"missing status_notes feature at {SN}"
    return SN.read_text()


def test_exports_factory():
    assert re.search(r"export\s+function\s+statusNoteTimeline\b", _src()) or \
        re.search(r"export\s*\{[^}]*\bstatusNoteTimeline\b[^}]*\}", _src()), \
        "must export `statusNoteTimeline`"


def test_returns_attach():
    assert re.search(r"\battach\s*\(", _src()), "factory result must expose `attach(viewer)`"


@pytest.mark.parametrize("name", [
    "uniqueValues", "assignColors", "findMatchingFrame", "rowForFrame",
])
def test_imports_reducer(name):
    assert re.search(
        rf"import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*[\"'][^\"']*csv_annotations\.mjs[\"']", _src()), \
        f"must import {name} from internal/csv_annotations.mjs (no re-implementation)"


@pytest.mark.parametrize("event", ["videoLoad", "frameChange"])
def test_subscribes_hook(event):
    src = _src()
    assert f'"{event}"' in src or f"'{event}'" in src, f'must subscribe to the "{event}" hook'


def test_navigates_via_viewer_seek():
    assert re.search(r"\.seek\s*\(", _src()), "prev/next nav must call viewer.seek(...)"


def test_no_hardcoded_endpoints():
    src = _src()
    for bad in ("/dlc-3d/", "/clip-cutter/", "/annotate/"):
        assert bad not in src, f"endpoints must be injected, not hardcoded ({bad})"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_status_notes_feature.py -q`
Expected: FAIL — `missing status_notes feature at ...`.

- [ ] **Step 3: Write the feature module**

Create `dlc-3D/src/static/components/viewer/features/status_notes.js`:

```js
// StatusNoteTimeline — feature module for VideoViewer.
// CSV-backed per-frame status + note browsing: timeline bars, toggle chips,
// prev/next-by-chip navigation, per-frame badges/inputs, and optional save-back.
// All endpoints/elements injected via config; subscribes to the viewer hook bus.
//
// Usage:
//   viewer.use(statusNoteTimeline({
//     endpoints: { csv: (videoPath) => url, saveRow: (payload) => fetchPromise },
//     els: { statusCanvas, noteCanvas, statusChips, noteChips,
//            statusBadge?, noteBadge?, statusInput?, noteInput?,
//            statusPrev?, statusNext?, notePrev?, noteNext?,
//            saveStatusBtn?, saveNoteBtn?, saveFeedback? },
//     palette?: { status: [...], note: [...] }, frameBase?: 0, fps?: 30,
//   }));
//
// The reducer works in CSV frame_number space; frameBase maps it to viewer seek-frames
// (row.frame_number = seekFrame + frameBase).

import {
  uniqueValues, assignColors, findMatchingFrame, rowForFrame,
  isInterestingAnnotation, applySavedRow, buildSaveRowPayload,
} from "../internal/csv_annotations.mjs";

const DEFAULT_STATUS_PALETTE = ["#34d399", "#f97316", "#e879f9", "#facc15", "#f87171", "#22d3ee", "#a78bfa", "#fb923c"];
const DEFAULT_NOTE_PALETTE = ["#60a5fa", "#f472b6", "#4ade80", "#38bdf8", "#e879f9", "#a78bfa", "#facc15", "#fb7185"];

export function statusNoteTimeline(config = {}) {
  const els = config.els || {};
  const endpoints = config.endpoints || {};
  const statusPalette = (config.palette && config.palette.status) || DEFAULT_STATUS_PALETTE;
  const notePalette = (config.palette && config.palette.note) || DEFAULT_NOTE_PALETTE;
  const frameBase = config.frameBase || 0;

  let viewer = null;
  let rows = [];
  let csvPath = null;
  let statusColors = {};
  let noteColors = {};
  const activeStatus = new Set();
  const activeNote = new Set();

  const seekToRow = (f) => f + frameBase;
  const rowToSeek = (fn) => fn - frameBase;
  const total = () => Math.max(viewer ? viewer.frameCount() : 1, 1);
  const curFrame = () => (viewer ? viewer.currentFrame() : 0);

  async function loadCsv(videoPath) {
    rows = [];
    csvPath = null;
    activeStatus.clear();
    activeNote.clear();
    if (endpoints.csv && videoPath) {
      try {
        const data = await (await fetch(endpoints.csv(videoPath))).json();
        rows = data.rows || [];
        csvPath = data.csv_path || null;
      } catch (_) { rows = []; }
    }
    recolor();
    rebuildChips();
    redraw(curFrame());
    updateBadges(curFrame());
  }

  function recolor() {
    statusColors = assignColors(uniqueValues(rows, "frame_line_status"), statusPalette);
    noteColors = assignColors(uniqueValues(rows, "note"), notePalette);
  }

  function rebuildChips() {
    renderChips(els.statusChips, statusColors, activeStatus);
    renderChips(els.noteChips, noteColors, activeNote);
    updateNavDisabled();
  }

  function renderChips(container, colorMap, activeSet) {
    if (!container) return;
    container.innerHTML = "";
    for (const val of Object.keys(colorMap)) {
      const chip = container.ownerDocument.createElement("span");
      chip.className = "vv-tag-chip" + (activeSet.has(val) ? " active" : "");
      chip.textContent = val;
      chip.style.setProperty("--chip-color", colorMap[val]);
      chip.addEventListener("click", () => {
        if (activeSet.has(val)) activeSet.delete(val);
        else activeSet.add(val);
        rebuildChips();
        redraw(curFrame());
      });
      container.appendChild(chip);
    }
  }

  function drawBar(canvas, field, activeSet, colorMap) {
    if (!canvas) return;
    const W = Math.round(canvas.getBoundingClientRect().width) || canvas.clientWidth || 600;
    canvas.width = W;
    const H = canvas.height || 12;
    const ctx = canvas.getContext("2d");
    const minW = Math.max(1, Math.round(W / total()));
    ctx.clearRect(0, 0, W, H);
    if (!activeSet.size) return;
    for (const row of rows) {
      const val = row[field];
      if (!val || (field === "frame_line_status" && val === "0")) continue;
      if (!activeSet.has(val)) continue;
      ctx.fillStyle = colorMap[val] || "#888";
      const x = Math.round((rowToSeek(Number(row.frame_number)) / Math.max(total() - 1, 1)) * W);
      ctx.fillRect(x, 0, minW, H);
    }
  }

  function drawCursor(canvas, frame) {
    if (!canvas || !canvas.width) return;
    const ctx = canvas.getContext("2d");
    const x = Math.round((frame / Math.max(total() - 1, 1)) * canvas.width);
    ctx.save();
    ctx.globalAlpha = 0.8;
    ctx.fillStyle = "#fff";
    ctx.fillRect(x, 0, 1, canvas.height);
    ctx.restore();
  }

  function redraw(frame) {
    drawBar(els.statusCanvas, "frame_line_status", activeStatus, statusColors);
    drawCursor(els.statusCanvas, frame);
    drawBar(els.noteCanvas, "note", activeNote, noteColors);
    drawCursor(els.noteCanvas, frame);
  }

  function updateBadges(frame) {
    const row = rowForFrame(rows, seekToRow(frame));
    if (els.statusBadge) els.statusBadge.textContent = (row && row.frame_line_status) || "—";
    if (els.noteBadge) els.noteBadge.textContent = (row && row.note) || "—";
    if (els.statusInput) els.statusInput.value = row ? (row.frame_line_status ?? "0") : "0";
    if (els.noteInput) els.noteInput.value = row ? (row.note || "") : "";
  }

  function updateNavDisabled() {
    const sOn = activeStatus.size > 0;
    const nOn = activeNote.size > 0;
    if (els.statusPrev) els.statusPrev.disabled = !sOn;
    if (els.statusNext) els.statusNext.disabled = !sOn;
    if (els.notePrev) els.notePrev.disabled = !nOn;
    if (els.noteNext) els.noteNext.disabled = !nOn;
  }

  function nav(field, activeSet, dir) {
    if (!viewer) return;
    const fn = findMatchingFrame(rows, field, activeSet, seekToRow(curFrame()), dir);
    if (fn != null) { viewer.pause(); viewer.seek(rowToSeek(fn)); }
  }

  async function save(kind) {
    if (!viewer || !csvPath || !endpoints.saveRow) return;
    const frame = curFrame();
    const existing = rowForFrame(rows, seekToRow(frame));
    const note = els.noteInput ? els.noteInput.value.trim()
      : (kind === "status" && existing ? (existing.note || "") : "");
    const status = els.statusInput ? (els.statusInput.value || "0")
      : (kind === "note" && existing ? (existing.frame_line_status || "0") : "0");
    const payload = buildSaveRowPayload({
      csvPath, frameNumber: seekToRow(frame), note, status, fps: config.fps || 30,
    });
    if (els.saveFeedback) els.saveFeedback.textContent = "Saving…";
    try {
      const data = await (await endpoints.saveRow(payload)).json();
      if (data.error) throw new Error(data.error);
      const savedRow = data.row || { frame_number: seekToRow(frame), frame_line_status: status, note };
      rows = applySavedRow(rows, savedRow, isInterestingAnnotation(note, status));
      recolor();
      rebuildChips();
      redraw(frame);
      if (els.saveFeedback) {
        els.saveFeedback.textContent = "Saved";
        setTimeout(() => {
          if (els.saveFeedback.textContent === "Saved") els.saveFeedback.textContent = "";
        }, 2000);
      }
    } catch (err) {
      if (els.saveFeedback) els.saveFeedback.textContent = `Error: ${err.message}`;
    }
  }

  return {
    attach(v) {
      viewer = v;
      v.on("videoLoad", (e) => loadCsv(e && e.videoPath));
      v.on("frameChange", (frame) => { updateBadges(frame); redraw(frame); });
      if (els.statusPrev) els.statusPrev.addEventListener("click", () => nav("frame_line_status", activeStatus, -1));
      if (els.statusNext) els.statusNext.addEventListener("click", () => nav("frame_line_status", activeStatus, 1));
      if (els.notePrev) els.notePrev.addEventListener("click", () => nav("note", activeNote, -1));
      if (els.noteNext) els.noteNext.addEventListener("click", () => nav("note", activeNote, 1));
      if (els.saveStatusBtn) els.saveStatusBtn.addEventListener("click", () => save("status"));
      if (els.saveNoteBtn) els.saveNoteBtn.addEventListener("click", () => save("note"));
    },
  };
}
```

- [ ] **Step 4: Run the contract test to verify it passes**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_status_notes_feature.py -q`
Expected: PASS — all cases green.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/components/viewer/features/status_notes.js dlc-3D/tests/test_status_notes_feature.py
git commit -m "feat(dlc-3d viewer-lib): StatusNoteTimeline feature module + contract test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Phase-3a wrap-up — suites green, no consumer touched

**Files:** none (verification only)

- [ ] **Step 1: Full viewer unit suite (now incl. csv_annotations)**

Run:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
node --test tests/unit/test_viewer_palette.mjs tests/unit/test_viewer_shapes.mjs \
  tests/unit/test_viewer_frame_pacer.mjs tests/unit/test_viewer_clip_naming.mjs \
  tests/unit/test_viewer_tile_layout.mjs tests/unit/test_viewer_seek_plan.mjs \
  tests/unit/test_viewer_fit_viewer.mjs tests/unit/test_viewer_controls.mjs \
  tests/unit/test_viewer_event_bus.mjs tests/unit/test_viewer_csv_annotations.mjs \
  tests/unit/test_pair_map.mjs
```
Expected: `# fail 0`.

- [ ] **Step 2: Contract tests (base class + this feature)**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D && python -m pytest tests/test_video_viewer_base.py tests/test_status_notes_feature.py -q`
Expected: all green.

- [ ] **Step 3: Confirm no consumer/origin file modified**

Run: `cd /home/sam/docker-images/deeplabcut-webapp-docker-supports && git diff --stat HEAD~2 -- dlc-3D/src/static/viewer_3d.js dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/enhanced_player.js clip-cutter/`
Expected: empty output.

---

## Phase-3a exit criteria

- `internal/csv_annotations.mjs` added with passing node tests; full viewer unit suite green.
- `features/status_notes.js` exports `statusNoteTimeline`, imports the reducers (no re-implementation), subscribes to `videoLoad`/`frameChange`, navigates via `viewer.seek`, and hardcodes no endpoint paths.
- `tests/test_status_notes_feature.py` passes.
- No consumer/origin file modified.

**Next:** Phase 3b — `ExtractModule` (clip extract/rename/delete/postfix; builds on Phase 1's `clip_naming.mjs`). Then `MarkerEditor` (the large overlay+editing feature, the bulk of the fork duplication), then `CurationModule`. Phase 4 migrates the consumers; Phase 5 adds the policy doc + enforcement test.
