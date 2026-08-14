// Which panels a card shows, and in what order.
//
// The two ways a saved-layout feature normally breaks, both pinned below:
//
//   * a panel added in a later release is absent from every saved order, and a
//     naive "render the saved list" makes it VANISH for anyone who has ever
//     dragged a panel;
//   * a panel removed in a later release is still in the saved order, and a
//     naive render tries to place an element that is not there.
//
// The rule that avoids both: the DOM decides membership, the saved order only
// decides sequence.
import test from "node:test";
import assert from "node:assert/strict";

import { applyOrder, reorder, sameOrder, dropTarget } from
  "../../src/static/internal/panel_order.mjs";

const DOM = ["a", "b", "c"];

test("with nothing saved, the markup order stands", () => {
  assert.deepEqual(applyOrder(DOM, []), ["a", "b", "c"]);
  assert.deepEqual(applyOrder(DOM, null), ["a", "b", "c"]);
});

test("a saved order is applied", () => {
  assert.deepEqual(applyOrder(DOM, ["c", "a", "b"]), ["c", "a", "b"]);
});

test("an id no longer in the DOM is ignored", () => {
  assert.deepEqual(applyOrder(DOM, ["gone", "c", "a", "b"]), ["c", "a", "b"]);
});

test("a panel missing from the saved order still appears", () => {
  // The regression that would otherwise hide a newly shipped panel from every
  // user who has dragged anything.
  assert.deepEqual(applyOrder(DOM, ["c", "a"]), ["c", "a", "b"]);
});

test("panels missing from the saved order keep their markup order", () => {
  assert.deepEqual(applyOrder(["a", "b", "c", "d"], ["c"]), ["c", "a", "b", "d"]);
});

test("a duplicated id in the saved order is placed once", () => {
  assert.deepEqual(applyOrder(DOM, ["c", "c", "a"]), ["c", "a", "b"]);
});

test("an empty DOM yields an empty order", () => {
  assert.deepEqual(applyOrder([], ["a"]), []);
});

test("reorder moves a panel before another", () => {
  assert.deepEqual(reorder(DOM, "c", "a"), ["c", "a", "b"]);
  assert.deepEqual(reorder(DOM, "a", "c"), ["b", "a", "c"]);
});

test("reorder with a null target moves it to the end", () => {
  // Dropping below the last panel is the only way to reach the end, so this is
  // not an edge case -- it is one of the two moves a user makes.
  assert.deepEqual(reorder(DOM, "a", null), ["b", "c", "a"]);
});

test("reorder onto itself changes nothing", () => {
  assert.deepEqual(reorder(DOM, "b", "b"), ["a", "b", "c"]);
});

test("reordering an unknown id changes nothing", () => {
  assert.deepEqual(reorder(DOM, "zz", "a"), ["a", "b", "c"]);
});

test("reorder does not mutate its input", () => {
  const input = ["a", "b", "c"];
  reorder(input, "c", "a");
  assert.deepEqual(input, ["a", "b", "c"]);
});

test("sameOrder compares by sequence", () => {
  assert.equal(sameOrder(["a", "b"], ["a", "b"]), true);
  assert.equal(sameOrder(["a", "b"], ["b", "a"]), false);
  assert.equal(sameOrder(["a"], ["a", "b"]), false);
  assert.equal(sameOrder(null, []), true);
});

// dropTarget — the decision made when a drag ends: which id (if any) to
// insert the moved panel before. `low` is whether the pointer was in the
// lower half of the drop target when the drop happened.
const FOUR = ["a", "b", "c", "d"];

test("upper half of a target inserts before it", () => {
  assert.equal(dropTarget(FOUR, "a", "c", false), "c");
});

test("lower half of a target inserts before the next panel", () => {
  assert.equal(dropTarget(FOUR, "a", "c", true), "d");
});

test("lower half of the last panel appends to the end", () => {
  // The only gesture that reaches the end of the list — a regression here
  // silently removes it.
  assert.equal(dropTarget(FOUR, "a", "d", true), null);
});

test("dropping a panel where it already sits, upper half, is a no-op", () => {
  // "a" already sits immediately before "b" — this would otherwise still
  // "succeed" and trigger a pointless save.
  assert.equal(dropTarget(FOUR, "a", "b", false), undefined);
});

test("dropping a panel where it already sits, lower half, is a no-op", () => {
  // The case the old `target === moved` guard existed for: "b" already sits
  // immediately after "a".
  assert.equal(dropTarget(FOUR, "b", "a", true), undefined);
});

test("a movedId that is not in ids is a no-op, not a crash", () => {
  assert.equal(dropTarget(FOUR, "zz", "b", false), undefined);
});
