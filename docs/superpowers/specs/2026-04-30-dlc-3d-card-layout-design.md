# DLC-3D Card Layout Redesign — Design Spec

**Date:** 2026-04-30
**Status:** Approved

## Goal

Replace the dlc-3D module's custom full-page split-panel layout with the main webapp's exact card-based layout. The dlc-3D page (`/dlc-3d/`) will be visually and structurally identical to `https://ppp.sam-tran.com` — same session bars, same 15-card grid, same JS/logic — except `card_frame_extractor` is replaced by a new `card_3d_extract` partial. The current sync-cam player UI only appears when the 3D Frame Extractor card is opened.

---

## Section 1: Template Structure

`dlc_3d.html` becomes a thin wrapper that mirrors `index.html` exactly:

```
{% extends "base.html" %}

{% block content %}
  session_dlc_bar.html   ← include verbatim (same partial file from base image)
  session_anipose_bar.html ← include verbatim
  <main class="cards">
    card_dlc_project.html         ← unchanged, included from base image
    card_3d_extract.html          ← NEW (replaces card_frame_extractor)
    card_frame_labeler.html       ← unchanged
    card_training_dataset.html    ← unchanged
    card_train_network.html       ← unchanged
    card_analyze.html             ← unchanged
    card_viewer.html              ← unchanged
    card_annotator.html           ← unchanged
    card_gpu_monitor.html         ← unchanged
    card_dlc_config.html          ← unchanged
    card_custom_script.html       ← unchanged
    card_project_explorer.html    ← unchanged
    card_session_actions.html     ← unchanged
    card_config_editor.html       ← unchanged
    card_admin.html               ← unchanged
  </main>
{% endblock %}

{% block scripts %}
{{ super() }}
<link rel="stylesheet" href="{{ url_for('dlc_3d.static', filename='dlc_3d.css') }}">
<script type="module" src="{{ url_for('dlc_3d.static', filename='enhanced_player.js') }}"></script>
<script type="module" src="{{ url_for('dlc_3d.static', filename='dlc_3d.js') }}"></script>
{% endblock %}
```

The `{% include %}` paths for the 14 unchanged cards resolve to `/app/templates/partials/` from the base image — no copies needed in `dlc-3D/src/`. Only `card_3d_extract.html` is placed in `dlc-3D/src/templates/partials/` (and mounted via docker-compose volume).

The `dlc_3d.css` `<link>` tag goes in `scripts` block (after `super()`) so it loads after the main webapp's CSS and can override only what it needs to.

---

## Section 2: `card_3d_extract.html` Structure

New partial at `dlc-3D/src/templates/partials/card_3d_extract.html`. Follows the exact main webapp card pattern.

```html
<section class="card dlc-theme hidden" id="dlc-3d-extract-card">
  <!-- Card header (identical pattern to other cards) -->
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.3rem">
    <h2>3D Frame Extractor</h2>
    <button class="btn-sm" id="btn-close-3d-extract" title="Close">
      <svg ...>×</svg>
      Close
    </button>
  </div>
  <p class="subtitle">
    Select a sync-cam video pair, navigate frame-by-frame, and save paired frames
    into <code>labeled-data/</code>.
  </p>

  <!-- Project picker row (always visible, no hidden wrapper) -->
  <div id="dlc3d-project-row" style="display:flex;align-items:center;gap:.5rem;margin-bottom:.75rem">
    <button class="btn-sm" id="dlc3d-btn-open-project">Browse Server</button>
    <span id="dlc3d-project-path" style="flex:1;font-size:.78rem;color:var(--text-dim);
      overflow:hidden;text-overflow:ellipsis;white-space:nowrap">No project loaded</span>
    <button class="btn-sm" id="dlc3d-btn-rescan" style="display:none">↺ Rescan</button>
  </div>

  <!-- Player section: hidden until project loaded -->
  <div id="dlc3d-player-section" style="display:none">
    <div class="dlc3d-layout">

      <!-- Left: session browser -->
      <div id="dlc3d-session-panel">
        <div id="dlc3d-session-empty">Open a DLC project to begin.</div>
      </div>

      <!-- Right: sync-cam player (full current enhanced_player UI) -->
      <div id="dlc3d-player-area">
        <div id="cam-displays">
          <div class="cam-wrap" id="cam1-wrap">
            <div class="cam-label" id="cam1-label">Primary camera</div>
            <div class="cam-frame-wrap" id="cam1-frame-wrap">
              <img id="ep-frame" src="" alt="" style="display:none">
              <span id="no-video-msg">Select a video from the left panel.</span>
            </div>
          </div>
          <div class="cam-wrap" id="ep-cam2-wrap" style="display:none">
            <div class="cam-label" id="cam2-label">Sibling camera</div>
            <div class="cam-frame-wrap">
              <img id="ep-cam2-frame" src="" alt="">
            </div>
          </div>
        </div>

        <!-- Controls: seek, playback, sync-cam row — identical to current enhanced_player UI -->
        <div id="controls">
          <!-- seek row, playback row, sync-cam row as in current dlc_3d.html -->
          ...
        </div>

        <div id="extract-status"></div>

        <div id="labeled-wrap" style="display:none">
          <div id="labeled-header">Extracted frames: <span id="labeled-count">0</span></div>
          <div id="labeled-list"></div>
        </div>
      </div>

    </div>
  </div>

  <!-- Filesystem browser modal (scoped inside card, portaled to body via JS if needed) -->
  <div id="dlc3d-browser-modal">
    <div id="dlc3d-browser-box">
      <div id="dlc3d-browser-box-header">
        <span>Open DLC Project</span>
        <button class="btn-sm" id="dlc3d-browser-close">✕</button>
      </div>
      <div id="dlc3d-browser-path-bar">/</div>
      <div id="dlc3d-browser-list"></div>
    </div>
  </div>
</section>
```

**Key decisions:**
- All element IDs prefixed `dlc3d-` except the ones that `enhanced_player.js` requires by its hardcoded IDs (`ep-frame`, `ep-cam2-frame`, `ep-cam2-wrap`, `cam-displays`, `cam1-label`, `cam2-label`, `cam1-frame-wrap`, `ep-seek`, `ep-play`, `ep-step-back`, `ep-step-fwd`, `ep-skip-start`, `ep-skip-end`, `ep-frame-num`, `ep-frame-total`, `ep-step`, `ep-extract-btn`, `ep-sync-cam`, `ep-extract-sibling`, `ep-extract-sibling-label`). Those IDs remain unchanged.
- The browser modal stays inside the card's DOM. A CSS rule positions it fixed relative to viewport (same as current).

---

## Section 3: JS Changes — `dlc_3d.js`

The init function wires the new card IDs and injects the session bar button.

**Button injection (replaces the old standalone header button):**
```javascript
document.addEventListener("DOMContentLoaded", () => {
  // Inject "3D Frame Extractor" button into DLC session bar
  const dlcBarBtns = document.querySelector("#dlc-bar .session-btns");
  if (dlcBarBtns) {
    const btn = document.createElement("button");
    btn.className = "btn-sm btn-create";
    btn.id = "btn-open-3d-extract";
    btn.textContent = "3D Frame Extractor";
    dlcBarBtns.appendChild(btn);
    btn.addEventListener("click", _openCard);
  }
  ...
});
```

**`_openCard` / `_closeCard` helpers:**
```javascript
function _openCard() {
  // Close other open cards by adding .hidden, then remove .hidden from ours
  document.querySelectorAll(".card:not(.hidden)").forEach(c => c.classList.add("hidden"));
  document.getElementById("dlc-3d-extract-card").classList.remove("hidden");
}
```

**ID updates in existing functions:**
- `document.getElementById("project-path-display")` → `"dlc3d-project-path"`
- `document.getElementById("btn-rescan")` → `"dlc3d-btn-rescan"`
- `document.getElementById("session-panel")` → `"dlc3d-session-panel"`
- `document.getElementById("session-empty")` → `"dlc3d-session-empty"`
- `document.getElementById("browser-modal")` → `"dlc3d-browser-modal"`
- `document.getElementById("browser-list")` → `"dlc3d-browser-list"`
- `document.getElementById("browser-path-bar")` → `"dlc3d-browser-path-bar"`
- `document.getElementById("btn-open-project")` → `"dlc3d-btn-open-project"`
- `document.getElementById("browser-close")` → `"dlc3d-browser-close"`
- `document.getElementById("extract-status")` → `"extract-status"` (unchanged, inside card)
- `document.getElementById("labeled-wrap")` → `"labeled-wrap"` (unchanged)
- `document.getElementById("labeled-count")` → `"labeled-count"` (unchanged)
- `document.getElementById("labeled-list")` → `"labeled-list"` (unchanged)

**Show player section once project loads:**
```javascript
async function _loadProject(path) {
  // ... existing fetch ...
  document.getElementById("dlc3d-player-section").style.display = "";
}
```

**Close button wiring:**
```javascript
document.getElementById("btn-close-3d-extract").addEventListener("click", () => {
  document.getElementById("dlc-3d-extract-card").classList.add("hidden");
});
```

---

## Section 4: CSS Changes — `dlc_3d.css`

Remove all full-page layout rules (`:root`, `body`, `header`, `.main-layout`, etc.) since the main webapp's CSS now owns the page. Keep only card-interior styles, scoped under `#dlc-3d-extract-card`:

- `.dlc3d-layout` — flex row, fills card content area, `overflow: hidden`
- `#dlc3d-session-panel` — left panel, `width: 220px`, `overflow-y: auto`
- `#dlc3d-player-area` — right panel, `flex: 1`, `overflow: hidden`
- `.session-group`, `.session-header`, `.session-body`, `.cam-row`, `.clip-row`, `.cam-badge`, `.clip-section`, `.clip-header` — all scoped under `#dlc-3d-extract-card` prefix
- `#dlc3d-browser-modal` — fixed overlay, `position: fixed`, same visual style as before
- `.frame-chip` — scoped under `#dlc-3d-extract-card`
- `#cam-displays`, `.cam-wrap`, `.cam-label`, `.cam-frame-wrap` — scoped

The `.btn` and `.btn-primary` classes are removed from `dlc_3d.css` entirely — the main webapp's CSS already defines `btn-sm`, `btn-create`, `btn-danger` which the card now uses. Any control buttons inside the player area switch from `.btn` to `.btn-sm` to match the main webapp's button style.

---

## Section 5: Docker-Compose Volume Mount Update

One new volume mount added for the new partial:
```yaml
- ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates/partials/card_3d_extract.html:/app/templates/partials/card_3d_extract.html
```

The `dlc_3d.html` mount changes from the full templates directory to a single file (already done in prior work):
```yaml
- ../deeplabcut-webapp-docker-supports/dlc-3D/src/templates/dlc_3d.html:/app/templates/dlc_3d.html
```

---

## File Map

| Action | Path |
|--------|------|
| Replace | `dlc-3D/src/templates/dlc_3d.html` |
| Create | `dlc-3D/src/templates/partials/card_3d_extract.html` |
| Replace | `dlc-3D/src/static/dlc_3d.js` |
| Replace | `dlc-3D/src/static/dlc_3d.css` |
| Modify | `deeplabcut-webapp-docker/docker-compose.yml` (add card partial volume mount) |

---

## Testing

1. `docker compose up -d dlc-3d` (no rebuild needed — live-mounted files)
2. Navigate to `/dlc-3d/` — confirms main webapp layout visible (session bars, card grid)
3. Click "3D Frame Extractor" button in DLC session bar — confirms card opens
4. Load a project — confirms player section appears and session browser populates
5. Select a video — confirms sync-cam player loads
6. Extract a frame — confirms `labeled-data/` file saved
7. Open any other card — confirms 3D extract card does not interfere
8. All 26 existing pytest tests pass: `python -m pytest tests/ -q`
