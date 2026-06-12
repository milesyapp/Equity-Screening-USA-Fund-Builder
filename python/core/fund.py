"""
Mini-fund builder.

Takes the ranked top-N stocks and constructs a score-weighted basket, then
characterises it the way a fund fact-sheet would:

  * blended fundamentals (weighted P/E, FCF yield, growth, ROE, net margin)
  * rolling 3Y and 5Y metrics: annualised return, volatility, Sharpe, max
    drawdown, and CAPM alpha + beta vs the benchmark (IVV)
  * a NAV series (fund vs benchmark, both rebased to 1.00) for the chart
  * sector breakdown

HONESTY NOTE (surfaced on the frontend): the NAV/metrics apply *today's*
holdings and weights backwards over the window. This is an in-sample
characterisation of the current basket — "what this basket looked like" — not a
live, survivorship-free track record. The real go-forward record is the
separate performance-tracker roadmap item.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import settings
from core import metrics

logger = logging.getLogger(__name__)

TD = settings.TRADING_DAYS


def score_weights(stocks: list[dict], max_weight: float | None = None) -> dict:
    """Weight each holding by its score, cap at max_weight, renormalise.
    Returns {ticker: weight} summing to 1.0."""
    max_weight = max_weight or settings.SCREENER_MAX_WEIGHT
    raw = {s["ticker"]: max(s["score"], 0.0) for s in stocks}
    total = sum(raw.values()) or 1.0
    w = {t: v / total for t, v in raw.items()}

    # Iteratively cap and redistribute so no name exceeds max_weight.
    for _ in range(50):
        over = {t: v for t, v in w.items() if v > max_weight + 1e-9}
        if not over:
            break
        excess = sum(v - max_weight for v in over.values())
        for t in over:
            w[t] = max_weight
        under = {t: v for t, v in w.items() if v < max_weight - 1e-9}
        under_total = sum(under.values()) or 1.0
        for t in under:
            w[t] += excess * (under[t] / under_total)
    total = sum(w.values()) or 1.0
    return {t: v / total for t, v in w.items()}


def _window_metrics(fund_daily: pd.Series, bench_daily: pd.Series, years: int) -> dict | None:
    """Compute annualised metrics for the trailing `years` of overlap."""
    aligned = pd.concat([fund_daily, bench_daily], axis=1).dropna()
    aligned.columns = ["fund", "bench"]
    need = int(years * TD * 0.9)  # allow ~10% missing days
    if len(aligned) < need:
        return None
    aligned = aligned.iloc[-(years * TD):]
    f, b = aligned["fund"], aligned["bench"]

    beta = metrics.beta_vs_market(f, b)
    rf = settings.RISK_FREE_RATE
    fund_ann = metrics.annual_return(f)
    bench_ann = metrics.annual_return(b)
    # CAPM alpha: actual return minus what beta would predict for the bench's excess.
    alpha = fund_ann - (rf + beta * (bench_ann - rf)) if not np.isnan(beta) else None
    # Newey-West t-stat of the daily OLS alpha — a bare alpha point estimate is
    # not interpretable; this says whether it is distinguishable from zero.
    _, alpha_t = metrics.alpha_newey_west(f, b, rf)

    return {
        "annualReturn":     round(fund_ann, 4),
        "annualVolatility": round(metrics.annual_volatility(f), 4),
        "sharpeRatio":      round(metrics.sharpe_ratio(f), 3),
        # rf-excess like sharpeRatio above; the forward panel's Sortino is
        # zero-rf to match its raw Sharpe (see research_log._sortino).
        "sortinoRatio":     round(metrics.sortino_ratio(f), 3),
        "maximumDrawdown":  round(metrics.maximum_drawdown(f), 4),
        "calmarRatio":      round(metrics.calmar_ratio(f), 3),
        "alpha":            round(alpha, 4) if alpha is not None else None,
        "alphaTStat":       round(alpha_t, 2) if alpha_t is not None else None,
        "beta":             round(beta, 3) if not np.isnan(beta) else None,
        "benchmarkReturn":  round(bench_ann, 4),
    }


def _nav_series(fund_daily: pd.Series, bench_daily: pd.Series, points: int = 180) -> list[dict]:
    """Rebased (1.00) cumulative NAV for fund and benchmark, downsampled to
    ~`points` evenly spaced observations to keep the JSON small."""
    aligned = pd.concat([fund_daily, bench_daily], axis=1).dropna()
    aligned.columns = ["fund", "bench"]
    if aligned.empty:
        return []
    fund_nav = (1.0 + aligned["fund"]).cumprod()
    bench_nav = (1.0 + aligned["bench"]).cumprod()
    fund_nav /= fund_nav.iloc[0]
    bench_nav /= bench_nav.iloc[0]

    n = len(fund_nav)
    step = max(1, n // points)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)

    out = []
    for i in idx:
        out.append({
            "date": fund_nav.index[i].strftime("%Y-%m-%d"),
            "fund": round(float(fund_nav.iloc[i]), 4),
            "benchmark": round(float(bench_nav.iloc[i]), 4),
        })
    return out


def _wavg(stocks: list[dict], weights: dict, field: str):
    num = wsum = 0.0
    for s in stocks:
        v = s.get(field)
        w = weights.get(s["ticker"], 0.0)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            num += v * w
            wsum += w
    return (num / wsum) if wsum > 0 else None


def build_fund(
    stocks: list[dict],
    returns: pd.DataFrame,
    bench_daily: pd.Series,
) -> dict:
    """
    stocks      : ranked top-N list of stock dicts (must include 'ticker','score',
                  sector + fundamentals).
    returns     : daily-return DataFrame for the holdings (columns = tickers).
    bench_daily : daily-return Series for the benchmark (IVV).
    """
    weights = score_weights(stocks)
    held = [s["ticker"] for s in stocks if s["ticker"] in returns.columns]
    w_series = pd.Series({t: weights[t] for t in held})
    w_series /= w_series.sum()

    fund_daily = metrics.portfolio_daily_returns(returns[held], w_series)

    windows = {}
    for yrs in settings.FUND_WINDOWS_YEARS:
        windows[f"metrics{yrs}Y"] = _window_metrics(fund_daily, bench_daily, yrs)

    # Sector breakdown (by fund weight).
    sector_w: dict = {}
    for s in stocks:
        sec = s.get("sector", "Unknown")
        sector_w[sec] = sector_w.get(sec, 0.0) + weights.get(s["ticker"], 0.0)
    sector_breakdown = sorted(
        [{"sector": k, "weight": round(v, 4)} for k, v in sector_w.items()],
        key=lambda x: x["weight"], reverse=True,
    )

    return {
        "name": "US Quality-Tilted Fund",
        "constituents": len(stocks),
        "weighting": "score-weighted",
        "benchmark": settings.SCREENER_BENCHMARK,
        "blended": {
            "pe":            _round(_wavg(stocks, weights, "peRatio"), 2),
            "fcfYield":      _round(_wavg(stocks, weights, "fcfYield"), 4),
            "revenueGrowth": _round(_wavg(stocks, weights, "revenueGrowth"), 4),
            "returnOnEquity":_round(_wavg(stocks, weights, "returnOnEquity"), 4),
            "netMargin":     _round(_wavg(stocks, weights, "netMargin"), 4),
        },
        **windows,
        "navSeries": _nav_series(fund_daily, bench_daily),
        "sectorBreakdown": sector_breakdown,
        "weights": {t: round(w, 5) for t, w in weights.items()},
    }


def _round(x, d):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), d)
