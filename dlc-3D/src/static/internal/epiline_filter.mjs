// Whether an epipolar line should be DRAWN, given the confidence of the
// reference marker that induced it.
//
// This gates display only. gate_ref still decides what the engine judges, and
// the two are deliberately separate: the default display threshold sits BELOW
// gate_ref so lines the engine ignored remain visible, which is often what
// explains an UNJUDGED verdict.

/**
 * @param {number|null|undefined} likelihood  reference marker confidence
 * @param {number|null|undefined} threshold   the panel's display threshold
 * @returns {boolean}
 */
export function shouldDrawLine(likelihood, threshold) {
  // An unknown confidence is not a confident one — hide it either way.
  if (!Number.isFinite(likelihood)) return false;
  // A blanked or malformed threshold must not empty the overlay while the user
  // is mid-edit, so fall back to drawing.
  if (!Number.isFinite(threshold)) return true;
  return likelihood >= threshold;
}
