// What the SAM panel holds ABOUT ONE VIDEO, and how to forget it.
//
// Switching video reloaded the panel but cleared nothing first, so when the new
// pair had no box or no sweep yet — the normal state of a fresh video — the
// load errored and the PREVIOUS video's trials, strips and thumbnails stayed on
// screen, looking like they belonged to the new one.
//
// The keys live here rather than inline so the reset and its test read from one
// list: adding a per-video field means adding it here, and the test says so.

export const PER_VIDEO_KEYS = [
  "windows",     // trial windows from /windows
  "trials",      // stored results + tag state from /trials
  "active",      // the selected trial
  "masks",       // frame -> SAM mask
  "markers",     // human s/f and start-* notes
  "sibling",     // cam1 path for this pair
  "canUndo",     // whether a tag write can be reverted
  "tagRows",     // onset-sidecar rows behind the whole-video timeline
];

/** A cleared value for every per-video key. Project-level state is untouched. */
export function emptyPanelState() {
  return {
    windows: [],
    trials: [],
    active: null,
    masks: new Map(),
    markers: [],
    sibling: null,
    canUndo: false,
    tagRows: null,
  };
}

/** Does `state` still carry anything about a video? */
export function isCleared(state) {
  const s = state || {};
  return PER_VIDEO_KEYS.every((k) => {
    const v = s[k];
    if (v == null || v === false) return true;
    if (Array.isArray(v)) return v.length === 0;
    if (v instanceof Map || v instanceof Set) return v.size === 0;
    return false;
  });
}
