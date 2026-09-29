import datetime as dt

from usmarket.models import DailySummary
from usmarket.render.builder import (
    et,
    heat_level,
    jst,
    nice_max,
    num,
    pct,
    render_daily,
    spark_path,
    tone,
    usd,
)


def test_formatters() -> None:
    assert pct(1.234) == "+1.23%"
    assert pct(-0.001) == "0.00%"
    assert pct(None) == "—"
    assert num(65432.1) == "65,432.10" and num(123456.7) == "123,457"
    assert num(4128.59) == "4,128.59"
    assert usd(2.35e10) == "$23.50B" and usd(4.56e8) == "$456M" and usd(None) == "—"
    assert tone(0.0) == "flat" and tone(0.5) == "up" and tone(-0.5) == "down"
    assert heat_level(0.1) == "z" and heat_level(-2.5) == "dn3" and heat_level(0.5) == "up1"
    assert nice_max([0.3, -0.8]) == 1.0
    assert nice_max([4.06, -0.79]) == 5.0
    assert jst(dt.datetime(2026, 9, 25, 6, 30, tzinfo=dt.UTC), "%H:%M") == "15:30"
    assert et(dt.datetime(2026, 9, 25, 20, 0, tzinfo=dt.UTC), "%H:%M") == "16:00"  # EDT
    assert et(dt.datetime(2026, 12, 4, 21, 0, tzinfo=dt.UTC), "%H:%M") == "16:00"  # EST


def test_spark_path_bounds() -> None:
    p = spark_path([1, 3, 2], w=100, h=20, pad=2)
    assert str(p["line"]).startswith("M2.0,")
    assert p["x"] == 98.0


def test_render_standalone(sample: DailySummary) -> None:
    html = render_daily(sample)
    assert html.lstrip().startswith("<!doctype html>")
    assert 'name="robots" content="noindex' in html
    for sec in sample.sectors:
        assert sec.name in html
    assert "推計値" in html and "XLK" in html
    assert "16:00 ET（日本時間 9/26 05:00）" in html  # EDT close
    assert 'data-updown="us" aria-pressed="true"' in html  # green = up by default


def test_render_fragment(sample: DailySummary) -> None:
    html = render_daily(sample, standalone=False)
    assert "<html" not in html and "<body" not in html
    assert "<title>" in html


def test_bp_and_shares() -> None:
    from usmarket.render.builder import bp, shares

    assert bp(0.021) == "+2.1bp" and bp(-0.1) == "-10.0bp" and bp(0.0) == "0.0bp" and bp(None) == "—"
    assert shares(12_345_678) == "1,235万株" and shares(250_000_000) == "2.50億株"


def test_render_rates_and_surge(sample: DailySummary) -> None:
    html = render_daily(sample)
    assert 'id="rates"' in html and "bp</td>" in html
    assert "出来高急増" in html and "万株" in html


def test_render_trends() -> None:
    from usmarket.render.builder import render_trends

    daily = [0.5] * 70
    trends = {
        "asof": "2026-09-25",
        "dates": [(dt.date(2026, 6, 1) + dt.timedelta(days=i)).isoformat() for i in range(70)],
        "periods": [
            {"key": "d1", "label": "1日", "scale": 1.0},
            {"key": "d20", "label": "20日", "scale": 4.472},
        ],
        "sectors": [
            {"id": "s:金融", "name": "金融", "periods": {"d1": 0.5, "d20": 10.5}, "daily": daily},
            {"id": "s:素材", "name": "素材", "periods": {"d1": -0.2, "d20": None}, "daily": daily},
        ],
        "themes": [{"id": "t:x", "name": "X</script>", "periods": {"d1": 1.0, "d20": 2.0}, "daily": daily}],
    }
    html = render_trends(trends)
    assert html.index("金融") < html.index("素材")  # sorted by 20日, missing last
    assert 'data-chart="s:金融"' in html and 'id="trends-data"' in html
    assert "X<\\/script>" in html  # embedded JSON cannot close the script tag


def test_render_disclosures(sample: DailySummary) -> None:
    html = render_daily(sample)
    assert 'id="disclosures"' in html and "引け後（3）" in html
    assert 'class="disc neutral"' in html and "📄 決算" in html  # badge on a ranking row
    assert "https://example.com/edgar/" in html and "SEC EDGAR" in html


def test_render_disclosure_moves(sample: DailySummary) -> None:
    html = render_daily(sample)
    assert "時間外 19:55" in html and "時間外 取引なし" in html and ">当日<" in html
    assert "$188.40" in html  # after-hours price in the tooltip
