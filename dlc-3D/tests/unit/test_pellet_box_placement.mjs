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
  newVisibility,
  isVisible,
  setVisible,
  canPlace,
} from "../../src/static/internal/pellet_box.mjs";

// ── tile selection ──────────────────────────────────────────────────────────
//
// A player tile is identified by WHAT IT IS (class vv-overlay-canvas), not by
// "any canvas that is not one of these ids". The id-exclusion version shipped
// twice and broke twice: first because the overlays it created had no id, then
// because the card holds eight other canvases (seek bar, status strip, note
// strip, two coverage bars, three pose3d canvases) that all matched.

// Exactly the canvases present in card_inline_analysis_3d_sam.html.
const CARD_CANVASES = [
  { id: "ia3ds-seek-canvas", className: "" },
  { id: "ia3ds-status-canvas", className: "" },
  { id: "ia3ds-note-canvas", className: "" },
  { id: "ia3ds-finalize-coverage", className: "" },
  { id: "ia3ds-triangulate-coverage", className: "" },
  { id: "ia3ds-pose3d-cam0", className: "" },
  { id: "ia3ds-pose3d-cam1", className: "" },
  { id: "ia3ds-pose3d-canvas", className: "" },
  { id: "", className: "vv-overlay-canvas" },     // cam0 tile
  { id: "", className: "vv-overlay-canvas" },     // cam1 tile
  { id: "ia3ds-sam-strip", className: "" },
  { id: "ia3ds-sam-tags", className: "" },
];

test("only the two player tiles are selected from a full card", () => {
  const tiles = selectTiles(CARD_CANVASES);
  assert.equal(tiles.length, 2, "the card's other 10 canvases are not tiles");
  assert.ok(tiles.every((t) => t.className.includes("vv-overlay-canvas")));
});

test("the seek bar and coverage strips are not tiles", () => {
  // These come FIRST in document order, so an index-based camera mapping over
  // an unfiltered list put cam0's overlay on the seek bar.
  assert.equal(isTile({ id: "ia3ds-seek-canvas", className: "" }), false);
  assert.equal(isTile({ id: "ia3ds-finalize-coverage", className: "" }), false);
  assert.equal(isTile({ id: "ia3ds-pose3d-cam1", className: "" }), false);
});

test("tile order is preserved so index 0 is cam0", () => {
  const tiles = selectTiles(CARD_CANVASES);
  assert.equal(CARD_CANVASES.indexOf(tiles[0]) < CARD_CANVASES.indexOf(tiles[1]), true);
});

test("our own overlay canvases are never tiles", () => {
  assert.equal(isTile({ id: `${OVERLAY_PREFIX}cam0`, className: "ia3ds-overlay" }), false);
  assert.equal(isTile({ id: `${OVERLAY_PREFIX}cam1`, className: "ia3ds-overlay" }), false);
});

test("selecting tiles twice does not grow the set", () => {
  const canvases = CARD_CANVASES.slice();
  const first = selectTiles(canvases);
  assert.equal(first.length, 2);
  first.forEach((c, i) => canvases.push(
    { id: `${OVERLAY_PREFIX}cam${i}`, className: "ia3ds-overlay" }));
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

// ── per-camera visibility ───────────────────────────────────────────────────

test("visibility defaults to off for every camera", () => {
  const v = newVisibility();
  assert.equal(isVisible(v, "cam0"), false);
  assert.equal(isVisible(v, "cam1"), false);
});

test("cameras toggle independently", () => {
  let v = setVisible(newVisibility(), "cam0", true);
  assert.equal(isVisible(v, "cam0"), true);
  assert.equal(isVisible(v, "cam1"), false, "cam1 must not follow cam0");
  v = setVisible(v, "cam1", true);
  v = setVisible(v, "cam0", false);
  assert.equal(isVisible(v, "cam0"), false);
  assert.equal(isVisible(v, "cam1"), true);
});

test("visibility does not gate placement", () => {
  // Hiding a box must not make its camera unclickable -- that coupling was the
  // earlier "cannot place on cam1 after ticking show box" report.
  const v = newVisibility();
  assert.equal(canPlace(v, "cam1"), true);
  assert.equal(canPlace(setVisible(v, "cam1", true), "cam1"), true);
});
