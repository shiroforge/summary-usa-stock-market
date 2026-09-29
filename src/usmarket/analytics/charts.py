"""Chart payload for the click-to-enlarge chart dialog (site/data/charts.json).

Series ids:  "NVDA" (stock/ETF ticker), "q:<quote key>", "s:<sector label>", "t:<theme key>".
Written only to the built site (not data/): it contains raw OHLC, see DECISIONS D-12 / D-18.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from typing import Any
from urllib.parse import quote

import pandas as pd

from usmarket.analytics import core
from usmarket.config import QuoteSpec, Settings, ThemeSpec
from usmarket.models import DailySummary, QuoteCategory
from usmarket.sources.master import Constituent

MAX_BARS = 250
TREASURY_PAGE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "TextView?type=daily_treasury_yield_curve"
)


def stock_links(code: str) -> dict[str, str]:
    tv = code.replace("-", ".")
    return {
        "株探": f"https://us.kabutan.jp/stocks/{tv}",
        "Yahoo! Finance": f"https://finance.yahoo.com/quote/{quote(code)}/",
        "Finviz": f"https://finviz.com/quote.ashx?t={quote(tv)}",
        "TradingView": f"https://www.tradingview.com/chart/?symbol={quote(tv)}",
    }


def quote_links(spec: QuoteSpec) -> dict[str, str]:
    if spec.links:
        return dict(spec.links)
    if spec.source == "treasury":
        return {"米財務省": TREASURY_PAGE}
    return {"Yahoo! Finance": f"https://finance.yahoo.com/quote/{quote(spec.ticker)}/"}


def _dates(idx: Iterable[dt.date]) -> dict[str, Any]:
    """Compact dates: first date + day offsets from the previous point (saves ~1MB over ISO strings)."""
    ds = list(idx)
    return {"t0": ds[0].isoformat(), "dt": [(b - a).days for a, b in pairwise(ds)]}


def _num(v: float, digits: int) -> float | int:
    r = round(v, digits)
    return int(r) if r == int(r) else r


def _nums(values: Iterable[Any], digits: int) -> list[float | int | None]:
    return [None if pd.isna(v) else _num(float(v), digits) for v in values]


def ohlc_series(
    bars: pd.DataFrame,
    name: str,
    *,
    digits: int = 2,
    links: Mapping[str, str],
    unit: str = "",
    note: str = "",
) -> dict[str, Any] | None:
    """bars: long rows for one symbol (date, open, high, low, close, volume)."""
    b = bars.dropna(subset=["close"]).sort_values("date").tail(MAX_BARS)
    if len(b) < 2:
        return None
    vol = b["volume"].fillna(0)
    out: dict[str, Any] = {
        "name": name,
        "kind": "ohlc",
        **_dates(b["date"]),
        "o": _nums(b["open"].fillna(b["close"]), digits),
        "h": _nums(b["high"].fillna(b["close"]), digits),
        "l": _nums(b["low"].fillna(b["close"]), digits),
        "c": _nums(b["close"], digits),
        "d": digits,  # display decimals
        "unit": unit,
        "note": note,
        "links": dict(links),
    }
    if float(vol.sum()) > 0:
        out["v"] = [int(v) for v in vol]
    return out


def line_series(
    s: pd.Series[float],
    name: str,
    *,
    digits: int = 2,
    unit: str = "",
    note: str = "",
    links: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    s = s.dropna().tail(MAX_BARS)
    if len(s) < 2:
        return None
    return {
        "name": name,
        "kind": "line",
        "unit": unit,
        "note": note,
        **_dates(s.index),
        "c": _nums(s, digits),
        "links": dict(links or {}),
    }


def cumulative_index(daily_pct: pd.Series[float]) -> pd.Series[float]:
    """Daily % changes -> index starting at 100 (first value treated as the base day)."""
    r = daily_pct.fillna(0.0).copy()
    r.iloc[0] = 0.0
    return 100 * (1 + r / 100).cumprod()


def build_chart_payload(
    summary: DailySummary,
    settings: Settings,
    *,
    themes: Sequence[ThemeSpec],
    bars: pd.DataFrame,
    master: list[Constituent],
    rets: pd.DataFrame,
    treasury: pd.DataFrame,
    extra_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Everything the chart dialog can open for this summary's page."""
    series: dict[str, dict[str, Any]] = {}
    by_symbol = {sym: g for sym, g in bars.groupby("symbol")}
    names = {c.code: c.name for c in master}
    for t in themes:
        for code, n in t.members.items():
            names.setdefault(code, n)
    for sector in settings.sectors:
        names.setdefault(sector.etf, f"{sector.name}セクターETF（{sector.etf}）")
    for code, n in (extra_names or {}).items():
        names.setdefault(code, n)

    # stocks & ETFs shown on the page
    codes: set[str] = set()
    for mv in (
        *summary.rankings.gainers,
        *summary.rankings.losers,
        *summary.rankings.turnover,
        *summary.rankings.volume_surge,
    ):
        codes.add(mv.code)
    for sec in summary.sectors:
        codes.update(m.code for m in (*sec.leaders, *sec.laggards))
    for th in summary.themes:
        codes.update(m.code for m in th.members)
    codes.update(d.code for d in (*summary.disclosures_session, *summary.disclosures_after))
    codes.update(sector.etf for sector in settings.sectors)
    for code in sorted(codes):
        g = by_symbol.get(code)
        if g is not None and (s := ohlc_series(g, names.get(code, code), links=stock_links(code))):
            series[code] = s

    # quotes
    for spec in settings.quotes:
        sid = f"q:{spec.key}"
        links = quote_links(spec)
        if spec.source == "treasury" and spec.ticker in treasury:
            series[sid] = line_series(treasury[spec.ticker], spec.name, digits=3, unit="%", links=links) or {}
        elif (g := by_symbol.get(spec.ticker)) is not None:
            if spec.category == QuoteCategory.RATES:  # yfinance yields have OHLC -> candles
                series[sid] = ohlc_series(g, spec.name, digits=3, unit="%", links=links) or {}
            else:
                digits = 4 if spec.category == QuoteCategory.FX and spec.unit != "円" else 2
                series[sid] = ohlc_series(g, spec.name, digits=digits, links=links) or {}

    # sector & theme indices (cumulative, base 100)
    for name, daily in core.sector_daily_returns(master, settings.sectors, rets).items():
        s = line_series(
            cumulative_index(daily.tail(MAX_BARS)),
            name,
            note="S&P500構成銘柄の指数ウエイト加重・起点=100",
        )
        if s:
            series[f"s:{name}"] = s
    for t in themes:
        cols = rets.columns.intersection(list(t.members))
        if cols.empty:
            continue
        daily = rets[cols].mean(axis=1, skipna=True).astype(float)
        s = line_series(cumulative_index(daily.tail(MAX_BARS)), t.name, note="構成銘柄の単純平均・起点=100")
        if s:
            series[f"t:{t.key}"] = s

    return {"asof": summary.date.isoformat(), "series": {k: v for k, v in series.items() if v}}
