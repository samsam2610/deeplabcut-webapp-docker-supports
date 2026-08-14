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
  toImage,
  toCanvas,
  scaleFor,
  clearBox,
  camCardHead,
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

// ── click → image coordinates ───────────────────────────────────────────────
//
// Reported 2026-08-12: frame 27591 had no pellet but was armed. Investigating
// it showed the stored box was ~12% up-and-left of where the user clicked —
// every stored mark was a uniform 0.88 x the true image coordinate, on both
// cameras and both axes.
//
// Cause: the code scaled the click by `canvas.width / rect.width`, assuming the
// backing store is the video's native size. VideoViewer sizes the tile's
// backing store to the DISPLAYED size, so that ratio is 1 and the click was
// stored in display pixels.
//
// The draw path had the mirrored error, so the box was painted at the stored
// (display) coordinate and appeared exactly under the cursor. Self-consistent
// on screen, wrong in the file — which is why it survived visual checking, and
// why these tests convert BOTH directions.

test("a click maps to image pixels, not display pixels", () => {
  // 800x600 video shown at 706x530 — the case that shipped.
  const rect = { left: 0, top: 0, width: 706, height: 530 };
  const natural = { width: 800, height: 600 };
  const p = toImage({ clientX: 326, clientY: 300 }, rect, natural);
  assert.equal(Math.round(p.x), 369);
  assert.equal(Math.round(p.y), 340);
});

test("the tile's offset is subtracted before scaling", () => {
  const rect = { left: 100, top: 50, width: 800, height: 600 };
  const p = toImage({ clientX: 500, clientY: 350 }, rect, { width: 800, height: 600 });
  assert.deepEqual([p.x, p.y], [400, 300]);
});

// Scaling is a float division, so compare within a pixel-thousandth rather
// than exactly: 388/600*600 is 387.99999999999994.
const near = (got, want, what) =>
  assert.ok(Math.abs(got - want) < 1e-6, `${what}: ${got} != ${want}`);

test("a 1:1 tile is unchanged", () => {
  const rect = { left: 0, top: 0, width: 800, height: 600 };
  const p = toImage({ clientX: 416, clientY: 388 }, rect, { width: 800, height: 600 });
  near(p.x, 416, "x"); near(p.y, 388, "y");
});

test("an enlarged tile scales down", () => {
  const rect = { left: 0, top: 0, width: 1600, height: 1200 };
  const p = toImage({ clientX: 832, clientY: 776 }, rect, { width: 800, height: 600 });
  near(p.x, 416, "x"); near(p.y, 388, "y");
});

test("a zero-sized tile does not divide by zero", () => {
  // Happens while the card is hidden: getBoundingClientRect() is all zeros.
  const p = toImage({ clientX: 10, clientY: 10 },
                    { left: 0, top: 0, width: 0, height: 0 },
                    { width: 800, height: 600 });
  assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
});

test("an unknown natural size falls back to the tile's own pixels", () => {
  // Better than inventing a scale: the mark is then wrong by the zoom only,
  // not by an arbitrary factor.
  const p = toImage({ clientX: 300, clientY: 200 },
                    { left: 0, top: 0, width: 706, height: 530 }, null);
  assert.deepEqual([p.x, p.y], [300, 200]);
});

// ── image → canvas, for drawing ─────────────────────────────────────────────

test("drawing scales image coordinates onto the displayed canvas", () => {
  const s = toCanvas({ x: 416, y: 388 }, { width: 800, height: 600 },
                     { width: 706, height: 530 });
  assert.equal(Math.round(s.x), 367);
  assert.equal(Math.round(s.y), 343);
});

test("a round trip through both conversions is the identity", () => {
  // The property that actually matters: what is drawn sits where the user
  // clicked AND what is stored is the true image coordinate.
  const rect = { left: 37, top: 11, width: 706, height: 530 };
  const natural = { width: 800, height: 600 };
  const click = { clientX: 400, clientY: 300 };
  const img = toImage(click, rect, natural);
  const back = toCanvas(img, natural, { width: rect.width, height: rect.height });
  assert.ok(Math.abs(back.x - (click.clientX - rect.left)) < 1e-9);
  assert.ok(Math.abs(back.y - (click.clientY - rect.top)) < 1e-9);
});

test("lengths scale too, so the box is the right SIZE on screen", () => {
  // half=22 in image pixels must not be drawn as 22 display pixels on a
  // shrunken tile, or the drawn box misrepresents what is swept.
  const s = scaleFor({ width: 800, height: 600 }, { width: 400, height: 300 });
  assert.equal(s.sx, 0.5);
  assert.equal(s.sy, 0.5);
});

test("scaleFor is 1 when the natural size is unknown", () => {
  assert.deepEqual(scaleFor(null, { width: 400, height: 300 }), { sx: 1, sy: 1 });
});

// ── re-placing a box ────────────────────────────────────────────────────────
//
// Reported: on cam0 "reclicks placed dots". That is the designed rule — the
// first click on a camera sets its box, every later one adds a pellet label —
// but it left NO way to move a box once placed. The box aims the search area,
// so a badly placed one has to be correctable without clearing the pellet pool
// that has been built up around it.

test("clearing a camera's box lets the next click re-place it", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = clearBox(s, "cam0");
  assert.equal(s.marks.filter((m) => m.kind === "box").length, 0);
  s = placeClick(s, { cam: "cam0", frame: 200, x: 415, y: 395 });
  const box = s.marks.find((m) => m.kind === "box");
  assert.deepEqual([box.x, box.y], [415, 395]);
});

test("clearing a box keeps the pellet labels", () => {
  // Those are the template pool. Losing them to a box correction would throw
  // away every click the user has made to teach the detector.
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = placeClick(s, { cam: "cam0", frame: 200, x: 411, y: 391 });
  s = clearBox(s, "cam0");
  assert.equal(s.marks.filter((m) => m.kind === "pellet").length, 2);
});

test("clearing one camera's box leaves the other's alone", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 1, x: 410, y: 390 });
  s = placeClick(s, { cam: "cam1", frame: 1, x: 590, y: 450 });
  s = clearBox(s, "cam0");
  const boxes = s.marks.filter((m) => m.kind === "box");
  assert.deepEqual(boxes.map((b) => b.cam), ["cam1"]);
});

test("clearing a box nobody placed is a no-op", () => {
  assert.deepEqual(clearBox(EMPTY, "cam0").marks, []);
});

test("clearing forgets the last placement, so WASD cannot move a ghost", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 1, x: 410, y: 390 });
  s = clearBox(s, "cam0");
  const after = nudge(s, "d", 1);
  assert.deepEqual(after.marks.filter((m) => m.kind === "box"), []);
});

// ── a box must not destroy a pellet label ───────────────────────────────────
//
// Reported: "placed pellet -> placing box replaces it". Placing a box wrote a
// pellet at the same point, and pellets are unique per (frame, camera), so the
// deliberate label was overwritten by a side effect of positioning a rectangle.
//
// The two are not the same claim. A pellet label says "the pellet is HERE, in
// this frame" and feeds the template pool. A box says "search around here",
// once per camera. On a frame with no label the first click can reasonably mean
// both. On a frame that already has one, it must not.

test("placing a box leaves an existing pellet on that frame alone", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = clearBox(s, "cam0");                       // now re-place the box
  s = placeClick(s, { cam: "cam0", frame: 100, x: 300, y: 300 });
  const box = s.marks.find((m) => m.kind === "box");
  const pellet = s.marks.find((m) => m.kind === "pellet" && m.frame === 100);
  assert.deepEqual([box.x, box.y], [300, 300], "the box moves");
  assert.deepEqual([pellet.x, pellet.y], [410, 390], "the label does not");
});

test("the first click on a bare frame still means both", () => {
  const s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  assert.deepEqual(s.marks.map((m) => m.kind).sort(), ["box", "pellet"]);
});

test("a pellet click still corrects the pellet on that frame", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = placeClick(s, { cam: "cam0", frame: 100, x: 415, y: 395 });
  const pellets = s.marks.filter((m) => m.kind === "pellet" && m.frame === 100);
  assert.equal(pellets.length, 1);
  assert.deepEqual([pellets[0].x, pellets[0].y], [415, 395]);
});

test("re-placing a box does not move the pellet with WASD afterwards", () => {
  let s = placeClick(EMPTY, { cam: "cam0", frame: 100, x: 410, y: 390 });
  s = clearBox(s, "cam0");
  s = placeClick(s, { cam: "cam0", frame: 100, x: 300, y: 300 });
  s = nudge(s, "d", 1);
  const pellet = s.marks.find((m) => m.kind === "pellet");
  const box = s.marks.find((m) => m.kind === "box");
  assert.deepEqual([pellet.x, pellet.y], [410, 390], "only the box was placed");
  assert.deepEqual([box.x, box.y], [301, 300]);
});

// ── camera card header ──────────────────────────────────────────────────────
//
// The header was built by string concatenation inside a 5000-line DOM-bound
// function, which is why the control it carries had no test. The clear button
// must name ITS OWN camera: the old single button read the camera from a
// dropdown, so a mis-wired per-camera button would clear the other camera's box
// and look like it worked.

test("the header carries a clear button for its own camera", () => {
  const html = camCardHead("cam1", { n_samples: 3, has_template: false }, false);
  assert.match(html, /data-clearcam="cam1"/);
  assert.equal(html.includes('data-clearcam="cam0"'), false);
});

test("each camera gets a show-box checkbox for its own camera", () => {
  const html = camCardHead("cam0", { n_samples: 0, has_template: false }, false);
  assert.match(html, /data-showcam="cam0"/);
});

test("show box reflects the visibility it was given", () => {
  const on = camCardHead("cam0", { n_samples: 0, has_template: false }, true);
  const off = camCardHead("cam0", { n_samples: 0, has_template: false }, false);
  assert.match(on, /data-showcam="cam0"[^>]*checked/);
  assert.equal(/data-showcam="cam0"[^>]*checked/.test(off), false);
});

test("the sample count is shown", () => {
  assert.match(camCardHead("cam0", { n_samples: 12 }, false), /12 samples/);
});

test("a camera with no template gets no <img>", () => {
  assert.equal(camCardHead("cam0", { has_template: false }, false).includes("<img"),
               false);
});
