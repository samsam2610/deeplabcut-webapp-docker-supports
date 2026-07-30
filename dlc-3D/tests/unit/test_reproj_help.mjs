import test from "node:test";
import assert from "node:assert/strict";
import { HELP, HELP_DEFAULT } from "../../src/static/internal/reproj_help.mjs";

const KEYS = ["trusted_cam", "k1", "k2", "gate_ref", "low_tgt", "high_conf",
              "rescue_floor"];

test("HELP covers exactly the panel's parameters", () => {
  assert.deepEqual(Object.keys(HELP).sort(), [...KEYS].sort());
});

test("every entry has a title, body and worked example", () => {
  for (const [key, e] of Object.entries(HELP)) {
    assert.ok(e.title && e.title.trim().length, `${key}: empty title`);
    assert.ok(e.body && e.body.trim().length > 20, `${key}: body too thin`);
    assert.ok(e.example && e.example.trim().length > 10,
              `${key}: an example is what makes it land`);
  }
});

test("the default state has something to say", () => {
  assert.ok(HELP_DEFAULT.title && HELP_DEFAULT.title.trim().length);
  assert.ok(HELP_DEFAULT.body && HELP_DEFAULT.body.trim().length > 20);
});

test("the two counter-intuitive parameters say so explicitly", () => {
  // high_conf loosens the rule when lowered; low_tgt does not affect rejection.
  // If these ever stop being called out, the panel has lost its main value.
  assert.match(HELP.high_conf.body + HELP.high_conf.example, /loosen|wider|inflat/i);
  assert.match(HELP.low_tgt.body, /reject/i);
});
