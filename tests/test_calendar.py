import datetime as dt

from usmarket.calendar import (
    ET,
    JST,
    is_early_close,
    is_trading_day,
    latest_trading_day,
    next_trading_day,
    prev_trading_day,
    session_close,
    trading_days_back,
)

D = dt.date


def test_weekend_and_holidays() -> None:
    assert is_trading_day(D(2026, 9, 25))  # Fri
    assert not is_trading_day(D(2026, 9, 26))  # Sat
    assert not is_trading_day(D(2026, 9, 7))  # Labor Day
    assert not is_trading_day(D(2026, 4, 3))  # Good Friday
    assert not is_trading_day(D(2026, 6, 19))  # Juneteenth
    assert not is_trading_day(D(2026, 7, 3))  # Independence Day (observed; July 4 is a Saturday)
    assert not is_trading_day(D(2026, 11, 26))  # Thanksgiving
    assert is_trading_day(D(2026, 9, 21))  # a JP holiday is a normal US session


def test_early_closes() -> None:
    assert is_early_close(D(2026, 11, 27))  # day after Thanksgiving
    assert is_early_close(D(2026, 12, 24))
    assert is_early_close(D(2025, 7, 3))
    assert not is_early_close(D(2026, 7, 3))  # a holiday that year, not a session
    assert session_close(D(2026, 11, 27)) == dt.datetime(2026, 11, 27, 13, 0, tzinfo=ET)
    assert session_close(D(2026, 9, 25)) == dt.datetime(2026, 9, 25, 16, 0, tzinfo=ET)


def test_prev_next() -> None:
    assert prev_trading_day(D(2026, 9, 8)) == D(2026, 9, 4)  # across Labor Day weekend
    assert next_trading_day(D(2026, 9, 4)) == D(2026, 9, 8)
    assert next_trading_day(D(2026, 12, 31)) == D(2027, 1, 4)


def test_trading_days_back() -> None:
    assert trading_days_back(D(2026, 9, 8), 3) == [D(2026, 9, 3), D(2026, 9, 4), D(2026, 9, 8)]


def test_latest_trading_day_across_dst() -> None:
    # EDT (UTC-4): 16:00 ET = 05:00 JST next day
    assert latest_trading_day(dt.datetime(2026, 9, 26, 5, 0, tzinfo=JST)) == D(2026, 9, 25)
    assert latest_trading_day(dt.datetime(2026, 9, 26, 4, 59, tzinfo=JST)) == D(2026, 9, 24)
    # EST (UTC-5): 16:00 ET = 06:00 JST next day
    assert latest_trading_day(dt.datetime(2026, 12, 5, 5, 30, tzinfo=JST)) == D(2026, 12, 3)
    assert latest_trading_day(dt.datetime(2026, 12, 5, 6, 0, tzinfo=JST)) == D(2026, 12, 4)
    # weekend / Monday morning in Japan -> Friday's session
    assert latest_trading_day(dt.datetime(2026, 9, 28, 7, 0, tzinfo=JST)) == D(2026, 9, 25)
