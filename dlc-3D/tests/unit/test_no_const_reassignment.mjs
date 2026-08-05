// No `const` binding may be assigned to.
//
// Shipped 2026-08-05: the per-tile refactor turned _fl3dEpiSig and
// _fl3dEpiSegments into const Maps, but _flShowFrame still did
// `_fl3dEpiSig = ""` on every frame change. That throws TypeError at runtime,
// aborting _flShowFrame partway — the epipolar lines stopped refreshing (the
// reported symptom) and, less visibly, so did the frame-name label, the
// bodypart chip status, the label count and the TAP status below it.
//
// Neither existing net catches this. `node --check` sees legal syntax; it is
// illegal only when executed. The jsdom load test imports the module, but the
// throw is on the frame-change path, not the import path.
//
// This walks a real AST rather than grepping. A regex version was written
// first and produced a screenful of false positives from template literals
// (`<rect x="2"`), query strings (`&buckets=${w}`) and multi-declarator
// consts — which is why the parser dependency is worth it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as acorn from "acorn";
import * as walk from "acorn-walk";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const STATIC = path.join(HERE, "..", "..", "src", "static");

/** Every first-party browser ES module under src/static, recursively. */
function jsFiles(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "vendor") continue;      // third-party, not ours to police
      out.push(...jsFiles(p));
    } else if (/\.(js|mjs)$/.test(e.name) && !e.name.startsWith(".")) {
      out.push(p);
    }
  }
  return out;
}

function constReassignments(src) {
  const ast = acorn.parse(src, {
    ecmaVersion: 2022, sourceType: "module", locations: true,
  });

  // Only MODULE-scope consts: declared at the top level, or directly inside
  // the single IIFE these files wrap themselves in. Locals are excluded
  // because we do no scope resolution — a `const idx` in one function and a
  // `let idx` in another are different bindings, and treating them as one
  // produced exactly that class of false positive.
  const isFn = (n) => /Function/.test(n.type);
  const moduleConsts = new Set();
  walk.ancestor(ast, {
    VariableDeclaration(node, _st, ancestors) {
      if (node.kind !== "const") return;
      if (ancestors.filter(isFn).length > 1) return;   // nested: skip
      for (const d of node.declarations) {
        walk.simple(d.id, { Identifier: (id) => moduleConsts.add(id.name) });
      }
    },
  });

  // Any name also bound as let/var/param somewhere is ambiguous without real
  // scope resolution — drop it rather than risk a false accusation.
  const rebound = new Set();
  walk.simple(ast, {
    VariableDeclaration(node) {
      if (node.kind === "const") return;
      for (const d of node.declarations) {
        walk.simple(d.id, { Identifier: (id) => rebound.add(id.name) });
      }
    },
    Function(node) {
      for (const p of node.params || []) {
        walk.simple(p, { Identifier: (id) => rebound.add(id.name) });
      }
    },
  });
  const constNames = new Set(
    [...moduleConsts].filter((n) => !rebound.has(n)));

  const bad = [];
  const flag = (name, node) => {
    if (constNames.has(name)) {
      bad.push(`${name} at line ${node.loc.start.line}`);
    }
  };
  walk.simple(ast, {
    AssignmentExpression(node) {
      if (node.left.type === "Identifier") flag(node.left.name, node);
    },
    UpdateExpression(node) {            // x++ / --x on a const throws too
      if (node.argument.type === "Identifier") flag(node.argument.name, node);
    },
  });
  return bad;
}

for (const file of jsFiles(STATIC)) {
  test(`no const is reassigned in ${path.relative(STATIC, file)}`, () => {
    const offenders = constReassignments(fs.readFileSync(file, "utf8"));
    assert.deepEqual(offenders, [],
      "assignment to a const throws TypeError at runtime and aborts the "
      + "enclosing function partway, silently killing everything after it:\n  "
      + offenders.join("\n  "));
  });
}
