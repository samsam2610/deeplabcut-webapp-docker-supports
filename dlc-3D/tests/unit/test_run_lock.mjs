import test from "node:test";
import assert from "node:assert/strict";
import { tryAcquire, release } from "../../src/static/internal/run_lock.mjs";

const btn = () => ({ disabled: false });

test("the first run takes the lock", () => {
  const b = [btn(), btn()];
  assert.equal(tryAcquire(b), true);
  assert.deepEqual(b.map((x) => x.disabled), [true, true]);
});

test("a second click while running is refused", () => {
  // The reported bug: two jobs on one window, competing for the same GPU.
  const b = [btn(), btn()];
  tryAcquire(b);
  assert.equal(tryAcquire(b), false);
});

test("the lock spans both run buttons, not one each", () => {
  // 2D and 3D score the same window into the same state.
  const run2d = btn(), run3d = btn();
  tryAcquire([run2d, run3d]);
  assert.equal(run2d.disabled, true);
  assert.equal(run3d.disabled, true);
});

test("releasing lets the next run start", () => {
  const b = [btn(), btn()];
  tryAcquire(b);
  release(b);
  assert.deepEqual(b.map((x) => x.disabled), [false, false]);
  assert.equal(tryAcquire(b), true);
});

test("release is safe when the lock was never taken", () => {
  const b = [btn()];
  release(b);
  assert.equal(b[0].disabled, false);
});

test("a missing button does not block runs forever", () => {
  // If the card changes and a button id goes stale, the panel must still work
  // rather than lock permanently on a null.
  assert.equal(tryAcquire([null, undefined]), true);
  assert.equal(tryAcquire([]), true);
});

test("release tolerates missing buttons", () => {
  release([null, btn(), undefined]);      // must not throw
});
