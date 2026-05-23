# Inline 3D Viewer — clip-cutter Control Parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the inline 3D analysis card clip-cutter's full video-viewer control set — shift-aware keyboard shortcuts incl. play-backward, two-level frame skip, an always-visible status/note timeline, and clip creation (both cams) — by composing/extending the shared VideoViewer library, never forking the player.

**Architecture:** Library changes are minimal + additive (shift-aware `resolveKey`, a play-direction keyboard intent, auto-focus). The inline card composes the existing `clipExtractor` feature and surfaces the existing `statusNoteTimeline`. One new dlc-3d backend route does frame-exact clip trimming via the already-imported `cv2`.

**Tech Stack:** Browser ESM (no build), `node:test` for pure reducers, pytest static-analysis + Playwright e2e, Flask blueprint (`dlc_3d_bp`), OpenCV (`cv2`).

**Spec:** `docs/superpowers/specs/2026-05-23-inline-3d-viewer-control-parity-design.md`

**Reference (worked example):** `src/static/viewer_3d.js` is the migrated-consumer template; `card_viewer_3d.html`/`viewer_3d.css` show the vv-* patterns. clip-cutter's `routes.py:1132-1230` is the extract-route port source. The clipExtractor contract is documented at the top of `src/static/components/viewer/features/clip_extractor.js`.

**Global constraints:**
- Do NOT write into `/user-data/...` fixtures during testing. Verify clip extraction against a scratch path, or rely on the backend unit test.
- Template (`.html`) edits need `docker compose restart dlc-3d` to serve (Jinja cache); static JS/CSS hot-reload.
- Live app at `http://localhost:5000/dlc-3d/`, token `deeplabcut`, project `/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07`, fixture video `OM-2_cam0_20260424...` in `/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/042426` (has sibling + h5).
- All paths below are relative to `deeplabcut-webapp-docker-supports/dlc-3D/` unless noted. The git repo root is `deeplabcut-webapp-docker-supports/` (commit with `dlc-3D/...` paths).

---

## File Structure

- `src/static/components/viewer/internal/controls.mjs` — extend `resolveKey` (shift-aware + play-back intent). [Task 1]
- `tests/unit/test_viewer_controls.mjs` — keymap tests. [Task 1]
- `src/static/components/viewer/video_viewer.js` — keydown passes `shiftKey`, handles `playPauseDir`, `Space` forces forward; auto-focus on load. [Task 2]
- `tests/test_video_viewer_base.py` — static contract for the new base behavior. [Task 2]
- `src/templates/partials/card_inline_analysis_3d.html` — skip presets, move timeline out of curation, clip-extract panel, shortcuts help. [Tasks 3,4,6-fe,5]
- `src/static/inline_analysis_3d.js` — wire skip presets, compose clipExtractor, shortcuts help. [Tasks 3,5,7]
- `src/static/inline_analysis_3d.css` — size-row left-align, clip panel + help styling. [Task 5,7]
- `src/dlc_3d_bp/routes.py` — `POST /extract-clip`, `/extract-clip/rename`, `/extract-clip/delete`. [Task 6]
- `tests/test_extract_clip_route.py` — backend route tests. [Task 6]
- `tests/test_inline_analysis_3d_ui_isolation.py` — frontend contract additions. [Tasks 3,4,5,7]

---

## Task 1: Shift-aware keymap (library reducer)

**Files:**
- Modify: `src/static/components/viewer/internal/controls.mjs` (`resolveKey`)
- Test: `tests/unit/test_viewer_controls.mjs`

- [ ] **Step 1: Write failing tests** — append to `tests/unit/test_viewer_controls.mjs`:

```javascript
test("shift+space → play backward; shift+arrows → skip step", () => {
  assert.deepEqual(resolveKey({ key: " ", shiftKey: true }), { type: "playPauseDir", dir: -1 });
  assert.deepEqual(resolveKey({ key: "Spacebar", shiftKey: true }), { type: "playPauseDir", dir: -1 });
  assert.deepEqual(resolveKey({ key: "ArrowLeft", shiftKey: true }),  { type: "stepSkip", dir: -1 });
  assert.deepEqual(resolveKey({ key: "ArrowRight", shiftKey: true }), { type: "stepSkip", dir: 1 });
  // plain space stays forward toggle
  assert.deepEqual(resolveKey({ key: " " }), { type: "playPause" });
});
```

- [ ] **Step 2: Run, verify it fails**

Run: `node --test tests/unit/test_viewer_controls.mjs`
Expected: FAIL (resolveKey returns `{type:"playPause"}` for shift+space, not `playPauseDir`).

- [ ] **Step 3: Implement** — replace the body of `resolveKey` in `controls.mjs` with:

```javascript
export function resolveKey({ key, ctrlKey = false, shiftKey = false }) {
  // "Spacebar" is the legacy key name some old WebViews send (pre-KeyboardEvent spec).
  if (key === " " || key === "Spacebar") {
    return shiftKey ? { type: "playPauseDir", dir: -1 } : { type: "playPause" };
  }
  if (key === "ArrowLeft") {
    return (ctrlKey || shiftKey) ? { type: "stepSkip", dir: -1 } : { type: "step", delta: -1 };
  }
  if (key === "ArrowRight") {
    return (ctrlKey || shiftKey) ? { type: "stepSkip", dir: 1 } : { type: "step", delta: 1 };
  }
  return null;
}
```

- [ ] **Step 4: Run, verify pass**

Run: `node --test tests/unit/test_viewer_controls.mjs`
Expected: PASS (all tests, including the existing space/arrow ones).

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/components/viewer/internal/controls.mjs dlc-3D/tests/unit/test_viewer_controls.mjs
git commit -m "feat(viewer): shift-aware keymap — Shift+Space play-back, Shift+arrow skip"
```

---

## Task 2: VideoViewer play-direction keyboard + auto-focus (library base)

**Files:**
- Modify: `src/static/components/viewer/video_viewer.js` (`_handleKeyDown`, `load`)
- Test: `tests/test_video_viewer_base.py` (static-analysis contract)

- [ ] **Step 1: Write failing contract test** — append to `tests/test_video_viewer_base.py`:

```python
def test_keydown_passes_shift_and_handles_playdir():
    src = (ROOT / "src" / "static" / "components" / "viewer" / "video_viewer.js").read_text()
    # keydown must forward shiftKey to resolveKey
    assert "shiftKey: e.shiftKey" in src, "keydown must pass shiftKey to resolveKey"
    # must handle the new play-direction intent
    assert 'intent.type === "playPauseDir"' in src, "base must handle playPauseDir intent"
    # plain Space must force forward direction before toggling
    assert "setPlayDir(1)" in src, "Space must set forward direction before toggling"

def test_load_autofocuses_mount():
    src = (ROOT / "src" / "static" / "components" / "viewer" / "video_viewer.js").read_text()
    assert "this.mount.focus" in src, "load() must auto-focus the mount so keyboard works without a click"
```

(Use the file's existing `ROOT` constant; if absent, add `from pathlib import Path` and `ROOT = Path(__file__).parent.parent`.)

- [ ] **Step 2: Run, verify it fails**

Run: `python -m pytest tests/test_video_viewer_base.py -q`
Expected: FAIL (the 2 new assertions).

- [ ] **Step 3: Implement** — in `video_viewer.js`, replace `_handleKeyDown` with:

```javascript
  _handleKeyDown(e) {
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    const intent = this._resolveKey({ key: e.key, ctrlKey: e.ctrlKey, shiftKey: e.shiftKey });
    if (!intent) return;
    e.preventDefault();
    if (intent.type === "playPause") { if (!this._playing) this.setPlayDir(1); this.togglePlay(); }
    else if (intent.type === "playPauseDir") {
      if (this._playing) this.pause();
      else { this.setPlayDir(intent.dir); this.play(); }
    }
    else if (intent.type === "step") this.step(intent.delta);
    else if (intent.type === "stepSkip") this.stepSkip(intent.dir);
  }
```

  And at the end of `load()` (after `await this.seek(0);`), add:

```javascript
    // Auto-focus so keyboard shortcuts work without an explicit click. Guarded:
    // only when no input/textarea is focused (don't steal focus while typing).
    const ae = this.mount.ownerDocument.activeElement;
    if (!ae || (ae.tagName !== "INPUT" && ae.tagName !== "TEXTAREA")) {
      try { this.mount.focus({ preventScroll: true }); } catch (_) { /* jsdom/no-op */ }
    }
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_video_viewer_base.py -q` → PASS.
Then `python -m pytest tests/e2e/test_analyzed_viewer.py -q` → still 15 passed (no regression; auto-focus is benign).

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/components/viewer/video_viewer.js dlc-3D/tests/test_video_viewer_base.py
git commit -m "feat(viewer): keyboard play-direction (Shift+Space) + auto-focus mount on load"
```

---

## Task 3: Skip-size presets on the inline card

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (controls row, near `#ia3d-skip-n`)
- Modify: `src/static/inline_analysis_3d.js` (`_wireViewerChrome`)
- Modify: `src/static/inline_analysis_3d.css`
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write failing contract test** — append to `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
def test_skip_presets_present_and_wired():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'class="ia3d-skip-preset"' in html, "skip-size preset buttons missing"
    js = JS.read_text()
    assert "ia3d-skip-preset" in js and "setSkipN" in js, "skip presets not wired to setSkipN"
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py::test_skip_presets_present_and_wired -q` → FAIL.

- [ ] **Step 3a: Add markup** — in `card_inline_analysis_3d.html`, immediately AFTER the `#ia3d-skip-n` input (the `<input type="number" id="ia3d-skip-n" ...>` element), insert:

```html
          <span class="ia3d-skip-presets" style="display:inline-flex;gap:.2rem">
            <button type="button" class="ia3d-skip-preset" data-n="1">1</button>
            <button type="button" class="ia3d-skip-preset" data-n="5">5</button>
            <button type="button" class="ia3d-skip-preset" data-n="10">10</button>
            <button type="button" class="ia3d-skip-preset" data-n="30">30</button>
          </span>
```

- [ ] **Step 3b: Wire** — in `inline_analysis_3d.js` `_wireViewerChrome`, after the existing `$("ia3d-skip-n")?.addEventListener("input", ...)` line, add:

```javascript
  // Skip-size presets (clip-cutter's quick step levels): set skip-N + mark active.
  const _syncSkipPresets = () => {
    const n = skipN();
    document.querySelectorAll("#inline-analysis-3d-card .ia3d-skip-preset").forEach((b) => {
      b.classList.toggle("active", parseInt(b.dataset.n, 10) === n);
    });
  };
  document.querySelectorAll("#inline-analysis-3d-card .ia3d-skip-preset").forEach((b) => {
    b.addEventListener("click", () => {
      const skip = $("ia3d-skip-n");
      if (skip) skip.value = b.dataset.n;
      v.setSkipN(parseInt(b.dataset.n, 10));
      _syncSkipPresets();
    });
  });
  $("ia3d-skip-n")?.addEventListener("input", _syncSkipPresets);
  _syncSkipPresets();
```

- [ ] **Step 3c: Style** — append to `inline_analysis_3d.css`:

```css
#inline-analysis-3d-card .ia3d-skip-preset {
  width: 28px; padding: 2px 0; font-size: .68rem; font-family: var(--mono);
  text-align: center; border: 1px solid var(--border); border-radius: 10px;
  background: transparent; color: var(--text-dim); cursor: pointer;
}
#inline-analysis-3d-card .ia3d-skip-preset.active { border-color: var(--accent); color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); }
```

- [ ] **Step 4: Run + restart + verify** — `python -m pytest tests/test_inline_analysis_3d_ui_isolation.py -q` → PASS. Then `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d` (template change).

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/src/static/inline_analysis_3d.js dlc-3D/src/static/inline_analysis_3d.css dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): skip-size presets on inline player"
```

---

## Task 4: Surface the status/note timeline out of the curation panel

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html`
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

**Context:** `statusNoteTimeline` is wired in `_ensureViewer` to ids `ia3d-status-canvas/note-canvas/status-chips/note-chips/status-bar-wrap/note-bar-wrap/status-prev-btn` etc. Those ids currently live inside `#ia3d-curation-controls > #ia3d-csv-bars`. Moving the `#ia3d-csv-bars` block to the viewer area (keeping the SAME ids) requires no JS change — `_ensureViewer`'s `$()` lookups resolve by id regardless of location.

- [ ] **Step 1: Write failing contract test** — append:

```python
def test_status_note_timeline_outside_curation_panel():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    cur_start = html.index('id="ia3d-curation-panel"')
    bars = html.index('id="ia3d-csv-bars"')
    # the timeline bars must appear BEFORE the curation panel (i.e. in the viewer area)
    assert bars < cur_start, "status/note timeline must be surfaced above the curation panel"
```

- [ ] **Step 2: Run, verify fail** — currently `#ia3d-csv-bars` is inside the curation panel (after `#ia3d-curation-panel`), so `bars < cur_start` is False → FAIL.

- [ ] **Step 3: Move the markup** — cut the entire `<div id="ia3d-csv-bars" ...> … </div>` block (status-bar-wrap + note-bar-wrap, ~`card_inline_analysis_3d.html` "Row 3b") out of `#ia3d-curation-controls` and paste it directly AFTER the `<span id="ia3d-status" ...></span>` line (which sits just below the controls/marker-edit area, before `#ia3d-curation-panel`). Wrap it so it's always in the viewer area:

```html
        <!-- Status / note timeline — always visible in the viewer (surfaced from curation) -->
        <div id="ia3d-viewer-timeline" style="margin-top:.5rem">
          <!-- (moved) the #ia3d-csv-bars block goes here verbatim -->
        </div>
```

  Leave the curation panel's `#ia3d-csv-section` (create-CSV / CSV-path display) where it is — only the `#ia3d-csv-bars` (bars+chips+nav) moves.

- [ ] **Step 4: Run + restart + verify** — contract PASS; `docker compose ... restart dlc-3d`; live-check (see Task 8) that the timeline shows on a video with a companion CSV without opening curation.

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): surface status/note timeline in inline viewer (out of curation panel)"
```

---

## Task 5: Size-slider left-align + shortcuts help

**Files:**
- Modify: `src/static/inline_analysis_3d.css`
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (help affordance)
- Modify: `src/static/inline_analysis_3d.js` (help toggle)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write failing contract test** — append:

```python
def test_size_row_left_aligned_and_help_present():
    css = (ROOT / "src" / "static" / "inline_analysis_3d.css").read_text()
    i = css.index(".vv-tile-size-row")
    assert "flex-start" in css[i:i+200], "size-row must be left-aligned (justify-content:flex-start)"
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    assert 'id="ia3d-help-btn"' in html and 'id="ia3d-help-tooltip"' in html, "shortcuts help missing"
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3a: Left-align** — in `inline_analysis_3d.css`, change the `#ia3d-viewer-mount .vv-tile-size-row` rule's `justify-content: flex-end;` to `justify-content: flex-start;`.

- [ ] **Step 3b: Help affordance** — in `card_inline_analysis_3d.html`, at the end of the controls row (`.fe-controls` div, after the time display), add:

```html
          <button type="button" id="ia3d-help-btn" class="btn-sm fe-ctrl-btn" title="Keyboard shortcuts" style="margin-left:auto">?</button>
          <div id="ia3d-help-tooltip" class="hidden" style="position:absolute;z-index:20;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:.5rem .7rem;font-size:.72rem;font-family:var(--mono);color:var(--text-dim);box-shadow:0 4px 16px rgba(0,0,0,.4)">
            <div><b>Space</b> play/pause · <b>Shift+Space</b> play backward</div>
            <div><b>← / →</b> step ±1 · <b>Shift+← / →</b> step ±skip</div>
            <div><b>Click frame #</b> jump to frame</div>
          </div>
```

- [ ] **Step 3c: Help toggle** — in `inline_analysis_3d.js` `_wireViewerChrome`, add:

```javascript
  const help = $("ia3d-help-btn"), helpTip = $("ia3d-help-tooltip");
  help?.addEventListener("click", (e) => { e.stopPropagation(); helpTip?.classList.toggle("hidden"); });
  document.addEventListener("click", () => helpTip?.classList.add("hidden"));
```

- [ ] **Step 4: Run + restart + verify** — contract PASS; restart; eyeball.

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d.css dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/src/static/inline_analysis_3d.js dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "fix(dlc-3d): left-align per-view slider + add shortcuts help"
```

---

## Task 6: Backend clip-extract route (frame-exact trim, both cams)

**Files:**
- Modify: `src/dlc_3d_bp/routes.py` (new routes + helper)
- Test: `tests/test_extract_clip_route.py`

**Context:** `routes.py` already imports `cv2`, `Path`, `Blueprint bp`, and has `_resolve_video_path(video_path, proj)` + `_find_sibling_on_filesystem(video_abs)`. Clips live in `<video_parent>/<video_stem>/clip_NNN<postfix>.avi` (dlc-3d clip-folder model). Frame-exact trim via cv2 (no ffmpeg dependency).

- [ ] **Step 1: Write failing tests** — create `tests/test_extract_clip_route.py`:

```python
from pathlib import Path
from src.dlc_3d_bp import routes as r


def test_clip_output_path_naming():
    # <parent>/<stem>/<stem>_<start>_<end>[_postfix].avi
    out = r._clip_output_path(Path("/data/vids/OM-2_cam0_x.avi"), 100, 50, "trial1")
    assert out.parent.name == "OM-2_cam0_x"
    assert out.name == "OM-2_cam0_x_100_150_trial1.avi", out.name
    out2 = r._clip_output_path(Path("/data/vids/v.avi"), 0, 10, "")
    assert out2.name == "v_0_10.avi", out2.name


def test_trim_frames_writes_expected_count(tmp_path):
    import cv2, numpy as np
    src = tmp_path / "src.avi"
    w = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"MJPG"), 20.0, (32, 24))
    for i in range(60):
        w.write(np.full((24, 32, 3), i % 255, dtype=np.uint8))
    w.release()
    out = tmp_path / "out.avi"
    n = r._trim_frames_cv2(src, out, start_frame=10, n_frames=15)
    assert n == 15
    cap = cv2.VideoCapture(str(out))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 15
    cap.release()
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_extract_clip_route.py -q` → FAIL (helpers undefined).

- [ ] **Step 3: Implement helpers + routes** — add to `routes.py`:

```python
import re as _re


def _clip_output_path(video_path: Path, start_frame: int, n_frames: int, postfix: str) -> Path:
    stem = video_path.stem
    end_frame = start_frame + n_frames
    name = f"{stem}_{start_frame}_{end_frame}"
    safe = "".join(c for c in (postfix or "") if c.isalnum() or c in "-_")[:64]
    if safe:
        name += f"_{safe}"
    return video_path.parent / stem / f"{name}.avi"


def _trim_frames_cv2(src: Path, out: Path, start_frame: int, n_frames: int) -> int:
    """Frame-exact trim [start_frame, start_frame+n_frames) → out. Returns frames written."""
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise ValueError(f"cannot open {src}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start_frame = max(0, start_frame)
    n_frames = max(0, min(n_frames, max(total - start_frame, 0)))
    out.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    written = 0
    for _ in range(n_frames):
        ok, frame = cap.read()
        if not ok:
            break
        vw.write(frame)
        written += 1
    vw.release()
    cap.release()
    return written


@bp.route("/extract-clip", methods=["POST"])
def extract_clip():
    body = request.get_json(force=True, silent=True) or {}
    proj = body.get("project") or request.args.get("project") or ""
    video_path = (body.get("video_path") or "").strip()
    start_frame = body.get("start_frame")
    n_frames = body.get("n_frames")
    if not video_path or start_frame is None or n_frames is None:
        return jsonify({"error": "video_path, start_frame, n_frames required"}), 400
    src = _resolve_video_path(video_path, proj) or Path(video_path)
    if not src.exists():
        return jsonify({"error": f"video not found: {src.name}"}), 404
    postfix = (body.get("postfix") or "").strip()
    try:
        out = _clip_output_path(src, int(start_frame), int(n_frames), postfix)
        written = _trim_frames_cv2(src, out, int(start_frame), int(n_frames))
        result = {"avi_path": str(out), "n_frames": written}
        # Optional sibling: trim the same range from the sibling cam if provided/resolvable.
        sib = (body.get("sibling_video") or "").strip()
        if sib:
            sib_src = _resolve_video_path(sib, proj) or Path(sib)
            if sib_src.exists():
                sib_out = _clip_output_path(sib_src, int(start_frame), int(n_frames), postfix)
                _trim_frames_cv2(sib_src, sib_out, int(start_frame), int(n_frames))
                result["sibling_avi_path"] = str(sib_out)
        return jsonify(result)
    except Exception as e:  # noqa: BLE001 — surface trim failures to the UI
        return jsonify({"error": str(e)}), 500


@bp.route("/extract-clip/rename", methods=["POST"])
def extract_clip_rename():
    body = request.get_json(force=True, silent=True) or {}
    avi_path = (body.get("avi_path") or "").strip()
    postfix = (body.get("postfix") or "").strip()
    if not avi_path:
        return jsonify({"error": "avi_path required"}), 400
    p = Path(avi_path)
    if not p.exists():
        return jsonify({"error": f"file not found: {p.name}"}), 404
    video_stem = p.parent.name
    m = _re.match(r"^_(\d+)_(\d+)", p.stem[len(video_stem):])
    if not m:
        return jsonify({"error": "cannot parse frame numbers from filename"}), 422
    new_stem = f"{video_stem}_{m.group(1)}_{m.group(2)}"
    safe = "".join(c for c in postfix if c.isalnum() or c in "-_")[:64]
    if safe:
        new_stem += f"_{safe}"
    new_avi = p.parent / f"{new_stem}.avi"
    if new_avi != p:
        p.rename(new_avi)
    return jsonify({"avi_path": str(new_avi)})


@bp.route("/extract-clip/delete", methods=["POST"])
def extract_clip_delete():
    body = request.get_json(force=True, silent=True) or {}
    avi_path = (body.get("avi_path") or "").strip()
    if not avi_path:
        return jsonify({"error": "avi_path required"}), 400
    p = Path(avi_path)
    if not p.exists():
        return jsonify({"error": f"file not found: {p.name}"}), 404
    p.unlink()
    return jsonify({"ok": True})
```

  NOTE on `_resolve_video_path`: confirm its signature in `routes.py:40` and match it (it takes `(video_path, proj)`); if `proj` isn't available in the request, the fallback `Path(video_path)` handles absolute paths (the inline card sends absolute paths).

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_extract_clip_route.py -q`
Expected: PASS (both tests). If imports fail, match the test's `from src.dlc_3d_bp import routes` to how other backend tests import (check an existing `tests/test_*` that imports from `src.dlc_3d_bp`); adjust the import path to the project's convention.

- [ ] **Step 5: Restart worker/module + commit** — the route is in the dlc-3d module: `docker compose -f ../../deeplabcut-webapp-docker/docker-compose.yml restart dlc-3d`.

```bash
git add dlc-3D/src/dlc_3d_bp/routes.py dlc-3D/tests/test_extract_clip_route.py
git commit -m "feat(dlc-3d): /extract-clip frame-exact trim route (both cams, clip-folder)"
```

---

## Task 7: Compose clipExtractor in the inline card

**Files:**
- Modify: `src/templates/partials/card_inline_analysis_3d.html` (clip panel)
- Modify: `src/static/inline_analysis_3d.js` (import + compose + inject endpoints + reset)
- Modify: `src/static/inline_analysis_3d.css` (clip panel styling)
- Test: `tests/test_inline_analysis_3d_ui_isolation.py`

**Context:** clipExtractor contract (top of `clip_extractor.js`): `els = { enable, panel, startInput, framesInput, endDisplay, postfixInput, extractBtn, renameBtn, deleteBtn, extractSibling?, tagsContainer?, addTagBtn?, newTagInput?, statusDisplay?, warning? }`; `endpoints = { extractClip, rename?, del?, overlap? }`. It reads `viewer.getTile(1).videoRel` for the sibling and `viewer.currentFrame()`/`frameCount()`. Enable-checkbox starts unchecked; panel hidden until enabled (consumer wires the reveal, mirroring how viewer_3d wires overlay/curation toggles).

- [ ] **Step 1: Write failing contract test** — append:

```python
def test_clip_extractor_composed():
    html = (ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html").read_text()
    for el in ("ia3d-clip-enable", "ia3d-clip-panel", "ia3d-clip-start",
               "ia3d-clip-frames", "ia3d-clip-extract-btn"):
        assert f'id="{el}"' in html, f"missing clip element {el}"
    # enable checkbox unchecked by default (no `checked` attr on the enable input)
    i = html.index('id="ia3d-clip-enable"')
    assert "checked" not in html[i-120:i+120], "clip-extract enable must be UNCHECKED by default"
    js = JS.read_text()
    assert "clipExtractor(" in js, "clipExtractor not composed"
    assert "/extract-clip" in js, "extractClip endpoint not injected"
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3a: Markup** — in `card_inline_analysis_3d.html`, add a clip panel after the Dataset Curation panel (mirror the curation panel's structure). Enable checkbox UNCHECKED; inner controls hidden:

```html
        <!-- ── Create Clip (trim current range, both cams) ──────────── -->
        <div id="ia3d-clip-panel-wrap" style="margin-top:.65rem;padding:.5rem .65rem;background:var(--surface-2);border:1px solid var(--border);border-radius:7px">
          <label style="display:flex;align-items:center;gap:.45rem;font-size:.8rem;font-weight:500;cursor:pointer;user-select:none">
            <input type="checkbox" id="ia3d-clip-enable" style="accent-color:var(--accent);width:14px;height:14px"/>
            Create Clip
          </label>
          <div id="ia3d-clip-panel" class="hidden" style="margin-top:.5rem;display:flex;flex-direction:column;gap:.4rem">
            <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;font-size:.78rem;color:var(--text-dim)">
              <label>start <input type="number" id="ia3d-clip-start" min="0" value="0" style="width:5.5rem;font-family:var(--mono);background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.2rem .3rem"></label>
              <label>length <input type="number" id="ia3d-clip-frames" min="1" value="800" style="width:5rem;font-family:var(--mono);background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.2rem .3rem"></label>
              <label>end <input type="number" id="ia3d-clip-end" readonly style="width:5.5rem;font-family:var(--mono);background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text-dim);padding:.2rem .3rem"></label>
              <label style="display:flex;align-items:center;gap:.3rem"><input type="checkbox" id="ia3d-clip-sibling" checked style="accent-color:var(--accent)">both cams</label>
            </div>
            <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">
              <input type="text" id="ia3d-clip-postfix" placeholder="postfix (optional)" style="flex:1;min-width:120px;font-size:.78rem;background:var(--surface);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:.22rem .4rem">
              <button class="btn-sm btn-create" id="ia3d-clip-extract-btn">Extract Clip</button>
              <button class="btn-sm" id="ia3d-clip-rename-btn" style="opacity:.8">Rename</button>
              <button class="btn-sm" id="ia3d-clip-delete-btn" style="opacity:.7">Delete</button>
            </div>
            <span id="ia3d-clip-status" class="fe-extract-status"></span>
          </div>
        </div>
```

- [ ] **Step 3b: Import + compose** — in `inline_analysis_3d.js`:
  - Add to the import block: `import { clipExtractor } from "./components/viewer/features/clip_extractor.js";`
  - In `_ensureViewer`, after the curation glue / other `_viewer.use(...)` calls, compose it:

```javascript
  // Clip creation (trim current range → <stem>/clip folder via /dlc-3d/extract-clip).
  _viewer.use(clipExtractor({
    storagePrefix: "ia3d",
    defaultFrames: 800,
    endpoints: {
      extractClip: (payload) => fetch("/dlc-3d/extract-clip", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      }),
      rename: (payload) => fetch("/dlc-3d/extract-clip/rename", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      }),
      del: (payload) => fetch("/dlc-3d/extract-clip/delete", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      }),
      // no `overlap` — no keyframes in the inline context.
    },
    els: {
      enable: $("ia3d-clip-enable"), panel: $("ia3d-clip-panel"),
      startInput: $("ia3d-clip-start"), framesInput: $("ia3d-clip-frames"),
      endDisplay: $("ia3d-clip-end"), postfixInput: $("ia3d-clip-postfix"),
      extractBtn: $("ia3d-clip-extract-btn"), renameBtn: $("ia3d-clip-rename-btn"),
      deleteBtn: $("ia3d-clip-delete-btn"), extractSibling: $("ia3d-clip-sibling"),
      statusDisplay: $("ia3d-clip-status"),
    },
  }));
```

  - VERIFY the clipExtractor's `extractClip` payload keys match the backend (`video_path`, `start_frame`, `n_frames`, `postfix`, `sibling_video`). Read `internal/clip_extract.mjs` `buildExtractRequest` to see the exact payload shape it emits, and adapt the injected `extractClip` closure to remap keys to the backend's names if they differ (e.g. wrap: `(p) => fetch(..., body: JSON.stringify({ video_path: p.video_path ?? p.videoPath, start_frame: p.start_fn ?? p.startFrame, n_frames: p.n_frames ?? p.frames, sibling_video: p.sibling, postfix: p.postfix }))`). This remap is REQUIRED if names differ — do not assume.

- [ ] **Step 3c: Style** (optional polish) — add any `.hidden` reliance is already covered; no new CSS strictly required.

- [ ] **Step 4: Run + restart + verify** — contract PASS; restart dlc-3d; live: enable checkbox reveals panel; (clip extraction itself verified in Task 8 against a scratch path only).

- [ ] **Step 5: Commit**

```bash
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html dlc-3D/src/static/inline_analysis_3d.js dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "feat(dlc-3d): compose clipExtractor on inline card (clip creation, both cams)"
```

---

## Task 8: Full live verification

**Files:** none (verification only). Use Playwright against the live app; mirror the driving pattern in prior verification scripts (auth → activate project → open `#btn-open-inline-analysis-3d` → Browse tab → select OM-2 cam0).

- [ ] **Step 1: Keyboard** — focus the viewer mount; assert `Space` toggles play (frame advances), `Shift+Space` plays backward (frame decreases), `→`/`←` step ±1, `Shift+→`/`Shift+←` step by skip-N. Capture frame numbers before/after.

- [ ] **Step 2: Skip presets** — click `5`, assert `#ia3d-skip-n` value=5 + the `5` preset has class `active`; a skip-fwd advances 5.

- [ ] **Step 3: Timeline surfaced** — on the OM-2 video (has companion CSV), assert `#ia3d-status-bar-wrap`/`#ia3d-note-bar-wrap` become visible WITHOUT checking `#ia3d-curation-toggle`.

- [ ] **Step 4: Size slider left** — assert the `.vv-tile-size-row` left edge ≈ the tile left edge (left-aligned).

- [ ] **Step 5: Clip panel** — check `#ia3d-clip-enable` → `#ia3d-clip-panel` visible; `#ia3d-clip-end` auto-updates from start+length. Do NOT click Extract against a `/user-data` video. (Backend trim is covered by Task 6's unit test.)

- [ ] **Step 6: No-regression** — `python -m pytest tests/e2e/test_analyzed_viewer.py -q` (15 passed), `node --test tests/unit/*.mjs` (14), `python -m pytest tests/test_video_viewer_policy.py tests/test_inline_analysis_3d_ui_isolation.py -q`.

- [ ] **Step 7: Commit** any test-script artifacts if kept (otherwise nothing to commit). Report results.

---

## Self-Review

**Spec coverage:** §1 keyboard → Tasks 1+2; §2 play fwd/back + multi-skip → Task 2 (keyboard) + Task 3 (presets); §3 timeline surfaced → Task 4; §4 clip creation → Tasks 6 (backend) + 7 (frontend); §5 size-left → Task 5; §6 help → Task 5. All covered.

**Type/name consistency:** keymap intent `playPauseDir{dir}` used in Task 1 (resolveKey) + Task 2 (`_handleKeyDown`). Backend helpers `_clip_output_path`/`_trim_frames_cv2` defined + tested in Task 6, called by routes in Task 6. clipExtractor `els`/`endpoints` keys taken from the feature's documented contract; Task 7 Step 3b explicitly flags verifying the `extractClip` payload key remap against `clip_extract.mjs` (the one place names could drift).

**Known risk flagged for implementers:** (a) `_resolve_video_path` signature + backend test import path must be matched to the repo's convention (Task 6 notes). (b) clipExtractor payload field names must be remapped to the backend's `{video_path,start_frame,n_frames,sibling_video,postfix}` (Task 7 notes).
