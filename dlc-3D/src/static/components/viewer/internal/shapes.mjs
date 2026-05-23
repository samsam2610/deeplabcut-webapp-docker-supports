// Marker shape draw primitives for multi-layer overlay rendering.
// Ported verbatim from the original viewer_3d.js draw helpers.

export function drawCircleFilled(ctx, x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 2 * Math.PI);
  ctx.fill();
}

export function drawDiamond(ctx, x, y, r, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x + r, y);
  ctx.lineTo(x, y + r);
  ctx.lineTo(x - r, y);
  ctx.closePath();
  ctx.fill();
}

export function drawSquare(ctx, x, y, r, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(x - r, y - r, 2 * r, 2 * r);
}

export function drawTriangle(ctx, x, y, r, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x + r, y + r);
  ctx.lineTo(x - r, y + r);
  ctx.closePath();
  ctx.stroke();
}

export const SHAPE_ORDER = ["circle-filled", "diamond", "square", "triangle"];

export const SHAPE_FN = {
  "circle-filled": drawCircleFilled,
  "diamond": drawDiamond,
  "square": drawSquare,
  "triangle": drawTriangle,
};

export function drawShape(name, ctx, x, y, r, color) {
  (SHAPE_FN[name] || drawCircleFilled)(ctx, x, y, r, color);
}

// Layer index → shape name (clamped to the last shape), matching
// viewer_3d.js _SHAPE_ORDER[Math.min(i, _SHAPE_ORDER.length - 1)].
export function shapeForLayer(i) {
  return SHAPE_ORDER[Math.min(i, SHAPE_ORDER.length - 1)];
}
