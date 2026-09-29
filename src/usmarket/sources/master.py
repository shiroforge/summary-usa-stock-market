"""S&P 500 constituent master: index weights from the SPY daily holdings file (State Street) and GICS
sectors / company names / CIKs from Wikipedia's "List of S&P 500 companies". DECISIONS D-04.

Both are cached under .cache/master/ (not committed) and refreshed weekly; a failed refresh falls back to
the cached copy.
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)

SPY_URL = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/"
    "holdings-daily-us-en-spy.xlsx"
)
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "Mozilla/5.0 (compatible; usmarket/0.1; +https://github.com/)"


@dataclass(frozen=True)
class Constituent:
    code: str  # yfinance form: "BRK-B"
    name: str
    sector: str  # GICS sector (English, as published)
    industry: str  # GICS sub-industry
    weight_pct: float  # share of the S&P 500 (SPY holdings weight)
    cik: str = ""  # SEC Central Index Key (zero-padded to 10 digits)


@dataclass(frozen=True)
class Master:
    as_of: dt.date
    constituents: list[Constituent]

    def by_code(self) -> dict[str, Constituent]:
        return {c.code: c for c in self.constituents}


def to_symbol(ticker: str) -> str:
    """Published tickers use a dot for share classes ("BRK.B"); yfinance uses a dash."""
    return ticker.strip().upper().replace(".", "-")


_SUFFIX = re.compile(
    r"[,\s]+(&\s*Co\.?|Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|plc|PLC|N\.V\.|S\.A\.|Holdings?)$"
)


def short_name(name: str) -> str:
    """'Apple Inc.' -> 'Apple', 'Alphabet Inc. (Class A)' -> 'Alphabet (Class A)',
    'Lilly (Eli)' -> 'Eli Lilly', 'Coca-Cola Company (The)' -> 'Coca-Cola'."""
    m = re.match(r"^(.*?)\s*(\(.*\))?$", name.strip())
    base, paren = (m.group(1), m.group(2)) if m else (name, None)
    prev = None
    while prev != base:
        prev, base = base, _SUFFIX.sub("", base).strip()
    if not paren or paren == "(The)":
        return base
    if paren.startswith("(Class") or paren.startswith("(Series"):
        return f"{base} {paren}"
    return f"{paren[1:-1]} {base}"


def parse_spy_holdings(raw: bytes) -> tuple[dt.date, dict[str, float]]:
    """(as-of date, {symbol: weight %}) from SSGA's holdings-daily xlsx."""
    df = pd.read_excel(io.BytesIO(raw), header=None)
    as_of: dt.date | None = None
    header_row: int | None = None
    for i, r in df.iterrows():
        cells = [str(v) for v in r.tolist() if not pd.isna(v)]
        text = " ".join(cells)
        if as_of is None and (m := re.search(r"As of (\d{1,2}-[A-Za-z]{3}-\d{4})", text)):
            as_of = dt.datetime.strptime(m.group(1), "%d-%b-%Y").date()
        if "Ticker" in cells and "Weight" in cells:
            header_row = int(str(i))
            break
    if header_row is None or as_of is None:
        raise ValueError("SPY holdings: header or date not found")
    cols = [str(v) for v in df.iloc[header_row].tolist()]
    body = df.iloc[header_row + 1 :]
    ti, wi = cols.index("Ticker"), cols.index("Weight")
    weights: dict[str, float] = {}
    for _, r in body.iterrows():
        t, w = r.iloc[ti], r.iloc[wi]
        if pd.isna(t) or pd.isna(w) or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,6}", str(t).strip()):
            continue
        try:
            weights[to_symbol(str(t))] = float(w)
        except ValueError:
            continue
    if len(weights) < 400:
        raise ValueError(f"SPY holdings: only {len(weights)} rows")
    return as_of, weights


def parse_wiki_list(html: str) -> pd.DataFrame:
    """Columns: code, name, sector, industry, cik."""
    tables = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})
    t = tables[0]
    out = pd.DataFrame(
        {
            "code": t["Symbol"].astype(str).map(to_symbol),
            "name": t["Security"].astype(str).map(short_name),
            "sector": t["GICS Sector"].astype(str),
            "industry": t["GICS Sub-Industry"].astype(str),
            "cik": t["CIK"].map(lambda v: f"{int(v):010d}" if not pd.isna(v) else ""),
        }
    )
    if len(out) < 400:
        raise ValueError(f"Wikipedia list: only {len(out)} rows")
    return out


def combine(as_of: dt.date, weights: dict[str, float], wiki: pd.DataFrame) -> Master:
    rows = []
    for r in wiki.itertuples(index=False):
        w = weights.get(str(r.code))
        if w is None:
            log.info("no SPY weight for %s; skipped", r.code)
            continue
        rows.append(
            Constituent(
                code=str(r.code),
                name=str(r.name),
                sector=str(r.sector),
                industry=str(r.industry),
                weight_pct=w,
                cik=str(r.cik),
            )
        )
    return Master(as_of=as_of, constituents=rows)


def _fetch(client: httpx.Client, url: str, path: Path, max_age_days: int, today: dt.date) -> bytes | None:
    """Cached bytes, refreshed when older than max_age_days (the old copy is kept if the refresh fails)."""
    fresh = path.exists() and dt.date.fromtimestamp(path.stat().st_mtime) > today - dt.timedelta(
        days=max_age_days
    )
    if not fresh:
        try:
            r = client.get(url, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(path)
        except httpx.HTTPError as e:
            log.warning("master refresh %s failed: %s", url, e)
    return path.read_bytes() if path.exists() else None


def load_master(cache_dir: Path, *, today: dt.date, client: httpx.Client, max_age_days: int = 7) -> Master:
    d = cache_dir / "master"
    spy = _fetch(client, SPY_URL, d / "spy_holdings.xlsx", max_age_days, today)
    wiki = _fetch(client, WIKI_URL, d / "sp500_wikipedia.html", max_age_days, today)
    if spy is None or wiki is None:
        raise RuntimeError("S&P 500 master unavailable (no download and no cache)")
    as_of, weights = parse_spy_holdings(spy)
    return combine(as_of, weights, parse_wiki_list(wiki.decode("utf-8", errors="replace")))
