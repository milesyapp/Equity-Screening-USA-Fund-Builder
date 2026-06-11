"""
Covariance estimation for portfolio construction (QUBO risk term).

settings.py has always *documented* two estimators — RiskMetrics-style EWMA
and Ledoit-Wolf shrinkage — via COV_METHOD / EWMA_HALFLIFE / LOOKBACK_YEARS,
but until v2.1 nothing implemented them: the QUBO used a raw sample covariance
over whatever rows survived a global dropna. This module makes the documented
methodology real and fixes two estimation problems at once:

  1. WINDOWING + COVERAGE. The estimate uses the last LOOKBACK_YEARS*252 rows
     only, and a name must have >= `min_coverage` non-null days inside that
     window to participate. Previously, dropna(how="any") over the FULL
     history let one short-history candidate silently truncate the estimation
     window for all 150 names.

  2. METHOD.
       "ewma"   — exponentially-weighted covariance, halflife =
                  settings.EWMA_HALFLIFE trading days (RiskMetrics standard);
                  recent regimes dominate, old shocks decay.
       "ledoit" — Ledoit-Wolf shrinkage (sklearn), the well-conditioned
                  estimator appropriate when N is large relative to T.
       "sample" — plain sample covariance (escape hatch / tests).

Returns (cov_matrix, info) where info reports the tickers actually estimated
(in matrix order), the method, observation count, and any names dropped for
coverage — so callers can align downstream arrays and log honestly.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

_MIN_OBS = 60  # below ~3 months of daily data, any covariance is noise


def estimate(
    returns: pd.DataFrame,
    method: str | None = None,
    halflife: int | None = None,
    lookback_years: int | None = None,
    min_coverage: float = 0.6,
) -> tuple[np.ndarray, dict]:
    """
    returns        : daily-return DataFrame (columns = tickers).
    method         : "ewma" | "ledoit" | "sample" (default settings.COV_METHOD).
    halflife       : EWMA halflife in trading days (default settings.EWMA_HALFLIFE).
    lookback_years : estimation window (default settings.LOOKBACK_YEARS).
    min_coverage   : minimum fraction of non-null days inside the window for a
                     ticker to be estimated; others are dropped (and reported).

    Returns (cov, info):
      cov  : (n x n) ndarray over info["tickers"], DAILY return units.
      info : {"tickers", "method", "nObs", "dropped", "halflife"}
    Raises ValueError when fewer than 2 tickers or _MIN_OBS rows survive.
    """
    method = (method or settings.COV_METHOD).lower()
    halflife = halflife or settings.EWMA_HALFLIFE
    lookback_years = lookback_years or settings.LOOKBACK_YEARS

    window = int(lookback_years * settings.TRADING_DAYS)
    df = returns.iloc[-window:] if len(returns) > window else returns

    coverage = df.notna().mean()
    kept = [t for t in df.columns if coverage.get(t, 0.0) >= min_coverage]
    dropped = [t for t in df.columns if t not in kept]
    if dropped:
        logger.info(
            "Covariance: dropped %d/%d names for <%d%% coverage in the %dy window: %s",
            len(dropped), len(df.columns), int(min_coverage * 100),
            lookback_years, dropped[:10],
        )
    if len(kept) < 2:
        raise ValueError(
            f"covariance needs >=2 tickers with >={min_coverage:.0%} coverage; "
            f"got {len(kept)}"
        )

    sub = df[kept].dropna(how="any")
    n_obs = len(sub)
    if n_obs < _MIN_OBS:
        raise ValueError(
            f"covariance needs >={_MIN_OBS} aligned daily observations; got {n_obs}"
        )

    X = sub.values
    # Explicit finite guard: pct_change clipping can leave residual ±inf when
    # a denominator was zero; dropna removes NaN but not inf. Non-finite rows
    # cause overflow/divide-by-zero in the matmul operations below.
    finite_mask = np.isfinite(X).all(axis=1)
    if not finite_mask.all():
        n_bad = int((~finite_mask).sum())
        logger.debug("Covariance: dropping %d non-finite rows before estimation", n_bad)
        X = X[finite_mask]
        n_obs = len(X)
        if n_obs < _MIN_OBS:
            raise ValueError(
                f"After dropping non-finite rows only {n_obs} observations remain "
                f"(need >={_MIN_OBS})"
            )
    if method == "ewma":
        lam = 0.5 ** (1.0 / halflife)
        ages = np.arange(n_obs - 1, -1, -1, dtype=float)  # most recent row -> age 0
        w = lam ** ages
        w /= w.sum()
        # errstate: macOS Python 3.9 + older numpy BLAS emits divide/overflow
        # warnings on matmul even when inputs and outputs are finite. Suppress
        # them here and validate the result explicitly instead.
        with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
            mu = w @ X
            Xc = X - mu
            cov = (Xc * w[:, None]).T @ Xc
        if not np.isfinite(cov).all():
            logger.warning(
                "EWMA covariance has non-finite values (numerical overflow) "
                "— falling back to sample covariance"
            )
            cov = np.cov(X, rowvar=False)
    elif method == "ledoit":
        from sklearn.covariance import LedoitWolf  # noqa: PLC0415
        cov = LedoitWolf().fit(X).covariance_
    elif method == "sample":
        cov = np.cov(X, rowvar=False)
    else:
        raise ValueError(f"unknown covariance method {method!r}; "
                         "use 'ewma', 'ledoit', or 'sample'")

    cov = np.asarray(cov, dtype=float)
    info = {
        "tickers": kept,
        "method": method,
        "nObs": int(n_obs),
        "dropped": dropped,
        "halflife": int(halflife) if method == "ewma" else None,
    }
    logger.info("Covariance estimated: %s over %d names x %d obs", method,
                len(kept), n_obs)
    return cov, info
