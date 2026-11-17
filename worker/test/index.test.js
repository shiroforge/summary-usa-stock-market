import assert from "node:assert/strict";
import { test } from "node:test";

import { buildDispatch, dispatch, SLOTS, slotAt } from "../src/index.js";

const env = { GITHUB_TOKEN: "test-token" };
const at = (hhmm) => Date.parse(`2026-11-18T${hhmm}:00Z`);

test("each repo waits for complete data until its last slot", () => {
  for (const repo of new Set(Object.values(SLOTS).map((s) => s.repo))) {
    const slots = Object.keys(SLOTS).filter((k) => SLOTS[k].repo === repo).sort();
    assert.deepEqual(
      slots.map((k) => SLOTS[k].early),
      [...slots.slice(0, -1).map(() => true), false],
      repo,
    );
  }
});

test("the scheduled time picks the repo", () => {
  assert.equal(slotAt(at("06:50")).repo, "shiroforge/summary-jpn-stock-market");
  assert.equal(slotAt(at("22:00")).repo, "shiroforge/summary-usa-stock-market");
  assert.throws(() => slotAt(at("12:00")), /no slot for 12:00/);
});

test("dispatch request", () => {
  const { url, init } = buildDispatch(SLOTS["23:30"], env);
  assert.equal(url, "https://api.github.com/repos/shiroforge/summary-usa-stock-market/actions/workflows/daily.yml/dispatches");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, "Bearer test-token");
  assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { notify: "true", early: "false" } });
  assert.equal(JSON.parse(buildDispatch(SLOTS["06:50"], env).init.body).inputs.early, "true");
});

test("any 2xx from GitHub is success", async () => {
  await dispatch(SLOTS["22:00"], env, async () => new Response(null, { status: 204 }));
  await dispatch(SLOTS["22:00"], env, async () => new Response("{}", { status: 200 }));
});

test("an error status is raised without exposing the token", async () => {
  await assert.rejects(
    dispatch(SLOTS["07:10"], env, async () => new Response("Resource not accessible", { status: 403 })),
    (e) => e.message.includes("summary-jpn-stock-market") && e.message.includes("HTTP 403") && !e.message.includes("test-token"),
  );
});
