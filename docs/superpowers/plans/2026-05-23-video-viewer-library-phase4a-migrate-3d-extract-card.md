# Video-Viewer Library — Phase 4a (migrate the 3D-Extract card) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. This plan **rewrites working UI code**; its correctness gate is **live-app verification** (the E2E for this card is visibility-only). Do NOT delete `enhanced_player.js` until the live-app checklist passes.

**Goal:** Migrate dlc-3D's "3D Frame Extractor" card off its private `enhanced_player.js` fork onto the shared library: `VideoViewer` + `statusNoteTimeline` + `frameExtractor`. Behavior parity is the bar.

**Why this is different from Phases 1–3:** every prior phase was purely additive and test-isolated. This phase touches a working card. Its only E2E (`tests/e2e/test_ui.py`) covers **card visibility/open-close** (7 checks; 2 more are environment-stateful) — NOT player/extract behavior. So parity is verified by **driving the live app** (stack is up at `http://localhost:5000/dlc-3d/`).

**Branch:** `feat/3d-inline-analysis`. **Baseline recorded:** library contracts 81/81 green; `test_ui.py` 7 pass / 2 env-fail (a project is active in the live instance → `browse-row` shows). The 7 structural checks must stay green.

---

## Current wiring (the migration source)

**Files:** `src/templates/partials/card_3d_extract.html`, `src/static/dlc_3d.js`, `src/static/enhanced_player.js` (the 570-line fork — to be deleted), included via `src/templates/dlc_3d.html`.

**`dlc_3d.js` imports** (line 4): `{ openPlayer, getCurrentFrame, getVideoPath, getSiblingPath, isSyncCamEnabled, epLoadFrameAt } from "./enhanced_player.js"`.

**Player markup** (`card_3d_extract.html:41-60`): `#cam-displays` → `#ep-zoom-controls` (`#ep-zoom-3d`, `#ep-zoom-3d-pct`) + `#cam1-wrap`(`#ep-frame`, `#no-video-msg`) + `#ep-cam2-wrap`(`#ep-cam2-frame`).

**Backend endpoints:** `/dlc-3d/video-info?video=`, `/dlc-3d/frame?video=&n=`, `/dlc-3d/sibling-camera?video=` (→ `{sibling_video_path, calibration_exists}`), `/dlc-3d/csv?video=` (→ `{rows, csv_exists, csv_path}`), `/dlc-3d/save-frame` (POST), `/dlc-3d/labeled-frames?session=`.

**DOM ids by area** (all stay except the `#cam*`/`#ep-frame`/`#ep-cam2-frame` markup):
- base/playback: `ep-seek`, `ep-frame-num`, `ep-frame-total`, `ep-skip-start`, `ep-back`, `ep-back1`, `ep-play-back`, `ep-play`, `ep-fwd1`, `ep-fwd`, `ep-skip-end`, `ep-loop`, `ep-step`, `ep-playn`, `.ep-step-preset`, zoom `ep-zoom-3d`/`ep-zoom-3d-pct`, `no-video-msg`.
- status/notes: `ep-status-bar-wrap`/`ep-note-bar-wrap`, `ep-status-canvas`/`ep-note-canvas`, `ep-status-cursor`/`ep-note-cursor`, `ep-status-chips`/`ep-note-chips`, `ep-status-prev`/`next`, `ep-note-prev`/`next`.
- sync-cam: `sync-cam-row`, `ep-sync-cam`, `ep-extract-sibling-label`, `ep-extract-sibling`.
- extract: `ep-extract-btn`, `extract-count`, `ep-batch-count`, `ep-batch-step`, `ep-batch-extract-btn`, `ep-batch-stop-btn`, `extract-status`.
- labeled list: `labeled-wrap`, `labeled-count`, `labeled-list`.
- consumer-only glue (UNCHANGED): project/browse/select/session — `dlc3d-*`, `dlc-active-path` observer, session-key derivation, `/dlc-3d/project`, `/dlc-3d/browse`, `_refreshLabeledFrames`.

**Key behavioral nuances to preserve:**
1. **Sync-cam toggle gated on calibration.** `#ep-sync-cam` is OFF by default; enabling it is blocked unless `calibration_exists`; only when ON is the sibling shown. The library's `VideoViewer` shows a discovered sibling tile *whenever a `siblingPath` is passed to `load()`* → preserve the card's behavior by **passing `siblingPath` to `load()` only when sync-cam is enabled** and reloading on toggle. `#ep-extract-sibling` (extract both) is independent and read by `frameExtractor` via `els.extractSibling`.
2. **Status/note are browse-only here** (no save-row in this card) → `statusNoteTimeline` gets `endpoints.csv` only, no `saveRow`, and no badges/inputs.
3. **`no-video-msg`** empty state — consumer hides it once a video is loaded (VideoViewer has no empty-state).
4. Batch advances the player between saves — `frameExtractor` already does `viewer.seek(frames[i+1])`.

---

## Task 1: restructure the card markup (mount point + keep controls)

**Files:** Modify `src/templates/partials/card_3d_extract.html`.

- [ ] **Step 1:** Replace the player markup `#cam-displays` block (lines 41-60) so the dual-cam wrappers become a single VideoViewer mount, keeping the zoom controls and the empty-state message:

```html
        <!-- Dual cameras rendered by the shared VideoViewer -->
        <div id="cam-displays">
          <div id="ep-zoom-controls">
            <span style="font-size:10px">🔍</span>
            <input type="range" id="ep-zoom-3d" min="50" max="200" step="10" value="100">
            <span id="ep-zoom-3d-pct">100%</span>
          </div>
          <div id="ep-viewer-mount"></div>
          <span id="no-video-msg">Select a video from the list above.</span>
        </div>
```

Leave EVERYTHING else in the file unchanged (controls row, seek, status/note timelines, sync-cam row, extract section, labeled list).

- [ ] **Step 2:** Append a small CSS block (in the card's existing style location or a `<style>` in `dlc_3d.html`) so the generated `vv-tile` row matches the prior cam-wrap look. Add to `src/static/dlc_3d.css` (or the card's CSS file):

```css
/* VideoViewer tiles in the 3D-Extract card (parity with the old .cam-wrap look) */
#ep-viewer-mount .vv-tile-row { gap: 1rem; }
#ep-viewer-mount .vv-tile { display: flex; flex-direction: column; }
#ep-viewer-mount .vv-tile-label { font-size: .72rem; color: var(--text-dim); margin-bottom: .2rem; order: -1; }
#ep-viewer-mount .vv-frame-img { max-width: 100%; border: 1px solid var(--border); border-radius: 6px; background: #000; }
#ep-viewer-mount .vv-overlay-canvas { /* extract card has no overlay; harmless */ }
```

- [ ] **Step 3 (commit):**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_3d_extract.html dlc-3D/src/static/dlc_3d.css
git commit -m "refactor(dlc-3d): 3D-Extract card markup → VideoViewer mount point

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: rewire `dlc_3d.js` onto the library

**Files:** Modify `src/static/dlc_3d.js` (replace the `enhanced_player.js` import + `openPlayer` usage + extract handlers with the library composition; KEEP all project/browse/select/session/labeled glue).

- [ ] **Step 1:** Replace the import line (`dlc_3d.js:4`) with the library imports:

```js
import { VideoViewer } from "./components/viewer/video_viewer.js";
import { statusNoteTimeline } from "./components/viewer/features/status_notes.js";
import { frameExtractor } from "./components/viewer/features/frame_extractor.js";
```

- [ ] **Step 2:** Add a module-level viewer + feature handle and a builder. Place near the top of the module:

```js
let _viewer = null;
let _frameExtractor = null;

function _ensureViewer() {
  if (_viewer) return _viewer;
  const mount = document.getElementById("ep-viewer-mount");
  _viewer = new VideoViewer({
    mount,
    fps: 15,
    storagePrefix: "dlc3d-extract",
    endpoints: {
      videoInfo: (v) => `/dlc-3d/video-info?video=${encodeURIComponent(v)}`,
      frame:     (v, n) => `/dlc-3d/frame?video=${encodeURIComponent(v)}&n=${n}`,
      // sibling discovery is handled by the consumer (we pass siblingPath to load()
      // only when sync-cam is enabled), so endpoints.sibling is intentionally omitted.
    },
  });

  // status/note timeline (browse-only — no save-row in this card)
  _viewer.use(statusNoteTimeline({
    endpoints: { csv: (v) => `/dlc-3d/csv?video=${encodeURIComponent(v)}` },
    els: {
      statusCanvas: document.getElementById("ep-status-canvas"),
      noteCanvas:   document.getElementById("ep-note-canvas"),
      statusChips:  document.getElementById("ep-status-chips"),
      noteChips:    document.getElementById("ep-note-chips"),
      statusPrev:   document.getElementById("ep-status-prev"),
      statusNext:   document.getElementById("ep-status-next"),
      notePrev:     document.getElementById("ep-note-prev"),
      noteNext:     document.getElementById("ep-note-next"),
    },
  }));

  // frame extractor (single + batch + sibling) → /dlc-3d/save-frame
  _frameExtractor = frameExtractor({
    endpoints: {
      saveFrame: (payload) => fetch("/dlc-3d/save-frame", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    },
    els: {
      extractBtn:     document.getElementById("ep-extract-btn"),
      batchBtn:       document.getElementById("ep-batch-extract-btn"),
      batchStopBtn:   document.getElementById("ep-batch-stop-btn"),
      batchCount:     document.getElementById("ep-batch-count"),
      batchStep:      document.getElementById("ep-batch-step"),
      extractSibling: document.getElementById("ep-extract-sibling"),
      statusDisplay:  document.getElementById("extract-status"),
    },
    onSaved: () => _refreshLabeledFrames(),
  });
  _viewer.use(_frameExtractor);

  _wireViewerChrome(_viewer);
  return _viewer;
}
```

- [ ] **Step 3:** Add `_wireViewerChrome` — wire the card's existing playback/seek/zoom/status-toggle chrome to the viewer (replaces what `enhanced_player.js` did internally):

```js
function _wireViewerChrome(v) {
  const $ = (id) => document.getElementById(id);
  const stepSize = () => Math.max(1, parseInt($("ep-step")?.value, 10) || 10);

  $("ep-skip-start")?.addEventListener("click", () => v.seek(0));
  $("ep-skip-end")?.addEventListener("click", () => v.seek(v.frameCount() - 1));
  $("ep-back1")?.addEventListener("click", () => v.step(-1));
  $("ep-fwd1")?.addEventListener("click", () => v.step(1));
  $("ep-back")?.addEventListener("click", () => v.step(-stepSize()));
  $("ep-fwd")?.addEventListener("click", () => v.step(stepSize()));
  $("ep-play")?.addEventListener("click", () => { v.setPlayDir(1); v.togglePlay(); });
  $("ep-play-back")?.addEventListener("click", () => { v.setPlayDir(-1); v.togglePlay(); });
  $("ep-loop")?.addEventListener("click", (e) => {
    const on = !e.currentTarget.classList.contains("active");
    e.currentTarget.classList.toggle("active", on);
    v.setLooping(on);
  });
  $("ep-step")?.addEventListener("input", () => { v.setSkipN(stepSize()); v.setPlayStep(stepSize()); });
  $("ep-playn")?.addEventListener("input", (e) => v.setPlayStep(e.target.value));
  document.querySelectorAll(".ep-step-preset").forEach((p) =>
    p.addEventListener("click", () => { const s = $("ep-step"); if (s) { s.value = p.value; s.dispatchEvent(new Event("input")); } }));

  const seek = $("ep-seek");
  seek?.addEventListener("input", () => v.seek(parseInt(seek.value, 10) || 0));

  const zoom = $("ep-zoom-3d");
  zoom?.addEventListener("input", () => {
    v.setZoom(parseInt(zoom.value, 10) || 100);
    const pct = $("ep-zoom-3d-pct"); if (pct) pct.textContent = zoom.value + "%";
  });

  v.on("videoLoad", ({ frameCount }) => {
    if (seek) { seek.min = 0; seek.max = Math.max(frameCount - 1, 0); }
    const tot = $("ep-frame-total"); if (tot) tot.textContent = String(frameCount);
    $("no-video-msg")?.style.setProperty("display", "none");
    $("ep-extract-btn")?.removeAttribute("disabled");
    $("ep-batch-extract-btn")?.removeAttribute("disabled");
  });
  v.on("frameChange", (n) => {
    if (seek) seek.value = String(n);
    const num = $("ep-frame-num"); if (num) num.textContent = String(n + 1); // 1-based display
  });
}
```

- [ ] **Step 4:** Replace `_selectVideo`'s `openPlayer(...)` call with the library load + sync-cam handling. Where `_selectVideo` currently does the sibling fetch + `openPlayer(videoPath, siblingPath, calibrationExists)`, change to:

```js
  // _selectVideo: after fetching { sibling_video_path, calibration_exists }
  _currentVideo = videoPath;
  _siblingVideo = siblingPath || null;
  _calibrationExists = !!calibrationExists;
  const v = _ensureViewer();
  _setupSyncCamToggle(v);                      // wires #ep-sync-cam (calibration-gated)
  const syncOn = document.getElementById("ep-sync-cam")?.checked;
  await v.load({ videoPath, siblingPath: syncOn ? _siblingVideo : null });
  _refreshLabeledFrames();
```

And add the sync-cam toggle handler (preserves the calibration gate + sibling-extract label visibility):

```js
function _setupSyncCamToggle(v) {
  const row = document.getElementById("sync-cam-row");
  const cb = document.getElementById("ep-sync-cam");
  const sibLabel = document.getElementById("ep-extract-sibling-label");
  if (!cb) return;
  // show the sync-cam row only when a sibling exists
  if (row) row.style.display = _siblingVideo ? "flex" : "none";
  if (cb._wired) return; cb._wired = true;
  cb.addEventListener("change", async () => {
    if (cb.checked && !_calibrationExists) {
      cb.checked = false;
      const st = document.getElementById("extract-status");
      if (st) st.textContent = "Sync cam needs calibration.toml (not found).";
      return;
    }
    if (sibLabel) sibLabel.style.display = cb.checked ? "flex" : "none";
    // reload with/without the sibling tile to match the toggle
    await v.load({ videoPath: _currentVideo, siblingPath: cb.checked ? _siblingVideo : null });
  });
}
```

- [ ] **Step 5:** Delete the now-dead extract code in `dlc_3d.js`: `_extractFrame`, `_extractBatch`, `_setBatchUIRunning`, `_batchStopRequested`, and any direct uses of `getCurrentFrame`/`getVideoPath`/`getSiblingPath`/`isSyncCamEnabled`/`epLoadFrameAt` (now owned by `frameExtractor` + the viewer). Keep `_refreshLabeledFrames`, project/browse/select/session glue. Reset on card close (`_resetExtractorUI`): call `_viewer?.destroy(); _viewer = null; _frameExtractor = null;` so re-open rebuilds cleanly.

- [ ] **Step 6:** If `dlc_3d.html` includes `enhanced_player.js` as a separate `<script type="module">`, remove that include (the import graph now pulls the library instead). Verify `dlc_3d.js` is loaded as a module.

- [ ] **Step 7 (commit):**
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.js dlc-3D/src/templates/dlc_3d.html
git commit -m "refactor(dlc-3d): 3D-Extract card consumes VideoViewer + StatusNoteTimeline + FrameExtractor

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: live-app verification (the correctness gate) + structural E2E

**Files:** none (verification). The dlc-3d container serves `src/` live (no rebuild needed for static/template edits — confirm by hard-refresh).

- [ ] **Step 1: structural E2E still green** (the 7 non-stateful checks):
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/test_ui.py -q -k "not browse_row_hidden_without_project and not open_extractor_card"
```
Expected: the structural checks pass (card hidden by default, opens, closes, others unaffected, empty-state, file-browser gating). (The 2 excluded are environment-stateful — a project is active.)

- [ ] **Step 2: drive the live app** at `http://localhost:5000/dlc-3d/` (token auth) and confirm parity against the pre-migration behavior. Use the `verify` skill / Playwright. Checklist:
  1. Open the 3D-Extract card; with the active project, browse + select a sync-cam video.
  2. **Tiles render** in `#ep-viewer-mount`; `no-video-msg` hides; frame 0 shows; counter shows `1 / N`.
  3. **Frame nav:** `‹`/`›` step ±1; `◀◀`/`▶▶` step ±N (the Step value); `⏮`/`⏭` jump to ends; seek bar scrubs and updates the counter; ←/→ keyboard steps.
  4. **Play/pause:** `▶` plays forward, toggles to pause; loop toggle (`↻`) wraps; `ep-playn`/presets change step.
  5. **Zoom:** slider resizes the tile row; `%` label updates.
  6. **Status/note:** if the CSV has rows, the status/note timelines + chips appear; toggling a chip highlights the timeline; prev/next jumps to matching frames.
  7. **Sync-cam:** with a sibling present, the `Sync Cam` checkbox enables the 2nd tile (frame-locked); blocked with a message if no calibration; the `Extract Sibling` label appears when on.
  8. **Extract:** `Extract Frame` saves (status line shows saved/skipped/calibration); `Extract Batch` (count/step) saves N frames advancing between each; `Stop` aborts; with sync-cam on, both cams saved; the `Extracted frames` list refreshes.
  9. No console errors; closing + reopening the card rebuilds cleanly.

- [ ] **Step 3:** Only after Step 2 passes, delete the fork and commit:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git rm dlc-3D/src/static/enhanced_player.js
# confirm nothing else imports it:
grep -rn "enhanced_player" dlc-3D/src && echo "STILL REFERENCED — do not delete" || true
git commit -m "refactor(dlc-3d): drop enhanced_player.js fork (3D-Extract card now on the shared library)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Phase-4a exit criteria

- The 3D-Extract card runs on `VideoViewer` + `statusNoteTimeline` + `frameExtractor`; `enhanced_player.js` deleted; nothing references it.
- Structural `test_ui.py` checks green; live-app checklist (Step 2) passes — frame nav, seek, zoom, play/loop, status/note browse, sync-cam toggle (calibration-gated), single + batch + sibling extract, labeled-frames refresh.
- Library node suite + all feature contracts still green; no library file changed by this phase.

**Next:** Phase 4b — migrate `viewer_3d.js` (View Analyzed card) onto `VideoViewer` + `statusNoteTimeline` + `markerEditor`, guarded by `test_analyzed_viewer.py` + `test_sync_frame.py` + `test_per_tile_size.py` (real behavioral E2E). Then 4c — `inline_analysis_3d.js` (+ curation = compose StatusNoteTimeline+FrameExtractor under a toggle). Phase 5 — policy doc + enforcement test.
