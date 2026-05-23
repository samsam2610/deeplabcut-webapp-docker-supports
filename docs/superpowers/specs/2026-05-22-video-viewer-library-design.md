# Spec: reusable video-viewer library

**Date:** 2026-05-22
**Status:** Approved (pre-approved for implementation)
**Scope:** Frontend-only JS library. Migrate dlc-3D's three viewer forks onto it. clip-cutter frozen as the origin. Python backends stay parallel (endpoints injected via config).

> **Update (2026-05-23):** Phase 3 implemented FOUR features, not the originally-listed set:
> `StatusNoteTimeline`, `FrameExtractor`, `ClipExtractor`, `MarkerEditor`.
> - The single "ExtractModule" was split into **FrameExtractor** (add frames to `labeled-data/`)
>   and **ClipExtractor** (trim the master clip, behind an unchecked-by-default toggle), per the
>   two distinct extract workflows.
> - **CurationModule was dropped:** the inline-analysis "curation block" is ~95% composition of
>   `StatusNoteTimeline` + `FrameExtractor` (which already does both-cams) under a consumer-side
>   "curation mode" show/hide toggle — no genuinely-new reusable logic. "Finalize-analysis"
>   (`/dlc/project/inline-analysis/finalize-range`) is a separate feature, not curation, and is
>   not part of this library.
> See the phase plans in `docs/superpowers/plans/2026-05-2[23]-video-viewer-library-phase*`.

---

## 1. Background & motivation

The clip-cutter module contains the gold-standard video curation viewer:
`clip-cutter/static/enhanced_player.js` (2054 lines) + `clip-cutter/static/clip_cutter.js`
(2055 lines). It provides frame navigation (step ±1/±N, scrubber, jump, keyboard),
sync-cam (frame-locked second camera), status/note browsing (canvas timelines + chips +
prev/next nav), and a clip-extract module (queue, rename, delete, postfix tags).

That code was **forked three times** into dlc-3D, and the forks have diverged badly:

| File | Lines | What it is |
|---|---|---|
| `dlc-3D/src/static/enhanced_player.js` | 570 | stripped clone; single-cam frame player used by the 3D-Extract card |
| `dlc-3D/src/static/viewer_3d.js` | 3223 | dual-cam frame-locked sync + kinematic overlay + marker editing |
| `dlc-3D/src/static/inline_analysis_3d.js` | 3819 | **~95% verbatim copy of `viewer_3d.js`** with `_va`→`_ia` prefixes, plus a curation mode |

`viewer_3d.js` and `inline_analysis_3d.js` are near-identical (~7000 lines of mostly
duplicated logic: frame loader, pose cache, overlay rendering, marker editing, CSV
annotation, hit-testing). Any bug fix must currently land in both.

**Goal:** extract one reusable, well-documented, parameterized video-viewer library and
migrate dlc-3D's three forks onto it, collapsing the duplication. clip-cutter (the origin)
is left untouched; adopting the library there later is tracked as tech debt.

This follows the existing `file_browser.js` precedent in this repo: a canonical component
in `dlc-3D/src/static/components/`, a policy doc in `docs/policies/`, and a static-analysis
enforcement test in `dlc-3D/tests/`.

---

## 2. Non-goals

- **No backend changes.** The parallel Flask backends (`/clip-cutter/*`, `/dlc-3d/*`,
  `/annotate/*`) stay as-is. The library is frontend-only and reaches them through
  injected endpoint config. Consolidating the Python backends is explicitly out of scope.
- **No changes to clip-cutter.** It is the frozen origin. It keeps its own
  `enhanced_player.js` / `clip_cutter.js`.
- **No new viewer features.** This is a faithful extraction + de-duplication. Behavior
  parity with today's forks is the bar. (One latent enhancement — per-tile/tile-1 editing —
  is noted as a follow-up, not part of this work.)

---

## 3. Architecture

### 3.1 Layout (follows the file_browser precedent)

```
dlc-3D/src/static/components/viewer/
  video_viewer.js          base class VideoViewer (the clip-cutter core)
  features/
    status_notes.js        StatusNoteTimeline tracker
    extract.js             ExtractModule (clip / rename / delete / postfix)
    marker_editor.js       MarkerEditor (overlay + editing)
    curation.js            CurationModule (thin; inline-analysis only)
  internal/                pure logic, unit-tested with node:test
    frame_pacer.mjs        step / clamp / wrap / playback-timing math
    palette.mjs            HSV→RGB, per-layer colors
    shapes.mjs             marker shape drawing
    clip_naming.mjs        {stem}_{start}_{end}_{postfix} parse / build

docs/policies/video-viewer-component.md      policy doc (the contract + rationale)
dlc-3D/tests/test_video_viewer_policy.py     static-analysis enforcement
```

Convention (matches the repo): `.mjs` = pure logic, importable and unit-tested with
Node's built-in `node:test` runner (like the existing `src/static/pair_map.mjs` +
`tests/unit/test_pair_map.mjs`). `.js` = DOM-bound modules covered by E2E tests.

### 3.2 Composition model

A **base class + composable feature modules** the consumer attaches in any combination.
Composition (not subclass inheritance) is required because the consumers need different
combinations of the add-ons (e.g. 3D-Extract wants {Status/Notes + Extract} but no markers;
viewer_3d wants {Status/Notes + Markers} but no extract). A single inheritance chain cannot
express "pick any subset of N".

```js
import { VideoViewer } from "./components/viewer/video_viewer.js";
import { statusNoteTimeline } from "./components/viewer/features/status_notes.js";
import { markerEditor }       from "./components/viewer/features/marker_editor.js";

const v = new VideoViewer({ mount, endpoints, storagePrefix: "dlc3d", fps: 30 });
v.use(statusNoteTimeline({ statusEl, noteEl, endpoints: { csv, saveAnnotation } }));
v.use(markerEditor({ endpoints: { poses, siblingH5, saveMarker }, editable: true }));
await v.load({ videoPath });
v.seek(120);
```

### 3.3 Base class — `VideoViewer`

Owns everything camera/curation-agnostic:

- **Tiles**: 1..N frame-locked camera tiles. This single abstraction generalizes
  clip-cutter's cam1/cam2 parallel-fetch sync-cam *and* dlc-3D's `Controller`/`Tile`
  dual-camera model. Each tile wraps `{ img, canvas, label, container }`. This is the
  "both 2D and 3D via sync cam" capability.
- **Frame source**: loads frames via injected `endpoints.frame(path, n)`; prefetches the
  next frame for smooth stepping. (Frame-by-frame JPEG/PNG fetch — no HTML5 `<video>` element,
  matching how all current forks work.)
- **Playback / navigation**: play/pause, direction, step ±1 / ±N, loop, FPS, seek bar,
  jump-to-frame, frame counter, configurable keyboard map, zoom.
- **Hook bus**: features subscribe to lifecycle events:
  - `onVideoLoad({ videoPath, frameCount, tiles })`
  - `onFrameChange(n)`
  - `onDrawTile(tile, n)`   — for per-tile overlay rendering
  - `onTeardown()`

**Config (all coupling injected — no hardcoded paths/ids/storage keys):**

```js
new VideoViewer({
  mount: HTMLElement,           // container the viewer renders into
  endpoints: {
    videoInfo: (path) => url,   // → { frame_count, fps }
    frame:     (path, n) => url,// → image bytes
    sibling:   (path) => url,   // optional → { sibling_video_path } for sync-cam
  },
  fps: 15,
  storagePrefix: "dlc3d",       // namespaces all localStorage keys
  keymap: { ... },              // optional override of default shortcuts
})
```

**Public API:** `load({ videoPath, siblingPath? })`, `seek(n)`, `step(delta)`, `play()`,
`pause()`, `currentFrame()`, `frameCount()`, `getTile(i)`, `use(feature)`, `on(event, cb)`,
`destroy()`.

**Frame-locked seek:** `seek(n)` loads frame `n` on all tiles in parallel
(`Promise.all`), then fires `onFrameChange(n)` and `onDrawTile(tile, n)` per tile so
features redraw overlays/timelines. This is the consolidation of
clip-cutter's `_epLoadCam2Frame` and dlc-3D's `Controller.seek`.

### 3.4 Feature modules

Each feature is a factory returning `{ attach(viewer) }`. It owns its own DOM sub-region
(passed in config), subscribes to hook-bus events, and exposes its own small API. All
endpoints are injected.

| Module | Replaces today | Responsibilities | Injected endpoints |
|---|---|---|---|
| **StatusNoteTimeline** (`status_notes.js`) | the CSV/status/note blocks in all 3 forks | status track + note track canvases, chips, prev/next-by-chip nav, badges, sub-rows, save-back | `csv`, `saveAnnotation` |
| **ExtractModule** (`extract.js`) | `clip_cutter.js` extract flow + `dlc_3d.js` glue | start/len/end/postfix inputs, queue + SSE stream, rename, delete, postfix tags (localStorage, namespaced), sibling extract, keyframe-overlap check | `queue`, `queueStream`, `rename`, `delete`, `overlap` |
| **MarkerEditor** (`marker_editor.js`) | the bulk of `viewer_3d.js` / `inline_analysis_3d.js` | multi-layer pose overlay (primary editable + read-only compare), palette/shapes, pose cache + prefetch, per-tile render via `onDrawTile`, hit-test, hover labels, bodypart visibility, drag/place/right-click-delete edits, unsaved-ring, edit banner + gating | `poses`, `siblingH5`, `saveMarker` |
| **CurationModule** (`curation.js`) | the curation IIFE in `inline_analysis_3d.js` | curation-mode toggle, per-frame good/bad judgments, bulk per-camera apply | `saveCuration` |

### 3.5 Consumer composition

| Consumer | Replaces | Composition |
|---|---|---|
| 3D-Extract card | `dlc-3D enhanced_player.js` + extract glue in `dlc_3d.js` | `VideoViewer + StatusNoteTimeline + ExtractModule` |
| viewer_3d | `dlc-3D viewer_3d.js` | `VideoViewer(2 tiles) + StatusNoteTimeline + MarkerEditor({editable:true})` |
| inline_analysis_3d | `dlc-3D inline_analysis_3d.js` | `VideoViewer + StatusNoteTimeline + MarkerEditor + CurationModule` |
| clip-cutter | — | frozen; not migrated (tech debt) |

viewer_3d and inline_analysis_3d differ only in attached features and injected endpoints
(e.g. `/dlc-3d/save-marker` vs `/annotate/save-marker`). The ~7000-line duplication
collapses onto one base + one shared `MarkerEditor`.

---

## 4. Data flow

1. The consumer page builds config with endpoints pointing at its own backend
   (`/dlc-3d/...`), instantiates `VideoViewer`, attaches features, calls `load()`.
2. `load()` fetches video-info (frame count), optionally discovers a sibling video
   (sync-cam), creates tiles, fires `onVideoLoad` → features load their data
   (CSV rows, pose layers, extract state).
3. `seek(n)` loads frame `n` on all tiles (frame-locked), fires `onFrameChange(n)` +
   `onDrawTile(tile, n)` → features redraw overlays / timelines / badges.
4. User actions (edit a marker, queue an extract, set a curation judgment) flow through
   the relevant feature's API → POST to the injected endpoint.

---

## 5. Migration strategy (incremental, test-guarded)

This is the safe realization of the standing "don't refactor working code" rule: the shared
library is built and green **before** any working consumer is rewired, and each rewire is
isolated behind its existing E2E test.

- **Phase 0 — Baseline.** Confirm existing E2E suites pass before touching anything:
  `test_sync_frame.py`, `test_analyzed_viewer.py`, `test_inline_analysis_3d_ui_isolation.py`,
  `test_frame_labeler_3d_*`. Record the green baseline.
- **Phase 1 — Pure logic.** Extract `internal/*.mjs` (palette, shapes, frame_pacer,
  clip_naming) with `node:test` unit tests. No consumer changes.
- **Phase 2 — Base.** Build `VideoViewer` + hook bus + tile/frame-locked seek.
- **Phase 3 — Features.** Build `StatusNoteTimeline`, `ExtractModule`, `MarkerEditor`,
  `CurationModule` one at a time, each tested.
- **Phase 4 — Migrate consumers, smallest first.** Each is its own commit; the old file is
  deleted only after its E2E passes:
  1. 3D-Extract card → `VideoViewer + StatusNoteTimeline + ExtractModule`
  2. viewer_3d.js → `VideoViewer + StatusNoteTimeline + MarkerEditor`
  3. inline_analysis_3d.js → `+ CurationModule`
- **Phase 5 — Lock it in.** Add `docs/policies/video-viewer-component.md` + the enforcement
  test.

If later phases slip, the biggest win (collapsing viewer_3d/inline_analysis_3d onto one base)
still lands at phase 4.2–4.3.

---

## 6. Testing

- **Unit** (`node --test`, `.mjs`): frame-pacer step/clamp/wrap math, palette HSV→RGB,
  shape geometry, clip-filename parse/build, CSV row parsing. Mirrors the existing
  `tests/unit/test_pair_map.mjs` pattern.
- **E2E** (existing, as regression guards): `test_sync_frame`, `test_analyzed_viewer`,
  `test_inline_analysis_3d_ui_isolation`, frame-labeler tests. **Run only with the
  conftest/pytest.ini disk-cleanup hooks** — never run long pytest without them (prior
  incident leaked 614 GB into /tmp).
- **Static policy** (`test_video_viewer_policy.py`): canonical `video_viewer.js` exists and
  exports `VideoViewer`; all three consumers import it; no leftover inline `_va*` / `_ia*`
  viewer definitions remain.

---

## 7. Open points (not blockers — resolve during implementation)

- **Tile-1 editing.** inline_analysis_3d's per-tile (tile-1) editing is "deferred" today.
  The unified `MarkerEditor` makes per-tile editing a natural config. Preserve current
  behavior first; enabling tile-1 editing is a follow-up, not part of this work.
- **Curation boundary.** Keep `CurationModule` separate/thin rather than folding it into
  `MarkerEditor` (recommended), revisit if it proves too coupled.
- **Endpoint catalogue.** Each consumer's exact endpoint URLs must be captured from the
  current forks during migration so injected config is faithful (e.g. video vs frames vs
  browse-video frame modes in viewer_3d; `/dlc-3d/save-marker` vs `/annotate/save-marker`).

---

## 8. Risks

- **Size.** viewer_3d/inline_analysis_3d are ~3200–3800 lines each; the overlay/editing
  generalization is the largest piece. Mitigated by the phased plan — each phase ships
  independently and behavior parity is guarded by E2E.
- **Behavior drift.** Subtle differences between the forks (FPS, prefetch windows, frame
  modes) could be lost. Mitigated by capturing the endpoint/behavior catalogue per consumer
  before rewiring, and by E2E regression guards.
