import test from "node:test";
import assert from "node:assert/strict";
import { epiGateReason, collectRefPoints, payloadSignature,
         classifyPPress, EPI_DOUBLE_TAP_MS }
  from "../../src/static/internal/epiline_request.mjs";

const OK = { syncOn: true, calibrationExists: true, camCount: 2 };

test("gate passes only when sync, calibration and two cams are all present", () => {
  assert.equal(epiGateReason(OK), null);
});

test("each blocked condition names itself", () => {
  // A single dead checkbox teaches the user nothing — each cause is distinct.
  assert.match(epiGateReason({ ...OK, syncOn: false }), /sync/i);
  assert.match(epiGateReason({ ...OK, calibrationExists: false }), /calibration\.toml/i);
  assert.match(epiGateReason({ ...OK, camCount: 1 }), /one camera/i);
});

test("more than two cameras is rejected at the gate, not misdrawn", () => {
  // The feature only knows how to project ref -> one target; on a 3+ camera
  // rig every non-reference tile but one would get geometrically wrong
  // lines, so this closes at the gate instead of generalising the drawing.
  assert.match(epiGateReason({ ...OK, camCount: 3 }), /exactly two cameras/i);
});

test("sync is reported before calibration when both are missing", () => {
  // Sync is the one the user can fix instantly; lead with it.
  const r = epiGateReason({ syncOn: false, calibrationExists: false, camCount: 1 });
  assert.match(r, /sync/i);
});

test("collectRefPoints returns labelled, visible bodyparts in bodypart order", () => {
  const labels = { paw: [30, 40], wrist: [10, 20] };
  const out = collectRefPoints(labels, {}, ["wrist", "elbow", "paw"]);
  assert.deepEqual(out, [
    { bodypart: "wrist", x: 10, y: 20 },
    { bodypart: "paw",   x: 30, y: 40 },
  ]);
});

test("unlabelled, null and hidden bodyparts are excluded", () => {
  const labels = { wrist: [1, 2], elbow: null, paw: [5, 6] };
  const out = collectRefPoints(labels, { paw: true }, ["wrist", "elbow", "paw"]);
  assert.deepEqual(out, [{ bodypart: "wrist", x: 1, y: 2 }]);
});

test("collectRefPoints tolerates missing label and hidden maps", () => {
  assert.deepEqual(collectRefPoints(undefined, undefined, ["wrist"]), []);
});

test("signature changes when any point moves", () => {
  const a = payloadSignature("s1", 0, 1, [{ bodypart: "w", x: 1, y: 2 }]);
  const b = payloadSignature("s1", 0, 1, [{ bodypart: "w", x: 1, y: 3 }]);
  assert.notEqual(a, b);
});

test("signature changes when the camera direction flips", () => {
  const pts = [{ bodypart: "w", x: 1, y: 2 }];
  assert.notEqual(payloadSignature("s1", 0, 1, pts),
                  payloadSignature("s1", 1, 0, pts));
});

test("signature is stable for identical input", () => {
  const pts = [{ bodypart: "w", x: 1, y: 2 }];
  assert.equal(payloadSignature("s1", 0, 1, pts),
               payloadSignature("s1", 0, 1, pts));
});

test("a lone P press is a single toggle", () => {
  assert.deepEqual(classifyPPress(1000, null), { kind: "single", revert: false });
});

test("a second press inside the window is a double-tap that reverts the first", () => {
  // revert matters: the single action already fired, so the double must undo
  // it or pressing PP would leave the overlay in the wrong state.
  assert.deepEqual(classifyPPress(1200, 1000),
                   { kind: "double", revert: true });
});

test("a second press past the window is another single", () => {
  assert.deepEqual(classifyPPress(1400, 1000), { kind: "single", revert: false });
});

test("the boundary is inclusive", () => {
  assert.equal(classifyPPress(1350, 1000).kind, "double");
  assert.equal(classifyPPress(1351, 1000).kind, "single");
});

test("a clock that went backwards is not a double-tap", () => {
  // Guards against a negative delta sneaking through the <= comparison.
  assert.equal(classifyPPress(900, 1000).kind, "single");
});

test("the double-tap window is 350ms", () => {
  assert.equal(EPI_DOUBLE_TAP_MS, 350);
});
