import assert from "node:assert/strict";
import { test } from "node:test";
import { officerIdMismatch } from "../../ui/auth-gate.js";

test("matching officer id and server principal is accepted", () => {
  assert.equal(officerIdMismatch("inv.patel", { user_id: "inv.patel" }), false);
});
test("comparison is case-insensitive and trims whitespace", () => {
  assert.equal(officerIdMismatch("  INV.Patel ", { user_id: "inv.patel" }), false);
});
test("a different or empty officer id is rejected", () => {
  assert.equal(officerIdMismatch("sup.demo", { user_id: "inv.patel" }), true);
  assert.equal(officerIdMismatch("", { user_id: "inv.patel" }), true);
  assert.equal(officerIdMismatch("inv.patel", null), true);
});
