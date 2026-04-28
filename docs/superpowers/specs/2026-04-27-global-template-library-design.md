# Global Template Library Design

## Goal

Three coordinated improvements to the clip-cutter template system:
1. **Global template libraries** — named, persisted collections of clips-directory paths that act as multi-source templates for scanning
2. **Batch operations** — multi-select `.avi` files across folder navigation for batch template init and batch scan
3. **Template viewer rework** — replace the thumbnail grid with a compact filename list with View and Delete buttons

## Architecture

All changes extend the existing three files (`clip_cutter.html`, `clip_cutter.js`, `routes.py`) plus `config.py` and `processor.py`. No new files. No changes to `docker-compose.yml` — the existing Cloud mount (`/home/sam/synology/Parra-Lab-Data → /user-data/Parra-Data/Cloud`) already persists all app data under `_DATA_ROOT`.

**New backend surface:** 5 library CRUD routes + 2 batch operation routes (init + scan).

**New frontend surface:** batch mode toggle + persistent queue in browser; Libraries tab in sidebar; template viewer list.

---

## Data Model

### Global Library Registry

Stored at `config.LIBRARIES_PATH`:

```python
# config.py addition
LIBRARIES_PATH = Path(
    os.environ.get(
        "CLIP_CUTTER_LIBRARIES_PATH",
        str(_DATA_ROOT / "Reaching-Task-Data/clip-cutter/libraries.json"),
    )
)
```

Host path: `/home/sam/synology/Parra-Lab-Data/Reaching-Task-Data/clip-cutter/libraries.json`

File format:
```json
{
  "MAP-2 Daytime": [
    "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/MAP-2/MAP2_session1",
    "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/MAP-2/MAP2_session2"
  ],
  "MAP-3 Dim Light": [
    "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/MAP-3/MAP3_session1"
  ]
}
```

Each entry is a **clips directory** (the stem-named folder next to the `.avi` file). The template state is implicitly at `<clips_dir>/template/template_state.json`. Entries are stored as absolute container paths (the same path space used everywhere else in the app).

### Library Registry Helpers (`routes.py`)

```python
def _load_libraries() -> dict:
    """Load libraries.json; return {} if absent."""
    p = config.LIBRARIES_PATH
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)

def _save_libraries(libs: dict) -> None:
    config.LIBRARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.LIBRARIES_PATH, "w") as f:
        json.dump(libs, f, indent=2)
```

---

## Backend Routes

### Library CRUD

```
GET  /global-libraries
     → {libraries: {"MAP-2 Daytime": ["/path/...", ...], ...}}

POST /global-libraries
     body: {name: "MAP-2 Daytime"}
     → {ok: true}   (422 if name already exists or empty)

DELETE /global-libraries/<name>
     → {ok: true}   (404 if not found)

POST /global-libraries/<name>/folders
     body: {path: "/user-data/Parra-Data/Cloud/.../MAP2_session3"}
     → {ok: true, count: 3}   (422 if path already in library)

DELETE /global-libraries/<name>/folders
     body: {path: "..."}
     → {ok: true, count: 2}   (404 if path not in library)
```

All routes read/write `libraries.json` with a module-level `threading.Lock` (same pattern as `_state_lock`).

### Batch Init

```
POST /batch-init
     body: {videos: ["/user-data/.../vid1.avi", ...]}
     → {job_id: "batch-init-<uuid>"}   (starts background thread)

GET  /batch-init/stream?job_id=<id>
     → SSE stream:
       data: {"phase": "progress", "current": 3, "total": 12, "video": "MAP2_session4"}
       data: {"phase": "done", "initialized": 12, "failed": 0}
       data: {"phase": "error", "video": "...", "message": "..."}   (skips, continues)
```

Background thread calls `processor.init_template_from_clips_dir(clips_dir, state_path, crop=config.TRAINING_CROP)` for each video sequentially. `clips_dir = Path(video_path).parent / Path(video_path).stem`. Failures are collected and reported in the final `done` event as `failed_videos: [...]`. The thread writes directly to the Cloud mount — no temp files.

### Batch Scan

```
POST /batch-scan
     body: {
       template_dirs: ["/user-data/.../MAP2_session1", ...],
       video_paths:   ["/user-data/.../vid_to_scan.avi", ...],
       params: {stride, threshold, min_spacing, fine_window, trigger_value, sensor_margin}
     }
     → {job_id: "batch-scan-<uuid>"}

GET  /batch-scan/stream?job_id=<id>
     → SSE stream (one block per video):
       data: {"video": "vid.avi", "phase": "coarse", "current": 100, "total": 2000}
       data: {"video": "vid.avi", "phase": "fine",   "current": 10,  "total": 10}
       data: {"video": "vid.avi", "phase": "done",   "detections": [...]}
       data: {"all_done": true}
```

**Combined embedding construction** (`processor.py`):

```python
def load_combined_template(template_dirs: list[str]) -> dict:
    """Load and stack embeddings from multiple template_state.json files."""
    clip_embs, dino_embs = [], []
    for d in template_dirs:
        state = load_template_state(Path(d) / "template" / "template_state.json")
        if state["mean_embedding"] is not None:
            clip_embs.append(state["mean_embedding"])
        if state["dino_mean_embedding"] is not None:
            dino_embs.append(state["dino_mean_embedding"])
    return {
        "clip_matrix":  np.stack(clip_embs)  if clip_embs  else None,  # (N, D_clip)
        "dino_matrix":  np.stack(dino_embs)  if dino_embs  else None,  # (N, D_dino)
    }
```

**Max-similarity scan** — in `processor.py`, a new `scan_video_multi_template` function wraps the existing `scan_video` / `scan_video_sensor_guided`, replacing the single dot-product similarity with:

```python
# Instead of: sim = frame_emb @ template_emb
sim = (clip_matrix @ frame_emb).max()           # scalar, best match across N templates
dino_sim = (dino_matrix @ dino_frame_emb).max() # same for DINOv2
```

This is one extra reduction op per frame batch — no additional GPU passes.

---

## Frontend

### Template Viewer Rework (Sidebar — Template Tab)

The `#template-grid` thumbnail grid is replaced with `#template-list`, a compact scrollable list.

**HTML structure** (replacing `#template-grid`):
```html
<div id="template-list" style="display:none; overflow-y:auto; flex:1;"></div>
```

**Each row** rendered by `renderTemplate()`:
```html
<div class="tpl-row">
  <span class="tpl-label" title="/full/path/to/clip.avi · fr200">
    MAP2_0_20768_21567_success · fr200
  </span>
  <button class="player-btn tpl-view-btn" title="View frame">↗</button>
  <button class="player-btn tpl-del-btn"  title="Remove">✕</button>
</div>
```

**CSS additions:**
```css
.tpl-row { display:flex; align-items:center; gap:4px; padding:5px 8px;
           border-bottom:1px solid #21262d; }
.tpl-row:last-child { border-bottom: none; }
.tpl-label { flex:1; font-size:10px; color:#cdd9e5; overflow:hidden;
             text-overflow:ellipsis; white-space:nowrap; }
.tpl-view-btn, .tpl-del-btn { flex-shrink:0; padding:2px 6px; font-size:10px; }
```

**View button:** `window.open('/clip-cutter/frame?video=' + encodeURIComponent(f.video_path) + '&n=' + (f.frame_number - 1), '_blank')` — opens the existing `/frame` JPEG endpoint directly in a new tab. No server changes.

**Delete button:** calls existing `removeTemplateFrame(idx)` → `DELETE /template/<idx>`.

The `#sidebar-frame-count` header counter is retained.

---

### Browser Batch Mode

**Toolbar addition** in `.browser-toolbar`:
```html
<button class="player-btn" id="batch-toggle" title="Toggle batch selection">☐ Batch</button>
<span id="batch-count" style="display:none; font-size:10px; color:#768390;"></span>
<button class="player-btn" id="batch-init-btn"  style="display:none;">⚡ Init</button>
<button class="player-btn" id="batch-scan-btn"  style="display:none;">▶ Scan</button>
<button class="player-btn" id="batch-add-folder-btn" style="display:none;" title="Add current folder to selected library">+ Lib</button>
```

**JS module state additions:**
```javascript
let _batchMode = false;
const _batchQueue = new Set();   // full video_path strings, persists across navigation
let _activeBatchLibrary = null;  // library name currently expanded in Libraries tab
let _activeBatchFolders = new Set(); // checked folder paths in expanded library
```

**Batch mode toggle behavior:**
- `#batch-toggle` click → `_batchMode = !_batchMode` → re-renders browser rows
- In batch mode, each `.avi` file row renders with a `<input type="checkbox">` on the left, checked if the path is in `_batchQueue`
- Checkbox change adds/removes from `_batchQueue`, updates `#batch-count` badge
- Navigation (folder clicks) does not clear `_batchQueue`
- `#batch-init-btn` visible when `_batchMode && _batchQueue.size > 0`
- `#batch-scan-btn` visible when `_batchMode && _batchQueue.size > 0 && _activeBatchFolders.size > 0`
- `#batch-add-folder-btn` visible when `_batchMode && _activeBatchLibrary !== null` — adds `_currentBrowserPath` to `_activeBatchLibrary`

**Batch Init click handler:**
```javascript
// POST /batch-init, open SSE stream, show progress in #status-msg
// On done: clear _batchQueue, update batch-count badge
```

**Batch Scan click handler:**
```javascript
// POST /batch-scan with {template_dirs: [..._activeBatchFolders], video_paths: [..._batchQueue]}
// SSE stream → progress per video in #status-msg
// On each video done: append detection cards same as existing scan result rendering
```

---

### Sidebar Libraries Tab

**Tab switcher** added to `.sidebar-header` (between title and existing buttons):
```html
<div id="sidebar-tabs">
  <button class="sidebar-tab active" id="tab-template">Template</button>
  <button class="sidebar-tab"        id="tab-libraries">Libraries</button>
</div>
```

```css
#sidebar-tabs { display:flex; gap:2px; }
.sidebar-tab { font-size:9px; padding:2px 6px; border-radius:3px; cursor:pointer;
               border:1px solid #30363d; background:transparent; color:#768390; }
.sidebar-tab.active { border-color:#388bfd; color:#388bfd; }
```

**Libraries tab body** (`#libraries-panel`, hidden by default):
```html
<div id="libraries-panel" style="display:none; flex-direction:column; flex:1; overflow:hidden;">
  <div id="lib-header" style="padding:6px 8px; border-bottom:1px solid #30363d; display:flex; gap:4px;">
    <input id="lib-new-name" placeholder="New library…" style="flex:1; font-size:10px;">
    <button class="player-btn" id="lib-new-btn">+ New</button>
  </div>
  <div id="lib-list" style="overflow-y:auto; flex:1;"></div>
</div>
```

**Library card** (rendered per library in `#lib-list`):
```html
<div class="lib-card" data-name="MAP-2 Daytime">
  <div class="lib-card-header">
    <span class="lib-name">MAP-2 Daytime</span>
    <span class="lib-folder-count">2 folders</span>
    <button class="player-btn lib-delete-btn">✕</button>
  </div>
  <!-- Expanded body (shown when clicked) -->
  <div class="lib-card-body" style="display:none;">
    <div class="lib-folder-row">
      <input type="checkbox" class="lib-folder-check">
      <span class="lib-folder-label" title="/full/path">MAP2_session1</span>
      <button class="player-btn lib-folder-remove">✕</button>
    </div>
    ...
    <button class="player-btn lib-scan-btn">▶ Scan with checked (1)</button>
  </div>
</div>
```

```css
.lib-card { border-bottom:1px solid #21262d; }
.lib-card-header { display:flex; align-items:center; gap:4px; padding:5px 8px; cursor:pointer; }
.lib-name { flex:1; font-size:10px; color:#cdd9e5; }
.lib-folder-count { font-size:9px; color:#768390; }
.lib-card-body { padding:4px 8px 6px; }
.lib-folder-row { display:flex; align-items:center; gap:4px; padding:2px 0; }
.lib-folder-label { flex:1; font-size:9px; color:#768390; overflow:hidden;
                    text-overflow:ellipsis; white-space:nowrap; }
.lib-scan-btn { width:100%; margin-top:4px; font-size:9px; }
```

**Expanding a library card** sets `_activeBatchLibrary` and `_activeBatchFolders` (which folders are checked). Only one library expanded at a time. Collapsing clears `_activeBatchLibrary`.

**`[▶ Scan with checked (N)]`** calls the batch scan with `_activeBatchFolders` as template dirs and `_batchQueue` as video targets. Requires `_batchMode` active and `_batchQueue.size > 0` — button is disabled otherwise with tooltip "Enable batch mode and select videos first".

---

## Collapsed Sidebar Additions

```css
.sidebar.collapsed #libraries-panel,
.sidebar.collapsed #sidebar-tabs { display: none !important; }
```

---

## Testing

- `test_routes.py`: library CRUD (create, add folder, remove folder, delete library); 404/422 edge cases; `libraries.json` written and read correctly
- `test_processor.py`: `load_combined_template` with 0, 1, N dirs; max-similarity produces higher score than single-template dot product for a known matching frame
- `test_ui.py` (Playwright): batch mode toggle shows checkboxes; queue persists across folder navigation; `[+ Lib]` button adds current path to library; library card expand/collapse; scan button disabled without batch queue
