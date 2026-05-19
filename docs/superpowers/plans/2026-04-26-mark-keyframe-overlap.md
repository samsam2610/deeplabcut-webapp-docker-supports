# Mark Current Frame as Keyframe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "📌 Set KF here" button to the clip player that updates a detection's keyframe in-place, with a backend overlap check against clips already on disk.

**Architecture:** Four files change — one new Flask route in `routes.py` (with unit tests), HTML additions to the player controls section, small wiring changes in `clip_cutter.js` (pass detection index to `loadClip`, id the clip-name span), and the core logic in `player.js` (new state, `applyNewKF`, button handlers). The `detections[]` array and `saveDetections()` are global in `clip_cutter.js` and accessible from `player.js` since both load on the same page.

**Tech Stack:** Flask/Python (backend), vanilla JS (frontend), pytest (tests)

---

## File Map

| File | Change |
|------|--------|
| `clip-cutter/routes.py` | Add `POST /clip-cutter/check-keyframe-overlap` |
| `clip-cutter/tests/test_routes.py` | Add 4 tests for the new route |
| `clip-cutter/templates/clip_cutter.html` | New buttons, KF counter, overlap warning container, CSS |
| `clip-cutter/static/clip_cutter.js` | Pass `idx` to `loadClip`; add `id` to clip-name element |
| `clip-cutter/static/player.js` | New state vars, updated `loadClip`, `applyNewKF`, button handlers |

---

## Task 1: Backend overlap-check endpoint

**Files:**
- Modify: `clip-cutter/routes.py` (after the `/extract` route, around line 412)
- Test: `clip-cutter/tests/test_routes.py`

The endpoint derives `clips_dir = Path(video_path).parent / Path(video_path).stem`, calls the existing `processor.get_known_key_frames(clips_dir)`, checks if `[key_frame−200, key_frame+599]` intersects any existing clip range, and returns the result. If `clips_dir` does not exist there are no clips yet — return `overlaps: false` without error.

- [ ] **Step 1: Write the failing tests**

Append to `clip-cutter/tests/test_routes.py`:

```python
def test_check_keyframe_overlap_missing_video_path(client):
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"key_frame": 500})
    assert resp.status_code == 422


def test_check_keyframe_overlap_no_clips_dir(client, tmp_path):
    video_path = str(tmp_path / "test_video.avi")
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"video_path": video_path, "key_frame": 500})
    assert resp.status_code == 200
    assert resp.get_json()["overlaps"] is False


def test_check_keyframe_overlap_no_overlap(client, tmp_path):
    clips_dir = tmp_path / "test_video"
    clips_dir.mkdir()
    # clip: start=300 (0-based) → kf=500, range [300, 1099]
    (clips_dir / "test_video_300_899_success.avi").touch()
    video_path = str(tmp_path / "test_video.avi")
    # new KF=2000, range [1800, 2599] — no overlap
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"video_path": video_path, "key_frame": 2000})
    assert resp.status_code == 200
    assert resp.get_json()["overlaps"] is False


def test_check_keyframe_overlap_with_conflict(client, tmp_path):
    clips_dir = tmp_path / "test_video"
    clips_dir.mkdir()
    # clip: start=300 (0-based) → kf=500, range [300, 1099]
    (clips_dir / "test_video_300_899_success.avi").touch()
    video_path = str(tmp_path / "test_video.avi")
    # new KF=600, range [400, 1199] — overlaps [300,1099] by min(1199,1099)-max(400,300)+1 = 700
    resp = client.post("/clip-cutter/check-keyframe-overlap",
                       json={"video_path": video_path, "key_frame": 600})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["overlaps"] is True
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["name"] == "test_video_300_899_success.avi"
    assert data["conflicts"][0]["overlap_frames"] == 700
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py::test_check_keyframe_overlap_missing_video_path \
  tests/test_routes.py::test_check_keyframe_overlap_no_clips_dir \
  tests/test_routes.py::test_check_keyframe_overlap_no_overlap \
  tests/test_routes.py::test_check_keyframe_overlap_with_conflict -v
```

Expected: 4 FAILs with 404 (route not found).

- [ ] **Step 3: Add the route to `routes.py`**

Insert after the `/extract` route (after line 411, the `return jsonify(result)` line):

```python
@bp.route("/check-keyframe-overlap", methods=["POST"])
def check_keyframe_overlap():
    body = request.get_json(force=True) or {}
    video_path = (body.get("video_path") or "").strip()
    key_frame = body.get("key_frame")
    if not video_path or key_frame is None:
        return jsonify({"error": "video_path and key_frame required"}), 422

    video_path = Path(video_path)
    clips_dir = video_path.parent / video_path.stem

    if not clips_dir.is_dir():
        return jsonify({"overlaps": False})

    known = processor.get_known_key_frames(clips_dir)

    new_start = key_frame - 200
    new_end = key_frame + 599
    conflicts = []
    for kf, stem in known.items():
        ex_start = kf - 200
        ex_end = kf + 599
        if new_start <= ex_end and new_end >= ex_start:
            overlap = min(new_end, ex_end) - max(new_start, ex_start) + 1
            conflicts.append({"name": stem + ".avi", "overlap_frames": overlap})

    if conflicts:
        return jsonify({"overlaps": True, "conflicts": conflicts})
    return jsonify({"overlaps": False})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/test_routes.py::test_check_keyframe_overlap_missing_video_path \
  tests/test_routes.py::test_check_keyframe_overlap_no_clips_dir \
  tests/test_routes.py::test_check_keyframe_overlap_no_overlap \
  tests/test_routes.py::test_check_keyframe_overlap_with_conflict -v
```

Expected: 4 PASSes.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/clip-cutter
python -m pytest tests/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/routes.py clip-cutter/tests/test_routes.py
git commit -m "feat(clip-cutter): add /check-keyframe-overlap endpoint"
```

---

## Task 2: HTML — new player controls and CSS

**Files:**
- Modify: `clip-cutter/templates/clip_cutter.html`

Add CSS for the new button variants and overlap warning, update the `#player-actions` row, and add the hidden overlap warning container.

- [ ] **Step 1: Add CSS rules**

In `clip_cutter.html`, find this block (around line 147–149):

```css
.player-btn { font-size: 11px; padding: 3px 10px; border-radius: 4px; cursor: pointer; border: 1px solid #30363d; background: transparent; color: #cdd9e5; }
.player-btn:hover { background: #30363d; }
.player-btn.active { border-color: #388bfd; color: #388bfd; }
```

Append immediately after `.player-btn.active { ... }`:

```css
.player-btn-blue { border-color: #388bfd; color: #388bfd; }
.player-btn-red { border-color: #da3633; color: #f85149; }
#player-overlap-warning { background: #161b22; border: 1px solid #da3633; border-radius: 6px; padding: 10px 12px; margin-top: 4px; flex-shrink: 0; }
#player-overlap-warning .ow-title { color: #f85149; font-size: 11px; font-weight: 600; margin-bottom: 4px; }
#player-overlap-warning .ow-body { font-size: 10px; color: #8b949e; margin-bottom: 8px; }
#player-overlap-warning .ow-body code { color: #e6edf3; background: #21262d; padding: 1px 4px; border-radius: 3px; }
#player-overlap-warning .ow-actions { display: flex; gap: 6px; }
```

- [ ] **Step 2: Update `#player-actions` and add warning container**

Find the current `#player-actions` block (around lines 316–319):

```html
          <div id="player-actions">
            <button class="player-btn" id="player-keyframe">&#8982; Key frame</button>
            <button class="player-btn active" id="player-loop">&#8617; Loop</button>
          </div>
```

Replace it with:

```html
          <div id="player-actions" style="display:flex;align-items:center;gap:6px;">
            <button class="player-btn" id="player-keyframe">&#8982; Key frame</button>
            <button class="player-btn active" id="player-loop">&#8617; Loop</button>
            <button class="player-btn" id="player-clip-start">&#9654; From clip start</button>
            <div style="flex:1"></div>
            <span style="font-size:10px;color:#768390;font-family:monospace;white-space:nowrap;">KF: <span id="player-kf-num">&#8212;</span></span>
            <button class="player-btn player-btn-blue" id="player-set-kf">&#128204; Set KF here</button>
          </div>
          <div id="player-overlap-warning" style="display:none;"></div>
```

- [ ] **Step 3: Verify the page loads without JS errors**

Open `http://localhost:5000` (or wherever the app runs) and confirm the player action row shows: `⤢ Key frame` | `↺ Loop` | `▶ From clip start` | `KF: —` | `📌 Set KF here`. No console errors.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/templates/clip_cutter.html
git commit -m "feat(clip-cutter): add Set KF Here and From Clip Start buttons to player"
```

---

## Task 3: `clip_cutter.js` — wire detection index to player

**Files:**
- Modify: `clip-cutter/static/clip_cutter.js`

Two small changes: pass `idx` when calling `loadClip`, and give the clip-name element a unique id so `player.js` can update it.

- [ ] **Step 1: Pass `idx` to `loadClip` in the card click handler**

In `buildResultCard` (around line 653–658), find:

```javascript
  card.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    document.querySelectorAll(".result-card").forEach((c) => c.classList.remove("active-preview"));
    card.classList.add("active-preview");
    if (typeof loadClip === "function") loadClip(d.video_path, d.frame_number);
  });
```

Replace the `loadClip` call:

```javascript
    if (typeof loadClip === "function") loadClip(d.video_path, d.frame_number, idx);
```

- [ ] **Step 2: Add `id` to the clip-name div in `buildResultCard`**

In `buildResultCard` (around line 606–619), find the `card.innerHTML` template. The `<div class="result-name">` line currently reads:

```javascript
    <div class="result-name"></div>
```

Change it to include the idx-based id:

```javascript
    <div class="result-name" id="card-clipname-${idx}"></div>
```

The full template block in context so the edit target is unambiguous (lines 606–619):

```javascript
  card.innerHTML = `
    <div class="result-meta">
      <div class="result-name"></div>
      <div class="result-info">
        Key frame <span class="kf-num"></span> &middot;
        <span class="match-pill ${isKnown ? "match-known" : "match-new"}"></span>
      </div>
      <div class="result-actions">
        <button class="btn-sm btn-green keep-btn">&#10003; Keep</button>
        <button class="btn-sm btn-red reject-btn">&#10007; Reject</button>
        <button class="btn-sm btn-blue add-btn">+ Add to template</button>
      </div>
    </div>
    <span class="sim-pill"></span>`;
```

Replace with:

```javascript
  card.innerHTML = `
    <div class="result-meta">
      <div class="result-name" id="card-clipname-${idx}"></div>
      <div class="result-info">
        Key frame <span class="kf-num"></span> &middot;
        <span class="match-pill ${isKnown ? "match-known" : "match-new"}"></span>
      </div>
      <div class="result-actions">
        <button class="btn-sm btn-green keep-btn">&#10003; Keep</button>
        <button class="btn-sm btn-red reject-btn">&#10007; Reject</button>
        <button class="btn-sm btn-blue add-btn">+ Add to template</button>
      </div>
    </div>
    <span class="sim-pill"></span>`;
```

- [ ] **Step 3: Verify**

Load the page, run a scan (or load saved detections), click a result card — confirm the player opens. The card-clipname id will be verified when Task 4 is complete.

- [ ] **Step 4: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/clip_cutter.js
git commit -m "feat(clip-cutter): pass detection idx to loadClip; add card-clipname id"
```

---

## Task 4: `player.js` — Set KF Here logic

**Files:**
- Modify: `clip-cutter/static/player.js`

Add state, update `loadClip`, add `applyNewKF`, and wire up all three new button handlers. Note: `detections[]` and `saveDetections()` are globals from `clip_cutter.js`, accessible here because both scripts load on the same page.

- [ ] **Step 1: Add state variables**

At the top of `player.js`, after line 12 (`let _playerTimeoutId = null;`), insert:

```javascript
let _playerDetectionIdx = null;
let _pendingKF = null;
```

- [ ] **Step 2: Update `loadClip` to accept and store `detectionIdx`, and show KF counter**

The current `loadClip` signature on line 14:

```javascript
async function loadClip(videoPath, keyFrame1Based) {
```

Replace with:

```javascript
async function loadClip(videoPath, keyFrame1Based, detectionIdx = null) {
```

Inside `loadClip`, after the line `_playerKeyFrame = kf0;` (line 24), insert:

```javascript
  _playerDetectionIdx = detectionIdx;
  document.getElementById("player-kf-num").textContent = keyFrame1Based;
  document.getElementById("player-overlap-warning").style.display = "none";
  _pendingKF = null;
```

- [ ] **Step 3: Add `applyNewKF` function**

After the closing `}` of `loadClip` and before `async function _playerLoadFrame`, insert:

```javascript
function applyNewKF(kf1) {
  if (_playerDetectionIdx === null) return;
  detections[_playerDetectionIdx].frame_number = kf1;
  const kf0 = kf1 - 1;
  _playerKeyFrame = kf0;
  _playerClipStart = Math.max(0, kf0 - 200);
  _playerClipEnd = Math.min(_playerFrameCount - 1, kf0 + 599);
  _pendingKF = null;
  document.getElementById("player-kf-num").textContent = kf1;
  document.getElementById("player-overlap-warning").style.display = "none";
  const nameEl = document.getElementById(`card-clipname-${_playerDetectionIdx}`);
  if (nameEl) {
    const d = detections[_playerDetectionIdx];
    const videoName = d.video_path.split("/").pop().replace(".avi", "");
    nameEl.textContent = `${videoName}_${kf1 - 200}_${kf1 + 599}.avi`;
  }
  if (typeof saveDetections === "function") saveDetections();
}
```

- [ ] **Step 4: Add button handlers inside the `DOMContentLoaded` listener**

Inside the `document.addEventListener("DOMContentLoaded", () => { ... })` block at the bottom of `player.js`, after the existing `player-seek` handler (after line 145's closing `});`), insert before the final `});` of DOMContentLoaded:

```javascript
  document.getElementById("player-set-kf").addEventListener("click", async () => {
    if (_playerVideoPath === null || _playerDetectionIdx === null) return;
    const kf1 = _playerCurrentFrame + 1;
    _pendingKF = kf1;
    let data;
    try {
      const resp = await fetch("/clip-cutter/check-keyframe-overlap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_path: _playerVideoPath, key_frame: kf1 }),
      });
      if (!resp.ok) { setStatus("Overlap check failed"); return; }
      data = await resp.json();
    } catch (e) {
      setStatus("Network error: " + e.message);
      return;
    }
    if (!data.overlaps) {
      applyNewKF(kf1);
      return;
    }
    const conflict = data.conflicts[0];
    const warning = document.getElementById("player-overlap-warning");
    warning.innerHTML = "";
    const title = document.createElement("div");
    title.className = "ow-title";
    title.textContent = "⚠ Overlap detected";
    const body = document.createElement("div");
    body.className = "ow-body";
    const code = document.createElement("code");
    code.textContent = conflict.name;
    body.appendChild(document.createTextNode("New range overlaps "));
    body.appendChild(code);
    body.appendChild(document.createTextNode(` by ${conflict.overlap_frames} frames.`));
    const actions = document.createElement("div");
    actions.className = "ow-actions";
    const cancelBtn = document.createElement("button");
    cancelBtn.className = "player-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", () => {
      _pendingKF = null;
      warning.style.display = "none";
    });
    const keepBtn = document.createElement("button");
    keepBtn.className = "player-btn player-btn-red";
    keepBtn.textContent = "Keep anyway";
    keepBtn.addEventListener("click", () => applyNewKF(_pendingKF));
    actions.appendChild(cancelBtn);
    actions.appendChild(keepBtn);
    warning.appendChild(title);
    warning.appendChild(body);
    warning.appendChild(actions);
    warning.style.display = "";
  });

  document.getElementById("player-clip-start").addEventListener("click", () => {
    if (_playerVideoPath === null) return;
    _playerStop();
    _playerLoadFrame(_playerClipStart).then(() => {
      _playerPlaying = true;
      document.getElementById("player-play").textContent = "⏸";
      _playerLoop();
    });
  });
```

- [ ] **Step 5: Manual smoke test**

Run the app and verify the following:

1. Select a video with existing clips on disk. Run a scan or load saved detections.
2. Click a result card to open it in the player.
3. Confirm `#player-kf-num` shows the detection's frame number.
4. Navigate to a frame that would overlap an existing clip, click "📌 Set KF here" — overlap warning card appears with the conflict name and frame count.
5. Click "Cancel" — warning hides, `detections[idx].frame_number` unchanged, card name unchanged.
6. Click "📌 Set KF here" again at the same frame, then "Keep anyway" — detection updates, card clip-name label changes, warning hides.
7. Navigate to a frame with no overlap, click "📌 Set KF here" — updates immediately, no warning.
8. Click "▶ From clip start" — player seeks to `keyframe−200` and begins playing.
9. Click "✓ Keep" on the card after a KF update — confirm the extraction uses the new keyframe (check the output filename in the clips directory).

- [ ] **Step 6: Commit**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports
git add clip-cutter/static/player.js
git commit -m "feat(clip-cutter): implement Set KF Here with overlap check"
```
