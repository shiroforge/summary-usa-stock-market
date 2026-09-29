"""Market data source interface. yfinance now, a paid feed later — analytics depend only on this."""

from __future__ import annotations

import datetime as dt
from typing import Protocol

import pandas as pd


class MarketDataSource(Protocol):
    name: str

    def daily_bars(self, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        """Daily OHLCV in long format.

        Columns: symbol (str), date (datetime.date), open, high, low, close, volume (float).
        `symbols` use yfinance-style tickers ("AAPL", "BRK-B", "^GSPC", "USDJPY=X").
        Missing symbols are omitted, never raised.
        """
        ...


class Constituent(Protocol):
    code: str
    name: str
    sector: str
    weight_pct: float
