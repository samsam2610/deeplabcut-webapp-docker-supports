// Pure request-shaping for the frame labeler's epipolar overlay. Kept free of
// DOM and fetch so the gating rules and payload construction are unit-testable,
// matching the pattern of pair_map.mjs and epiline_label.mjs.

/**
 * Why the overlay cannot run, or null when it can.
 * Ordered so the user hears the condition they can fix fastest first.
 */
export function epiGateReason({ syncOn, calibrationExists, camCount }) {
  if (!syncOn) return "turn on sync to see both cameras";
  if (camCount < 2) return "this frame has only one camera";
  if (camCount > 2) return "epipolar lines support exactly two cameras";
  if (!calibrationExists) return "no calibration.toml in this session folder";
  return null;
}

/**
 * Points to project: every bodypart with a label that is not hidden.
 * Returned in `bodyparts` order so the label staircase is stable across fires.
 */
export function collectRefPoints(labels, hidden, bodyparts) {
  const lab = labels || {};
  const hid = hidden || {};
  const out = [];
  for (const bp of bodyparts || []) {
    const pt = lab[bp];
    if (!pt || hid[bp]) continue;
    const [x, y] = pt;
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    out.push({ bodypart: bp, x, y });
  }
  return out;
}

/** Identity of a request, so an unchanged one is never re-issued. */
export function payloadSignature(session, refCam, tgtCam, points) {
  const pts = (points || [])
    .map((p) => `${p.bodypart}:${p.x}:${p.y}`)
    .join(",");
  return `${session}|${refCam}>${tgtCam}|${pts}`;
}

//: How close two P presses must be to count as a double-tap, in ms.
export const EPI_DOUBLE_TAP_MS = 350;

/**
 * Classify a P keypress as a single toggle or the second half of a double-tap.
 *
 * The single action fires IMMEDIATELY rather than waiting out the double-tap
 * window — a 350 ms lag on the common single press is worse than the brief
 * flicker of the double. So a second press within the window has to undo what
 * the first one did: `revert` says the caller should restore the overlay state
 * from before the first press, then apply the freeze toggle.
 *
 * @param {number} now      timestamp of this press
 * @param {number|null} last timestamp of the previous press, or null
 * @param {number} windowMs
 * @returns {{kind: "single"|"double", revert: boolean}}
 */
export function classifyPPress(now, last, windowMs = EPI_DOUBLE_TAP_MS) {
  const isDouble = last !== null && Number.isFinite(last)
    && (now - last) >= 0 && (now - last) <= windowMs;
  return isDouble
    ? { kind: "double", revert: true }
    : { kind: "single", revert: false };
}
