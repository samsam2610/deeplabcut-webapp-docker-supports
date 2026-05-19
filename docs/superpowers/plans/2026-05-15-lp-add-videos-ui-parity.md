# LP Add-Videos UI Parity — mirror the Predict card browser

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Make the "Add videos to LP project" panel in the Convert card use the same browser/queue UI pattern as the Predict card. No backend change.

**Architecture:**
- Hoist the existing `makeBrowser` factory + helpers out of `initPredictCard()` to module scope in `lp_cards.js` so both the predict and convert cards share one implementation.
- Rewrite the convert-card "Add videos" markup + JS to mirror predict-card layout (Target input, ↑ Up, Browse, browser pane, + Add to queue, ✕ Clear queue, queue list).
- POST target stays `/dlc-3d/lp/videos/add` (already exists).

**Tech stack:** Vanilla JS module, Jinja partial template. Existing pytest suite covers backend.

---

## File Structure

```
src/static/lp_cards.js                      ← MODIFY: hoist makeBrowser + use it in convert card
src/templates/partials/card_lp_convert.html ← MODIFY: replace the <details> add-videos block
```

No backend files touched. Existing tests stay green.

---

### Task 1: Hoist makeBrowser + supportedFile to module scope

**File:** `src/static/lp_cards.js`

Currently inside `initPredictCard()`:
- `const VIDEO_EXTS = new Set([...])`
- `const IMAGE_EXTS = new Set([...])`
- `const supportedFile = (name) => {...}`
- `function makeBrowser({ inputEl, paneEl, dirOnly }) { ... }`

- [ ] **Step 1: Move them to module scope**

In `lp_cards.js`, locate the helper section near the top of the file (next to `$ = (sel) => document.querySelector(sel)`) and insert:

```javascript
// ── Shared file-picker helpers (used by Predict + Convert/Add-Videos cards) ──
const _LP_VIDEO_EXTS = new Set([".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v"]);
const _LP_IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]);

function _lpSupportedFile(name) {
  const i = name.lastIndexOf(".");
  if (i < 0) return false;
  const ext = name.slice(i).toLowerCase();
  return _LP_VIDEO_EXTS.has(ext) || _LP_IMAGE_EXTS.has(ext);
}

/** Build a directory-tree picker for any (inputEl, paneEl) pair.
 *  Mirrors analyze.js' video picker. dirOnly=true hides files entirely.
 *  Returns { browseDir, openAt, up, getHighlighted }.
 *  Emits 'lp-picker-dblclick' (bubbles:false) on paneEl on file double-click. */
function _lpMakeBrowser({ inputEl, paneEl, dirOnly }) {
  let highlightedRow = null;
  let highlightedPath = "";
  let browserLoaded = false;
  let currentDir = "";

  function setHighlight(row, path) {
    if (highlightedRow && highlightedRow !== row) {
      highlightedRow.style.background = "";
      highlightedRow.style.outline = "";
    }
    highlightedRow = row;
    highlightedPath = path;
    inputEl.value = path;
    row.style.background = "var(--accent-dim, rgba(99,179,237,.18))";
    row.style.outline = "1px solid var(--accent, #63b3ed)";
  }

  function makeEntry(name, fullPath, isDir) {
    const wrapper = document.createElement("div");
    const row = document.createElement("div");
    row.style.cssText = "display:flex;align-items:center;gap:.3rem;padding:.15rem .4rem;border-radius:3px;cursor:pointer";
    const arrow = document.createElement("span");
    arrow.style.cssText = "width:.8rem;color:var(--text-dim);font-size:.7rem";
    arrow.textContent = isDir ? "▶" : "·";
    const label = document.createElement("span");
    label.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--mono);font-size:.74rem";
    label.textContent = name + (isDir ? "/" : "");
    row.appendChild(arrow); row.appendChild(label);
    wrapper.appendChild(row);

    const childContainer = document.createElement("div");
    childContainer.style.cssText = "display:none;padding-left:1rem";
    wrapper.appendChild(childContainer);

    let loaded = false, expanded = false;

    if (isDir) {
      row.addEventListener("click", async () => {
        setHighlight(row, fullPath);
        if (!expanded && !loaded) {
          childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">Loading…</span>`;
          childContainer.style.display = "block";
          try {
            const res = await fetch(`/fs/ls?path=${encodeURIComponent(fullPath)}`);
            const d = await res.json();
            childContainer.innerHTML = "";
            if (!d.error) {
              const vis = (d.entries || []).filter((e) =>
                (e.type === "dir" && e.has_media !== false) ||
                (!dirOnly && e.type === "file" && _lpSupportedFile(e.name)));
              vis.forEach((e) =>
                childContainer.appendChild(makeEntry(e.name, fullPath.replace(/\/+$/, "") + "/" + e.name, e.type === "dir")));
              if (!vis.length) childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">(no supported entries)</span>`;
            } else {
              childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">${d.error}</span>`;
            }
          } catch (e) {
            childContainer.innerHTML = `<span style="font-size:.72rem;color:var(--text-dim);padding:.15rem .4rem;display:block">Error loading.</span>`;
          }
          loaded = true; expanded = true; arrow.textContent = "▼";
        } else {
          expanded = !expanded;
          childContainer.style.display = expanded ? "block" : "none";
          arrow.textContent = expanded ? "▼" : "▶";
        }
      });
    } else {
      row.addEventListener("click", () => setHighlight(row, fullPath));
    }

    // Double-click: emit a custom event the parent wires to its queue handler
    row.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      inputEl.value = fullPath;
      paneEl.dispatchEvent(new CustomEvent("lp-picker-dblclick", { detail: { path: fullPath }, bubbles: false }));
      paneEl.classList.add("hidden");
      browserLoaded = false;
    });

    return wrapper;
  }

  async function browseDir(dirPath) {
    browserLoaded = false;
    currentDir = dirPath;
    inputEl.value = dirPath;
    paneEl.innerHTML = `<span style="font-size:.8rem;color:var(--text-dim)">Loading…</span>`;
    try {
      const res = await fetch(`/fs/ls?path=${encodeURIComponent(dirPath)}`);
      const data = await res.json();
      if (data.error) { paneEl.textContent = data.error; return; }
      paneEl.innerHTML = "";
      const visible = (data.entries || []).filter((e) =>
        (e.type === "dir" && e.has_media !== false) ||
        (!dirOnly && e.type === "file" && _lpSupportedFile(e.name)));
      if (!visible.length) {
        const empty = document.createElement("span");
        empty.style.cssText = "font-size:.78rem;color:var(--text-dim);padding:.3rem;display:block";
        empty.textContent = dirOnly ? "(no subfolders)" : "(no supported video or image files)";
        paneEl.appendChild(empty);
      } else {
        visible.forEach((e) =>
          paneEl.appendChild(makeEntry(e.name, (data.path || dirPath).replace(/\/+$/, "") + "/" + e.name, e.type === "dir")));
      }
      browserLoaded = true;
    } catch (err) {
      paneEl.textContent = "Failed to load.";
    }
  }

  function openAt(initialPath) {
    const isHidden = paneEl.classList.contains("hidden");
    paneEl.classList.toggle("hidden");
    if (!isHidden) return;
    const typed = inputEl.value.trim() || initialPath || "/user-data";
    browseDir(typed);
  }

  function up() {
    const cur = (inputEl.value.trim() || currentDir).replace(/\/+$/, "");
    if (!cur) return;
    const parent = cur.split("/").slice(0, -1).join("/") || "/";
    if (parent !== cur) { browseDir(parent); paneEl.classList.remove("hidden"); }
  }

  return { browseDir, openAt, up, getHighlighted: () => highlightedPath };
}
```

- [ ] **Step 2: Remove the inner copies from initPredictCard**

In `initPredictCard()`, **delete** the inner `const VIDEO_EXTS / IMAGE_EXTS / supportedFile = ...` block (currently around lines 433-438) **and** the inner `function makeBrowser({ inputEl, paneEl, dirOnly })` definition (currently around lines 441-568).

Then replace the two consumer calls:
```javascript
const videoBrowser = makeBrowser({ inputEl: targetEl, paneEl: browserEl, dirOnly: false });
// ...later:
const destBrowser = makeBrowser({ inputEl: destEl, paneEl: destBrowserEl, dirOnly: true });
```
with:
```javascript
const videoBrowser = _lpMakeBrowser({ inputEl: targetEl, paneEl: browserEl, dirOnly: false });
// ...later:
const destBrowser = _lpMakeBrowser({ inputEl: destEl, paneEl: destBrowserEl, dirOnly: true });
```

- [ ] **Step 3: Sanity-check predict card is unchanged**

Run the existing pytest suite (it doesn't directly cover JS, but ensures nothing in the route layer regresses):

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_lp_routes.py tests/test_lp_video_adder.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/static/lp_cards.js
git commit -m "refactor(dlc-3d): hoist makeBrowser to module scope for reuse"
```

---

### Task 2: Rewrite the Add-Videos panel HTML

**File:** `src/templates/partials/card_lp_convert.html`

- [ ] **Step 1: Replace the `<details id="lp-add-videos-section">` block**

Locate the block (it begins `<details class="lp-field" id="lp-add-videos-section">`). Replace the *entire* `<details>...</details>` element with the following markup, which mirrors the Predict card's IDs (prefixed `lp-add-videos-*`):

```html
<details class="lp-field" id="lp-add-videos-section">
  <summary style="cursor:pointer;font-weight:500">Add videos to LP project</summary>
  <p class="subtitle" style="margin-top:.4rem">
    Browse for video files and place them under
    <code style="font-family:var(--mono);font-size:.7rem">&lt;lp&gt;/videos/</code>.
    Files that already exist are skipped (never overwritten).
  </p>

  <div class="lp-field">
    <label>LP project</label>
    <input type="text" id="lp-add-videos-project" placeholder="defaults to the convert target above">
  </div>

  <div class="lp-field">
    <label>Mode</label>
    <select id="lp-add-videos-mode" style="font-family:var(--mono);font-size:.78rem;padding:.3rem .5rem;background:var(--surface-2);border:1px solid var(--border);border-radius:4px;color:var(--text)">
      <option value="symlink" selected>symlink (recommended)</option>
      <option value="hardlink">hardlink (falls back to copy)</option>
      <option value="copy">copy</option>
    </select>
  </div>

  <!-- Target / Up / Browse — same layout as Predict card -->
  <div class="lp-field">
    <label>Target (file or folder path)</label>
    <div style="display:flex;gap:.4rem">
      <input type="text" id="lp-add-videos-target" placeholder="/path/to/video.mp4  or  /path/to/folder"
        style="flex:1;font-family:var(--mono);font-size:.78rem;padding:.35rem .55rem;background:var(--surface-2);border:1px solid var(--border);border-radius:5px;color:var(--text)" />
      <button class="btn-sm" id="lp-add-videos-up" style="padding:.2rem .45rem;font-size:.75rem" title="Go up one level">↑ Up</button>
      <button class="btn-sm" id="lp-add-videos-browse-btn" title="Browse for videos and folders">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        Browse
      </button>
    </div>
    <div id="lp-add-videos-browser" class="hidden" style="margin-top:.5rem;max-height:240px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);padding:.4rem .5rem;font-size:.77rem"></div>
    <div style="display:flex;gap:.4rem;margin-top:.4rem;align-items:center;flex-wrap:wrap">
      <button class="btn-sm" id="lp-add-videos-batch-add" title="Add highlighted path to the add-videos queue" style="opacity:.85">+ Add to queue</button>
      <button class="btn-sm" id="lp-add-videos-batch-clear" title="Clear all queued paths" style="opacity:.7">✕ Clear queue</button>
      <span style="font-size:.72rem;color:var(--text-dim)">Single-click to highlight · double-click to add instantly</span>
    </div>
    <div id="lp-add-videos-batch-list" style="margin-top:.4rem;display:none;border:1px solid var(--border);border-radius:5px;background:var(--surface-2);max-height:140px;overflow-y:auto;padding:.3rem .4rem;font-size:.74rem;font-family:var(--mono)"></div>
  </div>

  <button class="btn-primary" id="btn-lp-add-videos-run">Add videos</button>
  <pre class="lp-result" id="lp-add-videos-result" hidden></pre>
</details>
```

- [ ] **Step 2: Commit**

```bash
git add src/templates/partials/card_lp_convert.html
git commit -m "feat(dlc-3d): add-videos panel mirrors Predict card browser layout"
```

---

### Task 3: Rewire the JS to use the hoisted browser

**File:** `src/static/lp_cards.js` — inside `initConvertCard()`.

- [ ] **Step 1: Find the current add-videos init block**

It's inside `initConvertCard()`. Search for IDs starting with `lp-add-videos-` (project / mode / browse / queue) — that's the block to replace.

- [ ] **Step 2: Replace it with the makeBrowser-based version**

```javascript
// ── Add-videos panel (mirrors Predict card's browser pattern) ───────
const avProjEl    = $("#lp-add-videos-project");
const avModeEl    = $("#lp-add-videos-mode");
const avTargetEl  = $("#lp-add-videos-target");
const avUpEl      = $("#lp-add-videos-up");
const avBrowseEl  = $("#lp-add-videos-browse-btn");
const avPaneEl    = $("#lp-add-videos-browser");
const avBatchAdd  = $("#lp-add-videos-batch-add");
const avBatchClr  = $("#lp-add-videos-batch-clear");
const avBatchList = $("#lp-add-videos-batch-list");
const avRunEl     = $("#btn-lp-add-videos-run");
const avResEl     = $("#lp-add-videos-result");

if (avProjEl && avTargetEl) {
  const avBrowser = _lpMakeBrowser({ inputEl: avTargetEl, paneEl: avPaneEl, dirOnly: false });
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
      rm.textContent = "×"; rm.title = "Remove";
      rm.addEventListener("click", () => { avQueue.splice(i, 1); avRenderQueue(); });
      row.appendChild(txt); row.appendChild(rm);
      avBatchList.appendChild(row);
    });
  }

  function avAddToQueue(p) {
    p = (p || "").trim();
    if (!p) return;
    if (!avQueue.includes(p)) avQueue.push(p);
    avRenderQueue();
  }

  avPaneEl.addEventListener("lp-picker-dblclick", (e) => avAddToQueue(e.detail.path));
  avBatchAdd.addEventListener("click", () => avAddToQueue(avBrowser.getHighlighted() || avTargetEl.value));
  avBatchClr.addEventListener("click", () => { avQueue.length = 0; avRenderQueue(); });

  avBrowseEl.addEventListener("click", () => {
    // Seed from the LP project field if available, otherwise /user-data
    const fallback = (avProjEl.value.trim() || dstEl?.value?.trim() || "/user-data");
    avBrowser.openAt(fallback);
  });
  avUpEl.addEventListener("click", () => avBrowser.up());
  avTargetEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      avBrowser.browseDir(avTargetEl.value.trim());
      avPaneEl.classList.remove("hidden");
    }
  });

  avRunEl.addEventListener("click", async () => {
    const lp = avProjEl.value.trim() || dstEl?.value?.trim();
    if (!lp) {
      avResEl.hidden = false;
      avResEl.textContent = "Specify the LP project (or fill the convert target above).";
      return;
    }
    // Use queue if non-empty; else fall back to the target field alone
    const paths = avQueue.length ? avQueue.slice() : (avTargetEl.value.trim() ? [avTargetEl.value.trim()] : []);
    if (!paths.length) {
      avResEl.hidden = false;
      avResEl.textContent = "Queue at least one video (browse + double-click, or + Add to queue).";
      return;
    }
    avRunEl.disabled = true;
    avResEl.hidden = false;
    avResEl.textContent = "Adding…";
    try {
      const r = await fetch("/dlc-3d/lp/videos/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lp_project: lp,
          video_paths: paths,
          mode: avModeEl.value || "symlink",
        }),
      });
      const j = await r.json();
      avResEl.textContent = JSON.stringify(j, null, 2);
      if (r.ok) { avQueue.length = 0; avRenderQueue(); }
    } catch (e) {
      avResEl.textContent = "Error: " + e.message;
    } finally {
      avRunEl.disabled = false;
    }
  });
}
```

The variable `dstEl` already exists in `initConvertCard()` and points at `#lp-convert-dst` — used here as a fallback for the LP project field. If `dstEl` isn't defined in your scope yet, search initConvertCard for `lp-convert-dst` to verify the symbol name, and substitute accordingly.

- [ ] **Step 3: Smoke-test in container**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker
docker compose restart dlc-3d
sleep 3
docker compose exec dlc-3d python3 -c "
import urllib.request, json
b = json.loads(urllib.request.urlopen('http://localhost:5050/dlc-3d/lp/health').read())
print('health.ok:', b['ok'])
"
```

Manual UI check: open the dlc-3d page, open the Convert card, expand "Add videos to LP project". You should see Target / ↑ Up / Browse / browser pane / + Add to queue / ✕ Clear queue / queue list — the same layout as the Predict card.

- [ ] **Step 4: Run pytest backend suite**

```bash
cd /home/sam/docker-images/deeplabcut-webapp-docker-supports/dlc-3D
pytest tests/test_lp_routes.py tests/test_lp_video_adder.py tests/test_lp_converter.py -q
```

Expected: all pass (no backend changes in this plan).

- [ ] **Step 5: Commit**

```bash
git add src/static/lp_cards.js
git commit -m "feat(dlc-3d): convert add-videos UI uses shared makeBrowser"
```

---

## Self-review

- [x] No backend changes; existing tests cover the unchanged routes.
- [x] Hoisted helpers are prefixed `_lp*` to avoid name collisions.
- [x] Both Predict and Convert browsers will share one implementation — bugfixes flow to both.
- [x] All new HTML IDs prefixed `lp-add-videos-*` — no collisions with predict's `lp-predict-*`.
- [x] dstEl scoping note included; the implementer may need to verify the existing symbol name in `initConvertCard()` before relying on it as the fallback.
