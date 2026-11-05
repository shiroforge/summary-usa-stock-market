"""The external trigger's slots must land after the close and before Tokyo's open, in both DST regimes."""

from __future__ import annotations

import datetime as dt
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from usmarket.calendar import ET, JST

ROOT = Path(__file__).resolve().parent.parent
WINTER = dt.date(2026, 11, 5)
SUMMER = dt.date(2026, 7, 8)
YAHOO_GAP_STARTS = dt.time(19, 57)  # the last time individual stocks' bars were seen before the gap (D-29)


def worker_crons() -> list[str]:
    config = tomllib.loads((ROOT / "worker" / "wrangler.toml").read_text(encoding="utf-8"))
    crons: list[str] = config["triggers"]["crons"]
    return crons


def workflow_dispatch_inputs() -> dict[str, Any]:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))
    inputs: dict[str, Any] = workflow[True]["workflow_dispatch"]["inputs"]  # YAML 1.1 reads `on` as True
    return inputs


@pytest.mark.parametrize("day", [WINTER, SUMMER])
def test_every_slot_is_between_the_close_and_the_yahoo_gap(day: dt.date) -> None:
    for cron in worker_crons():
        minute, hour, *_ = cron.split()
        at = dt.datetime.combine(day, dt.time(int(hour), int(minute)), dt.UTC)
        et = at.astimezone(ET).time()
        assert dt.time(16, 0) < et < YAHOO_GAP_STARTS, cron


@pytest.mark.parametrize("day", [WINTER, SUMMER])
def test_every_slot_is_before_tokyo_opens(day: dt.date) -> None:
    for cron in worker_crons():
        minute, hour, *_ = cron.split()
        at = dt.datetime.combine(day, dt.time(int(hour), int(minute)), dt.UTC)
        assert at.astimezone(JST).time() < dt.time(9, 0), cron


def test_weekdays_are_named() -> None:
    # Cloudflare numbers 1 = Sunday, so "1-5" would run Sunday to Thursday
    assert all(cron.split()[4] == "mon-fri" for cron in worker_crons())


def test_the_worker_final_slot_exists() -> None:
    source = (ROOT / "worker" / "src" / "index.js").read_text(encoding="utf-8")
    finals = [cron for cron in worker_crons() if f'FINAL_CRON = "{cron}"' in source]
    assert finals == [worker_crons()[-1]]


def test_the_workflow_accepts_what_the_worker_sends() -> None:
    inputs = workflow_dispatch_inputs()
    assert inputs["early"]["default"] is False  # manual runs keep building regardless
    assert inputs["notify"]["default"] is True
