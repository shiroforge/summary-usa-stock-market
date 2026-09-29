"""Render DailySummary into static HTML (Jinja2 + server-side SVG; no JS required to read the page)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from usmarket.calendar import ET, JST, session_close
from usmarket.models import DailySummary, QuoteCategory, SeriesHistory

WEEKDAYS_JA = "月火水木金土日"
STATIC_DIR = Path(__file__).with_name("static")


def tone(v: float | None, eps: float = 0.005) -> str:
    if v is None or abs(v) < eps:
        return "flat"
    return "up" if v > 0 else "down"


def pct(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:+.{digits}f}%".replace("+0.00%", "0.00%").replace("-0.00%", "0.00%")


def num(v: float | None) -> str:
    """Format a price level with 2 decimals (US quotes are in cents); very large values without."""
    if v is None:
        return "—"
    return f"{v:,.0f}" if abs(v) >= 100000 else f"{v:,.2f}"


def signed(v: float | None) -> str:
    if v is None:
        return "—"
    s = num(abs(v))
    return ("+" if v > 0 else "−" if v < 0 else "±") + s


def usd(v: float | None) -> str:
    """Dollar amount -> $1.23B / $456M."""
    if v is None:
        return "—"
    if abs(v) >= 1e9:
        return f"${v / 1e9:,.2f}B"
    return f"${v / 1e6:,.0f}M"


def bp(v: float | None) -> str:
    """Yield change in %pt -> basis points."""
    if v is None:
        return "—"
    x = round(v * 100, 1)
    return f"{x:+.1f}bp" if x else "0.0bp"


def shares(v: float | None) -> str:
    """Share volume -> 万株 / 億株."""
    if v is None:
        return "—"
    if v >= 1e8:
        return f"{v / 1e8:,.2f}億株"
    return f"{v / 1e4:,.0f}万株"


def jdate(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日({WEEKDAYS_JA[d.weekday()]})"


def jst(t: dt.datetime, fmt: str) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return t.astimezone(JST).strftime(fmt)


def et(t: dt.datetime, fmt: str) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.UTC)
    return t.astimezone(ET).strftime(fmt)


def spark_path(values: list[float], w: float = 120, h: float = 36, pad: float = 3) -> dict[str, object]:
    """Polyline + area paths for a sparkline, scaled to its own min/max."""
    if len(values) < 2:
        return {"line": "", "area": "", "x": 0.0, "y": 0.0}
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    step = (w - 2 * pad) / (len(values) - 1)
    pts = [(pad + i * step, pad + (h - 2 * pad) * (1 - (v - lo) / span)) for i, v in enumerate(values)]
    line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = line + f" L{pts[-1][0]:.1f},{h:.1f} L{pts[0][0]:.1f},{h:.1f} Z"
    return {"line": line, "area": area, "x": pts[-1][0], "y": pts[-1][1]}


def heat_level(v: float | None, cap: float = 3.0) -> str:
    """Bucket a % change into a diverging class: dn3..dn1, z, up1..up3."""
    if v is None:
        return "na"
    a = abs(v)
    if a < 0.25:
        return "z"
    lvl = 1 if a < 1.0 else 2 if a < cap - 1.0 else 3
    return f"{'up' if v > 0 else 'dn'}{lvl}"


def nice_max(values: list[float], floor: float = 1.0) -> float:
    """Symmetric axis bound for diverging bars: the smallest 'nice' value >= max(|v|)."""
    m = max([abs(v) for v in values] + [floor])
    for cand in (1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 50):
        if m <= cand:
            return float(cand)
    return float(m)


def make_env() -> Environment:
    env = Environment(
        loader=PackageLoader("usmarket.render", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        tone=tone,
        pct=pct,
        num=num,
        signed=signed,
        usd=usd,
        jdate=jdate,
        heat=heat_level,
        jst=jst,
        et=et,
        bp=bp,
        shares=shares,
    )
    env.globals.update(spark_path=spark_path, nice_max=nice_max, pct=pct, QuoteCategory=QuoteCategory)
    return env


def render_daily(
    summary: DailySummary,
    *,
    standalone: bool = True,
    base_url: str = "..",
    prev_date: dt.date | None = None,
    next_date: dt.date | None = None,
    charts_url: str | None = None,
) -> str:
    """Render the daily page.

    standalone=False omits <!doctype>/<html>/<head>/<body> (for embedding, e.g. Artifact previews).
    CSS/JS are always inlined so a single HTML file is self-contained.
    """
    env = make_env()
    tpl = env.get_template("daily.html.j2")
    close = session_close(summary.date)
    return tpl.render(
        s=summary,
        close_et=close.strftime("%H:%M"),
        close_jst=jst(close, "%-m/%-d %H:%M"),
        standalone=standalone,
        base_url=base_url,
        prev_date=prev_date,
        next_date=next_date,
        charts_url=charts_url if charts_url is not None else f"{base_url}/data/charts.json",
        css=(STATIC_DIR / "style.css").read_text(encoding="utf-8"),
        js=(STATIC_DIR / "app.js").read_text(encoding="utf-8"),
    )


def _by_d20(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strongest 20-session performers first; items without a 20-session figure last."""
    return sorted(rows, key=lambda r: (r["periods"].get("d20") is None, -(r["periods"].get("d20") or 0)))


def _heat_history(trends: dict[str, Any], rows: list[dict[str, Any]], n: int = 60) -> SeriesHistory:
    dates = [dt.date.fromisoformat(d) for d in trends["dates"]][-n:]
    return SeriesHistory(dates=dates, series={r["id"][2:]: r["daily"][-n:] for r in rows})


def render_trends(
    trends: dict[str, Any], *, standalone: bool = True, base_url: str = "..", charts_url: str | None = None
) -> str:
    """Trends page: multi-period table, cumulative line chart, 60-session heatmap."""
    sectors, themes = _by_d20(trends["sectors"]), _by_d20(trends["themes"])
    payload = json.dumps(
        {
            "dates": trends["dates"],
            "items": [{"id": r["id"], "name": r["name"], "daily": r["daily"]} for r in sectors + themes],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    return (
        make_env()
        .get_template("trends.html.j2")
        .render(
            standalone=standalone,
            base_url=base_url,
            charts_url=charts_url if charts_url is not None else f"{base_url}/data/charts.json",
            asof=dt.date.fromisoformat(trends["asof"]),
            periods=trends["periods"],
            sectors=sectors,
            themes=themes,
            heat_s=_heat_history(trends, sectors),
            heat_s_order=[r["id"][2:] for r in sectors],
            heat_t=_heat_history(trends, themes),
            heat_t_order=[r["id"][2:] for r in themes],
            heat_t_labels={r["id"][2:]: r["name"] for r in themes},
            payload=payload,
            css=(STATIC_DIR / "style.css").read_text(encoding="utf-8"),
            js=(STATIC_DIR / "app.js").read_text(encoding="utf-8"),
            trends_js=(STATIC_DIR / "trends.js").read_text(encoding="utf-8"),
        )
    )
