// Does frame_labeler_3d.js actually LOAD?
//
// Three production outages in this file had the same shape: the module parses
// fine, `node --check` is happy, every source-text assertion passes — and then
// it throws on load in the browser, aborting its initFl3d IIFE. The folder
// dropdown still renders (server-side), so the symptom is "pick a folder, get
// no frame", which reads like a data problem rather than a dead module.
//
//   a21d80a  `let _fl3dEpiFrozen` declared ~500 lines after the init-time gate
//            call that read it -> ReferenceError (temporal dead zone)
//   aa95b26  the same failure, reintroduced by the per-tile refactor, in the
//            same commit that deleted the guard test protecting against it
//
// Nothing in the suite ever executed the module, so nothing caught them. This
// does: it builds the card's DOM under jsdom, imports the real file, and fails
// if loading throws. Source assertions cannot replace it — a TDZ error is a
// runtime event, invisible to any amount of reading.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "..", "src");
const TARGET = path.join(SRC, "static", "frame_labeler_3d.js");
const CARD = path.join(SRC, "templates", "partials", "card_frame_labeler.html");

// The module imports /static/js/training.js by absolute URL — resolvable only
// by a browser. Rewrite that single import to a local stub, and write the copy
// beside the original so every RELATIVE import still resolves normally.
const STUB = "../../tests/fixtures/training_stub.mjs";
const TMP = path.join(SRC, "static", ".frame_labeler_3d.smoke.mjs");

function loadableCopy() {
  const src = fs.readFileSync(TARGET, "utf8");
  const patched = src.replace("'/static/js/training.js'", `'${STUB}'`);
  assert.notEqual(patched, src,
    "expected the absolute training.js import to be present and rewritten");
  fs.writeFileSync(TMP, patched);
  return pathToFileURL(TMP).href;
}

/** The card's real markup, so the module sees the elements it looks for. */
function buildDom() {
  // Jinja tags would confuse the parser; the labeler only reads ids/classes.
  const markup = fs.readFileSync(CARD, "utf8")
    .replace(/\{%[\s\S]*?%\}/g, "")
    .replace(/\{\{[\s\S]*?\}\}/g, "");

  // jsdom has no canvas backend; getContext returns null and reports a
  // "not implemented" jsdomError. That is not a load failure, so swallow it —
  // but let every other console channel through so real errors stay visible.
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => {
    if (!/HTMLCanvasElement.prototype.getContext/.test(String(e))) throw e;
  });

  const dom = new JSDOM(`<!doctype html><html><body>${markup}</body></html>`,
    { pretendToBeVisual: true, virtualConsole });

  // Copy the whole window surface rather than a hand-listed subset. The first
  // version listed eight globals and the module still died on `new Image()`;
  // enumerating is a losing game, and a missing global would look exactly like
  // the load failure this test exists to detect.
  // These two are re-pointed unconditionally: the skip-if-present rule below
  // would otherwise leave a second buildDom() call reading the FIRST call's
  // (already closed) document.
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  for (const k of Object.getOwnPropertyNames(dom.window)) {
    if (k in globalThis) continue;
    try { globalThis[k] = dom.window[k]; } catch { /* getter-only; skip */ }
  }
  // The module fetches on init paths; keep it inert and offline.
  globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
  return dom;
}

test("the module loads without throwing, with the card's DOM present", async () => {
  const dom = buildDom();
  // Guard the guard: if the card markup ever stops carrying these, the IIFE
  // returns at its own early-exit and this test would pass without running
  // any of the init code it exists to exercise.
  assert.ok(document.getElementById("fl3d-stem-select"),
    "card markup must provide #fl3d-stem-select or init exits immediately");
  assert.ok(document.getElementById("fl3d-canvas"),
    "card markup must provide #fl3d-canvas or init exits immediately");

  try {
    await import(loadableCopy());
  } finally {
    fs.rmSync(TMP, { force: true });
    dom.window.close();
  }
});

test("the card markup carries the per-tile epipolar checkbox", async () => {
  // Cheap companion: the module wires this by class, so a template rename
  // would leave a module that loads fine and silently does nothing.
  buildDom();
  assert.ok(document.querySelector(".fl3d-tile-epi-cb"),
    "the primary tile header must carry .fl3d-tile-epi-cb");
});
