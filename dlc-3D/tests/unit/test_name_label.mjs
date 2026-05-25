import test from "node:test";
import assert from "node:assert/strict";
import { NAME_LABEL_FONT, nameLabelBox } from "../../src/static/components/viewer/internal/name_label.mjs";

test("NAME_LABEL_FONT matches the frame-labeler font", () => {
  assert.equal(NAME_LABEL_FONT, "bold 11px 'JetBrains Mono', monospace");
});

test("nameLabelBox positions the box at cx+r+2 / cy-7 with measured width+6 x 14", () => {
  // cx=100, cy=50, r=6, textWidth=30
  const b = nameLabelBox(100, 50, 6, 30);
  assert.equal(b.boxX, 108);  // cx + r + 2
  assert.equal(b.boxY, 43);   // cy - 7
  assert.equal(b.boxW, 36);   // textWidth + 6
  assert.equal(b.boxH, 14);
  assert.equal(b.textX, 111); // cx + r + 5
  assert.equal(b.textY, 54);  // cy + 4
  assert.equal(b.font, "bold 11px 'JetBrains Mono', monospace");
});

test("nameLabelBox tracks radius (bigger r pushes the box right)", () => {
  const b = nameLabelBox(0, 0, 12, 10);
  assert.equal(b.boxX, 14);   // 0 + 12 + 2
  assert.equal(b.textX, 17);  // 0 + 12 + 5
});
