import test from "node:test";
import assert from "node:assert/strict";
import {
  PER_VIDEO_KEYS, emptyPanelState, isCleared,
} from "../../src/static/internal/panel_state.mjs";

const populated = () => ({
  windows: [{ start: 1, end: 2 }],
  trials: [{ marker: 2 }],
  active: { pick: 5 },
  masks: new Map([[1, {}]]),
  markers: [{ frame: 1, note: "s" }],
  sibling: "/v/cam1.avi",
  canUndo: true,
  tagRows: [{ frame_number: 1 }],
  judge: { threshold: 0.55 },        // project-level, must survive
  frame: 1234,
});

test("every per-video key has a cleared value", () => {
  const empty = emptyPanelState();
  PER_VIDEO_KEYS.forEach((k) => assert.ok(k in empty, `no reset for ${k}`));
});

test("a populated state is not cleared", () => {
  assert.equal(isCleared(populated()), false);
});

test("applying the empty state clears everything about the video", () => {
  const after = { ...populated(), ...emptyPanelState() };
  assert.equal(isCleared(after), true);
});

test("project-level state survives the reset", () => {
  // The judging parameters belong to the project, not the video; wiping them on
  // every switch would silently re-tune the pipeline.
  const after = { ...populated(), ...emptyPanelState() };
  assert.deepEqual(after.judge, { threshold: 0.55 });
});

test("each individual leftover is caught", () => {
  // Guards the guard: isCleared must not pass just because most keys are empty.
  PER_VIDEO_KEYS.forEach((k) => {
    const s = { ...emptyPanelState() };
    s[k] = k === "canUndo" ? true
      : k === "sibling" ? "/v/x.avi"
      : k === "active" || k === "tagRows" ? { a: 1 }
      : k === "masks" ? new Map([[1, {}]])
      : [{}];
    assert.equal(isCleared(s), false, `a leftover ${k} was not noticed`);
  });
});

test("a fresh empty state is cleared", () => {
  assert.equal(isCleared(emptyPanelState()), true);
});

test("an unknown state is treated as cleared rather than throwing", () => {
  assert.equal(isCleared(undefined), true);
  assert.equal(isCleared({}), true);
});
