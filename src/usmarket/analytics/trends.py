"""Multi-period sector/theme performance for the trends page (site/trends/)."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from usmarket.analytics import core
from usmarket.calendar import next_trading_day
from usmarket.config import SectorSpec, ThemeSpec
from usmarket.sources.master import Constituent

SERIES_LEN = 250  # daily points embedded for the line chart (covers year-to-date)
PERIODS: list[tuple[str, str, int | None]] = [  # key, label, sessions (None = year to date)
    ("d1", "1日", 1),
    ("d5", "5日", 5),
    ("d20", "20日", 20),
    ("d60", "60日", 60),
    ("d120", "120日", 120),
    ("ytd", "年初来", None),
]


def _compound(daily_pct: pd.Series[float]) -> float:
    return round(float((np.prod(1 + daily_pct.to_numpy(dtype=float) / 100) - 1) * 100), 2)


def period_return(daily_pct: pd.Series[float], n: int) -> float | None:
    """Compounded % change over the last n sessions (None if fewer than n sessions of data)."""
    tail = daily_pct.dropna().iloc[-n:]
    if len(tail) < n:
        return None
    return _compound(tail)


def ytd_return(daily_pct: pd.Series[float], target: dt.date) -> float | None:
    """Since the previous year's last close. Requires a return on the year's first session
    (i.e. the prior year's close was available); otherwise None rather than a partial figure."""
    s = daily_pct.dropna()
    first_session = next_trading_day(dt.date(target.year - 1, 12, 31))
    this_year = s[[first_session <= d <= target for d in s.index]]
    if this_year.empty or this_year.index[0] != first_session:
        return None
    return _compound(this_year)


def heat_scale(n: int | None, ytd_sessions: int) -> float:
    """Typical |move| for a period; colour thresholds scale with sqrt(sessions)."""
    sessions = n if n is not None else max(ytd_sessions, 1)
    return math.sqrt(sessions)


def _row(item_id: str, name: str, daily: pd.Series[float], target: dt.date) -> dict[str, Any]:
    periods: dict[str, float | None] = {}
    for key, _, n in PERIODS:
        periods[key] = ytd_return(daily, target) if n is None else period_return(daily, n)
    tail = daily.iloc[-SERIES_LEN:]
    return {
        "id": item_id,
        "name": name,
        "periods": periods,
        "daily": [None if pd.isna(v) else round(float(v), 2) for v in tail],
    }


def build_trends(
    master: Sequence[Constituent],
    sector_specs: Sequence[SectorSpec],
    themes: Sequence[ThemeSpec],
    rets: pd.DataFrame,
    target: dt.date,
) -> dict[str, Any]:
    rets = rets.loc[[d for d in rets.index if d <= target]]
    dates = list(rets.index[-SERIES_LEN:])
    sectors = [
        _row(f"s:{name}", name, daily.reindex(rets.index), target)
        for name, daily in core.sector_daily_returns(master, sector_specs, rets).items()
    ]
    theme_rows = []
    for t in themes:
        cols = rets.columns.intersection(list(t.members))
        if cols.empty:
            continue
        daily = rets[cols].mean(axis=1, skipna=True).astype(float)
        theme_rows.append(_row(f"t:{t.key}", t.name, daily, target))
    ytd_sessions = sum(1 for d in rets.index if d.year == target.year)
    return {
        "asof": target.isoformat(),
        "dates": [d.isoformat() for d in dates],
        "periods": [
            {"key": k, "label": label, "scale": round(heat_scale(n, ytd_sessions), 3)}
            for k, label, n in PERIODS
        ],
        "sectors": sectors,
        "themes": theme_rows,
    }
