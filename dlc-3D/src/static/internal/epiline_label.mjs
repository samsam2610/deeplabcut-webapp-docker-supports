// Pure geometry for placing an epipolar line's bodypart label at the frame edge.
//
// Labels are anchored at ONE end of the clipped segment and stepped along the
// line, so that where several lines converge near the epipole their labels form
// a staircase instead of a pile — and every label still sits on the line it
// names.

/**
 * @param {Array} segment  [[x1,y1],[x2,y2]] in video-pixel coordinates.
 * @param {number} order   Index among visible bodyparts; 0 sits at the endpoint.
 * @param {number} step    Pixels to advance per order.
 * @returns {{x:number,y:number,ux:number,uy:number}|null}
 */
export function labelAnchor(segment, order, step) {
  if (!segment || segment.length !== 2) return null;
  const [p, q] = segment;
  if (!p || !q || p.length !== 2 || q.length !== 2) return null;
  const [x1, y1] = p;
  const [x2, y2] = q;
  if (![x1, y1, x2, y2].every(Number.isFinite)) return null;

  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (!(len > 0)) return null;

  // Anchor at the end nearer the frame's top-left so the label does not hop
  // between edges while scrubbing. Ties on x+y fall back to smaller x, then
  // smaller y, so the choice never depends on argument order.
  const pFirst =
    (x1 + y1 !== x2 + y2) ? (x1 + y1 < x2 + y2)
    : (x1 !== x2) ? (x1 < x2)
    : (y1 <= y2);

  const ax = pFirst ? x1 : x2;
  const ay = pFirst ? y1 : y2;
  const ux = (pFirst ? dx : -dx) / len;
  const uy = (pFirst ? dy : -dy) / len;

  const d = Math.max(0, order) * step;
  return { x: ax + ux * d, y: ay + uy * d, ux, uy };
}
