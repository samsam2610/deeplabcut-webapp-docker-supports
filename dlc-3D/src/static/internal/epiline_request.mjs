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
