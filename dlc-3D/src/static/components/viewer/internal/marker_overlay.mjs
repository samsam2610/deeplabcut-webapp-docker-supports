// Pure overlay/edit logic for the MarkerEditor feature: scale + coordinate transforms,
// hit-testing, pose↔edit merge, prefetch-window math, layer threshold/cache-key, WASD
// nudge, tab cycling, and the save-marker payload. No DOM, no fetch.
// Marker drawing reuses palette.mjs + shapes.mjs (Phase 1). Edits are a plain object
// keyed by frame: { [frame]: { [bp]: { x, y } } }, where x===null,y===null means deleted.

// ── scale + coordinate transforms ──
export function scaleFor(naturalW, naturalH, canvasW, canvasH) {
  return { sx: canvasW / (naturalW || 1), sy: canvasH / (naturalH || 1) };
}

export function videoToCanvas(x, y, scale) {
  return { cx: Math.round(x * scale.sx), cy: Math.round(y * scale.sy) };
}

export function canvasToVideo(cx, cy, scale) {
  return { x: cx / scale.sx, y: cy / scale.sy };
}

export function markerRadius(markerSize, scale) {
  return Math.max(1, Math.round(markerSize * Math.min(scale.sx, scale.sy)));
}

// ── hit-testing ──
// poses: [{ bp, x, y }]; frameEdits: { [bp]: { x, y } } overrides position (null = deleted);
// pad widens the hit radius (6 for plain, 8 when accounting for edits). Returns bp or null.
export function hitTest(poses, cx, cy, scale, markerSize, frameEdits = {}, pad = 6) {
  const hitR = (markerSize + pad) * Math.max(scale.sx, scale.sy);
  for (const pose of poses) {
    const e = frameEdits[pose.bp];
    if (e && (e.x == null || e.y == null)) continue; // deleted marker
    const px = (e ? e.x : pose.x) * scale.sx;
    const py = (e ? e.y : pose.y) * scale.sy;
    const dx = px - cx;
    const dy = py - cy;
    if (Math.sqrt(dx * dx + dy * dy) <= hitR) return pose.bp;
  }
  return null;
}

// ── pose↔edit merge (for rendering) ──
export function resolvePose(pose, frameEdits = {}) {
  const e = frameEdits[pose.bp];
  if (!e) return { x: pose.x, y: pose.y, edited: false, deleted: false };
  if (e.x == null || e.y == null) return { x: null, y: null, edited: true, deleted: true };
  return { x: e.x, y: e.y, edited: true, deleted: false };
}

// ── local edits (immutable plain-object ops) ──
export function setEdit(edits, frame, bp, x, y) {
  const frameDict = {};
  for (const [k, v] of Object.entries(edits[frame] || {})) frameDict[k] = { ...v };
  frameDict[bp] = { x, y };
  return { ...edits, [frame]: frameDict };
}

export function deleteEdit(edits, frame, bp) {
  return setEdit(edits, frame, bp, null, null);
}

export function frameEditsOf(edits, frame) {
  return edits[frame] || {};
}

export function editedFrameCount(edits) {
  return Object.keys(edits).length;
}

// Convert the in-memory edits ({ [frame]: {bp:{x,y}} }, integer frame keys) into
// the server edit-cache format ({ "frame_<N>": {bp:{x,y}} }) so Save can send
// memory directly in the request body — making the save independent of the
// separate, un-awaited marker-edit mirror that Save used to race.
export function serializeEditsForSave(edits) {
  const out = {};
  for (const [frame, bpEdits] of Object.entries(edits || {})) {
    out[`frame_${frame}`] = bpEdits;
  }
  return out;
}

// ── WASD nudge ──
export function nudge(base, key, shift) {
  if (!base || base.x == null || base.y == null) return null; // can't nudge a deleted/absent marker
  const step = shift ? 10 : 1;
  let dx = 0;
  let dy = 0;
  switch (key.toLowerCase()) {
    case "a": dx = -step; break;
    case "d": dx = step; break;
    case "w": dy = -step; break;
    case "s": dy = step; break;
    default: return null;
  }
  return { x: base.x + dx, y: base.y + dy };
}

// ── tab cycling ──
export function nextBodypart(list, current, backward = false) {
  if (!list.length) return null;
  const idx = list.indexOf(current);
  if (idx < 0) return list[0];
  const n = backward ? (list.length + idx - 1) % list.length : (idx + 1) % list.length;
  return list[n];
}

// ── prefetch window ──
export function prefetchWindow(fromFrame, windowSize, frameCount) {
  const end = Math.min(fromFrame + windowSize, frameCount);
  return { start: fromFrame, count: Math.max(0, end - fromFrame) };
}

// allCached: true iff every frame in [fromFrame, fromFrame+windowSize) (clamped to
// frameCount) is present in the cache Map with a matching `key`.
export function allCached(cache, fromFrame, windowSize, frameCount, key) {
  for (let i = fromFrame; i < fromFrame + windowSize && i < frameCount; i++) {
    const c = cache.get(i);
    if (!c || c.key !== key) return false;
  }
  return true;
}

// Parse a pose-endpoint JSON body that may contain non-finite literals (NaN /
// Infinity / -Infinity, emitted by numpy/pandas for undetected frames). The browser's
// JSON.parse rejects those, so sanitize them to null first. Without this, a single
// undetected frame throws and the consumer would permanently disable the pose layer.
export function parsePoseJson(text) {
  return JSON.parse(text.replace(/\bNaN\b/g, "null").replace(/-?\bInfinity\b/g, "null"));
}

// Body parts that actually have a drawable marker at a frame: finite x AND y.
// Mirrors renderTile's finiteness gate so the chip 'labeled' state matches what is
// drawn. Undetected parts leak through the backend's `lh < threshold` filter with
// NaN→null coords (NaN < threshold is False); without this they'd show a checked
// chip but no dot.
export function posedBodyparts(poses) {
  const s = new Set();
  for (const p of poses || []) {
    if (Number.isFinite(p.x) && Number.isFinite(p.y)) s.add(p.bp);
  }
  return s;
}

// Body parts that have a (non-deleted) local edit but are ABSENT from the
// detected poses — i.e. a marker placed on a below-threshold/undetected part the
// backend omits from frame-poses (`lh < threshold` → dropped). renderTile and
// hitTest iterate `poses`, so without merging these the placed marker is stored
// (edit count rises) yet never drawn or selectable. Returns the bp names to add.
export function editedOnlyBodyparts(poses, frameEdits) {
  const have = new Set((poses || []).map((p) => p.bp));
  const out = [];
  for (const [bp, e] of Object.entries(frameEdits || {})) {
    if (have.has(bp)) continue;                       // already drawn via its pose
    if (!e || e.x == null || e.y == null) continue;   // deleted / no coords
    out.push(bp);
  }
  return out;
}

// ── layer threshold + cache key ──
export function layerThreshold(layer, globalThreshold, perLayer) {
  return (perLayer && layer.threshold != null) ? layer.threshold : globalThreshold;
}

export function poseCacheKey(h5Path, threshold) {
  return `${h5Path}:${Number(threshold).toFixed(2)}`;
}

// ── save-marker payload (x===null,y===null for delete) ──
export function buildMarkerEditPayload(h5Path, frame, bp, x, y) {
  return { h5: h5Path, frame, bp, x, y };
}
