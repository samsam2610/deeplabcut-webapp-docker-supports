# LP Manage-Videos Card — list, delete, and (moved-here) add

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** New "Manage LP Videos" card with list + delete. Move the existing "Add videos to LP project" section out of the Convert card into this new one.

**Architecture:**
- Backend: new lister module + delete helper; two new routes (`GET /lp/videos/list`, `POST /lp/videos/delete`).
- Frontend: new partial `card_lp_videos.html`; new launcher button; `lp_cards.js` gains `initVideosCard()`; the add-videos block leaves the Convert card.
- `docker-compose.yml` mounts the new partial (single-file bind-mount pattern).

**Tech stack:** Flask, pathlib, os.lstat/os.unlink, pytest with tmp_path, vanilla JS. No new deps.

---

## File Structure

```
src/dlc_3d_bp/lp/
  video_lister.py                       ← NEW: list_videos()
  video_adder.py                        ← MODIFY: add delete_videos_from_lp()

src/dlc_3d_bp/
  lp_routes.py                          ← MODIFY: GET /lp/videos/list, POST /lp/videos/delete

src/templates/partials/
  card_lp_videos.html                   ← NEW: list + delete + (moved) add panel
  card_lp_convert.html                  ← MODIFY: remove the add-videos <details> block
  card_lp_launcher.html                 ← MODIFY: add launcher button data-lp-target="lp-videos-card"

src/templates/
  dlc_3d.html                           ← MODIFY: {% include "partials/card_lp_videos.html" %}

src/static/
  lp_cards.js                           ← MODIFY: initVideosCard() + remove add-videos from initConvertCard()

../deeplabcut-webapp-docker/docker-compose.yml  ← MODIFY: mount card_lp_videos.html

tests/
  test_lp_video_lister.py               ← NEW
  test_lp_video_adder.py                ← MODIFY: append delete_videos_from_lp tests
  test_lp_routes.py                     ← MODIFY: integration tests for the new routes
```

---

### Task 1: Backend — list_videos helper

**Files:**
- Create: `src/dlc_3d_bp/lp/video_lister.py`
- Test:   `tests/test_lp_video_lister.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_lp_video_lister.py
import os
from pathlib import Path

import pytest
from dlc_3d_bp.lp.video_lister import list_videos


def _make_lp(tmp_path: Path) -> Path:
    lp = tmp_path / "lp_proj"
    lp.mkdir()
    (lp / "config.yaml").write_text("data: {}\n")
    (lp / "videos").mkdir()
    return lp


def test_empty_videos_dir(tmp_path):
    lp = _make_lp(tmp_path)
    assert list_videos(lp) == []


def test_list_regular_file(tmp_path):
    lp = _make_lp(tmp_path)
    f = lp / "videos" / "v.mp4"
    f.write_bytes(b"hello")
    [entry] = list_videos(lp)
    assert entry["name"] == "v.mp4"
    assert entry["is_symlink"] is False
    assert entry["target"] is None
    assert entry["target_exists"] is True
    assert entry["size_bytes"] == 5


def test_list_symlink_target_exists(tmp_path):
    lp = _make_lp(tmp_path)
    real = tmp_path / "real.mp4"; real.write_bytes(b"abc")
    link = lp / "videos" / "v.mp4"
    os.symlink(str(real), str(link))
    [entry] = list_videos(lp)
    assert entry["name"] == "v.mp4"
    assert entry["is_symlink"] is True
    assert entry["target"] == str(real)
    assert entry["target_exists"] is True
    assert entry["size_bytes"] == 3


def test_list_symlink_broken(tmp_path):
    lp = _make_lp(tmp_path)
    link = lp / "videos" / "v.mp4"
    os.symlink("/no/such/path.mp4", str(link))
    [entry] = list_videos(lp)
    assert entry["is_symlink"] is True
    assert entry["target"] == "/no/such/path.mp4"
    assert entry["target_exists"] is False
    assert entry["size_bytes"] is None  # can't stat — surface as null


def test_rejects_non_lp_project(tmp_path):
    not_lp = tmp_path / "not_lp"; not_lp.mkdir()
    with pytest.raises(FileNotFoundError):
        list_videos(not_lp)


def test_listing_sorted_by_name(tmp_path):
    lp = _make_lp(tmp_path)
    for name in ("c.mp4", "a.mp4", "b.mp4"):
        (lp / "videos" / name).write_bytes(b"")
    names = [e["name"] for e in list_videos(lp)]
    assert names == ["a.mp4", "b.mp4", "c.mp4"]
```

- [ ] **Step 2: Run failing tests** — `pytest tests/test_lp_video_lister.py -v`. Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/dlc_3d_bp/lp/video_lister.py
"""List entries in an LP project's videos/ directory.

Uses os.lstat so symlinks are reported as symlinks (even broken ones) and never
followed at listing time. The result is JSON-serialisable for the route layer.
"""
from __future__ import annotations
import os
from pathlib import Path


def list_videos(lp_dir: Path | str) -> list[dict]:
    """Return a sorted list of entries under ``<lp_dir>/videos/``.

    Each entry is::

        {
          "name":          str,           # basename
          "is_symlink":    bool,
          "target":        str | None,    # readlink result if symlink, else None
          "target_exists": bool,          # for symlinks: target resolves; for files: True
          "size_bytes":    int | None,    # stat().st_size; None for broken symlinks
        }

    Raises FileNotFoundError if lp_dir is not an LP project (no config.yaml).
    """
    lp_dir = Path(lp_dir).resolve()
    if not (lp_dir / "config.yaml").is_file():
        raise FileNotFoundError(f"not an LP project (no config.yaml): {lp_dir}")

    videos = lp_dir / "videos"
    if not videos.is_dir():
        return []

    out: list[dict] = []
    for entry in sorted(videos.iterdir()):
        is_link = entry.is_symlink()
        target: str | None = None
        target_exists: bool
        size: int | None
        if is_link:
            target = os.readlink(str(entry))
            try:
                st = entry.stat()        # follows the symlink
                target_exists = True
                size = st.st_size
            except OSError:
                target_exists = False
                size = None
        else:
            try:
                st = entry.stat()
                target_exists = True
                size = st.st_size
            except OSError:
                target_exists = False
                size = None
        out.append({
            "name":          entry.name,
            "is_symlink":    is_link,
            "target":        target,
            "target_exists": target_exists,
            "size_bytes":    size,
        })
    return out
```

- [ ] **Step 4: Pass** — `pytest tests/test_lp_video_lister.py -v` → 6 passed.

- [ ] **Step 5: Commit**
```bash
git add src/dlc_3d_bp/lp/video_lister.py tests/test_lp_video_lister.py
git commit -m "feat(dlc-3d): video_lister module — list videos/ entries (lstat-only)"
```

---

### Task 2: Backend — delete_videos_from_lp helper

**Files:**
- Modify: `src/dlc_3d_bp/lp/video_adder.py`
- Test:   `tests/test_lp_video_adder.py` (append)

The delete helper lives next to the add helper — both manipulate `<lp>/videos/`.

- [ ] **Step 1: Failing tests** — append to `tests/test_lp_video_adder.py`:

```python
def test_delete_symlink_does_not_follow_target(tmp_path):
    from dlc_3d_bp.lp.video_adder import delete_videos_from_lp
    lp = _make_lp(tmp_path)
    real = tmp_path / "real.mp4"; real.write_bytes(b"keep me")
    link = lp / "videos" / "v.mp4"
    os.symlink(str(real), str(link))

    out = delete_videos_from_lp(lp, ["v.mp4"])
    assert out["deleted"] == ["v.mp4"]
    assert out["missing"] == []
    assert out["errors"] == []
    assert not link.exists() and not link.is_symlink()
    # Target file untouched
    assert real.read_bytes() == b"keep me"


def test_delete_regular_file(tmp_path):
    from dlc_3d_bp.lp.video_adder import delete_videos_from_lp
    lp = _make_lp(tmp_path)
    f = lp / "videos" / "v.mp4"; f.write_bytes(b"")
    out = delete_videos_from_lp(lp, ["v.mp4"])
    assert out["deleted"] == ["v.mp4"]
    assert not f.exists()


def test_delete_broken_symlink(tmp_path):
    from dlc_3d_bp.lp.video_adder import delete_videos_from_lp
    lp = _make_lp(tmp_path)
    link = lp / "videos" / "broken.mp4"
    os.symlink("/no/such/path", str(link))
    out = delete_videos_from_lp(lp, ["broken.mp4"])
    assert out["deleted"] == ["broken.mp4"]
    assert not link.is_symlink()


def test_delete_missing_entry_reported(tmp_path):
    from dlc_3d_bp.lp.video_adder import delete_videos_from_lp
    lp = _make_lp(tmp_path)
    out = delete_videos_from_lp(lp, ["ghost.mp4"])
    assert out["deleted"] == []
    assert out["missing"] == ["ghost.mp4"]
    assert out["errors"] == []


def test_delete_rejects_path_traversal(tmp_path):
    from dlc_3d_bp.lp.video_adder import delete_videos_from_lp
    lp = _make_lp(tmp_path)
    sibling = tmp_path / "sibling"; sibling.mkdir()
    secret = sibling / "secret.txt"; secret.write_text("important")

    for bad in ("../sibling/secret.txt", "foo/bar.mp4", "/etc/passwd", ".."):
        with pytest.raises(ValueError):
            delete_videos_from_lp(lp, [bad])
    # Sibling untouched
    assert secret.is_file()


def test_delete_mixed_names(tmp_path):
    from dlc_3d_bp.lp.video_adder import delete_videos_from_lp
    lp = _make_lp(tmp_path)
    (lp / "videos" / "a.mp4").write_bytes(b"")
    (lp / "videos" / "b.mp4").write_bytes(b"")
    out = delete_videos_from_lp(lp, ["a.mp4", "ghost.mp4", "b.mp4"])
    assert out["deleted"] == ["a.mp4", "b.mp4"]
    assert out["missing"] == ["ghost.mp4"]
```

- [ ] **Step 2: Failing** — `pytest tests/test_lp_video_adder.py -v`.

- [ ] **Step 3: Implement** — add to `src/dlc_3d_bp/lp/video_adder.py`:

```python
def delete_videos_from_lp(lp_dir: Path | str, names: Iterable[str]) -> dict:
    """Unlink named entries from ``<lp_dir>/videos/``.

    Uses ``os.unlink`` (operates on the link, never the target). Rejects names
    containing ``/`` or ``..`` to prevent path traversal — only basenames in the
    videos/ dir are allowed.

    Returns::
        {"deleted": [str, ...], "missing": [str, ...], "errors": [str, ...]}

    Raises:
        FileNotFoundError: lp_dir is not an LP project.
        ValueError:        a name contains ``/`` or ``..``.
    """
    lp_dir = Path(lp_dir).resolve()
    if not (lp_dir / "config.yaml").is_file():
        raise FileNotFoundError(f"not an LP project (no config.yaml): {lp_dir}")

    videos = lp_dir / "videos"
    videos.mkdir(exist_ok=True)

    deleted: list[str] = []
    missing: list[str] = []
    errors:  list[str] = []

    for raw in names:
        if not raw or "/" in raw or ".." in raw.split(os.sep):
            raise ValueError(f"invalid name (path traversal disallowed): {raw!r}")
        path = videos / raw
        # Treat the entry as "exists" if it's a regular file, dir, OR symlink
        # (broken symlinks return False from .exists() but lstat works).
        try:
            os.lstat(str(path))
        except FileNotFoundError:
            missing.append(raw)
            continue
        try:
            os.unlink(str(path))
            deleted.append(raw)
        except OSError as e:
            errors.append(f"{raw}: {e}")

    return {"deleted": deleted, "missing": missing, "errors": errors}
```

- [ ] **Step 4: Pass** — `pytest tests/test_lp_video_adder.py -v` (existing + new).

- [ ] **Step 5: Commit**
```bash
git add src/dlc_3d_bp/lp/video_adder.py tests/test_lp_video_adder.py
git commit -m "feat(dlc-3d): delete_videos_from_lp — unlink-only, path-traversal guard"
```

---

### Task 3: Routes — GET list + POST delete

**Files:**
- Modify: `src/dlc_3d_bp/lp_routes.py`
- Test:   `tests/test_lp_routes.py`

- [ ] **Step 1: Failing tests** — append to `tests/test_lp_routes.py`:

```python
def test_videos_list_endpoint(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))
    lp = tmp_path / "proj"; lp.mkdir()
    (lp / "config.yaml").write_text("d:{}\n"); (lp / "videos").mkdir()
    (lp / "videos" / "a.mp4").write_bytes(b"123")

    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.get(f"/dlc-3d/lp/videos/list?lp_project={lp}")
    assert r.status_code == 200
    j = r.get_json()
    assert j["videos"][0]["name"] == "a.mp4"
    assert j["videos"][0]["size_bytes"] == 3


def test_videos_list_rejects_outside_user_data(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", "/nope")
    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.get(f"/dlc-3d/lp/videos/list?lp_project={tmp_path / 'proj'}")
    assert r.status_code == 403


def test_videos_delete_endpoint(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))
    lp = tmp_path / "proj"; lp.mkdir()
    (lp / "config.yaml").write_text("d:{}\n"); (lp / "videos").mkdir()
    (lp / "videos" / "v.mp4").write_bytes(b"")

    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/delete",
               json={"lp_project": str(lp), "video_names": ["v.mp4"]})
    assert r.status_code == 200
    assert r.get_json()["deleted"] == ["v.mp4"]
    assert not (lp / "videos" / "v.mp4").exists()


def test_videos_delete_path_traversal_400(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))
    lp = tmp_path / "proj"; lp.mkdir()
    (lp / "config.yaml").write_text(""); (lp / "videos").mkdir()
    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/delete",
               json={"lp_project": str(lp), "video_names": ["../escape.txt"]})
    assert r.status_code == 400
```

- [ ] **Step 2: Failing** — run those tests.

- [ ] **Step 3: Implement** — in `lp_routes.py`, append after the existing `videos/add` route:

```python
@lp_bp.route("/videos/list", methods=["GET"])
def videos_list():
    from dlc_3d_bp.lp.video_lister import list_videos

    lp = (request.args.get("lp_project") or "").strip()
    if not lp:
        return jsonify({"error": "lp_project required"}), 400
    lp_p = Path(lp)
    if not _under_user_data(lp_p):
        return jsonify({"error": "lp_project must resolve under /user-data/"}), 403
    try:
        videos = list_videos(lp_p)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"lp_project": str(lp_p), "videos": videos})


@lp_bp.route("/videos/delete", methods=["POST"])
def videos_delete():
    from dlc_3d_bp.lp.video_adder import delete_videos_from_lp

    body = request.get_json(force=True, silent=True) or {}
    lp = (body.get("lp_project") or "").strip()
    names = body.get("video_names") or []
    if not lp:
        return jsonify({"error": "lp_project required"}), 400
    if not isinstance(names, list) or not names:
        return jsonify({"error": "video_names (non-empty list) required"}), 400

    lp_p = Path(lp)
    if not _under_user_data(lp_p):
        return jsonify({"error": "lp_project must resolve under /user-data/"}), 403

    try:
        result = delete_videos_from_lp(lp_p, names)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"lp_project": str(lp_p), **result})
```

- [ ] **Step 4: Pass** — `pytest tests/test_lp_routes.py -v`.

- [ ] **Step 5: Commit**
```bash
git add src/dlc_3d_bp/lp_routes.py tests/test_lp_routes.py
git commit -m "feat(dlc-3d): GET /lp/videos/list + POST /lp/videos/delete"
```

---

### Task 4: New card template + launcher button + compose mount

**Files:**
- Create: `src/templates/partials/card_lp_videos.html`
- Modify: `src/templates/partials/card_lp_launcher.html` (one new button)
- Modify: `src/templates/dlc_3d.html` (one new {% include %})
- Modify: `../deeplabcut-webapp-docker/docker-compose.yml` (one new mount line)

- [ ] **Step 1: Create `card_lp_videos.html`**

```html
<section class="card dlc-theme hidden" id="lp-videos-card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
    <h2>Manage LP Videos</h2>
    <div style="display:flex;gap:.4rem">
      <button class="btn-sm" id="btn-lp-videos-refresh">Refresh</button>
      <button class="btn-sm" id="btn-close-lp-videos" title="Close">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        Close
      </button>
    </div>
  </div>
  <p class="subtitle">List, delete, and add videos under <code style="font-family:var(--mono);font-size:.78rem">&lt;lp&gt;/videos/</code>. Deleting a symlink removes only the link — the original file is never touched.</p>

  <div class="lp-field">
    <label>LP project</label>
    <input type="text" id="lp-videos-project" placeholder="defaults to the active DLC project's -LP/">
  </div>

  <!-- ── Current videos ─────────────────────────────────────────────── -->
  <fieldset class="lp-field">
    <legend>Current videos</legend>
    <div id="lp-videos-list" style="border:1px solid var(--border);border-radius:5px;background:var(--surface-2);max-height:280px;overflow-y:auto;padding:.3rem .4rem;font-size:.75rem;font-family:var(--mono)"></div>
    <div style="display:flex;gap:.4rem;margin-top:.4rem;align-items:center;flex-wrap:wrap">
      <button class="btn-sm" id="btn-lp-videos-select-all" title="Toggle all" style="opacity:.85">Toggle all</button>
      <button class="btn-sm" id="btn-lp-videos-delete" title="Delete selected entries (symlinks unlink the link, not the target)" style="opacity:.85;color:var(--accent)">Delete selected (<span id="lp-videos-selected-count">0</span>)</button>
      <span style="font-size:.7rem;color:var(--text-dim)">Selecting a symlink deletes only the shortcut.</span>
    </div>
  </fieldset>

  <!-- ── Add videos (moved from Convert card; same browser pattern as Predict) ── -->
  <details class="lp-field" id="lp-videos-add-section">
    <summary style="cursor:pointer;font-weight:500">Add videos to LP project</summary>
    <p class="subtitle" style="margin-top:.4rem">
      Browse for video files and place them under
      <code style="font-family:var(--mono);font-size:.7rem">&lt;lp&gt;/videos/</code>.
      Files that already exist are skipped (never overwritten).
    </p>
    <div class="lp-field">
      <label>Mode</label>
      <select id="lp-videos-add-mode" style="font-family:var(--mono);font-size:.78rem;padding:.3rem .5rem;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text)">
        <option value="symlink" selected>symlink (recommended)</option>
        <option value="hardlink">hardlink (falls back to copy)</option>
        <option value="copy">copy</option>
      </select>
    </div>
    <div class="lp-field">
      <label>Target (file or folder path)</label>
      <div style="display:flex;gap:.4rem">
        <input type="text" id="lp-videos-add-target" placeholder="/path/to/video.mp4  or  /path/to/folder"
          style="flex:1;font-family:var(--mono);font-size:.78rem;padding:.35rem .55rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text)" />
        <button class="btn-sm" id="lp-videos-add-up" style="padding:.2rem .45rem;font-size:.75rem" title="Go up one level">↑ Up</button>
        <button class="btn-sm" id="lp-videos-add-browse-btn" title="Browse for videos and folders">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          Browse
        </button>
      </div>
      <div id="lp-videos-add-browser" class="hidden" style="margin-top:.5rem;max-height:240px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.4rem .5rem;font-size:.77rem"></div>
      <div style="display:flex;gap:.4rem;margin-top:.4rem;align-items:center;flex-wrap:wrap">
        <button class="btn-sm" id="lp-videos-add-batch-add" style="opacity:.85">+ Add to queue</button>
        <button class="btn-sm" id="lp-videos-add-batch-clear" style="opacity:.7">✕ Clear queue</button>
        <span style="font-size:.72rem;color:var(--text-dim)">Single-click to highlight · double-click to add instantly</span>
      </div>
      <div id="lp-videos-add-batch-list" style="margin-top:.4rem;display:none;border:1px solid var(--border);border-radius:5px;background:var(--surface-2);max-height:140px;overflow-y:auto;padding:.3rem .4rem;font-size:.74rem;font-family:var(--mono)"></div>
    </div>
    <button class="btn-primary" id="btn-lp-videos-add-run">Add videos</button>
  </details>

  <pre class="lp-result" id="lp-videos-result" hidden></pre>
</section>
```

- [ ] **Step 2: Launcher button** — in `card_lp_launcher.html`, add a button next to the existing ones (mirror their pattern):

```html
<button class="inspect-btn lp-launcher-btn" data-lp-target="lp-videos-card">
  <span class="lp-launcher-icon">🎞️</span>
  Manage Videos
</button>
```

(Match whatever wrapper/grid the existing buttons use; if there's a specific layout container, append inside it. If launcher uses `<svg>` icons rather than emoji, mirror that style.)

- [ ] **Step 3: Include in dlc_3d.html** — add the include line, ideally next to the other LP card includes:

```jinja
{% include "partials/card_lp_videos.html" %}
```

- [ ] **Step 4: Compose mount** — in `../deeplabcut-webapp-docker/docker-compose.yml`, find the dlc-3d service's `volumes:` list and add (preserving the indentation style of neighboring entries):

```yaml
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_lp_videos.html:/app/templates/partials/card_lp_videos.html
```

Then restart dlc-3d so the bind-mount picks up the new file:
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose up -d dlc-3d
sleep 4
# Verify the partial is reachable
docker compose exec dlc-3d test -f /app/templates/partials/card_lp_videos.html && echo "mount OK"
```

(Use `docker compose up -d` not `restart` — `restart` doesn't recreate the container, so a new volume mount wouldn't take effect.)

- [ ] **Step 5: Commit**
```bash
git add src/templates/partials/card_lp_videos.html src/templates/partials/card_lp_launcher.html src/templates/dlc_3d.html
git -C /home/sam/docker-images/deeplabcut-webapp-docker add docker-compose.yml
git commit -m "feat(dlc-3d): Manage Videos card template + launcher + compose mount"
git -C /home/sam/docker-images/deeplabcut-webapp-docker commit -m "chore(dlc-3d): mount card_lp_videos.html partial"
```

Note: the supports repo and the main webapp repo are SEPARATE git repos. Commit each in its own root.

---

### Task 5: JS — initVideosCard + remove add-videos from Convert

**Files:**
- Modify: `src/static/lp_cards.js`
- Modify: `src/templates/partials/card_lp_convert.html` (remove the old <details> block)

- [ ] **Step 1: Add `initVideosCard()`** at the bottom of `lp_cards.js`, before the existing `initLpLauncher()` call. Use the canonical `makeFileBrowser` factory from `./components/file_browser.js`.

```javascript
function initVideosCard() {
  const card = $("#lp-videos-card");
  if (!card) return;

  const projectEl = $("#lp-videos-project");
  const listEl    = $("#lp-videos-list");
  const refreshEl = $("#btn-lp-videos-refresh");
  const selAllEl  = $("#btn-lp-videos-select-all");
  const delEl     = $("#btn-lp-videos-delete");
  const countEl   = $("#lp-videos-selected-count");
  const resEl     = $("#lp-videos-result");

  $("#btn-close-lp-videos")?.addEventListener("click", () => card.classList.add("hidden"));

  // Auto-fill project from the active DLC project (mirrors initPredictCard's logic)
  function syncProject() {
    const dlc = activeDlcProjectFromDom();
    const auto = dlc ? dlc.replace(/\/+$/, "") + "-LP" : "";
    if (!projectEl.value) projectEl.value = auto;
  }

  function fmtSize(n) {
    if (n === null || n === undefined) return "?";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0; let v = n;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
  }

  function selectedNames() {
    return Array.from(listEl.querySelectorAll('input[type="checkbox"]:checked'))
      .map(cb => cb.dataset.name);
  }
  function updateCount() {
    countEl.textContent = String(selectedNames().length);
  }

  async function refresh() {
    syncProject();
    const lp = projectEl.value.trim();
    if (!lp) {
      listEl.innerHTML = '<span style="color:var(--text-dim)">specify the LP project above</span>';
      return;
    }
    listEl.innerHTML = '<span style="color:var(--text-dim)">Loading…</span>';
    try {
      const r = await fetch(`/dlc-3d/lp/videos/list?lp_project=${encodeURIComponent(lp)}`);
      const body = await r.json();
      if (!r.ok) { listEl.innerHTML = `<span style="color:var(--text-dim)">error: ${body.error || r.status}</span>`; return; }
      const videos = body.videos || [];
      if (!videos.length) {
        listEl.innerHTML = '<span style="color:var(--text-dim)">(no videos)</span>';
        updateCount();
        return;
      }
      listEl.innerHTML = "";
      for (const v of videos) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:.4rem;padding:.1rem 0;border-bottom:1px solid rgba(255,255,255,.05)";
        const cb = document.createElement("input");
        cb.type = "checkbox"; cb.dataset.name = v.name; cb.style.cursor = "pointer";
        cb.addEventListener("change", updateCount);
        const name = document.createElement("span");
        name.textContent = v.name;
        name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
        const tag = document.createElement("span");
        tag.style.cssText = "font-size:.68rem;padding:0 .3rem;border-radius:3px";
        if (v.is_symlink) {
          tag.textContent = v.target_exists ? "symlink" : "symlink (broken)";
          tag.style.color = v.target_exists ? "var(--accent, #63b3ed)" : "var(--warn, #e2a050)";
          tag.style.background = "rgba(99,179,237,.12)";
        } else {
          tag.textContent = "file";
          tag.style.color = "var(--text-dim)";
        }
        const size = document.createElement("span");
        size.textContent = fmtSize(v.size_bytes);
        size.style.cssText = "color:var(--text-dim);font-size:.7rem;min-width:4rem;text-align:right";
        row.append(cb, name, tag, size);
        if (v.is_symlink && v.target) {
          row.title = `→ ${v.target}`;
        }
        listEl.appendChild(row);
      }
      updateCount();
    } catch (e) {
      listEl.innerHTML = `<span style="color:var(--text-dim)">error: ${e.message}</span>`;
    }
  }

  refreshEl?.addEventListener("click", refresh);

  selAllEl?.addEventListener("click", () => {
    const boxes = Array.from(listEl.querySelectorAll('input[type="checkbox"]'));
    if (!boxes.length) return;
    const anyUnchecked = boxes.some(b => !b.checked);
    boxes.forEach(b => { b.checked = anyUnchecked; });
    updateCount();
  });

  delEl?.addEventListener("click", async () => {
    const names = selectedNames();
    if (!names.length) { resEl.hidden = false; resEl.textContent = "Nothing selected."; return; }
    if (!confirm(`Delete ${names.length} entry/entries from <lp>/videos/?\nSymlinks unlink only the shortcut.`)) return;
    delEl.disabled = true; const oldText = delEl.innerHTML; delEl.textContent = "Deleting…";
    try {
      const r = await fetch("/dlc-3d/lp/videos/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lp_project: projectEl.value.trim(), video_names: names }),
      });
      const body = await r.json();
      resEl.hidden = false;
      resEl.textContent = JSON.stringify(body, null, 2);
      if (r.ok) await refresh();
    } catch (e) {
      resEl.hidden = false; resEl.textContent = "error: " + e.message;
    } finally {
      delEl.disabled = false; delEl.innerHTML = oldText;
      updateCount();
    }
  });

  // ── Add-videos section (moved from Convert card; same shape) ────────
  const avModeEl    = $("#lp-videos-add-mode");
  const avTargetEl  = $("#lp-videos-add-target");
  const avUpEl      = $("#lp-videos-add-up");
  const avBrowseEl  = $("#lp-videos-add-browse-btn");
  const avPaneEl    = $("#lp-videos-add-browser");
  const avBatchAdd  = $("#lp-videos-add-batch-add");
  const avBatchClr  = $("#lp-videos-add-batch-clear");
  const avBatchList = $("#lp-videos-add-batch-list");
  const avRunEl     = $("#btn-lp-videos-add-run");

  if (avTargetEl) {
    const avBrowser = makeFileBrowser({
      inputEl: avTargetEl, paneEl: avPaneEl, dirOnly: false,
      onPick: (p) => avAddToQueue(p),
    });
    const avQueue = [];

    function avRenderQueue() {
      if (!avQueue.length) {
        avBatchList.style.display = "none";
        avBatchList.innerHTML = "";
        return;
      }
      avBatchList.style.display = "block";
      avBatchList.innerHTML = "";
      avQueue.forEach((p, i) => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.1rem 0";
        const txt = document.createElement("span");
        txt.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap";
        txt.textContent = p;
        const rm = document.createElement("button");
        rm.className = "btn-sm"; rm.style.cssText = "padding:0 .35rem;font-size:.7rem;opacity:.6";
        rm.textContent = "×";
        rm.addEventListener("click", () => { avQueue.splice(i, 1); avRenderQueue(); });
        row.appendChild(txt); row.appendChild(rm);
        avBatchList.appendChild(row);
      });
    }
    function avAddToQueue(p) {
      p = (p || "").trim(); if (!p) return;
      if (!avQueue.includes(p)) avQueue.push(p);
      avRenderQueue();
    }

    avBatchAdd.addEventListener("click", () => avAddToQueue(avBrowser.getHighlighted() || avTargetEl.value));
    avBatchClr.addEventListener("click", () => { avQueue.length = 0; avRenderQueue(); });
    avBrowseEl.addEventListener("click", () => avBrowser.openAt(projectEl.value.trim() || "/user-data"));
    avUpEl.addEventListener("click", () => avBrowser.up());
    avTargetEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); avBrowser.browseDir(avTargetEl.value.trim()); avPaneEl.classList.remove("hidden"); }
    });

    avRunEl?.addEventListener("click", async () => {
      const lp = projectEl.value.trim();
      if (!lp) { resEl.hidden = false; resEl.textContent = "Specify the LP project above."; return; }
      const paths = avQueue.length ? avQueue.slice() : (avTargetEl.value.trim() ? [avTargetEl.value.trim()] : []);
      if (!paths.length) { resEl.hidden = false; resEl.textContent = "Queue at least one video."; return; }
      avRunEl.disabled = true; resEl.hidden = false; resEl.textContent = "Adding…";
      try {
        const r = await fetch("/dlc-3d/lp/videos/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lp_project: lp, video_paths: paths, mode: avModeEl.value || "symlink" }),
        });
        const body = await r.json();
        resEl.textContent = JSON.stringify(body, null, 2);
        if (r.ok) { avQueue.length = 0; avRenderQueue(); await refresh(); }
      } catch (e) {
        resEl.textContent = "error: " + e.message;
      } finally {
        avRunEl.disabled = false;
      }
    });
  }

  // Refresh whenever the card becomes visible (matches Jobs card pattern)
  new MutationObserver(() => {
    if (!card.classList.contains("hidden")) refresh();
  }).observe(card, { attributes: true, attributeFilter: ["class"] });

  // Also refresh when the active DLC project changes
  const upstream = document.getElementById("dlc-active-path");
  if (upstream) {
    new MutationObserver(() => { if (!card.classList.contains("hidden")) refresh(); })
      .observe(upstream, { childList: true, characterData: true, subtree: true });
  }
}

initVideosCard();
```

- [ ] **Step 2: Remove the add-videos block from `initConvertCard()`** — delete the section that wires `lp-add-videos-*` IDs (the block beginning `// ── Add-videos panel`). It now lives in `initVideosCard()`.

- [ ] **Step 3: Remove the add-videos `<details>` block from `card_lp_convert.html`** — the entire `<details id="lp-add-videos-section">…</details>` element. Convert card shrinks back to just the mode radio + run button + result.

- [ ] **Step 4: Restart dlc-3d** (single-file template mounts need recreation):
```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d
sleep 4
docker compose exec dlc-3d python3 -c "
import urllib.request
html = urllib.request.urlopen('http://localhost:5050/dlc-3d/').read().decode()
for tok in ('lp-videos-card', 'lp-videos-add-browse-btn', 'lp-videos-list', 'lp-add-videos-section'):
    print(f'  {tok}: {html.count(tok)}')
"
```

Expected: `lp-videos-card`, `lp-videos-add-browse-btn`, `lp-videos-list` each appear ≥1 time. `lp-add-videos-section` appears **0 times** (removed from Convert card).

- [ ] **Step 5: Commit**
```bash
git add src/static/lp_cards.js src/templates/partials/card_lp_convert.html
git commit -m "feat(dlc-3d): initVideosCard + remove add-videos from Convert card"
```

---

### Task 6: Full pytest

- [ ] `cd dlc-3D && pytest tests/ -q`

Baseline: same pre-existing e2e Playwright and dirty-`predict_runner.py`-driven failures. The 12+ new tests added by this plan must all pass. No NEW unrelated regressions.

---

## Self-review

- [x] **No new deps.** Pure Python + vanilla JS.
- [x] **Symlink semantics preserved everywhere.** Listing uses lstat (so broken links show up); deletion uses unlink (operates on the link, never the target).
- [x] **Path-traversal guard** in `delete_videos_from_lp` plus `_under_user_data` enforcement at the route layer.
- [x] **The compose change uses `up -d` not `restart`.** A volume-mount addition requires container recreation; `restart` would leave the new mount unloaded.
- [x] **JS reuses the canonical file_browser component** via `makeFileBrowser` — no inline copies. Static-analysis tests from prior policy plan still pass.
- [x] **The relative-symlink fix is explicitly out of scope** (separate concern). The Manage Videos card lets you delete the broken-from-Jupyter-perspective symlinks right inside the app, which is what the user asked for.
