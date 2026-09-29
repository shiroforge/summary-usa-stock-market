"""Generate a deterministic *dummy* DailySummary for design mocks and render tests.

Run: uv run python tests/fixtures/make_sample.py  ->  tests/fixtures/sample_summary.json
Values are fake (seeded random); names/structure are realistic.
"""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

import yaml

from usmarket.calendar import ET
from usmarket.models import (
    Breadth,
    DailySummary,
    Disclosure,
    NewsItem,
    Quote,
    QuoteCategory,
    Rankings,
    SectorPerf,
    SeriesHistory,
    StockMove,
    ThemePerf,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("sample_summary.json")
DATE = dt.date(2026, 9, 25)

STOCKS = [
    ("NVDA", "Nvidia", "情報技術"),
    ("AAPL", "Apple", "情報技術"),
    ("MSFT", "Microsoft", "情報技術"),
    ("AVGO", "Broadcom", "情報技術"),
    ("AMZN", "Amazon", "一般消費財"),
    ("TSLA", "Tesla", "一般消費財"),
    ("META", "Meta Platforms", "コミュニケーション"),
    ("GOOGL", "Alphabet (Class A)", "コミュニケーション"),
    ("JPM", "JPMorgan Chase", "金融"),
    ("BRK-B", "Berkshire Hathaway", "金融"),
    ("LLY", "Eli Lilly", "ヘルスケア"),
    ("UNH", "UnitedHealth Group", "ヘルスケア"),
    ("XOM", "Exxon Mobil", "エネルギー"),
    ("CAT", "Caterpillar", "資本財"),
    ("GE", "GE Aerospace", "資本財"),
    ("WMT", "Walmart", "生活必需品"),
    ("NEE", "NextEra Energy", "公益"),
    ("PLD", "Prologis", "不動産"),
    ("LIN", "Linde", "素材"),
    ("MU", "Micron Technology", "情報技術"),
    ("PLTR", "Palantir Technologies", "情報技術"),
    ("ORCL", "Oracle", "情報技術"),
]


def spark(rng: random.Random, start: float, n: int = 20, vol: float = 0.01) -> list[float]:
    out = [start]
    for _ in range(n - 1):
        out.append(round(out[-1] * (1 + rng.gauss(0.0008, vol)), 4))
    return out


def quote(
    rng: random.Random,
    key: str,
    name: str,
    ticker: str,
    cat: QuoteCategory,
    level: float,
    vol: float = 0.01,
    *,
    unit: str = "",
    as_of: dt.date = DATE,
) -> Quote:
    s = spark(rng, level, 21, vol)
    close, prev = s[-1], s[-2]
    return Quote(
        key=key,
        name=name,
        ticker=ticker,
        category=cat,
        close=round(close, 4) if unit == "%" or close < 10 else round(close, 2),
        change=round(close - prev, 4),
        change_pct=round((close / prev - 1) * 100, 2),
        change_5d_pct=round((close / s[-6] - 1) * 100, 2),
        change_20d_pct=round((close / s[0] - 1) * 100, 2),
        change_5d=round(close - s[-6], 4),
        change_20d=round(close - s[0], 4),
        spark=s[1:],
        as_of=as_of,
        unit=unit,
    )


def move(rng: random.Random, code: str, name: str, sector: str | None, pct: float | None = None) -> StockMove:
    return StockMove(
        code=code,
        name=name,
        sector=sector,
        close=round(rng.uniform(20, 900), 2),
        change_pct=round(pct if pct is not None else rng.gauss(0.3, 2.5), 2),
        turnover=round(rng.uniform(2e8, 3e10), -6),
        volume=round(rng.uniform(5e5, 2e8), -3),
        volume_ratio=round(rng.uniform(0.5, 4.5), 2),
    )


def main() -> None:
    rng = random.Random(20260925)
    jp_date = DATE + dt.timedelta(days=1)
    Q = QuoteCategory
    quotes = [
        quote(rng, "sp500", "S&P500", "^GSPC", Q.US_INDEX, 7700, 0.008),
        quote(rng, "nasdaq", "NASDAQ総合", "^IXIC", Q.US_INDEX, 26900, 0.011),
        quote(rng, "dow", "NYダウ", "^DJI", Q.US_INDEX, 51600, 0.007),
        quote(rng, "nasdaq100", "NASDAQ100", "^NDX", Q.US_INDEX, 30300, 0.011),
        quote(rng, "russell2000", "ラッセル2000", "^RUT", Q.US_INDEX, 2830, 0.013),
        quote(rng, "sox", "SOX指数", "^SOX", Q.US_INDEX, 12500, 0.018),
        quote(rng, "vix", "VIX", "^VIX", Q.FUTURES_VOL, 15.2, 0.05),
        quote(rng, "es_futures", "S&P500先物", "ES=F", Q.FUTURES_VOL, 7760, 0.008),
        quote(rng, "usdjpy", "ドル円", "USDJPY=X", Q.FX, 157.2, 0.004, unit="円"),
        quote(rng, "eurusd", "ユーロドル", "EURUSD=X", Q.FX, 1.1352, 0.003),
        quote(rng, "nikkei225", "日経平均", "^N225", Q.GLOBAL, 65400, 0.012, as_of=jp_date),
        quote(rng, "dax", "独DAX", "^GDAXI", Q.GLOBAL, 25400, 0.009),
        quote(rng, "wti", "WTI原油", "CL=F", Q.COMMODITY, 91.5, 0.015),
        quote(rng, "gold", "金", "GC=F", Q.COMMODITY, 4300, 0.008),
        quote(rng, "bitcoin", "ビットコイン", "BTC-USD", Q.COMMODITY, 84000, 0.02),
        quote(rng, "ust3m", "米国 3ヶ月", "^IRX", Q.RATES, 4.05, 0.004, unit="%"),
        quote(rng, "ust2y", "米国 2年", "2 Yr", Q.RATES, 4.87, 0.006, unit="%"),
        quote(rng, "us10y", "米国 10年", "^TNX", Q.RATES, 5.18, 0.006, unit="%"),
        quote(rng, "ust30y", "米国 30年", "^TYX", Q.RATES, 5.5, 0.005, unit="%"),
    ]

    sector_cfg = yaml.safe_load((ROOT / "config/indices.yaml").read_text())["sectors"]
    weights = [33.0, 9.4, 11.5, 8.6, 9.9, 8.1, 4.5, 3.4, 1.9, 1.7, 1.7]
    sectors = []
    for cfg, weight in zip(sector_cfg, weights, strict=True):
        pct = round(rng.gauss(0.3, 1.0) + (1.8 if cfg["name"] == "情報技術" else 0), 2)
        cnt = rng.randint(20, 80)
        adv = max(0, min(cnt, int(cnt * (0.5 + pct / 6) + rng.randint(-3, 3))))
        members = [move(rng, c, n, s, pct + rng.gauss(0, 1.2)) for c, n, s in STOCKS if s == cfg["name"]]
        members.sort(key=lambda m: m.change_pct, reverse=True)
        sectors.append(
            SectorPerf(
                name=cfg["name"],
                key=cfg["key"],
                change_pct=pct,
                median_pct=round(pct + rng.gauss(0, 0.3), 2),
                advancers=adv,
                decliners=cnt - adv,
                count=cnt,
                index_weight_pct=weight,
                etf=cfg["etf"],
                etf_change_pct=round(pct + rng.gauss(0, 0.15), 2),
                leaders=members[:3],
                laggards=list(reversed(members[-2:])) if len(members) > 3 else [],
            )
        )
    sectors.sort(key=lambda s: s.change_pct, reverse=True)

    themes_cfg = yaml.safe_load((ROOT / "config/themes.yaml").read_text())["themes"]
    themes = []
    for t in themes_cfg:
        if not t.get("members"):
            continue
        base = rng.gauss(0.4, 1.6) + (2.5 if t["key"] == "semiconductor" else 0)
        members = [move(rng, str(c), n, None, base + rng.gauss(0, 1.5)) for c, n in t["members"].items()]
        members.sort(key=lambda m: m.change_pct, reverse=True)
        avg = sum(m.change_pct for m in members) / len(members)
        themes.append(
            ThemePerf(
                key=t["key"],
                name=t["name"],
                change_pct=round(avg, 2),
                advancers_ratio=round(sum(m.change_pct > 0 for m in members) / len(members), 2),
                count=len(members),
                members=members,
                news_count=rng.randint(0, 5),
            )
        )
    themes.sort(key=lambda t: t.change_pct, reverse=True)

    movers = [move(rng, c, n, s) for c, n, s in STOCKS]

    def disc(
        code: str, name: str, day: int, hhmm: str, items: list[str], tags: list[str], tone: str
    ) -> Disclosure:
        h, mnt = map(int, hhmm.split(":"))
        return Disclosure(
            code=code,
            name=name,
            time=dt.datetime(2026, 9, day, h, mnt, tzinfo=ET),
            title="; ".join(f"{i} Item text" for i in items),
            url=f"https://example.com/edgar/{code}-index.htm",
            items=[*items, "9.01"],
            tags=tags,
            tone=tone,
        )

    session_discs = [
        disc(movers[0].code, movers[0].name, 25, "08:00", ["2.02"], ["決算"], "neutral").model_copy(
            update={"move_pct": 6.4, "move_basis": "day"}
        ),
        disc(
            movers[1].code,
            movers[1].name,
            24,
            "17:05",
            ["1.01", "8.01"],
            ["重要な契約", "その他の重要事項"],
            "neutral",
        ).model_copy(update={"move_pct": -2.1, "move_basis": "day"}),
    ]
    after_discs = [
        disc(
            movers[19].code, movers[19].name, 25, "16:05", ["2.02", "7.01"], ["決算", "Reg FD開示"], "neutral"
        ).model_copy(
            update={
                "move_pct": 9.2,
                "move_basis": "ah",
                "ah_price": 188.4,
                "ah_time": dt.datetime(2026, 9, 25, 19, 55, tzinfo=ET),
            }
        ),
        disc(movers[20].code, movers[20].name, 25, "16:30", ["2.05"], ["リストラ"], "neg").model_copy(
            update={"move_basis": "ah"}
        ),
        disc(movers[21].code, movers[21].name, 25, "20:40", ["5.02"], ["役員の異動"], "neutral"),
    ]
    movers[0] = movers[0].model_copy(update={"disclosures": [session_discs[0]]})
    movers[1] = movers[1].model_copy(update={"disclosures": [session_discs[1]]})
    themes[0] = themes[0].model_copy(
        update={
            "members": [
                m.model_copy(update={"disclosures": [session_discs[0]]}) if i == 0 else m
                for i, m in enumerate(themes[0].members)
            ]
        }
    )

    rankings = Rankings(
        gainers=sorted(movers, key=lambda m: m.change_pct, reverse=True)[:10],
        losers=sorted(movers, key=lambda m: m.change_pct)[:10],
        turnover=sorted(movers, key=lambda m: m.turnover or 0, reverse=True)[:10],
        volume_surge=sorted(movers, key=lambda m: m.volume_ratio or 0, reverse=True)[:10],
    )

    def utc(h: int, m: int, day: int = 25) -> dt.datetime:
        return dt.datetime(2026, 9, day, h, m, tzinfo=dt.UTC)

    news = [
        NewsItem(
            title="FRB議長、追加利下げに慎重姿勢　米長期金利が上昇",
            url="https://example.com/n1",
            source="日経速報",
            published_at=utc(18, 10),
            tags=[],
        ),
        NewsItem(
            title="Nvidia shares climb as data center demand stays strong",
            url="https://example.com/n2",
            source="CNBC Markets",
            published_at=utc(17, 30),
            tags=["semiconductor", "ai_infra"],
        ),
        NewsItem(
            title="Stocks close higher as chipmakers rally; Dow gains 300 points",
            url="https://example.com/n3",
            source="MarketWatch",
            published_at=utc(20, 5),
            tags=["semiconductor"],
        ),
        NewsItem(
            title="Oil rises on supply concerns in the Middle East",
            url="https://example.com/n4",
            source="Bloomberg Markets",
            published_at=utc(15, 45),
            tags=["oil_gas"],
        ),
        NewsItem(
            title="米国株、ナスダック続伸　半導体株に買い",
            url="https://example.com/n5",
            source="Google News 米国株",
            published_at=utc(21, 20),
            tags=["semiconductor"],
        ),
    ]

    dates: list[dt.date] = []
    d = DATE
    while len(dates) < 20:
        if d.weekday() < 5:
            dates.append(d)
        d -= dt.timedelta(days=1)
    dates.reverse()
    sector_hist = SeriesHistory(
        dates=dates,
        series={
            s.name: [round(rng.gauss(0.05, 1.0), 2) for _ in dates[:-1]] + [s.change_pct] for s in sectors
        },
    )
    theme_hist = SeriesHistory(
        dates=dates,
        series={t.key: [round(rng.gauss(0.05, 1.6), 2) for _ in dates[:-1]] + [t.change_pct] for t in themes},
    )

    total_adv = sum(s.advancers for s in sectors)
    total_dec = sum(s.decliners for s in sectors)
    summary = DailySummary(
        date=DATE,
        generated_at=dt.datetime(2026, 9, 25, 21, 42, tzinfo=dt.UTC),
        sources=["yfinance", "SPDR S&P 500 ETF 保有比率（2026-09-24時点）", "SEC EDGAR（8-K）", "RSS 各社"],
        warnings=["【ダミーデータ】デザイン確認用のサンプルです。数値は実在の相場ではありません。"],
        comment=(
            f"S&P500は{quotes[0].change_pct:+.2f}%、NASDAQ総合は{quotes[1].change_pct:+.2f}%。"
            f"{sectors[0].name}・{sectors[1].name}が上昇を主導し、{sectors[-1].name}が軟調。"
            f"テーマでは「{themes[0].name}」が強い。"
        ),
        quotes=quotes,
        sectors=sectors,
        themes=themes,
        breadth=Breadth(
            advancers=total_adv,
            decliners=total_dec,
            unchanged=5,
            total=total_adv + total_dec + 5,
            adv_dec_ratio_25d=108.4,
            new_highs=27,
            new_lows=6,
            above_50dma_pct=58.2,
            above_200dma_pct=63.9,
        ),
        rankings=rankings,
        news=news,
        disclosures_session=session_discs,
        disclosures_after=after_discs,
        disclosure_counts={"session": 41, "after": 12, "edgar": 1},
        sector_history=sector_hist,
        theme_history=theme_hist,
    )
    OUT.write_text(summary.model_dump_json(indent=1), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
