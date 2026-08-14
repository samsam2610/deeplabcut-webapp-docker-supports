// Drag-to-reorder, at the DOM level.
//
// The property this file exists to pin is IDENTITY. Panels hold canvases with
// live 2D contexts, listeners wired at injection time, and a VideoViewer. An
// implementation that re-rendered the markup would look right in a screenshot
// and be dead to the touch, and no assertion about ORDER would catch it.
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

import { domOrder, applyToDom, initPanelLayout } from
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

/** Same fixture, but also globalThis.window (for the blur listener) and a
 *  fetch stub (loadLayout's GET), so initPanelLayout can wire real handlers. */
function buildWired() {
  const dom = build();
  globalThis.window = dom.window;
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ layout: {} }) });
  const sect = dom.window.document.getElementById("sect");
  initPanelLayout({ card: "test", containerId: "sect", ids: IDS });
  return { dom, sect };
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

// ── mousedown arm / disarm ───────────────────────────────────────────────────

test("mousedown arms the panel for drag", () => {
  const { dom } = buildWired();
  const { window } = dom;
  const p1 = window.document.getElementById("p1");
  const head = p1.firstElementChild;
  head.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
  assert.equal(p1.draggable, true);
});

test("releasing the mouse over the window disarms the panel (the common case)", () => {
  const { dom } = buildWired();
  const { window } = dom;
  const p1 = window.document.getElementById("p1");
  const head = p1.firstElementChild;
  head.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
  assert.equal(p1.draggable, true);
  window.document.dispatchEvent(new window.MouseEvent("mouseup", { bubbles: true }));
  assert.equal(p1.draggable, false);
});

test("a window blur (release outside the window) also disarms the panel", () => {
  // This is the case Fix 5(a) exists for: no mouseup ever reaches `document`
  // when the button is released outside the browser window, so without the
  // blur fallback `panel.draggable` would stay true forever.
  const { dom } = buildWired();
  const { window } = dom;
  const p1 = window.document.getElementById("p1");
  const head = p1.firstElementChild;
  head.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
  assert.equal(p1.draggable, true, "armed by mousedown");
  window.dispatchEvent(new window.Event("blur"));
  assert.equal(p1.draggable, false, "disarmed by blur even though mouseup never fired");
});

test("blur firing does not leave a stale mouseup listener behind", () => {
  // Whichever of mouseup/blur fires first must remove both registrations.
  // Provoke it twice on the same panel: if `off` only unregistered itself
  // from one of the two events, the second round would double-fire and this
  // would throw or leave draggable in a surprising state.
  const { dom } = buildWired();
  const { window } = dom;
  const p1 = window.document.getElementById("p1");
  const head = p1.firstElementChild;

  head.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
  window.dispatchEvent(new window.Event("blur"));
  assert.equal(p1.draggable, false);

  head.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
  assert.equal(p1.draggable, true);
  window.document.dispatchEvent(new window.MouseEvent("mouseup", { bubbles: true }));
  assert.equal(p1.draggable, false);
});

// ── dragstart target filter ──────────────────────────────────────────────────

function fakeDataTransfer() {
  const calls = [];
  return { calls, setData: (...a) => calls.push(a), effectAllowed: null };
}

test("dragstart from the panel itself arms the real drag", () => {
  const { dom } = buildWired();
  const { window } = dom;
  const p1 = window.document.getElementById("p1");
  const ev = new window.Event("dragstart", { bubbles: true, cancelable: true });
  const dt = fakeDataTransfer();
  Object.defineProperty(ev, "dataTransfer", { value: dt });
  p1.dispatchEvent(ev);
  assert.equal(dt.calls.length, 1, "setData was called");
  assert.ok(p1.classList.contains("ia3d-panel-dragging"));
});

test("dragstart bubbling up from a child (e.g. a text selection) is ignored", () => {
  // Fix 5(b): dragstart bubbles, and a text selection dragged inside the panel
  // fires one with ev.target set to the inner element, not the panel. Left
  // unfiltered this would overwrite the drop payload with the panel's id and
  // reorder the stack as a side effect of selecting text.
  const { dom } = buildWired();
  const { window } = dom;
  const p1 = window.document.getElementById("p1");
  const head = p1.firstElementChild;
  const ev = new window.Event("dragstart", { bubbles: true, cancelable: true });
  const dt = fakeDataTransfer();
  Object.defineProperty(ev, "dataTransfer", { value: dt });
  head.dispatchEvent(ev);                 // target = head, currentTarget = p1
  assert.equal(dt.calls.length, 0, "setData must not be called for a bubbled dragstart");
  assert.ok(!p1.classList.contains("ia3d-panel-dragging"));
});
