"""DailySummary: the single contract between the producer (collect/analyze) and consumers (render/notify).

Changing this schema is a design decision: bump SCHEMA_VERSION and record it in docs/DECISIONS.md.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class QuoteCategory(StrEnum):
    US_INDEX = "us_index"  # 米国の株価指数
    FUTURES_VOL = "futures_vol"  # 先物・VIX
    FX = "fx"  # 為替
    GLOBAL = "global"  # 日本・欧州・アジアの指数
    COMMODITY = "commodity"  # 商品・暗号資産
    RATES = "rates"  # 金利（米国債利回り）


class Quote(BaseModel):
    """An index / FX / commodity quote with short-term performance."""

    key: str  # stable id, e.g. "sp500"
    name: str  # display name, e.g. "S&P500"
    ticker: str  # source-specific symbol
    category: QuoteCategory
    close: float
    change: float  # vs previous close, in price units
    change_pct: float  # %
    change_5d_pct: float | None = None
    change_20d_pct: float | None = None
    change_5d: float | None = None  # absolute (price units; for yields: %pt, shown as bp)
    change_20d: float | None = None
    spark: list[float] = Field(default_factory=list)  # last ~20 closes, oldest first
    as_of: dt.date  # date of `close` (other markets may be a day ahead/behind the US session)
    is_proxy: bool = False  # True when an ETF etc. stands in for the index
    unit: str = ""  # e.g. "%" for yields, "円" for USD/JPY


class Disclosure(BaseModel):
    """An SEC EDGAR 8-K filing (form, items and index link only; the document itself is never stored)."""

    code: str  # ticker, e.g. "NVDA"
    name: str
    time: dt.datetime  # tz-aware acceptance time
    title: str  # e.g. "8-K: 決算（Item 2.02）"
    url: str  # EDGAR filing index page
    items: list[str] = Field(default_factory=list)  # 8-K item numbers, e.g. ["2.02", "9.01"]
    tags: list[str] = Field(default_factory=list)  # categories, e.g. ["決算"]
    tone: str = "neutral"  # "pos" | "neg" | "neutral" (item-based, not investment advice)
    # price reaction: "day" = that session's close-to-close change; "ah" = after-hours price vs. the close
    move_pct: float | None = None
    move_basis: str | None = None  # "day" | "ah"
    ah_price: float | None = None
    ah_time: dt.datetime | None = None


class StockMove(BaseModel):
    code: str  # ticker in yfinance form, e.g. "NVDA", "BRK-B"
    name: str
    sector: str | None = None  # GICS sector (Japanese label)
    close: float
    change_pct: float
    turnover: float | None = None  # 売買代金 (USD), close * volume approximation
    volume: float | None = None  # 出来高 (shares)
    volume_ratio: float | None = None  # today's volume / average of the previous 20 sessions
    disclosures: list[Disclosure] = Field(default_factory=list)  # since the previous close


class SectorPerf(BaseModel):
    """GICS sector performance, estimated from S&P 500 constituents weighted by index weight."""

    name: str  # e.g. "情報技術"
    key: str  # GICS English name, e.g. "Information Technology"
    change_pct: float  # index-weight weighted return
    median_pct: float
    advancers: int
    decliners: int
    count: int
    index_weight_pct: float  # sector share of the S&P 500
    etf: str | None = None  # Select Sector SPDR ticker, e.g. "XLK"
    etf_change_pct: float | None = None
    leaders: list[StockMove] = Field(default_factory=list)  # top contributors (max 3)
    laggards: list[StockMove] = Field(default_factory=list)


class ThemePerf(BaseModel):
    key: str
    name: str
    change_pct: float  # equal-weighted
    advancers_ratio: float  # 0..1
    count: int
    members: list[StockMove] = Field(default_factory=list)  # sorted by change_pct desc
    news_count: int = 0


class Breadth(BaseModel):
    advancers: int
    decliners: int
    unchanged: int
    total: int
    adv_dec_ratio_25d: float | None = None  # 騰落レシオ(25日), %
    new_highs: int | None = None  # 52週高値更新
    new_lows: int | None = None  # 52週安値更新
    above_50dma_pct: float | None = None  # % of members closing above their 50-day average
    above_200dma_pct: float | None = None


class Rankings(BaseModel):
    gainers: list[StockMove] = Field(default_factory=list)
    losers: list[StockMove] = Field(default_factory=list)
    turnover: list[StockMove] = Field(default_factory=list)
    volume_surge: list[StockMove] = Field(default_factory=list)  # 出来高急増 (volume_ratio desc)


class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    published_at: dt.datetime | None = None
    tags: list[str] = Field(default_factory=list)  # theme keys matched by keyword


class SeriesHistory(BaseModel):
    """Daily % change history for heatmaps (dates oldest first; each series aligned to dates)."""

    dates: list[dt.date] = Field(default_factory=list)
    series: dict[str, list[float | None]] = Field(default_factory=dict)


class DailySummary(BaseModel):
    schema_version: int = SCHEMA_VERSION
    date: dt.date  # US (NYSE) trading date
    generated_at: dt.datetime
    sources: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # data gaps etc., shown on the page

    comment: str = ""  # 1-3 sentence market comment (rule-based)

    quotes: list[Quote] = Field(default_factory=list)
    sectors: list[SectorPerf] = Field(default_factory=list)  # sorted by change_pct desc
    themes: list[ThemePerf] = Field(default_factory=list)  # sorted by change_pct desc
    breadth: Breadth | None = None
    rankings: Rankings = Field(default_factory=Rankings)
    news: list[NewsItem] = Field(default_factory=list)
    disclosures_session: list[Disclosure] = Field(default_factory=list)  # notable, prev close .. close
    disclosures_after: list[Disclosure] = Field(default_factory=list)  # notable, close .. generation time
    disclosure_counts: dict[str, int] = Field(default_factory=dict)  # {"session": n, "after": n}

    sector_history: SeriesHistory = Field(default_factory=SeriesHistory)  # keyed by sector name
    theme_history: SeriesHistory = Field(default_factory=SeriesHistory)  # keyed by theme key

    def quote(self, key: str) -> Quote | None:
        return next((q for q in self.quotes if q.key == key), None)
