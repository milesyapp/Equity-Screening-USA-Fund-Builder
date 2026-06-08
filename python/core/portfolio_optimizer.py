"""
Mean-variance optimization — the robust version.

Why this differs from textbook Markowitz:
  * Covariance via Ledoit-Wolf shrinkage (sklearn) instead of the raw sample
    covariance, which is noisy and nearly singular with many assets.
  * Expected returns shrunk toward the cross-sectional mean (James-Stein style)
    so the optimizer doesn't chase a single lucky high-mean name.
  * Hard per-name weight cap (settings.MAX_WEIGHT) to prevent concentration.
  * Sparsity step to land on MIN_STOCKS..MAX_STOCKS holdings.

Note: choosing the candidate pool by trailing Sharpe still uses in-sample
information. The shrinkage + caps are what keep the result from over-fitting it.

Improvements over v1.0:
  - Added 'from __future__ import annotations' so float | None type hint syntax
    works on Python 3.9 as well as 3.10+.
  - Optimizer convergence warnings are now logged so non-convergence is visible
    in production logs rather than silently falling back to equal weights.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

from config import settings

logger = logging.getLogger(__name__)
TD = settings.TRADING_DAYS


def _annualized_inputs(daily_returns: pd.DataFrame):
    mean = daily_returns.mean() * TD
    X = np.nan_to_num(
        daily_returns.to_numpy(dtype=float), nan=0.0, posinf=0.0, neginf=0.0
    )
    lw = LedoitWolf(store_precision=False).fit(X)
    cov_arr = (
        np.nan_to_num(lw.covariance_, nan=0.0, posinf=0.0, neginf=0.0) * TD
    )
    cov_arr[np.diag_indices_from(cov_arr)] += 1e-8  # tiny ridge -> strictly PD
    cov = pd.DataFrame(
        cov_arr, index=daily_returns.columns, columns=daily_returns.columns
    )
    return mean, cov


def _shrink_returns(mean: pd.Series, intensity: float) -> pd.Series:
    grand = mean.mean()
    return (1 - intensity) * mean + intensity * grand


def _neg_sharpe(w, mean, cov, rf):
    if not np.all(np.isfinite(w)):
        return 1e9
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        var = w @ cov @ w
    if not np.isfinite(var) or var <= 0:
        return 1e9
    return -(w @ mean - rf) / np.sqrt(var)


def _max_sharpe_weights(mean, cov, rf, max_weight, label: str = "") -> pd.Series:
    n = len(mean)
    cons = ({"type": "eq", "fun": lambda x: x.sum() - 1},)
    bounds = tuple((0.0, max_weight) for _ in range(n))
    x0 = np.repeat(1.0 / n, n)
    res = minimize(
        _neg_sharpe,
        x0,
        args=(mean.values, cov.values, rf),
        method="SLSQP",
        bounds=bounds,
        constraints=cons,
        options={"maxiter": 1000, "ftol": 1e-9},
    )
    if not res.success:
        logger.warning(
            "Max-Sharpe optimizer did not fully converge%s: %s — "
            "results may be suboptimal.",
            f" ({label})" if label else "",
            res.message,
        )
    return pd.Series(res.x, index=mean.index)


def select_candidates(daily_returns: pd.DataFrame, pool_size: int = 40) -> list[str]:
    """Trim a large screened set to a tractable pool by trailing risk-adjusted return."""
    if daily_returns.shape[1] <= pool_size:
        return daily_returns.columns.tolist()
    ann_ret = daily_returns.mean() * TD
    ann_vol = daily_returns.std() * np.sqrt(TD)
    score = (ann_ret - settings.RISK_FREE_RATE) / ann_vol.replace(0, np.nan)
    return score.sort_values(ascending=False).head(pool_size).index.tolist()


def optimize(daily_returns: pd.DataFrame) -> dict:
    """Run the full optimization and return weights + the realized daily series."""
    rf = settings.RISK_FREE_RATE
    pool = select_candidates(daily_returns)
    rets = daily_returns[pool].dropna(how="any")

    mean, cov = _annualized_inputs(rets)
    mean = _shrink_returns(mean, settings.RETURN_SHRINKAGE)

    weights = _max_sharpe_weights(mean, cov, rf, settings.MAX_WEIGHT, label="initial pass")

    # Sparsify: keep the top MAX_STOCKS names, then re-optimize within them.
    top = weights.sort_values(ascending=False).head(settings.MAX_STOCKS).index.tolist()
    rets = rets[top]
    mean, cov = _annualized_inputs(rets)
    mean = _shrink_returns(mean, settings.RETURN_SHRINKAGE)
    weights = _max_sharpe_weights(mean, cov, rf, settings.MAX_WEIGHT, label="sparsity pass")
    weights = weights[weights > 0.005]
    weights = weights / weights.sum()

    logger.info("Optimized portfolio: %d holdings", len(weights))
    return {"weights": weights, "candidate_pool": pool}


def efficient_frontier(
    daily_returns: pd.DataFrame,
    points: int = 40,
    w_max: float | None = None,
) -> list[dict]:
    """Trace the frontier by minimizing variance across a grid of target returns.
    w_max caps any single asset (default = settings.MAX_WEIGHT for the equity
    sleeve; pass 1.0 for a cross-asset frontier so the corners are real)."""
    mean, cov = _annualized_inputs(daily_returns)
    mean = _shrink_returns(mean, settings.RETURN_SHRINKAGE)
    n = len(mean)
    cap = settings.MAX_WEIGHT if w_max is None else w_max
    bounds = tuple((0.0, cap) for _ in range(n))

    targets = np.linspace(mean.min(), mean.max(), points)
    frontier = []
    n_failed = 0
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        for t in targets:
            cons = (
                {"type": "eq", "fun": lambda x: x.sum() - 1},
                {"type": "ineq", "fun": lambda x, t=t: x @ mean.values - t},
            )
            res = minimize(
                lambda x: x @ cov.values @ x,
                np.repeat(1.0 / n, n),
                method="SLSQP",
                bounds=bounds,
                constraints=cons,
                options={"maxiter": 500, "ftol": 1e-9},
            )
            if res.success:
                w = res.x
                ret = float(w @ mean.values)
                vol = float(np.sqrt(w @ cov.values @ w))
                sharpe = (ret - settings.RISK_FREE_RATE) / vol if vol else 0.0
                frontier.append({"volatility": vol, "return": ret, "sharpeRatio": sharpe})
            else:
                n_failed += 1

    if n_failed:
        logger.debug(
            "Efficient frontier: %d/%d target-return sub-problems did not converge "
            "(normal near the frontier extremes).",
            n_failed,
            points,
        )
    frontier.sort(key=lambda p: p["volatility"])
    return frontier
