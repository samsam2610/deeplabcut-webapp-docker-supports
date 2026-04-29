# KF Propagation + Note→Postfix Mapping — Design Spec

**Date:** 2026-04-28

---

## Goal

Two related features that together let users process candidate clips faster with less manual adjustment:

1. **KF Propagation** — when the user sets a new keyframe via "Set KF here," optionally add that frame to the video's template and re-run the fine scan ahead, updating pending candidates' keyframes automatically.
2. **Note→Postfix Mapping** — drag note chips onto quicktag bubbles to create persistent mappings; the extract panel auto-populates the postfix field for candidates whose window contains exactly one mapped note.

---

## Section 1: KF Propagation (Feature 1)

### 1.1 Trigger and checkbox

A "↻ Propagate KF" checkbox is added to the extract panel, directly below the `ep-set-kf` button area (near the `ep-warning` element). Default: **checked**.

When checked and the user clicks "📌 Set KF here" (`_epApplyNewKF` is called):

1. POST the new keyframe frame to `/clip-cutter/template/add` to enrich the template. **Wait for this to succeed** before proceeding — the rescan job must read the enriched embedding.
2. Collect all pending candidates with index ≥ `_detectionIdx + 3` on the same video (`detections[i].status` is neither `"kept"` nor `"rejected"`, and `detections[i].video_path === _videoPath`).
3. If any such candidates exist, POST to `/clip-cutter/rescan-forward` and open an SSE stream for results.
4. Show a compact progress bar in the extract panel while the job runs.

The offset of `+3` is the buffer: C+1 and C+2 are skipped to avoid interfering with candidates the user is likely about to review immediately.

### 1.2 Result handling (client)

On each SSE event `{ idx, new_frame_number, similarity }`:

- If `_detectionIdx === idx` → **discard** (user is currently on this candidate)
- If `detections[idx].status === "kept" || detections[idx].status === "rejected"` → **discard** (already processed; extraction sets status to `"kept"`)
- Otherwise → call `_epApplyRescanKF(idx, new_frame_number)` which updates `detections[idx].frame_number`, refreshes the card's clip-name label (`#card-clipname-{idx}`), and redraws the KF canvas

No **automatic** cancellation. The job runs to completion; individual results are silently dropped when they would conflict with the user's current state. The user can manually cancel via the progress indicator button.

### 1.3 Progress indicator

While a rescan job is active, show in the extract panel:

```
↻ Rescanning 5 ahead…  3 / 5   [✕ cancel]
```

The cancel button calls `POST /clip-cutter/rescan-forward/{job_id}/cancel` and clears the indicator. Results that arrive before cancel is processed are still subject to the discard rules.

### 1.4 Backend — `/clip-cutter/rescan-forward`

**Request:**
```json
{
  "video_path": "/abs/path/to/video.avi",
  "candidates": [
    { "idx": 4, "frame_number": 1234 },
    { "idx": 5, "frame_number": 1890 }
  ],
  "params": {
    "fine_window": 50
  }
}
```

**Processing strategy — maximize CUDA:1 utilization:**

The current pipeline embeds frames sequentially, leaving CUDA:1 (RTX PRO 6000 Blackwell) at 20–30%. To saturate it:

1. **Parallel frame prefetch** — use `ThreadPoolExecutor` (8–16 threads) to read all frames from all candidate windows from disk concurrently. Each candidate window is `[frame_number - fine_window, frame_number + fine_window]`, so ~101 frames per candidate. Disk I/O is the bottleneck here, not the GPU.
2. **Single large batch embed** — once all frames are loaded, embed the entire frame set in one call to `embed_frames_dino_batch(..., batch_size=N)` on `CUDA:1`. With the RTX PRO 6000 Blackwell's VRAM, `batch_size` can be tuned high enough to fill the GPU in one pass. Use `CUDA_VISIBLE_DEVICES=1` or `torch.device("cuda:1")` explicitly.
3. **Per-candidate argmax** — slice the embedding output back per candidate window, compute cosine similarity against the updated template mean embedding, take `argmax` to find the best frame within that window. That frame's 1-based index is the new `frame_number`.
4. **Stream results** — emit one SSE event per candidate as it resolves (candidates resolve in order since the batch is processed together, but emit as slices are computed).

**SSE event format:**
```json
{ "idx": 4, "new_frame_number": 1241, "similarity": 0.91 }
```

Terminal events: `{ "phase": "done" }` and `{ "phase": "error", "error": "..." }` and `{ "phase": "cancelled" }`.

**Cancellation:** job checks a threading `Event` before each emit; setting the event causes the job to exit cleanly after the current batch.

### 1.5 Template enrichment

The frame added to the template is the frame at the new keyframe position. This is identical to the existing `POST /clip-cutter/template/add` call, which updates `template_state.json` and recomputes the mean embedding. The rescan job reads the template after this update, so it uses the enriched embedding automatically.

---

## Section 2: Note→Postfix Mapping (Feature 2)

### 2.1 Storage

A new `localStorage` key `clip_cutter_note_mappings` stores a JSON object:
```json
{ "f": "failure", "s": "success" }
```

Keys are note values from the CSV; values are quicktag strings from `_epPostfixTags`. Mappings persist across sessions alongside the existing postfix tags.

### 2.2 Note palette UI

A "Note → Tag" subsection is added to the extract panel, directly below the existing quicktag row. It is only visible when a CSV with note data is loaded (`Object.keys(_epNoteColorMap).length > 0`).

**Structure:**
```
Note chips — drag onto a quicktag to map
  [⠿ f]  [⠿ s]  [⠿ start reaching]

Quicktags (drop zones):
  [failure]^f   [success]^s   [baseline]
```

- Note chips are draggable (`draggable="true"`). They are built from `_epNoteColorMap` keys whenever the note bar is rebuilt (`_epBuildTagBars`).
- Each mapped quicktag shows a small badge (the note value it is mapped from) in its top-right corner.
- Unmapped quicktags show a dashed border to invite drops.
- Dropping a note chip that already has a mapping onto a different quicktag **replaces** the old mapping.

### 2.3 Drag-and-drop interaction

**Dragstart** (note chip):
```js
chip.addEventListener("dragstart", e => {
  e.dataTransfer.setData("text/plain", noteVal);
  e.dataTransfer.effectAllowed = "link";
});
```

**Dragover** (quicktag bubble):
```js
bubble.addEventListener("dragover", e => {
  e.preventDefault();
  e.dataTransfer.dropEffect = "link";
  bubble.classList.add("drop-hover");
});
bubble.addEventListener("dragleave", () => bubble.classList.remove("drop-hover"));
```

**Drop** (quicktag bubble):
```js
bubble.addEventListener("drop", e => {
  e.preventDefault();
  bubble.classList.remove("drop-hover");
  const noteVal = e.dataTransfer.getData("text/plain");
  _epSaveNoteMapping(noteVal, tagVal);  // saves to localStorage
  _epRenderNotePalette();               // re-renders badges
  _epAutoPopulatePostfixes();           // scans all candidates
});
```

To clear a mapping: a small `×` appears on the badge; clicking it removes the mapping key and re-runs `_epAutoPopulatePostfixes`.

### 2.4 Auto-populate logic

`_epAutoPopulatePostfixes()` runs:
- When any mapping is created or removed
- When a new video loads (CSV rows are ready and mappings exist)
- When detections are rendered (`renderDetections`)

Returns early if `_csvRows` is empty (video has no CSV, or CSV not yet loaded).

For each detection `d` at index `i`:
1. Skip if `d.status === "kept"` or `d.status === "rejected"`.
2. Scan `_csvRows` for rows where `frame_number` is in `[d.frame_number − 200, d.frame_number + 599]` and `row.note` is non-empty.
3. Collect unique note values in that window that have entries in the mapping: `mappedNotes`.
4. Cases:
   - **`mappedNotes.length === 1`** → set `d.extract_postfix = mappings[mappedNotes[0]]`; update `#card-clipname-{i}` label; if `_detectionIdx === i`, also set `#ep-postfix`.
   - **`mappedNotes.length > 1`** → set conflict flag on card: add amber `⚠` badge showing the conflicting note values (e.g., "⚠ f + s").
   - **`mappedNotes.length === 0`** → no change (do not clear a postfix the user set manually).

### 2.5 Conflict indicator on result card

`buildResultCard` adds a hidden `<span class="ep-conflict-badge" style="display:none">⚠ …</span>` inside `.result-row`. `_epAutoPopulatePostfixes` shows/hides and sets its text content. The card gets a CSS class `has-conflict` which applies an amber left-border accent (mirrors the existing `kept`/`rejected` accent).

---

## Section 3: File Changes

| File | Change |
|------|--------|
| `clip-cutter/static/enhanced_player.js` | Add propagate checkbox logic, `_epApplyRescanKF`, rescan SSE listener, note palette render, drag-and-drop handlers, `_epAutoPopulatePostfixes`, note mapping localStorage helpers |
| `clip-cutter/static/clip_cutter.js` | Add conflict badge element to `buildResultCard`; call `_epAutoPopulatePostfixes` after `renderDetections` |
| `clip-cutter/templates/clip_cutter.html` | Add propagate checkbox + progress row in extract panel; add note palette section in extract panel; add `.drop-hover`, `.has-conflict`, `.ep-conflict-badge` CSS |
| `clip-cutter/routes.py` | Add `POST /clip-cutter/rescan-forward`, `GET /clip-cutter/rescan-forward/stream`, `POST /clip-cutter/rescan-forward/{job_id}/cancel` |
| `clip-cutter/processor.py` | Add `rescan_forward_candidates(video_path, candidates, fine_window, template_state, device)` — parallel prefetch + large-batch DINOv2 embed on specified device |

No new files. No changes to extraction pipeline, scan logic, or CSV handling.

---

## Section 4: Testing

**Feature 1:**
1. Set KF on candidate C with propagate checked → template gains a frame, rescan fires for C+3+. Candidate cards ahead update keyframes as SSE events arrive.
2. While rescan is running, click candidate C+4 → result for C+4 arrives and is silently discarded; card label does not change.
3. While rescan is running, extract candidate C+5 (status becomes "kept") → rescan result for C+5 arrives and is discarded.
4. Uncheck propagate, Set KF → no rescan fires, no template update.
5. Cancel button stops the job; partial results already applied remain.

**Feature 2:**
1. Drag "f" chip onto "failure" quicktag → badge "f" appears on "failure"; all candidates with only "f" in their window get `extract_postfix = "failure"`.
2. Candidate with both "f" and "s" in window → amber ⚠ badge shown, no postfix set.
3. Clear the "f" mapping → conflict badge and auto-postfix are removed from affected cards.
4. Open extract panel on auto-populated candidate → `ep-postfix` field shows the mapped tag value.
5. Load a video with no CSV → note palette is hidden.
