"""Build the static site from all stored daily summaries."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from usmarket.models import DailySummary
from usmarket.render.builder import STATIC_DIR, make_env, render_daily, render_trends


def load_all(data_dir: Path) -> list[DailySummary]:
    paths = sorted((data_dir / "daily").glob("*.json"))
    return [DailySummary.model_validate_json(p.read_text(encoding="utf-8")) for p in paths]


def build_site(
    summaries: list[DailySummary], site_dir: Path, *, only_latest: int | None = None
) -> list[Path]:
    """Write every daily page, the archive, and a redirecting index. Returns written paths.

    only_latest=N re-renders just the newest N daily pages (plus their neighbours' links stay valid
    because pages are keyed by date).
    """
    site_dir.mkdir(parents=True, exist_ok=True)
    summaries = sorted(summaries, key=lambda s: s.date)
    written: list[Path] = []
    targets = (
        range(len(summaries))
        if only_latest is None
        else range(max(0, len(summaries) - only_latest - 1), len(summaries))
    )
    for i in targets:
        s = summaries[i]
        prev_d = summaries[i - 1].date if i > 0 else None
        next_d = summaries[i + 1].date if i + 1 < len(summaries) else None
        p = site_dir / s.date.isoformat() / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_daily(s, base_url="..", prev_date=prev_d, next_date=next_d), encoding="utf-8")
        written.append(p)
    written.append(_write_archive(summaries, site_dir))
    trends_json = site_dir / "data" / "trends.json"
    if trends_json.exists():
        p = site_dir / "trends" / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_trends(json.loads(trends_json.read_text(encoding="utf-8"))), encoding="utf-8")
        written.append(p)
    written.append(_write_index(summaries, site_dir))
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    return written


def _write_archive(summaries: list[DailySummary], site_dir: Path) -> Path:
    months: dict[tuple[int, int], list[dict[str, object]]] = {}
    for s in reversed(summaries):
        sp, nq, dj = s.quote("sp500"), s.quote("nasdaq"), s.quote("dow")
        months.setdefault((s.date.year, s.date.month), []).append(
            {
                "date": s.date,
                "sp": sp.change_pct if sp else None,
                "nq": nq.change_pct if nq else None,
                "dj": dj.change_pct if dj else None,
                "top_sector": s.sectors[0].name if s.sectors else "",
                "top_theme": s.themes[0].name if s.themes else "",
            }
        )
    html = (
        make_env()
        .get_template("archive.html.j2")
        .render(
            months=months,
            css=(STATIC_DIR / "style.css").read_text(encoding="utf-8"),
            js=(STATIC_DIR / "app.js").read_text(encoding="utf-8"),
        )
    )
    p = site_dir / "archive" / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return p


def _write_index(summaries: list[DailySummary], site_dir: Path) -> Path:
    latest: dt.date | None = summaries[-1].date if summaries else None
    target = f"./{latest.isoformat()}/" if latest else "./archive/"
    html = (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="robots" content="noindex, nofollow">'
        f'<meta http-equiv="refresh" content="0; url={target}"><title>NY引けノート</title></head>'
        f'<body><p><a href="{target}">最新のNY引けノートへ</a></p></body></html>'
    )
    p = site_dir / "index.html"
    p.write_text(html, encoding="utf-8")
    return p
