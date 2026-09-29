"""usmarket CLI: run (collect -> analyze -> save -> build site), build, render."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Annotated

import httpx
import typer

from usmarket.calendar import is_trading_day, latest_trading_day
from usmarket.config import Settings
from usmarket.models import DailySummary
from usmarket.pipeline import Deps, StaleDataError, build, save_site_data, save_summary, summary_path
from usmarket.render.builder import render_daily
from usmarket.render.site import build_site, load_all
from usmarket.sources.yfinance_src import YFinanceSource

app = typer.Typer(no_args_is_help=True, add_completion=False)
EXIT_NOT_TRADING_DAY = 0
EXIT_STALE = 75  # EX_TEMPFAIL: retry later


def _parse_date(s: str | None) -> dt.date:
    if s:
        return dt.date.fromisoformat(s)
    return latest_trading_day(dt.datetime.now(dt.UTC))


@app.callback()
def main(verbose: Annotated[bool, typer.Option("-v", "--verbose")] = False) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )


@app.command()
def run(
    date: Annotated[
        str | None, typer.Option(help="Trading date YYYY-MM-DD (default: latest closed session)")
    ] = None,
    force: Annotated[bool, typer.Option(help="Rebuild even if the day's JSON exists")] = False,
    final: Annotated[
        bool,
        typer.Option("--final/--early", help="--early: exit 75 on incomplete data so a later run retries"),
    ] = True,
) -> None:
    """Collect data for one day, save data/daily/<date>.json, and rebuild the site."""
    settings = Settings()
    target = _parse_date(date)
    if not is_trading_day(target):
        typer.echo(f"{target} is not a trading day; nothing to do")
        raise typer.Exit(EXIT_NOT_TRADING_DAY)
    path = summary_path(settings.data_dir, target)
    if path.exists() and not force:
        typer.echo(f"{path} exists; skipping collection (use --force to rebuild)")
    else:
        with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as http:
            deps = Deps(
                source=YFinanceSource(
                    chunk_size=settings.yf_chunk_size,
                    pause_sec=settings.yf_pause_sec,
                    max_retries=settings.yf_max_retries,
                ),
                http=http,
                now=dt.datetime.now(dt.UTC),
                final=final,
            )
            try:
                result = build(target, settings, deps)
            except StaleDataError as e:
                typer.echo(f"data not ready: {e}", err=True)
                raise typer.Exit(EXIT_STALE) from e
        summary = result.summary
        path = save_summary(summary, settings.data_dir)
        save_site_data(result, settings.site_dir)
        typer.echo(f"wrote {path}")
        for w in summary.warnings:
            typer.echo(f"warning: {w}", err=True)
    written = build_site(load_all(settings.data_dir), settings.site_dir)
    typer.echo(f"site: {len(written)} files under {settings.site_dir}")


@app.command("build")
def build_cmd() -> None:
    """Rebuild the whole site from data/daily/*.json."""
    settings = Settings()
    written = build_site(load_all(settings.data_dir), settings.site_dir)
    typer.echo(f"site: {len(written)} files under {settings.site_dir}")


@app.command()
def render(
    summary: Annotated[Path, typer.Argument(exists=True, help="DailySummary JSON")],
    out: Annotated[Path, typer.Option(help="Output HTML path")] = Path("site/index.html"),
    fragment: Annotated[bool, typer.Option(help="Omit <html>/<head>/<body> (for Artifact previews)")] = False,
    charts_url: Annotated[
        str | None, typer.Option(help="URL of charts.json (default: ../data/charts.json)")
    ] = None,
) -> None:
    """Render one DailySummary JSON into a self-contained HTML page."""
    s = DailySummary.model_validate_json(summary.read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_daily(s, standalone=not fragment, charts_url=charts_url), encoding="utf-8")
    typer.echo(f"wrote {out}")


def _gh_output(**kv: str) -> None:
    """Write key=value pairs to $GITHUB_OUTPUT when running in Actions (always echo them too)."""
    import os

    lines = [f"{k}={v}" for k, v in kv.items()]
    for line in lines:
        typer.echo(line)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


@app.command()
def plan(date: Annotated[str | None, typer.Option(help="Override the target date")] = None) -> None:
    """Decide the target date and whether it still needs building (for CI)."""
    settings = Settings()
    target = _parse_date(date)
    _gh_output(
        date=target.isoformat(),
        trading=str(is_trading_day(target)).lower(),
        exists=str(summary_path(settings.data_dir, target).exists()).lower(),
    )


def _page_url(settings: Settings, d: dt.date) -> str:
    return f"{settings.site_base_url.rstrip('/')}/{d.isoformat()}/"


@app.command()
def notify(
    date: Annotated[str | None, typer.Option(help="Trading date YYYY-MM-DD")] = None,
    dry_run: Annotated[bool, typer.Option(help="Print the payload instead of sending")] = False,
) -> None:
    """Send the day's digest to Discord (DISCORD_WEBHOOK_URL)."""
    import json

    from usmarket.notify.discord import DiscordNotifier

    settings = Settings()
    target = _parse_date(date)
    path = summary_path(settings.data_dir, target)
    if not path.exists():
        typer.echo(f"{path} not found", err=True)
        raise typer.Exit(1)
    if not settings.discord_webhook_url and not dry_run:
        typer.echo("DISCORD_WEBHOOK_URL is not set; skipping notification", err=True)
        return
    summary = DailySummary.model_validate_json(path.read_text(encoding="utf-8"))
    payload = DiscordNotifier(settings.discord_webhook_url).send(
        summary, _page_url(settings, target), dry_run=dry_run
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=1) if dry_run else "sent")


@app.command("notify-error")
def notify_error(
    message: Annotated[str, typer.Argument(help="What went wrong")],
    run_url: Annotated[str | None, typer.Option(help="Link to the CI run")] = None,
) -> None:
    """Send a failure notice to Discord."""
    from usmarket.notify.discord import DiscordNotifier

    settings = Settings()
    if not settings.discord_webhook_url:
        typer.echo("DISCORD_WEBHOOK_URL is not set; skipping", err=True)
        return
    DiscordNotifier(settings.discord_webhook_url).send_error(message, run_url=run_url)
    typer.echo("sent")
