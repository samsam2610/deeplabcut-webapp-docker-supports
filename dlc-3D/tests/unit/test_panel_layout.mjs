// Drag-to-reorder, at the DOM level.
//
// The property this file exists to pin is IDENTITY. Panels hold canvases with
// live 2D contexts, listeners wired at injection time, and a VideoViewer. An
// implementation that re-rendered the markup would look right in a screenshot
// and be dead to the touch, and no assertion about ORDER would catch it.
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

import { domOrder, applyToDom } from
  "../../src/static/internal/panel_layout.mjs";

function build() {
  const dom = new JSDOM(`<!doctype html><body>
    <div id="sect">
      <div id="viewer">the video, which must never move</div>
      <div id="p1"><div>head 1</div></div>
      <div id="p2"><div>head 2</div></div>
      <div id="p3"><div>head 3</div></div>
      <div id="tail">not a movable panel</div>
    </div></body>`);
  globalThis.document = dom.window.document;
  return dom;
}

const IDS = ["p1", "p2", "p3"];

test("domOrder reports the panels in DOM order, ignoring everything else", () => {
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  assert.deepEqual(domOrder(sect, IDS), ["p1", "p2", "p3"]);
});

test("applyToDom puts the panels in the given order", () => {
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  applyToDom(sect, IDS, ["p3", "p1", "p2"]);
  assert.deepEqual(domOrder(sect, IDS), ["p3", "p1", "p2"]);
});

test("the panels are MOVED, not rebuilt", () => {
  // Identity, not markup: same node object, and anything attached to it lives.
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  const p1 = dom.window.document.getElementById("p1");
  p1.dataset.live = "yes";
  applyToDom(sect, IDS, ["p3", "p2", "p1"]);
  assert.equal(dom.window.document.getElementById("p1"), p1);
  assert.equal(dom.window.document.getElementById("p1").dataset.live, "yes");
});

test("nothing outside the movable set is disturbed", () => {
  // The viewer sits above the panels and the reprojection card has a panel
  // BELOW them. Reordering must not walk over either.
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  applyToDom(sect, IDS, ["p3", "p2", "p1"]);
  const ids = Array.from(sect.children).map((el) => el.id);
  assert.equal(ids[0], "viewer");
  assert.equal(ids[ids.length - 1], "tail");
});

test("an order naming a panel that is not there is survivable", () => {
  const dom = build();
  const sect = dom.window.document.getElementById("sect");
  applyToDom(sect, IDS, ["gone", "p2", "p1", "p3"]);
  assert.deepEqual(domOrder(sect, IDS), ["p2", "p1", "p3"]);
});
