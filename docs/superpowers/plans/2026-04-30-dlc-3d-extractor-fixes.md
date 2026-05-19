# DLC-3D Extractor Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four bugs in the DLC-3D Frame Extractor: absolute video paths end-to-end (backend now accepts any `/user-data/` path), remove project path display + add editable address bar, constrain card width, and persist last browse directory with filesystem-based sibling detection.

**Architecture:** Four sequential tasks — two backend (routes.py), one HTML/CSS, one JS. Each builds on the last: backend first so JS tests can hit real endpoints, then HTML so JS wiring has real DOM, then JS last.

**Tech Stack:** Flask Blueprint (Python), Vanilla ES6 JS module, Jinja2 HTML partial, pytest unit tests, pytest-playwright E2E tests.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `dlc-3D/src/dlc_3d_bp/routes.py` |
| Modify | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Modify | `dlc-3D/src/static/dlc_3d.js` |
| Modify | `dlc-3D/src/static/dlc_3d.css` |
| Modify | `dlc-3D/tests/test_core.py` |

---

### Task 1: Backend — `_resolve_video_path` + update `/frame` and `/video-info`

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py:28-48` (add helpers after regex block)
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py:292-339` (update `/frame` and `/video-info`)
- Modify: `dlc-3D/tests/test_core.py` (add tests + import `_resolve_video_path`)

**Context:** `routes.py` currently constructs video paths as `(Path(proj) / video_path).resolve()` and checks `is_relative_to(proj)`, blocking any path outside the project directory. Videos at `/user-data/Parra-Data/...` are outside the DLC project at `/user-data/NAS-Data-Share/...`, so every frame request returns 400. The fix: a new `_resolve_video_path` helper that accepts any absolute path within `/user-data/` or relative paths within the project. Apply it to `/frame` and `/video-info`; the next task handles `_save_single_frame` and `/sibling-camera`.

- [ ] **Step 1: Write failing tests for `_resolve_video_path`**

Append to `dlc-3D/tests/test_core.py`. First update the import block at the top of the file (lines 10-17):

```python
from dlc_3d_bp.routes import (
    _cam_index_from_stem,
    _find_sibling_on_filesystem,
    _find_sibling_video,
    _load_or_scan_videos,
    _resolve_video_path,
    _save_single_frame,
    _scan_videos,
    _session_key_from_stem,
)
```

Then append these tests at the end of `test_core.py`:

```python
# ── _resolve_video_path ───────────────────────────────────────────────────────

def test_resolve_video_path_absolute_within_user_data():
    p = _resolve_video_path("/user-data/Parra-Data/videos/foo.avi", "/user-data/proj")
    assert p == Path("/user-data/Parra-Data/videos/foo.avi")


def test_resolve_video_path_absolute_outside_user_data_returns_none():
    p = _resolve_video_path("/etc/passwd", "/user-data/proj")
    assert p is None


def test_resolve_video_path_relative_within_project(tmp_path):
    p = _resolve_video_path("videos/foo.avi", str(tmp_path))
    assert p == (tmp_path / "videos/foo.avi").resolve()


def test_resolve_video_path_relative_escaping_project_returns_none(tmp_path):
    p = _resolve_video_path("../../etc/passwd", str(tmp_path))
    assert p is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py::test_resolve_video_path_absolute_within_user_data tests/test_core.py::test_resolve_video_path_absolute_outside_user_data_returns_none tests/test_core.py::test_resolve_video_path_relative_within_project tests/test_core.py::test_resolve_video_path_relative_escaping_project_returns_none -v
```

Expected: FAIL — `ImportError: cannot import name '_resolve_video_path'`

- [ ] **Step 3: Add `_USER_DATA_ROOT` constant and `_resolve_video_path` to `routes.py`**

In `dlc-3D/src/dlc_3d_bp/routes.py`, add after line 32 (after `_FRAME_RE = re.compile(...)`) and before the blank line + `def _session_key_from_stem`:

```python
# ── Path security ─────────────────────────────────────────────────────────────

_USER_DATA_ROOT = "/user-data"


def _resolve_video_path(video_path: str, proj: str) -> "Path | None":
    """Return resolved absolute Path for video_path, or None if disallowed.

    Absolute paths must be within /user-data/.
    Relative paths must stay within the project directory.
    """
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

- [ ] **Step 4: Run tests to confirm the four new tests pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py::test_resolve_video_path_absolute_within_user_data tests/test_core.py::test_resolve_video_path_absolute_outside_user_data_returns_none tests/test_core.py::test_resolve_video_path_relative_within_project tests/test_core.py::test_resolve_video_path_relative_escaping_project_returns_none -v
```

Expected: 4 passed.

- [ ] **Step 5: Update `/frame` endpoint to use `_resolve_video_path`**

In `routes.py`, replace lines 309–311:

```python
    full_path = (Path(proj) / video_path).resolve()
    if not full_path.is_relative_to(Path(proj).resolve()):
        return jsonify({"error": "video path escapes project root"}), 400
```

With:

```python
    full_path = _resolve_video_path(video_path, proj)
    if full_path is None:
        return jsonify({"error": "video path not allowed"}), 400
```

- [ ] **Step 6: Update `/video-info` endpoint to use `_resolve_video_path`**

In `routes.py`, replace lines 332–334:

```python
    full_path = (Path(proj) / video_path).resolve()
    if not full_path.is_relative_to(Path(proj).resolve()):
        return jsonify({"error": "video path escapes project root"}), 400
```

With:

```python
    full_path = _resolve_video_path(video_path, proj)
    if full_path is None:
        return jsonify({"error": "video path not allowed"}), 400
```

- [ ] **Step 7: Run full backend test suite to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py -q
```

Expected: 31 passed (27 original + 4 new).

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_core.py
git commit -m "feat: add _resolve_video_path, accept /user-data/ absolute paths in /frame and /video-info"
```

---

### Task 2: Backend — `_save_single_frame` + `_find_sibling_on_filesystem` + `/sibling-camera`

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py:153-204` (`_save_single_frame`)
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py:112-148` (add `_find_sibling_on_filesystem` after `_find_sibling_video`)
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py:342-357` (`/sibling-camera` endpoint)
- Modify: `dlc-3D/tests/test_core.py` (add tests + import `_find_sibling_on_filesystem`)

**Context:** `_save_single_frame` uses the same `(project_path / video_rel).resolve()` + `is_relative_to` pattern as `/frame`. The `/sibling-camera` endpoint only looks up `videos.json`, which only lists project-internal videos — it can't find siblings for out-of-project paths. New `_find_sibling_on_filesystem` scans the video's parent directory for files with the same session prefix and date but a different camera index.

- [ ] **Step 1: Write failing tests for `_find_sibling_on_filesystem`**

Append to `dlc-3D/tests/test_core.py` (the import at the top was already updated in Task 1 to include `_find_sibling_on_filesystem`):

```python
# ── _find_sibling_on_filesystem ───────────────────────────────────────────────

def test_find_sibling_on_filesystem_finds_cam1(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    cam0 = vid_dir / "surv1_cam0_20260123_121732_0.avi"
    cam1 = vid_dir / "surv1_cam1_20260123_121732_0.avi"
    cam0.write_bytes(b"")
    cam1.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(cam0))
    assert result == str(cam1)


def test_find_sibling_on_filesystem_no_sibling(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    cam0 = vid_dir / "surv1_cam0_20260123_121732_0.avi"
    cam0.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(cam0))
    assert result is None


def test_find_sibling_on_filesystem_no_pattern(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    f = vid_dir / "recording.avi"
    f.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(f))
    assert result is None


def test_find_sibling_on_filesystem_ignores_same_cam(tmp_path):
    vid_dir = tmp_path / "videos"
    vid_dir.mkdir()
    cam0a = vid_dir / "surv1_cam0_20260123_121732_0.avi"
    cam0b = vid_dir / "surv1_cam0_20260123_999999_0.avi"
    cam0a.write_bytes(b"")
    cam0b.write_bytes(b"")
    result = _find_sibling_on_filesystem(str(cam0a))
    assert result is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py::test_find_sibling_on_filesystem_finds_cam1 tests/test_core.py::test_find_sibling_on_filesystem_no_sibling tests/test_core.py::test_find_sibling_on_filesystem_no_pattern tests/test_core.py::test_find_sibling_on_filesystem_ignores_same_cam -v
```

Expected: FAIL — `ImportError: cannot import name '_find_sibling_on_filesystem'`

- [ ] **Step 3: Add `_find_sibling_on_filesystem` to `routes.py`**

In `routes.py`, add this function immediately after `_find_sibling_video` (after line 148, before the blank line + `# ── Frame saving`):

```python
def _find_sibling_on_filesystem(video_abs: str) -> "str | None":
    """Find sibling camera video by scanning same directory on filesystem.

    Works for any absolute path, not limited to the DLC project directory.
    """
    vp = Path(video_abs)
    m = re.match(r'^(.+?)_cam(\d+)_(\d{8})', vp.stem)
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

- [ ] **Step 4: Run the four new tests to confirm they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py::test_find_sibling_on_filesystem_finds_cam1 tests/test_core.py::test_find_sibling_on_filesystem_no_sibling tests/test_core.py::test_find_sibling_on_filesystem_no_pattern tests/test_core.py::test_find_sibling_on_filesystem_ignores_same_cam -v
```

Expected: 4 passed.

- [ ] **Step 5: Update `_save_single_frame` to use `_resolve_video_path`**

In `routes.py`, replace lines 181–183:

```python
    video_path = (project_path / video_rel).resolve()
    if not video_path.is_relative_to(project_path.resolve()):
        raise ValueError(f"video_rel escapes project root: {video_rel!r}")
```

With:

```python
    video_path = _resolve_video_path(video_rel, str(project_path))
    if video_path is None:
        raise ValueError(f"video path not allowed: {video_rel!r}")
```

- [ ] **Step 6: Update `/sibling-camera` endpoint**

In `routes.py`, replace lines 342–357 (the entire `get_sibling_camera` function):

```python
@bp.route("/sibling-camera")
def get_sibling_camera():
    with _state_lock:
        proj = _active_project
    video_path = request.args.get("video", "").strip()
    if not video_path or not proj:
        return jsonify({"sibling_video_path": None})

    sibling = _find_sibling_on_filesystem(video_path)
    if sibling:
        return jsonify({"sibling_video_path": sibling})

    vj_path = Path(proj) / "videos.json"
    sibling = None
    if vj_path.exists():
        with open(vj_path) as f:
            videos_json = json.load(f)
        sibling = _find_sibling_video(video_path, videos_json)
    return jsonify({"sibling_video_path": sibling})
```

- [ ] **Step 7: Run full backend test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py -q
```

Expected: 35 passed (31 from Task 1 + 4 new).

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_core.py
git commit -m "feat: accept absolute paths in save-frame, add filesystem sibling detection"
```

---

### Task 3: Frontend HTML + CSS — remove project display, add address bar, fix card width

**Files:**
- Modify: `dlc-3D/src/templates/partials/card_3d_extract.html:13-28`
- Modify: `dlc-3D/src/static/dlc_3d.css:3-7`

**Context:** The `#dlc3d-source-section` currently shows "Project: /full/path" + a Browse button. The full project path is noise — the user only needs to know what directory they're currently browsing. Replace that div with Browse button + path input (both hidden until project loads). The CSS has `max-width: none; width: 100%` on the card which makes it span the full viewport; remove both lines to restore the normal 560px card constraint.

- [ ] **Step 1: Replace `#dlc3d-source-section` contents in HTML**

In `card_3d_extract.html`, replace lines 13–28:

```html
      <!-- ── Source section ── -->
      <div id="dlc3d-source-section">
        <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.35rem">
          <div style="font-size:.75rem;color:var(--text-dim);flex:1">
            Project: <span id="dlc3d-project-display" style="color:var(--text)">—</span>
          </div>
          <button id="dlc3d-browse-btn" class="btn-sm btn-server-pick"
                  style="display:none" title="Browse project files">Browse</button>
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

With:

```html
      <!-- ── Source section ── -->
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

- [ ] **Step 2: Remove card-width overrides from CSS**

In `dlc-3D/src/static/dlc_3d.css`, replace lines 3–7:

```css
/* Card fills full width */
#dlc-3d-extract-card {
  max-width: none;
  width: 100%;
}
```

With:

```css
#dlc-3d-extract-card {
}
```

- [ ] **Step 3: Rebuild container and run full E2E suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose build dlc-3d && docker compose up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/ -v
```

Expected: 9 passed (E2E tests check DOM structure; the `dlc3d-browse-btn` is still present so `test_browse_btn_hidden_without_project` still passes).

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/templates/partials/card_3d_extract.html dlc-3D/src/static/dlc_3d.css
git commit -m "feat: remove project path display, add editable path input, restore normal card width"
```

---

### Task 4: Frontend JS — absolute paths, address bar wiring, browser persistence

**Files:**
- Modify: `dlc-3D/src/static/dlc_3d.js`

**Context:** `dlc_3d.js` currently stores relative video paths (`row.dataset.videoRel`) computed by slicing off `_projectPath`. When browsing outside the project, the slice produces a garbage string. The fix is to store and pass absolute paths throughout. Summary of all changes:

1. Rename `_sessionKeyFromVideoRel` → `_sessionKeyFromVideoPath` (body is unchanged — still operates on the filename stem)
2. `_resetExtractorUI`: remove `dlc3d-project-display` reset; add hide for `dlc3d-path-input`
3. `_loadProject`: remove `dlc3d-project-display` line (element no longer in HTML)
4. `_browseDir`: store absolute path on `row.dataset.videoPath`; update `#dlc3d-path-input` after each navigation; click handler passes absolute path to `_selectVideo`
5. `_selectVideo(videoPath)`: rename param from `videoRel`; match active row on `dataset.videoPath`; hide `dlc3d-path-input` on collapse; call `_sessionKeyFromVideoPath`
6. Browse button toggle: use `_browserCurrentPath || _projectPath` so browser reopens at last visited directory
7. New `keydown` listener on `#dlc3d-path-input` — Enter key calls `_browseDir(input.value.trim())`

- [ ] **Step 1: Rename `_sessionKeyFromVideoRel` → `_sessionKeyFromVideoPath`**

In `dlc_3d.js`, replace line 26:

```javascript
function _sessionKeyFromVideoRel(videoRel) {
  const parts = videoRel.split("/");
```

With:

```javascript
function _sessionKeyFromVideoPath(videoPath) {
  const parts = videoPath.split("/");
```

- [ ] **Step 2: Update `_resetExtractorUI` — remove project-display reset, add path-input hide**

In `dlc_3d.js`, replace lines 54–57:

```javascript
  const display = document.getElementById("dlc3d-project-display");
  if (display) display.textContent = "—";
  const browseBtn = document.getElementById("dlc3d-browse-btn");
  if (browseBtn) browseBtn.style.display = "none";
```

With:

```javascript
  const browseBtn = document.getElementById("dlc3d-browse-btn");
  if (browseBtn) browseBtn.style.display = "none";
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) { pathInput.style.display = "none"; pathInput.value = ""; }
```

- [ ] **Step 3: Update `_loadProject` — remove project-display line**

In `dlc_3d.js`, replace lines 96–99:

```javascript
  _projectPath = data.project_path;
  document.getElementById("dlc3d-project-display").textContent = _projectPath;
  document.getElementById("dlc3d-browse-btn").style.display = "";
  _setStatus("");
```

With:

```javascript
  _projectPath = data.project_path;
  document.getElementById("dlc3d-browse-btn").style.display = "";
  _setStatus("");
```

- [ ] **Step 4: Update `_browseDir` — absolute paths, path input, click handler**

In `dlc_3d.js`, replace the `_browseDir` function body starting at line 130 (`_browserCurrentPath = data.path;`) through the closing of the `else if (entry.type === "file")` block.

Replace lines 130–162:

```javascript
  _browserCurrentPath = data.path;
  browser.innerHTML = "";

  if (data.parent) {
    const upRow = document.createElement("div");
    upRow.className = "fe-video-item";
    const upSpan = document.createElement("span");
    upSpan.textContent = "↑  ..";
    upSpan.style.cssText = "color:var(--text-dim);font-style:italic";
    upRow.appendChild(upSpan);
    upRow.addEventListener("click", () => _browseDir(data.parent));
    browser.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    row.className = "fe-video-item";

    const icon = document.createElement("span");
    const name = document.createElement("span");
    name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    name.textContent = entry.name;

    if (entry.type === "dir") {
      icon.textContent = "📁 ";
      row.append(icon, name);
      row.addEventListener("click", () => _browseDir(_browserCurrentPath + "/" + entry.name));
    } else if (entry.type === "file") {
      icon.textContent = "🎬 ";
      row.dataset.videoRel = (_browserCurrentPath + "/" + entry.name).slice(_projectPath.length + 1);
      row.append(icon, name);
      row.addEventListener("click", () => _selectVideo(row.dataset.videoRel));
    } else {
      continue;
    }
    browser.appendChild(row);
  }
```

With:

```javascript
  _browserCurrentPath = data.path;
  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) pathInput.value = data.path;
  browser.innerHTML = "";

  if (data.parent) {
    const upRow = document.createElement("div");
    upRow.className = "fe-video-item";
    const upSpan = document.createElement("span");
    upSpan.textContent = "↑  ..";
    upSpan.style.cssText = "color:var(--text-dim);font-style:italic";
    upRow.appendChild(upSpan);
    upRow.addEventListener("click", () => _browseDir(data.parent));
    browser.appendChild(upRow);
  }

  for (const entry of data.entries || []) {
    const row = document.createElement("div");
    row.className = "fe-video-item";

    const icon = document.createElement("span");
    const name = document.createElement("span");
    name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
    name.textContent = entry.name;

    if (entry.type === "dir") {
      icon.textContent = "📁 ";
      row.append(icon, name);
      row.addEventListener("click", () => _browseDir(_browserCurrentPath + "/" + entry.name));
    } else if (entry.type === "file") {
      icon.textContent = "🎬 ";
      row.dataset.videoPath = _browserCurrentPath + "/" + entry.name;
      row.append(icon, name);
      row.addEventListener("click", () => _selectVideo(row.dataset.videoPath));
    } else {
      continue;
    }
    browser.appendChild(row);
  }
```

- [ ] **Step 5: Update `_selectVideo` — rename param, absolute path, hide path input**

In `dlc_3d.js`, replace lines 178–213 (the entire `_selectVideo` function):

```javascript
async function _selectVideo(videoPath) {
  _activeVideo   = videoPath;
  _activeSession = _sessionKeyFromVideoPath(videoPath);

  document.querySelectorAll("#dlc3d-file-browser .fe-video-item").forEach(el => {
    el.classList.toggle("active", el.dataset.videoPath === videoPath);
  });

  const empty = document.getElementById("dlc3d-session-empty");
  if (empty) empty.style.display = "none";

  const browser = document.getElementById("dlc3d-file-browser");
  if (browser) browser.style.display = "none";

  const pathInput = document.getElementById("dlc3d-path-input");
  if (pathInput) pathInput.style.display = "none";

  document.getElementById("dlc3d-player-section").style.display = "";

  const camIdx = videoPath.match(/_cam(\d+)_/)?.[1] ?? "?";
  document.getElementById("cam1-label").textContent = `Camera ${camIdx} (primary)`;

  let siblingPath = null;
  try {
    const sr = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(videoPath)}`);
    if (sr.ok) {
      const sd = await sr.json();
      siblingPath = sd.sibling_video_path || null;
    }
  } catch (e) { console.warn("[dlc_3d] sibling-camera fetch failed:", e); }

  if (siblingPath) {
    const sibCamIdx = siblingPath.match(/_cam(\d+)_/)?.[1] ?? "?";
    document.getElementById("cam2-label").textContent = `Camera ${sibCamIdx} (sibling)`;
  }

  _setStatus("");
  await openPlayer(videoPath, siblingPath);
  _refreshLabeledFrames();
}
```

- [ ] **Step 6: Update Browse button toggle to persist last directory**

In `dlc_3d.js`, replace lines 303–312 (the `dlc3d-browse-btn` click listener):

```javascript
  document.getElementById("dlc3d-browse-btn")?.addEventListener("click", () => {
    const browser = document.getElementById("dlc3d-file-browser");
    if (browser.style.display === "none") {
      _browseDir(_projectPath);
    } else {
      browser.style.display = "none";
      const empty = document.getElementById("dlc3d-session-empty");
      if (empty) empty.style.display = "";
    }
  });
```

With:

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

- [ ] **Step 7: Add path input Enter key listener**

In `dlc_3d.js`, add after the Browse button listener (after its closing `});` and before the `const activePathEl` block):

```javascript
  document.getElementById("dlc3d-path-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const v = e.target.value.trim();
      if (v) _browseDir(v);
    }
  });

```

- [ ] **Step 8: Run backend tests to confirm nothing broken**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/test_core.py -q
```

Expected: 35 passed.

- [ ] **Step 9: Rebuild and run full E2E suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose build dlc-3d && docker compose up -d dlc-3d
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/e2e/ -v
```

Expected: 9 passed.

- [ ] **Step 10: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.js
git commit -m "feat: absolute paths in file browser, editable address bar, persistent browse directory"
```
