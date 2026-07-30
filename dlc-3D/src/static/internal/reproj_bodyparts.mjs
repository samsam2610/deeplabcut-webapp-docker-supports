// Which bodyparts get an epipolar line, resolved from the best available source.
//
// Regression this exists to prevent: the original code read
// `markerEditor.posedBodyparts()` — a method that is NOT in that module's public
// API, so it was always undefined — and then fell back to the audit summary,
// which is only populated by a Run and only in memory. With markers on screen
// but no Run clicked in the current page session, the list came back empty and
// no line was ever drawn, whatever the checkbox said.
//
// The bp-chips are the right source: markerEditor renders one per bodypart from
// the loaded h5 as soon as the overlay is on, so they are available without a
// Run, without an Estimate, and without a server round-trip. They are also the
// same elements consulted for each bodypart's colour and hidden state, so the
// line, its colour and its visibility all agree by construction.

/**
 * @param {object} sources
 * @param {string[]} [sources.chipNames]       data-bp values from this card's chips
 * @param {string[]} [sources.knownBodyparts]  list captured by the last Estimate
 * @param {string[]} [sources.auditBodyparts]  keys from the last Run's summary
 * @returns {string[]}
 */
export function activeBodyparts(sources) {
  const s = sources || {};
  for (const list of [s.chipNames, s.knownBodyparts, s.auditBodyparts]) {
    if (Array.isArray(list) && list.length) return list;
  }
  return [];
}
