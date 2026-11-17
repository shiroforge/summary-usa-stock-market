// Starts the `daily` workflows of both note repos on time. GitHub's own cron runs hours late, while a
// workflow_dispatch starts right away (usmarket D-29, jpmarket D-28). Each workflow decides holidays and
// "already built" itself, so the Worker only keeps the clock.

const USA = "shiroforge/summary-usa-stock-market";
const JPN = "shiroforge/summary-jpn-stock-market";

// UTC "HH:MM" of each slot. The cron triggers in wrangler.toml must cover exactly these (tests check it).
// The last slot of each repo builds even with some data missing; earlier ones wait for complete data.
export const SLOTS = {
  "06:50": { repo: JPN, early: true }, // 15:50 JST
  "07:10": { repo: JPN, early: true }, // 16:10 JST
  "07:30": { repo: JPN, early: true }, // 16:30 JST
  "08:00": { repo: JPN, early: false }, // 17:00 JST
  "22:00": { repo: USA, early: true }, // 07:00 JST
  "22:30": { repo: USA, early: true }, // 07:30 JST
  "23:00": { repo: USA, early: true }, // 08:00 JST
  "23:30": { repo: USA, early: false }, // 08:30 JST
};

export function slotAt(scheduledTime) {
  const t = new Date(scheduledTime);
  const key = `${String(t.getUTCHours()).padStart(2, "0")}:${String(t.getUTCMinutes()).padStart(2, "0")}`;
  const slot = SLOTS[key];
  if (!slot) throw new Error(`no slot for ${key} UTC; wrangler.toml and SLOTS disagree`);
  return slot;
}

export function buildDispatch(slot, env) {
  return {
    url: `https://api.github.com/repos/${slot.repo}/actions/workflows/daily.yml/dispatches`,
    init: {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "usmarket-dispatch",
        "X-GitHub-Api-Version": "2026-03-10",
      },
      body: JSON.stringify({ ref: "main", inputs: { notify: "true", early: String(slot.early) } }),
    },
  };
}

export async function dispatch(slot, env, fetchFn = fetch) {
  const { url, init } = buildDispatch(slot, env);
  const res = await fetchFn(url, init);
  if (!res.ok) {
    // Shows up in the Worker's logs. Each workflow's own GitHub cron remains as the fallback.
    throw new Error(`dispatch to ${slot.repo} failed: HTTP ${res.status} ${(await res.text()).slice(0, 300)}`);
  }
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatch(slotAt(controller.scheduledTime), env));
  },
};
