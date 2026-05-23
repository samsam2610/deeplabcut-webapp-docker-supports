import test from "node:test";
import assert from "node:assert/strict";
import { planTiles } from "../../src/static/components/viewer/internal/tile_layout.mjs";

test("primary only → single main tile (cam 0)", () => {
  assert.deepEqual(planTiles({ primaryVideoRel: "a.avi", siblingVideoRel: null }),
    [{ cam: 0, videoRel: "a.avi", label: "main" }]);
});

test("primary + sibling → two tiles", () => {
  assert.deepEqual(planTiles({ primaryVideoRel: "a.avi", siblingVideoRel: "b.avi" }),
    [{ cam: 0, videoRel: "a.avi", label: "main" },
     { cam: 1, videoRel: "b.avi", label: "sibling" }]);
});

test("empty-string sibling is treated as no sibling", () => {
  assert.equal(planTiles({ primaryVideoRel: "a.avi", siblingVideoRel: "" }).length, 1);
});

test("custom labels are honored", () => {
  const tiles = planTiles({ primaryVideoRel: "a", siblingVideoRel: "b",
    primaryLabel: "cam0", siblingLabel: "cam1" });
  assert.equal(tiles[0].label, "cam0");
  assert.equal(tiles[1].label, "cam1");
});
