import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const app = readFileSync(new URL("../../ui/app.js", import.meta.url), "utf8");
const start = app.indexOf("function paintCommandStatus(");
const end = app.indexOf("\nfunction applyIntelMode(", start);

function harness(api) {
  const nodes = new Map();
  for (const id of ["#view-live", "#live-ai-coverage", "#cc-health", "#cc-alerts", "#cc-ai"]) {
    const classes = new Set(id === "#view-live" ? ["active"] : []);
    nodes.set(id, { textContent: "", title: "", hidden: true,
      classList: {
        contains: (name) => classes.has(name),
        toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
      } });
  }
  const context = vm.createContext({ $: (id) => nodes.get(id), state: {}, api });
  vm.runInContext(app.slice(start, end), context);
  return { nodes, context };
}

test("coverage and its explanation reach the wall and masthead", () => {
  const { nodes, context } = harness();
  const worker = { chip: "AI ACTIVE", note: "COVERAGE registered | DEEP INFERENCE active",
    detail: "Bounded by machine throughput." };
  context.paintCommandStatus({ isolation: { ai_worker: worker } }, null);
  assert.equal(nodes.get("#live-ai-coverage").textContent, worker.note);
  assert.equal(nodes.get("#live-ai-coverage").hidden, false);
  assert.equal(nodes.get("#live-ai-coverage").title, worker.detail);
  assert.equal(nodes.get("#cc-ai").title, `${worker.note}\n${worker.detail}`);
  assert.equal(nodes.get("#cc-ai").classList.contains("verify"), false);
  assert.equal(context.state.isolation.ai_worker, worker);
});

test("failed refresh replaces an old active reading with unknown status", async () => {
  const { nodes, context } = harness(async () => { throw new Error("offline"); });
  context.paintCommandStatus({ isolation: { ai_worker: { chip: "AI ACTIVE", note: "old" } } }, null);
  await context.refreshAnalyticsCoverage();
  assert.equal(nodes.get("#cc-ai").textContent, "AI NOT MEASURED");
  assert.match(nodes.get("#live-ai-coverage").textContent, /deep inference not measured/);
});

test("coverage polls do not overlap and ignore a response after leaving Live", async () => {
  let resolve;
  let calls = 0;
  const { nodes, context } = harness(() => {
    calls += 1;
    return new Promise((done) => { resolve = done; });
  });
  const pending = context.refreshAnalyticsCoverage();
  await context.refreshAnalyticsCoverage();
  assert.equal(calls, 1);
  nodes.get("#view-live").classList.toggle("active", false);
  resolve({ isolation: { ai_worker: { chip: "AI ACTIVE", note: "late" } } });
  await pending;
  assert.equal(nodes.get("#live-ai-coverage").textContent, "");
});
