import datetime as dt

import pandas as pd

from usmarket.calendar import ET
from usmarket.sources.extended import after_hours

DAY = dt.date(2026, 9, 25)


def intraday(tickers: list[str], day: dt.date) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp(2026, 9, 25, 15, 55, tz=ET),
            pd.Timestamp(2026, 9, 25, 16, 0, tz=ET),
            pd.Timestamp(2026, 9, 25, 19, 55, tz=ET),
            pd.Timestamp(2026, 9, 26, 4, 0, tz=ET),  # next pre-market: ignored
        ]
    )
    cols = pd.MultiIndex.from_product([["NVDA", "AAPL"], ["Open", "Close"]])
    return pd.DataFrame(
        [[1, 100.0, 1, 200.0], [1, 101.0, 1, None], [1, 103.5, 1, None], [1, 99.0, 1, None]],
        index=idx,
        columns=cols,
    )


def test_after_hours_last_trade() -> None:
    got = after_hours(["NVDA", "AAPL"], DAY, downloader=intraday)
    assert set(got) == {"NVDA"}  # AAPL had no trade after the close
    assert got["NVDA"].price == 103.5 and got["NVDA"].time == dt.datetime(2026, 9, 25, 19, 55, tzinfo=ET)


def test_after_hours_failures_are_empty() -> None:
    def boom(tickers: list[str], day: dt.date) -> pd.DataFrame:
        raise RuntimeError("rate limited")

    assert after_hours(["NVDA"], DAY, downloader=boom) == {}
    assert after_hours([], DAY, downloader=boom) == {}
