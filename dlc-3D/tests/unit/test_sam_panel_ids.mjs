// Every id the SAM panel wires must exist in the card it wires against.
//
// This panel has gone dead twice from an id that did not match:
//
//   * `_pelletTiles()` excluded two canvases BY ID while the overlays it made
//     had none, so every poll gave each overlay its own overlay
//   * a stale `ia3ds-pellet-show` handler threw on `.onclick` of null and took
//     every handler wired after it with it — the whole panel, from one id
//
// The `on()` helper downgrades the second failure to a console warning, which
// means a typo is now silent rather than fatal. That is worse to diagnose, so
// the mismatch has to be caught here instead.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.join(HERE, "..", "..", "src", "static");

const js = fs.readFileSync(path.join(STATIC, "inline_analysis_3d_sam.js"), "utf8");
const html = fs.readFileSync(
  path.join(STATIC, "card_inline_analysis_3d_sam.html"), "utf8");

const declared = new Set(
  [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));

/** ids the JS looks up: _samEl("x"), on("x", …), getElementById("x"). */
function referenced(source) {
  const out = new Set();
  const patterns = [
    /_samEl\(\s*"([^"]+)"\s*\)/g,
    /\bon\(\s*"([^"]+)"\s*,/g,
    /getElementById\(\s*"([^"]+)"\s*\)/g,
  ];
  patterns.forEach((re) => {
    for (const m of source.matchAll(re)) out.add(m[1]);
  });
  return out;
}

// Created at runtime rather than declared in the card.
const RUNTIME_IDS = new Set([
  "ia3ds-ov-cam0",                  // per-tile overlay canvases
  "ia3ds-ov-cam1",
  "inline-analysis-3d-sam-card",    // the card element itself, from dlc_3d.html
]);

test("every id the panel wires exists in the card", () => {
  const missing = [...referenced(js)]
    .filter((id) => id.startsWith("ia3ds-") || id.startsWith("inline-analysis"))
    .filter((id) => !declared.has(id) && !RUNTIME_IDS.has(id));
  assert.deepEqual(missing, [], `wired but absent from the card: ${missing}`);
});

test("the judging fields the panel reads are all present", () => {
  // Reading a missing field yields undefined, which clampJudge turns into the
  // default — so a typo here does not throw, it silently ignores the user.
  ["ia3ds-judge-threshold", "ia3ds-judge-minrun", "ia3ds-judge-lookback",
   "ia3ds-judge-mincand", "ia3ds-judge-guard", "ia3ds-judge-apply",
   "ia3ds-judge-reset", "ia3ds-judge-status",
  ].forEach((id) => assert.ok(declared.has(id), `card is missing #${id}`));
});

test("no id is declared twice in the card", () => {
  const all = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
  const dupes = all.filter((id, i) => all.indexOf(id) !== i);
  assert.deepEqual([...new Set(dupes)], []);
});
