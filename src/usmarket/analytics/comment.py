"""Rule-based one-paragraph market comment (may be augmented by an LLM later)."""

from __future__ import annotations

from usmarket.models import Breadth, Quote, SectorPerf, ThemePerf


def _pct(v: float) -> str:
    return f"{v:+.2f}%"


def market_comment(
    indices: list[Quote | None],
    sectors: list[SectorPerf],
    themes: list[ThemePerf],
    breadth: Breadth | None,
    *,
    vix: Quote | None = None,
    us10y: Quote | None = None,
) -> str:
    """indices: the headline indices in display order (e.g. S&P500, NASDAQ総合, NYダウ)."""
    parts: list[str] = []
    idx = [f"{q.name}は{_pct(q.change_pct)}" for q in indices if q is not None]
    if idx:
        parts.append("、".join(idx) + "。")
    if breadth and breadth.total:
        ratio = breadth.advancers / breadth.total
        if ratio >= 0.8:
            parts.append(f"値上がり銘柄が{ratio:.0%}を占める全面高。")
        elif ratio <= 0.2:
            parts.append(f"値下がり銘柄が{1 - ratio:.0%}を占める全面安。")
    if len(sectors) >= 3:
        up = [s for s in sectors[:2] if s.change_pct > 0]
        down = [s for s in sectors[::-1][:2] if s.change_pct < 0]
        if up and down:
            parts.append(
                f"{'・'.join(s.name for s in up)}が上昇を主導し、{'・'.join(s.name for s in down)}が軟調。"
            )
        elif up:
            parts.append(f"{'・'.join(s.name for s in up)}が上昇を主導。")
        elif down:
            parts.append(f"{'・'.join(s.name for s in down)}の下げが目立つ。")
    if themes:
        best, worst = themes[0], themes[-1]
        if best.change_pct > 0:
            parts.append(f"テーマでは「{best.name}」({_pct(best.change_pct)})が強い。")
        if worst.change_pct < 0 and worst is not best:
            parts.append(f"「{worst.name}」({_pct(worst.change_pct)})は売られた。")
    macro = []
    if vix is not None:
        macro.append(f"VIXは{vix.close:.2f}（{vix.change:+.2f}）")
    if us10y is not None:
        macro.append(f"米10年債利回りは{us10y.close:.2f}%（{us10y.change * 100:+.1f}bp）")
    if macro:
        parts.append("、".join(macro) + "。")
    return "".join(parts)
