# LP Video Add + Additive Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two LP project management features — (1) browse & add video files to `<lp>/videos/`, (2) sync a DLC project into an existing LP project additively without overwriting.

**Architecture:**
- New backend module `dlc_3d_bp/lp/video_adder.py` for video placement (symlink / copy / hardlink), separate from converter.
- Extend `convert_dlc_to_lp` with a `mode` parameter (`fresh` | `force` | `sync`) replacing the binary `force`.
- New POST endpoint `/dlc-3d/lp/videos/add`; existing `/dlc-3d/lp/convert` accepts `mode`.
- UI changes confined to `card_lp_convert.html` + `lp_cards.js` (reuse existing `/dlc-3d/browse` for navigation).

**Tech Stack:** Flask, pathlib, shutil, os.link / os.symlink. Tests via pytest + Flask test client. No new deps.

---

## File Structure

```
src/dlc_3d_bp/
  lp/
    video_adder.py          ← NEW: add_videos_to_lp() helper
    converter.py            ← MODIFY: convert_dlc_to_lp gains mode= param
  lp_routes.py              ← MODIFY: POST /lp/videos/add + /lp/convert mode

src/templates/partials/
  card_lp_convert.html      ← MODIFY: 3-way radio + new "Add videos" panel

src/static/
  lp_cards.js               ← MODIFY: wire the new panel + sync radio

tests/
  test_lp_video_adder.py    ← NEW
  test_lp_converter.py      ← MODIFY: add sync-mode coverage
  test_lp_routes.py         ← MODIFY: integration tests for both endpoints
```

---

### Task 1: video_adder module

**Files:**
- Create: `src/dlc_3d_bp/lp/video_adder.py`
- Test:   `tests/test_lp_video_adder.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lp_video_adder.py
import os
from pathlib import Path
import pytest
from dlc_3d_bp.lp.video_adder import add_videos_to_lp


def _make_lp(tmp_path: Path) -> Path:
    lp = tmp_path / "lp_proj"
    lp.mkdir()
    (lp / "config.yaml").write_text("data: {}\n")
    (lp / "videos").mkdir()
    return lp


def test_symlink_mode_creates_symlinks(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake")
    out = add_videos_to_lp(lp, [src], mode="symlink")
    assert out["added"] == [str(lp / "videos" / "src.mp4")]
    assert out["skipped"] == []
    dst = lp / "videos" / "src.mp4"
    assert dst.is_symlink()
    assert os.readlink(dst) == str(src)


def test_copy_mode_creates_real_files(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"contents")
    out = add_videos_to_lp(lp, [src], mode="copy")
    dst = lp / "videos" / "src.mp4"
    assert not dst.is_symlink()
    assert dst.read_bytes() == b"contents"
    assert out["added"] == [str(dst)]


def test_hardlink_mode_links_on_same_fs(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    out = add_videos_to_lp(lp, [src], mode="hardlink")
    dst = lp / "videos" / "src.mp4"
    # On the same filesystem hardlink should succeed → same inode
    assert dst.stat().st_ino == src.stat().st_ino
    assert out["added"] == [str(dst)]


def test_skip_existing_destination(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"a")
    (lp / "videos" / "src.mp4").write_bytes(b"already-there")
    out = add_videos_to_lp(lp, [src], mode="symlink")
    assert out["added"] == []
    assert out["skipped"] == [str(lp / "videos" / "src.mp4")]
    # Existing file untouched
    assert (lp / "videos" / "src.mp4").read_bytes() == b"already-there"


def test_rejects_non_lp_project(tmp_path):
    not_lp = tmp_path / "not_lp"
    not_lp.mkdir()
    src = tmp_path / "v.mp4"; src.write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        add_videos_to_lp(not_lp, [src], mode="symlink")


def test_missing_source_video_reported_as_error(tmp_path):
    lp = _make_lp(tmp_path)
    out = add_videos_to_lp(lp, [tmp_path / "ghost.mp4"], mode="symlink")
    assert out["added"] == []
    assert out["skipped"] == []
    assert len(out["errors"]) == 1
    assert "ghost.mp4" in out["errors"][0]


def test_invalid_mode_raises(tmp_path):
    lp = _make_lp(tmp_path)
    src = tmp_path / "v.mp4"; src.write_bytes(b"x")
    with pytest.raises(ValueError):
        add_videos_to_lp(lp, [src], mode="bogus")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_lp_video_adder.py -v`
Expected: `ModuleNotFoundError: No module named 'dlc_3d_bp.lp.video_adder'`

- [ ] **Step 3: Implement the module**

```python
# src/dlc_3d_bp/lp/video_adder.py
"""Place video files into an LP project's videos/ directory."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Iterable

_VALID_MODES = {"symlink", "copy", "hardlink"}


def add_videos_to_lp(
    lp_dir: Path | str,
    video_paths: Iterable[Path | str],
    mode: str = "symlink",
) -> dict:
    """Add videos to ``<lp_dir>/videos/`` without overwriting.

    Args:
        lp_dir: LP project root (must contain config.yaml).
        video_paths: source video files to add.
        mode: 'symlink' (default) | 'copy' | 'hardlink'. hardlink falls back
            to copy when source/dest live on different filesystems.

    Returns:
        ``{"added": [<dst>...], "skipped": [<dst>...], "errors": [str, ...]}``

    Raises:
        FileNotFoundError: lp_dir is not an LP project (no config.yaml).
        ValueError: unknown ``mode``.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; expected one of {sorted(_VALID_MODES)}")

    lp_dir = Path(lp_dir).resolve()
    if not (lp_dir / "config.yaml").is_file():
        raise FileNotFoundError(f"not an LP project (no config.yaml): {lp_dir}")

    videos_dir = lp_dir / "videos"
    videos_dir.mkdir(exist_ok=True)

    added: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for raw in video_paths:
        src = Path(raw)
        if not src.is_file():
            errors.append(f"source missing: {src}")
            continue
        dst = videos_dir / src.name
        if dst.exists() or dst.is_symlink():
            skipped.append(str(dst))
            continue
        try:
            if mode == "symlink":
                # Resolve src to an absolute path so the symlink stays valid
                # regardless of where the worker reads it from.
                os.symlink(str(src.resolve()), str(dst))
            elif mode == "hardlink":
                try:
                    os.link(str(src), str(dst))
                except OSError:
                    shutil.copy2(str(src), str(dst))
            else:  # copy
                shutil.copy2(str(src), str(dst))
            added.append(str(dst))
        except OSError as e:
            errors.append(f"{src.name}: {e}")

    return {"added": added, "skipped": skipped, "errors": errors}
```

- [ ] **Step 4: Tests pass**

Run: `pytest tests/test_lp_video_adder.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dlc_3d_bp/lp/video_adder.py tests/test_lp_video_adder.py
git commit -m "feat(dlc-3d): add_videos_to_lp helper (symlink/copy/hardlink)"
```

---

### Task 2: /lp/videos/add route

**Files:**
- Modify: `src/dlc_3d_bp/lp_routes.py`
- Test:   `tests/test_lp_routes.py`

- [ ] **Step 1: Write failing tests** (append to test_lp_routes.py)

```python
def test_lp_videos_add_symlink(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    # Allow tmp_path as USER_DATA root for this test
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))

    lp = tmp_path / "proj"; lp.mkdir(); (lp / "config.yaml").write_text("d:{}\n"); (lp / "videos").mkdir()
    src = tmp_path / "v.mp4"; src.write_bytes(b"x")

    from src.app import app  # noqa
    # Use the lp_routes blueprint directly via a fresh flask app
    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/add",
               json={"lp_project": str(lp), "video_paths": [str(src)], "mode": "symlink"})
    assert r.status_code == 201
    j = r.get_json()
    assert j["added"] == [str(lp / "videos" / "v.mp4")]


def test_lp_videos_add_rejects_outside_user_data(tmp_path, monkeypatch):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", "/nope")
    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/videos/add",
               json={"lp_project": str(tmp_path / "proj"),
                     "video_paths": [str(tmp_path / "v.mp4")], "mode": "symlink"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run to confirm fail** (`pytest tests/test_lp_routes.py::test_lp_videos_add_symlink -v`)

- [ ] **Step 3: Implement endpoint**

Insert after the existing `/predict` route in lp_routes.py:

```python
@lp_bp.route("/videos/add", methods=["POST"])
def videos_add():
    from dlc_3d_bp.lp.video_adder import add_videos_to_lp

    body = request.get_json(force=True, silent=True) or {}
    lp = (body.get("lp_project") or "").strip()
    paths = body.get("video_paths") or []
    mode = (body.get("mode") or "symlink").strip().lower()

    if not lp:
        return jsonify({"error": "lp_project required"}), 400
    if not isinstance(paths, list) or not paths:
        return jsonify({"error": "video_paths (non-empty list) required"}), 400

    lp_p = Path(lp)
    if not _under_user_data(lp_p):
        return jsonify({"error": "lp_project must resolve under /user-data/"}), 403
    for v in paths:
        if not _under_user_data(Path(v)):
            return jsonify({"error": f"video path outside /user-data/: {v}"}), 403

    try:
        result = add_videos_to_lp(lp_p, [Path(v) for v in paths], mode=mode)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"lp_project": str(lp_p), **result}), 201
```

- [ ] **Step 4: Tests pass** (`pytest tests/test_lp_routes.py -v`)

- [ ] **Step 5: Commit**

```bash
git add src/dlc_3d_bp/lp_routes.py tests/test_lp_routes.py
git commit -m "feat(dlc-3d): POST /lp/videos/add endpoint"
```

---

### Task 3: Converter sync mode

**Files:**
- Modify: `src/dlc_3d_bp/lp/converter.py`
- Test:   `tests/test_lp_converter.py`

- [ ] **Step 1: Write failing tests** (append to test_lp_converter.py — read existing file first to match style/fixtures)

Tests to add:
1. `test_convert_sync_preserves_existing_config_yaml` — after a fresh convert, modify lp/config.yaml manually, run convert again with `mode="sync"`, verify config.yaml unchanged.
2. `test_convert_sync_appends_new_cam_csv_rows_without_dup` — add a new session in DLC, run sync, verify cam{N}.csv has the new rows but no duplicates of old rows.
3. `test_convert_sync_does_not_overwrite_existing_labeled_pngs` — touch a PNG in lp/labeled-data/*, run sync, verify mtime unchanged.
4. `test_convert_sync_adds_new_session_when_some_exist` — partial-pre-populated LP, then sync, verify NEW session appears.
5. `test_convert_force_still_overwrites` — back-compat: `force=True` (or `mode="force"`) still wipes.

- [ ] **Step 2: Run failing tests** (`pytest tests/test_lp_converter.py::test_convert_sync_preserves_existing_config_yaml -v`)

- [ ] **Step 3: Implement sync mode**

Change `convert_dlc_to_lp` signature:

```python
def convert_dlc_to_lp(
    dlc_dir,
    lp_dir,
    link_mode: str = "link",
    force: bool = False,        # deprecated alias for mode="force"
    mode: str | None = None,    # "fresh" (default) | "force" | "sync"
) -> dict:
```

Coerce `mode`:
```python
if mode is None:
    mode = "force" if force else "fresh"
if mode not in ("fresh", "force", "sync"):
    raise ValueError(f"invalid mode {mode!r}")
```

Apply mode semantics:
- `fresh`: existing behavior — raise if `lp_dir` is non-empty.
- `force`: existing behavior — proceed, overwrite.
- `sync`:
  - Do not raise on non-empty lp_dir.
  - When writing `<lp>/config.yaml`: skip if exists.
  - When writing `<lp>/sv-pretrain/config.yaml`: skip if exists. (And skip the whole sv-pretrain rebuild if dir already exists with a config.yaml.)
  - For `cam{N}.csv`: if file exists, parse existing rows, merge new rows by frame-path key (first column), keep existing rows verbatim, append only new ones.
  - `_link_or_copy` already early-returns on `dst.exists()` → labeled-data PNGs and videos already skip-existing. No change needed there.

Identify the cam-CSV writing call site in converter.py and gate it through a helper:

```python
def _write_or_merge_cam_csv(dst: Path, header: list[list[str]], rows: list[list[str]], mode: str) -> None:
    if mode != "sync" or not dst.is_file():
        _write_csv(dst, header + rows)
        return
    # Sync: merge by first-column key, existing rows win
    import csv
    existing_keys: set[str] = set()
    existing_lines: list[list[str]] = []
    with dst.open() as f:
        for row in csv.reader(f):
            existing_lines.append(row)
            # Skip 3-row LP MultiIndex header
            if len(existing_lines) <= 3:
                continue
            if row:
                existing_keys.add(row[0])
    new_rows = [r for r in rows if r and r[0] not in existing_keys]
    _write_csv(dst, existing_lines + new_rows)
```

Locate where cam csvs are written in `convert_dlc_to_lp` (search for `cam` + `.csv`) and route through `_write_or_merge_cam_csv` when `mode == "sync"`.

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```bash
git add src/dlc_3d_bp/lp/converter.py tests/test_lp_converter.py
git commit -m "feat(dlc-3d): converter sync mode (additive DLC→LP without overwrite)"
```

---

### Task 4: /lp/convert accepts mode

**Files:**
- Modify: `src/dlc_3d_bp/lp_routes.py`
- Test:   `tests/test_lp_routes.py`

- [ ] **Step 1: Failing test**

```python
def test_lp_convert_sync_mode_passes_through(monkeypatch, tmp_path):
    from dlc_3d_bp import lp_routes
    monkeypatch.setattr(lp_routes, "_USER_DATA_ROOT", str(tmp_path))

    received = {}
    def fake_convert(dlc, lp, **kwargs):
        received["dlc"] = str(dlc); received["lp"] = str(lp); received["kwargs"] = kwargs
        return {"output_dir": str(lp), "n_sessions": 0, "n_views": 0, "warnings": []}
    monkeypatch.setattr("dlc_3d_bp.lp.converter.convert_dlc_to_lp", fake_convert)

    dlc = tmp_path / "dlc"; dlc.mkdir(); (dlc / "config.yaml").write_text("")
    lp  = tmp_path / "lp";  lp.mkdir()

    from flask import Flask
    a = Flask(__name__); a.register_blueprint(lp_routes.lp_bp)
    c = a.test_client()
    r = c.post("/dlc-3d/lp/convert",
               json={"dlc_dir": str(dlc), "lp_dir": str(lp), "mode": "sync"})
    assert r.status_code == 201
    assert received["kwargs"].get("mode") == "sync"
```

- [ ] **Step 2: Run failing test**

- [ ] **Step 3: Implement** — update `/lp/convert` route in `lp_routes.py`:

```python
body = request.get_json(force=True, silent=True) or {}
dlc = (body.get("dlc_dir") or "").strip()
lp  = (body.get("lp_dir") or "").strip()
force = bool(body.get("force", False))
mode  = (body.get("mode") or ("force" if force else "fresh")).strip().lower()
if mode not in ("fresh", "force", "sync"):
    return jsonify({"error": f"invalid mode {mode!r}"}), 400
...
summary = convert_dlc_to_lp(dlc_p, lp_p, mode=mode)
```

- [ ] **Step 4: Test passes**

- [ ] **Step 5: Commit**

```bash
git add src/dlc_3d_bp/lp_routes.py tests/test_lp_routes.py
git commit -m "feat(dlc-3d): /lp/convert accepts mode=fresh|force|sync"
```

---

### Task 5: UI — sync radio + add-videos panel

**Files:**
- Modify: `src/templates/partials/card_lp_convert.html`
- Modify: `src/static/lp_cards.js`

No unit tests for the UI (vanilla JS, no test runner). Manual smoke-test as part of Step 5.

- [ ] **Step 1: Replace the overwrite checkbox with a radio group**

Existing block in `card_lp_convert.html`:
```html
<div class="lp-field lp-checkbox">
  <input type="checkbox" id="lp-convert-force">
  <label for="lp-convert-force">Overwrite if target directory is not empty</label>
</div>
```

Replace with:
```html
<fieldset class="lp-field">
  <legend>Convert mode</legend>
  <label><input type="radio" name="lp-convert-mode" value="fresh" checked> Fresh — fail if target not empty</label>
  <label><input type="radio" name="lp-convert-mode" value="force"> Force — overwrite all existing files</label>
  <label><input type="radio" name="lp-convert-mode" value="sync"> Sync — add new only, keep existing</label>
</fieldset>
```

- [ ] **Step 2: Add a videos panel above the run button**

Append before `<button class="btn-primary" id="btn-lp-convert-run">Run conversion</button>`:

```html
<details class="lp-field" id="lp-add-videos-section">
  <summary style="cursor:pointer;font-weight:500">Add videos to LP project</summary>
  <p class="subtitle" style="margin-top:.4rem">Browse for video files and place them under <code style="font-family:var(--mono);font-size:.7rem">&lt;lp&gt;/videos/</code>. Files that already exist are skipped (never overwritten).</p>
  <div class="lp-field">
    <label>LP project</label>
    <input type="text" id="lp-add-videos-project" placeholder="defaults to current convert target">
  </div>
  <div class="lp-field">
    <label>Mode</label>
    <select id="lp-add-videos-mode">
      <option value="symlink" selected>symlink (recommended)</option>
      <option value="hardlink">hardlink (falls back to copy)</option>
      <option value="copy">copy</option>
    </select>
  </div>
  <div class="lp-field">
    <button class="btn-sm" id="btn-lp-add-videos-browse">Browse for videos…</button>
    <div id="lp-add-videos-browser" class="hidden" style="max-height:240px;overflow:auto;border:1px solid var(--border);border-radius:4px;padding:.4rem;margin-top:.4rem;background:var(--surface-2);font-family:var(--mono);font-size:.75rem"></div>
  </div>
  <div class="lp-field">
    <label>Queue (<span id="lp-add-videos-count">0</span>)</label>
    <ul id="lp-add-videos-queue" style="list-style:none;padding:0;margin:0;font-family:var(--mono);font-size:.75rem"></ul>
  </div>
  <button class="btn-primary" id="btn-lp-add-videos-run">Add videos</button>
  <pre class="lp-result" id="lp-add-videos-result" hidden></pre>
</details>
```

- [ ] **Step 3: Wire up sync radio in `initConvertCard()` of lp_cards.js**

Locate the existing convert-run handler that reads `lp-convert-force`. Replace it to read the selected radio:

```javascript
const modeEl = () => document.querySelector('input[name="lp-convert-mode"]:checked')?.value || "fresh";
// in the run handler body, where `force: $("#lp-convert-force")?.checked` was sent:
const r = await fetch("/dlc-3d/lp/convert", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    dlc_dir: dlcEl?.value || undefined,
    lp_dir: dstEl?.value || undefined,
    mode: modeEl(),
  }),
});
```

- [ ] **Step 4: Wire up add-videos panel in `initConvertCard()`**

```javascript
const aProj   = $("#lp-add-videos-project");
const aMode   = $("#lp-add-videos-mode");
const aBrowse = $("#btn-lp-add-videos-browse");
const aList   = $("#lp-add-videos-browser");
const aQueueEl = $("#lp-add-videos-queue");
const aCountEl = $("#lp-add-videos-count");
const aRun    = $("#btn-lp-add-videos-run");
const aResult = $("#lp-add-videos-result");

let curPath = null;
const queue = new Set();

function renderQueue() {
  aQueueEl.innerHTML = "";
  Array.from(queue).forEach(p => {
    const li = document.createElement("li");
    li.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.15rem 0";
    li.innerHTML = `<button class="btn-sm" data-remove>−</button> <span>${p}</span>`;
    li.querySelector("[data-remove]").addEventListener("click", () => { queue.delete(p); renderQueue(); });
    aQueueEl.appendChild(li);
  });
  aCountEl.textContent = String(queue.size);
}

async function loadDir(path) {
  curPath = path;
  const url = "/dlc-3d/browse" + (path ? "?path=" + encodeURIComponent(path) : "");
  const r = await fetch(url);
  const j = await r.json();
  if (!r.ok) { aList.textContent = "browse error: " + (j.error || r.status); return; }
  aList.innerHTML = "";
  const up = document.createElement("div");
  up.textContent = "../"; up.style.cssText = "cursor:pointer;color:var(--accent)";
  up.addEventListener("click", () => loadDir(j.parent_path || ""));
  aList.appendChild(up);
  (j.entries || []).forEach(e => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:.4rem;padding:.1rem 0";
    if (e.type === "dir") {
      const a = document.createElement("a");
      a.href = "#"; a.textContent = e.name + "/"; a.style.color = "var(--accent)";
      a.addEventListener("click", ev => { ev.preventDefault(); loadDir((j.current_path || curPath || "") + "/" + e.name); });
      row.appendChild(a);
    } else {
      const lower = (e.name || "").toLowerCase();
      const isVid = lower.endsWith(".mp4") || lower.endsWith(".avi") || lower.endsWith(".mov") || lower.endsWith(".mkv");
      const btn = document.createElement("button");
      btn.className = "btn-sm";
      btn.disabled = !isVid;
      btn.textContent = "+";
      btn.addEventListener("click", () => {
        const full = (j.current_path || curPath || "") + "/" + e.name;
        queue.add(full); renderQueue();
      });
      row.appendChild(btn);
      const span = document.createElement("span");
      span.textContent = e.name;
      if (!isVid) span.style.opacity = "0.5";
      row.appendChild(span);
    }
    aList.appendChild(row);
  });
}

aBrowse?.addEventListener("click", () => {
  aList.classList.toggle("hidden");
  if (!aList.classList.contains("hidden") && !curPath) {
    const seed = aProj?.value?.trim() || dstEl?.value?.trim() || "";
    loadDir(seed ? seed.replace(/\/+$/, "").split("/").slice(0, -1).join("/") : "");
  }
});

aRun?.addEventListener("click", async () => {
  const lp = aProj?.value?.trim() || dstEl?.value?.trim();
  if (!lp) { aResult.hidden = false; aResult.textContent = "specify LP project"; return; }
  if (!queue.size) { aResult.hidden = false; aResult.textContent = "queue is empty"; return; }
  aRun.disabled = true; aRun.textContent = "Adding…";
  try {
    const r = await fetch("/dlc-3d/lp/videos/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lp_project: lp, video_paths: Array.from(queue), mode: aMode.value }),
    });
    const j = await r.json();
    aResult.hidden = false;
    aResult.textContent = JSON.stringify(j, null, 2);
    if (r.ok) { queue.clear(); renderQueue(); }
  } catch (e) {
    aResult.hidden = false; aResult.textContent = "error: " + e.message;
  } finally {
    aRun.disabled = false; aRun.textContent = "Add videos";
  }
});
```

- [ ] **Step 5: Smoke-test in container + commit**

After implementation:
```bash
# Restart dlc-3d flask so any template changes propagate (live-mount, but cached)
cd /home/sam/docker-images/deeplabcut-webapp-docker && docker compose restart dlc-3d
sleep 3
# Verify endpoint
docker compose exec dlc-3d python3 -c "
import urllib.request, json
b = json.loads(urllib.request.urlopen('http://localhost:5050/dlc-3d/lp/health').read())
print('health:', b['ok'])
"
```

Commit:
```bash
git add src/templates/partials/card_lp_convert.html src/static/lp_cards.js
git commit -m "feat(dlc-3d): LP convert sync mode + add-videos panel UI"
```

---

### Task 6: Run full test suite

- [ ] `pytest tests/ -x -q` from project root. Expected: 0 failures.

If any pre-existing test now fails, capture the failure and report — do NOT silently fix unrelated tests.

---

## Self-review checklist

- [x] No placeholders, no "TODO", no "similar to Task N".
- [x] Each task has complete code, expected output for failing tests, and a commit step.
- [x] Tests run before AND after implementation in each task (TDD).
- [x] `_link_or_copy` early-return on `dst.exists()` is identified as why labeled-data PNGs and videos don't need extra sync logic in Task 3.
- [x] back-compat: `force=True` still works as documented in existing tests.
- [x] No worker restart required (no celery task changes).
