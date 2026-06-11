"""
Scoring engine for the US stock screener.

Each stock is scored 0-100 on three pillars, combined by the weights in
settings.SCORE_WEIGHTS (default 70 / 20 / 10):

  HEALTH (financial strength of the business)
    + return on equity         (higher is better)
    + operating margin         (higher is better)
    + net margin               (higher is better)
    + free-cash-flow margin    (higher is better)
    + revenue growth (YoY)     (higher is better)
    - debt / equity            (lower is better -> inverted)

  VALUATION (is the price attractive for what you get?)
    - P/E ratio                (lower is better -> inverted; only if P/E > 0)
    + FCF yield                (higher is better)

  MOMENTUM (is the market already confirming the thesis?)
    + 6-month price return     (higher is better)
    + 3-month price return     (higher is better)

Each raw factor is converted to a *percentile rank* across the scored universe
(0 = worst in the universe, 100 = best). This is robust to outliers and to the
different natural scales of the factors. Missing factors are imputed at the
universe median: each pillar mean is shrunk toward the neutral 50 in proportion
to factor coverage, so a name reporting 1 of 6 health factors keeps only 1/6 of
its distance from the median rather than posting an extreme pillar score from a
single ratio. A pillar with no usable factors lands exactly on 50 — the
coverage-0 limit of the same rule, not a special case.

The composite is the weighted average of the three pillar scores. Everything
here is pure pandas/numpy: no network, fully unit-testable.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


# Factor name -> ("higher" | "lower") meaning "which direction is good".
HEALTH_FACTORS = {
    "returnOnEquity":  "higher",
    "operatingMargin": "higher",
    "netMargin":       "higher",
    "fcfMargin":       "higher",
    "revenueGrowth":   "higher",
    "debtToEquity":    "lower",
}
VALUATION_FACTORS = {
    "peRatio":  "lower",
    "fcfYield": "higher",
}
MOMENTUM_FACTORS = {
    "return6M": "higher",
    "return3M": "higher",
}


def _percentile_rank(s: pd.Series, direction: str) -> pd.Series:
    """Percentile-rank a series to 0-100. NaNs stay NaN (excluded later).
    direction='higher' => bigger value gets higher score;
    direction='lower'  => smaller value gets higher score."""
    ranked = s.rank(pct=True, na_option="keep") * 100.0
    if direction == "lower":
        ranked = 100.0 - ranked
    return ranked


def _pillar_score(df: pd.DataFrame, factors: dict) -> tuple[pd.Series, pd.DataFrame]:
    """Average the available factor percentiles for each row. Returns
    (pillar_score, per_factor_percentiles_df)."""
    cols = {}
    for fac, direction in factors.items():
        if fac in df.columns:
            cols[fac] = _percentile_rank(df[fac], direction)
    if not cols:
        empty = pd.Series(np.nan, index=df.index)
        return empty, pd.DataFrame(index=df.index)
    pct = pd.DataFrame(cols, index=df.index)
    # Row mean over available factor percentiles, shrunk toward the neutral 50
    # in proportion to factor coverage — equivalent to imputing each missing
    # factor at the universe median. coverage == 0 gives exactly 50, subsuming
    # the old empty-pillar fallback.
    raw = pct.mean(axis=1, skipna=True)
    coverage = pct.notna().sum(axis=1) / len(factors)
    score = 50.0 + (raw.fillna(50.0) - 50.0) * coverage
    return score, pct


def score_universe(fundamentals: pd.DataFrame, momentum: pd.DataFrame) -> pd.DataFrame:
    """
    fundamentals : DataFrame indexed by ticker with columns including
        returnOnEquity, operatingMargin, netMargin, fcfMargin, revenueGrowth,
        debtToEquity, peRatio, fcfYield  (any may be NaN).
    momentum     : DataFrame indexed by ticker with return3M, return6M (and any
        other return windows, which are passed through untouched).

    Returns a DataFrame indexed by ticker with the three pillar scores, the
    composite score, and the per-factor percentile columns (suffixed `_pctl`)
    used to generate plain-English reasons downstream.
    """
    df = fundamentals.copy()

    # A negative or zero P/E is "no earnings" — not a cheap valuation. Exclude
    # it from the valuation ranking rather than rewarding it as ultra-low.
    if "peRatio" in df:
        df["peRatio"] = df["peRatio"].where(df["peRatio"] > 0)

    # Attach momentum columns.
    for col in MOMENTUM_FACTORS:
        if col in momentum.columns:
            df[col] = momentum[col]

    health, health_pct = _pillar_score(df, HEALTH_FACTORS)
    valuation, val_pct = _pillar_score(df, VALUATION_FACTORS)
    momentum_s, mom_pct = _pillar_score(df, MOMENTUM_FACTORS)

    # Neutral 50 for any pillar a stock has no data for, so it isn't unfairly
    # zeroed — but a stock with NO health data at all is too opaque to rank, and
    # is dropped by the caller (screener) before scoring.
    health = health.fillna(50.0)
    valuation = valuation.fillna(50.0)
    momentum_s = momentum_s.fillna(50.0)

    w = settings.SCORE_WEIGHTS
    composite = (
        w["health"] * health
        + w["valuation"] * valuation
        + w["momentum"] * momentum_s
    )

    out = pd.DataFrame({
        "healthScore":    health.round(2),
        "valuationScore": valuation.round(2),
        "momentumScore":  momentum_s.round(2),
        "score":          composite.round(2),
    })
    # Keep the per-factor percentiles for reason-generation (suffixed).
    for name, frame in (("", health_pct), ("", val_pct), ("", mom_pct)):
        for c in frame.columns:
            out[f"{c}_pctl"] = frame[c].round(1)
    return out


# ── Plain-English reasons & flags ─────────────────────────────────────────────

# Threshold (percentile) above which a factor counts as a "strength".
_STRONG_PCTL = 80.0

_FACTOR_LABELS = {
    "returnOnEquity":  ("return on equity", "%", 100),
    "operatingMargin": ("operating margin", "%", 100),
    "netMargin":       ("net margin", "%", 100),
    "fcfMargin":       ("free-cash-flow margin", "%", 100),
    "revenueGrowth":   ("revenue growth", "%", 100),
    "fcfYield":        ("FCF yield", "%", 100),
}


def build_reasons(row: dict, sector_pe_median: float | None) -> tuple[list[str], list[str]]:
    """Generate (reasons, flags) for one stock from its scored row.
    `row` is a dict with the fundamentals + the `*_pctl` percentile columns."""
    reasons: list[str] = []
    flags: list[str] = []

    # Strengths: factors in the top quintile of the universe.
    strengths = []
    for fac, (label, unit, mult) in _FACTOR_LABELS.items():
        pctl = row.get(f"{fac}_pctl")
        val = row.get(fac)
        if pctl is not None and not _isnan(pctl) and pctl >= _STRONG_PCTL and val is not None and not _isnan(val):
            top_pct = max(1, round(100 - pctl))
            band = "the highest in the universe" if pctl >= 99.5 else f"top {top_pct}% of the universe"
            strengths.append((pctl, f"{label.capitalize()} of {val * mult:.1f}{unit} — {band}"))
    strengths.sort(reverse=True)
    reasons.extend(s[1] for s in strengths[:4])

    # Low leverage is a quiet strength worth surfacing.
    dte = row.get("debtToEquity")
    dte_pctl = row.get("debtToEquity_pctl")
    if dte is not None and not _isnan(dte) and dte_pctl is not None and dte_pctl >= _STRONG_PCTL:
        reasons.append(f"Low leverage — debt/equity of {dte:.2f}")

    # Valuation context.
    pe = row.get("peRatio")
    if pe is not None and not _isnan(pe):
        if sector_pe_median and sector_pe_median > 0:
            rel = pe / sector_pe_median - 1.0
            if rel <= -0.15:
                reasons.append(f"Trades at a {abs(rel) * 100:.0f}% discount to its sector (P/E {pe:.1f} vs {sector_pe_median:.1f} median)")
            elif rel >= 0.25:
                flags.append(f"Premium valuation — P/E {pe:.1f} vs sector median {sector_pe_median:.1f}")
    else:
        flags.append("No positive earnings (P/E not meaningful) — valuation rests on growth")

    # Risk flags.
    fcf_margin = row.get("fcfMargin")
    if fcf_margin is not None and not _isnan(fcf_margin) and fcf_margin < 0:
        flags.append("Currently free-cash-flow negative")
    if dte is not None and not _isnan(dte) and dte > 2.0:
        flags.append(f"Elevated leverage — debt/equity {dte:.1f}")
    growth = row.get("revenueGrowth")
    if growth is not None and not _isnan(growth) and growth < 0:
        flags.append(f"Revenue declined {abs(growth) * 100:.0f}% YoY")

    if not reasons:
        reasons.append("Balanced profile — no single standout factor, ranks on consistency")
    return reasons, flags


def _isnan(x) -> bool:
    try:
        return bool(np.isnan(x))
    except (TypeError, ValueError):
        return False
