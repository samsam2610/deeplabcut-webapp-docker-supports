# Global Template Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a named, persisted global template library system to clip-cutter, with batch init, batch scan using max-similarity across multiple template sources, and a reworked compact template viewer.

**Architecture:** All changes extend five existing files (`config.py`, `processor.py`, `routes.py`, `clip_cutter.html`, `clip_cutter.js`). The library registry is a JSON file on the Cloud mount. Batch operations use SSE streams matching the existing scan pattern. Multi-template scanning stacks mean embeddings into a matrix and takes max similarity per frame.

**Tech Stack:** Flask (Python), vanilla JS, HTML5, pytest, numpy (matrix dot product for multi-template similarity).

---

## File Map

| File | Changes |
|------|---------|
| `clip-cutter/config.py` | Add `LIBRARIES_PATH` |
| `clip-cutter/processor.py` | Add `load_combined_template`, `get_similarity_curve_multi`, `fine_scan_multi`, `scan_video_multi_template` |
| `clip-cutter/routes.py` | Add `_libraries_lock`, `_load_libraries`, `_save_libraries`; 5 library CRUD routes; `POST /batch-init`, `GET /batch-init/stream`; `POST /batch-scan`, `GET /batch-scan/stream` |
| `clip-cutter/templates/clip_cutter.html` | Rework template viewer CSS+HTML; add sidebar tabs, library panel, batch toolbar buttons |
| `clip-cutter/static/clip_cutter.js` | Update `renderTemplate()`; add tab switching, library UI rendering; batch mode state + `renderBrowser` update; batch init + scan handlers |
| `clip-cutter/tests/test_routes.py` | Library CRUD tests; batch init smoke test; batch scan smoke test |
| `clip-cutter/tests/test_processor.py` | `load_combined_template` tests; `scan_video_multi_template` similarity test |

---

## Task 1: Template Viewer Rework

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html` (CSS lines 42–46, HTML line 352)
- Modify: `clip-cutter/static/clip_cutter.js` (renderTemplate, initTemplate)

No backend changes. No new tests (pure rendering).

- [ ] **Step 1: Replace thumbnail CSS with list-row CSS in `clip_cutter.html`**

Find and replace the four `.thumb` rules and update the grid/list rule. Also update the collapsed sidebar selector. The existing lines 42–46 in the `<style>` block currently read:

```css
#template-grid { padding: 5px; display: flex; flex-wrap: wrap; gap: 3px; overflow-y: auto; flex: 1; }
.thumb { width: 50px; height: 38px; background: #1c2128; border-radius: 3px; border: 1px solid #30363d; cursor: pointer; position: relative; overflow: hidden; }
.thumb:hover { border-color: #f85149; }
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-label { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.65); font-size: 7px; color: #ccc; text-align: center; padding: 1px; }
```

Replace those five lines with:

```css
#template-list { overflow-y: auto; flex: 1; }
.tpl-row { display: flex; align-items: center; gap: 4px; padding: 5px 8px; border-bottom: 1px solid #21262d; }
.tpl-row:last-child { border-bottom: none; }
.tpl-label { flex: 1; font-size: 10px; color: #cdd9e5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tpl-view-btn, .tpl-del-btn { flex-shrink: 0; padding: 2px 6px; font-size: 10px; }
```

Also update the collapsed-sidebar rule (currently on line 23) from `#template-grid` to `#template-list`:

```css
.sidebar.collapsed #template-list,
```

- [ ] **Step 2: Replace `#template-grid` div with `#template-list` in HTML**

Find in the HTML body (currently line 352):

```html
    <div id="template-grid" style="display:none;padding:8px;flex-wrap:wrap;gap:5px;overflow-y:auto;flex:1;"></div>
```

Replace with:

```html
    <div id="template-list" style="display:none;overflow-y:auto;flex:1;"></div>
```

- [ ] **Step 3: Update `renderTemplate()` in `clip_cutter.js`**

The function currently references `template-grid` and renders `.thumb` divs. Replace the entire function with:

```javascript
function renderTemplate(data) {
  const emptyState = document.getElementById("sidebar-empty-state");
  const noTemplate = document.getElementById("sidebar-no-template");
  const noTemplateMsg = document.getElementById("sidebar-no-template-msg");
  const list = document.getElementById("template-list");
  const footer = document.getElementById("template-footer");
  const initBtn = document.getElementById("sidebar-init-btn");
  const sidebarActions = document.getElementById("sidebar-actions");
  const frameCount = document.getElementById("sidebar-frame-count");

  if (!_selectedVideoStem) {
    emptyState.style.display = "";
    noTemplate.style.display = "none";
    list.style.display = "none";
    footer.style.display = "none";
    initBtn.style.display = "none";
    sidebarActions.style.display = "none";
    frameCount.textContent = "";
    return;
  }

  emptyState.style.display = "none";
  initBtn.style.display = "";

  if (!data.has_template) {
    noTemplate.style.display = "";
    noTemplateMsg.textContent = `No template for ${_selectedVideoStem}`;
    list.style.display = "none";
    footer.style.display = "none";
    sidebarActions.style.display = "none";
    frameCount.textContent = "";
    return;
  }

  noTemplate.style.display = "none";
  list.style.display = "";
  footer.style.display = "";
  sidebarActions.style.display = "flex";
  frameCount.textContent = `${data.count} fr`;

  list.innerHTML = "";
  data.frames.forEach((f, idx) => {
    const stem = f.video_path.split("/").pop().replace(/\.avi$/i, "");
    const label = `${stem} · fr${f.frame_number}`;
    const row = document.createElement("div");
    row.className = "tpl-row";
    row.innerHTML = `
      <span class="tpl-label" title="${f.video_path} · fr${f.frame_number}">${label}</span>
      <button class="player-btn tpl-view-btn" title="View frame">&#8599;</button>
      <button class="player-btn tpl-del-btn" title="Remove">&#10005;</button>
    `;
    row.querySelector(".tpl-view-btn").addEventListener("click", () => {
      window.open(
        `/clip-cutter/frame?video=${encodeURIComponent(f.video_path)}&n=${f.frame_number - 1}`,
        "_blank"
      );
    });
    row.querySelector(".tpl-del-btn").addEventListener("click", () => removeTemplateFrame(idx));
    list.appendChild(row);
  });
  footer.textContent = `${data.count} frame${data.count !== 1 ? "s" : ""} loaded`;
}
```

- [ ] **Step 4: Fix `initTemplate()` reference to `template-grid`**

In `clip_cutter.js`, `initTemplate()` checks `document.getElementById("template-grid").style.display !== "none"`. Update that one reference:

```javascript
async function initTemplate() {
  if (document.getElementById("template-list").style.display !== "none") {
```

- [ ] **Step 5: Verify tests still pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -q --tb=short
```

Expected: 138 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/clip_cutter.js
git commit -m "feat: replace template thumbnail grid with compact filename list"
```

---

## Task 2: Config + Library Persistence Helpers

**Files:**
- Modify: `clip-cutter/config.py`
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write failing tests for `_load_libraries` and `_save_libraries`**

Add to `tests/test_routes.py` after the existing fixtures:

```python
def test_load_libraries_returns_empty_when_missing(tmp_path, monkeypatch):
    import config
    import routes
    monkeypatch.setattr(config, "LIBRARIES_PATH", tmp_path / "libraries.json")
    assert routes._load_libraries() == {}


def test_save_and_load_libraries_roundtrip(tmp_path, monkeypatch):
    import config
    import routes
    monkeypatch.setattr(config, "LIBRARIES_PATH", tmp_path / "libraries.json")
    libs = {"TestLib": ["/user-data/session1", "/user-data/session2"]}
    routes._save_libraries(libs)
    assert routes._load_libraries() == libs
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py::test_load_libraries_returns_empty_when_missing tests/test_routes.py::test_save_and_load_libraries_roundtrip -v
```

Expected: FAIL — `AttributeError: module 'routes' has no attribute '_load_libraries'`

- [ ] **Step 3: Add `LIBRARIES_PATH` to `config.py`**

Add after the `DETECTIONS_DIR` block:

```python
LIBRARIES_PATH = Path(
    os.environ.get(
        "CLIP_CUTTER_LIBRARIES_PATH",
        str(_DATA_ROOT / "Reaching-Task-Data/clip-cutter/libraries.json"),
    )
)
```

- [ ] **Step 4: Add lock + helpers to `routes.py`**

Add after `_state_lock = threading.Lock()` (around line 33):

```python
_libraries_lock = threading.Lock()


def _load_libraries() -> dict:
    """Load libraries.json; return {} if absent or malformed."""
    p = config.LIBRARIES_PATH
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_libraries(libs: dict) -> None:
    config.LIBRARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.LIBRARIES_PATH, "w") as f:
        json.dump(libs, f, indent=2)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_routes.py::test_load_libraries_returns_empty_when_missing tests/test_routes.py::test_save_and_load_libraries_roundtrip -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/config.py clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add LIBRARIES_PATH config and library persistence helpers"
```

---

## Task 3: Library CRUD Routes

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`

- [ ] **Step 1: Write failing tests for library CRUD**

Add to `tests/test_routes.py`:

```python
@pytest.fixture
def lib_client(tmp_path, monkeypatch):
    """Flask test client with patched LIBRARIES_PATH."""
    import config
    import processor
    monkeypatch.setattr(config, "LIBRARIES_PATH", tmp_path / "libraries.json")
    monkeypatch.setattr(config, "TEMPLATE_STATE_PATH", tmp_path / "state.json")
    rng = np.random.default_rng(42)
    class FakeModel:
        def encode(self, images, convert_to_numpy=True, batch_size=64, show_progress_bar=False):
            n = len(images) if isinstance(images, list) else 1
            arr = rng.random((n, 512)).astype(np.float32)
            return arr[0] if n == 1 else arr
    monkeypatch.setattr(processor, "_model", FakeModel())
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_global_libraries_empty_on_start(lib_client):
    resp = lib_client.get("/clip-cutter/global-libraries")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["libraries"] == {}


def test_create_library(lib_client):
    resp = lib_client.post("/clip-cutter/global-libraries", json={"name": "TestLib"})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["ok"] is True
    resp2 = lib_client.get("/clip-cutter/global-libraries")
    assert "TestLib" in json.loads(resp2.data)["libraries"]


def test_create_library_duplicate_returns_422(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "TestLib"})
    resp = lib_client.post("/clip-cutter/global-libraries", json={"name": "TestLib"})
    assert resp.status_code == 422


def test_create_library_empty_name_returns_422(lib_client):
    resp = lib_client.post("/clip-cutter/global-libraries", json={"name": ""})
    assert resp.status_code == 422


def test_delete_library(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "ToDelete"})
    resp = lib_client.delete("/clip-cutter/global-libraries/ToDelete")
    assert resp.status_code == 200
    data = json.loads(lib_client.get("/clip-cutter/global-libraries").data)
    assert "ToDelete" not in data["libraries"]


def test_delete_missing_library_returns_404(lib_client):
    resp = lib_client.delete("/clip-cutter/global-libraries/NoSuchLib")
    assert resp.status_code == 404


def test_add_folder_to_library(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    resp = lib_client.post(
        "/clip-cutter/global-libraries/Lib/folders",
        json={"path": "/user-data/session1"},
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["count"] == 1
    libs = json.loads(lib_client.get("/clip-cutter/global-libraries").data)["libraries"]
    assert "/user-data/session1" in libs["Lib"]


def test_add_duplicate_folder_returns_422(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    lib_client.post("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    resp = lib_client.post("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    assert resp.status_code == 422


def test_remove_folder_from_library(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    lib_client.post("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    resp = lib_client.delete("/clip-cutter/global-libraries/Lib/folders", json={"path": "/p"})
    assert resp.status_code == 200
    libs = json.loads(lib_client.get("/clip-cutter/global-libraries").data)["libraries"]
    assert "/p" not in libs["Lib"]


def test_remove_missing_folder_returns_404(lib_client):
    lib_client.post("/clip-cutter/global-libraries", json={"name": "Lib"})
    resp = lib_client.delete("/clip-cutter/global-libraries/Lib/folders", json={"path": "/nope"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_routes.py -k "global_libraries or add_folder or remove_folder or create_library or delete_library" -v
```

Expected: FAIL — 404 (routes not yet defined).

- [ ] **Step 3: Add library CRUD routes to `routes.py`**

Add after the `clear_template` route (around line 125), before `_init_status`:

```python
# ── Global template library ───────────────────────────────────────────────────

@bp.route("/global-libraries", methods=["GET"])
def get_libraries():
    with _libraries_lock:
        libs = _load_libraries()
    return jsonify({"libraries": libs})


@bp.route("/global-libraries", methods=["POST"])
def create_library():
    name = (request.get_json(force=True) or {}).get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 422
    with _libraries_lock:
        libs = _load_libraries()
        if name in libs:
            return jsonify({"error": "library already exists"}), 422
        libs[name] = []
        _save_libraries(libs)
    return jsonify({"ok": True})


@bp.route("/global-libraries/<name>", methods=["DELETE"])
def delete_library(name):
    with _libraries_lock:
        libs = _load_libraries()
        if name not in libs:
            return jsonify({"error": "not found"}), 404
        del libs[name]
        _save_libraries(libs)
    return jsonify({"ok": True})


@bp.route("/global-libraries/<name>/folders", methods=["POST"])
def add_library_folder(name):
    path = (request.get_json(force=True) or {}).get("path", "").strip()
    if not path:
        return jsonify({"error": "path required"}), 422
    with _libraries_lock:
        libs = _load_libraries()
        if name not in libs:
            return jsonify({"error": "library not found"}), 404
        if path in libs[name]:
            return jsonify({"error": "path already in library"}), 422
        libs[name].append(path)
        _save_libraries(libs)
    return jsonify({"ok": True, "count": len(libs[name])})


@bp.route("/global-libraries/<name>/folders", methods=["DELETE"])
def remove_library_folder(name):
    path = (request.get_json(force=True) or {}).get("path", "").strip()
    with _libraries_lock:
        libs = _load_libraries()
        if name not in libs:
            return jsonify({"error": "library not found"}), 404
        if path not in libs[name]:
            return jsonify({"error": "path not in library"}), 404
        libs[name].remove(path)
        _save_libraries(libs)
    return jsonify({"ok": True, "count": len(libs[name])})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_routes.py -k "global_libraries or add_folder or remove_folder or create_library or delete_library" -v
```

Expected: 10 passed.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat: add global library CRUD routes (GET/POST/DELETE)"
```

---

## Task 4: Library Sidebar Tab (HTML + JS)

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`
- Modify: `clip-cutter/static/clip_cutter.js`

No new backend. No new tests (UI rendering).

- [ ] **Step 1: Add CSS for sidebar tabs and library panel in `clip_cutter.html`**

Add after the `#sidebar-frame-count` rule (after line 47):

```css
/* ── Sidebar tabs ───────────────────────────────────────────────────────────── */
#sidebar-tabs { display: flex; gap: 2px; margin: 0 6px; }
.sidebar-tab { font-size: 9px; padding: 2px 7px; border-radius: 3px; cursor: pointer;
               border: 1px solid #30363d; background: transparent; color: #768390; }
.sidebar-tab.active { border-color: #388bfd; color: #388bfd; }
/* ── Library panel ──────────────────────────────────────────────────────────── */
#libraries-panel { display: none; flex-direction: column; flex: 1; overflow: hidden; }
#lib-header { padding: 5px 8px; border-bottom: 1px solid #30363d; display: flex; gap: 4px; flex-shrink: 0; }
#lib-new-name { flex: 1; font-size: 10px; padding: 2px 6px; background: #0d1117;
                border: 1px solid #30363d; border-radius: 3px; color: #cdd9e5; }
#lib-list { overflow-y: auto; flex: 1; }
.lib-card { border-bottom: 1px solid #21262d; }
.lib-card-header { display: flex; align-items: center; gap: 4px; padding: 5px 8px;
                   cursor: pointer; user-select: none; }
.lib-card-header:hover { background: #1c2128; }
.lib-name { flex: 1; font-size: 10px; color: #cdd9e5; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap; }
.lib-folder-count { font-size: 9px; color: #768390; flex-shrink: 0; }
.lib-delete-btn { flex-shrink: 0; padding: 1px 5px; font-size: 9px; }
.lib-card-body { padding: 4px 8px 6px; display: none; }
.lib-card-body.open { display: block; }
.lib-folder-row { display: flex; align-items: center; gap: 4px; padding: 2px 0; }
.lib-folder-label { flex: 1; font-size: 9px; color: #768390; overflow: hidden;
                    text-overflow: ellipsis; white-space: nowrap; }
.lib-folder-remove { flex-shrink: 0; padding: 1px 4px; font-size: 9px; }
.lib-scan-btn { width: 100%; margin-top: 5px; font-size: 9px; padding: 3px 0; }
```

Also add to collapsed sidebar rules:

```css
.sidebar.collapsed #libraries-panel,
.sidebar.collapsed #sidebar-tabs { display: none !important; }
```

- [ ] **Step 2: Add sidebar tabs + libraries panel HTML**

In the sidebar HTML, replace the existing `.sidebar-header` div:

```html
    <div class="sidebar-header">
      <span class="sidebar-title">Template Bank</span>
      <span id="sidebar-frame-count"></span>
      <div id="sidebar-tabs">
        <button class="sidebar-tab active" id="tab-template">Template</button>
        <button class="sidebar-tab" id="tab-libraries">Libraries</button>
      </div>
      <button class="btn-sm btn-green" id="sidebar-init-btn" style="display:none;" title="Init template from this video">&#8635; Init</button>
      <button class="btn-sm" id="sidebar-toggle" title="Collapse sidebar">&#9660;</button>
    </div>
```

After the `#sidebar-actions` div and before `#sidebar-resize-handle`, add:

```html
    <div id="libraries-panel">
      <div id="lib-header">
        <input id="lib-new-name" placeholder="New library name…">
        <button class="player-btn" id="lib-new-btn">+ New</button>
      </div>
      <div id="lib-list"></div>
    </div>
```

- [ ] **Step 3: Add JS module state for active library**

Add at the top of `clip_cutter.js`, after the existing module-level `let` declarations:

```javascript
let _activeBatchLibrary = null;   // name of expanded library card
let _activeBatchFolders = new Set();  // checked folder paths in expanded library
```

- [ ] **Step 4: Add tab-switching JS in `clip_cutter.js`**

Add inside the `DOMContentLoaded` block (at the end, before the closing `}`):

```javascript
// ── Sidebar tabs ──────────────────────────────────────────────────────────────
const tabTemplate  = document.getElementById("tab-template");
const tabLibraries = document.getElementById("tab-libraries");
const templateBody = [
  "sidebar-empty-state", "sidebar-no-template", "template-list",
  "template-footer", "sidebar-actions",
].map(id => document.getElementById(id));
const librariesPanel = document.getElementById("libraries-panel");
const initBtn = document.getElementById("sidebar-init-btn");

function showTemplateTab() {
  tabTemplate.classList.add("active");
  tabLibraries.classList.remove("active");
  librariesPanel.style.display = "none";
  initBtn.style.display = _selectedVideoStem ? "" : "none";
  loadTemplate();
}

function showLibrariesTab() {
  tabLibraries.classList.add("active");
  tabTemplate.classList.remove("active");
  templateBody.forEach(el => { if (el) el.style.display = "none"; });
  initBtn.style.display = "none";
  librariesPanel.style.display = "flex";
  loadLibraries();
}

tabTemplate.addEventListener("click", showTemplateTab);
tabLibraries.addEventListener("click", showLibrariesTab);
```

- [ ] **Step 5: Add `loadLibraries()` and library card rendering JS**

Add in `clip_cutter.js` before the `DOMContentLoaded` block:

```javascript
// ── Global libraries ──────────────────────────────────────────────────────────

async function loadLibraries() {
  const resp = await fetch("/clip-cutter/global-libraries");
  if (!resp.ok) { setStatus("Failed to load libraries"); return; }
  const { libraries } = await resp.json();
  renderLibraries(libraries);
}

function renderLibraries(libraries) {
  const list = document.getElementById("lib-list");
  list.innerHTML = "";
  for (const [name, folders] of Object.entries(libraries)) {
    const card = document.createElement("div");
    card.className = "lib-card";
    const isActive = name === _activeBatchLibrary;
    card.innerHTML = `
      <div class="lib-card-header">
        <span class="lib-name" title="${name}">${name}</span>
        <span class="lib-folder-count">${folders.length} folder${folders.length !== 1 ? "s" : ""}</span>
        <button class="player-btn lib-delete-btn" title="Delete library">&#10005;</button>
      </div>
      <div class="lib-card-body${isActive ? " open" : ""}">
        ${folders.map(p => {
          const label = p.split("/").pop();
          const checked = _activeBatchFolders.has(p);
          return `<div class="lib-folder-row">
            <input type="checkbox" class="lib-folder-check" data-path="${p}" ${checked ? "checked" : ""}>
            <span class="lib-folder-label" title="${p}">${label}</span>
            <button class="player-btn lib-folder-remove" data-path="${p}" title="Remove folder">&#10005;</button>
          </div>`;
        }).join("")}
        <button class="player-btn lib-scan-btn" disabled>&#9654; Scan with checked (${
          folders.filter(p => _activeBatchFolders.has(p)).length
        })</button>
      </div>
    `;

    // Header click: expand/collapse
    card.querySelector(".lib-card-header").addEventListener("click", (e) => {
      if (e.target.closest(".lib-delete-btn")) return;
      const body = card.querySelector(".lib-card-body");
      const opening = !body.classList.contains("open");
      // Collapse all
      document.querySelectorAll(".lib-card-body.open").forEach(b => b.classList.remove("open"));
      if (opening) {
        body.classList.add("open");
        _activeBatchLibrary = name;
        _activeBatchFolders = new Set(
          [...body.querySelectorAll(".lib-folder-check:checked")].map(cb => cb.dataset.path)
        );
      } else {
        _activeBatchLibrary = null;
        _activeBatchFolders = new Set();
      }
      updateBatchScanBtn();
    });

    // Delete library
    card.querySelector(".lib-delete-btn").addEventListener("click", async () => {
      if (!confirm(`Delete library "${name}"?`)) return;
      await fetch(`/clip-cutter/global-libraries/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (_activeBatchLibrary === name) { _activeBatchLibrary = null; _activeBatchFolders = new Set(); }
      await loadLibraries();
    });

    // Folder checkboxes
    card.querySelectorAll(".lib-folder-check").forEach(cb => {
      cb.addEventListener("change", () => {
        if (cb.checked) _activeBatchFolders.add(cb.dataset.path);
        else _activeBatchFolders.delete(cb.dataset.path);
        const scanBtn = card.querySelector(".lib-scan-btn");
        scanBtn.textContent = `▶ Scan with checked (${_activeBatchFolders.size})`;
        updateBatchScanBtn();
      });
    });

    // Remove folder buttons
    card.querySelectorAll(".lib-folder-remove").forEach(btn => {
      btn.addEventListener("click", async () => {
        const p = btn.dataset.path;
        await fetch(`/clip-cutter/global-libraries/${encodeURIComponent(name)}/folders`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: p }),
        });
        _activeBatchFolders.delete(p);
        await loadLibraries();
      });
    });

    // Scan button
    card.querySelector(".lib-scan-btn").addEventListener("click", () => startBatchScan());

    list.appendChild(card);
  }
}

function updateBatchScanBtn() {
  document.querySelectorAll(".lib-scan-btn").forEach(btn => {
    btn.disabled = _activeBatchFolders.size === 0 || _batchQueue.size === 0;
  });
}
```

- [ ] **Step 6: Wire `[+ New]` button in `DOMContentLoaded`**

Add inside the `DOMContentLoaded` block:

```javascript
document.getElementById("lib-new-btn").addEventListener("click", async () => {
  const name = document.getElementById("lib-new-name").value.trim();
  if (!name) return;
  const resp = await fetch("/clip-cutter/global-libraries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (resp.ok) {
    document.getElementById("lib-new-name").value = "";
    await loadLibraries();
  } else {
    const err = await resp.json();
    setStatus("Error: " + err.error);
  }
});
```

- [ ] **Step 7: Run full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/clip_cutter.js
git commit -m "feat: add Libraries sidebar tab with CRUD UI"
```

---

## Task 5: Batch Mode Checkbox Queue in Browser

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Add batch toolbar CSS + HTML in `clip_cutter.html`**

Add CSS after the `.browser-row.selected` rule:

```css
/* ── Batch mode ─────────────────────────────────────────────────────────────── */
#batch-toggle.active { border-color: #f0c040; color: #f0c040; }
#batch-count { font-size: 10px; color: #768390; }
.browser-row-checkbox { flex-shrink: 0; accent-color: #388bfd; }
```

In the browser toolbar HTML (find `<div class="browser-toolbar">`), add the new buttons after the Up button:

```html
      <button class="player-btn" id="batch-toggle" title="Toggle batch selection">&#9744; Batch</button>
      <span id="batch-count" style="display:none;"></span>
      <button class="player-btn" id="batch-init-btn" style="display:none;" title="Batch init templates">&#9889; Init</button>
      <button class="player-btn" id="batch-add-folder-btn" style="display:none;" title="Add current folder to selected library">+ Lib</button>
```

- [ ] **Step 2: Add batch mode JS state and toggle logic in `clip_cutter.js`**

Add module-level state after `_activeBatchFolders`:

```javascript
let _batchMode = false;
const _batchQueue = new Set();  // full video_path strings, persists across navigation
```

Add `updateBatchToolbar()` function before the `DOMContentLoaded` block:

```javascript
function updateBatchToolbar() {
  const countEl  = document.getElementById("batch-count");
  const initBtn  = document.getElementById("batch-init-btn");
  const addFolderBtn = document.getElementById("batch-add-folder-btn");
  const toggleBtn = document.getElementById("batch-toggle");
  toggleBtn.classList.toggle("active", _batchMode);
  if (_batchMode && _batchQueue.size > 0) {
    countEl.style.display = "";
    countEl.textContent = `(${_batchQueue.size} selected)`;
    initBtn.style.display = "";
  } else {
    countEl.style.display = "none";
    initBtn.style.display = "none";
  }
  addFolderBtn.style.display = (_batchMode && _activeBatchLibrary !== null) ? "" : "none";
  updateBatchScanBtn();
}
```

- [ ] **Step 3: Wire batch toggle button in `DOMContentLoaded`**

Add inside `DOMContentLoaded`:

```javascript
document.getElementById("batch-toggle").addEventListener("click", () => {
  _batchMode = !_batchMode;
  updateBatchToolbar();
  if (_browserCurrentPath) loadFolder(_browserCurrentPath);
});

document.getElementById("batch-add-folder-btn").addEventListener("click", async () => {
  if (!_activeBatchLibrary || !_browserCurrentPath) return;
  const resp = await fetch(
    `/clip-cutter/global-libraries/${encodeURIComponent(_activeBatchLibrary)}/folders`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: _browserCurrentPath }),
    }
  );
  if (resp.ok) {
    setStatus(`Added "${_browserCurrentPath.split("/").pop()}" to ${_activeBatchLibrary}`);
    await loadLibraries();
  } else {
    const err = await resp.json();
    setStatus("Error: " + err.error);
  }
});
```

- [ ] **Step 4: Update `renderBrowser()` in `clip_cutter.js` to show checkboxes in batch mode**

Find the `else` branch that handles `.avi` file rows (currently starting with `icon.textContent = "▶"`). Replace the entire `else` block with:

```javascript
    } else {
      icon.textContent = "▶";
      const badge = document.createElement("span");
      badge.className = `badge ${entry.done ? "badge-done" : "badge-pending"}`;
      badge.textContent = entry.done ? "done" : "ready";
      row.appendChild(badge);

      if (_batchMode) {
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.className = "browser-row-checkbox";
        cb.checked = _batchQueue.has(videoPath);
        cb.addEventListener("change", (e) => {
          e.stopPropagation();
          if (cb.checked) _batchQueue.add(videoPath);
          else _batchQueue.delete(videoPath);
          updateBatchToolbar();
        });
        row.insertBefore(cb, icon);
        row.addEventListener("click", (e) => {
          if (e.target === cb) return;
          cb.checked = !cb.checked;
          if (cb.checked) _batchQueue.add(videoPath);
          else _batchQueue.delete(videoPath);
          updateBatchToolbar();
        });
      } else {
        row.addEventListener("click", () => {
          document.querySelectorAll(".browser-row.selected").forEach((r) =>
            r.classList.remove("selected")
          );
          row.classList.add("selected");
          selectVideo(videoPath, stem, data.path);
        });
      }
    }
```

Note: `videoPath` and `stem` are already defined earlier in the same `forEach` callback as:
```javascript
const videoPath = data.path + "/" + entry.name;
const stem = entry.name.replace(/\.avi$/i, "");
```

- [ ] **Step 5: Run full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html clip-cutter/static/clip_cutter.js
git commit -m "feat: add batch mode checkbox queue in file browser"
```

---

## Task 6: Batch Init Route + Frontend

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Write failing tests for batch init**

Add to `tests/test_routes.py`:

```python
def test_batch_init_requires_videos(lib_client):
    resp = lib_client.post("/clip-cutter/batch-init", json={"videos": []})
    assert resp.status_code == 400


def test_batch_init_returns_job_id(lib_client, monkeypatch, tmp_path):
    import processor
    monkeypatch.setattr(
        processor, "init_template_from_clips_dir",
        lambda clips_dir, state_path, crop=None: {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    )
    resp = lib_client.post(
        "/clip-cutter/batch-init",
        json={"videos": [str(tmp_path / "myvid.avi")]},
    )
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "job_id" in data


def test_batch_init_stream_returns_done(lib_client, monkeypatch, tmp_path):
    import processor, routes
    monkeypatch.setattr(
        processor, "init_template_from_clips_dir",
        lambda clips_dir, state_path, crop=None: {"frames": [], "mean_embedding": None, "dino_mean_embedding": None}
    )
    resp = lib_client.post(
        "/clip-cutter/batch-init",
        json={"videos": [str(tmp_path / "myvid.avi")]},
    )
    job_id = json.loads(resp.data)["job_id"]
    import time
    time.sleep(0.2)
    stream_resp = lib_client.get(f"/clip-cutter/batch-init/stream?job_id={job_id}")
    # Read one SSE event
    raw = stream_resp.data.decode()
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data:")]
    statuses = {e.get("phase") for e in events}
    assert "done" in statuses
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_routes.py::test_batch_init_requires_videos tests/test_routes.py::test_batch_init_returns_job_id tests/test_routes.py::test_batch_init_stream_returns_done -v
```

Expected: FAIL — 404.

- [ ] **Step 3: Add batch init routes to `routes.py`**

Add module-level state after `_init_lock`:

```python
_batch_init_jobs: dict[str, dict] = {}
_batch_init_jobs_lock = threading.Lock()
```

Add the background function and two routes after the `init_template_status` route:

```python
def _run_batch_init(job_id: str, video_paths: list[str]):
    total = len(video_paths)
    failed = []
    for i, video_path in enumerate(video_paths):
        p = Path(video_path)
        clips_dir = p.parent / p.stem
        state_path = clips_dir / "template" / "template_state.json"
        with _batch_init_jobs_lock:
            _batch_init_jobs[job_id]["current"] = i + 1
            _batch_init_jobs[job_id]["video"] = p.name
        try:
            processor.init_template_from_clips_dir(clips_dir, state_path, crop=config.TRAINING_CROP)
        except Exception as exc:
            failed.append({"video": p.name, "error": str(exc)})
    with _batch_init_jobs_lock:
        _batch_init_jobs[job_id]["phase"] = "done"
        _batch_init_jobs[job_id]["initialized"] = total - len(failed)
        _batch_init_jobs[job_id]["failed"] = len(failed)
        _batch_init_jobs[job_id]["failed_videos"] = failed


@bp.route("/batch-init", methods=["POST"])
def start_batch_init():
    body = request.get_json(force=True) or {}
    videos = body.get("videos", [])
    if not videos:
        return jsonify({"error": "videos list required"}), 400
    job_id = str(uuid.uuid4())
    with _batch_init_jobs_lock:
        _batch_init_jobs[job_id] = {
            "phase": "progress", "current": 0, "total": len(videos), "video": "",
        }
    thread = threading.Thread(target=_run_batch_init, args=(job_id, videos), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id})


@bp.route("/batch-init/stream")
def batch_init_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _batch_init_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        while True:
            with _batch_init_jobs_lock:
                job = dict(_batch_init_jobs[job_id])
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("phase") == "done":
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_routes.py::test_batch_init_requires_videos tests/test_routes.py::test_batch_init_returns_job_id tests/test_routes.py::test_batch_init_stream_returns_done -v
```

Expected: 3 passed.

- [ ] **Step 5: Add batch init click handler in `clip_cutter.js`**

Add `startBatchInit()` function before `DOMContentLoaded`:

```javascript
async function startBatchInit() {
  if (_batchQueue.size === 0) return;
  const videos = [..._batchQueue];
  document.getElementById("batch-init-btn").disabled = true;
  setStatus(`Starting batch init for ${videos.length} video${videos.length !== 1 ? "s" : ""}…`);
  try {
    const resp = await fetch("/clip-cutter/batch-init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videos }),
    });
    if (!resp.ok) { setStatus("Batch init error"); document.getElementById("batch-init-btn").disabled = false; return; }
    const { job_id } = await resp.json();
    const es = new EventSource(`/clip-cutter/batch-init/stream?job_id=${job_id}`);
    es.onmessage = (e) => {
      const job = JSON.parse(e.data);
      if (job.phase === "done") {
        es.close();
        document.getElementById("batch-init-btn").disabled = false;
        const msg = `Batch init done: ${job.initialized} initialized` +
          (job.failed > 0 ? `, ${job.failed} failed` : "");
        setStatus(msg);
      } else {
        setStatus(`Initializing ${job.current}/${job.total}: ${job.video}…`);
      }
    };
    es.onerror = () => {
      es.close();
      document.getElementById("batch-init-btn").disabled = false;
      setStatus("Batch init stream error");
    };
  } catch (err) {
    document.getElementById("batch-init-btn").disabled = false;
    setStatus("Network error: " + err.message);
  }
}
```

Wire the button in `DOMContentLoaded`:

```javascript
document.getElementById("batch-init-btn").addEventListener("click", startBatchInit);
```

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/static/clip_cutter.js clip-cutter/tests/test_routes.py
git commit -m "feat: add batch init route + frontend SSE handler"
```

---

## Task 7: Combined Template Processor

**Files:**
- Modify: `clip-cutter/processor.py`
- Modify: `clip-cutter/tests/test_processor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_processor.py`:

```python
def test_load_combined_template_empty_dirs(tmp_path):
    result = processor.load_combined_template([])
    assert result["clip_matrix"] is None
    assert result["dino_matrix"] is None


def test_load_combined_template_missing_state(tmp_path):
    # Directory exists but no template_state.json — should be skipped
    (tmp_path / "template").mkdir(parents=True)
    result = processor.load_combined_template([str(tmp_path)])
    assert result["clip_matrix"] is None


def test_load_combined_template_single_dir(tmp_path, mock_model):
    # Create a minimal template_state.json
    import json
    state = {
        "frames": [],
        "mean_embedding": [0.1] * 512,
        "dino_mean_embedding": [0.2] * 1024,
    }
    tpl_dir = tmp_path / "template"
    tpl_dir.mkdir()
    (tpl_dir / "template_state.json").write_text(json.dumps(state))
    result = processor.load_combined_template([str(tmp_path)])
    assert result["clip_matrix"].shape == (1, 512)
    assert result["dino_matrix"].shape == (1, 1024)


def test_load_combined_template_two_dirs(tmp_path, mock_model):
    import json
    for i in range(2):
        d = tmp_path / f"session{i}" / "template"
        d.mkdir(parents=True)
        state = {
            "frames": [],
            "mean_embedding": [float(i)] * 512,
            "dino_mean_embedding": [float(i)] * 1024,
        }
        (d / "template_state.json").write_text(json.dumps(state))
    dirs = [str(tmp_path / f"session{i}") for i in range(2)]
    result = processor.load_combined_template(dirs)
    assert result["clip_matrix"].shape == (2, 512)
    assert result["dino_matrix"].shape == (2, 1024)


def test_scan_video_multi_template_finds_detections(mock_model, tiny_video, tmp_path):
    """Multi-template scan returns detections list (may be empty for random embeddings)."""
    import json
    rng = np.random.default_rng(0)
    state = {
        "frames": [],
        "mean_embedding": rng.random(512).tolist(),
        "dino_mean_embedding": rng.random(1024).tolist(),
    }
    tpl_dir = tmp_path / "template"
    tpl_dir.mkdir()
    (tpl_dir / "template_state.json").write_text(json.dumps(state))
    combined = processor.load_combined_template([str(tmp_path)])
    detections = processor.scan_video_multi_template(
        tiny_video, combined,
        stride=5, threshold=0.0, min_spacing=1, fine_window=2, batch_size=10,
    )
    assert isinstance(detections, list)
    for d in detections:
        assert "frame_number" in d
        assert "similarity" in d
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_processor.py -k "combined_template or multi_template" -v
```

Expected: FAIL — `AttributeError: module 'processor' has no attribute 'load_combined_template'`.

- [ ] **Step 3: Implement `load_combined_template` in `processor.py`**

Add after `save_template_state`:

```python
def load_combined_template(template_dirs: list) -> dict:
    """
    Load template_state.json from each clips_dir/template/ and stack embeddings.
    Returns {clip_matrix: ndarray (N,512) or None, dino_matrix: ndarray (N,D) or None}.
    """
    clip_embs, dino_embs = [], []
    for d in template_dirs:
        state_path = Path(d) / "template" / "template_state.json"
        state = load_template_state(state_path)
        if state["mean_embedding"] is not None:
            clip_embs.append(state["mean_embedding"])
        if state.get("dino_mean_embedding") is not None:
            dino_embs.append(state["dino_mean_embedding"])
    return {
        "clip_matrix": np.stack(clip_embs) if clip_embs else None,
        "dino_matrix": np.stack(dino_embs) if dino_embs else None,
    }
```

- [ ] **Step 4: Implement `get_similarity_curve_multi` in `processor.py`**

Add after `get_similarity_curve`:

```python
def get_similarity_curve_multi(
    video_path: Path | str,
    clip_matrix: np.ndarray,
    stride: int = 10,
    batch_size: int = 64,
    progress_cb=None,
    positions: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Like get_similarity_curve but uses max(clip_matrix @ frame_emb) over N templates.
    clip_matrix shape: (N, 512).
    """
    from concurrent.futures import ThreadPoolExecutor

    video_path_str = str(video_path)
    cap = cv2.VideoCapture(video_path_str)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if positions is None:
        all_positions = np.arange(0, total_frames, stride, dtype=np.int64)
    else:
        all_positions = np.sort(np.asarray(positions, dtype=np.int64))

    similarities = np.zeros(len(all_positions), dtype=np.float32)
    if len(all_positions) == 0:
        return all_positions, similarities

    def read_batch(batch_positions):
        if len(batch_positions) == 0:
            return []
        vcap = cv2.VideoCapture(video_path_str)
        vcap.set(cv2.CAP_PROP_POS_FRAMES, int(batch_positions[0]))
        cur = int(batch_positions[0])
        frames = []
        try:
            for target in batch_positions:
                target = int(target)
                while cur < target:
                    vcap.grab()
                    cur += 1
                ret, frame = vcap.read()
                cur += 1
                frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
        finally:
            vcap.release()
        return frames

    processed = 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_batch, all_positions[:batch_size])
        for batch_start in range(0, len(all_positions), batch_size):
            batch_pos = all_positions[batch_start: batch_start + batch_size]
            frames = future.result()
            next_start = batch_start + batch_size
            future = pool.submit(read_batch, all_positions[next_start: next_start + batch_size])
            embs = embed_frames_batch(frames)               # (B, 512)
            sims = (embs @ clip_matrix.T).max(axis=1)      # (B,)
            n = len(batch_pos)
            similarities[batch_start: batch_start + n] = sims[:n]
            processed += n
            if progress_cb:
                progress_cb(processed, len(all_positions))

    return all_positions, similarities
```

- [ ] **Step 5: Implement `fine_scan_multi` in `processor.py`**

Add after `fine_scan`:

```python
def fine_scan_multi(
    video_path: Path | str,
    clip_matrix: "np.ndarray | None",
    coarse_cv2_pos: int,
    window: int = 50,
    dino_matrix: "np.ndarray | None" = None,
) -> tuple[int, float]:
    """
    Like fine_scan but uses max similarity across N template embeddings.
    clip_matrix: (N, 512) or None. dino_matrix: (N, D_dino) or None.
    """
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start = max(0, coarse_cv2_pos - window)
    end = min(total - 1, coarse_cv2_pos + window)
    positions = list(range(start, end + 1))
    frames = []
    for pos in positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ret, frame = cap.read()
        frames.append(frame if ret else np.zeros((64, 64, 3), dtype=np.uint8))
    cap.release()

    if dino_matrix is not None:
        embs = embed_frames_dino_batch(frames)              # (B, D_dino)
        sims = (embs @ dino_matrix.T).max(axis=1)          # (B,)
    else:
        embs = embed_frames_batch(frames)                   # (B, 512)
        sims = (embs @ clip_matrix.T).max(axis=1)          # (B,)

    best_local = int(np.argmax(sims))
    return positions[best_local], float(sims[best_local])
```

- [ ] **Step 6: Implement `scan_video_multi_template` in `processor.py`**

Add after `scan_video_sensor_guided` (or at the end of the scan section):

```python
def scan_video_multi_template(
    video_path: Path | str,
    combined: dict,
    stride: int = 10,
    threshold: float = 0.70,
    min_spacing: int = 900,
    fine_window: int = 50,
    batch_size: int = 64,
    smooth_sigma: float = 3.0,
    progress_cb=None,
    phase_cb=None,
) -> list[dict]:
    """
    Full scan pipeline using multiple template embeddings (max similarity).
    combined: output of load_combined_template().
    Returns same format as scan_video(): [{cv2_pos, frame_number, similarity}, ...].
    """
    clip_matrix = combined.get("clip_matrix")
    dino_matrix = combined.get("dino_matrix")
    if clip_matrix is None:
        return []

    if phase_cb:
        phase_cb("coarse", 0, 1)

    frame_indices, similarities = get_similarity_curve_multi(
        video_path, clip_matrix,
        stride=stride, batch_size=batch_size,
        progress_cb=lambda c, t: phase_cb("coarse", c, t) if phase_cb else (progress_cb(c, t) if progress_cb else None),
    )

    if len(frame_indices) == 0:
        return []

    if phase_cb:
        phase_cb("peak_detection", 0, 1)
    smoothed = smooth_curve(similarities, sigma=smooth_sigma)
    coarse_peaks = find_peaks_in_curve(smoothed, frame_indices, threshold, min_spacing)

    detections = []
    if phase_cb:
        phase_cb("fine", 0, len(coarse_peaks))
    for i, cv2_pos in enumerate(coarse_peaks):
        best_pos, best_sim = fine_scan_multi(
            video_path, clip_matrix, cv2_pos,
            window=fine_window, dino_matrix=dino_matrix,
        )
        detections.append({
            "cv2_pos": best_pos,
            "frame_number": best_pos + 1,
            "similarity": best_sim,
        })
        if phase_cb:
            phase_cb("fine", i + 1, len(coarse_peaks))

    return detections
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python -m pytest tests/test_processor.py -k "combined_template or multi_template" -v
```

Expected: 5 passed.

- [ ] **Step 8: Run full test suite**

```bash
python -m pytest tests/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/processor.py clip-cutter/tests/test_processor.py
git commit -m "feat: add load_combined_template and scan_video_multi_template (max-similarity)"
```

---

## Task 8: Batch Scan Route + Frontend Wiring

**Files:**
- Modify: `clip-cutter/routes.py`
- Modify: `clip-cutter/tests/test_routes.py`
- Modify: `clip-cutter/static/clip_cutter.js`

- [ ] **Step 1: Write failing tests for batch scan**

Add to `tests/test_routes.py`:

```python
def test_batch_scan_requires_template_dirs(lib_client):
    resp = lib_client.post(
        "/clip-cutter/batch-scan",
        json={"template_dirs": [], "video_paths": ["/user-data/v.avi"]},
    )
    assert resp.status_code == 400


def test_batch_scan_requires_video_paths(lib_client):
    resp = lib_client.post(
        "/clip-cutter/batch-scan",
        json={"template_dirs": ["/some/dir"], "video_paths": []},
    )
    assert resp.status_code == 400


def test_batch_scan_returns_job_id(lib_client, monkeypatch, tmp_path):
    import processor
    monkeypatch.setattr(
        processor, "load_combined_template",
        lambda dirs: {"clip_matrix": None, "dino_matrix": None},
    )
    monkeypatch.setattr(
        processor, "scan_video_multi_template",
        lambda *a, **kw: [],
    )
    resp = lib_client.post(
        "/clip-cutter/batch-scan",
        json={"template_dirs": ["/some/dir"], "video_paths": [str(tmp_path / "v.avi")]},
    )
    assert resp.status_code == 200
    assert "job_id" in json.loads(resp.data)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_routes.py::test_batch_scan_requires_template_dirs tests/test_routes.py::test_batch_scan_requires_video_paths tests/test_routes.py::test_batch_scan_returns_job_id -v
```

Expected: FAIL — 404.

- [ ] **Step 3: Add batch scan routes to `routes.py`**

Add module-level state after `_batch_init_jobs_lock`:

```python
_batch_scan_jobs: dict[str, dict] = {}
_batch_scan_jobs_lock = threading.Lock()
```

Add background function and routes after the `batch_init_stream` route:

```python
def _run_batch_scan(job_id: str, template_dirs: list, video_paths: list, params: dict):
    stride        = params.get("stride",        config.SCAN_STRIDE)
    threshold     = params.get("threshold",     config.SIMILARITY_THRESHOLD)
    min_spacing   = params.get("min_spacing",   config.MIN_PEAK_SPACING)
    fine_window   = params.get("fine_window",   config.FINE_SCAN_WINDOW)

    combined = processor.load_combined_template(template_dirs)
    if combined["clip_matrix"] is None:
        with _batch_scan_jobs_lock:
            _batch_scan_jobs[job_id]["phase"] = "error"
            _batch_scan_jobs[job_id]["error"] = "No valid templates found in selected directories"
        return

    results = []
    total_videos = len(video_paths)
    for i, video_path in enumerate(video_paths):
        def phase_cb(phase, current, total, _vpath=video_path):
            with _batch_scan_jobs_lock:
                _batch_scan_jobs[job_id]["video"] = Path(_vpath).name
                _batch_scan_jobs[job_id]["video_index"] = i + 1
                _batch_scan_jobs[job_id]["video_total"] = total_videos
                _batch_scan_jobs[job_id]["phase"] = phase
                _batch_scan_jobs[job_id]["current"] = current
                _batch_scan_jobs[job_id]["total"] = total

        try:
            detections = processor.scan_video_multi_template(
                video_path, combined,
                stride=stride, threshold=threshold,
                min_spacing=min_spacing, fine_window=fine_window,
                batch_size=config.SCAN_BATCH_SIZE,
                phase_cb=phase_cb,
            )
            for d in detections:
                d["status"] = "pending"
                d["source"] = "global_library"
            results.append({"video": video_path, "detections": detections})
        except Exception as exc:
            results.append({"video": video_path, "error": str(exc), "detections": []})

    with _batch_scan_jobs_lock:
        _batch_scan_jobs[job_id]["phase"] = "done"
        _batch_scan_jobs[job_id]["results"] = results


@bp.route("/batch-scan", methods=["POST"])
def start_batch_scan():
    body = request.get_json(force=True) or {}
    template_dirs = body.get("template_dirs", [])
    video_paths = body.get("video_paths", [])
    if not template_dirs:
        return jsonify({"error": "template_dirs required"}), 400
    if not video_paths:
        return jsonify({"error": "video_paths required"}), 400
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    job_id = str(uuid.uuid4())
    with _batch_scan_jobs_lock:
        _batch_scan_jobs[job_id] = {
            "phase": "starting", "video": "", "video_index": 0, "video_total": len(video_paths),
            "current": 0, "total": 1,
        }
    thread = threading.Thread(
        target=_run_batch_scan,
        args=(job_id, template_dirs, video_paths, params),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@bp.route("/batch-scan/stream")
def batch_scan_stream():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in _batch_scan_jobs:
        return jsonify({"error": "unknown job_id"}), 404

    def generate():
        while True:
            with _batch_scan_jobs_lock:
                job = dict(_batch_scan_jobs[job_id])
            yield f"data: {json.dumps(job)}\n\n"
            if job.get("phase") in ("done", "error"):
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_routes.py::test_batch_scan_requires_template_dirs tests/test_routes.py::test_batch_scan_requires_video_paths tests/test_routes.py::test_batch_scan_returns_job_id -v
```

Expected: 3 passed.

- [ ] **Step 5: Add `startBatchScan()` in `clip_cutter.js`**

Add before `DOMContentLoaded`:

```javascript
async function startBatchScan() {
  if (_activeBatchFolders.size === 0 || _batchQueue.size === 0) return;
  const template_dirs = [..._activeBatchFolders];
  const video_paths = [..._batchQueue];
  setStatus(`Starting batch scan: ${template_dirs.length} template source(s), ${video_paths.length} video(s)…`);
  try {
    const resp = await fetch("/clip-cutter/batch-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        template_dirs,
        video_paths,
        params: {
          trigger_value: parseInt(document.getElementById("trigger-value").value, 10),
          sensor_margin: parseInt(document.getElementById("sensor-margin").value, 10),
          stride: parseInt(document.getElementById("scan-stride").value, 10),
          threshold: parseFloat(document.getElementById("scan-threshold").value),
          min_spacing: parseInt(document.getElementById("min-spacing").value, 10),
          fine_window: parseInt(document.getElementById("fine-window").value, 10),
        },
      }),
    });
    if (!resp.ok) { setStatus("Batch scan error"); return; }
    const { job_id } = await resp.json();
    const es = new EventSource(`/clip-cutter/batch-scan/stream?job_id=${job_id}`);
    es.onmessage = (e) => {
      const job = JSON.parse(e.data);
      if (job.phase === "done") {
        es.close();
        let total = 0;
        (job.results || []).forEach(r => {
          total += r.detections.length;
          renderDetections(r.detections);
        });
        setStatus(`Batch scan done — ${total} detection${total !== 1 ? "s" : ""} across ${video_paths.length} video${video_paths.length !== 1 ? "s" : ""}`);
      } else if (job.phase === "error") {
        es.close();
        setStatus("Batch scan error: " + job.error);
      } else {
        setStatus(`Scanning ${job.video} (${job.video_index}/${job.video_total}) — ${job.phase}…`);
      }
    };
    es.onerror = () => { es.close(); setStatus("Batch scan stream error"); };
  } catch (err) {
    setStatus("Network error: " + err.message);
  }
}
```

- [ ] **Step 6: Run full test suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/static/clip_cutter.js clip-cutter/tests/test_routes.py
git commit -m "feat: add batch scan route + frontend wiring with max-similarity multi-template"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| Template viewer rework (list rows, View, Delete) | Task 1 |
| `LIBRARIES_PATH` config + persistence helpers | Task 2 |
| Library CRUD (5 routes) | Task 3 |
| Libraries sidebar tab (tabs, panel, card UI) | Task 4 |
| Batch mode checkbox queue (persists across navigation) | Task 5 |
| `[+ Add folder]` button adds current browser path | Task 5 |
| Batch init route + SSE stream | Task 6 |
| `load_combined_template` (max-similarity) | Task 7 |
| `scan_video_multi_template` | Task 7 |
| Batch scan route + SSE stream | Task 8 |
| `startBatchScan()` frontend | Task 8 |
| `libraries.json` on Cloud mount (persisted) | Task 2 (LIBRARIES_PATH under _DATA_ROOT) |

All spec requirements covered. ✓

**Placeholder scan:** No TBDs, all code blocks complete. ✓

**Type consistency:**
- `load_combined_template` returns `{clip_matrix, dino_matrix}` — used consistently in `scan_video_multi_template` (Task 7) and `_run_batch_scan` (Task 8). ✓
- `_batchQueue` is a `Set` — spread as `[..._batchQueue]` in Tasks 6 and 8. ✓
- `_activeBatchFolders` is a `Set` — spread as `[..._activeBatchFolders]` in Task 8. ✓
- `renderBrowser` in Task 5 references `videoPath` and `stem` — both defined earlier in the same `forEach` callback. ✓
- `updateBatchScanBtn()` defined in Task 4 — called in Tasks 4 and 5. ✓
- `startBatchScan()` defined in Task 8 — wired in Task 4 lib scan button. ✓ (Task 4 adds the button with a `startBatchScan()` call; Task 8 defines the function. Tasks must run in order.)
