import test from "node:test";
import assert from "node:assert/strict";
import { hsvToRgb, paletteColor } from "../../src/static/components/viewer/internal/palette.mjs";

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
