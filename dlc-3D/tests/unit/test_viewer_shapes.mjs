import test from "node:test";
import assert from "node:assert/strict";
import {
  SHAPE_ORDER, SHAPE_FN, drawShape, shapeForLayer,
} from "../../src/static/components/viewer/internal/shapes.mjs";

// Recording stub for a CanvasRenderingContext2D.
function makeCtx() {
  const calls = [];
  const props = {};
  const rec = (name) => (...args) => calls.push({ name, args });
  return {
    calls, props,
    set fillStyle(v) { props.fillStyle = v; },
    set strokeStyle(v) { props.strokeStyle = v; },
    set lineWidth(v) { props.lineWidth = v; },
    beginPath: rec("beginPath"), closePath: rec("closePath"),
    moveTo: rec("moveTo"), lineTo: rec("lineTo"), arc: rec("arc"),
    fill: rec("fill"), stroke: rec("stroke"), strokeRect: rec("strokeRect"),
  };
}
const names = (ctx) => ctx.calls.map((c) => c.name);

test("SHAPE_ORDER and shapeForLayer mapping", () => {
  assert.deepEqual(SHAPE_ORDER, ["circle-filled", "diamond", "square", "triangle"]);
  assert.equal(shapeForLayer(0), "circle-filled");
  assert.equal(shapeForLayer(2), "square");
  assert.equal(shapeForLayer(99), "triangle"); // clamps to last
  assert.equal(shapeForLayer(-1), "circle-filled"); // clamps to first, not undefined
});

test("circle-filled fills an arc with the color", () => {
  const ctx = makeCtx();
  drawShape("circle-filled", ctx, 10, 20, 5, "rgb(1,2,3)");
  assert.equal(ctx.props.fillStyle, "rgb(1,2,3)");
  assert.deepEqual(ctx.calls.find((c) => c.name === "arc").args, [10, 20, 5, 0, 2 * Math.PI]);
  assert.ok(names(ctx).includes("fill"));
});

test("square strokes a rect; triangle strokes a 3-point path", () => {
  const sq = makeCtx();
  drawShape("square", sq, 10, 20, 5, "red");
  assert.deepEqual(sq.calls.find((c) => c.name === "strokeRect").args, [5, 15, 10, 10]);

  const tri = makeCtx();
  drawShape("triangle", tri, 10, 20, 5, "red");
  assert.equal(names(tri).filter((n) => n === "lineTo").length, 2);
  assert.ok(names(tri).includes("stroke"));
});

test("unknown shape falls back to circle-filled", () => {
  const ctx = makeCtx();
  drawShape("nope", ctx, 0, 0, 1, "x");
  assert.ok(names(ctx).includes("arc"));
  assert.ok(names(ctx).includes("fill"));
});

test("diamond fills a 4-point path", () => {
  const dia = makeCtx();
  drawShape("diamond", dia, 10, 20, 5, "blue");
  assert.equal(dia.calls.filter((c) => c.name === "lineTo").length, 3);
  assert.ok(dia.calls.some((c) => c.name === "fill"));
  assert.equal(dia.props.fillStyle, "blue");
});

test("SHAPE_FN has an entry for every SHAPE_ORDER name", () => {
  for (const n of SHAPE_ORDER) assert.equal(typeof SHAPE_FN[n], "function");
});
