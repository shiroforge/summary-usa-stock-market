import datetime as dt
import math
from pathlib import Path

import httpx
import pandas as pd
import pytest

from usmarket.calendar import ET, is_trading_day
from usmarket.config import Settings
from usmarket.models import Disclosure, NewsItem
from usmarket.pipeline import Deps, StaleDataError, build, build_summary, save_summary
from usmarket.render.builder import render_daily
from usmarket.render.site import build_site, load_all
from usmarket.sources.extended import AfterHours
from usmarket.sources.ipo import Listing
from usmarket.sources.master import Constituent, Master

D = dt.date
T = D(2026, 9, 25)  # Friday

MASTER = Master(
    as_of=D(2026, 9, 24),
    constituents=[
        Constituent("NVDA", "Nvidia", "Information Technology", "Semiconductors", 8.0, "0001045810"),
        Constituent("AAPL", "Apple", "Information Technology", "Hardware", 7.0, "0000320193"),
        Constituent("MSFT", "Microsoft", "Information Technology", "Software", 6.0, "0000789019"),
        Constituent("JPM", "JPMorgan Chase", "Financials", "Banks", 2.0, "0000019617"),
        Constituent("BAC", "Bank of America", "Financials", "Banks", 1.0, "0000070858"),
        Constituent("XOM", "Exxon Mobil", "Energy", "Integrated Oil", 1.0, "0000034088"),
        Constituent("BRK-B", "Berkshire Hathaway", "Financials", "Insurance", 1.5, "0001067983"),
        Constituent("LLY", "Eli Lilly", "Health Care", "Pharma", 1.5, "0000059478"),
    ],
)


class FakeSource:
    """Deterministic bars for every requested symbol on every trading day up to `last_day`."""

    name = "fake"

    def __init__(self, last_day: dt.date = T) -> None:
        self.last_day = last_day
        self.calls: list[list[str]] = []

    def daily_bars(self, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        self.calls.append(symbols)
        rows = []
        d = start
        while d <= min(end, self.last_day):
            if is_trading_day(d):
                n = (d - D(2025, 1, 1)).days
                for i, s in enumerate(symbols):
                    close = 100 + 5 * math.sin(n / 7 + i)
                    rows.append(
                        {
                            "symbol": s,
                            "date": d,
                            "open": close,
                            "high": close + 1,
                            "low": close - 1,
                            "close": close,
                            "volume": 3e6 + 1e5 * i,
                        }
                    )
            d += dt.timedelta(days=1)
        return pd.DataFrame(rows)


DISCLOSURES = [
    Disclosure(
        code="NVDA",
        name="NVIDIA CORP",
        time=dt.datetime(2026, 9, 25, 8, 0, tzinfo=ET),
        title="2.02 Results of Operations and Financial Condition",
        url="https://x/1",
        items=["2.02", "9.01"],
        tags=["決算"],
    ),
    Disclosure(
        code="NVDA",
        name="NVIDIA CORP",
        time=dt.datetime(2026, 9, 25, 16, 5, tzinfo=ET),
        title="1.01 Entry into a Material Definitive Agreement",
        url="https://x/2",
        items=["1.01"],
        tags=["重要な契約"],
    ),
    Disclosure(
        code="JPM",
        name="JPMORGAN CHASE & CO",
        time=dt.datetime(2026, 9, 25, 20, 30, tzinfo=ET),  # after the after-hours session
        title="5.02 Departure of Directors",
        url="https://x/3",
        items=["5.02"],
        tags=["役員の異動"],
    ),
    Disclosure(
        code="ZZZZ",  # not in the universe
        name="X",
        time=dt.datetime(2026, 9, 25, 10, 0, tzinfo=ET),
        title="8.01 Other Events",
        url="https://x/4",
        items=["8.01"],
        tags=["その他の重要事項"],
    ),
]


def settings(tmp: Path) -> Settings:
    return Settings(data_dir=tmp / "data", cache_dir=tmp / "cache", site_dir=tmp / "site")


def treasury() -> pd.DataFrame:
    days = [d for d in pd.date_range("2026-06-01", "2026-09-25").date if is_trading_day(d)]
    return pd.DataFrame({"2 Yr": [4.5 + i * 0.01 for i in range(len(days))]}, index=days)


def deps(source: FakeSource) -> Deps:
    news = [
        NewsItem(
            title="Nvidia shares rise as chip demand stays strong",
            url="https://example.com/1",
            source="t",
            published_at=dt.datetime(2026, 9, 25, 18, 0, tzinfo=dt.UTC),
        )
    ]
    return Deps(
        source=source,
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
        now=dt.datetime(2026, 9, 26, 1, 0, tzinfo=dt.UTC),  # 21:00 ET
        master=MASTER,
        news=news,
        disclosures=DISCLOSURES,
        after_hours=lambda codes, day: {
            "NVDA": AfterHours(price=110.0, time=dt.datetime(2026, 9, 25, 17, 30, tzinfo=ET))
        },
        ipos=[Listing(date=D(2026, 3, 2), code="NEWCO", name="NewCo", market="NYSE", offer_usd=5e8)],
        treasury=treasury(),
    )


def test_build(tmp_path: Path) -> None:
    s = build_summary(T, settings(tmp_path), deps(FakeSource()))
    sp = s.quote("sp500")
    assert sp is not None and len(sp.spark) == 20 and sp.as_of == T
    assert s.quote("usdjpy") is not None and s.quote("nasdaq") is not None
    ust2y = s.quote("ust2y")
    assert ust2y is not None and ust2y.close == pytest.approx(treasury()["2 Yr"].iloc[-1])
    assert [x.name for x in s.sectors] and {x.name for x in s.sectors} == {
        "情報技術",
        "金融",
        "エネルギー",
        "ヘルスケア",
    }
    tech = next(x for x in s.sectors if x.key == "Information Technology")
    assert tech.etf == "XLK" and tech.etf_change_pct is not None and tech.count == 3
    assert tech.index_weight_pct == pytest.approx(21 / 28 * 100, abs=0.01)
    assert s.themes and all(t.count > 0 for t in s.themes)
    ipo = next(t for t in s.themes if t.key == "ipo")  # dynamic theme filled from the injected listings
    assert [m.code for m in ipo.members] == ["NEWCO"]
    assert s.breadth is not None and s.breadth.total == 8
    assert s.breadth.above_50dma_pct is not None and s.breadth.new_highs is not None
    assert s.news and "semiconductor" in s.news[0].tags
    assert s.comment.startswith("S&P500は")
    assert len(s.sector_history.dates) == 20
    assert any("SPDR" in src for src in s.sources) and any("財務省" in src for src in s.sources)


def test_disclosures_attached(tmp_path: Path) -> None:
    s = build_summary(T, settings(tmp_path), deps(FakeSource()))
    assert [x.url for x in s.disclosures_session] == ["https://x/1"]  # ZZZZ is outside the universe
    assert [x.url for x in s.disclosures_after] == ["https://x/2", "https://x/3"]  # biggest weight first
    assert s.disclosure_counts == {"session": 1, "after": 2, "edgar": 1, "ah_unavailable": 0}
    semi = next(t for t in s.themes if t.key == "semiconductor")
    nvda = next(m for m in semi.members if m.code == "NVDA")
    assert [x.tags for x in nvda.disclosures] == [["決算"]]
    assert s.disclosures_session[0].name == "Nvidia"  # display name from the master, not EDGAR's
    # price reaction: session filing -> that day's change; after-close -> after-hours vs. the close
    sess, aft, late = s.disclosures_session[0], *s.disclosures_after
    assert sess.move_basis == "day" and sess.move_pct == nvda.change_pct
    assert aft.move_basis == "ah" and aft.ah_price == 110.0
    assert aft.move_pct == pytest.approx((110.0 / nvda.close - 1) * 100, abs=0.02)
    assert late.move_basis is None and late.move_pct is None  # filed after 20:00 ET


def test_after_hours_trade_before_filing_is_ignored(tmp_path: Path) -> None:
    d = deps(FakeSource())
    d.after_hours = lambda codes, day: {
        "NVDA": AfterHours(price=110.0, time=dt.datetime(2026, 9, 25, 16, 0, tzinfo=ET))
    }
    aft = build_summary(T, settings(tmp_path), d).disclosures_after[0]
    assert aft.move_basis == "ah" and aft.move_pct is None and aft.ah_price is None


def test_after_hours_unavailable_flag(tmp_path: Path) -> None:
    d = deps(FakeSource())
    d.disclosures = DISCLOSURES[:2]
    d.after_hours = lambda codes, day: {}
    s = build_summary(T, settings(tmp_path), d)
    assert s.disclosure_counts["ah_unavailable"] == 1
    assert "今回は時間外取引の価格を取得できませんでした" in render_daily(s)


def test_edgar_skipped_without_user_agent(tmp_path: Path) -> None:
    d = deps(FakeSource())
    d.disclosures = None  # would fetch, but SEC_USER_AGENT is not configured
    s = build_summary(T, settings(tmp_path), d)
    assert s.disclosures_session == [] and s.disclosure_counts["edgar"] == 0
    assert not any("EDGAR" in src for src in s.sources)


def test_stale(tmp_path: Path) -> None:
    with pytest.raises(StaleDataError):
        build_summary(T, settings(tmp_path), deps(FakeSource(D(2026, 9, 24))))


def test_site(tmp_path: Path) -> None:
    st = settings(tmp_path)
    for d in (D(2026, 9, 24), T):
        save_summary(build_summary(d, st, deps(FakeSource(d))), st.data_dir)
    build_site(load_all(st.data_dir), st.site_dir)
    day = (st.site_dir / "2026-09-25" / "index.html").read_text(encoding="utf-8")
    assert 'href="../2026-09-24/"' in day and "翌営業日 →</span>" in day
    assert "2026-09-25" in (st.site_dir / "index.html").read_text(encoding="utf-8")
    assert "2026年9月24日" in (st.site_dir / "archive" / "index.html").read_text(encoding="utf-8")


class HolidayFxSource(FakeSource):
    """FX trades on US holidays (e.g. Labor Day 2026-09-07); stocks do not."""

    def daily_bars(self, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        df = super().daily_bars(symbols, start, end)
        holiday = D(2026, 9, 7)
        extra = [
            {
                "symbol": "USDJPY=X",
                "date": holiday,
                "open": 150.0,
                "high": 150.0,
                "low": 150.0,
                "close": 150.0,
                "volume": 0.0,
            }
        ]
        if start <= holiday <= end and "USDJPY=X" in symbols:
            df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
        return df


def test_histories_skip_us_holidays(tmp_path: Path) -> None:
    s = build_summary(T, settings(tmp_path), deps(HolidayFxSource()))
    assert all(is_trading_day(d) for d in s.sector_history.dates)
    assert all(is_trading_day(d) for d in s.theme_history.dates)
    assert all(v is not None for series in s.sector_history.series.values() for v in series[1:])


def test_chart_payload(tmp_path: Path) -> None:
    res = build(T, settings(tmp_path), deps(FakeSource()))
    summary, charts = res.summary, res.charts
    assert res.trends["sectors"] and res.trends["dates"][-1] == "2026-09-25"
    s = charts["series"]
    assert charts["asof"] == "2026-09-25"
    code = summary.rankings.turnover[0].code
    assert s[code]["kind"] == "ohlc" and len(s[code]["dt"]) + 1 == len(s[code]["c"]) == len(s[code]["v"])
    assert s[code]["t0"] < "2026-09-25" and all(d >= 1 for d in s[code]["dt"])
    assert "株探" in s[code]["links"] and "Finviz" in s[code]["links"]
    assert s["q:sp500"]["kind"] == "ohlc" and "TradingView" in s["q:sp500"]["links"]
    assert s["q:us10y"]["kind"] == "ohlc" and s["q:us10y"]["unit"] == "%"
    assert s["q:ust2y"]["kind"] == "line" and "米財務省" in s["q:ust2y"]["links"]
    assert s["XLK"]["kind"] == "ohlc"
    for sid, ser in s.items():  # every series uses the compact date encoding, aligned with values
        assert "t" not in ser and len(ser["dt"]) + 1 == len(ser["c"]), sid
    assert s["s:" + summary.sectors[0].name]["c"][0] == 100
    assert "t:semiconductor" in s


class PartialSource(FakeSource):
    """Only some of the constituents have today's bar."""

    def daily_bars(self, symbols: list[str], start: dt.date, end: dt.date) -> pd.DataFrame:
        df = super().daily_bars(symbols, start, end)
        late = {"NVDA", "AAPL", "MSFT"}
        return df[~((df["date"] == T) & df["symbol"].isin(late))]


def test_early_attempt_waits_for_coverage(tmp_path: Path) -> None:
    early = deps(PartialSource())
    early.final = False
    with pytest.raises(StaleDataError, match="S&P 500 weight"):
        build_summary(T, settings(tmp_path), early)
    s = build_summary(T, settings(tmp_path / "b"), deps(PartialSource()))
    assert any("ウエイト" in w for w in s.warnings)
