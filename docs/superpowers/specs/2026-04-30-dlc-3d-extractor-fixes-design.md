# DLC-3D Extractor Fixes — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Fix four issues in the 3D Frame Extractor:
1. Videos outside the DLC project directory fail to load (critical bug)
2. Project path display clutters the card — remove it; add an editable address bar for the current browse directory
3. Card is too wide — constrain to normal card width
4. Browser resets to project root after each video selection — persist the last visited directory; sibling camera detection broken for out-of-project videos

---

## Section 1: Absolute paths end-to-end

### Root cause

`_browseDir` computes paths relative to `_projectPath` using `.slice(_projectPath.length + 1)`. When the user browses to a location outside the project (e.g. `/user-data/Parra-Data/...`), this produces a garbage string. The backend `/frame` and `/video-info` endpoints also block any path outside the project directory.

### Frontend (`dlc_3d.js`)

In `_browseDir`, store the absolute path on file rows:

```javascript
row.dataset.videoPath = _browserCurrentPath + "/" + entry.name;
row.addEventListener("click", () => _selectVideo(row.dataset.videoPath));
```

`_selectVideo(videoPath)` receives the absolute path. Update the active-row highlight to match on `el.dataset.videoPath === videoPath`. The session key is still derived from the filename stem / parent folder name — no change to `_sessionKeyFromVideoRel` logic (rename it `_sessionKeyFromVideoPath`, keep the body identical).

`_extractFrame` sends `primary_video = getVideoPath()` — this now carries the absolute path. No change needed in `_extractFrame` itself.

### Backend (`routes.py`)

Add a helper used by all three endpoints:

```python
_USER_DATA_ROOT = "/user-data"

def _resolve_video_path(video_path: str, proj: str) -> "Path | None":
    if video_path.startswith("/"):
        p = Path(video_path).resolve()
        if not str(p).startswith(_USER_DATA_ROOT + "/"):
            return None
        return p
    p = (Path(proj) / video_path).resolve()
    if not p.is_relative_to(Path(proj).resolve()):
        return None
    return p
```

Apply it in:
- **`/frame`**: replace the current `Path(proj) / video_path` block with `_resolve_video_path(video_path, proj)`; return 400 if `None`.
- **`/video-info`**: same.
- **`/save-frame`** (`_save_single_frame`): replace the `Path(proj) / video_rel` + `is_relative_to` check with `_resolve_video_path`. The rest of the function (session key from stem, labeled-data save path) is unchanged because it operates on the filename stem only.

---

## Section 2: Remove project path display; add editable address bar

### HTML (`card_3d_extract.html`)

Remove the entire flex row containing `#dlc3d-project-display` and `#dlc3d-browse-btn`. Replace with a simpler structure:

```html
<div id="dlc3d-source-section">
  <div style="display:flex;align-items:center;gap:.4rem;margin-bottom:.35rem">
    <button id="dlc3d-browse-btn" class="btn-sm btn-server-pick"
            style="display:none;flex-shrink:0" title="Browse files">Browse</button>
    <input id="dlc3d-path-input" type="text"
           style="display:none;flex:1;font-size:.72rem;font-family:var(--mono);
                  padding:.2rem .4rem;background:var(--surface-2);
                  border:1px solid var(--border);border-radius:4px;color:var(--text);
                  min-width:0"
           placeholder="Type or paste a path, then press Enter">
  </div>
  <!-- Inline file browser (opened/closed by Browse button) -->
  <div id="dlc3d-file-browser" class="fe-video-list"
    style="display:none;max-height:220px;overflow-y:auto;margin-bottom:.5rem">
  </div>
  <p id="dlc3d-session-empty" class="explorer-empty">
    Load a DLC project via "Manage DLC Project".
  </p>
</div>
```

The Browse button and path input sit in the same flex row. Both are hidden until a project loads.

### JS (`dlc_3d.js`)

**`_loadProject`**: remove `document.getElementById("dlc3d-project-display").textContent = _projectPath`. Show the Browse button only — path input stays hidden until Browse is clicked.

**`_resetExtractorUI`**: remove `dlc3d-project-display` reset; add hide for `dlc3d-path-input`.

**`_browseDir(path)`**: after setting `_browserCurrentPath = data.path`, update the path input:
```javascript
const pathInput = document.getElementById("dlc3d-path-input");
if (pathInput) pathInput.value = data.path;
```

**Browse button toggle** (replace existing listener):
```javascript
document.getElementById("dlc3d-browse-btn")?.addEventListener("click", () => {
  const browser   = document.getElementById("dlc3d-file-browser");
  const pathInput = document.getElementById("dlc3d-path-input");
  if (browser.style.display === "none") {
    pathInput.style.display = "";
    _browseDir(_browserCurrentPath || _projectPath);
  } else {
    browser.style.display = "none";
    pathInput.style.display = "none";
    const empty = document.getElementById("dlc3d-session-empty");
    if (empty) empty.style.display = "";
  }
});
```

**Path input Enter handler** (new listener in `DOMContentLoaded`):
```javascript
document.getElementById("dlc3d-path-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const v = e.target.value.trim();
    if (v) _browseDir(v);
  }
});
```

**`_selectVideo`**: also hide `dlc3d-path-input` when collapsing:
```javascript
const pathInput = document.getElementById("dlc3d-path-input");
if (pathInput) pathInput.style.display = "none";
```

### CSS (`dlc_3d.css`)

Remove the two lines that override card width:
```css
/* REMOVE these two lines from #dlc-3d-extract-card: */
max-width: none;
width: 100%;
```

---

## Section 3: Browser persistence + filesystem sibling detection

### Browser persistence (`dlc_3d.js`)

The Browse button toggle in Section 2 already handles this: `_browseDir(_browserCurrentPath || _projectPath)`. When `_browserCurrentPath` is set (user has navigated somewhere), it reopens there. When null (first open), it starts at the project root.

`_resetExtractorUI` clears `_browserCurrentPath = null` — correct, so a project change resets the browse position.

### Filesystem sibling detection (`routes.py`)

Add a filesystem-based sibling search that works for any path:

```python
def _find_sibling_on_filesystem(video_abs: str) -> "str | None":
    vp = Path(video_abs)
    stem = vp.stem
    m = re.match(r'^(.+?)_cam(\d+)_(\d{8})', stem)
    if not m:
        return None
    prefix, date = m.group(1), m.group(3)
    cam_idx = int(m.group(2))
    for f in vp.parent.iterdir():
        if f == vp or f.suffix.lower() not in (".avi", ".mp4"):
            continue
        m2 = re.match(r'^(.+?)_cam(\d+)_(\d{8})', f.stem)
        if m2 and m2.group(1) == prefix and m2.group(3) == date and int(m2.group(2)) != cam_idx:
            return str(f)
    return None
```

Update the `/sibling-camera` endpoint to try `_find_sibling_on_filesystem` first (works for any absolute path), then fall back to the existing `videos.json` lookup for relative paths.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/dlc_3d.js` |
| Modify | `dlc-3D/src/static/dlc_3d.css` |
| Modify | `dlc-3D/src/dlc_3d_bp/routes.py` |
| Modify | `dlc-3D/tests/test_core.py` |

---

## Testing

Manual test paths:
- Videos: `/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/042326`
- DLC project: `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07`

1. `docker compose build dlc-3d && docker compose up -d dlc-3d`
2. Load project via "Manage DLC Project" → extractor card shows no project path, Browse button appears
3. Click Browse → path input + file list appear, starting at project root
4. Paste `/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/042326` into path input + Enter → navigates there
5. Click a `.avi` file → player loads, frame visible, browser collapses
6. Click Browse again → reopens at the same directory (not project root)
7. If sibling camera found → Sync Cam checkbox appears; enable it → sibling frame loads
8. Card is same width as other cards
9. `python -m pytest tests/test_core.py -q` → all tests pass (27+)
