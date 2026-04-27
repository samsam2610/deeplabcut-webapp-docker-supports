# Enhanced Player — Design Spec

**Date:** 2026-04-27

## Goal

Replace the two existing video players (the inline detection clip viewer in `player.js` and the template browsing overlay in `clip_cutter.js`) with a single unified enhanced player (`enhanced_player.js`) that lives as a resizable bottom panel. The player supports two modes — template browsing and clip viewing — and adds step-size navigation, editable frame counter, zoom, CSV status/note display, play-every-N, and a compact clip extract panel.

---

## Section 1: Scope

**In scope:**
- `enhanced_player.js` — new file; replaces `player.js` (deleted) and the `_tp` block in `clip_cutter.js`
- Bottom panel (`#player-panel`) — always in DOM, hidden until `openPlayer()` is called; video on left, narrow extract panel (~160px) on right
- **Navigation:** step-size input (frames per ◀/▶ click, default 10); ⏮/⏭ jump to clip start/end; seek slider; double-click frame counter to type-jump to any frame; keyboard: ← → single frame, Ctrl+←/→ skip by step-size
- **Playback:** play/pause; loop toggle; "Play every N frames" input (N=1 = normal, N>1 skips frames at same timer rate for fast preview)
- **Zoom:** slider 50–200% on frame image
- **Status/note strip:** reads parent video companion CSV via `/clip-cutter/csv`; shows current frame's `frame_line_status` and `note` values; ◀ ▶ buttons jump to prev/next frame with the same tag value
- **Clip extract panel:** Start frame, Frames (default 800), End frame (auto, read-only), Postfix (optional text), Output dir (auto-populated to `<video_parent>/<video_stem>/`, read-only display), Lock start checkbox
- **Clip mode extras:** seek bar highlights locked range `[kf−200, kf+599]`; nav and seek clamped to that range; "📌 Set KF" button — sets `detections[idx].frame_number` to current frame, recalculates extract panel start/end, recalculates locked range; lock start checkbox checked by default
- **Template mode extras:** no lock indicator, no "Set KF" or "Reject" buttons; seek bar unlocked (full video); start frame tracks current frame unless lock checkbox is checked
- **Reject** (clip mode only): removes `detections[idx]` from array, removes card from DOM, saves JSON
- New backend route: `GET /clip-cutter/csv?path=<abs_path>` — returns CSV rows as JSON

**Out of scope:**
- Writing annotations back to CSV
- Changes to scan pipeline, template init, folder browser, or DINOv2 logic

---

## Section 2: Architecture

### Public API

`enhanced_player.js` exports one function, called by `clip_cutter.js`:

```js
openPlayer({
  mode: "template" | "clip",
  videoPath: "/abs/path/to/video.avi",
  keyFrame1Based: 4823,     // clip mode only
  detectionIdx: 2,          // clip mode only
  csvPath: "/abs/path/to/video.csv",  // optional; null skips status/note strip
})
```

### Module-private state

```js
let _mode = null;               // "template" | "clip"
let _videoPath = null;
let _frameCount = 0;
let _currentFrame = 0;          // 0-based
let _clipStart = 0;             // 0-based; clip mode: kf0-200
let _clipEnd = 0;               // 0-based; clip mode: kf0+599
let _keyFrame = 0;              // 0-based; clip mode only
let _detectionIdx = null;       // clip mode only
let _csvRows = [];              // [{frame_number, frame_line_status, note}, ...]
let _stepSize = 10;
let _playN = 1;
let _playing = false;
let _looping = true;
let _busy = false;
let _timerId = null;
```

### Cross-file globals (from `clip_cutter.js`)

`detections[]`, `saveDetections()`, `setStatus()` — accessed as globals; same pattern as current `player.js`.

### Panel lifecycle

`#player-panel` is always in the DOM (hidden via `display:none`). `openPlayer()` shows it, resets all state, loads video info, optionally fetches CSV, then renders the first frame. A collapse button hides the panel and stops playback.

### CSV route

```
GET /clip-cutter/csv?path=/abs/path/to/video.csv
Response: { "rows": [{"frame_number": 1, "frame_line_status": "14", "note": "start_reaching"}, ...] }
404 if file not found
403 if path is outside the configured data root
```

Backend reads the CSV (columns: timestamp, frame_number, frame_line_status, note), skips the header, returns all rows as JSON. Read-only — no write path.

### `clip_cutter.js` changes

- Remove the `_tp` state object and all `_tpLoadFrame`, `_tpLoop`, `_tpUpdateDisplay`, `openTemplatePlayer`, `closeTemplatePlayer` functions (~80 lines)
- Card click handler: replace `loadClip(d.video_path, d.frame_number, idx)` with `openPlayer({mode:"clip", videoPath:d.video_path, keyFrame1Based:d.frame_number, detectionIdx:idx, csvPath: d.video_path.replace(/\.avi$/i, ".csv")})`
- "Browse frames" buttons: replace `openTemplatePlayer()` with `openPlayer({mode:"template", videoPath:selectedVideoPath, csvPath: selectedVideoPath.replace(/\.avi$/i, ".csv")})`
- Add Reject handler: `detections.splice(idx, 1)`, remove card from DOM, call `saveDetections()`
- Add Reject button to `buildResultCard`

---

## Section 3: UI Components

### Bottom panel (`#player-panel`)

Fixed to the bottom of the viewport, resizable vertically (CSS `resize: vertical` or drag handle). Default height: 320px.

```
┌─ #player-panel ─────────────────────────────────────────────────────────┐
│  [frame image — flex:1]                │  [extract panel — 160px]       │
│  [seek bar + frame counter]            │  Start  [_____]  ☑ lock        │
│  [⏮ ◀ ▶ ▶ ⏭]  Step[__] N=[__]  ↺    │  Frames [_800_]                │
│  [Status: 14  Note: start_reaching ◀▶] │  End    [_____] (auto)         │
│                                         │  Postfix[_____]                │
│                                         │  …/MAP2_20250515/              │
│                                         │  [📌 Set KF]  (clip mode)      │
│                                         │  [✂ Extract]                   │
│                                         │  [✕ Reject]   (clip mode)      │
└─────────────────────────────────────────────────────────────────────────┘
```

### Seek bar

- Full-width range input clamped to `[_clipStart, _clipEnd]` in clip mode (full video in template mode)
- In clip mode: blue highlight overlay covers the locked range `[_clipStart, _clipEnd]`
- Lock indicator badge top-left of frame image (clip mode only): `🔒 4623–5422`

### Frame counter

- `fr <N> / <total>` where N is **underlined** — double-click opens an inline `<input type="number">` pre-filled with the current 1-based frame number; Enter commits the jump; Escape cancels
- In clip mode, committed value is clamped to `[_clipStart+1, _clipEnd+1]`

### Playback controls

| Button | Action |
|--------|--------|
| ⏮ | Jump to `_clipStart` |
| ◀ | Go back `_stepSize` frames (clamped) |
| ▶ (play) | Toggle play/pause |
| ▶ (single) | Advance 1 frame |
| ⏭ | Jump to `_clipEnd` |

Step input: `<input type="number" min="1" value="10">` — updates `_stepSize` on change.

Play-N input: `<input type="number" min="1" value="1">` — updates `_playN`. When playing, each timer tick advances `_playN` frames instead of 1.

Loop toggle: ↺ button — toggles `_looping`; active state with blue border.

### Status/note strip

- Reads `_csvRows` for the row where `frame_number === _currentFrame + 1` (1-based)
- Displays `frame_line_status` and `note` as coloured pill badges
- ◀ ▶ buttons: find previous/next row with the same non-empty note value and jump to that frame
- If no CSV loaded or no matching row: strip shows `—`

### Clip extract panel (160px wide)

Fields (grid layout, label + input):
- **Start**: editable number; syncs to `_currentFrame + 1` on each frame change unless lock is checked
- **Frames**: editable number, default 800; changing it recalculates End
- **End**: auto-calculated (`Start + Frames − 1`), read-only (dimmed)
- **Postfix**: free text, optional
- **Output dir**: auto-populated `<video_parent>/<video_stem>/`, read-only display
- **Lock start** checkbox: when checked, Start does not track playback position

Buttons (stacked at bottom):
- **📌 Set KF** (clip mode only): sets `detections[_detectionIdx].frame_number = _currentFrame + 1`; recalculates `_clipStart/_clipEnd`; updates Start/End fields; calls `saveDetections()`
- **✂ Extract**: POSTs to `/clip-cutter/extract` with `{video_path, key_frame: start_frame + 200, postfix}`; on success marks detection as "kept" and disables panel buttons
- **✕ Reject** (clip mode only): removes `detections[_detectionIdx]`, removes card `#card-{idx}` from DOM, calls `saveDetections()`, hides player panel

---

## Section 4: File Changes

| File | Change |
|------|--------|
| `clip-cutter/static/enhanced_player.js` | **New** — all player logic |
| `clip-cutter/static/player.js` | **Deleted** |
| `clip-cutter/static/clip_cutter.js` | Remove `_tp` block; update card click + Browse buttons; add Reject; update `buildResultCard` |
| `clip-cutter/templates/clip_cutter.html` | Replace player markup + template-player markup with `#player-panel`; swap `<script>` tag |
| `clip-cutter/routes.py` | Add `GET /clip-cutter/csv` route |
| `clip-cutter/tests/test_routes.py` | Add 3 tests for `/csv` route |

---

## Section 5: Testing

### Backend (pytest)

```python
def test_csv_returns_rows(client, tmp_path):
    # create a CSV with known content, assert JSON response matches

def test_csv_missing_file_returns_404(client):
    # path that does not exist → 404

def test_csv_path_outside_data_root_returns_403(client):
    # path traversal attempt → 403
```

### Manual smoke tests

1. **Template mode:** Click "Browse frames" → bottom panel opens; full video navigable; step-size and play-N work; status/note strip shows CSV data; lock checkbox controls whether start tracks playback; Extract writes clip to `<parent>/<stem>/`
2. **Clip mode:** Click a detection card → panel opens; seek bar shows blue locked range; nav clamped; extract panel pre-populated; "📌 Set KF" updates detection and recalculates fields and lock range; Extract uses updated values and marks card as kept; Reject removes card and hides panel
3. **Mode switching:** Open template mode, then click a detection card — panel reinitialises cleanly with no stale state from the previous session
