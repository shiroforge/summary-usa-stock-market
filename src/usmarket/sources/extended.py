"""After-hours prices (16:00-20:00 ET) from yfinance 5-minute bars with extended hours. DECISIONS D-24.

Used only for the few stocks with a notable filing after the close, to show the market's first reaction.
"""

from __future__ import annotations

import datetime as dt
import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from usmarket.calendar import ET, session_close

log = logging.getLogger(__name__)

# (tickers, day) -> yfinance-style wide intraday frame (columns: (ticker, field); tz-aware index)
IntradayDownloader = Callable[[list[str], dt.date], pd.DataFrame]


@dataclass(frozen=True)
class AfterHours:
    price: float
    time: dt.datetime  # tz-aware (ET), start of the last 5-minute bar with a trade


def _yf_intraday(tickers: list[str], day: dt.date) -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(
            tickers,
            start=day.isoformat(),
            end=(day + dt.timedelta(days=1)).isoformat(),
            interval="5m",
            prepost=True,
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    return df if df is not None else pd.DataFrame()


def after_hours(
    tickers: list[str], day: dt.date, *, downloader: IntradayDownloader = _yf_intraday
) -> dict[str, AfterHours]:
    """Last traded price after the session close on `day`, per ticker (missing if none traded)."""
    if not tickers:
        return {}
    try:
        df = downloader(sorted(set(tickers)), day)
    except Exception as e:  # yfinance raises a variety of errors; this data is optional
        log.warning("after-hours download failed: %s", e)
        return {}
    if df.empty or not isinstance(df.columns, pd.MultiIndex):
        return {}
    close = session_close(day)
    out: dict[str, AfterHours] = {}
    for t in df.columns.get_level_values(0).unique():
        sub = df[t]
        if "Close" not in sub.columns:
            continue
        s = sub["Close"].dropna()
        if s.empty:
            continue
        idx = pd.DatetimeIndex(s.index)
        idx = idx.tz_localize(ET) if idx.tz is None else idx.tz_convert(ET)
        s.index = idx
        post = s[(s.index >= close) & (s.index < dt.datetime.combine(day, dt.time(20, 0), ET))]
        if post.empty:
            continue
        out[str(t)] = AfterHours(price=float(post.iloc[-1]), time=post.index[-1].to_pydatetime())
    return out
