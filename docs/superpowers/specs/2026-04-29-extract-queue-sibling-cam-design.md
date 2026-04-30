# Extract Queue + Sibling-Cam Extraction Design

**Date:** 2026-04-29  
**Scope:** `clip-cutter/` module

---

## Overview

Two related features:

1. **Sibling-cam extraction checkbox** — when "sync cam" is enabled in the player, a second checkbox appears (checked by default) so the user can extract the same clip window from the sibling camera simultaneously.

2. **Extract queue system** — instead of extracting immediately on accept, detections are queued. Extraction happens sequentially (one clip at a time) to avoid the GPU/disk bottleneck of concurrent writes. The queue persists across restarts via a global JSON file, auto-processes after 5 minutes of queue inactivity, and can be triggered manually from the detections bar.

---

## 1. Data Model

### 1.1 Queue item schema (`queue.json`)

```json
{
  "items": [
    {
      "id": "<uuid4>",
      "group_id": "<uuid4>",
      "video_path": "/path/to/cam0.avi",
      "key_frame": 1234,
      "postfix": "success",
      "status": "pending",
      "enqueued_at": "2026-04-29T12:00:00",
      "finished_at": null,
      "error": null,
      "avi_path": null
    }
  ]
}
```

**`status` values:** `"pending"` | `"processing"` | `"done"` | `"error"`

**`group_id`:** Sibling items share the same `group_id` as their primary item, so the frontend can render them as a unit. Primary always comes first in the list.

**File location:** `config.QUEUE_PATH` (a new config constant, e.g. `/data/clip_cutter_queue.json`).

### 1.2 Detection status

The existing per-video detection JSON (stored in `config.DETECTIONS_DIR`) gains a new status value: `"queued"`. This is the only source of truth for whether a detection's card should show the filled queue button on page refresh. The `queue.json` is the source of truth for extraction order and progress.

When a queued item finishes extraction (`"done"`), the backend updates the detection JSON: status → `"kept"`, `extract_avi_path` → extracted path.

When a queued item is removed before extraction, the backend updates the detection JSON: status → `"pending"`.

---

## 2. `queue_manager.py` Module

New standalone module with no Flask imports. All state is guarded by a single `threading.Lock`.

### 2.1 Public API

```python
def add(video_path, key_frame, postfix="", sibling_video_path=None, extract_sibling=False) -> list[str]:
    """Add 1 or 2 items. Returns list of item IDs added. Resets inactivity timer."""

def remove(item_id: str) -> bool:
    """Remove a pending item. Returns True if found and removed, False if not pending."""

def get_status() -> dict:
    """Return full queue snapshot: {items: [...], pending_count: int, processing: bool}"""

def process_now() -> None:
    """Signal the worker to begin processing immediately (non-blocking)."""

def start_worker() -> None:
    """Start the background worker thread (called once at app startup)."""
```

### 2.2 Worker loop

- Runs in a daemon thread started by `start_worker()`.
- Wakes every 30 seconds.
- Checks: `now - _last_enqueue_time > 300` AND `pending_count > 0` → begins processing.
- Also wakes immediately when `process_now()` is called (via `threading.Event`).
- Processes items sequentially: set `status="processing"`, call `processor.extract_clip()`, update item with result (`"done"` + `avi_path`, or `"error"` + message), update detection JSON, save queue file, repeat.
- Does **not** process items added while it is mid-run — those remain pending for the next cycle. (The timer resets on each `add()` call, so a user actively queuing won't trigger mid-session processing.)

### 2.3 Inactivity timer

`_last_enqueue_time` is an in-memory `float` (from `time.time()`). Reset on every `add()`. Worker checks `time.time() - _last_enqueue_time > 300`.

### 2.4 Persistence

`save()` writes atomically: serialize to `.tmp`, then `os.replace()` to `QUEUE_PATH`.  
`load()` reads on startup; items with `status="processing"` are reset to `"pending"` (they were interrupted by a restart).

### 2.5 Detection JSON update helper

`queue_manager` imports `processor` (already exists) and calls `processor.load_detections` / `processor.save_detections` to update the per-video detection JSON when item status changes. It matches a queue item to its detection by `video_path` + `key_frame`.

---

## 3. Backend Routes

All new routes added to `routes.py`, mounted under the existing `bp` blueprint.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/clip-cutter/queue` | Snapshot of queue state |
| POST | `/clip-cutter/queue` | Add item(s) to queue |
| DELETE | `/clip-cutter/queue/<id>` | Remove a pending item |
| POST | `/clip-cutter/queue/process` | Trigger immediate processing |
| GET | `/clip-cutter/queue/stream` | SSE: live queue status updates |

### POST `/clip-cutter/queue` request body

```json
{
  "video_path": "/path/to/cam0.avi",
  "key_frame": 1234,
  "postfix": "success",
  "extract_sibling": true,
  "sibling_video_path": "/path/to/cam1.avi"
}
```

Response: `{"ids": ["<uuid>", "<uuid>"], "pending_count": 3}`

### GET `/clip-cutter/queue/stream` (SSE)

Emits the full `get_status()` dict every time queue state changes (polled every 0.5 s in the generator). Closes when client disconnects. Format:

```
data: {"items": [...], "pending_count": 2, "processing": true}
```

### DELETE `/clip-cutter/queue/<id>`

Calls `queue_manager.remove(id)`. Also updates the per-video detection JSON (status back to `"pending"`). Returns `{"ok": true}` or `{"error": "..."}`.

---

## 4. UI Changes

### 4.1 Candidate card (results list)

`buildResultCard()` in `clip_cutter.js` adds a **yellow circle button** between the accept (✓) and reject (✗) buttons.

- **Unqueued state:** hollow yellow circle `○`, tooltip "Add to extract queue"
- **Queued state:** filled yellow circle `●` (CSS: `background: #f0c040`), tooltip "Remove from queue"
- On click (unqueued): POST to `/clip-cutter/queue`, detection status → `"queued"`, button fills.
- On click (queued): DELETE to `/clip-cutter/queue/<id>`, detection status → `"pending"`, button empties.
- State is restored on page load from detection JSON (`status === "queued"` → filled button, stored `queue_item_id` on the detection object).

The detection object gains two new optional fields: `queue_item_id` (string) and `sibling_queue_item_id` (string), stored in the detection JSON alongside existing fields.

### 4.2 Player extract panel

- **Rename** `✂ Extract` button → `✂ Extract Queue` (id `ep-extract` unchanged; label text changes).
- Clicking `ep-extract` now calls `_epQueueExtract()` instead of directly POSTing to `/extract`.
- `_epQueueExtract()`: POST `/clip-cutter/queue` with `extract_sibling` set based on `ep-extract-sibling` checkbox; update detection status; swap button visibility.
- **After queueing:**
  - `ep-extract` hidden.
  - Show `Remove queue` button (new element `ep-remove-queue`, styled like current `ep-delete-extract`).
  - `ep-rename-extract` hidden (no file yet).
  - `ep-delete-extract` hidden (no file yet).
- **After extraction completes** (detection status flips to `"kept"` via SSE):
  - `ep-remove-queue` hidden.
  - Show `ep-rename-extract` and `ep-delete-extract` (existing behavior).
- **`ep-delete-extract`** remains unchanged — only visible when `extract_avi_path` is set.

### 4.3 Sibling-cam extraction checkbox

In `enhanced_player.js` / the player HTML, below the existing `ep-sync-cam` label, add:

```html
<label id="ep-extract-sibling-label" style="display:none;">
  <input type="checkbox" id="ep-extract-sibling" checked> also extract sibling clip
</label>
```

Visibility logic in `_epUpdateSyncCamUI()`:
- Show `ep-extract-sibling-label` only when `_syncCamEnabled && _siblingVideoPath`.
- Checkbox is checked by default each time it becomes visible (reset to `true`).

When `ep-extract` is clicked:
- Read `ep-extract-sibling.checked`.
- If true, pass `extract_sibling: true, sibling_video_path: _siblingVideoPath` to the queue POST.
- The sibling item uses the same `key_frame` and `postfix`; the output directory is derived from `sibling_video_path` (sibling stem folder).

Sibling clip filename follows the same convention: `{sibling_stem}_{start}_{end}[_{postfix}].avi`.

### 4.4 Detections bar

In `clip_cutter.html`, next to the existing "Browse" button in the results header, add:

```html
<button id="extract-queue-btn" style="display:none;">⏳ Extract Queue (<span id="queue-pending-count">0</span>)</button>
```

- Shown when `pending_count > 0` (updated via SSE).
- On click: POST `/clip-cutter/queue/process`.
- Button label updates live as items are processed.

### 4.5 Live updates via SSE

On page load, `clip_cutter.js` opens `GET /clip-cutter/queue/stream`. On each message:
1. Update `#queue-pending-count` and show/hide `#extract-queue-btn`.
2. For each `"done"` item in the queue, find the matching detection by `queue_item_id` and update its card: status → `"kept"`, disable buttons, add `kept` class, update `result-name`.
3. For each `"error"` item, surface the error on the matching card.

The SSE connection is kept alive for the page session. On page refresh, `GET /clip-cutter/queue` provides the initial snapshot before the SSE stream opens.

---

## 5. Config

Add to `config.py`:

```python
QUEUE_PATH = Path(os.environ.get("CLIP_CUTTER_QUEUE_PATH", "/data/clip_cutter_queue.json"))
```

---

## 6. Startup

In `app.py`, after creating the Flask app, call `queue_manager.start_worker()` once. This starts the background thread. The thread is daemon=True so it doesn't block shutdown.

---

## 7. Error Handling

- If `extract_clip()` raises, the item is marked `"error"` with the message; the detection JSON is NOT updated to `"kept"`. The frontend shows an error indicator on the card.
- A failed item stays in the queue list (visible to the user) and is not retried automatically. The user can remove it manually.
- If `queue.json` is corrupted on load, the worker logs a warning and starts with an empty queue (does not crash).

---

## 8. What Does Not Change

- The `/extract` route remains for any direct-extract paths (browse mode manual extracts, which bypass the queue by design).
- All existing detection statuses (`pending`, `kept`, `rejected`) continue to work as before.
- The batch scan / batch init flows are unaffected.
- The rename-extract and delete-extract flows for already-extracted clips are unaffected.
