"""The external trigger's slots (worker/) must land after each market's close and before the deadlines."""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from usmarket.calendar import ET, JST

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "worker"
WINTER = dt.date(2026, 11, 5)
SUMMER = dt.date(2026, 7, 8)
YAHOO_GAP_STARTS = dt.time(19, 57)  # the last time US stocks' bars were seen before the gap (D-29)
USA = "shiroforge/summary-usa-stock-market"
JPN = "shiroforge/summary-jpn-stock-market"


def crons() -> list[str]:
    config = tomllib.loads((WORKER / "wrangler.toml").read_text(encoding="utf-8"))
    out: list[str] = config["triggers"]["crons"]
    return out


def _field(spec: str) -> list[int]:
    values: list[int] = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        values.extend(range(int(lo), int(hi or lo) + 1))
    return values


def fired_times() -> list[str]:
    """UTC "HH:MM" of every firing (only minute/hour lists and ranges are used)."""
    return sorted(
        f"{h:02d}:{m:02d}"
        for cron in crons()
        for h in _field(cron.split()[1])
        for m in _field(cron.split()[0])
    )


def slots() -> dict[str, tuple[str, bool]]:
    """SLOTS in worker/src/index.js: UTC "HH:MM" -> (repo, early)."""
    source = (WORKER / "src" / "index.js").read_text(encoding="utf-8")
    repos = {"USA": USA, "JPN": JPN}
    found = re.findall(r'"(\d\d:\d\d)": \{ repo: (USA|JPN), early: (true|false) \}', source)
    return {t: (repos[r], e == "true") for t, r, e in found}


def at(day: dt.date, hhmm: str) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), dt.UTC)


def test_triggers_and_slots_agree() -> None:
    assert len(crons()) <= 5  # Workers Free plan: 5 Cron Triggers per account
    assert fired_times() == sorted(slots())


def test_weekdays_are_named() -> None:
    # Cloudflare numbers 1 = Sunday, so "1-5" would run Sunday to Thursday
    assert all(cron.split()[2:] == ["*", "*", "mon-fri"] for cron in crons())


@pytest.mark.parametrize("day", [WINTER, SUMMER])
def test_usa_slots_are_between_the_close_and_the_yahoo_gap_and_before_tokyo_opens(day: dt.date) -> None:
    for t, (repo, _) in slots().items():
        if repo == USA:
            assert dt.time(16, 0) < at(day, t).astimezone(ET).time() < YAHOO_GAP_STARTS, t
            assert at(day, t).astimezone(JST).time() < dt.time(9, 0), t


def test_jpn_slots_are_after_the_close_and_around_four() -> None:
    for t, (repo, _) in slots().items():
        if repo == JPN:
            assert dt.time(15, 45) <= at(WINTER, t).astimezone(JST).time() <= dt.time(17, 0), t


def test_each_repo_ends_with_one_final_slot() -> None:
    for repo in (USA, JPN):
        mine = [early for t, (r, early) in sorted(slots().items()) if r == repo]
        assert len(mine) >= 2 and mine[-1] is False and all(mine[:-1]), repo


def test_the_workflow_accepts_what_the_worker_sends() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))
    inputs: dict[str, Any] = workflow[True]["workflow_dispatch"]["inputs"]  # YAML 1.1 reads `on` as True
    assert inputs["early"]["default"] is False  # manual runs keep building regardless
    assert inputs["notify"]["default"] is True
