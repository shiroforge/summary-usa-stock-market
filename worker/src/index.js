// Starts the `daily` GitHub Actions workflow on time. GitHub's own cron runs 2–6 hours late, while a
// workflow_dispatch starts right away (DECISIONS D-29). The workflow decides holidays and "already built".

// The last slot builds even with some data missing; earlier ones wait for complete data.
export const FINAL_CRON = "30 23 * * mon-fri";

export function buildDispatch(cron, env) {
  const inputs = { notify: "true", early: cron === FINAL_CRON ? "false" : "true" };
  return {
    url: `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`,
    init: {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "usmarket-dispatch",
        "X-GitHub-Api-Version": "2026-03-10",
      },
      body: JSON.stringify({ ref: env.GITHUB_REF, inputs }),
    },
  };
}

export async function dispatch(cron, env, fetchFn = fetch) {
  const { url, init } = buildDispatch(cron, env);
  const res = await fetchFn(url, init);
  if (!res.ok) {
    // Shows up in the Worker's logs. The workflow's own GitHub cron remains as the fallback.
    throw new Error(`dispatch failed for "${cron}": HTTP ${res.status} ${(await res.text()).slice(0, 300)}`);
  }
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatch(controller.cron, env));
  },
};
