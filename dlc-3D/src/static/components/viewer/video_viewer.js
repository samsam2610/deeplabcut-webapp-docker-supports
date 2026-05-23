// VideoViewer — reusable base video player (DOM shell).
// Assembles the pure reducers in ./internal/ into a frame-by-frame, N-tile,
// frame-locked viewer with a hook bus that feature modules subscribe to.
//
// All coupling is injected via config — no hardcoded endpoints, DOM ids, or
// localStorage keys. Frames are fetched as images and swapped onto <img> elements
// (no <video> element), matching the clip-cutter / viewer_3d players this is
// extracted from.
//
// Hook-bus events (subscribe via viewer.on(event, cb)):
//   "videoLoad"  ({ videoPath, frameCount, tiles })   after a video is loaded
//   "frameChange"(frame)                               after every seek
//   "drawTile"   (tile, frame)                         per tile after a seek
//   "teardown"   ()                                    on destroy()

import { makeEventBus } from "./internal/event_bus.mjs";
import { planTiles } from "./internal/tile_layout.mjs";
import { planSeek } from "./internal/seek_plan.mjs";
import { fitViewerSize } from "./internal/fit_viewer.mjs";
import { resolveKey, clampPlayStep, clampFps } from "./internal/controls.mjs";
import { nextFrame, frameDelayMs } from "./internal/frame_pacer.mjs";

const TILE_HTML = `
  <div class="vv-tile-canvas-wrap" style="position:relative;display:inline-block;">
    <img class="vv-frame-img" style="display:block;max-width:100%;">
    <canvas class="vv-overlay-canvas" style="position:absolute;top:0;left:0;pointer-events:none;"></canvas>
    <div class="vv-frame-spinner hidden"></div>
    <div class="vv-tile-label"></div>
  </div>`;

class Tile {
  constructor(cam, videoRel, label, rootEl) {
    this.cam = cam;
    this.videoRel = videoRel;
    this.label = label;
    this.rootEl = rootEl;
    this.imgEl = rootEl.querySelector(".vv-frame-img");
    this.canvasEl = rootEl.querySelector(".vv-overlay-canvas");
    this.labelEl = rootEl.querySelector(".vv-tile-label");
    this.spinnerEl = rootEl.querySelector(".vv-frame-spinner");
    this._loadToken = 0;
    if (this.labelEl) this.labelEl.textContent = label || "";
  }
}

export class VideoViewer {
  constructor({ mount, endpoints, fps = 15, storagePrefix = "vv", keymap = resolveKey } = {}) {
    if (!mount) throw new Error("VideoViewer: `mount` element is required");
    if (!endpoints || typeof endpoints.frame !== "function") {
      throw new Error("VideoViewer: `endpoints.frame(videoPath, n)` is required");
    }
    this.mount = mount;
    this.endpoints = endpoints;
    this.storagePrefix = storagePrefix;
    this._resolveKey = keymap;
    this._bus = makeEventBus();
    this._features = [];

    // playback / view state
    this._currentFrame = 0;
    this._frameCount = 0;
    this._fps = clampFps(fps, 15);
    this._playN = 1;
    this._playDir = 1;
    this._looping = false;
    this._playing = false;
    this._playTimer = null;
    this._zoom = 100;
    this._skipN = 10;
    this.framesMode = false;

    this.tiles = [];
    this._videoPath = null;
    this._seekToken = 0;

    const doc = mount.ownerDocument;
    this.rowEl = doc.createElement("div");
    this.rowEl.className = "vv-tile-row";
    this.rowEl.style.display = "flex";
    this.rowEl.style.gap = "8px";
    mount.appendChild(this.rowEl);

    if (!mount.getAttribute("tabindex")) mount.setAttribute("tabindex", "0");
    this._onKeyDown = (e) => this._handleKeyDown(e);
    mount.addEventListener("keydown", this._onKeyDown);
  }

  // ── hook bus ──────────────────────────────────────────────
  on(event, cb) { return this._bus.on(event, cb); }
  _emit(event, ...args) { this._bus.emit(event, ...args); }

  // ── feature composition ───────────────────────────────────
  use(feature) {
    if (feature && typeof feature.attach === "function") feature.attach(this);
    this._features.push(feature);
    return this;
  }

  // ── getters ───────────────────────────────────────────────
  currentFrame() { return this._currentFrame; }
  frameCount() { return this._frameCount; }
  getTile(i) { return this.tiles[i] || null; }
  videoPath() { return this._videoPath; }
  isPlaying() { return this._playing; }

  // ── loading ───────────────────────────────────────────────
  async load({ videoPath, siblingPath, frameCount, framesMode = false } = {}) {
    this._stop();
    this._clearTiles();
    this._videoPath = videoPath;
    this.framesMode = framesMode;

    if (frameCount != null) {
      this._frameCount = frameCount;
    } else if (this.endpoints.videoInfo) {
      try {
        const info = await (await fetch(this.endpoints.videoInfo(videoPath))).json();
        this._frameCount = info.frame_count || 0;
        if (info.fps) this._fps = info.fps;
      } catch (_) { this._frameCount = 0; }
    }

    if (siblingPath === undefined && this.endpoints.sibling && !framesMode) {
      try {
        const j = await (await fetch(this.endpoints.sibling(videoPath))).json();
        siblingPath = j.sibling_video_path || null;
      } catch (_) { siblingPath = null; }
    }

    const descs = planTiles({ primaryVideoRel: videoPath, siblingVideoRel: siblingPath || null });
    this.tiles = descs.map((d) => this._createTile(d));

    this._emit("videoLoad", { videoPath, frameCount: this._frameCount, tiles: this.tiles });
    await this.seek(0);
  }

  _createTile(desc) {
    const wrap = this.mount.ownerDocument.createElement("div");
    wrap.className = "vv-tile";
    wrap.dataset.cam = String(desc.cam);
    wrap.innerHTML = TILE_HTML;
    this.rowEl.appendChild(wrap);
    return new Tile(desc.cam, desc.videoRel, desc.label, wrap);
  }

  _clearTiles() {
    // Features that add child DOM/listeners to tiles must rebuild on the "videoLoad"
    // hook: load() calls this mid-session (before "teardown") and removes tile nodes wholesale.
    this.rowEl.innerHTML = "";
    this.tiles = [];
  }

  // ── seeking (frame-locked across tiles) ───────────────────
  async seek(n) {
    const token = ++this._seekToken;
    const { frame, loads } = planSeek({
      n, frameCount: this._frameCount, tiles: this.tiles, framesMode: this.framesMode,
    });
    const loadCams = new Set(loads.map((l) => l.cam));
    await Promise.all(
      this.tiles
        .filter((t) => loadCams.has(t.cam))
        .map((t) => this._loadTileFrame(t, frame, t.cam === 0)),
    );
    if (token !== this._seekToken) return; // superseded by a newer seek
    this._currentFrame = frame;
    this._emit("frameChange", frame);
    for (const tile of this.tiles) this._emit("drawTile", tile, frame);
  }

  async _loadTileFrame(tile, frame, isPrimary) {
    if (!tile.videoRel || !tile.imgEl) return;
    const token = ++tile._loadToken;
    if (tile.spinnerEl) tile.spinnerEl.classList.remove("hidden");
    try {
      const url = this.endpoints.frame(tile.videoRel, frame);
      const img = new Image();
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = (e) => reject(e instanceof Error ? e : new Error("frame load failed"));
        img.src = url;
      });
      if (token !== tile._loadToken) return;        // superseded by a newer seek
      tile.imgEl.src = img.src;
      if (isPrimary) {
        if (frame + 1 < this._frameCount) {
          const pre = new Image();
          pre.src = this.endpoints.frame(tile.videoRel, frame + 1);
        }
        await new Promise(requestAnimationFrame);   // paint barrier for honest pacing
      }
    } catch (_) {
      /* keep the previous frame on error */
    } finally {
      // Always hide — a newer seek re-shows its own spinner synchronously before awaiting.
      if (tile.spinnerEl) tile.spinnerEl.classList.add("hidden");
    }
  }

  // ── stepping ──────────────────────────────────────────────
  step(delta) { return this.seek(this._currentFrame + delta); }
  stepSkip(dir) { return this.seek(this._currentFrame + dir * this._skipN); }
  setSkipN(n) { this._skipN = Math.max(1, parseInt(n, 10) || 1); }

  // ── playback ──────────────────────────────────────────────
  setFps(v) { this._fps = clampFps(v, this._fps); }
  setPlayStep(v) { this._playN = clampPlayStep(v, this._playN); }
  setLooping(on) { this._looping = !!on; }
  setPlayDir(dir) { this._playDir = dir < 0 ? -1 : 1; }

  play() {
    if (this._playing) return;
    this._playing = true;
    this._playLoop();
  }
  pause() { this._stop(); }
  togglePlay() { if (this._playing) this.pause(); else this.play(); }

  _stop() {
    if (this._playTimer !== null) { clearTimeout(this._playTimer); this._playTimer = null; }
    this._playing = false;
  }

  async _playLoop() {
    if (!this._playing) return;
    const { frame, stop } = nextFrame({
      current: this._currentFrame, playN: this._playN, playDir: this._playDir,
      lo: 0, hi: Math.max(this._frameCount - 1, 0), looping: this._looping,
    });
    if (stop) { this._stop(); return; }
    const t0 = performance.now();
    await this.seek(frame);
    if (!this._playing) return;
    const elapsed = performance.now() - t0;
    this._playTimer = setTimeout(() => this._playLoop(), frameDelayMs(this._fps, elapsed));
  }

  // ── zoom ──────────────────────────────────────────────────
  setZoom(pct) {
    this._zoom = pct;
    const primary = this.getTile(0);
    if (!primary || !primary.imgEl || !primary.imgEl.naturalWidth) return;
    const baseW = this.mount.clientWidth || primary.imgEl.naturalWidth;
    const view = this.mount.ownerDocument.defaultView || window;
    const maxW = Math.max(baseW, (view.innerWidth || baseW) - 32);
    const { width, marginLeft } = fitViewerSize({ baseW, maxW, zoom: pct });
    this.rowEl.style.width = width + "px";
    this.rowEl.style.marginLeft = marginLeft < 0 ? `${marginLeft}px` : "";
  }

  // ── keyboard ──────────────────────────────────────────────
  _handleKeyDown(e) {
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    const intent = this._resolveKey({ key: e.key, ctrlKey: e.ctrlKey });
    if (!intent) return;
    e.preventDefault();
    if (intent.type === "playPause") this.togglePlay();
    else if (intent.type === "step") this.step(intent.delta);
    else if (intent.type === "stepSkip") this.stepSkip(intent.dir);
  }

  // ── teardown ──────────────────────────────────────────────
  destroy() {
    this._stop();
    this.mount.removeEventListener("keydown", this._onKeyDown);
    this._emit("teardown");
    this._clearTiles();
  }
}
