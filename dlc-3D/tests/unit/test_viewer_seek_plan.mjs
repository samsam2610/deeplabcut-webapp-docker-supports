import test from "node:test";
import assert from "node:assert/strict";
import { planSeek } from "../../src/static/components/viewer/internal/seek_plan.mjs";

const TILES = [
  { cam: 0, videoRel: "a.avi" },
  { cam: 1, videoRel: "b.avi" },
];

test("clamps n into [0, frameCount-1] and loads both tiles at that frame", () => {
  assert.deepEqual(planSeek({ n: 5, frameCount: 100, tiles: TILES }), {
    frame: 5,
    loads: [{ cam: 0, videoRel: "a.avi", frame: 5 },
            { cam: 1, videoRel: "b.avi", frame: 5 }],
  });
  assert.equal(planSeek({ n: -10, frameCount: 100, tiles: TILES }).frame, 0);
  assert.equal(planSeek({ n: 999, frameCount: 100, tiles: TILES }).frame, 99);
});

test("frameCount 0 clamps to frame 0", () => {
  assert.equal(planSeek({ n: 3, frameCount: 0, tiles: TILES }).frame, 0);
});

test("sibling tile is skipped in frames mode", () => {
  const plan = planSeek({ n: 2, frameCount: 100, tiles: TILES, framesMode: true });
  assert.deepEqual(plan.loads, [{ cam: 0, videoRel: "a.avi", frame: 2 }]);
});

test("tiles without a videoRel are skipped", () => {
  const plan = planSeek({ n: 2, frameCount: 100,
    tiles: [{ cam: 0, videoRel: "a.avi" }, { cam: 1, videoRel: null }] });
  assert.equal(plan.loads.length, 1);
  assert.equal(plan.loads[0].cam, 0);
});
