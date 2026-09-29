import datetime as dt

from usmarket.analytics.comment import market_comment
from usmarket.models import Breadth, Quote, QuoteCategory, SectorPerf, ThemePerf


def q(name: str, pct: float) -> Quote:
    return Quote(
        key=name,
        name=name,
        ticker=name,
        category=QuoteCategory.US_INDEX,
        close=1,
        change=0,
        change_pct=pct,
        as_of=dt.date(2026, 9, 25),
    )


def sec(name: str, pct: float) -> SectorPerf:
    return SectorPerf(
        name=name,
        key=name,
        change_pct=pct,
        median_pct=pct,
        advancers=0,
        decliners=0,
        count=1,
        index_weight_pct=1,
    )


def th(name: str, pct: float) -> ThemePerf:
    return ThemePerf(key=name, name=name, change_pct=pct, advancers_ratio=0.5, count=2)


def br(adv: int, dec: int) -> Breadth:
    return Breadth(advancers=adv, decliners=dec, unchanged=0, total=adv + dec)


def test_broad_rally() -> None:
    c = market_comment(
        [q("S&P500", 2.1), q("NASDAQ総合", 1.8), q("NYダウ", 1.2)],
        [sec("金融", 3), sec("素材", 2), sec("公益", 1)],
        [th("大手銀行", 3), th("防衛", 1)],
        br(90, 10),
    )
    assert c.startswith(
        "S&P500は+2.10%、NASDAQ総合は+1.80%、NYダウは+1.20%。値上がり銘柄が90%を占める全面高。"
    )
    assert "金融・素材が上昇を主導。" in c and "「大手銀行」(+3.00%)が強い" in c and "売られた" not in c


def test_mixed() -> None:
    c = market_comment(
        [q("S&P500", 0.1), None],
        [sec("金融", 1), sec("素材", 0.2), sec("エネルギー", -1.5)],
        [th("大手銀行", 1), th("宇宙", -2)],
        br(50, 50),
    )
    assert c.startswith("S&P500は+0.10%。")
    assert "金融・素材が上昇を主導し、エネルギーが軟調。" in c and "「宇宙」(-2.00%)は売られた。" in c
    assert "全面" not in c and "VIX" not in c


def test_broad_selloff() -> None:
    c = market_comment(
        [q("S&P500", -2.5)],
        [sec("a", -0.5), sec("b", -1), sec("c", -3)],
        [th("x", -1)],
        br(10, 90),
    )
    assert "全面安" in c and "c・bの下げが目立つ。" in c and "強い" not in c


def test_vix_and_yield() -> None:
    vix = q("VIX", 5.0).model_copy(update={"close": 18.52, "change": 1.3})
    tnx = q("米国 10年", 0.5).model_copy(update={"close": 5.24, "change": 0.056})
    c = market_comment([q("S&P500", -0.5)], [], [], None, vix=vix, us10y=tnx)
    assert c.endswith("VIXは18.52（+1.30）、米10年債利回りは5.24%（+5.6bp）。")
