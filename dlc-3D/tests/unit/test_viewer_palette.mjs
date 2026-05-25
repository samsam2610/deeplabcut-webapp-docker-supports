import test from "node:test";
import assert from "node:assert/strict";
import { hsvToRgb, paletteColor, FL_COLORS, labelerColor } from "../../src/static/components/viewer/internal/palette.mjs";

test("hsvToRgb black and pure red", () => {
  assert.equal(hsvToRgb(0, 0, 0), "rgb(0,0,0)");
  assert.equal(hsvToRgb(0, 1, 1), "rgb(255,0,0)");
});

test("hsvToRgb pure green and blue hues", () => {
  // h=1/3 → green sector, h=2/3 → blue sector, full sat/val
  assert.equal(hsvToRgb(1 / 3, 1, 1), "rgb(0,255,0)");
  assert.equal(hsvToRgb(2 / 3, 1, 1), "rgb(0,0,255)");
});

test("paletteColor uses 0.9 sat / 0.95 val and clamps total to >=1", () => {
  // idx 0 → hue 0 → r=v=0.95(242), g=b=v*(1-s)=0.095(24)
  assert.equal(paletteColor(0, 4), "rgb(242,24,24)");
  // total 0 must not divide by zero
  assert.equal(paletteColor(0, 0), "rgb(242,24,24)");
});

test("FL_COLORS is the 15-hex frame-labeler palette in order", () => {
  assert.deepEqual(FL_COLORS, [
    "#f87171", "#fb923c", "#fbbf24", "#a3e635", "#34d399",
    "#22d3ee", "#818cf8", "#e879f9", "#f43f5e", "#10b981",
    "#3b82f6", "#ec4899", "#f59e0b", "#84cc16", "#06b6d4",
  ]);
  assert.equal(FL_COLORS.length, 15);
});

test("labelerColor indexes FL_COLORS and cycles every 15", () => {
  assert.equal(labelerColor(0), "#f87171");
  assert.equal(labelerColor(4), "#34d399");
  assert.equal(labelerColor(14), "#06b6d4");
  assert.equal(labelerColor(15), "#f87171"); // wraps
  assert.equal(labelerColor(16), "#fb923c");
});

test("labelerColor is negative-safe (no undefined)", () => {
  assert.equal(labelerColor(-1), "#06b6d4");  // ((-1%15)+15)%15 = 14
  assert.equal(labelerColor(-15), "#f87171"); // wraps to 0
});
