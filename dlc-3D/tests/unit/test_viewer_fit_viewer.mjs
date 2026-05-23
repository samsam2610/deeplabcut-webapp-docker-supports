import test from "node:test";
import assert from "node:assert/strict";
import { fitViewerSize } from "../../src/static/components/viewer/internal/fit_viewer.mjs";

test("100% zoom: width == baseW, no centering margin", () => {
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 1200, zoom: 100 }),
    { width: 800, marginLeft: 0 });
});

test("150% zoom within maxW: overflow centered by negative half-margin", () => {
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 2000, zoom: 150 }),
    { width: 1200, marginLeft: -200 });
});

test("zoom clamped by maxW (floored)", () => {
  // round(800*1.5)=1200 but maxW floor is 1000 → width 1000, extra 200 → margin -100
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 1000.9, zoom: 150 }),
    { width: 1000, marginLeft: -100 });
});

test("zoom below 100% never produces a positive margin", () => {
  assert.deepEqual(fitViewerSize({ baseW: 800, maxW: 2000, zoom: 50 }),
    { width: 400, marginLeft: 0 });
});
