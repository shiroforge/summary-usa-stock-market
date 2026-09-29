"""Local daily-bar cache (parquet) so each run only fetches the last few days (DECISIONS D-05).

Lives in .cache/prices/ (not committed; persisted across CI runs with actions/cache).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from usmarket.sources.base import MarketDataSource
from usmarket.sources.yfinance_src import BAR_COLUMNS

RETENTION_DAYS = 420  # 52-week highs/lows and the 200-day average need ~1 year
BOOTSTRAP_DAYS = 400  # first fetch: a year of history (+ margin)
REFETCH_OVERLAP_DAYS = 7  # re-pull recent days to pick up late corrections


class PriceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._df: pd.DataFrame | None = None

    @property
    def bars(self) -> pd.DataFrame:
        if self._df is None:
            self._df = pd.read_parquet(self.path) if self.path.exists() else pd.DataFrame(columns=BAR_COLUMNS)
            if not self._df.empty:
                self._df["date"] = pd.to_datetime(self._df["date"]).dt.date
        return self._df

    def upsert(self, new: pd.DataFrame, *, today: dt.date) -> None:
        if new.empty:
            return
        df = pd.concat([self.bars, new[BAR_COLUMNS]], ignore_index=True)
        df = df.drop_duplicates(subset=["symbol", "date"], keep="last")
        df = df[df["date"] >= today - dt.timedelta(days=RETENTION_DAYS)]
        self._df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.bars.to_parquet(self.path, index=False)

    def last_date(self, symbol: str) -> dt.date | None:
        s = self.bars.loc[self.bars["symbol"] == symbol, "date"]
        return None if s.empty else max(s)

    def update(self, source: MarketDataSource, symbols: list[str], target: dt.date) -> list[str]:
        """Fetch what is missing for `symbols` up to `target`. Returns symbols still lacking `target`."""
        bootstrap_start = target - dt.timedelta(days=BOOTSTRAP_DAYS)
        last = self.bars.groupby("symbol")["date"].max().to_dict() if not self.bars.empty else {}
        known = [s for s in symbols if s in last and last[s] >= bootstrap_start]
        fresh = [s for s in symbols if s not in known]
        if known:
            start = min(last[s] for s in known) - dt.timedelta(days=REFETCH_OVERLAP_DAYS)
            self.upsert(source.daily_bars(known, max(start, bootstrap_start), target), today=target)
        if fresh:
            self.upsert(source.daily_bars(fresh, bootstrap_start, target), today=target)
        have = set(self.bars.loc[self.bars["date"] == target, "symbol"])
        return [s for s in symbols if s not in have]

    def closes(self, symbols: list[str] | None = None, end: dt.date | None = None) -> pd.DataFrame:
        """Wide close matrix: index=date (ascending), columns=symbol."""
        df = self.bars
        if symbols is not None:
            df = df[df["symbol"].isin(symbols)]
        if end is not None:
            df = df[df["date"] <= end]
        return df.pivot(index="date", columns="symbol", values="close").sort_index()

    def volumes(self, symbols: list[str] | None = None, end: dt.date | None = None) -> pd.DataFrame:
        df = self.bars
        if symbols is not None:
            df = df[df["symbol"].isin(symbols)]
        if end is not None:
            df = df[df["date"] <= end]
        return df.pivot(index="date", columns="symbol", values="volume").sort_index()
