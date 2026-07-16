import test from "node:test";
import assert from "node:assert/strict";
import { serializeEditsForSave } from "../../src/static/components/viewer/internal/marker_overlay.mjs";

// serializeEditsForSave converts the in-memory editsByCam[cam] shape
// ({ [frame]: { [bp]: {x,y} } }, integer frame keys) into the server edit-cache
// format ({ "frame_<N>": {bp:{x,y}} }) so Save can send memory directly and the
// backend applies it without depending on the async marker-edit mirror.

test("serializeEditsForSave: integer frame keys → 'frame_<N>' cache format", () => {
  const edits = { 3: { Snout: { x: 12, y: 34 } }, 10: { Wrist: { x: 5, y: 6 } } };
  assert.deepEqual(serializeEditsForSave(edits), {
    frame_3: { Snout: { x: 12, y: 34 } },
    frame_10: { Wrist: { x: 5, y: 6 } },
  });
});

test("serializeEditsForSave: preserves deleted markers (null x/y)", () => {
  const edits = { 7: { Tail: { x: null, y: null } } };
  assert.deepEqual(serializeEditsForSave(edits), { frame_7: { Tail: { x: null, y: null } } });
});

test("serializeEditsForSave: empty / null → {}", () => {
  assert.deepEqual(serializeEditsForSave({}), {});
  assert.deepEqual(serializeEditsForSave(null), {});
});
