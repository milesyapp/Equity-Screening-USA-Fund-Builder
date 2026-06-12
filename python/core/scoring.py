"""
Scoring engine for the US stock screener.

Each stock is scored 0-100 on three pillars, combined by the weights in
settings.SCORE_WEIGHTS (default 70 / 20 / 10):

  HEALTH (financial strength of the business)
    + return on equity         (higher is better)
    + operating margin         (higher is better)
    + net margin               (higher is better)
    + free-cash-flow margin    (matched-period 3-yr average; higher is better)
    + revenue growth (3-yr CAGR) (higher is better)
    - debt / equity            (lower is better -> inverted)

  VALUATION (is the price attractive for what you get?)
    - P/E ratio                (lower is better -> inverted; only if P/E > 0)
    + FCF yield                (higher is better)

  MOMENTUM (is the market already confirming the thesis?)
    + 6-month price return     (higher is better)
    + 3-month price return     (higher is better)

Each raw factor is converted to a *percentile rank* (0 = worst, 100 = best),
which is robust to outliers and to the different natural scales of the factors.

SECTOR-NEUTRAL RANKING (v2.3): health and valuation factors are ranked WITHIN
GICS sector, so a bank's net margin is compared to other banks', not to
software companies'. Before this, universe-wide ranking let structurally
high-margin sectors flood the top decile (Financials held 32/100 fund slots at
2.3x their universe share). Two deliberate carve-outs:
  - Momentum stays UNIVERSE-WIDE: cross-sectional momentum is meant to capture
    sector trends — neutralising it would delete the signal.
  - Min-count fallback: if a sector has fewer than
    settings.SECTOR_NEUTRAL_MIN_COUNT names with a factor (or the sector is
    "Unknown" — a grab-bag, not a peer group), those names use the
    universe-wide percentile for that factor instead.

Missing factors are imputed at the median: each pillar mean is shrunk toward
the neutral 50 in proportion to factor coverage, so a name reporting 1 of 6
health factors keeps only 1/6 of its distance from the median rather than
posting an extreme pillar score from a single ratio. Because 50 in percentile
space IS the median of whatever population the rank ran over, sector ranking
automatically makes this a SECTOR-median imputation (universe-median where the
fallback fired) — the shrinkage line itself is unchanged from v2.1. A pillar
with no usable factors lands exactly on 50 — the coverage-0 limit of the same
rule, not a special case.

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


def _sector_percentile_rank(
    s: pd.Series, direction: str, sectors: pd.Series, min_count: int,
) -> tuple[pd.Series, pd.Series]:
    """Within-sector percentile rank to 0-100, falling back to the
    universe-wide percentile for names whose sector has fewer than min_count
    non-NaN values of THIS factor, or whose sector is "Unknown" (failed
    lookups form a grab-bag, not a peer group — never rank within it).
    Returns (ranked, sector_ranked_mask)."""
    universe = _percentile_rank(s, direction)
    within = s.groupby(sectors).rank(pct=True) * 100.0
    if direction == "lower":
        within = 100.0 - within
    counts = s.notna().groupby(sectors).transform("sum")
    use_sector = (counts >= min_count) & (sectors != "Unknown")
    return within.where(use_sector, universe), use_sector


def _pillar_score(
    df: pd.DataFrame, factors: dict, sectors: pd.Series | None = None,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """Average the available factor percentiles for each row — within-sector
    when `sectors` is given, universe-wide otherwise. Returns
    (pillar_score, per_factor_percentiles_df, sector_ranked_mask_df)."""
    cols, masks = {}, {}
    min_count = settings.SECTOR_NEUTRAL_MIN_COUNT
    for fac, direction in factors.items():
        if fac in df.columns:
            if sectors is not None:
                cols[fac], masks[fac] = _sector_percentile_rank(
                    df[fac], direction, sectors, min_count)
                n_fallback = int((~masks[fac] & df[fac].notna()).sum())
                if n_fallback:
                    logger.info(
                        "sector-neutral: %s — %d/%d names on universe fallback "
                        "(thin or Unknown sector)",
                        fac, n_fallback, int(df[fac].notna().sum()))
            else:
                cols[fac] = _percentile_rank(df[fac], direction)
    if not cols:
        empty = pd.Series(np.nan, index=df.index)
        return empty, pd.DataFrame(index=df.index), pd.DataFrame(index=df.index)
    pct = pd.DataFrame(cols, index=df.index)
    # Row mean over available factor percentiles, shrunk toward the neutral 50
    # in proportion to factor coverage — equivalent to imputing each missing
    # factor at the median of the rank population (sector median where ranks
    # are within-sector, universe median otherwise; 50 IS that median in
    # percentile space, so this line is identical under both regimes).
    # coverage == 0 gives exactly 50, subsuming the old empty-pillar fallback.
    raw = pct.mean(axis=1, skipna=True)
    coverage = pct.notna().sum(axis=1) / len(factors)
    score = 50.0 + (raw.fillna(50.0) - 50.0) * coverage
    return score, pct, pd.DataFrame(masks, index=df.index)


def score_universe(
    fundamentals: pd.DataFrame,
    momentum: pd.DataFrame,
    sectors: pd.Series | None = None,
) -> pd.DataFrame:
    """
    fundamentals : DataFrame indexed by ticker with columns including
        returnOnEquity, operatingMargin, netMargin, fcfMargin, revenueGrowth,
        debtToEquity, peRatio, fcfYield  (any may be NaN).
    momentum     : DataFrame indexed by ticker with return3M, return6M (and any
        other return windows, which are passed through untouched).
    sectors      : optional Series of GICS sector per ticker. When given, the
        HEALTH and VALUATION pillars rank within sector (with the min-count /
        Unknown fallback); when None, all ranks are universe-wide (pre-v2.3
        behaviour, kept for callers without sector data).

    Returns a DataFrame indexed by ticker with the three pillar scores, the
    composite score, the per-factor percentile columns (suffixed `_pctl`) used
    to generate plain-English reasons downstream, and — under sector ranking —
    boolean `{factor}_sectorRanked` columns recording, per name, whether each
    factor's percentile is within-sector (False = min-count/Unknown fallback),
    so the reason strings can claim the right comparison population.
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

    if sectors is not None:
        sectors = sectors.reindex(df.index).fillna("Unknown")

    health, health_pct, health_mask = _pillar_score(df, HEALTH_FACTORS, sectors)
    valuation, val_pct, val_mask = _pillar_score(df, VALUATION_FACTORS, sectors)
    # Momentum is DELIBERATELY universe-wide even when sectors are available:
    # cross-sectional momentum exists to capture sector trends — ranking it
    # within sector would neutralise exactly the signal it carries.
    momentum_s, mom_pct, _ = _pillar_score(df, MOMENTUM_FACTORS)

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
    # Per-name scope of each health/valuation percentile, for the reasons.
    for frame in (health_mask, val_mask):
        for c in frame.columns:
            out[f"{c}_sectorRanked"] = frame[c]
    return out


# ── Plain-English reasons & flags ─────────────────────────────────────────────

# Threshold (percentile) above which a factor counts as a "strength".
_STRONG_PCTL = 80.0

_FACTOR_LABELS = {
    "returnOnEquity":  ("return on equity", "%", 100),
    "operatingMargin": ("operating margin", "%", 100),
    "netMargin":       ("net margin", "%", 100),
    "fcfMargin":       ("free-cash-flow margin (3-yr avg)", "%", 100),
    "revenueGrowth":   ("revenue growth (3-yr CAGR)", "%", 100),
    "fcfYield":        ("FCF yield (3-yr avg FCF)", "%", 100),
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
            # Say what the percentile was actually computed against: within
            # GICS sector for health/valuation factors, unless this name's
            # factor fell back to the universe rank (thin/Unknown sector).
            scope = "its sector" if row.get(f"{fac}_sectorRanked") else "the universe"
            band = f"the highest in {scope}" if pctl >= 99.5 else f"top {top_pct}% of {scope}"
            # Upper-case only the first character — .capitalize() would
            # lower-case acronyms like CAGR/FCF inside the label.
            strengths.append((pctl, f"{label[:1].upper()}{label[1:]} of {val * mult:.1f}{unit} — {band}"))
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
        flags.append(f"Revenue declining — {abs(growth) * 100:.0f}%/yr over ~3 years")

    if not reasons:
        reasons.append("Balanced profile — no single standout factor, ranks on consistency")
    return reasons, flags


def _isnan(x) -> bool:
    try:
        return bool(np.isnan(x))
    except (TypeError, ValueError):
        return False
