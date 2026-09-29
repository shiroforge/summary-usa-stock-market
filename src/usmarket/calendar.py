"""NYSE trading calendar: weekends, exchange holidays (holidays.financial_holidays("NYSE")), early closes.

All session times are US Eastern (America/New_York), so DST is handled by zoneinfo.
"""

from __future__ import annotations

import datetime as dt
from functools import cache
from zoneinfo import ZoneInfo

import holidays

ET = ZoneInfo("America/New_York")
JST = ZoneInfo("Asia/Tokyo")
REGULAR_CLOSE = dt.time(16, 0)
EARLY_CLOSE = dt.time(13, 0)


@cache
def _nyse_holidays(year: int) -> frozenset[dt.date]:
    return frozenset(holidays.financial_holidays("NYSE", years=year).keys())


def is_trading_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in _nyse_holidays(d.year)


def _thanksgiving(year: int) -> dt.date:
    nov1 = dt.date(year, 11, 1)
    return nov1 + dt.timedelta(days=(3 - nov1.weekday()) % 7 + 21)


def is_early_close(d: dt.date) -> bool:
    """13:00 ET closes: the day after Thanksgiving, Christmas Eve, and July 3 (when they are sessions)."""
    if not is_trading_day(d):
        return False
    return d in (_thanksgiving(d.year) + dt.timedelta(days=1), dt.date(d.year, 12, 24), dt.date(d.year, 7, 3))


def session_close(d: dt.date) -> dt.datetime:
    """The session's closing time (tz-aware, ET)."""
    return dt.datetime.combine(d, EARLY_CLOSE if is_early_close(d) else REGULAR_CLOSE, ET)


def prev_trading_day(d: dt.date) -> dt.date:
    d -= dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def next_trading_day(d: dt.date) -> dt.date:
    d += dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def trading_days_back(end: dt.date, n: int) -> list[dt.date]:
    """The n trading days ending at `end` (inclusive if `end` is a trading day), oldest first."""
    out: list[dt.date] = []
    d = end if is_trading_day(end) else prev_trading_day(end)
    while len(out) < n:
        out.append(d)
        d = prev_trading_day(d)
    return out[::-1]


def latest_trading_day(now: dt.datetime) -> dt.date:
    """Most recent trading day whose close has passed at `now` (tz-aware)."""
    et = now.astimezone(ET)
    d = et.date()
    if is_trading_day(d) and et >= session_close(d):
        return d
    return prev_trading_day(d)
