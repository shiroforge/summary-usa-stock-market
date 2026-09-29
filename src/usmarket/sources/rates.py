"""US Treasury par yields from the Treasury's official daily CSV (home.treasury.gov). DECISIONS D-14.

Published after the close on each business day (usually by ~18:00 ET). Tenors with intraday OHLC on
yfinance (^IRX, ^FVX, ^TNX, ^TYX) use the normal quote path; this module covers 2Y (no yfinance series).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)

TREASURY_CSV = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
    "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)
HEADERS = {"User-Agent": "usmarket/0.1 (+https://github.com/)"}


def parse_treasury_csv(text: str) -> pd.DataFrame:
    """Rows: date (ascending). Columns: tenor labels as published ("2 Yr", "10 Yr", ...). Values in %."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if not rows or rows[0][0] != "Date":
        raise ValueError("Treasury CSV header not found")
    header = rows[0]
    data: dict[dt.date, dict[str, float]] = {}
    for r in rows[1:]:
        try:
            d = dt.datetime.strptime(r[0], "%m/%d/%Y").date()
        except (ValueError, IndexError):
            continue
        data[d] = {h: float(v) for h, v in zip(header[1:], r[1:], strict=False) if v not in ("", "N/A")}
    return pd.DataFrame.from_dict(data, orient="index").sort_index()


def _get_year(client: httpx.Client, year: int) -> pd.DataFrame:
    r = client.get(TREASURY_CSV.format(year=year), headers=HEADERS)
    r.raise_for_status()
    return parse_treasury_csv(r.text)


def load_treasury_yields(cache_dir: Path, *, today: dt.date, client: httpx.Client) -> pd.DataFrame:
    """Last year's curve (cached once) + this year's (fetched each run)."""
    frames = []
    prev_path = cache_dir / "rates" / f"treasury_{today.year - 1}.csv"
    if not prev_path.exists():
        try:
            r = client.get(TREASURY_CSV.format(year=today.year - 1), headers=HEADERS)
            r.raise_for_status()
            parse_treasury_csv(r.text)  # validate before caching
            prev_path.parent.mkdir(parents=True, exist_ok=True)
            prev_path.write_text(r.text, encoding="utf-8")
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Treasury %d fetch failed: %s", today.year - 1, e)
    if prev_path.exists():
        frames.append(parse_treasury_csv(prev_path.read_text(encoding="utf-8")))
    try:
        frames.append(_get_year(client, today.year))
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Treasury %d fetch failed: %s", today.year, e)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[df.index <= today]
