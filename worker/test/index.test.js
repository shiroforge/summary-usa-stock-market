import assert from "node:assert/strict";
import { test } from "node:test";

import { buildDispatch, dispatch, FINAL_CRON } from "../src/index.js";

const env = {
  GITHUB_REPO: "owner/repo",
  GITHUB_WORKFLOW: "daily.yml",
  GITHUB_REF: "main",
  GITHUB_TOKEN: "test-token",
};

test("early slots wait for complete data and notify", () => {
  const { url, init } = buildDispatch("0 22 * * mon-fri", env);
  assert.equal(url, "https://api.github.com/repos/owner/repo/actions/workflows/daily.yml/dispatches");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, "Bearer test-token");
  assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { notify: "true", early: "true" } });
});

test("the final slot builds regardless", () => {
  const { init } = buildDispatch(FINAL_CRON, env);
  assert.equal(JSON.parse(init.body).inputs.early, "false");
});

test("any 2xx from GitHub is success", async () => {
  await dispatch(FINAL_CRON, env, async () => new Response(null, { status: 204 }));
  await dispatch(FINAL_CRON, env, async () => new Response("{}", { status: 200 }));
});

test("an error status is raised without exposing the token", async () => {
  await assert.rejects(
    dispatch(FINAL_CRON, env, async () => new Response("Bad credentials", { status: 401 })),
    (e) => e.message.includes("HTTP 401") && e.message.includes("Bad credentials") && !e.message.includes("test-token"),
  );
});
