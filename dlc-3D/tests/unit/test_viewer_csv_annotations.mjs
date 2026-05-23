import test from "node:test";
import assert from "node:assert/strict";
import {
  uniqueValues, assignColors, findMatchingFrame, rowForFrame,
  isInterestingAnnotation, applySavedRow, buildSaveRowPayload,
} from "../../src/static/components/viewer/internal/csv_annotations.mjs";

const ROWS = [
  { frame_number: 1, frame_line_status: "0", note: "" },
  { frame_number: 3, frame_line_status: "reach", note: "good" },
  { frame_number: 5, frame_line_status: "reach", note: "" },
  { frame_number: 8, frame_line_status: "grasp", note: "good" },
];

test("uniqueValues: status drops '0'/empty, keeps first-seen order, dedups", () => {
  assert.deepEqual(uniqueValues(ROWS, "frame_line_status"), ["reach", "grasp"]);
  assert.deepEqual(uniqueValues(ROWS, "note"), ["good"]);
});

test("assignColors cycles the palette by index", () => {
  assert.deepEqual(assignColors(["a", "b", "c"], ["#1", "#2"]),
    { a: "#1", b: "#2", c: "#1" });
});

test("findMatchingFrame: next/prev in frame_number space, accepts Set or array", () => {
  // next 'reach' after frame 3 is 5; after 5 is null
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", ["reach"], 3, 1), 5);
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", ["reach"], 5, 1), null);
  // prev 'reach' before frame 5 is 3
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", new Set(["reach"]), 5, -1), 3);
  // multi-value set spans both values
  assert.equal(findMatchingFrame(ROWS, "frame_line_status", new Set(["reach", "grasp"]), 5, 1), 8);
});

test("findMatchingFrame: empty active set or no match → null", () => {
  assert.equal(findMatchingFrame(ROWS, "note", [], 0, 1), null);
  assert.equal(findMatchingFrame(ROWS, "note", ["missing"], 0, 1), null);
});

test("rowForFrame returns the row or null", () => {
  assert.equal(rowForFrame(ROWS, 3).note, "good");
  assert.equal(rowForFrame(ROWS, 999), null);
});

test("isInterestingAnnotation: note OR non-'0' status", () => {
  assert.equal(isInterestingAnnotation("hi", "0"), true);
  assert.equal(isInterestingAnnotation("", "reach"), true);
  assert.equal(isInterestingAnnotation("", "0"), false);
  assert.equal(isInterestingAnnotation("", ""), false);
});

test("applySavedRow updates existing, inserts+sorts new, deletes when not interesting", () => {
  // update existing frame 3
  const upd = applySavedRow(ROWS, { frame_number: 3, frame_line_status: "reach", note: "edited" }, true);
  assert.equal(rowForFrame(upd, 3).note, "edited");
  assert.equal(upd.length, ROWS.length);
  // insert new frame 4, kept sorted
  const ins = applySavedRow(ROWS, { frame_number: 4, frame_line_status: "x", note: "" }, true);
  assert.deepEqual(ins.map((r) => r.frame_number), [1, 3, 4, 5, 8]);
  // delete frame 3 when not interesting
  const del = applySavedRow(ROWS, { frame_number: 3 }, false);
  assert.equal(rowForFrame(del, 3), null);
  assert.equal(del.length, ROWS.length - 1);
  // not interesting + not present → unchanged length
  assert.equal(applySavedRow(ROWS, { frame_number: 99 }, false).length, ROWS.length);
});

test("applySavedRow does not mutate the input array", () => {
  const before = ROWS.length;
  applySavedRow(ROWS, { frame_number: 4, note: "z" }, true);
  assert.equal(ROWS.length, before);
});

test("buildSaveRowPayload shapes the request body", () => {
  assert.deepEqual(
    buildSaveRowPayload({ csvPath: "/x.csv", frameNumber: 7, note: "n", status: "s", fps: 30 }),
    { csv_path: "/x.csv", frame_number: 7, note: "n", frame_line_status: "s", fps: 30 },
  );
});
