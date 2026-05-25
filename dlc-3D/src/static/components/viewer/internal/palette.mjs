// Pure HSV→RGB palette used for multi-layer overlay marker colors.
// Ported from the original viewer_3d.js (_vaHsvToRgb / _vaPaletteColor).

export function hsvToRgb(h, s, v) {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  let r, g, b;
      // Guard against h<0: JS % can yield negatives; double-modulo keeps i in 0..5.
  switch (((i % 6) + 6) % 6) {
    case 0: r = v; g = t; b = p; break;
    case 1: r = q; g = v; b = p; break;
    case 2: r = p; g = v; b = t; break;
    case 3: r = p; g = q; b = v; break;
    case 4: r = t; g = p; b = v; break;
    default: r = v; g = p; b = q;
  }
  return `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
}

export function paletteColor(idx, total) {
  return hsvToRgb(idx / Math.max(total, 1), 0.9, 0.95);
}

// ── Frame-labeler (Napari-inspired) fixed palette ──
// 15 hexes copied verbatim from frame_labeler_3d.js:623-627. Used for
// primary-layer markers + bp-chips so the labeler, chips, and overlay all agree
// on a bodypart's color. Comparison layers keep paletteColor (HSV) above for
// per-layer differentiation.
export const FL_COLORS = [
  "#f87171", "#fb923c", "#fbbf24", "#a3e635", "#34d399",
  "#22d3ee", "#818cf8", "#e879f9", "#f43f5e", "#10b981",
  "#3b82f6", "#ec4899", "#f59e0b", "#84cc16", "#06b6d4",
];

// idx → hex, cycling every 15. Negative-safe (double-modulo, matching hsvToRgb's
// guard) so a stray -1 index never yields undefined.
export function labelerColor(idx) {
  const n = FL_COLORS.length;
  return FL_COLORS[(((idx % n) + n) % n)];
}
