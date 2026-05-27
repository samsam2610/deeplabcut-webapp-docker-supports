import test from "node:test";
import assert from "node:assert/strict";
import { pickLatestVariant }
  from "../../src/static/components/viewer/internal/pick_latest_variant.mjs";

test("pickLatestVariant: returns the variant with the max ISO ts", () => {
  const variants = [
    { path: "/a.h5", ts: null },
    { path: "/old.h5", ts: "2026-05-02T11:36:42Z" },
    { path: "/new.h5", ts: "2026-05-20T09:00:00Z" },
  ];
  assert.equal(pickLatestVariant(variants).path, "/new.h5");
});

test("pickLatestVariant: ISO strings compare lexicographically (no Date parse needed)", () => {
  const variants = [
    { path: "/jan.h5", ts: "2026-01-31T23:59:59Z" },
    { path: "/feb.h5", ts: "2026-02-01T00:00:00Z" },
  ];
  assert.equal(pickLatestVariant(variants).path, "/feb.h5");
});

test("pickLatestVariant: all raw (no ts) → returns the LAST array element", () => {
  const variants = [
    { path: "/raw-a.h5", ts: null },
    { path: "/raw-b.h5", ts: null },
  ];
  // backend orders raw companions alphabetically; the last is the freshly-written one
  assert.equal(pickLatestVariant(variants).path, "/raw-b.h5");
});

test("pickLatestVariant: mix → a dated variant beats undated ones", () => {
  const variants = [
    { path: "/raw.h5", ts: null },
    { path: "/run.h5", ts: "2026-05-02T11:36:42Z" },
  ];
  assert.equal(pickLatestVariant(variants).path, "/run.h5");
});

test("pickLatestVariant: empty / null → null (overlay-on shows nothing)", () => {
  assert.equal(pickLatestVariant([]), null);
  assert.equal(pickLatestVariant(null), null);
  assert.equal(pickLatestVariant(undefined), null);
});

test("pickLatestVariant: single variant → that variant", () => {
  const v = { path: "/only.h5", ts: null };
  assert.equal(pickLatestVariant([v]), v);
});
