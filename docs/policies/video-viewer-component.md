# Policy: video-viewer component

**TL;DR:** Every frame-by-frame video curation viewer in this module's frontend MUST be built by composing `src/static/components/viewer/video_viewer.js` (the `VideoViewer` base) with the shared feature modules in `src/static/components/viewer/features/`. Do not fork the player (no per-card `Tile` class or `Controller` singleton).

## The canonical component

Path: `dlc-3D/src/static/components/viewer/`

- **Base:** `video_viewer.js` exports `class VideoViewer` — the DOM shell: N-tile frame-locked seek, play loop, zoom, per-tile sizing, keyboard, and a hook bus (`videoLoad` / `frameChange` / `drawTile` / `teardown`). Public surface: `load/seek/step/stepSkip/play/pause/togglePlay/use/on/destroy/currentFrame/frameCount/getTile/setZoom/setFps/setPlayStep/setLooping/setPlayDir/setSkipN/setTileWeight/equalizeTiles`.
- **Features** (each `factory(config) → { attach(viewer) }`, composed via `viewer.use(feature)`):
  - `features/status_notes.js` → `statusNoteTimeline` — companion-CSV status/note timeline bars, chips, prev/next nav, per-frame badges, optional save-back.
  - `features/frame_extractor.js` → `frameExtractor` — add frames (single + batch, incl. sibling-cam pairs) to `labeled-data/` via an injected `saveFrame` endpoint.
  - `features/clip_extractor.js` → `clipExtractor` — trim the master clip (start/length/end, postfix tags, keyframe-overlap), gated behind an unchecked-by-default checkbox.
  - `features/marker_editor.js` → `markerEditor` — kinematic pose overlay + focused-tile multi-view marker editing (per-cam edits routed to each cam's h5), comparison layers, threshold, bp chips, edit banner, and a `setEditable` master gate for gated-editing workflows.

All coupling — endpoints, DOM element refs, localStorage keys — is **injected via the feature/base `config`**. The library hardcodes no `/dlc-3d/`, `/clip-cutter/`, or DOM ids.

Pure logic lives in `components/viewer/internal/*.mjs` (node-tested with `node:test`); the DOM base and features are `*.js` (browser ESM, verified by the static-analysis contract tests in `dlc-3D/tests/test_*_feature.py` + `test_video_viewer_base.py`).

## Consumers

These cards are built on the library — each imports `VideoViewer` plus the features it needs and owns only its launcher/glue:

| Card | Consumer | Features used |
|------|----------|---------------|
| 3D Extract | `src/static/dlc_3d.js` | statusNoteTimeline, frameExtractor |
| View Analyzed | `src/static/viewer_3d.js` | statusNoteTimeline, markerEditor |
| Inline Analysis 3D | `src/static/inline_analysis_3d.js` | statusNoteTimeline, markerEditor (+ curation glue) |

(`clip-cutter` is the frozen origin the library was extracted from; adopting the library there is tracked tech debt, not required.)

## When to add a new feature vs. fork

If your card needs viewer behavior the library doesn't have, **add a feature module** (or extend an existing one) — do not copy the base player or a feature into your card and tweak it. A feature is the right unit when the behavior subscribes to the hook bus and reads the viewer's public surface.

Card-specific orchestration that is **not** player behavior stays as consumer glue, not in the library. Examples that legitimately live in the consumer: the inline card's snapshot picker / Start-Analysis worker calls / Initialize-file / 3D-Finalize range copy; a card's content-list launcher and Project/Browse tabs.

If you're tempted to write a new `class Tile` or `Controller` for a card, stop — compose `VideoViewer` instead.

## Why this rule exists

`viewer_3d.js` and `inline_analysis_3d.js` were ~95% duplicate forks of the same player (~7000 lines combined), with a third partial fork in the 3D-Extract card. Bug fixes (e.g. the NaN-pose render bug, sync-cam frame preservation, per-tile sizing) had to be re-applied per fork or silently missed one. Consolidating onto `VideoViewer` + features removed the duplication; the static-analysis tests in `dlc-3D/tests/test_video_viewer_policy.py` enforce that:

1. The canonical base + the four feature modules exist and export their factories.
2. Every feature factory returns an object exposing `attach` (the composition contract).
3. Each consumer imports `VideoViewer` from the canonical path and composes ≥1 feature.
4. No consumer reintroduces a player fork (`class Tile` / `const Controller`).
5. This policy doc exists.

If a future contributor adds a card by copying the player, those tests fail and force the conversation back to "compose the component instead."

## Adding a new consumer

```javascript
import { VideoViewer } from "./components/viewer/video_viewer.js";
import { statusNoteTimeline } from "./components/viewer/features/status_notes.js";
import { markerEditor } from "./components/viewer/features/marker_editor.js";

const viewer = new VideoViewer({
  mount: document.getElementById("my-viewer-mount"),
  perTileSize: true,
  endpoints: {
    frame:   (videoRel, n) => `/my/frame/${encodeURIComponent(videoRel)}/${n}`,
    sibling: (videoRel)    => `/my/sibling-camera?video=${encodeURIComponent(videoRel)}`,
  },
});
viewer.use(markerEditor({ endpoints: { /* poses, posesBatch, layerInfo, saveMarker, editCache */ }, els: { /* … */ } }));
viewer.use(statusNoteTimeline({ endpoints: { /* csv, saveRow */ }, els: { /* … */ } }));

await viewer.load({ videoPath, frameCount, framesMode: false, siblingPath: undefined });
```

## Adding capabilities to the component

If a card needs behavior the base or a feature lacks, **add it to the library**, not your card — as a new feature module, a new config option, or a new method on the relevant feature. (Recent examples: `VideoViewer` `perTileSize`; `markerEditor` focused-cam editing + `setEditable`.)

When you extend the library, update both this policy doc and the static-analysis tests (`test_video_viewer_policy.py` plus the relevant per-feature contract test) to cover the new contract.
