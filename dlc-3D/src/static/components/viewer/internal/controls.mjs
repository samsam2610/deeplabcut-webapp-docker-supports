// Pure control mapping for the base viewer. Mirrors viewer_3d.js keydown handler
// (space / arrows / ctrl+arrows) and _vaPlayStep / _vaPlaybackFps clamps.
// Feature keys (Tab, WASD, Delete) are intentionally NOT handled here.

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

export function clampPlayStep(v, def = 1) {
  const n = parseInt(v, 10);
  return Math.max(1, Math.min(100, isNaN(n) ? def : n));
}

export function clampFps(v, def = 5) {
  const n = parseInt(v, 10);
  return Math.max(1, Math.min(120, isNaN(n) ? def : n));
}

export function clampTileWeight(v, def = 100) {
  const n = parseInt(v, 10);
  return Math.max(50, Math.min(500, isNaN(n) ? def : n));
}
