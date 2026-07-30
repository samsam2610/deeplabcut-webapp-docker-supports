import test from "node:test";
import assert from "node:assert/strict";
import { labelAnchor } from "../../src/static/internal/epiline_label.mjs";

const SEG = [[10, 10], [110, 10]];   // horizontal, left end nearer top-left

test("labelAnchor: order 0 anchors exactly at the top-left-most endpoint", () => {
  const a = labelAnchor(SEG, 0, 14);
  assert.equal(a.x, 10);
  assert.equal(a.y, 10);
});

test("labelAnchor: endpoint choice does not depend on the order supplied", () => {
  const a = labelAnchor(SEG, 0, 14);
  const b = labelAnchor([[110, 10], [10, 10]], 0, 14);
  assert.deepEqual({ x: a.x, y: a.y }, { x: b.x, y: b.y });
});

test("labelAnchor: successive orders step further along the line", () => {
  const p0 = labelAnchor(SEG, 0, 14);
  const p1 = labelAnchor(SEG, 1, 14);
  const p2 = labelAnchor(SEG, 2, 14);
  assert.equal(p1.x, 24);
  assert.equal(p2.x, 38);
  assert.ok(p0.x < p1.x && p1.x < p2.x, "spacing must be monotonic");
});

test("labelAnchor: the anchor lies on the segment's line", () => {
  const seg = [[0, 0], [100, 50]];
  const p = labelAnchor(seg, 3, 10);
  // cross product of (p - start) with the segment direction must vanish
  const cross = (p.x - 0) * (50 - 0) - (p.y - 0) * (100 - 0);
  assert.ok(Math.abs(cross) < 1e-9, `anchor off the line, cross=${cross}`);
});

test("labelAnchor: ux,uy is a unit vector pointing at the far endpoint", () => {
  const p = labelAnchor([[0, 0], [0, 100]], 0, 14);
  assert.ok(Math.abs(Math.hypot(p.ux, p.uy) - 1) < 1e-12);
  assert.ok(p.uy > 0, "must point towards the far endpoint");
});

test("labelAnchor: ties on x+y are resolved deterministically", () => {
  // Both endpoints have x+y == 100; the result must not depend on argument order.
  const a = labelAnchor([[0, 100], [100, 0]], 0, 14);
  const b = labelAnchor([[100, 0], [0, 100]], 0, 14);
  assert.deepEqual({ x: a.x, y: a.y }, { x: b.x, y: b.y });
});

test("labelAnchor: degenerate and non-finite segments return null", () => {
  assert.equal(labelAnchor([[5, 5], [5, 5]], 0, 14), null);
  assert.equal(labelAnchor([[0, 0], [NaN, 10]], 0, 14), null);
  assert.equal(labelAnchor(null, 0, 14), null);
});
