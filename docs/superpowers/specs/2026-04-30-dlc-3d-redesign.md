---
name: DLC-3D Redesign — Main Webapp Integration
description: Design spec for rebuilding dlc-3D module to inherit the main webapp's GUI, auth, styling, and routes via Docker image overlay
type: project
---

# DLC-3D Redesign — Main Webapp Integration

**Date:** 2026-04-30  
**Scope:** Replace the standalone dlc-3D Flask container with one that inherits the full main webapp image and overlays only the dlc-3D-specific code. The extract-frame logic and video routes are unchanged; only the container assembly and template change.

---

## 1. Architecture

**Approach:** Build-time overlay via Docker. `dlc-3D/Dockerfile` uses `FROM deeplabcut-webapp-docker-flask:latest` as its base, then:

1. Copies `anipose_src/` from `deeplabcut-webapp-docker/src/` (not in base image — the main webapp's `Dockerfile.flask` only copies `anipose/`).
2. Renames `/app/app.py` → `/app/base_app.py` so the dlc-3D overlay can import it.
3. Copies `deeplabcut-webapp-docker-supports/dlc-3D/src/` over `/app/`, dropping in the dlc-3D entry point and blueprint.

The dlc-3D container runs on port 5050. The main webapp's proxy forwards `/dlc-3d/*` to `http://dlc-3d:5050/dlc-3d/*` (already wired). `AUTH_DISABLED=true` in the dlc-3D container — auth is handled by the main webapp proxy before the request reaches dlc-3D.

Build context for the dlc-3D image is `../` (parent directory of both repos) so the Dockerfile can COPY from both sibling repositories.

---

## 2. Module Restructure

New `dlc-3D/` layout:

```
dlc-3D/
  Dockerfile               ← rewritten (build context = ../)
  requirements.txt         ← dlc-3D-only additions (kept minimal)
  src/
    app.py                 ← imports base_app, registers bp
    config.py              ← DLC_3D_PORT=5050, USER_DATA_ROOTS (unchanged)
    viewer.py              ← LRU VideoCapture cache (unchanged)
    dlc_3d_bp/
      __init__.py          ← empty
      routes.py            ← all dlc-3D routes (logic unchanged, Blueprint static_url_path updated)
    templates/
      dlc_3d.html          ← rewritten to extend base.html
    static/
      dlc_3d.css           ← extracted from inline <style> block
      dlc_3d.js            ← unchanged
      enhanced_player.js   ← unchanged
  tests/
    test_core.py           ← 26 existing tests (unchanged)
```

`src/app.py` (overlay entry point):

```python
from base_app import app
from dlc_3d_bp.routes import bp
app.register_blueprint(bp)
```

---

## 3. Template Changes

`dlc_3d.html` is rewritten to extend the main webapp's `base.html`:

```html
{% extends "base.html" %}

{% block title %}DLC-3D Extractor{% endblock %}

{% block extra_head %}
<link rel="stylesheet" href="{{ url_for('dlc_3d.static', filename='dlc_3d.css') }}">
{% endblock %}

{% block content %}
<div id="dlc3d-app">
  <!-- session browser panel (left) -->
  <!-- player panels (right) -->
  <!-- extract controls bar (bottom) -->
</div>
{% endblock %}

{% block scripts %}
{{ super() }}
<script src="{{ url_for('dlc_3d.static', filename='enhanced_player.js') }}"></script>
<script src="{{ url_for('dlc_3d.static', filename='dlc_3d.js') }}"></script>
{% endblock %}
```

The `<style>` block from the current `dlc_3d.html` moves to `static/dlc_3d.css`. All existing JS logic and `/dlc-3d/...` fetch URLs remain unchanged.

The Blueprint `static_url_path` is updated to `/dlc-3d/static` to avoid collision with the main webapp's `/static` path:

```python
bp = Blueprint("dlc_3d", __name__, url_prefix="/dlc-3d",
    template_folder="templates",
    static_folder="static",
    static_url_path="/dlc-3d/static")
```

---

## 4. Dockerfile

Build context: `../` (parent of both repos).

```dockerfile
FROM deeplabcut-webapp-docker-flask:latest

USER root

# anipose_src is not in the base image (Dockerfile.flask only copies anipose/)
COPY --chown=appuser:appuser deeplabcut-webapp-docker/src/anipose_src/ /app/anipose_src/

# Rename main webapp entry point so our overlay can import it
RUN mv /app/app.py /app/base_app.py

# Copy dlc-3D source over the top
COPY --chown=appuser:appuser deeplabcut-webapp-docker-supports/dlc-3D/src/ /app/

USER appuser

EXPOSE 5050

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5050", "--timeout", "300", "app:app"]
```

---

## 5. docker-compose Changes (main webapp)

Replace the existing `dlc-3d` service in `deeplabcut-webapp-docker/docker-compose.yml`:

```yaml
dlc-3d:
  build:
    context: ../
    dockerfile: deeplabcut-webapp-docker-supports/dlc-3D/Dockerfile
  volumes:
    - /home/sam/data-disk/Parra-Data:/user-data/Parra-Data/Disk
    - /home/sam/synology/Parra-Lab-Data:/user-data/Parra-Data/Cloud
    - /home/sam/data-mount-dir:/user-data/Martin-Data/USB
    - /home/sam/Parra-Lab-Data-NAS:/user-data/NAS-Data-Share
  environment:
    - AUTH_DISABLED=true
    - DLC_3D_PORT=5050
  networks:
    - default
  restart: unless-stopped
```

No exposed host port. Only reachable via the main webapp's internal Docker network proxy.

---

## 6. Out of Scope

- Any changes to dlc-3D route logic or frame extraction behaviour
- Adding new features to the dlc-3D UI
- Modifying the main webapp's `app.py`, `base.html`, or proxy route
