import test from "node:test";
import assert from "node:assert/strict";
import { buildPairMap } from "../../src/static/pair_map.mjs";

test("empty input → empty pair map and cam set", () => {
  const out = buildPairMap([]);
  assert.equal(out.pairMap.size, 0);
  assert.deepEqual(out.camSet, []);
  assert.deepEqual(out.frameNumbers, []);
});

test("single cam, 5 frames", () => {
  const frames = [
    "img_cam0_0000_30281.png",
    "img_cam0_0001_30287.png",
    "img_cam0_0002_30331.png",
    "img_cam0_0003_30341.png",
    "img_cam0_0004_09074.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0]);
  assert.equal(out.pairMap.size, 5);
  assert.equal(out.pairMap.get(30281).length, 1);
  assert.equal(out.pairMap.get(30281)[0].cam, 0);
  assert.equal(out.pairMap.get(30281)[0].fname, "img_cam0_0000_30281.png");
  assert.deepEqual(out.frameNumbers, [9074, 30281, 30287, 30331, 30341]);
});

test("two cams equal counts, all matching frame numbers", () => {
  const frames = [
    "img_cam0_0000_100.png", "img_cam0_0001_200.png", "img_cam0_0002_300.png",
    "img_cam1_0000_100.png", "img_cam1_0001_200.png", "img_cam1_0002_300.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1]);
  assert.equal(out.pairMap.size, 3);
  for (const fnum of [100, 200, 300]) {
    assert.equal(out.pairMap.get(fnum).length, 2);
  }
});

test("two cams mismatched (3 cam0 + 2 cam1, 1 unmatched)", () => {
  const frames = [
    "img_cam0_0000_100.png", "img_cam0_0001_200.png", "img_cam0_0002_300.png",
    "img_cam1_0000_100.png", "img_cam1_0001_200.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1]);
  assert.equal(out.pairMap.size, 3);
  assert.equal(out.pairMap.get(100).length, 2);
  assert.equal(out.pairMap.get(200).length, 2);
  assert.equal(out.pairMap.get(300).length, 1);
  assert.equal(out.pairMap.get(300)[0].cam, 0);
});

test("three cams sparse", () => {
  const frames = [
    "img_cam0_0000_100.png", "img_cam0_0001_200.png",
    "img_cam1_0000_200.png",
    "img_cam2_0000_100.png", "img_cam2_0001_300.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1, 2]);
  assert.deepEqual(out.frameNumbers, [100, 200, 300]);
  assert.equal(out.pairMap.get(100).length, 2);
  assert.equal(out.pairMap.get(200).length, 2);
  assert.equal(out.pairMap.get(300).length, 1);
});

test("non-conforming filenames silently skipped", () => {
  const frames = [
    "img_cam0_0000_100.png",
    "img0001.png",
    "thumbs.db",
    "img_cam1_0000_100.png",
  ];
  const out = buildPairMap(frames);
  assert.deepEqual(out.camSet, [0, 1]);
  assert.equal(out.pairMap.size, 1);
  assert.equal(out.pairMap.get(100).length, 2);
});
