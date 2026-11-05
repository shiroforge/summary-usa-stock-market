"""Measure when Yahoo's daily bars carry the session's close (read-only: no site, no notification).

Fetches the same way as the pipeline (YFinanceSource, daily bars) for the top-weight S&P 500 names and
appends one JSON line per sample, so the delivery schedule can be chosen from evidence (DECISIONS D-29).

    uv run python scripts/probe_close.py --once
    uv run python scripts/probe_close.py --date 2026-11-05 --out probe.jsonl --at 16:05 --at 17:00
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import time
from pathlib import Path

import httpx

from usmarket.calendar import ET, latest_trading_day
from usmarket.config import Settings
from usmarket.sources.master import load_master
from usmarket.sources.yfinance_src import YFinanceSource

INDEX = "^GSPC"
SAMPLE_SIZE = 50


def top_weights(n: int) -> dict[str, float]:
    settings = Settings()
    today = dt.datetime.now(dt.UTC).date()
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as http:
        master = load_master(settings.cache_dir, today=today, client=http, max_age_days=30)
    ranked = sorted(master.constituents, key=lambda c: c.weight_pct, reverse=True)[:n]
    return {c.code: c.weight_pct for c in ranked}


def sample(target: dt.date, weights: dict[str, float]) -> dict[str, object]:
    source = YFinanceSource(chunk_size=100, pause_sec=1.0, max_retries=0)
    start = target - dt.timedelta(days=7)
    try:
        bars = source.daily_bars([*weights, INDEX], start, target)
    except Exception as e:  # keep sampling through a transient failure
        return {"error": f"{type(e).__name__}: {e}"}
    day = bars[bars["date"] == target]
    closes = {str(s): float(c) for s, c in zip(day["symbol"], day["close"], strict=True)}
    have = [s for s in weights if s in closes]
    return {
        "index_has_close": INDEX in closes,
        "symbols_with_close": len(have),
        "symbols_total": len(weights),
        "weight_coverage_pct": round(sum(weights[s] for s in have) / sum(weights.values()) * 100, 1),
        "closes": closes,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", help="Session YYYY-MM-DD (default: latest closed session)")
    p.add_argument("--out", type=Path, help="Append JSON lines here (default: stdout only)")
    p.add_argument("--at", action="append", default=[], help="ET time HH:MM on --date (repeatable)")
    p.add_argument("--once", action="store_true", help="Take one sample now and exit")
    args = p.parse_args()
    logging.basicConfig(level=logging.ERROR)

    now = dt.datetime.now(dt.UTC)
    target = dt.date.fromisoformat(args.date) if args.date else latest_trading_day(now)
    weights = top_weights(SAMPLE_SIZE)
    times = [dt.datetime.combine(target, dt.time.fromisoformat(t), ET) for t in args.at]
    for when in [dt.datetime.now(ET)] if args.once else sorted(times):
        wait = (when - dt.datetime.now(ET)).total_seconds()
        if wait < 0 and not args.once:
            continue
        time.sleep(max(wait, 0))
        result = {"target": target.isoformat(), "at_et": dt.datetime.now(ET).isoformat(timespec="seconds")}
        result |= sample(target, weights)
        line = json.dumps(result, ensure_ascii=False)
        print(line if args.out is None else {k: v for k, v in result.items() if k != "closes"}, flush=True)
        if args.out:
            with args.out.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


if __name__ == "__main__":
    main()
