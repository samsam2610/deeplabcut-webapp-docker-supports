// Pure placement logic for the SAM card's pellet box.
//
// Kept in its own module so it can be unit-tested without a DOM, and imported
// by inline_analysis_3d_sam.js at runtime. The card's earlier box handling
// lived inside the DOM-bound module where nothing could reach it, which is how
// a two-line invariant (overlays are not tiles) shipped broken.

/** Prefix for the overlay canvases this card creates. */
export const OVERLAY_PREFIX = "ia3ds-ov-";

/** Canvases the card owns, which must never be mistaken for player tiles. */
const OWN_CANVAS_IDS = new Set(["ia3ds-sam-strip", "ia3ds-sam-tags"]);

/**
 * Is this canvas one of the player's video tiles?
 *
 * Anything the card created is not. The previous version excluded exactly two
 * ids and nothing else, so overlay canvases — which had no id at all — counted
 * as tiles and each poll gave every overlay its own overlay.
 */
export function isTile(canvas) {
  const id = (canvas && canvas.id) || "";
  if (OWN_CANVAS_IDS.has(id)) return false;
  if (id.startsWith(OVERLAY_PREFIX)) return false;
  return true;
}

export function selectTiles(canvases) {
  return Array.from(canvases || []).filter(isTile);
}

const KEY_DELTA = { w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0] };

/** Is `key` one this module handles? Lets the caller ignore everything else. */
export function isNudgeKey(key) {
  return Object.prototype.hasOwnProperty.call(KEY_DELTA, String(key).toLowerCase());
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

/**
 * Place a click.
 *
 * The first click for a camera sets that camera's box AND records a pellet;
 * every later click records a pellet only. A click always means "the pellet is
 * here", so there is no mode to get wrong.
 *
 * Clicking the same (frame, camera) twice replaces that frame's pellet — a
 * second click there is a correction, not a second observation.
 *
 * Returns a NEW state; callers keep the old one if a save fails.
 */
export function placeClick(state, { cam, frame, x, y }) {
  const marks = (state.marks || []).slice();
  const hasBox = marks.some((m) => m.kind === "box" && m.cam === cam);
  const ids = [];

  if (!hasBox) {
    const box = { kind: "box", cam, frame, x, y };
    marks.push(box);
    ids.push(box);
  }
  const dup = marks.findIndex(
    (m) => m.kind === "pellet" && m.cam === cam && m.frame === frame);
  const pellet = { kind: "pellet", cam, frame, x, y };
  if (dup >= 0) marks[dup] = pellet;
  else marks.push(pellet);
  ids.push(pellet);

  return {
    ...state,
    marks,
    // WASD moves whatever was just placed. A first click placed two marks that
    // describe the same point, so they move together.
    last: { kind: hasBox ? "pellet" : "box", cam, frame, marks: ids },
  };
}

/**
 * Nudge the most recent placement.
 *
 * `bounds` is optional; when given, positions are clamped inside the frame so a
 * held key cannot walk the box off the image.
 */
export function nudge(state, key, step = 1, bounds = null) {
  const delta = KEY_DELTA[String(key).toLowerCase()];
  if (!delta || !state.last || !state.last.marks || !state.last.marks.length) {
    return state;
  }
  const moving = new Set(state.last.marks);
  const marks = (state.marks || []).map((m) => {
    if (!moving.has(m)) return m;
    let x = m.x + delta[0] * step;
    let y = m.y + delta[1] * step;
    if (bounds) {
      x = clamp(x, 0, bounds.width - 1);
      y = clamp(y, 0, bounds.height - 1);
    }
    return { ...m, x, y };
  });
  // Re-point `last` at the new objects, so a second nudge moves the same marks.
  const remapped = state.last.marks.map(
    (old) => marks[(state.marks || []).indexOf(old)]).filter(Boolean);
  return { ...state, marks, last: { ...state.last, marks: remapped } };
}

/**
 * Centre for a camera: its box mark, else the project default, else unplaced.
 *
 * Derived rather than stored separately — the box and the labels then cannot
 * disagree, because there is only one place either can come from.
 */
export function centreFor(state, cam, projectDefault) {
  const box = (state.marks || []).find((m) => m.kind === "box" && m.cam === cam);
  if (box) return { cx: box.x, cy: box.y };
  if (projectDefault && projectDefault.cx != null && projectDefault.cy != null) {
    return { cx: projectDefault.cx, cy: projectDefault.cy };
  }
  return null;
}

/** Cameras still needing a box — what blocks sweeping. */
export function unplacedCameras(state, cams = ["cam0", "cam1"]) {
  return cams.filter(
    (c) => !(state.marks || []).some((m) => m.kind === "box" && m.cam === c));
}
