# DLC-3D Redesign — Main Webapp Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the dlc-3D Docker container so it inherits the full main webapp image (navbar, CSS, auth, fonts) via a build-time overlay, replacing the current standalone Flask setup.

**Architecture:** The dlc-3D Dockerfile uses `FROM deeplabcut-webapp-docker-flask:latest`, renames `/app/app.py` → `/app/base_app.py`, then copies the dlc-3D `src/` tree on top. `src/app.py` imports `base_app` and registers the dlc-3D Blueprint. `dlc_3d.html` extends the main webapp's `base.html`.

**Tech Stack:** Python 3.10, Flask Blueprint, Jinja2 template inheritance, Docker build-time overlay, gunicorn, OpenCV headless, pytest.

---

## File Map

| Action | Path |
|--------|------|
| Create | `dlc-3D/src/app.py` |
| Create | `dlc-3D/src/dlc_3d_bp/__init__.py` |
| Move → | `dlc-3D/routes.py` → `dlc-3D/src/dlc_3d_bp/routes.py` |
| Move → | `dlc-3D/config.py` → `dlc-3D/src/config.py` |
| Move → | `dlc-3D/viewer.py` → `dlc-3D/src/viewer.py` |
| Move → | `dlc-3D/templates/dlc_3d.html` → `dlc-3D/src/templates/dlc_3d.html` |
| Move → | `dlc-3D/static/*` → `dlc-3D/src/static/*` |
| Create | `dlc-3D/src/static/dlc_3d.css` |
| Modify | `dlc-3D/src/templates/dlc_3d.html` (extend base.html) |
| Modify | `dlc-3D/src/dlc_3d_bp/routes.py` (Blueprint static_url_path) |
| Modify | `dlc-3D/tests/conftest.py` (sys.path update) |
| Modify | `dlc-3D/tests/test_core.py` (import path update) |
| Replace | `dlc-3D/Dockerfile` |
| Modify | `deeplabcut-webapp-docker/docker-compose.yml` (dlc-3d service) |

---

### Task 1: Scaffold src/ directory and move files

**Files:**
- Create: `dlc-3D/src/dlc_3d_bp/__init__.py`
- Move: `dlc-3D/routes.py` → `dlc-3D/src/dlc_3d_bp/routes.py`
- Move: `dlc-3D/config.py` → `dlc-3D/src/config.py`
- Move: `dlc-3D/viewer.py` → `dlc-3D/src/viewer.py`
- Move: `dlc-3D/templates/dlc_3d.html` → `dlc-3D/src/templates/dlc_3d.html`
- Move: `dlc-3D/static/*` → `dlc-3D/src/static/*`

Working directory for all commands: `/home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/dlc_3d_bp src/templates src/static
```

- [ ] **Step 2: Move Python modules**

```bash
mv routes.py src/dlc_3d_bp/routes.py
mv config.py src/config.py
mv viewer.py src/viewer.py
touch src/dlc_3d_bp/__init__.py
```

- [ ] **Step 3: Move templates and static assets**

```bash
mv templates/dlc_3d.html src/templates/dlc_3d.html
rmdir templates
mv static/dlc_3d.js src/static/dlc_3d.js
mv static/enhanced_player.js src/static/enhanced_player.js
rmdir static
```

- [ ] **Step 4: Verify layout**

```bash
find src/ -type f | sort
```

Expected output:
```
src/config.py
src/dlc_3d_bp/__init__.py
src/dlc_3d_bp/routes.py
src/static/dlc_3d.js
src/static/enhanced_player.js
src/templates/dlc_3d.html
src/viewer.py
```

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/ dlc-3D/templates dlc-3D/static dlc-3D/routes.py dlc-3D/config.py dlc-3D/viewer.py
git commit -m "refactor(dlc-3d): move source files into src/ layout"
```

---

### Task 2: Fix imports after move

`routes.py` imports `config` and `viewer` with bare names. After moving to `src/dlc_3d_bp/routes.py`, those siblings are now one level up (`src/`). Since the app runs from `/app/` (where `config.py` and `viewer.py` land after `COPY src/ /app/`), bare imports still work at runtime. But tests run from the repo and need a sys.path fix.

**Files:**
- Modify: `dlc-3D/tests/conftest.py`
- Modify: `dlc-3D/tests/test_core.py`

- [ ] **Step 1: Update conftest.py to add src/ to sys.path**

Replace the entire contents of `dlc-3D/tests/conftest.py` with:

```python
import sys
from pathlib import Path

# Add src/ so tests can import config, viewer, dlc_3d_bp.*
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
```

- [ ] **Step 2: Update test_core.py import**

In `dlc-3D/tests/test_core.py`, replace:

```python
from routes import (
    _cam_index_from_stem,
    _find_sibling_video,
    _load_or_scan_videos,
    _save_single_frame,
    _scan_videos,
    _session_key_from_stem,
)
```

with:

```python
from dlc_3d_bp.routes import (
    _cam_index_from_stem,
    _find_sibling_video,
    _load_or_scan_videos,
    _save_single_frame,
    _scan_videos,
    _session_key_from_stem,
)
```

- [ ] **Step 3: Run tests to confirm all 26 pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/tests/conftest.py dlc-3D/tests/test_core.py
git commit -m "fix(dlc-3d): update test imports for src/dlc_3d_bp layout"
```

---

### Task 3: Update Blueprint static_url_path

The Blueprint currently serves static files at `/static/<filename>`, which collides with the main webapp's `/static/` endpoint. Change `static_url_path` to `/dlc-3d/static` so files are served at `/dlc-3d/static/<filename>`.

**Files:**
- Modify: `dlc-3D/src/dlc_3d_bp/routes.py`

- [ ] **Step 1: Update Blueprint definition**

In `dlc-3D/src/dlc_3d_bp/routes.py`, find:

```python
bp = Blueprint(
    "dlc_3d", __name__, url_prefix="/dlc-3d",
    template_folder="templates",
    static_folder="static", static_url_path="/static",
)
```

Replace with:

```python
bp = Blueprint(
    "dlc_3d", __name__, url_prefix="/dlc-3d",
    template_folder="templates",
    static_folder="static", static_url_path="/dlc-3d/static",
)
```

- [ ] **Step 2: Run tests to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/dlc_3d_bp/routes.py
git commit -m "fix(dlc-3d): set Blueprint static_url_path to /dlc-3d/static"
```

---

### Task 4: Create src/app.py overlay entry point

**Files:**
- Create: `dlc-3D/src/app.py`

- [ ] **Step 1: Create src/app.py**

Create `dlc-3D/src/app.py` with:

```python
from base_app import app
from dlc_3d_bp.routes import bp

app.register_blueprint(bp)
```

- [ ] **Step 2: Verify file**

```bash
cat /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/app.py
```

Expected output:
```
from base_app import app
from dlc_3d_bp.routes import bp

app.register_blueprint(bp)
```

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/app.py
git commit -m "feat(dlc-3d): add overlay app.py that imports base_app and registers blueprint"
```

---

### Task 5: Extract CSS and rewrite dlc_3d.html

The current `dlc_3d.html` is a standalone page (lines 1–204). The inline `<style>` block (lines 7–111) moves to `src/static/dlc_3d.css`. The HTML is rewritten to extend the main webapp's `base.html`.

**Files:**
- Create: `dlc-3D/src/static/dlc_3d.css`
- Replace: `dlc-3D/src/templates/dlc_3d.html`

- [ ] **Step 1: Extract the CSS**

Create `dlc-3D/src/static/dlc_3d.css` with the contents of the `<style>` block from lines 8–110 of `dlc_3d.html` (everything between `<style>` and `</style>`, not including those tags):

```css
:root {
  --bg: #0d1117; --panel: #161b22; --border: #30363d;
  --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
       height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* ── Header ── */
header { background: var(--panel); border-bottom: 1px solid var(--border);
         padding: .45rem 1rem; display: flex; align-items: center; gap: .75rem; flex-shrink: 0; }
header h1 { font-size: .92rem; font-weight: 600; white-space: nowrap; }
#project-path-display { font-size: .75rem; color: var(--text-dim); flex: 1;
                         white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ── Buttons ── */
.btn { background: var(--panel); border: 1px solid var(--border); color: var(--text);
       padding: .28rem .65rem; border-radius: 5px; cursor: pointer; font-size: .8rem;
       white-space: nowrap; }
.btn:hover { border-color: var(--accent); }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #000; font-weight: 600; }
.btn:disabled { opacity: .45; cursor: default; }

/* ── Main layout ── */
.main-layout { display: flex; flex: 1; overflow: hidden; }

/* ── Session panel (left) ── */
#session-panel { width: 260px; min-width: 180px; border-right: 1px solid var(--border);
                 overflow-y: auto; padding: .4rem; display: flex; flex-direction: column; gap: .25rem; }
#session-empty { font-size: .75rem; color: var(--text-dim); padding: .5rem; }
.session-group { border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }
.session-header { font-size: .8rem; font-weight: 600; padding: .3rem .55rem;
                  background: var(--panel); cursor: pointer; display: flex; align-items: center; gap: .35rem; }
.session-header:hover { background: #21262d; }
.session-body { display: none; }
.session-body.open { display: block; }
.cam-row { padding: .22rem .55rem .22rem 1.1rem; font-size: .78rem; color: var(--text-dim);
           cursor: pointer; display: flex; align-items: center; gap: .4rem; }
.cam-row:hover { background: #21262d; color: var(--text); }
.cam-row.active { background: #1f3a5c; color: var(--accent); }
.clip-section { padding-left: 1.6rem; }
.clip-header { font-size: .72rem; color: var(--text-dim); padding: .15rem .4rem; font-style: italic; }
.clip-row { padding: .18rem .4rem; font-size: .75rem; color: var(--text-dim); cursor: pointer; border-radius: 3px; }
.clip-row:hover { background: #21262d; color: var(--text); }
.clip-row.active { background: #1f3a5c; color: var(--accent); }
.cam-badge { font-size: .68rem; background: #21262d; border-radius: 3px;
             padding: .05rem .3rem; color: var(--text-dim); }
```

> **Note:** Read the actual CSS from `dlc-3D/src/static/dlc_3d.css` after copying — the excerpt above may not be complete. Copy lines 8–110 from `dlc_3d.html` verbatim to ensure you get all rules.

- [ ] **Step 2: Verify the CSS file was created**

```bash
wc -l /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/static/dlc_3d.css
```

Expected: at least 80 lines.

- [ ] **Step 3: Rewrite dlc_3d.html to extend base.html**

Replace the entire contents of `dlc-3D/src/templates/dlc_3d.html` with:

```html
{% extends "base.html" %}

{% block title %}DLC-3D Extractor{% endblock %}

{% block extra_head %}
<link rel="stylesheet" href="{{ url_for('dlc_3d.static', filename='dlc_3d.css') }}">
{% endblock %}

{% block content %}
  <!-- Header bar (project open / rescan) -->
  <header>
    <h1>DLC 3D Extractor</h1>
    <button class="btn" id="btn-open-project">Open Project</button>
    <span id="project-path-display">No project loaded</span>
    <button class="btn" id="btn-rescan" style="display:none">↺ Rescan</button>
  </header>

  <div class="main-layout">
    <!-- Left: session browser -->
    <div id="session-panel">
      <div id="session-empty">Open a DLC project to begin.</div>
    </div>

    <!-- Right: player area -->
    <div id="player-area">
      <div id="cam-displays">
        <div class="cam-wrap" id="cam1-wrap">
          <div class="cam-label" id="cam1-label">Primary camera</div>
          <div class="cam-frame-wrap" id="cam1-frame-wrap">
            <img id="ep-frame" src="" alt="" style="display:none">
            <span id="no-video-msg">Select a video or clip from the left panel.</span>
          </div>
        </div>
        <div class="cam-wrap" id="ep-cam2-wrap" style="display:none">
          <div class="cam-label" id="cam2-label">Sibling camera</div>
          <div class="cam-frame-wrap">
            <img id="ep-cam2-frame" src="" alt="">
          </div>
        </div>
      </div>

      <div id="controls">
        <!-- Seek row -->
        <div class="ctrl-row">
          <input type="range" id="ep-seek" value="0" min="0" max="0">
          <span class="frame-info">
            Frame <span id="ep-frame-num">—</span> / <span id="ep-frame-total">—</span>
          </span>
        </div>
        <!-- Playback row -->
        <div class="ctrl-row">
          <button class="btn" id="ep-skip-start" title="Jump to start">⏮</button>
          <button class="btn" id="ep-step-back" title="Step back">◀</button>
          <button class="btn" id="ep-play" title="Play / pause">▶</button>
          <button class="btn" id="ep-step-fwd" title="Step forward">▶</button>
          <button class="btn" id="ep-skip-end" title="Jump to end">⏭</button>
          <label style="font-size:.75rem;color:var(--text-dim)">
            Skip <input type="number" id="ep-step" value="10" min="1" max="9999"
              style="width:3.2rem;background:var(--bg);border:1px solid var(--border);
                     color:var(--text);padding:.18rem .28rem;border-radius:3px;font-size:.78rem">
          </label>
          <button class="btn btn-primary" id="ep-extract-btn" disabled>Extract Frame</button>
        </div>
        <!-- Sync cam row -->
        <div class="ctrl-row" id="sync-cam-row">
          <label class="toggle">
            <input type="checkbox" id="ep-sync-cam"> Sync Cam
          </label>
          <label class="toggle" id="ep-extract-sibling-label" style="display:none">
            <input type="checkbox" id="ep-extract-sibling" checked> Extract Sibling
          </label>
        </div>
      </div>

      <div id="extract-status"></div>

      <!-- Labeled frames for current session -->
      <div id="labeled-wrap">
        <div id="labeled-header">Extracted frames: <span id="labeled-count">0</span></div>
        <div id="labeled-list"></div>
      </div>
    </div>
  </div>

  <!-- Filesystem browser modal -->
  <div id="browser-modal">
    <div id="browser-box">
      <div id="browser-box-header">
        <span>Open DLC Project</span>
        <button class="btn" id="browser-close">✕</button>
      </div>
      <div id="browser-path-bar">/</div>
      <div id="browser-list"></div>
    </div>
  </div>
{% endblock %}

{% block scripts %}
{{ super() }}
<script type="module" src="{{ url_for('dlc_3d.static', filename='enhanced_player.js') }}"></script>
<script type="module" src="{{ url_for('dlc_3d.static', filename='dlc_3d.js') }}"></script>
{% endblock %}
```

- [ ] **Step 4: Verify the template no longer contains a `<style>` block**

```bash
grep -c "<style" /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D/src/templates/dlc_3d.html
```

Expected: `0`

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/src/static/dlc_3d.css dlc-3D/src/templates/dlc_3d.html
git commit -m "feat(dlc-3d): extract CSS to dlc_3d.css, rewrite template to extend base.html"
```

---

### Task 6: Rewrite Dockerfile

The build context is `../` (one level above `deeplabcut-webapp-docker-supports/`). The Dockerfile lives at `deeplabcut-webapp-docker-supports/dlc-3D/Dockerfile`. It builds from the main webapp's Flask image.

**Files:**
- Replace: `dlc-3D/Dockerfile`

- [ ] **Step 1: Verify the main webapp image exists**

```bash
docker images deeplabcut-webapp-docker-flask:latest
```

Expected: one row with `deeplabcut-webapp-docker-flask` and tag `latest`. If not present, build it first:

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker build -f Dockerfile.flask -t deeplabcut-webapp-docker-flask:latest .
```

- [ ] **Step 2: Write the new Dockerfile**

Replace the entire contents of `dlc-3D/Dockerfile` with:

```dockerfile
# Build context: ../  (parent of both deeplabcut-webapp-docker and deeplabcut-webapp-docker-supports)
FROM deeplabcut-webapp-docker-flask:latest

USER root

# anipose_src is not in the base image (Dockerfile.flask only copies src/anipose/)
COPY --chown=appuser:appuser deeplabcut-webapp-docker/src/anipose_src/ /app/anipose_src/

# Rename main webapp entry point so our overlay can import it
RUN mv /app/app.py /app/base_app.py

# Copy dlc-3D source on top
COPY --chown=appuser:appuser deeplabcut-webapp-docker-supports/dlc-3D/src/ /app/

USER appuser

EXPOSE 5050

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5050", "--timeout", "300", "app:app"]
```

- [ ] **Step 3: Do a test build to confirm the Dockerfile is valid**

```bash
cd /home/sam/docker-images
docker build -f deeplabcut-webapp-docker-supports/dlc-3D/Dockerfile -t dlc-3d:latest .
```

Expected: build completes without errors. The final `Successfully built ...` line confirms success.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/Dockerfile
git commit -m "feat(dlc-3d): replace Dockerfile with build-time overlay from main webapp image"
```

---

### Task 7: Update docker-compose.yml (main webapp)

Replace the `dlc-3d` service in the main webapp's `docker-compose.yml`. The build context changes from the old module directory to `../` (parent of `deeplabcut-webapp-docker`). Volume mounts for live-reload update to reflect the new `src/` layout.

**Files:**
- Modify: `deeplabcut-webapp-docker/docker-compose.yml`

The current `dlc-3d` service block is:

```yaml
  dlc-3d:
    build:
      context: ../deeplabcut-webapp-docker-supports/dlc-3D
      dockerfile: Dockerfile
    image: dlc-3d:latest
    volumes:
      - /home/sam/data-disk/Parra-Data:/user-data/Parra-Data/Disk
      - /home/sam/synology/Parra-Lab-Data:/user-data/Parra-Data/Cloud
      - /home/sam/data-mount-dir:/user-data/Martin-Data/USB
      - /home/sam/Parra-Lab-Data-NAS:/user-data/NAS-Data-Share
      - ../deeplabcut-webapp-docker-supports/dlc-3D/routes.py:/app/routes.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/config.py:/app/config.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/viewer.py:/app/viewer.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/templates:/app/templates
      - ../deeplabcut-webapp-docker-supports/dlc-3D/static:/app/static
    environment:
      - DLC_3D_PORT=5050
    networks:
      - default
    restart: unless-stopped
```

- [ ] **Step 1: Replace the dlc-3d service block**

In `deeplabcut-webapp-docker/docker-compose.yml`, replace the block above with:

```yaml
  dlc-3d:
    build:
      context: ../
      dockerfile: deeplabcut-webapp-docker-supports/dlc-3D/Dockerfile
    image: dlc-3d:latest
    volumes:
      - /home/sam/data-disk/Parra-Data:/user-data/Parra-Data/Disk
      - /home/sam/synology/Parra-Lab-Data:/user-data/Parra-Data/Cloud
      - /home/sam/data-mount-dir:/user-data/Martin-Data/USB
      - /home/sam/Parra-Lab-Data-NAS:/user-data/NAS-Data-Share
      # Live-reload source files without rebuild
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/app.py:/app/app.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/dlc_3d_bp:/app/dlc_3d_bp
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/config.py:/app/config.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/viewer.py:/app/viewer.py
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates:/app/templates
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/static:/app/static
    environment:
      - AUTH_DISABLED=true
      - DLC_3D_PORT=5050
    networks:
      - default
    restart: unless-stopped
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose config --quiet
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Rebuild and restart the dlc-3d container**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose build dlc-3d
docker compose up -d dlc-3d
docker compose logs dlc-3d --tail 20
```

Expected in logs: `[INFO] Listening at: http://0.0.0.0:5050` (gunicorn startup).

- [ ] **Step 4: Smoke-test the page loads**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5050/dlc-3d/
```

Expected: `200`

Also open `http://localhost:5000/dlc-3d/` in a browser and confirm the main webapp navbar is visible.

- [ ] **Step 5: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
git add docker-compose.yml
git commit -m "feat(dlc-3d): update docker-compose to build from parent context with overlay Dockerfile"
```

---

### Task 8: Clean up old root-level files

With everything moved into `src/`, the old flat files at the root of `dlc-3D/` are gone (moved in Task 1). Confirm nothing leftover breaks the repo.

**Files:**
- Delete: `dlc-3D/app.py` (the old standalone factory — replaced by `src/app.py`)
- Delete: `dlc-3D/docker-compose.yml` (the old standalone compose — superseded by main webapp's compose)

- [ ] **Step 1: Remove old standalone files**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
rm -f app.py docker-compose.yml
```

- [ ] **Step 2: Confirm tests still pass**

```bash
python -m pytest tests/ -q
```

Expected: `26 passed`

- [ ] **Step 3: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add dlc-3D/app.py dlc-3D/docker-compose.yml
git commit -m "chore(dlc-3d): remove old standalone app.py and docker-compose.yml"
```
