import test from "node:test";
import assert from "node:assert/strict";
import {
  scaleFor, videoToCanvas, canvasToVideo, markerRadius,
  hitTest, resolvePose, setEdit, deleteEdit, frameEditsOf, editedFrameCount,
  nudge, nextBodypart, prefetchWindow, allCached, layerThreshold,
  poseCacheKey, buildMarkerEditPayload, parsePoseJson,
} from "../../src/static/components/viewer/internal/marker_overlay.mjs";

const HALF = { sx: 0.5, sy: 0.5 };

test("parsePoseJson tolerates non-finite literals (NaN/Infinity → null)", () => {
  // numpy-emitted bodies the browser's JSON.parse would otherwise reject
  const body = '{"poses":[{"bp":"a","x":NaN,"y":NaN,"lh":NaN},{"bp":"b","x":3.5,"y":Infinity,"lh":-Infinity}],"n_bodyparts":2}';
  const d = parsePoseJson(body);
  assert.equal(d.n_bodyparts, 2);
  assert.equal(d.poses[0].x, null);   // NaN → null
  assert.equal(d.poses[1].x, 3.5);    // real value preserved
  assert.equal(d.poses[1].y, null);   // Infinity → null
  assert.equal(d.poses[1].lh, null);  // -Infinity → null
  assert.deepEqual(parsePoseJson('{"poses":[],"n_bodyparts":1}'), { poses: [], n_bodyparts: 1 });
});

test("scale + coordinate transforms", () => {
  assert.deepEqual(scaleFor(800, 600, 400, 300), { sx: 0.5, sy: 0.5 });
  assert.deepEqual(scaleFor(0, 0, 400, 300), { sx: 400, sy: 300 }); // guards /0
  assert.deepEqual(videoToCanvas(100, 50, HALF), { cx: 50, cy: 25 });
  assert.deepEqual(canvasToVideo(50, 25, HALF), { x: 100, y: 50 });
  assert.equal(markerRadius(6, HALF), 3);
  assert.equal(markerRadius(1, { sx: 0.1, sy: 0.1 }), 1); // floor at 1
});

test("hitTest: nearest bp within radius (video coords scaled to canvas)", () => {
  const poses = [{ bp: "a", x: 100, y: 50 }, { bp: "b", x: 300, y: 300 }];
  assert.equal(hitTest(poses, 50, 25, HALF, 6), "a");   // on top of a
  assert.equal(hitTest(poses, 50, 200, HALF, 6), null); // far from both
});

test("hitTest: edits override position; deleted edits are skipped", () => {
  const poses = [{ bp: "a", x: 100, y: 50 }];
  const moved = { a: { x: 200, y: 100 } };
  assert.equal(hitTest(poses, 100, 50, HALF, 6, moved, 8), "a"); // hits moved location
  assert.equal(hitTest(poses, 50, 25, HALF, 6, moved, 8), null); // original spot now empty
  const deleted = { a: { x: null, y: null } };
  assert.equal(hitTest(poses, 50, 25, HALF, 6, deleted, 8), null);
  const halfNull = { a: { x: 50, y: null } };
  assert.equal(hitTest(poses, 50, 25, HALF, 6, halfNull, 8), null); // half-null = deleted
});

test("resolvePose merges an edit over a pose", () => {
  const pose = { bp: "a", x: 100, y: 50 };
  assert.deepEqual(resolvePose(pose, {}), { x: 100, y: 50, edited: false, deleted: false });
  assert.deepEqual(resolvePose(pose, { a: { x: 7, y: 8 } }), { x: 7, y: 8, edited: true, deleted: false });
  assert.deepEqual(resolvePose(pose, { a: { x: null, y: null } }), { x: null, y: null, edited: true, deleted: true });
});

test("setEdit / deleteEdit are immutable; frameEditsOf + editedFrameCount", () => {
  const e0 = {};
  const e1 = setEdit(e0, 5, "a", 10, 20);
  assert.deepEqual(e0, {});                                   // not mutated
  assert.deepEqual(e1, { 5: { a: { x: 10, y: 20 } } });
  const e2 = setEdit(e1, 5, "b", 1, 2);
  assert.deepEqual(e2[5], { a: { x: 10, y: 20 }, b: { x: 1, y: 2 } });
  const e3 = deleteEdit(e2, 5, "a");
  assert.deepEqual(e3[5].a, { x: null, y: null });
  assert.deepEqual(frameEditsOf(e3, 5), e3[5]);
  assert.deepEqual(frameEditsOf(e3, 99), {});
  assert.equal(editedFrameCount({ 5: {}, 7: {} }), 2);
  // existing bp entries are deep-copied, not shared across versions
  const s1 = setEdit({}, 5, "a", 1, 2);
  const s2 = setEdit(s1, 5, "c", 3, 4);
  assert.notEqual(s2[5].a, s1[5].a);
  assert.deepEqual(s1[5], { a: { x: 1, y: 2 } });
});

test("nudge: WASD ±1 / ±10, null for other keys", () => {
  const b = { x: 10, y: 20 };
  assert.deepEqual(nudge(b, "a", false), { x: 9, y: 20 });
  assert.deepEqual(nudge(b, "d", false), { x: 11, y: 20 });
  assert.deepEqual(nudge(b, "w", false), { x: 10, y: 19 });
  assert.deepEqual(nudge(b, "s", false), { x: 10, y: 21 });
  assert.deepEqual(nudge(b, "D", true), { x: 20, y: 20 });   // shift = 10, case-insensitive
  assert.equal(nudge(b, "x", false), null);
  assert.equal(nudge({ x: null, y: null }, "a", false), null); // deleted base → null
  assert.equal(nudge(null, "a", false), null);                 // absent base → null
});

test("nextBodypart cycles forward/backward and handles edges", () => {
  const l = ["a", "b", "c"];
  assert.equal(nextBodypart(l, "a"), "b");
  assert.equal(nextBodypart(l, "c"), "a");                   // wrap
  assert.equal(nextBodypart(l, "b", true), "a");
  assert.equal(nextBodypart(l, "a", true), "c");             // wrap backward
  assert.equal(nextBodypart(l, "missing"), "a");             // not found → first
  assert.equal(nextBodypart([], "a"), null);
});

test("prefetchWindow clamps to frameCount", () => {
  assert.deepEqual(prefetchWindow(10, 30, 100), { start: 10, count: 30 });
  assert.deepEqual(prefetchWindow(90, 30, 100), { start: 90, count: 10 });
  assert.deepEqual(prefetchWindow(100, 30, 100), { start: 100, count: 0 });
});

test("allCached: every frame in the window present with matching key", () => {
  const cache = new Map();
  for (let i = 10; i < 40; i++) cache.set(i, { key: "k", poses: [] });
  assert.equal(allCached(cache, 10, 30, 100, "k"), true);
  assert.equal(allCached(cache, 10, 30, 100, "other"), false); // key changed
  cache.delete(25);
  assert.equal(allCached(cache, 10, 30, 100, "k"), false);     // a gap
  assert.equal(allCached(new Map(), 100, 30, 100, "k"), true); // past end → vacuously cached
});

test("layerThreshold + poseCacheKey + payload", () => {
  assert.equal(layerThreshold({ threshold: 0.8 }, 0.6, true), 0.8);
  assert.equal(layerThreshold({ threshold: 0.8 }, 0.6, false), 0.6); // per-layer off
  assert.equal(layerThreshold({ threshold: null }, 0.6, true), 0.6); // null falls back
  assert.equal(poseCacheKey("/x.h5", 0.6), "/x.h5:0.60");
  assert.deepEqual(buildMarkerEditPayload("/x.h5", 5, "a", 10, 20),
    { h5: "/x.h5", frame: 5, bp: "a", x: 10, y: 20 });
  assert.deepEqual(buildMarkerEditPayload("/x.h5", 5, "a", null, null),
    { h5: "/x.h5", frame: 5, bp: "a", x: null, y: null });
});
