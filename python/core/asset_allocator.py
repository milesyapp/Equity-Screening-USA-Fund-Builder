"""
Multi-asset allocation engine.

Allocates across ASSET CLASSES (equities, intl, EM, bonds, gold, REITs), where
low cross-correlations make mean-variance / risk-based optimization genuinely
meaningful -- unlike a single-asset-class equity frontier.

Primary objective is RISK PARITY (equal risk contribution from each asset),
which requires no expected-return forecast at all -- the most defensible answer
to "this is too backward-looking." We also expose minimum-variance and the
cross-asset efficient frontier for comparison.

Cash is handled OUTSIDE this solver (a near-zero-vol asset would dominate any
risk-based weighting); it's sized separately from the market regime.

Improvements over v1.1:
  - Added ewma_cov(): exponentially-weighted covariance (RiskMetrics-style).
    Now the DEFAULT covariance estimator (settings.COV_METHOD = "ewma").
    Recent market structure influences weights more than historical shocks.
  - annualized_cov() (Ledoit-Wolf) retained as the "ledoit" fallback.
  - get_cov() dispatches between the two based on settings.COV_METHOD.
  - TRADING_DAYS imported from config.settings (single source of truth).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

from config import settings

logger = logging.getLogger(__name__)

# Single source of truth: defined in settings.py, imported here.
TRADING_DAYS = settings.TRADING_DAYS


def ewma_cov(daily_returns: pd.DataFrame, halflife: int | None = None) -> np.ndarray:
    """
    Exponentially-weighted covariance matrix (RiskMetrics-style), annualized.

    Why EWMA over simple historical covariance:
      The simple (or Ledoit-Wolf) covariance treats every past day equally.
      In a 3-year window that includes 2022, the bond crash inflates AGG's
      measured volatility and distorts all cross-asset correlations for the
      ENTIRE lookback. EWMA down-weights that shock exponentially: with a
      63-day half-life, a day 63 trading days ago has 50% the influence of
      today's observation. By the time you're 250 days out (~1 year), it
      weighs only 6% as much. The covariance therefore tracks the *current*
      correlation regime rather than being anchored to an historical stress event.

    Industry reference: J.P. Morgan's RiskMetrics (1994) popularised λ=0.94
    (equivalent to a ~32-day half-life) for daily risk. AQR and Bridgewater
    use 63–126 day half-lives for multi-asset risk parity to avoid over-
    reacting to single-day moves while still adapting to regime shifts.

    halflife: number of trading days for the 50%-decay point (default: EWMA_HALFLIFE
    from settings, typically 63 trading days ≈ 3 months).
    """
    hl = halflife if halflife is not None else settings.EWMA_HALFLIFE

    # pandas ewm().cov() returns a MultiIndex (timestamp, asset) x asset DataFrame.
    # The final block (last timestamp) is the most recent EWMA estimate.
    ewm_full = daily_returns.ewm(halflife=hl, adjust=True).cov()
    n = len(daily_returns.columns)
    cov_daily = ewm_full.iloc[-n:].values   # last n rows = final EWMA covariance

    cov = cov_daily * TRADING_DAYS
    # Symmetrize (floating-point imprecision can break PD) and add tiny ridge.
    cov = (cov + cov.T) / 2
    cov = np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0)
    cov[np.diag_indices_from(cov)] += 1e-10
    return cov


def annualized_cov(daily_returns: pd.DataFrame) -> np.ndarray:
    """
    Ledoit-Wolf shrunk, annualized covariance with a tiny PD ridge.

    Treats all days in the lookback window equally. Appropriate for longer
    windows (5+ years) or when regime stability is more important than
    responsiveness. Use COV_METHOD='ledoit' in settings to select this.
    """
    X = daily_returns.values
    lw = LedoitWolf(store_precision=False).fit(X)
    cov = np.nan_to_num(lw.covariance_, nan=0.0, posinf=0.0, neginf=0.0) * TRADING_DAYS
    cov[np.diag_indices_from(cov)] += 1e-10
    return cov


def get_cov(daily_returns: pd.DataFrame) -> np.ndarray:
    """
    Dispatch to the configured covariance estimator (settings.COV_METHOD).

    "ewma"   → ewma_cov()  (default, recommended for risk parity)
    "ledoit" → annualized_cov() (Ledoit-Wolf, appropriate for long lookbacks)
    """
    method = getattr(settings, "COV_METHOD", "ewma")
    if method == "ledoit":
        logger.debug("Covariance: Ledoit-Wolf (historical)")
        return annualized_cov(daily_returns)
    logger.debug("Covariance: EWMA halflife=%d days", settings.EWMA_HALFLIFE)
    return ewma_cov(daily_returns)


def _solve(objective, n: int, w_max: float):
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1.0},)
    bounds = [(0.0, w_max)] * n
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        res = minimize(
            objective,
            np.repeat(1.0 / n, n),
            method="SLSQP",
            bounds=bounds,
            constraints=cons,
            options={"maxiter": 1000, "ftol": 1e-12},
        )
    w = np.clip(res.x, 0.0, None)
    s = w.sum()
    return (w / s) if s > 0 else np.repeat(1.0 / n, n)


def risk_parity(cov: np.ndarray, w_max: float = 0.40) -> np.ndarray:
    """Equal-risk-contribution weights via the log-barrier formulation
    (Maillard, Roncalli & Teiletche). Minimizing  ½·wᵀΣw − (1/n)·Σ ln(wᵢ)
    over w > 0 yields the unique long-only portfolio where every asset
    contributes equal, positive risk; we then normalize to sum to 1. This is
    robust even when an asset (e.g. bonds) is a hedge, which breaks naive RC.
    No expected-return input is used."""
    n = cov.shape[0]

    def obj(w):
        return 0.5 * (w @ cov @ w) - (1.0 / n) * np.sum(np.log(w))

    bounds = [(1e-6, None)] * n  # strictly positive; budget handled by normalizing
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        res = minimize(
            obj,
            np.repeat(1.0 / n, n),
            method="SLSQP",
            bounds=bounds,
            options={"maxiter": 1000, "ftol": 1e-12},
        )
    w = np.clip(res.x, 1e-9, None)
    w = w / w.sum()
    if w.max() > w_max:  # optional concentration cap -> clamp + renormalize
        for _ in range(50):
            over = w > w_max
            if not over.any():
                break
            excess = (w[over] - w_max).sum()
            w[over] = w_max
            free = ~over & (w > 0)
            if not free.any():
                break
            w[free] += excess * w[free] / w[free].sum()
    return w


def min_variance(cov: np.ndarray, w_max: float = 0.40) -> np.ndarray:
    n = cov.shape[0]
    return _solve(lambda w: w @ cov @ w, n, w_max)


def risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Fraction of total portfolio risk contributed by each asset (sums to 1)."""
    rc = w * (cov @ w)
    tot = rc.sum()
    return rc / tot if tot > 0 else rc


def allocate(daily_returns: pd.DataFrame, method: str = "risk_parity") -> dict:
    """Return {asset: weight} plus risk contributions for the chosen method.

    Covariance is estimated via get_cov() which dispatches to EWMA (default)
    or Ledoit-Wolf based on settings.COV_METHOD.

    Risk parity runs UNCAPPED so the equal-risk-contribution property holds
    exactly (it is naturally diversified along the risk axis). Min-variance is
    capped, since unconstrained it piles into the single lowest-vol asset.

    Note: risk_contributions() is recomputed on the SAME covariance matrix
    used for optimization, so the reported contributions are internally
    consistent with the weights."""
    cov = get_cov(daily_returns)
    if method == "risk_parity":
        w = risk_parity(cov, w_max=1.0)
    else:
        w = min_variance(cov, w_max=0.40)
    assets = list(daily_returns.columns)
    rc = risk_contributions(w, cov)
    logger.info(
        "Allocation (%s, cov=%s): %s",
        method,
        getattr(settings, "COV_METHOD", "ewma"),
        {a: f"{wi*100:.1f}%" for a, wi in zip(assets, w)},
    )
    return {
        "weights": {a: float(wi) for a, wi in zip(assets, w)},
        "riskContributions": {a: float(r) for a, r in zip(assets, rc)},
    }
