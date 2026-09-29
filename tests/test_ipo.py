import datetime as dt
from pathlib import Path
from typing import Any

import httpx

from usmarket.sources.ipo import Listing, is_operating_ipo, load_recent_ipos, parse_calendar


def payload(rows: list[tuple[str, str, str, str]]) -> dict[str, Any]:
    return {
        "data": {
            "priced": {
                "rows": [
                    {
                        "proposedTickerSymbol": sym,
                        "companyName": name,
                        "proposedExchange": "NASDAQ Global Select",
                        "pricedDate": day,
                        "dollarValueOfSharesOffered": amount,
                    }
                    for sym, name, day, amount in rows
                ]
            }
        }
    }


SEPT = payload(
    [
        ("ADRX", "ADARx Pharmaceuticals, Inc.", "9/25/2026", "$446,250,000"),
        ("BRRKU", "Bluerock Acquisition Corp. II", "9/25/2026", "$150,000,000"),  # SPAC units
        ("RSCH", "Research Alliance Corp IV", "9/20/2026", "$200,000,000"),  # blank check
        ("TINY", "Tiny Co", "9/10/2026", "$8,000,000"),  # too small
        ("NOAM", "No Amount Inc.", "9/3/2026", ""),
        ("LATE", "Late Inc.", "9/29/2026", "$500,000,000"),  # after the target date
    ]
)
OLD = payload([("SPCX", "SPACE EXPLORATION TECHNOLOGIES CORP", "6/12/2026", "$25,000,000,000")])


def test_parse_calendar() -> None:
    rows = parse_calendar(SEPT)
    assert rows[0] == Listing(
        dt.date(2026, 9, 25), "ADRX", "ADARx Pharmaceuticals", "NASDAQ Global Select", 446250000.0
    )
    assert parse_calendar({"data": None}) == []


def test_operating_ipo_filter() -> None:
    names = {x.code: is_operating_ipo(x, 1e8) for x in parse_calendar(SEPT)}
    assert names == {"ADRX": True, "BRRKU": False, "RSCH": False, "TINY": False, "NOAM": False, "LATE": True}


def test_load_recent(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "date=2026-09" in str(req.url):
            return httpx.Response(200, json=SEPT)
        if "date=2026-06" in str(req.url):
            return httpx.Response(200, json=OLD)
        return httpx.Response(200, json={"data": {"priced": {"rows": []}}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    got = load_recent_ipos(tmp_path, today=dt.date(2026, 9, 28), client=client, window_days=120)
    assert got is not None and [x.code for x in got] == ["ADRX", "SPCX"]
    assert got[1].name == "Space Exploration Technologies"
    assert len(calls) == 5  # 2026-05 .. 2026-09
    load_recent_ipos(tmp_path, today=dt.date(2026, 9, 28), client=client, window_days=120)
    assert len(calls) == 6  # past months cached; only the current month is fetched again


def test_current_month_unavailable(tmp_path: Path) -> None:
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert load_recent_ipos(tmp_path, today=dt.date(2026, 9, 28), client=down) is None
