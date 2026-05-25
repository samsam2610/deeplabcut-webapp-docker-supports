import test from "node:test";
import assert from "node:assert/strict";
import { addTag, removeTag } from "../../src/static/internal/tag_list.mjs";

test("addTag: appends a trimmed tag, returns a new array", () => {
  const a = ["reach"];
  const b = addTag(a, "  good  ");
  assert.deepEqual(b, ["reach", "good"]);
  assert.deepEqual(a, ["reach"], "input array must not be mutated");
});

test("addTag: dedupes (case-sensitive exact match) and ignores empties", () => {
  assert.deepEqual(addTag(["reach"], "reach"), ["reach"]);
  assert.deepEqual(addTag(["reach"], ""), ["reach"]);
  assert.deepEqual(addTag(["reach"], "   "), ["reach"]);
});

test("addTag: coerces a non-array base to an empty list", () => {
  assert.deepEqual(addTag(null, "good"), ["good"]);
  assert.deepEqual(addTag(undefined, "good"), ["good"]);
});

test("removeTag: removes the exact value, returns a new array, no-op if absent", () => {
  const a = ["reach", "good", "retry"];
  assert.deepEqual(removeTag(a, "good"), ["reach", "retry"]);
  assert.deepEqual(a, ["reach", "good", "retry"], "input array must not be mutated");
  assert.deepEqual(removeTag(["reach"], "absent"), ["reach"]);
});

test("removeTag: coerces a non-array base to an empty list", () => {
  assert.deepEqual(removeTag(null, "x"), []);
});
