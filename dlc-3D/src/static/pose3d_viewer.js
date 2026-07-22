// pose3d_viewer.js — isolated three.js 3D pose viewer (spike).
//
// All three.js lives inside this module (isolation): the inline-analysis card
// controller only ever touches the handle returned by makePose3dViewer(). See
// docs/superpowers/specs/2026-07-21-inline-3d-pose-viewer-threejs-spike-design.md.
//
// Data contract (frozen) from GET /dlc/project/triangulate/poses-3d:
//   { bodyparts: string[],
//     skeleton:  [ [bpA, bpB], ... ],
//     frames:    number[],                       // populated frames only
//     points:    [ [ [x,y,z]|null, ... per bp ], ... per frame ],
//     bounds:    { center:[cx,cy,cz], size:s } | null }

import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
import { labelerColor } from "./components/viewer/internal/palette.mjs";

// Per-bodypart colour: reuse the 2D overlay's frame-labeler palette (labelerColor
// by bodypart index) so a joint is the SAME colour in the 2D markers and here.
// The backend returns bodyparts in native (DLC/2D) column order, so index i lines
// up with the 2D marker's color_idx for the same bodypart.
function _colorForIndex(i) {
  return new THREE.Color(labelerColor(i));
}

export function makePose3dViewer({ canvas, statusEl }) {
  // ── three.js objects (created lazily in init) ──────────────────────────────
  let scene = null;
  let camera = null;
  let renderer = null;
  let controls = null;
  let rafId = null;
  let resizeObs = null;
  let inited = false;

  // ── Loaded data state ──────────────────────────────────────────────────────
  let group = null;             // holds spheres + bone LineSegments
  let spheres = [];             // one Mesh per bodypart (index-aligned to bodyparts)
  let boneLine = null;          // THREE.LineSegments for the skeleton
  let bonePairs = [];           // [ [ai, bi], ... ] bodypart-index pairs
  let sharedSphereGeo = null;   // shared SphereGeometry (disposed once)
  let boneGeo = null;           // BufferGeometry backing boneLine
  let bonePositions = null;     // Float32Array for bone vertex positions

  let bodyparts = [];
  let frameToRow = new Map();   // frame number → row index into points
  let points = [];              // per-frame array of per-bodypart [x,y,z]|null
  let bounds = null;            // { center:[..], size } | null

  // Quality columns (parallel to points) + live thresholds (Part 3).
  let scores = [];              // per-frame per-bodypart score (or null)
  let errors = [];              // per-frame per-bodypart error (or null)
  let errorMax = null;          // max finite error across the data (slider upper bound)
  let scoreThr = 0;             // min score gate (0 → show all)
  let errThr = Infinity;        // max error gate (Infinity → show all)
  let _lastFrame = null;        // last frame passed to showFrame (for threshold re-apply)
  let markerMult = 1;           // sphere scale multiplier (adjustable marker size)

  const _setStatus = (msg) => { if (statusEl) statusEl.textContent = msg || ""; };

  // Radius/grid sizing derived from data extent so the scene reads well at any scale.
  function _sceneScale() {
    const s = bounds && bounds.size ? Number(bounds.size) : 0;
    return s > 0 ? s : 1;
  }

  // ── init() — idempotent lazy setup ─────────────────────────────────────────
  function init() {
    if (inited) return;
    inited = true;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x12141a);

    const { w, h } = _canvasSize();
    camera = new THREE.PerspectiveCamera(50, w / Math.max(h, 1), 0.01, 100000);
    camera.position.set(3, 3, 3);

    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h, false);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    // Helpers — ground grid + world axes.
    const grid = new THREE.GridHelper(10, 10, 0x444a55, 0x2a2e37);
    grid.name = "grid";
    scene.add(grid);
    const axes = new THREE.AxesHelper(1);
    axes.name = "axes";
    scene.add(axes);

    // Light so MeshStandardMaterial spheres are visible (also add ambient).
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const dir = new THREE.DirectionalLight(0xffffff, 0.6);
    dir.position.set(1, 2, 1);
    scene.add(dir);

    group = new THREE.Group();
    scene.add(group);

    // Resize handling — prefer ResizeObserver, fall back to window resize.
    if (typeof ResizeObserver !== "undefined") {
      resizeObs = new ResizeObserver(() => _resize());
      resizeObs.observe(canvas);
    } else {
      window.addEventListener("resize", _resize);
    }

    const tick = () => {
      rafId = requestAnimationFrame(tick);
      if (controls) controls.update();
      if (renderer && scene && camera) renderer.render(scene, camera);
    };
    rafId = requestAnimationFrame(tick);
  }

  function _canvasSize() {
    const r = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width || canvas.clientWidth || 300));
    const h = Math.max(1, Math.round(r.height || canvas.clientHeight || 300));
    return { w, h };
  }

  function _resize() {
    if (!renderer || !camera) return;
    const { w, h } = _canvasSize();
    renderer.setSize(w, h, false);
    camera.aspect = w / Math.max(h, 1);
    camera.updateProjectionMatrix();
  }

  // ── load(data) — build meshes + skeleton, fit camera ───────────────────────
  function load(data) {
    if (!inited) init();
    _clearSceneData();

    data = data || {};
    bodyparts = Array.isArray(data.bodyparts) ? data.bodyparts : [];
    points = Array.isArray(data.points) ? data.points : [];
    bounds = data.bounds || null;
    // Quality columns (Part 3) — parallel to points; missing → empty (no gate).
    scores = Array.isArray(data.scores) ? data.scores : [];
    errors = Array.isArray(data.errors) ? data.errors : [];
    errorMax = (data.error_max != null && Number.isFinite(Number(data.error_max)))
      ? Number(data.error_max) : null;
    const frames = Array.isArray(data.frames) ? data.frames : [];
    const skeleton = Array.isArray(data.skeleton) ? data.skeleton : [];

    frameToRow = new Map();
    frames.forEach((f, i) => frameToRow.set(Number(f), i));

    if (!frames.length || !bodyparts.length) {
      _setStatus("no 3D yet");
      _fitToBounds();
      return;
    }

    const scale = _sceneScale();
    const radius = Math.max(scale * 0.012, 1e-4);
    sharedSphereGeo = new THREE.SphereGeometry(radius, 16, 12);

    spheres = bodyparts.map((_, i) => {
      const mat = new THREE.MeshStandardMaterial({
        color: _colorForIndex(i),
        roughness: 0.5,
        metalness: 0.0,
      });
      const m = new THREE.Mesh(sharedSphereGeo, mat);
      m.visible = false;
      group.add(m);
      return m;
    });

    // Skeleton → bodypart-index pairs (skip bones referencing unknown names).
    const bpIndex = new Map(bodyparts.map((b, i) => [b, i]));
    bonePairs = [];
    for (const pair of skeleton) {
      if (!Array.isArray(pair) || pair.length < 2) continue;
      const a = bpIndex.get(pair[0]);
      const b = bpIndex.get(pair[1]);
      if (a === undefined || b === undefined) continue;
      bonePairs.push([a, b]);
    }
    if (bonePairs.length) {
      bonePositions = new Float32Array(bonePairs.length * 2 * 3);
      boneGeo = new THREE.BufferGeometry();
      boneGeo.setAttribute("position", new THREE.BufferAttribute(bonePositions, 3));
      const boneMat = new THREE.LineBasicMaterial({ color: 0xcfd6e4 });
      boneLine = new THREE.LineSegments(boneGeo, boneMat);
      boneLine.visible = false;
      group.add(boneLine);
    }

    // Re-apply the current marker-size multiplier so it persists across reloads
    // (refilter / source switch rebuild the spheres at unit scale).
    spheres.forEach((m) => m.scale.setScalar(markerMult));

    _fitToBounds();
    _setStatus(`3D ready — ${frames.length} frames`);
  }

  // ── showFrame(n) — cheap position update; hide when frame has no row ───────
  function showFrame(n) {
    if (!inited || !group) return;
    _lastFrame = Number(n);
    const row = frameToRow.get(Number(n));
    if (row === undefined) {
      group.visible = false;
      return;
    }
    group.visible = true;
    const rowPts = points[row] || [];
    const srow = scores[row] || null;   // per-bodypart score for this frame (or null)
    const erow = errors[row] || null;   // per-bodypart error for this frame (or null)

    // Spheres — position present points, hide null / gated-out ones. A joint shows
    // only if finite AND (score is null OR score >= scoreThr) AND (error is null OR
    // error <= errThr). Null score/error acts as "no gate".
    const shown = new Array(spheres.length);
    for (let i = 0; i < spheres.length; i++) {
      const p = rowPts[i];
      const m = spheres[i];
      let vis = !!(p && p.length >= 3 && _finite(p));
      if (vis) {
        const sc = srow ? srow[i] : null;
        const er = erow ? erow[i] : null;
        if (sc != null && Number.isFinite(sc) && sc < scoreThr) vis = false;
        else if (er != null && Number.isFinite(er) && er > errThr) vis = false;
      }
      shown[i] = vis;
      if (vis) {
        m.position.set(p[0], p[1], p[2]);
        m.visible = true;
      } else {
        m.visible = false;
      }
    }

    // Bones — rebuild endpoints; hide a bone (degenerate to a point) unless BOTH
    // endpoints are shown this frame (missing OR gated out → hidden).
    if (boneLine && bonePositions) {
      let anyBone = false;
      for (let k = 0; k < bonePairs.length; k++) {
        const [ai, bi] = bonePairs[k];
        const pa = rowPts[ai];
        const pb = rowPts[bi];
        const base = k * 6;
        if (shown[ai] && shown[bi]) {
          bonePositions[base] = pa[0];
          bonePositions[base + 1] = pa[1];
          bonePositions[base + 2] = pa[2];
          bonePositions[base + 3] = pb[0];
          bonePositions[base + 4] = pb[1];
          bonePositions[base + 5] = pb[2];
          anyBone = true;
        } else {
          // Collapse to origin-of-nothing: zero-length segment (invisible).
          for (let j = 0; j < 6; j++) bonePositions[base + j] = 0;
        }
      }
      boneGeo.attributes.position.needsUpdate = true;
      boneLine.visible = anyBone;
    }
  }

  function _finite(p) {
    return Number.isFinite(p[0]) && Number.isFinite(p[1]) && Number.isFinite(p[2]);
  }

  // ── resetView() — recenter camera/controls on bounds ───────────────────────
  function resetView() {
    _fitToBounds();
  }

  // ── zoomBy(factor) — dolly along the camera→target offset (Part 2) ─────────
  // factor < 1 zooms in (shorter offset), > 1 zooms out. Clamp the offset length
  // to the near/far shell so the scene never crosses the clipping planes.
  function zoomBy(factor) {
    if (!camera || !controls) return;
    const offset = camera.position.clone().sub(controls.target);
    const len = offset.length();
    if (!(len > 0) || !(factor > 0)) return;
    let newLen = len * factor;
    const minLen = camera.near * 1.5;
    const maxLen = camera.far * 0.9;
    newLen = Math.min(Math.max(newLen, minLen), maxLen);
    offset.setLength(newLen);
    camera.position.copy(controls.target).add(offset);
    controls.update();
  }

  // ── orbit(dAz, dPol) — rotate camera around the controls target (Part 2) ───
  // Builds a THREE.Spherical from the current offset, nudges theta/phi by the
  // given radians, clamps phi to (epsilon, PI-epsilon), and re-derives position.
  function orbit(dAzimuthRad, dPolarRad) {
    if (!camera || !controls) return;
    const offset = camera.position.clone().sub(controls.target);
    const sph = new THREE.Spherical().setFromVector3(offset);
    sph.theta += Number(dAzimuthRad) || 0;
    sph.phi += Number(dPolarRad) || 0;
    const eps = 1e-3;
    sph.phi = Math.max(eps, Math.min(Math.PI - eps, sph.phi));
    sph.makeSafe();
    offset.setFromSpherical(sph);
    camera.position.copy(controls.target).add(offset);
    controls.update();
  }

  // ── setThresholds({score, error}) — live quality gate (Part 3) ─────────────
  // Stores the thresholds and re-applies them to the current frame (no reload).
  function setThresholds(t) {
    t = t || {};
    if (t.score != null && Number.isFinite(Number(t.score))) scoreThr = Number(t.score);
    if (t.error != null && Number.isFinite(Number(t.error))) errThr = Number(t.error);
    if (_lastFrame != null) showFrame(_lastFrame);
  }

  // Upper bound for the error slider (max finite error in the data, or null).
  function getErrorMax() {
    return errorMax;
  }

  // ── setMarkerSize(mult) — scale every sphere mesh (no geometry rebuild) ─────
  // Stores the multiplier so load() can re-apply it after a rebuild, and scales
  // the existing meshes live.
  function setMarkerSize(mult) {
    const m = Number(mult);
    if (!Number.isFinite(m) || m <= 0) return;
    markerMult = m;
    spheres.forEach((mesh) => mesh.scale.setScalar(markerMult));
  }

  // ── setBackground(hex) — set the scene backdrop colour (persisted per project) ─
  // Accepts any THREE.Color-parseable value ("#12141a"); no-op before init().
  function setBackground(hex) {
    if (!scene || !scene.background) return;
    scene.background.set(hex);
    if (renderer && camera) renderer.render(scene, camera);
  }

  function _fitToBounds() {
    if (!camera || !controls) return;
    let cx = 0, cy = 0, cz = 0, size = 1;
    if (bounds && Array.isArray(bounds.center)) {
      cx = Number(bounds.center[0]) || 0;
      cy = Number(bounds.center[1]) || 0;
      cz = Number(bounds.center[2]) || 0;
      size = Number(bounds.size) > 0 ? Number(bounds.size) : 1;
    }
    const target = new THREE.Vector3(cx, cy, cz);
    controls.target.copy(target);

    // Frame the bounding box: pull back along a fixed diagonal by ~1.6× extent.
    const dist = size * 1.6 + 0.5;
    camera.position.set(cx + dist, cy + dist, cz + dist);
    camera.near = Math.max(size / 1000, 1e-3);
    camera.far = Math.max(size * 100, 1000);
    camera.updateProjectionMatrix();
    camera.lookAt(target);

    // Rescale helpers to match the data extent so they stay useful.
    const grid = scene && scene.getObjectByName("grid");
    const axes = scene && scene.getObjectByName("axes");
    if (grid) { grid.position.set(cx, cy, cz); const g = size * 2 || 2; grid.scale.set(g / 10, 1, g / 10); }
    if (axes) { axes.position.set(cx, cy, cz); const a = size * 0.5 || 1; axes.scale.set(a, a, a); }

    controls.update();
  }

  // ── dispose() — stop loop, free GPU resources ──────────────────────────────
  function dispose() {
    if (rafId != null) cancelAnimationFrame(rafId);
    rafId = null;
    if (resizeObs) { resizeObs.disconnect(); resizeObs = null; }
    else window.removeEventListener("resize", _resize);
    _clearSceneData();
    if (controls) { controls.dispose(); controls = null; }
    if (renderer) { renderer.dispose(); renderer = null; }
    scene = null;
    camera = null;
    inited = false;
  }

  // Dispose per-load geometry/materials + detach meshes from the group.
  function _clearSceneData() {
    if (group) {
      for (const m of spheres) {
        group.remove(m);
        if (m.material) m.material.dispose();
      }
      if (boneLine) group.remove(boneLine);
    }
    spheres = [];
    if (boneLine && boneLine.material) boneLine.material.dispose();
    boneLine = null;
    if (boneGeo) { boneGeo.dispose(); boneGeo = null; }
    bonePositions = null;
    bonePairs = [];
    if (sharedSphereGeo) { sharedSphereGeo.dispose(); sharedSphereGeo = null; }
    frameToRow = new Map();
    points = [];
    scores = [];
    errors = [];
  }

  return { init, load, showFrame, resetView, zoomBy, orbit, setThresholds, setMarkerSize, setBackground, getErrorMax, dispose };
}
