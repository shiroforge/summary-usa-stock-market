import datetime as dt
from pathlib import Path

import httpx
import pytest

from usmarket.sources.rates import load_treasury_yields, parse_treasury_csv

FIX = Path(__file__).parent / "fixtures"


def test_parse_treasury_csv() -> None:
    df = parse_treasury_csv((FIX / "treasury_sample.csv").read_text(encoding="utf-8"))
    assert list(df.index) == sorted(df.index) and df.index[-1] == dt.date(2026, 9, 28)
    assert df.at[dt.date(2026, 9, 28), "2 Yr"] == 4.92 and df.at[dt.date(2026, 9, 25), "10 Yr"] == 5.17
    with pytest.raises(ValueError):
        parse_treasury_csv("<html>error</html>")


def test_load_combines_years_and_caches_last_year(tmp_path: Path) -> None:
    this_year = (FIX / "treasury_sample.csv").read_text(encoding="utf-8")
    last_year = 'Date,"2 Yr","10 Yr"\n12/31/2025,4.10,4.60\n12/30/2025,4.12,4.61\n'
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, text=last_year if "/2025/" in str(req.url) else this_year)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    df = load_treasury_yields(tmp_path, today=dt.date(2026, 9, 28), client=client)
    assert df.index[0] == dt.date(2025, 12, 30) and df.index[-1] == dt.date(2026, 9, 28)
    assert len(calls) == 2
    load_treasury_yields(tmp_path, today=dt.date(2026, 9, 28), client=client)
    assert len(calls) == 3  # last year is cached; only this year is fetched again


def test_load_future_rows_are_dropped_and_failures_tolerated(tmp_path: Path) -> None:
    text = (FIX / "treasury_sample.csv").read_text(encoding="utf-8")
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=text)))
    df = load_treasury_yields(tmp_path, today=dt.date(2026, 9, 25), client=ok)
    assert df.index[-1] == dt.date(2026, 9, 25)
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert load_treasury_yields(tmp_path / "x", today=dt.date(2026, 9, 25), client=down).empty
