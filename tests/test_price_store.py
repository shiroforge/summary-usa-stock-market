import datetime as dt
from pathlib import Path

import pandas as pd

from usmarket.sources.price_store import PriceStore

D = dt.date


class FakeSource:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dt.date, dt.date]] = []

    def daily_bars(self, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        self.calls.append((list(symbols), start, end))
        rows = []
        for s in symbols:
            d = start
            while d <= end:
                if d.weekday() < 5:
                    rows.append(
                        {
                            "symbol": s,
                            "date": d,
                            "open": 1.0,
                            "high": 1.0,
                            "low": 1.0,
                            "close": 100.0 + d.day,
                            "volume": 10.0,
                        }
                    )
                d += dt.timedelta(days=1)
        return pd.DataFrame(rows)


def test_bootstrap_then_incremental(tmp_path: Path) -> None:
    src = FakeSource()
    store = PriceStore(tmp_path / "bars.parquet")
    missing = store.update(src, ["AAPL", "MSFT"], D(2026, 9, 24))
    assert missing == []
    assert src.calls[0][1] == D(2025, 8, 20)  # 400 days back: a year of history for 52-week stats
    store.save()

    store2 = PriceStore(tmp_path / "bars.parquet")
    src2 = FakeSource()
    store2.update(src2, ["AAPL", "MSFT", "NVDA"], D(2026, 9, 25))
    (known, start, _), (fresh, fresh_start, _) = src2.calls
    assert known == ["AAPL", "MSFT"] and start == D(2026, 9, 17)
    assert fresh == ["NVDA"] and fresh_start == D(2025, 8, 21)
    closes = store2.closes(["AAPL"])
    assert closes.index[-1] == D(2026, 9, 25)
    assert not closes.index.duplicated().any()


def test_reports_missing_target(tmp_path: Path) -> None:
    store = PriceStore(tmp_path / "bars.parquet")
    assert store.update(FakeSource(), ["AAPL"], D(2026, 9, 26)) == ["AAPL"]  # Saturday: no bar
