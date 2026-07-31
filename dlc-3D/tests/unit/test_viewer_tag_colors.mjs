import test from "node:test";
import assert from "node:assert/strict";
import { tagColor, sortTags, isValidHexColor } from "../../src/static/components/viewer/internal/tag_colors.mjs";

const MODULE_PATH =
  new URL("../../src/static/components/viewer/internal/tag_colors.mjs", import.meta.url).pathname;

const PALETTE8 = ["#34d399", "#f97316", "#e879f9", "#facc15", "#f87171", "#22d3ee", "#a78bfa", "#fb923c"];

// ── isValidHexColor ──────────────────────────────────────────────────────────

test("isValidHexColor accepts plain #rrggbb only", () => {
  assert.equal(isValidHexColor("#aabbcc"), true);
  assert.equal(isValidHexColor("#AABBCC"), true);
  assert.equal(isValidHexColor("#123456"), true);
});

test("isValidHexColor rejects malformed/short/injected values", () => {
  assert.equal(isValidHexColor("#abc"), false); // 3-digit shorthand not accepted
  assert.equal(isValidHexColor("red"), false);
  assert.equal(isValidHexColor("aabbcc"), false); // missing '#'
  assert.equal(isValidHexColor("#aabbccdd"), false); // too long
  assert.equal(isValidHexColor(""), false);
  assert.equal(isValidHexColor(null), false);
  assert.equal(isValidHexColor(undefined), false);
  assert.equal(isValidHexColor("#aabbcc; background: url(x)"), false); // CSS-injection attempt
  assert.equal(isValidHexColor(123456), false);
});

// ── tagColor ─────────────────────────────────────────────────────────────────

test("tagColor: same name → same color across repeated calls", () => {
  const c1 = tagColor("start-success", PALETTE8);
  const c2 = tagColor("start-success", PALETTE8);
  const c3 = tagColor("start-success", PALETTE8);
  assert.equal(c1, c2);
  assert.equal(c2, c3);
  assert.ok(PALETTE8.includes(c1));
});

test("tagColor: a name's color does not depend on which other names were queried around it", () => {
  const before = tagColor("shared-tag", PALETTE8);
  // Query a bunch of unrelated names in between.
  for (const n of ["one", "two", "three", "four", "five"]) tagColor(n, PALETTE8);
  const after = tagColor("shared-tag", PALETTE8);
  assert.equal(before, after);
});

test("tagColor: distributes distinct names across more than one palette slot", () => {
  const names = ["start-success", "not-good", "113.6", "start-failure", "f", "113.5", "113.4", "reach", "grasp"];
  const colors = new Set(names.map((n) => tagColor(n, PALETTE8)));
  assert.ok(colors.size > 1, `expected spread across slots, got ${colors.size} distinct colors`);
});

test("tagColor: every result is a member of the given palette", () => {
  for (const n of ["a", "bb", "ccc", "dddd", "start-success", "113.6", ""]) {
    assert.ok(PALETTE8.includes(tagColor(n, PALETTE8)), `tagColor(${JSON.stringify(n)}) not in palette`);
  }
});

test("tagColor: empty/missing palette does not throw", () => {
  assert.equal(tagColor("x", []), undefined);
  assert.equal(tagColor("x", undefined), undefined);
});

// Reproduces the actual bug being fixed: the same tag name must get the same
// color whether it is the first tag ever queried for a video/session or the
// Nth — i.e. tagColor(name, palette) may not depend on any hidden
// call-order/insertion-order state. Verified by loading TWO independent
// instances of the module (via cache-busting query strings, so each gets its
// own fresh module-level state) and priming each with a DIFFERENT set/order
// of other tag names before asking for the same target name — a pure
// hash-based implementation is unaffected by this; an insertion-order-based
// one would assign the target a different slot depending on how many/which
// other distinct names were "seen" first in each instance.
test("tagColor: same name -> same color even under different call-order priming (catches insertion-order regressions)", async () => {
  const modA = await import(`${MODULE_PATH}?tagcolor-order-a`);
  const modB = await import(`${MODULE_PATH}?tagcolor-order-b`);
  assert.notEqual(modA.tagColor, modB.tagColor, "sanity: must be independent module instances");

  // Instance A: prime with 7 other names, THEN query the target.
  for (const n of ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf"]) modA.tagColor(n, PALETTE8);
  const colorA = modA.tagColor("target-tag", PALETTE8);

  // Instance B: query the target FIRST, with no priming at all.
  const colorB = modB.tagColor("target-tag", PALETTE8);

  assert.equal(colorA, colorB, "tagColor must not depend on prior calls for other names");
});

// ── sortTags ─────────────────────────────────────────────────────────────────

test("sortTags: no overrides -> plain alphabetical", () => {
  assert.deepEqual(
    sortTags(["start-success", "not-good", "113.6", "start-failure", "f"], {}),
    ["113.6", "f", "not-good", "start-failure", "start-success"],
  );
});

test("sortTags: some overrides -> overridden tags first (alphabetical within group), then the rest alphabetically", () => {
  const tags = ["start-success", "not-good", "113.6", "start-failure", "f"];
  const overrides = { f: "#111111", "start-success": "#222222" };
  assert.deepEqual(
    sortTags(tags, overrides),
    ["f", "start-success", "113.6", "not-good", "start-failure"],
  );
});

test("sortTags: all tags overridden -> pure alphabetical (single group)", () => {
  const tags = ["zeta", "alpha", "mu"];
  const overrides = { zeta: "#111111", alpha: "#222222", mu: "#333333" };
  assert.deepEqual(sortTags(tags, overrides), ["alpha", "mu", "zeta"]);
});

test("sortTags: an override for a tag not currently present is ignored (no invented entries)", () => {
  const tags = ["bravo", "alpha"];
  const overrides = { "not-present-at-all": "#111111" };
  assert.deepEqual(sortTags(tags, overrides), ["alpha", "bravo"]);
});

test("sortTags: missing/undefined overrides behaves like {}", () => {
  assert.deepEqual(sortTags(["b", "a"], undefined), ["a", "b"]);
  assert.deepEqual(sortTags(["b", "a"], null), ["a", "b"]);
});

test("sortTags: does not mutate its inputs", () => {
  const tags = ["b", "a", "c"];
  const overrides = { c: "#111111" };
  const before = tags.slice();
  sortTags(tags, overrides);
  assert.deepEqual(tags, before);
});

test("sortTags: empty tags -> empty array", () => {
  assert.deepEqual(sortTags([], { a: "#111111" }), []);
  assert.deepEqual(sortTags([], {}), []);
});
