"""yfinance-backed MarketDataSource with chunking, gap re-fetch, and 429 backoff (DECISIONS D-05)."""

from __future__ import annotations

import datetime as dt
import logging
import time
import warnings
from collections.abc import Callable

import pandas as pd

log = logging.getLogger(__name__)

BAR_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]

# (tickers, start, end_exclusive) -> yfinance-style wide frame (columns: (ticker, field))
Downloader = Callable[[list[str], dt.date, dt.date], pd.DataFrame]


def to_yf(symbol: str) -> str:
    """Symbols are stored in yfinance form already (share classes as "BRK-B", see master.to_symbol)."""
    return symbol


def _yf_download(tickers: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(
            tickers,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    return df if df is not None else pd.DataFrame()


def _is_rate_limited(exc: BaseException) -> bool:
    return "RateLimit" in type(exc).__name__ or "Too Many Requests" in str(exc)


def wide_to_long(df: pd.DataFrame, yf_to_symbol: dict[str, str]) -> pd.DataFrame:
    """Convert yfinance's (ticker, field) columns into long bars, dropping rows without a close."""
    if df.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    frames = []
    if not isinstance(df.columns, pd.MultiIndex):
        return pd.DataFrame(columns=BAR_COLUMNS)
    for t in df.columns.get_level_values(0).unique():
        sub = df[t]
        if "Close" not in sub.columns:
            continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "symbol": yf_to_symbol.get(str(t), str(t)),
                    "date": [pd.Timestamp(i).date() for i in sub.index],
                    "open": sub["Open"].astype(float).to_numpy(),
                    "high": sub["High"].astype(float).to_numpy(),
                    "low": sub["Low"].astype(float).to_numpy(),
                    "close": sub["Close"].astype(float).to_numpy(),
                    "volume": sub["Volume"].astype(float).fillna(0).to_numpy(),
                }
            )
        )
    if not frames:
        return pd.DataFrame(columns=BAR_COLUMNS)
    return pd.concat(frames, ignore_index=True)


class YFinanceSource:
    name = "yfinance"

    def __init__(
        self,
        *,
        chunk_size: int = 100,
        pause_sec: float = 1.0,
        max_retries: int = 3,
        downloader: Downloader = _yf_download,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.chunk_size = chunk_size
        self.pause_sec = pause_sec
        self.max_retries = max_retries
        self._download = downloader
        self._sleep = sleep

    def daily_bars(self, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        """Bars for [start, end] inclusive. Symbols with no data are omitted."""
        mapping = {to_yf(s): s for s in dict.fromkeys(symbols)}
        pending = list(mapping)
        got: list[pd.DataFrame] = []
        for attempt in range(self.max_retries + 1):
            if not pending:
                break
            if attempt:
                wait = self.pause_sec * (4**attempt)
                log.info(
                    "re-fetching %d missing symbols after %.0fs (attempt %d)", len(pending), wait, attempt
                )
                self._sleep(wait)
            missing: list[str] = []
            for i in range(0, len(pending), self.chunk_size):
                chunk = pending[i : i + self.chunk_size]
                if i:
                    self._sleep(self.pause_sec)
                try:
                    wide = self._download(chunk, start, end + dt.timedelta(days=1))
                except Exception as e:
                    if not _is_rate_limited(e):
                        raise
                    log.warning("rate limited on chunk of %d: %s", len(chunk), e)
                    missing.extend(chunk)
                    continue
                bars = wide_to_long(wide, mapping)
                got.append(bars)
                have = set(bars["symbol"])
                missing.extend(t for t in chunk if mapping[t] not in have)
            pending = missing
        if pending:
            log.warning("no data for %d symbols: %s", len(pending), [mapping[t] for t in pending[:20]])
        if not got:
            return pd.DataFrame(columns=BAR_COLUMNS)
        out = pd.concat(got, ignore_index=True)
        return out[(out["date"] >= start) & (out["date"] <= end)].reset_index(drop=True)
