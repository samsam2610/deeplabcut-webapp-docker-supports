// Drag-to-reorder for a card's panel stack, saved per project.
//
// Two rules the implementation must keep:
//
//   1. Panels are MOVED (insertBefore relocates the same node), never
//      re-rendered. Each one holds canvases with live 2D contexts and handlers
//      wired at injection time; rebuilding the markup would leave a panel that
//      looks right and does nothing.
//   2. Only the ids passed in are movable, and they only ever occupy the
//      positions they already hold — the viewer above them, and the
//      reprojection panel below them in that card, must not be walked over.
import { applyOrder, reorder, sameOrder, dropTarget } from "./panel_order.mjs";

const ENDPOINT = "/dlc-3d/card-layout";
const DRAGGING = "ia3d-panel-dragging";
const BEFORE = "ia3d-panel-drop-before";
const AFTER = "ia3d-panel-drop-after";

/** The movable panels, in the order they currently sit in. */
export function domOrder(container, ids) {
  const wanted = new Set(ids || []);
  return Array.from(container.children)
    .filter((el) => wanted.has(el.id))
    .map((el) => el.id);
}

/** Rearrange the panels to `order`, moving the existing elements. */
export function applyToDom(container, ids, order) {
  const here = domOrder(container, ids);
  if (!here.length) return;
  const last = document.getElementById(here[here.length - 1]);
  // Anchor on whatever follows the block. Inserting each panel before that
  // anchor, in sequence, both preserves the block's position in the section and
  // leaves the panels in exactly `order`.
  const tail = last ? last.nextSibling : null;
  (order || []).forEach((id) => {
    const el = document.getElementById(id);
    if (el && el.parentElement === container) container.insertBefore(el, tail);
  });
}

let _layout = null;

async function loadLayout() {
  if (_layout) return _layout;
  _layout = (async () => {
    try {
      const r = await fetch(ENDPOINT);
      if (!r.ok) return {};
      return (await r.json()).layout || {};
    } catch {
      return {};                 // the shipped order is always a valid answer
    }
  })();
  return _layout;
}

const _timers = {};

function saveOrder(card, order) {
  clearTimeout(_timers[card]);
  _timers[card] = setTimeout(() => {
    fetch(ENDPOINT, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card, order }),
    }).catch(() => {});          // a failed save must not disturb the page
  }, 400);
}

function clearMarkers(container) {
  container.querySelectorAll(`.${BEFORE}, .${AFTER}`).forEach((el) => {
    el.classList.remove(BEFORE, AFTER);
  });
}

function wirePanel(container, panel, card, ids) {
  // Every one of these panels opens with its toggle row — a <div> for five of
  // them, a bare <label> for Create Clip. Both are the right grab target.
  const head = panel.firstElementChild;
  if (!head || head.dataset.panelDrag === "1") return;
  head.dataset.panelDrag = "1";
  head.classList.add("ia3d-panel-grab");

  head.addEventListener("mousedown", (ev) => {
    // Never arm a drag from the checkbox itself: the drag would swallow the
    // click that opens the panel, and ticking a box is the commoner action.
    panel.draggable = ev.target.tagName !== "INPUT";
    // Disarm on release. Left armed after a click that never became a drag, the
    // WHOLE panel stays draggable — and then a drag inside a number input or
    // across the viewer would pick the panel up instead.
    const off = () => {
      panel.draggable = false;
      document.removeEventListener("mouseup", off);
    };
    document.addEventListener("mouseup", off);
  });
  panel.addEventListener("dragstart", (ev) => {
    ev.dataTransfer.setData("text/plain", panel.id);
    ev.dataTransfer.effectAllowed = "move";
    panel.classList.add(DRAGGING);
  });
  panel.addEventListener("dragend", () => {
    panel.draggable = false;
    panel.classList.remove(DRAGGING);
    clearMarkers(container);
  });
  panel.addEventListener("dragover", (ev) => {
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "move";
    const rect = panel.getBoundingClientRect();
    const low = ev.clientY - rect.top > rect.height / 2;
    panel.classList.toggle(AFTER, low);
    panel.classList.toggle(BEFORE, !low);
  });
  panel.addEventListener("dragleave", () => panel.classList.remove(BEFORE, AFTER));
  panel.addEventListener("drop", (ev) => {
    ev.preventDefault();
    // Recomputed from the event geometry, exactly as `dragover` does — never
    // read off the CSS marker classes. Per the HTML drag-and-drop processing
    // model, an iteration where the immediate user selection changes fires
    // dragenter/dragleave and NOT dragover, and `dragleave` here is
    // unfiltered, so a bubbled dragleave from any child can clear both marker
    // classes right before drop fires. Trusting the class would then insert
    // the panel above the target instead of below.
    const rect = panel.getBoundingClientRect();
    const low = ev.clientY - rect.top > rect.height / 2;
    clearMarkers(container);
    const moved = ev.dataTransfer.getData("text/plain");
    if (!moved || moved === panel.id) return;
    const here = domOrder(container, ids);
    const target = dropTarget(here, moved, panel.id, low);
    // dropTarget returns undefined for a no-op — the panel would land exactly
    // where it already sits.
    if (target === undefined) return;
    const next = reorder(here, moved, target);
    applyToDom(container, ids, next);
    saveOrder(card, next);
  });
}

/**
 * Make a card's panel stack reorderable. Idempotent; returns false when the
 * card's markup is not in the document yet (two of the three cards inject
 * themselves at runtime).
 */
export function initPanelLayout({ card, containerId, ids }) {
  const container = document.getElementById(containerId);
  if (!container) return false;
  if (container.dataset.panelLayout === "1") return true;
  container.dataset.panelLayout = "1";

  const present = domOrder(container, ids);
  present.forEach((id) => {
    const el = document.getElementById(id);
    if (el) wirePanel(container, el, card, ids);
  });

  loadLayout().then((layout) => {
    const wanted = applyOrder(present, (layout || {})[card] || []);
    if (!sameOrder(wanted, domOrder(container, ids))) {
      applyToDom(container, ids, wanted);
    }
  });
  return true;
}
