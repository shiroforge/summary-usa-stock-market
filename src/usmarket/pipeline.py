"""Assemble one day's DailySummary from sources; the only place concrete implementations are wired up."""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from usmarket.analytics import core
from usmarket.analytics.charts import build_chart_payload
from usmarket.analytics.comment import market_comment
from usmarket.analytics.trends import build_trends
from usmarket.calendar import ET, is_trading_day, prev_trading_day, session_close
from usmarket.config import Settings, ThemeSpec
from usmarket.models import DailySummary, Disclosure, NewsItem, Quote, QuoteCategory, StockMove
from usmarket.news import edgar, rss
from usmarket.sources import rates
from usmarket.sources.base import MarketDataSource
from usmarket.sources.extended import AfterHours, after_hours
from usmarket.sources.ipo import Listing, load_recent_ipos
from usmarket.sources.master import Master, load_master
from usmarket.sources.price_store import PriceStore

log = logging.getLogger(__name__)
FRESHNESS_SYMBOL = "^GSPC"
HEADLINE_INDICES = ("sp500", "nasdaq", "dow")
AFTER_HOURS_END = dt.time(20, 0)  # ET


class StaleDataError(RuntimeError):
    """Target-day data is not available yet (retryable)."""


@dataclass
class Deps:
    """External dependencies; tests replace these with fakes."""

    source: MarketDataSource
    http: httpx.Client
    now: dt.datetime
    master: Master | None = None  # None -> SPY holdings + Wikipedia (cached)
    final: bool = True  # False on early attempts: incomplete data raises StaleDataError to retry later
    news: list[NewsItem] | None = None  # None -> fetch RSS
    disclosures: list[Disclosure] | None = None  # None -> fetch EDGAR (if SEC_USER_AGENT is set)
    cik_map: dict[str, str] | None = None  # {CIK: ticker}; None -> SEC company_tickers.json
    after_hours: Callable[[list[str], dt.date], dict[str, AfterHours]] | None = None  # None -> yfinance
    ipos: list[Listing] | None = None  # None -> Nasdaq IPO calendar
    treasury: pd.DataFrame | None = None  # None -> home.treasury.gov
    failed_feeds: list[str] = field(default_factory=list)


def resolve_themes(
    themes: Sequence[ThemeSpec], target: dt.date, settings: Settings, deps: Deps, warnings: list[str]
) -> list[ThemeSpec]:
    """Fill dynamic themes (e.g. recent IPOs) with today's members."""
    out = []
    for t in themes:
        if t.dynamic == "ipo":
            listings = (
                deps.ipos
                if deps.ipos is not None
                else load_recent_ipos(
                    settings.cache_dir,
                    today=target,
                    client=deps.http,
                    window_days=t.window_days,
                    min_offer_usd=settings.ipo_min_offer_usd,
                )
            )
            if listings is None:
                warnings.append("IPOカレンダー（Nasdaq）を取得できなかったため、IPOテーマを省きました。")
                continue
            t = t.model_copy(update={"members": {x.code: x.name for x in listings}})
        if t.members:
            out.append(t)
    return out


def with_day_moves(
    items: Sequence[Disclosure], rets: pd.DataFrame, target: dt.date, deps: Deps
) -> list[Disclosure]:
    """Attach the session's close-to-close change (fetching bars for stocks we don't track)."""
    moves: dict[str, float] = {}
    if target in rets.index:
        today = core.row(rets, target)
        moves = {
            c: float(today[c]) for c in {d.code for d in items} if c in today.index and not pd.isna(today[c])
        }
    missing = sorted({d.code for d in items} - set(moves))
    if missing:
        bars = deps.source.daily_bars(missing, target - dt.timedelta(days=14), target)
        if not bars.empty:
            extra = core.returns_pct(bars.pivot(index="date", columns="symbol", values="close").sort_index())
            if target in extra.index:
                row = core.row(extra, target)
                moves.update({c: float(row[c]) for c in row.index if not pd.isna(row[c])})
    return [
        d.model_copy(update={"move_pct": round(moves[d.code], 2), "move_basis": "day"})
        if d.code in moves
        else d
        for d in items
    ]


def with_ah_moves(
    items: Sequence[Disclosure], closes: pd.DataFrame, target: dt.date, deps: Deps
) -> list[Disclosure]:
    """Attach the after-hours reaction: last extended-hours trade vs. the session close."""
    if not items:
        return []
    lookup = deps.after_hours or after_hours
    ah_end = dt.datetime.combine(target, AFTER_HOURS_END, ET)
    ah = lookup(sorted({d.code for d in items if d.time < ah_end}), target)
    refs: dict[str, float] = {}
    if target in closes.index:
        refs = {str(k): float(v) for k, v in core.row(closes, target).dropna().items()}
    missing = sorted({d.code for d in items if d.code in ah} - set(refs))
    if missing:
        bars = deps.source.daily_bars(missing, target - dt.timedelta(days=7), target)
        for r in bars[bars["date"] == target].itertuples(index=False):
            refs[str(r.symbol)] = float(r.close)  # type: ignore[arg-type]
    out = []
    for d in items:
        if d.time >= ah_end:  # filed after the after-hours session: no reaction to show yet
            out.append(d)
            continue
        a, ref = ah.get(d.code), refs.get(d.code)
        if a is not None and a.time + dt.timedelta(minutes=5) <= d.time:
            a = None  # the last trade happened before the filing
        if a is None or not ref:
            out.append(d.model_copy(update={"move_basis": "ah"}))
            continue
        out.append(
            d.model_copy(
                update={
                    "move_basis": "ah",
                    "move_pct": round((a.price / ref - 1) * 100, 2),
                    "ah_price": round(a.price, 2),
                    "ah_time": a.time,
                }
            )
        )
    return out


def summary_path(data_dir: Path, d: dt.date) -> Path:
    return data_dir / "daily" / f"{d.isoformat()}.json"


def load_disclosures(
    since: dt.datetime,
    universe: Mapping[str, str],
    master: Master,
    settings: Settings,
    deps: Deps,
    target: dt.date,
    warnings: list[str],
) -> tuple[list[Disclosure], bool]:
    """(filings by companies in `universe` {ticker: name}, whether EDGAR was consulted)."""
    if deps.disclosures is not None:
        got: list[Disclosure] | None = deps.disclosures
    elif not settings.sec_user_agent:
        return [], False
    else:
        got = _fetch_edgar(since, universe, master, settings, deps, target)
    if got is None:
        warnings.append("SEC EDGAR の開示を取得できませんでした。")
        return [], True
    # EDGAR's company names are upper-case legal names; prefer our display names
    return [d.model_copy(update={"name": universe[d.code]}) for d in got if d.code in universe], True


def _fetch_edgar(
    since: dt.datetime,
    universe: Mapping[str, str],
    master: Master,
    settings: Settings,
    deps: Deps,
    target: dt.date,
) -> list[Disclosure] | None:
    cik_map = deps.cik_map
    if cik_map is None:
        cik_map = edgar.load_cik_map(
            settings.cache_dir, client=deps.http, user_agent=settings.sec_user_agent, today=target
        )
    cik_map = {**cik_map, **{c.cik: c.code for c in master.constituents if c.cik}}
    by_cik = {cik: code for cik, code in cik_map.items() if code in universe}
    return edgar.fetch_recent(since, by_cik, client=deps.http, user_agent=settings.sec_user_agent)


@dataclass
class BuildResult:
    summary: DailySummary
    charts: dict[str, Any]  # site/data/charts.json
    trends: dict[str, Any]  # site/data/trends.json


def build_summary(target: dt.date, settings: Settings, deps: Deps) -> DailySummary:
    return build(target, settings, deps).summary


def build(target: dt.date, settings: Settings, deps: Deps) -> BuildResult:
    """The day's summary plus the payloads for the chart dialog and the trends page."""
    warnings: list[str] = []
    master = deps.master or load_master(settings.cache_dir, today=target, client=deps.http)
    codes = [c.code for c in master.constituents]
    theme_specs = resolve_themes(settings.themes, target, settings, deps, warnings)
    theme_codes = [c for t in theme_specs for c in t.members]
    etf_codes = [s.etf for s in settings.sectors]
    quote_tickers = [q.ticker for q in settings.quotes if q.source == "yfinance"]

    store = PriceStore(settings.cache_dir / "prices" / "bars.parquet")
    store.update(deps.source, list(dict.fromkeys(codes + theme_codes + etf_codes + quote_tickers)), target)
    store.save()
    all_closes = store.closes(end=target)
    if FRESHNESS_SYMBOL not in all_closes.columns or pd.isna(all_closes[FRESHNESS_SYMBOL].get(target)):
        raise StaleDataError(f"{FRESHNESS_SYMBOL} has no close for {target} yet")
    # FX / crypto / foreign indices trade on US holidays; stock-level analytics use NYSE sessions only.
    nyse_days = [d for d in all_closes.index if is_trading_day(d)]
    closes = all_closes.loc[nyse_days]
    vols = store.volumes(end=target).reindex(nyse_days)
    rets = core.returns_pct(closes)

    weights = pd.Series({c.code: c.weight_pct for c in master.constituents}, dtype=float)
    cov = core.coverage_pct(core.row(rets, target), weights)
    if cov < settings.coverage_warn_pct:
        if not deps.final:
            raise StaleDataError(f"only {cov:.1f}% of S&P 500 weight has a close for {target}")
        warnings.append(
            f"当日の株価を取得できた銘柄がS&P500の時価総額ウエイトの{cov:.1f}%にとどまります"
            "（セクターの推計値の誤差が大きくなります）。"
        )

    # quotes
    treasury = (
        deps.treasury
        if deps.treasury is not None
        else rates.load_treasury_yields(settings.cache_dir, today=target, client=deps.http)
        if any(s.source == "treasury" for s in settings.quotes)
        else pd.DataFrame()
    )
    quotes: list[Quote] = []
    missing_rates: list[str] = []
    for spec in settings.quotes:
        if spec.source == "treasury":
            q = (
                core.build_quote(spec, treasury[spec.ticker].astype(float), target)
                if spec.ticker in treasury
                else None
            )
        elif spec.ticker in all_closes.columns:
            q = core.build_quote(spec, all_closes[spec.ticker].astype(float), target)
        else:
            q = None
        if q is not None:
            quotes.append(q)
        else:
            log.warning("no data for quote %s", spec.key)
            if spec.category == QuoteCategory.RATES:
                missing_rates.append(spec.name)
    if missing_rates:
        warnings.append(f"金利データを取得できませんでした（{'、'.join(missing_rates)}）。")

    sectors = core.sector_perf(master.constituents, settings.sectors, closes, rets, vols, target)
    sector_label = {s.key: s.name for s in settings.sectors}
    sector_of = {c.code: sector_label.get(c.sector, c.sector) for c in master.constituents}
    moves = [
        m
        for c in master.constituents
        if (m := core.stock_move(c.code, c.name, sector_of[c.code], closes, rets, vols, target)) is not None
    ]
    themes = core.theme_perf(theme_specs, closes, rets, vols, target, sector_of)
    breadth = core.breadth(codes, closes, rets, target)

    # news & filings: from the previous close until now (capped at the next morning's open)
    prev_close = session_close(prev_trading_day(target))
    close = session_close(target)
    until = min(deps.now, dt.datetime.combine(target + dt.timedelta(days=1), dt.time(9, 30), ET))
    if deps.news is None:
        raw, failed = rss.fetch_feeds(settings.feeds, client=deps.http)
    else:
        raw, failed = deps.news, deps.failed_feeds
    window = rss.select(rss.tag(raw, theme_specs), since=prev_close, until=until, max_items=len(raw))
    news = rss.rank(window)[: settings.news_max_items]
    if failed:
        warnings.append(f"一部のニュースを取得できませんでした（{'、'.join(failed)}）。")
    counts: dict[str, int] = {}
    for n in news:
        for t in n.tags:
            counts[t] = counts.get(t, 0) + 1
    themes = [t.model_copy(update={"news_count": counts.get(t.key, 0)}) for t in themes]

    universe = {c.code: c.name for c in master.constituents}
    for theme in theme_specs:
        for code, label in theme.members.items():
            universe.setdefault(code, label)
    fetched, used_edgar = load_disclosures(prev_close, universe, master, settings, deps, target, warnings)
    session = edgar.window(fetched, prev_close, close)
    after = edgar.window(fetched, close, max(deps.now, close))
    by_code: dict[str, list[Disclosure]] = {}
    for d in sorted(
        session, key=lambda d: (min(edgar.PRIORITY.get(t, 99) for t in d.tags or ["-"]), -d.time.timestamp())
    ):
        if d.tags and len(by_code.get(d.code, [])) < 2:
            by_code.setdefault(d.code, []).append(d)

    def attach(ms: list[StockMove]) -> list[StockMove]:
        return [m.model_copy(update={"disclosures": by_code[m.code]}) if m.code in by_code else m for m in ms]

    rankings = core.rankings(moves, settings.min_turnover_for_ranking)
    rankings = rankings.model_copy(
        update={k: attach(getattr(rankings, k)) for k in ("gainers", "losers", "turnover", "volume_surge")}
    )
    themes = [t.model_copy(update={"members": attach(t.members)}) for t in themes]
    sectors = [
        s.model_copy(update={"leaders": attach(s.leaders), "laggards": attach(s.laggards)}) for s in sectors
    ]

    weight_by_code = {str(k): float(v) for k, v in weights.items()}
    by_key = {q.key: q for q in quotes}
    disc_after = with_ah_moves(edgar.notable(after, weight_by_code), closes, target, deps)
    summary = DailySummary(
        date=target,
        generated_at=deps.now,
        sources=[
            "yfinance",
            f"S&P500構成銘柄のウエイト: SPDR S&P 500 ETF の保有比率（{master.as_of.isoformat()}時点）",
            "GICSセクター: Wikipedia「List of S&P 500 companies」",
            *(["米財務省（2年債利回り）"] if not treasury.empty else []),
            *(["SEC EDGAR（8-K）"] if used_edgar else []),
            "RSS（" + "、".join(f.name for f in settings.feeds if f.name not in failed) + "）",
        ],
        warnings=warnings,
        comment=market_comment(
            [by_key.get(k) for k in HEADLINE_INDICES],
            sectors,
            themes,
            breadth,
            vix=by_key.get("vix"),
            us10y=by_key.get("us10y"),
        ),
        quotes=quotes,
        sectors=sectors,
        themes=themes,
        breadth=breadth,
        rankings=rankings,
        news=news,
        disclosures_session=with_day_moves(edgar.notable(session, weight_by_code), rets, target, deps),
        disclosures_after=disc_after,
        disclosure_counts={
            "session": len(session),
            "after": len(after),
            "edgar": int(used_edgar),
            # 1 when no after-close item could be priced at all (e.g. the quote source is unreachable)
            "ah_unavailable": int(bool(disc_after) and all(d.move_pct is None for d in disc_after)),
        },
        sector_history=core.sector_history(master.constituents, settings.sectors, rets, target),
        theme_history=core.theme_history(theme_specs, rets, target),
    )
    charts = build_chart_payload(
        summary,
        settings,
        themes=theme_specs,
        bars=store.bars,
        master=master.constituents,
        rets=rets,
        treasury=treasury,
        extra_names=universe,
    )
    trends = build_trends(master.constituents, settings.sectors, theme_specs, rets, target)
    return BuildResult(summary=summary, charts=charts, trends=trends)


def save_site_data(result: BuildResult, site_dir: Path) -> list[Path]:
    """charts.json / trends.json live only in the built site (raw OHLC; not committed, see D-12/D-18)."""
    out = []
    for name, payload in (("charts", result.charts), ("trends", result.trends)):
        p = site_dir / "data" / f"{name}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        out.append(p)
    return out


def save_summary(summary: DailySummary, data_dir: Path) -> Path:
    p = summary_path(data_dir, summary.date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(summary.model_dump_json(indent=1), encoding="utf-8")
    return p
