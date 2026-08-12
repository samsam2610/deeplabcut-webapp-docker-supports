// Executable model of the SAM card's pellet-box placement rules.
//
// The real functions live inside inline_analysis_3d_sam.js's DOM-bound module
// and cannot be imported, so this mirrors their logic exactly — the same
// approach as test_auto_advance.mjs and the other 32 unit tests here.
//
// Why these exist (2026-08-11): the first attempt at box placement used dragging
// and shipped three bugs, none of which had a test. The worst was that
// _pelletTiles() excluded exactly two canvases BY ID, while the overlay canvases
// it created had no id — so every poll gave each overlay its own overlay and the
// frame filled with dozens of stacked boxes. That is a two-line DOM invariant.
import test from "node:test";
import assert from "node:assert/strict";

import {
  isTile,
  selectTiles,
  placeClick,
  nudge,
  centreFor,
  OVERLAY_PREFIX,
} from "../../src/static/internal/pellet_box.mjs";

// ── tile selection: overlays are not tiles ──────────────────────────────────

test("an overlay canvas is never treated as a tile", () => {
  assert.equal(isTile({ id: `${OVERLAY_PREFIX}cam0` }), false);
  assert.equal(isTile({ id: `${OVERLAY_PREFIX}cam1` }), false);
});

test("the strip and tag canvases are not tiles", () => {
  assert.equal(isTile({ id: "ia3ds-sam-strip" }), false);
  assert.equal(isTile({ id: "ia3ds-sam-tags" }), false);
});

test("a player tile is a tile", () => {
  assert.equal(isTile({ id: "" }), true);
  assert.equal(isTile({ id: "vv-tile-0" }), true);
});

test("selecting tiles twice does not grow the set", () => {
  // THE exponential bug: pass 1 creates overlays, pass 2 must not see them as
  // tiles and give each one an overlay of its own.
  const canvases = [{ id: "" }, { id: "" }];
  const first = selectTiles(canvases);
  assert.equal(first.length, 2);
  first.forEach((c, i) => canvases.push({ id: `${OVERLAY_PREFIX}cam${i}` }));
  const second = selectTiles(canvases);
  assert.equal(second.length, 2, "overlays must not be counted as tiles");
  assert.deepEqual(second, first);
});

// ── click semantics ─────────────────────────────────────────────────────────

const EMPTY = { marks: [] };

test("the first click on a camera places a box AND a pellet", () => {
  const out = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  const kinds = out.marks.map((m) => m.kind).sort();
  assert.deepEqual(kinds, ["box", "pellet"]);
  assert.equal(out.last.kind, "box");
});

test("a later click on the same camera places only a pellet", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = placeClick(s, { cam: "cam0", frame: 250, x: 412, y: 391 });
  assert.equal(s.marks.filter((m) => m.kind === "box").length, 1);
  assert.equal(s.marks.filter((m) => m.kind === "pellet").length, 2);
  assert.equal(s.last.kind, "pellet");
});

test("each camera gets its own box", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = placeClick(s, { cam: "cam1", frame: 100, x: 590, y: 450 });
  const boxes = s.marks.filter((m) => m.kind === "box");
  assert.deepEqual(boxes.map((b) => b.cam).sort(), ["cam0", "cam1"]);
});

test("clicking the same frame and camera twice corrects rather than duplicates", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = placeClick(s, { cam: "cam0", frame: 100, x: 415, y: 395 });
  const pellets = s.marks.filter((m) => m.kind === "pellet" && m.frame === 100);
  assert.equal(pellets.length, 1, "a second click on one frame is a correction");
  assert.deepEqual([pellets[0].x, pellets[0].y], [415, 395]);
});

// ── WASD ────────────────────────────────────────────────────────────────────

test("WASD moves the mark that was just placed", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = placeClick(s, { cam: "cam0", frame: 250, x: 500, y: 300 });
  s = nudge(s, "d", 1);
  const moved = s.marks.find((m) => m.kind === "pellet" && m.frame === 250);
  const untouched = s.marks.find((m) => m.kind === "pellet" && m.frame === 100);
  assert.deepEqual([moved.x, moved.y], [501, 300]);
  assert.deepEqual([untouched.x, untouched.y], [410, 390]);
});

test("a first click moves its box and pellet together", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = nudge(s, "s", 1);
  const box = s.marks.find((m) => m.kind === "box");
  const pellet = s.marks.find((m) => m.kind === "pellet");
  assert.deepEqual([box.x, box.y], [410, 391]);
  assert.deepEqual([pellet.x, pellet.y], [410, 391]);
});

test("all four directions", () => {
  const start = placeClick(EMPTY, { cam: "cam0", frame: 1, x: 400, y: 300 });
  const at = (k, step) => {
    const m = nudge(start, k, step).marks.find((x) => x.kind === "box");
    return [m.x, m.y];
  };
  assert.deepEqual(at("w", 1), [400, 299]);
  assert.deepEqual(at("s", 1), [400, 301]);
  assert.deepEqual(at("a", 1), [399, 300]);
  assert.deepEqual(at("d", 1), [401, 300]);
});

test("shift takes a bigger step", () => {
  const s = nudge(placeClick(EMPTY, { cam: "cam0", frame: 1, x: 400, y: 300 }), "d", 10);
  assert.equal(s.marks.find((m) => m.kind === "box").x, 410);
});

test("nudging with nothing placed is a no-op", () => {
  const s = nudge(EMPTY, "d", 1);
  assert.deepEqual(s.marks, []);
});

test("nudges clamp to the frame", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 1, x: 1, y: 1 });
  s = nudge(s, "a", 10, { width: 800, height: 600 });
  s = nudge(s, "w", 10, { width: 800, height: 600 });
  const box = s.marks.find((m) => m.kind === "box");
  assert.deepEqual([box.x, box.y], [0, 0]);

  let t = placeClick(EMPTY, { cam: "cam1", frame: 1, x: 799, y: 599 });
  t = nudge(t, "d", 10, { width: 800, height: 600 });
  t = nudge(t, "s", 10, { width: 800, height: 600 });
  const b2 = t.marks.find((m) => m.kind === "box");
  assert.deepEqual([b2.x, b2.y], [799, 599]);
});

// ── centre derivation ───────────────────────────────────────────────────────

test("the centre comes from the box mark when one exists", () => {
  const s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 411, y: 402 });
  assert.deepEqual(centreFor(s, "cam0", { cx: 416, cy: 388 }), { cx: 411, cy: 402 });
});

test("the centre falls back to the project default when unplaced", () => {
  assert.deepEqual(centreFor(EMPTY, "cam0", { cx: 416, cy: 388 }), { cx: 416, cy: 388 });
});

test("no box and no default means unplaced, not a guess at (0,0)", () => {
  assert.equal(centreFor(EMPTY, "cam0", null), null);
});

test("one camera's box does not supply the other's centre", () => {
  const s = placeClick(EMPTY, { cam: "cam0", frame: 1, x: 411, y: 402 });
  assert.deepEqual(centreFor(s, "cam1", { cx: 593, cy: 450 }), { cx: 593, cy: 450 });
});
