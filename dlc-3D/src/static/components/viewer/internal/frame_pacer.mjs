// Pure frame-stepping math extracted from enhanced_player.js (_epLoadFrame clamp,
// _epLoop wrap/stop logic). No DOM, no timers — callers own setTimeout/fetch.

export function clampFrame(n, lo, hi) {
  return Math.max(lo, Math.min(n, hi));
}

// Decide the next frame for a playback tick.
// Returns { frame, stop }: stop=true means playback should halt (no-loop boundary).
export function nextFrame({ current, playN, playDir, lo, hi, looping }) {
  const next = current + playN * playDir;
  if (playDir > 0 && next > hi) {
    return looping ? { frame: lo, stop: false } : { frame: current, stop: true };
  }
  if (playDir < 0 && next < lo) {
    return looping ? { frame: hi, stop: false } : { frame: current, stop: true };
  }
  return { frame: next, stop: false };
}

// Remaining delay (ms) for a target fps after a frame took elapsedMs to load.
export function frameDelayMs(fps, elapsedMs) {
  return Math.max(0, Math.round(1000 / fps) - elapsedMs);
}

// The active [lo,hi] frame bounds: full video when unlocked, clip window otherwise.
export function frameRange({ frameCount, unlocked, clipStart, clipEnd }) {
  return unlocked ? { lo: 0, hi: frameCount - 1 } : { lo: clipStart, hi: clipEnd };
}
