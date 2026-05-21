# 3D Inline Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "3D Inline Analysis" card to the dlc-3D page that runs DLC pose inference on both camera videos of a stereo pair over the same frame range (via the main webapp's warm inline-analysis worker) and shows per-camera markers on both tiles.

**Architecture:** Clone the existing `viewer_3d.js` + `card_viewer_3d.html` (the dual-camera marker viewer) into `inline_analysis_3d.js` + `card_inline_analysis_3d.html`, renaming `va3d-*` DOM ids → `ia3d-*` and `va*`/`_va*` JS identifiers → `ia*`/`_ia*`. Append a stereo analysis-dispatch IIFE that calls the main webapp's existing `/dlc/project/inline-analysis/*` API twice (cam0 + cam1) against one warm session. No main-webapp backend changes.

**Tech Stack:** Vanilla ES-module JS (no framework), Jinja2 partials, Flask (dlc-3D blueprint), the main webapp's Celery warm-worker (reused as-is), pytest + Playwright for verification.

**Spec:** `docs/superpowers/specs/2026-05-20-3d-inline-analysis-design.md`

**Repo / cwd:** `/home/sam/docker-images/deeplabcut-webapp-docker-supports` (branch `main`). All paths below are relative to the `dlc-3D/` module unless noted. Run shell commands from `dlc-3D/`.

---

## File structure

| Path | Responsibility |
|---|---|
| `src/static/inline_analysis_3d.js` | **new** — cloned dual-camera viewer (`ia*`) + stereo analysis-dispatch IIFE |
| `src/templates/partials/card_inline_analysis_3d.html` | **new** — cloned dual-tile card (`ia3d-*`) + analysis-params block |
| `src/templates/dlc_3d.html` | edit — include the new partial, add `<script>` tag, add the nav open button |
| `tests/test_inline_analysis_3d_ui_isolation.py` | **new** — static guards (clone parity, dispatch wiring, sibling-required) |
| `../deeplabcut-webapp-docker/docker-compose.yml` | edit — one bind-mount line for the new partial (live dev) |

Reference files (read-only): `src/static/viewer_3d.js` (3223 lines), `src/templates/partials/card_viewer_3d.html` (415 lines), and the 2D dispatch template at `../deeplabcut-webapp-docker/src/static/js/inline_analysis_player.js` (bottom IIFE).

---

## Task 1: Clone viewer_3d.js → inline_analysis_3d.js (rename)

**Files:**
- Create: `src/static/inline_analysis_3d.js` (from `src/static/viewer_3d.js`)

The clone keeps viewer_3d's logic verbatim, renaming only identifiers so it drives its own DOM and shares no globals. Renames:
- `va3d-` → `ia3d-` (DOM id literals, in quotes/backticks)
- bare `vaXxx` → `iaXxx` (camelCase JS identifiers; `\bva[A-Z]…`)
- `_vaXxx` → `_iaXxx` (covers `_va3d*` too)
- string ids that aren't `va`-prefixed identifiers: `view-analyzed-3d-card` → `inline-analysis-3d-card`, `btn-open-view-analyzed` → `btn-open-inline-analysis-3d`, `btn-close-view-analyzed-3d` → `btn-close-inline-analysis-3d`
- `__va3dController` → `__ia3dController`

- [ ] **Step 1: Write the rename script and run it**

Create `/tmp/clone_ia3d.py` and run it:

```python
import re
src = open("src/static/viewer_3d.js").read()
# 1) string ids that are NOT va-identifiers (do these BEFORE the va→ia pass)
src = src.replace("view-analyzed-3d-card", "inline-analysis-3d-card")
src = src.replace("btn-open-view-analyzed", "btn-open-inline-analysis-3d")
src = src.replace("btn-close-view-analyzed-3d", "btn-close-inline-analysis-3d")
src = src.replace("__va3dController", "__ia3dController")
# 2) DOM id literals va3d- → ia3d- (quotes + backticks)
src = src.replace("va3d-", "ia3d-")
# 3) JS identifiers: _vaXxx → _iaXxx  (covers _va3d* already turned to _ia... no:
#    _va3d* still starts with _va, handled here)
src = re.sub(r"\b_va([A-Za-z0-9_]*)", r"_ia\1", src)
# 4) bare camelCase vaXxx → iaXxx
src = re.sub(r"\bva([A-Z][A-Za-z0-9_]*)", r"ia\1", src)
open("src/static/inline_analysis_3d.js", "w").write(src)
print("wrote src/static/inline_analysis_3d.js")
```

Run: `python3 /tmp/clone_ia3d.py`
Expected: `wrote src/static/inline_analysis_3d.js`

- [ ] **Step 2: Verify the rename is complete and the file parses**

Run:
```bash
echo "leftover va3d- ids:  $(grep -c 'va3d-' src/static/inline_analysis_3d.js)"
echo "leftover \\bva[A-Z]:  $(grep -cE '\bva[A-Z]' src/static/inline_analysis_3d.js)"
echo "leftover \\b_va:      $(grep -cE '\b_va[A-Za-z]' src/static/inline_analysis_3d.js)"
echo "old card id:         $(grep -c 'view-analyzed-3d-card' src/static/inline_analysis_3d.js)"
node --input-type=module --check < src/static/inline_analysis_3d.js && echo "PARSE OK"
```
Expected: all four counts `0`, and `PARSE OK`.

If any count is non-zero, inspect those lines (`grep -nE '<pattern>' src/static/inline_analysis_3d.js`) and extend the rename script — do NOT hand-edit individual hits, fix the script and re-run so it stays reproducible.

- [ ] **Step 3: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d.js
git commit -m "feat(dlc-3d): clone viewer_3d.js -> inline_analysis_3d.js (va->ia rename)"
```

---

## Task 2: Clone card_viewer_3d.html → card_inline_analysis_3d.html + params block

**Files:**
- Create: `src/templates/partials/card_inline_analysis_3d.html` (from `src/templates/partials/card_viewer_3d.html`)

- [ ] **Step 1: Clone + rename the partial**

Create `/tmp/clone_ia3d_html.py` and run it:

```python
src = open("src/templates/partials/card_viewer_3d.html").read()
src = src.replace("view-analyzed-3d-card", "inline-analysis-3d-card")
src = src.replace("btn-close-view-analyzed-3d", "btn-close-inline-analysis-3d")
src = src.replace("va3d-", "ia3d-")
# Header text
src = src.replace("View Analyzed Videos / Frames", "3D Inline Analysis")
src = src.replace(
    "Browse and play labeled videos or frame-by-frame labeled image folders produced by the analysis step.",
    "Scrub a stereo pair, run DLC on N frames forward on BOTH cameras against a warm model, and view the results on both views immediately.",
)
open("src/templates/partials/card_inline_analysis_3d.html", "w").write(src)
print("wrote card_inline_analysis_3d.html")
```

Run: `python3 /tmp/clone_ia3d_html.py`
Expected: `wrote card_inline_analysis_3d.html`

- [ ] **Step 2: Inject the analysis-params block**

Open `src/templates/partials/card_inline_analysis_3d.html`. Immediately AFTER the `<p class="subtitle">…</p>` line (the card description) and BEFORE the `<!-- Source tabs -->` block, insert this block verbatim:

```html
      <!-- ── Analysis params (3D inline analysis) ───────────────────── -->
      <div id="ia3d-analysis-params" style="border:1px solid var(--border);border-radius:8px;background:var(--surface-2);padding:.5rem .6rem;margin-bottom:.6rem">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.4rem">
          <strong style="font-size:.8rem">Analysis</strong>
          <span id="ia3d-warm-indicator" style="font-size:.72rem;color:var(--text-dim)">○ idle</span>
        </div>
        <div style="display:grid;grid-template-columns:auto 1fr auto;gap:.35rem .5rem;align-items:center;font-size:.75rem">
          <label for="ia3d-snapshot">Snapshot</label>
          <select id="ia3d-snapshot" style="min-width:0;font-size:.74rem"></select>
          <button class="btn-sm" id="ia3d-refresh-snapshots" style="padding:.15rem .4rem;font-size:.72rem" title="Reload snapshots">↺</button>

          <label for="ia3d-shuffle">Shuffle</label>
          <input id="ia3d-shuffle" type="number" min="0" value="1" style="width:5rem;font-size:.74rem"/>
          <span></span>

          <label for="ia3d-trainingsetindex">Trainset idx</label>
          <input id="ia3d-trainingsetindex" type="number" min="0" value="0" style="width:5rem;font-size:.74rem"/>
          <span></span>

          <label for="ia3d-batch-size">Batch size</label>
          <input id="ia3d-batch-size" type="number" min="1" value="8" style="width:5rem;font-size:.74rem"/>
          <span></span>

          <label for="ia3d-frames-per-click">Frames / run</label>
          <input id="ia3d-frames-per-click" type="number" min="1" max="10000" value="500" style="width:5rem;font-size:.74rem"/>
          <span></span>

          <label for="ia3d-keep-warm-seconds">Keep warm (s)</label>
          <input id="ia3d-keep-warm-seconds" type="number" min="30" value="300" style="width:5rem;font-size:.74rem"/>
          <span></span>
        </div>
        <label style="display:flex;align-items:center;gap:.35rem;font-size:.73rem;margin-top:.4rem;cursor:pointer">
          <input type="checkbox" id="ia3d-save-csv" style="accent-color:var(--accent);width:13px;height:13px"/>
          Also write .csv
        </label>
        <div id="ia3d-sibling-status" style="font-size:.72rem;color:var(--text-dim);margin-top:.4rem">Pick a cam0 video to resolve its sibling.</div>
        <button class="btn-sm" id="ia3d-btn-analyze-range" disabled
                style="margin-top:.45rem;width:100%;padding:.35rem;font-size:.78rem">▶ Analyze both cameras</button>
        <div id="ia3d-last-run-status" class="fe-extract-status" style="margin-top:.35rem;font-size:.73rem"></div>
      </div>
```

- [ ] **Step 3: Verify all required ids exist and the old ids are gone**

Run:
```bash
F=src/templates/partials/card_inline_analysis_3d.html
for id in inline-analysis-3d-card btn-close-inline-analysis-3d \
          ia3d-snapshot ia3d-shuffle ia3d-trainingsetindex ia3d-batch-size \
          ia3d-frames-per-click ia3d-keep-warm-seconds ia3d-save-csv \
          ia3d-btn-analyze-range ia3d-last-run-status ia3d-warm-indicator \
          ia3d-refresh-snapshots ia3d-sibling-status \
          ia3d-overlay-toggle ia3d-seek ia3d-frame-counter ia3d-frame-img-0; do
  grep -q "\"$id\"\|'$id'\|id=\"$id\"" "$F" && echo "OK   $id" || echo "MISS $id"
done
echo "leftover va3d-:            $(grep -c 'va3d-' $F)"
echo "leftover old card id:      $(grep -c 'view-analyzed-3d-card' $F)"
```
Expected: every id `OK`, both leftover counts `0`.

- [ ] **Step 4: Commit**

```bash
git add dlc-3D/src/templates/partials/card_inline_analysis_3d.html
git commit -m "feat(dlc-3d): card_inline_analysis_3d.html (cloned dual-tile + analysis params)"
```

---

## Task 3: Wire the card into the page + bind-mount

**Files:**
- Modify: `src/templates/dlc_3d.html`
- Modify: `../deeplabcut-webapp-docker/docker-compose.yml`

- [ ] **Step 1: Add the include + open button in dlc_3d.html**

In `src/templates/dlc_3d.html`, add the include right after the viewer-3d include (line ~23):

```html
    {% include "partials/card_viewer_3d.html" %}
    {% include "partials/card_inline_analysis_3d.html" %}
```

And add a nav open button at the very top of the `{% block content %}` (right after the line `{% block content %}`), so the hidden card has an entry point that lives in this module-owned file:

```html
  <div style="margin:.4rem 0">
    <button class="btn-sm" id="btn-open-inline-analysis-3d" style="padding:.25rem .7rem;font-size:.8rem">⊞ 3D Inline Analysis</button>
  </div>
```

- [ ] **Step 2: Add the script tag in dlc_3d.html**

In the `{% block scripts %}` section, add after the viewer_3d.js tag (line ~45):

```html
<script type="module" src="{{ url_for('dlc_3d.static', filename='viewer_3d.js') }}"></script>
<script type="module" src="{{ url_for('dlc_3d.static', filename='inline_analysis_3d.js') }}"></script>
```

- [ ] **Step 3: Add the bind-mount for the new partial**

In `../deeplabcut-webapp-docker/docker-compose.yml`, in the `dlc-3d:` service `volumes:` list (right after the `card_3d_extract.html` mount line ~187), add:

```yaml
      - ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_inline_analysis_3d.html:/app/templates/partials/card_inline_analysis_3d.html
```

- [ ] **Step 4: Recreate the dlc-3d container so the new mount + JS are live**

Run (from `../deeplabcut-webapp-docker`):
```bash
cd ../deeplabcut-webapp-docker && docker compose up -d --no-deps dlc-3d
for i in $(seq 1 20); do code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://localhost:5000/dlc-3d/" 2>/dev/null); [ "$code" = "200" ] && { echo "dlc-3d up"; break; }; sleep 1; done
cd ../deeplabcut-webapp-docker-supports
```
Expected: `dlc-3d up`. (`up -d` re-reads compose volumes; a plain `restart` would NOT pick up the new mount.)

- [ ] **Step 5: Verify the card + button render (no JS errors)**

Create `/tmp/ia3d_loads.py`:
```python
from playwright.sync_api import sync_playwright
URL = "http://localhost:5000/dlc-3d/?token=deeplabcut"
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); pg = b.new_context().new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    pg.on("console", lambda m: m.type == "error" and errs.append("console:"+m.text[:160]))
    pg.goto(URL, wait_until="networkidle")
    has_btn  = pg.query_selector("#btn-open-inline-analysis-3d") is not None
    has_card = pg.query_selector("#inline-analysis-3d-card") is not None
    pg.click("#btn-open-inline-analysis-3d")
    pg.wait_for_timeout(500)
    opened = pg.eval_on_selector("#inline-analysis-3d-card", "el => !el.classList.contains('hidden')") if has_card else False
    print("button:", has_btn, "| card:", has_card, "| opened:", opened, "| errors:", len(errs))
    for e in errs[:6]: print("  ", e)
    b.close()
```
Run: `python3 /tmp/ia3d_loads.py`
Expected: `button: True | card: True | opened: True | errors: 0`.

Note: the cloned viewer wires `iaOpenBtn = getElementById("btn-open-inline-analysis-3d")` and `iaCloseBtn = getElementById("btn-close-inline-analysis-3d")`, so opening already works from the clone. The dispatch (Task 4) only adds analysis behavior.

- [ ] **Step 6: Commit**

```bash
git add dlc-3D/src/templates/dlc_3d.html ../deeplabcut-webapp-docker/docker-compose.yml
git commit -m "feat(dlc-3d): mount + wire 3D inline analysis card into the page"
```
(Commit the compose change in the main webapp repo separately if `git` treats them as different repos — run `git -C ../deeplabcut-webapp-docker add docker-compose.yml && git -C ../deeplabcut-webapp-docker commit -m "chore(dlc-3d): bind-mount card_inline_analysis_3d.html"`.)

---

## Task 4: Append the stereo analysis-dispatch IIFE

**Files:**
- Modify: `src/static/inline_analysis_3d.js` (append at end of file)

This is the only substantively new logic. It reuses the cloned viewer's state (`_iaCurrentVideoPath`, `_iaCurrentFrame`, `_iaDiscoverVariants`, `_iaLoadFrame`, `iaOverlayToggle`, `iaOpenBtn`, `iaCloseBtn`, `iaFrameCounter`) which exist in the same module scope.

- [ ] **Step 1: Append the dispatch IIFE**

Append this verbatim to the END of `src/static/inline_analysis_3d.js`:

```javascript

    // ════════════════════════════════════════════════════════════════════
    //  STEREO ANALYSIS DISPATCH — run DLC on BOTH cameras (cam0 + cam1) over
    //  the same [start, n] range via the main webapp's warm inline-analysis
    //  worker, then trigger the cloned viewer's normal discover+render path
    //  (which already resolves + paints the sibling tile's h5).
    // ════════════════════════════════════════════════════════════════════
    (function () {
      const snapSel    = document.getElementById("ia3d-snapshot");
      const shuffleEl  = document.getElementById("ia3d-shuffle");
      const tsiEl      = document.getElementById("ia3d-trainingsetindex");
      const batchEl    = document.getElementById("ia3d-batch-size");
      const framesEl   = document.getElementById("ia3d-frames-per-click");
      const keepWarmEl = document.getElementById("ia3d-keep-warm-seconds");
      const saveCsvEl  = document.getElementById("ia3d-save-csv");
      const analyzeBtn = document.getElementById("ia3d-btn-analyze-range");
      const lastRun    = document.getElementById("ia3d-last-run-status");
      const warmInd    = document.getElementById("ia3d-warm-indicator");
      const refreshBtn = document.getElementById("ia3d-refresh-snapshots");
      const siblingEl  = document.getElementById("ia3d-sibling-status");

      if (!analyzeBtn) return;   // markup missing — bail silently

      let _snapKey   = null;
      let _siblingPath = null;   // resolved cam1 absolute path (or null)
      let _statusPoll = null;

      // ── Snapshot loader (main webapp API; needs same active project) ──
      async function _loadSnapshots() {
        try {
          const r = await fetch("/dlc/project/snapshots");
          const data = await r.json();
          if (!snapSel) return;
          snapSel.innerHTML = "";
          if (data.error) {
            const o = document.createElement("option");
            o.value = ""; o.textContent = "(activate the DLC project in the main webapp)";
            snapSel.appendChild(o); return;
          }
          const latest = document.createElement("option");
          latest.value = data.latest_rel_path || "-1";
          latest.textContent = data.latest_label ? `Latest — ${data.latest_label}` : "Latest (from config)";
          snapSel.appendChild(latest);
          (data.snapshots || []).forEach((s) => {
            const o = document.createElement("option");
            o.value = s.rel_path;
            const it = s.iteration != null ? `  ·  iter ${s.iteration.toLocaleString()}` : "";
            const sh = s.shuffle   != null ? `  ·  sh${s.shuffle}` : "";
            o.textContent = `${s.label}${it}${sh}`;
            snapSel.appendChild(o);
          });
        } catch (e) { /* silent */ }
      }
      refreshBtn?.addEventListener("click", _loadSnapshots);
      shuffleEl?.addEventListener("change", _loadSnapshots);
      iaOpenBtn?.addEventListener("click", _loadSnapshots);

      // ── Sibling resolution + Analyze-button gating ───────────────────
      function _cam0Path() { return _iaCurrentVideoPath || _iaBrowseVideoPath || null; }

      async function _refreshSibling() {
        const cam0 = _cam0Path();
        _siblingPath = null;
        if (!cam0) {
          siblingEl.textContent = "Pick a cam0 video to resolve its sibling.";
          analyzeBtn.disabled = true;
          return;
        }
        try {
          const r = await fetch(`/dlc-3d/sibling-camera?video=${encodeURIComponent(cam0)}`);
          const d = await r.json();
          if (d.sibling_video_path) {
            _siblingPath = d.sibling_video_path;
            siblingEl.textContent = `Sibling: ${_siblingPath.split("/").pop()}`;
            siblingEl.style.color = "var(--text-dim)";
            analyzeBtn.disabled = false;
          } else {
            siblingEl.textContent = "No sibling camera found — 3D analysis disabled for this video.";
            siblingEl.style.color = "var(--danger, #e66)";
            analyzeBtn.disabled = true;
          }
        } catch (e) {
          siblingEl.textContent = "Could not resolve sibling camera.";
          analyzeBtn.disabled = true;
        }
      }
      // Re-resolve whenever a new video is opened: the cloned viewer updates
      // _iaCurrentVideoPath on open; poll-on-frame-counter-change is the
      // simplest hook that fires after _iaOpenBrowseVideo runs.
      if (iaFrameCounter) {
        let _lastCam0 = null;
        new MutationObserver(() => {
          const c = _cam0Path();
          if (c !== _lastCam0) { _lastCam0 = c; _refreshSibling(); }
        }).observe(iaFrameCounter, { childList: true, characterData: true, subtree: true });
      }

      // ── Warm-worker session ──────────────────────────────────────────
      async function _ensureSession() {
        const snapshot = snapSel?.value;
        if (!snapshot) { lastRun.textContent = "Pick a snapshot first."; return null; }
        const r = await fetch("/dlc/project/inline-analysis/session/start", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            snapshot_path: snapshot,
            shuffle:       parseInt(shuffleEl?.value, 10) || 1,
            ttl_seconds:   parseInt(keepWarmEl?.value, 10) || 300,
            batch_size:    parseInt(batchEl?.value, 10) || 8,
          }),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          lastRun.textContent = d.error || `Could not start session (HTTP ${r.status})`;
          lastRun.className = "fe-extract-status err";
          return null;
        }
        _snapKey = (await r.json()).snap_key;
        _startStatusPoll();
        return _snapKey;
      }
      function _startStatusPoll() {
        if (_statusPoll) return;
        _statusPoll = setInterval(async () => {
          if (!_snapKey) return;
          try {
            const r = await fetch(`/dlc/project/inline-analysis/session/status?snap_key=${_snapKey}`);
            const d = await r.json();
            const s = d.status || "absent";
            const rem = d.idle_remaining_s || 0;
            const mm = Math.floor(rem / 60), ss = String(rem % 60).padStart(2, "0");
            if (warmInd) warmInd.textContent =
              s === "ready" ? `● warm · ${mm}:${ss}` : s === "warming" ? "… warming" : `○ ${s}`;
          } catch (e) { /* keep polling */ }
        }, 2000);
      }
      function _stopStatusPoll() { if (_statusPoll) { clearInterval(_statusPoll); _statusPoll = null; } }

      // ── Submit one /range, return req_id (or null) ───────────────────
      async function _submitRange(sk, videoPath, startFrame, nFrames) {
        const r = await fetch("/dlc/project/inline-analysis/range", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            snap_key: sk, video_path: videoPath,
            start_frame: startFrame, n_frames: nFrames,
            batch_size: parseInt(batchEl?.value, 10) || 8,
            save_as_csv: !!(saveCsvEl && saveCsvEl.checked),
            snapshot_path: snapSel?.value || "",
            shuffle: parseInt(shuffleEl?.value, 10) || 1,
            trainingsetindex: parseInt(tsiEl?.value, 10) || 0,
          }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { lastRun.textContent = `Error: ${d.error || r.status}`; lastRun.className = "fe-extract-status err"; return null; }
        return d.req_id;
      }

      // ── Poll one req_id to terminal state → {status, n_analyzed, ...} ─
      function _pollReq(reqId) {
        return new Promise((resolve) => {
          const t = setInterval(async () => {
            try {
              const r = await fetch(`/dlc/project/inline-analysis/range/status?req_id=${reqId}`);
              if (!r.ok) return;
              const d = await r.json();
              if (d.status === "done" || d.status === "error") { clearInterval(t); resolve(d); }
            } catch (e) { /* keep polling */ }
          }, 500);
        });
      }

      // ── Analyze BOTH cameras ─────────────────────────────────────────
      analyzeBtn.addEventListener("click", async () => {
        const cam0 = _cam0Path();
        if (!cam0)        { lastRun.textContent = "Pick a cam0 video first."; return; }
        if (!_siblingPath) { lastRun.textContent = "No sibling camera — cannot run 3D analysis."; return; }
        const sk = await _ensureSession();
        if (!sk) return;
        const startFrame = _iaCurrentFrame || 0;
        const nFrames    = parseInt(framesEl?.value, 10) || 500;
        lastRun.textContent = `Running both cameras (${nFrames} frames from ${startFrame})…`;
        lastRun.className = "fe-extract-status";
        analyzeBtn.disabled = true;
        const [req0, req1] = await Promise.all([
          _submitRange(sk, cam0, startFrame, nFrames),
          _submitRange(sk, _siblingPath, startFrame, nFrames),
        ]);
        if (!req0 || !req1) { analyzeBtn.disabled = false; return; }
        const [d0, d1] = await Promise.all([_pollReq(req0), _pollReq(req1)]);
        analyzeBtn.disabled = false;
        const errs = [d0, d1].filter(d => d.status === "error");
        if (errs.length === 2) {
          lastRun.textContent = `Both cameras failed: ${errs[0].error || "unknown"}`;
          lastRun.className = "fe-extract-status err"; return;
        }
        lastRun.textContent = errs.length === 1
          ? `One camera failed (${errs[0].error || "unknown"}); other: ${(d0.status==='done'?d0:d1).n_analyzed} analyzed`
          : `Last run: cam0 ${d0.n_analyzed} analyzed/${d0.n_skipped} skipped · cam1 ${d1.n_analyzed}/${d1.n_skipped}`;
        // Trigger the cloned viewer's normal render path. _iaDiscoverVariants on
        // the cam0 video sets the primary; the viewer's multi-tile logic resolves
        // + paints the cam1 sibling h5. Then force a full frame load so markers
        // paint deterministically (same as the threshold-slider path).
        if (typeof _iaDiscoverVariants === "function") {
          await _iaDiscoverVariants(cam0);
          if (iaOverlayToggle && !iaOverlayToggle.checked) {
            iaOverlayToggle.checked = true;
            iaOverlayToggle.dispatchEvent(new Event("change", { bubbles: true }));
          }
          if (typeof _iaLoadFrame === "function") await _iaLoadFrame(_iaCurrentFrame);
        }
      });

      // ── Cleanup ──────────────────────────────────────────────────────
      iaCloseBtn?.addEventListener("click", () => {
        _stopStatusPoll();
        if (_snapKey) {
          try {
            fetch("/dlc/project/inline-analysis/session/stop", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ snap_key: _snapKey }),
            });
          } catch (e) { /* ignore */ }
          _snapKey = null;
        }
      });
      window.addEventListener("beforeunload", () => {
        if (_snapKey) navigator.sendBeacon?.(
          "/dlc/project/inline-analysis/session/stop",
          new Blob([JSON.stringify({ snap_key: _snapKey })], { type: "application/json" }),
        );
      });
    })(); // end STEREO ANALYSIS DISPATCH
```

- [ ] **Step 2: Verify it parses**

Run: `node --input-type=module --check < src/static/inline_analysis_3d.js && echo "PARSE OK"`
Expected: `PARSE OK`.

- [ ] **Step 3: Commit**

```bash
git add dlc-3D/src/static/inline_analysis_3d.js
git commit -m "feat(dlc-3d): stereo analysis-dispatch IIFE (two-camera /range + dual poll)"
```

---

## Task 5: Static guard tests

**Files:**
- Create: `tests/test_inline_analysis_3d_ui_isolation.py`

- [ ] **Step 1: Write the guard tests**

Create `tests/test_inline_analysis_3d_ui_isolation.py`:

```python
"""Static guards for the 3D Inline Analysis card.

Cloned from viewer_3d.js / card_viewer_3d.html with va*->ia* rename, plus a
stereo analysis-dispatch IIFE. These parse the source files directly (no
runtime). See docs/superpowers/specs/2026-05-20-3d-inline-analysis-design.md.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS   = ROOT / "src" / "static" / "inline_analysis_3d.js"
CARD = ROOT / "src" / "templates" / "partials" / "card_inline_analysis_3d.html"
PAGE = ROOT / "src" / "templates" / "dlc_3d.html"


def test_files_exist():
    assert JS.is_file() and CARD.is_file()


def test_no_va_identifier_leaks_in_clone():
    src = JS.read_text()
    import re
    assert "va3d-" not in src, "DOM id va3d- leaked into the clone"
    assert not re.search(r"\bva[A-Z]", src), "camelCase va* identifier leaked"
    assert "view-analyzed-3d-card" not in src
    assert "btn-open-view-analyzed" not in src


def test_card_has_analysis_params_and_dual_tile():
    html = CARD.read_text()
    for needed in [
        "inline-analysis-3d-card", "btn-close-inline-analysis-3d",
        "ia3d-snapshot", "ia3d-batch-size", "ia3d-frames-per-click",
        "ia3d-keep-warm-seconds", "ia3d-btn-analyze-range",
        "ia3d-last-run-status", "ia3d-warm-indicator", "ia3d-sibling-status",
        "ia3d-overlay-toggle", "ia3d-frame-img-0",
    ]:
        assert needed in html, f"missing id {needed!r}"
    assert "va3d-" not in html


def test_page_wires_card_button_and_script():
    page = PAGE.read_text()
    assert "partials/card_inline_analysis_3d.html" in page
    assert "inline_analysis_3d.js" in page
    assert 'id="btn-open-inline-analysis-3d"' in page


def test_dispatch_runs_both_cameras_against_main_webapp_api():
    src = JS.read_text()
    # uses the main webapp inline-analysis endpoints
    assert "/dlc/project/inline-analysis/session/start" in src
    assert "/dlc/project/inline-analysis/range" in src
    assert "/dlc/project/inline-analysis/range/status" in src
    assert "/dlc/project/snapshots" in src
    # resolves the sibling camera + gates the button
    assert "/dlc-3d/sibling-camera" in src
    assert "_siblingPath" in src
    # submits TWO ranges and polls both (stereo)
    assert "_submitRange(sk, cam0" in src
    assert "_submitRange(sk, _siblingPath" in src
    assert "Promise.all([_pollReq(req0), _pollReq(req1)])" in src
    # on done: re-discovers + force-loads the frame (inherited render path)
    assert "_iaDiscoverVariants(cam0)" in src
    assert "_iaLoadFrame(_iaCurrentFrame)" in src


def test_analyze_button_disabled_by_default():
    html = CARD.read_text()
    import re
    m = re.search(r'<button[^>]*id="ia3d-btn-analyze-range"[^>]*>', html)
    assert m and "disabled" in m.group(0), (
        "Analyze button must default disabled until a sibling is resolved"
    )
```

- [ ] **Step 2: Run the guards (expect PASS; they assert the work from Tasks 1-4)**

Run: `python3 -m pytest tests/test_inline_analysis_3d_ui_isolation.py -v`
Expected: 6 passed. If any fail, the failure names the missing id/wiring — fix the source file it points to (do not weaken the test).

- [ ] **Step 3: Commit**

```bash
git add dlc-3D/tests/test_inline_analysis_3d_ui_isolation.py
git commit -m "test(dlc-3d): static guards for 3D inline analysis card"
```

---

## Task 6: Live stereo Playwright smoke

**Files:**
- Create: `/tmp/ia3d_stereo_smoke.py` (throwaway verification, not committed)

**Prerequisites (manual / environment):** the main webapp must have the DLC project active (so `/dlc/project/snapshots` returns snapshots and the warm session can start), and a stereo video pair must exist under `/user-data/...` where the cam0 video has a resolvable cam1 sibling. Use a real pair from the active project.

- [ ] **Step 1: Write the stereo smoke**

Create `/tmp/ia3d_stereo_smoke.py` (fill `VDIR` + `CAM0_FILE` with a real cam0 video that has a cam1 sibling; `PROJECT` is the DLC project to activate in the main webapp):

```python
import time
from playwright.sync_api import sync_playwright
MAIN = "http://localhost:5000"
URL  = f"{MAIN}/dlc-3d/?token=deeplabcut"
PROJECT = "/user-data/NAS-Data-Share/Motor-Learning/DLC-Projects/DREADD-Ali-2026-01-07"
VDIR = "/user-data/Parra-Data/Cloud/Reaching-Task-Data/RatBox Videos/tdcs/050726"
CAM0_FILE = "<a cam0 .avi in VDIR that has a cam1 sibling>"  # FILL IN

def canvas_nt(pg, cam):
    return pg.evaluate("""(cam)=>{const cv=document.getElementById('ia3d-overlay-canvas-'+cam);
        if(!cv)return -1;const d=cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;
        let n=0;for(let j=3;j<d.length;j+=4)if(d[j]>0)n++;return n;}""", cam)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True); pg = b.new_context(viewport={"width":1500,"height":1100}).new_page()
    errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)[:160]))
    # activate the DLC project in the MAIN webapp so snapshots + warm session work
    pg.goto(f"{MAIN}/?token=deeplabcut", wait_until="networkidle")
    pg.evaluate("""async(p)=>{await fetch('/dlc/project',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:p})})}""", PROJECT)
    # open the dlc-3d page + the new card
    pg.goto(URL, wait_until="networkidle")
    pg.click("#btn-open-inline-analysis-3d"); pg.wait_for_selector("#inline-analysis-3d-card:not(.hidden)")
    # browse to the cam0 video (Browse Folders tab)
    pg.click("#ia3d-tab-browse"); pg.wait_for_selector("#ia3d-tab-browse-panel:not(.hidden)")
    pg.fill("#ia3d-browse-breadcrumb", VDIR); pg.press("#ia3d-browse-breadcrumb", "Enter")
    pg.wait_for_function(f"()=>Array.from(document.querySelectorAll('#ia3d-browse-list span')).some(s=>s.textContent==='{CAM0_FILE}')", timeout=20000)
    pg.evaluate(f"""()=>{{const t=Array.from(document.querySelectorAll('#ia3d-browse-list .fe-video-item')).find(r=>r.querySelector('span')?.textContent==='{CAM0_FILE}');if(t)t.click();}}""")
    pg.wait_for_function("()=>!document.getElementById('ia3d-player-section').classList.contains('hidden')", timeout=15000)
    time.sleep(2)  # let sibling resolve
    print("analyze enabled:", pg.eval_on_selector("#ia3d-btn-analyze-range", "el=>!el.disabled"))
    print("sibling status:", pg.eval_on_selector("#ia3d-sibling-status", "el=>el.textContent"))
    # pick a snapshot
    pg.evaluate("""()=>{const s=document.getElementById('ia3d-snapshot'); if(s.options.length>1) s.selectedIndex=1; s.dispatchEvent(new Event('change',{bubbles:true}));}""")
    # scrub to a frame (normalized 0..1000 seek)
    pg.evaluate("""()=>{const s=document.getElementById('ia3d-seek');s.value='100';s.dispatchEvent(new Event('input',{bubbles:true}));s.dispatchEvent(new Event('change',{bubbles:true}));}""")
    pg.fill("#ia3d-frames-per-click","10"); pg.fill("#ia3d-keep-warm-seconds","30")
    pg.click("#ia3d-btn-analyze-range")
    pg.wait_for_function("()=>/Last run:|failed/.test(document.getElementById('ia3d-last-run-status').textContent)", timeout=180000)
    print("last run:", pg.eval_on_selector("#ia3d-last-run-status","el=>el.textContent"))
    nt0=nt1=0
    for _ in range(40):
        time.sleep(0.25); nt0=canvas_nt(pg,0); nt1=canvas_nt(pg,1)
        if nt0>100 and nt1>100: break
    print(f"cam0 painted={nt0}  cam1 painted={nt1}  errors={len(errs)}")
    for e in errs[:5]: print("  ",e)
    b.close()
```

- [ ] **Step 2: Run it**

Run: `python3 /tmp/ia3d_stereo_smoke.py`
Expected: `analyze enabled: True`, a `Last run: cam0 … cam1 …` line, and **both** `cam0 painted` and `cam1 painted` > 100, `errors=0`.

If a camera paints 0: navigate to a frame that is inside the analyzed range (the worker analyzes [start, start+N); seek there), and confirm the h5s for both cameras exist on disk (`ls` the videos dir for `*_cam0_*…​.h5` and `*_cam1_*…​.h5`).

- [ ] **Step 3: Final commit (if any fixups were needed)**

```bash
git add -A dlc-3D/
git commit -m "fix(dlc-3d): 3D inline analysis stereo smoke fixups" || echo "nothing to commit"
```

---

## Self-review (completed by plan author)

- **Spec coverage:** card clone (Task 2), JS clone (Task 1), stereo dispatch + two-camera run (Task 4), sibling-required gating (Task 4 + guard in Task 5), reuse main-webapp API (Task 4), viewing via cloned viewer_3d render path (Task 4 on-done), wiring + mount (Task 3), tests (Task 5/6). All spec sections map to a task.
- **Placeholder scan:** the only intentional fill-ins are the live-data values in the Playwright smoke (`CAM0_FILE`, `VDIR`, `PROJECT`) — these are environment-specific and flagged. No code placeholders.
- **Type/name consistency:** the dispatch references `_iaCurrentVideoPath`, `_iaBrowseVideoPath`, `_iaCurrentFrame`, `_iaDiscoverVariants`, `_iaLoadFrame`, `iaOverlayToggle`, `iaOpenBtn`, `iaCloseBtn`, `iaFrameCounter` — all produced by the Task 1 rename (verified by the `va`→`ia` mapping of viewer_3d's `_vaCurrentVideoPath`, `_vaDiscoverVariants`, `_vaLoadFrame`, `vaOverlayToggle`, `vaOpenBtn`, `vaCloseBtn`, `vaFrameCounter`). DOM ids `ia3d-overlay-canvas-{0,1}`, `ia3d-player-section`, `ia3d-seek`, `ia3d-tab-browse`, `ia3d-browse-*` come from the card clone (Task 2 renames `va3d-`→`ia3d-`).
