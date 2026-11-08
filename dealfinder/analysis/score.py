"""One 0-100 deal score for ranking: BMV 40, yield 25, cashflow 20, evidence 15."""
from __future__ import annotations

from ..models import Analysis


def _scale(value: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def deal_score(a: Analysis) -> int:
    score = 0.0
    if a.bmv_pct is not None and not a.comparison_warning:
        # An auction guide price is set low on purpose, so its discount counts for half.
        score += (20 if a.is_auction else 40) * _scale(a.bmv_pct, 0, 30)
    if a.gross_yield_pct is not None:
        score += 25 * _scale(a.gross_yield_pct, 5, 12)
    if a.monthly_cashflow is not None:
        score += 20 * _scale(a.monthly_cashflow, 0, 400)
    score += 15 * a.valuation_confidence
    return int(round(score))
