import test from "node:test";
import assert from "node:assert/strict";
import { makeEventBus } from "../../src/static/components/viewer/internal/event_bus.mjs";

test("on/emit delivers args to listener", () => {
  const bus = makeEventBus();
  let got = null;
  bus.on("frame", (n, extra) => { got = [n, extra]; });
  bus.emit("frame", 7, "x");
  assert.deepEqual(got, [7, "x"]);
});

test("multiple listeners on one event all fire", () => {
  const bus = makeEventBus();
  let a = 0, b = 0;
  bus.on("e", () => a++);
  bus.on("e", () => b++);
  bus.emit("e");
  assert.equal(a, 1);
  assert.equal(b, 1);
});

test("emit with no listeners is a no-op", () => {
  const bus = makeEventBus();
  assert.doesNotThrow(() => bus.emit("nope", 1));
});

test("the function returned by on() unsubscribes", () => {
  const bus = makeEventBus();
  let n = 0;
  const off = bus.on("e", () => n++);
  bus.emit("e");
  off();
  bus.emit("e");
  assert.equal(n, 1);
});

test("a listener unsubscribing itself mid-emit does not break iteration", () => {
  const bus = makeEventBus();
  const calls = [];
  const off = bus.on("e", () => { calls.push("a"); off(); });
  bus.on("e", () => calls.push("b"));
  bus.emit("e");
  bus.emit("e");
  assert.deepEqual(calls, ["a", "b", "b"]);
});
