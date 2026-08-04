import test from "node:test";
import assert from "node:assert/strict";
import { epiGateReason, collectRefPoints, payloadSignature }
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
