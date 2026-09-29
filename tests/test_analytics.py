import datetime as dt

import numpy as np
import pandas as pd
import pytest

from usmarket.analytics.core import (
    breadth,
    build_quote,
    rankings,
    returns_pct,
    sector_history,
    sector_perf,
    stock_move,
    theme_history,
    theme_perf,
)
from usmarket.config import QuoteSpec, SectorSpec, ThemeSpec
from usmarket.models import QuoteCategory, StockMove
from usmarket.sources.master import Constituent

D = dt.date
DATES = [D(2026, 9, 24), D(2026, 9, 25)]
T = DATES[-1]

MASTER = [
    Constituent("JPM", "JPMorgan", "Financials", "Banks", 3.0),
    Constituent("BAC", "Bank of America", "Financials", "Banks", 1.0),
    Constituent("NVDA", "Nvidia", "Information Technology", "Semis", 2.0),
    Constituent("AMD", "AMD", "Information Technology", "Semis", 2.0),
    Constituent("ZZZ", "Unknown", "Not A Sector", "?", 1.0),  # ignored by sector analytics
]
SPECS = [
    SectorSpec(key="Information Technology", name="情報技術", etf="XLK"),
    SectorSpec(key="Financials", name="金融", etf="XLF"),
]


def frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    closes = pd.DataFrame(
        {"JPM": [100, 110], "BAC": [100, 90], "NVDA": [100, 101], "AMD": [100, np.nan], "XLF": [50, 51]},
        index=DATES,
        dtype=float,
    )
    vols = pd.DataFrame({c: [1e7, 1e7] for c in closes.columns}, index=DATES)
    return closes, returns_pct(closes), vols


def test_returns_use_previous_available_close() -> None:
    c = pd.DataFrame({"x": [100.0, np.nan, 110.0]}, index=[D(2026, 9, 1), D(2026, 9, 2), D(2026, 9, 3)])
    r = returns_pct(c)
    assert r.at[D(2026, 9, 3), "x"] == pytest.approx(10.0)
    assert pd.isna(r.at[D(2026, 9, 2), "x"])


def test_build_quote() -> None:
    idx = [D(2026, 9, 1) + dt.timedelta(days=i) for i in range(25)]
    s = pd.Series([100.0 + i for i in range(25)], index=idx)
    spec = QuoteSpec(key="k", name="N", ticker="^X", category=QuoteCategory.US_INDEX)
    q = build_quote(spec, s, D(2026, 9, 25))
    assert q is not None
    assert q.close == 124 and q.change == 1 and q.change_pct == pytest.approx(0.81)
    assert q.change_5d_pct == pytest.approx((124 / 119 - 1) * 100, abs=0.01)
    assert q.change_20d_pct == pytest.approx((124 / 104 - 1) * 100, abs=0.01)
    assert len(q.spark) == 20 and q.as_of == D(2026, 9, 25)
    # foreign quote lagging the US date
    q2 = build_quote(spec, s.iloc[:-1], D(2026, 9, 25))
    assert q2 is not None and q2.as_of == D(2026, 9, 24)
    assert build_quote(spec, s.iloc[:1], D(2026, 9, 25)) is None


def test_sector_perf_weighted() -> None:
    closes, rets, vols = frames()
    secs = {s.name: s for s in sector_perf(MASTER, SPECS, closes, rets, vols, T)}
    fin = secs["金融"]
    assert fin.change_pct == pytest.approx((10 * 3 - 10 * 1) / 4)  # +5.0
    assert (fin.advancers, fin.decliners, fin.count) == (1, 1, 2)
    assert [m.code for m in fin.leaders] == ["JPM"] and fin.leaders[0].sector == "金融"
    assert [m.code for m in fin.laggards] == ["BAC"]
    assert fin.key == "Financials" and fin.etf == "XLF" and fin.etf_change_pct == pytest.approx(2.0)
    tech = secs["情報技術"]
    assert tech.count == 1 and tech.change_pct == pytest.approx(1.0)  # AMD missing today
    assert tech.etf_change_pct is None  # XLK not in the frame
    assert fin.index_weight_pct == pytest.approx(4 / 9 * 100, abs=0.01)
    assert list(secs) == ["金融", "情報技術"]


def test_breadth_and_rankings() -> None:
    closes, rets, _ = frames()
    b = breadth([c.code for c in MASTER], closes, rets, T)
    assert (b.advancers, b.decliners, b.unchanged, b.total) == (2, 1, 0, 3)
    assert b.adv_dec_ratio_25d is None and b.new_highs is None and b.above_50dma_pct is None
    moves = [
        StockMove(code="1", name="a", close=1, change_pct=5, turnover=2e9),
        StockMove(code="2", name="b", close=1, change_pct=20, turnover=1e8),  # illiquid
        StockMove(code="3", name="c", close=1, change_pct=-3, turnover=5e9),
    ]
    rk = rankings(moves, min_turnover=1e9)
    assert [m.code for m in rk.gainers] == ["1", "3"]
    assert [m.code for m in rk.losers] == ["3", "1"]
    assert [m.code for m in rk.turnover] == ["3", "1", "2"]


def test_breadth_52w_highs_and_moving_averages() -> None:
    idx = pd.bdate_range("2025-09-01", "2026-09-25").date
    n = len(idx)
    c = pd.DataFrame(
        {
            "a": [100.0 + i for i in range(n)],  # steady riser: 52w high, above both averages
            "b": [100.0 - 0.1 * i for i in range(n)],  # steady faller: 52w low, below both
            "c": [100.0] * (n - 1) + [100.5],  # flat, then up on the last day: new high
        },
        index=idx,
    )
    b = breadth(["a", "b", "c"], c, returns_pct(c), idx[-1])
    assert (b.new_highs, b.new_lows) == (2, 1)
    assert b.above_50dma_pct == pytest.approx(66.7) and b.above_200dma_pct == pytest.approx(66.7)
    short = breadth(["a"], c.iloc[-30:], returns_pct(c.iloc[-30:]), idx[-1])
    assert short.new_highs is None and short.above_50dma_pct is None  # not enough history


def test_stock_move_turnover() -> None:
    closes, rets, vols = frames()
    m = stock_move("JPM", "A", "金融", closes, rets, vols, T)
    assert m is not None and m.turnover == 1.1e9 and m.change_pct == 10.0 and m.sector == "金融"
    assert stock_move("AMD", "D", None, closes, rets, vols, T) is None
    assert stock_move("9999", "Z", None, closes, rets, vols, T) is None


def test_themes() -> None:
    closes, rets, vols = frames()
    themes = [
        ThemeSpec(key="bank", name="銀行", members={"JPM": "A", "BAC": "B"}),
        ThemeSpec(key="elec", name="半導体", members={"NVDA": "C", "AMD": "D"}),
        ThemeSpec(key="none", name="なし", members={"9999": "Z"}),
    ]
    tp = theme_perf(themes, closes, rets, vols, T, {"JPM": "金融"})
    assert [t.key for t in tp] == ["elec", "bank"]  # 1.0 > 0.0; "none" dropped
    assert tp[1].change_pct == 0.0 and tp[1].advancers_ratio == 0.5
    assert tp[0].count == 1
    th = theme_history(themes, rets, T)
    assert th.series["bank"][-1] == 0.0 and "none" not in th.series


def test_sector_history() -> None:
    _, rets, _ = frames()
    h = sector_history(MASTER, SPECS, rets, T)
    assert h.dates == DATES
    assert h.series["金融"] == [None, 5.0]
    assert list(h.series) == ["情報技術", "金融"]  # config order


def test_volume_ratio_and_surge() -> None:
    idx = [D(2026, 9, 1) + dt.timedelta(days=i) for i in range(21)]
    closes = pd.DataFrame({"x": [100.0] * 20 + [110.0], "y": [100.0] * 21}, index=idx)
    vols = pd.DataFrame({"x": [1e6] * 20 + [3e7], "y": [2e7] * 21}, index=idx)
    rets = returns_pct(closes)
    mx = stock_move("x", "X", None, closes, rets, vols, idx[-1])
    my = stock_move("y", "Y", None, closes, rets, vols, idx[-1])
    assert mx is not None and mx.volume == 3e7 and mx.volume_ratio == 30.0
    assert my is not None and my.volume_ratio == 1.0
    rk = rankings([my, mx], min_turnover=1e9)
    assert [m.code for m in rk.volume_surge] == ["x", "y"]


def test_quote_absolute_changes_for_yields() -> None:
    idx = [D(2026, 9, 1) + dt.timedelta(days=i) for i in range(21)]
    s = pd.Series([1.0 + 0.01 * i for i in range(21)], index=idx)
    spec = QuoteSpec(key="us10y", name="10年", ticker="^TNX", category=QuoteCategory.RATES, unit="%")
    q = build_quote(spec, s, idx[-1])
    assert q is not None
    assert (
        q.change == pytest.approx(0.01)
        and q.change_5d == pytest.approx(0.05)
        and q.change_20d == pytest.approx(0.2)
    )
