"""Recent IPOs from Nasdaq's public IPO calendar API (covers NYSE and Nasdaq listings). DECISIONS D-25.

SPACs, units, warrants and rights are excluded (not operating-company IPOs), as are deals smaller than
`min_offer_usd` (micro-cap listings would dominate an equal-weighted theme).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

CALENDAR_URL = "https://api.nasdaq.com/api/ipo/calendar?date={year}-{month:02d}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; usmarket/0.1)", "Accept": "application/json"}
# blank-check companies: "... Acquisition Corp", "... Equity Partners VII", "... Corp IV"
SPAC_WORDS = re.compile(r"\b(Acquisition|SPAC|Merger Corp)\b|\s[IVX]{1,4}$", re.I)


@dataclass(frozen=True)
class Listing:
    date: dt.date
    code: str
    name: str
    market: str
    offer_usd: float | None


def _money(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(re.sub(r"[$,\s]", "", s))
    except ValueError:
        return None


def _short(name: str) -> str:
    name = re.sub(r"/[A-Z]{2}/$", "", name).strip()  # EDGAR-style state suffix: "ITG, Inc./DE/"
    if name.isupper():
        name = name.title()
    prev = None
    while prev != name:
        prev = name
        name = re.sub(
            r"[,\s]+(Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited|plc|PLC|LLC|N\.V\.|S\.p\.A\.|Co\.?)$", "", name
        ).strip()
    return name


def parse_calendar(payload: dict[str, Any]) -> list[Listing]:
    """Priced deals from one month of the calendar."""
    rows = ((payload.get("data") or {}).get("priced") or {}).get("rows") or []
    out = []
    for r in rows:
        code = str(r.get("proposedTickerSymbol") or "").strip().upper()
        name = str(r.get("companyName") or "").strip()
        try:
            day = dt.datetime.strptime(str(r.get("pricedDate")), "%m/%d/%Y").date()
        except ValueError:
            continue
        if not re.fullmatch(r"[A-Z]{1,5}", code):
            continue
        out.append(
            Listing(
                date=day,
                code=code,
                name=_short(name),
                market=str(r.get("proposedExchange") or ""),
                offer_usd=_money(r.get("dollarValueOfSharesOffered")),
            )
        )
    return out


def is_operating_ipo(x: Listing, min_offer_usd: float) -> bool:
    if SPAC_WORDS.search(x.name.strip()):
        return False
    if len(x.code) == 5 and x.code[-1] in "UWR":  # units / warrants / rights
        return False
    return x.offer_usd is not None and x.offer_usd >= min_offer_usd


def _month_payload(client: httpx.Client, cache_dir: Path, year: int, month: int, today: dt.date) -> Any:
    """Past months are immutable -> cached forever; the current month is fetched each run."""
    path = cache_dir / "ipo" / f"{year}-{month:02d}.json"
    current = (year, month) == (today.year, today.month)
    if path.exists() and not current:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        r = client.get(CALENDAR_URL.format(year=year, month=month), headers=HEADERS)
        r.raise_for_status()
        payload = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Nasdaq IPO calendar %d-%02d failed: %s", year, month, e)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def load_recent_ipos(
    cache_dir: Path,
    *,
    today: dt.date,
    client: httpx.Client,
    window_days: int = 365,
    min_offer_usd: float = 1e8,
) -> list[Listing] | None:
    """Operating-company IPOs priced within `window_days` up to `today` (newest first).

    None if the current month could not be read at all.
    """
    start = today - dt.timedelta(days=window_days)
    months = []
    y, m = start.year, start.month
    while (y, m) <= (today.year, today.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    listings: list[Listing] = []
    for y, m in months:
        payload = _month_payload(client, cache_dir, y, m, today)
        if payload is None and (y, m) == (today.year, today.month):
            return None
        if payload:
            listings.extend(parse_calendar(payload))
    seen: set[str] = set()
    out = []
    for x in sorted(listings, key=lambda x: x.date, reverse=True):
        if x.code in seen or not (start <= x.date <= today) or not is_operating_ipo(x, min_offer_usd):
            continue
        seen.add(x.code)
        out.append(x)
    return out
