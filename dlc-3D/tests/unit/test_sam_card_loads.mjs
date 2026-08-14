// Does inline_analysis_3d_sam.js actually LOAD?
//
// Everything else in this suite checks pieces: the pure modules are unit
// tested, the ids are cross-checked against the card, the AST is walked for
// const reassignment. None of that executes the module.
//
// That gap is not theoretical — it is the same one that let three outages ship
// in frame_labeler_3d.js (see test_frame_labeler_loads.mjs). A temporal dead
// zone, a bad destructure, a typo'd import name: all parse fine, all pass every
// source-text assertion, and all throw at load, taking the whole panel with
// them. The card renders server-side, so the symptom is "the buttons do
// nothing", which reads like a backend problem.
//
// Added 2026-08-12 after a substantial rewrite of this file — new imports, a
// restructured runner, a new render path — with nothing executing it.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { JSDOM, VirtualConsole } from "jsdom";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, "..", "..", "src");
const TARGET = path.join(SRC, "static", "inline_analysis_3d_sam.js");
const CARD = path.join(SRC, "static", "card_inline_analysis_3d_sam.html");
const STUB = "../../tests/fixtures/sam_card_stubs.mjs";
const TMP = path.join(SRC, "static", ".inline_analysis_3d_sam.smoke.mjs");

/** A copy whose two absolute imports point at local stubs; relative ones keep working. */
function loadableCopy() {
  const src = fs.readFileSync(TARGET, "utf8");
  const patched = src
    .replace('"/static/js/components/tracked_files_tab.js"', `"${STUB}"`)
    .replace('"/static/js/state.js"', `"${STUB}"`);
  assert.notEqual(patched, src, "expected absolute imports to be present and rewritten");
  assert.ok(!patched.includes('"/static/js/'), "every absolute import must be stubbed");
  fs.writeFileSync(TMP, patched);
  return pathToFileURL(TMP).href;
}

const cardIds = new Set(
  [...fs.readFileSync(CARD, "utf8").matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));

function buildDom() {
  const markup = fs.readFileSync(CARD, "utf8")
    .replace(/\{%[\s\S]*?%\}/g, "")
    .replace(/\{\{[\s\S]*?\}\}/g, "");
  // jsdom has no canvas backend and getContext returns null. Left alone, the
  // first draw throws, the panel's own try/catch swallows it, and the REST OF
  // THE WIRING NEVER RUNS — so the test would pass while covering half the
  // function. A no-op 2D context lets the whole of _samWirePanel execute.
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (e) => {
    if (!/HTMLCanvasElement.prototype.getContext/.test(String(e))) throw e;
  });
  const dom = new JSDOM(`<!doctype html><html><body>${markup}</body></html>`,
    { pretendToBeVisual: true, virtualConsole });
  const ctx2d = new Proxy({}, {
    get: (_t, prop) => {
      if (prop === "measureText") return () => ({ width: 10 });
      if (prop === "canvas") return { width: 800, height: 600 };
      if (prop === "createLinearGradient") {
        return () => ({ addColorStop() {} });
      }
      return () => {};                 // every draw call is a no-op
    },
    set: () => true,                   // fillStyle, lineWidth, font, ...
  });
  dom.window.HTMLCanvasElement.prototype.getContext = () => ctx2d;
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  for (const k of Object.getOwnPropertyNames(dom.window)) {
    if (k in globalThis) continue;
    try { globalThis[k] = dom.window[k]; } catch { /* getter-only */ }
  }
  globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
  // Record the panel's pollers WITHOUT replacing the timer implementation.
  // node:test schedules off these; a no-op stub hangs the runner. unref() stops
  // the real intervals holding the process open.
  realTimers.setInterval = globalThis.setInterval;
  globalThis.setInterval = (fn, ms, ...rest) => {
    const id = realTimers.setInterval(fn, ms, ...rest);
    installed.push(ms);
    timerIds.push(id);
    if (id && typeof id.unref === "function") id.unref();
    return id;
  };
  return dom;
}

const installed = [];
const timerIds = [];
const realTimers = {};

function restoreTimers() {
  if (realTimers.setInterval) globalThis.setInterval = realTimers.setInterval;
  timerIds.forEach((id) => globalThis.clearInterval(id));
  timerIds.length = 0;
}

// The import happens at MODULE scope, not inside the test body. Awaiting it
// inside a node:test callback never settles here — the runner reports "Promise
// resolution is still pending but the event loop has already resolved" while a
// standalone script importing the very same file exits cleanly with zero active
// handles. Top-level await sidesteps the interaction entirely, and the test
// below then just asserts on what happened.
const dom = buildDom();
let loadError = null;
try {
  await import(loadableCopy());
} catch (err) {
  loadError = err;
} finally {
  restoreTimers();
  fs.rmSync(TMP, { force: true });
}
// Deferred via after() rather than closed inline above: node:test runs test()
// bodies only once the module's top-level (async) execution has fully settled,
// so an inline dom.window.close() here would blank the document — every
// dom.window.document access below would see an empty page — before any test
// gets to look at it. after() runs once all tests in this file have finished.
after(() => { dom.window.close(); });

test("the card's markup provides what the panel wires against", () => {
  // Guard the guard: without these the wiring exits early and the load test
  // below would pass without exercising the code it exists to cover.
  assert.ok(cardIds.has("ia3ds-sam-reload"),
    "card must provide #ia3ds-sam-reload or _samWirePanel returns immediately");
  assert.ok(cardIds.has("ia3ds-sam-run3d"), "card must provide the 3D run button");
});

test("the SAM card's module loads without throwing", () => {
  assert.equal(loadError, null,
    loadError ? `module threw on load: ${loadError.message}` : "");
});

test("loading it wires the panel all the way through", () => {
  // >= 2 proves _samWirePanel ran to completion: it installs the video watcher
  // AND the tile re-binder, and the second comes after the first canvas draw.
  // With jsdom's null 2D context only one appears — which is exactly how a
  // half-wired panel would slip past a load-only check.
  assert.ok(installed.length >= 2,
    `expected the panel's pollers to be installed, saw ${installed.length}`);
});

test("the SAM panel is one of the player section's panels", () => {
  // It has to share a parent with the other five to take part in the reorder,
  // and sharing that parent is also what makes it hide with the player instead
  // of lingering with a closed video's contents on screen.
  const section = dom.window.document.getElementById("ia3ds-player-section");
  const panel = dom.window.document.getElementById("ia3ds-sam-panel");
  assert.ok(section, "card must have #ia3ds-player-section");
  assert.ok(panel, "card must have #ia3ds-sam-panel");
  assert.equal(panel.parentElement, section);
});

test("the SAM panel starts collapsed, like its five neighbours", () => {
  const controls = dom.window.document.getElementById("ia3ds-sam-controls");
  const toggle = dom.window.document.getElementById("ia3ds-sam-toggle");
  assert.ok(controls, "card must have #ia3ds-sam-controls");
  assert.ok(controls.className.split(/\s+/).includes("hidden"));
  assert.equal(toggle.checked, false);
});

test("the trial picker lives inside the collapsible body", () => {
  // A control left outside the wrapper would still be on screen when the panel
  // is collapsed -- which is how a "collapsed" panel keeps acting.
  const controls = dom.window.document.getElementById("ia3ds-sam-controls");
  assert.ok(controls.querySelector("#ia3ds-sam-trial"),
    "the trial dropdown must be inside #ia3ds-sam-controls");
  assert.ok(controls.querySelector("#ia3ds-pellet"),
    "the pellet section must be inside #ia3ds-sam-controls");
});
