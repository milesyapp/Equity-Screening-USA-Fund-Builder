"""
Portfolio performance & risk metrics.

All metrics operate on a daily portfolio-return Series unless noted.
Annualization uses settings.TRADING_DAYS.

Improvements over v1.0:
  - summary() now includes six additional metrics standard in professional
    portfolio analytics: tracking_error, information_ratio, skewness,
    kurtosis, win_rate, and max_drawdown_duration (days underwater).
  - All new metrics degrade gracefully to None when there is insufficient data
    (e.g. no benchmark supplied) rather than raising or returning 0.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings

TD = settings.TRADING_DAYS


def portfolio_daily_returns(asset_returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Weighted daily return series from per-asset daily returns."""
    w = weights.reindex(asset_returns.columns).fillna(0.0)
    return asset_returns.mul(w, axis=1).sum(axis=1)


def annual_return(daily: pd.Series) -> float:
    # Geometric annualization — more honest than mean*252 for compounding.
    total_growth = (1.0 + daily).prod()
    years = len(daily) / TD
    if years <= 0:
        return 0.0
    return total_growth ** (1.0 / years) - 1.0


def annual_volatility(daily: pd.Series) -> float:
    return float(daily.std() * np.sqrt(TD))


def sharpe_ratio(daily: pd.Series, rf: float = settings.RISK_FREE_RATE) -> float:
    vol = annual_volatility(daily)
    return 0.0 if vol == 0 else (annual_return(daily) - rf) / vol


def sortino_ratio(daily: pd.Series, rf: float = settings.RISK_FREE_RATE) -> float:
    # Downside deviation only penalizes returns below the daily risk-free target.
    daily_rf = rf / TD
    downside = daily[daily < daily_rf] - daily_rf
    dd = np.sqrt((downside ** 2).mean()) * np.sqrt(TD) if len(downside) else 0.0
    return 0.0 if dd == 0 else (annual_return(daily) - rf) / dd


def maximum_drawdown(daily: pd.Series) -> float:
    curve = (1.0 + daily).cumprod()
    peak = curve.cummax()
    return float(((curve - peak) / peak).min())


def max_drawdown_duration(daily: pd.Series) -> int | None:
    """
    Maximum number of consecutive calendar days the portfolio spent below its
    prior peak (i.e. the longest underwater period). Returns None if there are
    no drawdown periods in the sample.

    This is sometimes called the 'pain duration' and is especially meaningful
    to institutional investors whose mandates include recovery-time constraints.
    """
    curve = (1.0 + daily).cumprod()
    peak = curve.cummax()
    underwater = curve < peak

    if not underwater.any():
        return None

    max_dur = 0
    current = 0
    for val in underwater:
        if val:
            current += 1
            max_dur = max(max_dur, current)
        else:
            current = 0
    return max_dur


def calmar_ratio(daily: pd.Series) -> float:
    mdd = abs(maximum_drawdown(daily))
    return 0.0 if mdd == 0 else annual_return(daily) / mdd


def value_at_risk(daily: pd.Series, confidence: float = 0.95) -> float:
    """Historical 1-day VaR (a positive number = expected loss at this confidence)."""
    return float(-np.percentile(daily, (1 - confidence) * 100))


def conditional_var(daily: pd.Series, confidence: float = 0.95) -> float:
    """Expected shortfall: average loss beyond the VaR threshold."""
    var = -value_at_risk(daily, confidence)
    tail = daily[daily <= var]
    return float(-tail.mean()) if len(tail) else 0.0


def beta_vs_market(daily: pd.Series, market_daily: pd.Series) -> float:
    aligned = pd.concat([daily, market_daily], axis=1).dropna()
    if len(aligned) < 2:
        return np.nan
    cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1])
    return float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else np.nan


def tracking_error(daily: pd.Series, benchmark_daily: pd.Series) -> float | None:
    """
    Annualized standard deviation of excess returns vs the benchmark.
    Returns None if the two series cannot be aligned (e.g. no benchmark).
    """
    aligned = pd.concat([daily, benchmark_daily], axis=1).dropna()
    if len(aligned) < 2:
        return None
    excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    return float(excess.std() * np.sqrt(TD))


def information_ratio(daily: pd.Series, benchmark_daily: pd.Series) -> float | None:
    """
    Annualized active return divided by tracking error.
    A ratio > 0.5 is generally considered strong; > 1.0 is exceptional.
    Returns None if tracking error is zero or the series cannot be aligned.
    """
    te = tracking_error(daily, benchmark_daily)
    if te is None or te == 0:
        return None
    aligned = pd.concat([daily, benchmark_daily], axis=1).dropna()
    excess_ann = (annual_return(aligned.iloc[:, 0]) - annual_return(aligned.iloc[:, 1]))
    return float(excess_ann / te)


def win_rate(daily: pd.Series) -> float:
    """Fraction of trading days with a positive return. Range [0, 1]."""
    if len(daily) == 0:
        return 0.0
    return float((daily > 0).sum() / len(daily))


def summary(daily: pd.Series, market_daily: pd.Series | None = None) -> dict:
    """
    Bundle the headline metrics into a dict whose keys match the frontend's
    camelCase TypeScript types.

    Includes both the original six metrics and the six additional professional
    metrics added in v1.1. Any metric that cannot be computed (e.g. information
    ratio when no benchmark is supplied) is returned as None rather than
    omitted, so the frontend shape remains stable.
    """
    from scipy.stats import skew, kurtosis  # noqa: PLC0415

    out: dict = {
        # ── Core metrics ────────────────────────────────────────────────────
        "annualReturn": annual_return(daily),
        "annualVolatility": annual_volatility(daily),
        "sharpeRatio": sharpe_ratio(daily),
        "sortinoRatio": sortino_ratio(daily),
        "maximumDrawdown": maximum_drawdown(daily),
        "calmarRatio": calmar_ratio(daily),
        "valueAtRisk95": value_at_risk(daily, 0.95),
        "conditionalVar95": conditional_var(daily, 0.95),
        # ── Professional / institutional metrics (v1.1) ──────────────────────
        # Win rate: % of trading days with positive return.
        "winRate": win_rate(daily),
        # Skewness: negative skew = fat left tail = more crash risk than a
        # normal distribution would imply. Risk managers watch this closely.
        "skewness": float(skew(daily.dropna())) if len(daily.dropna()) > 2 else None,
        # Excess kurtosis: > 0 means fatter tails than normal (leptokurtic).
        # Financial returns are almost always leptokurtic; large values warn
        # of tail risk the volatility estimate alone doesn't capture.
        "kurtosis": float(kurtosis(daily.dropna())) if len(daily.dropna()) > 3 else None,
        # Max drawdown duration: longest consecutive days spent below prior peak.
        "maxDrawdownDuration": max_drawdown_duration(daily),
    }

    if market_daily is not None:
        out["beta"] = beta_vs_market(daily, market_daily)
        out["trackingError"] = tracking_error(daily, market_daily)
        out["informationRatio"] = information_ratio(daily, market_daily)
    else:
        out["beta"] = None
        out["trackingError"] = None
        out["informationRatio"] = None

    return out


def alpha_newey_west(
    daily: pd.Series,
    benchmark_daily: pd.Series,
    rf: float = settings.RISK_FREE_RATE,
) -> tuple[float | None, float | None]:
    """
    CAPM regression alpha with a Newey-West (HAC) t-statistic.

    Regresses daily fund excess returns on daily benchmark excess returns:
        (r_f - rf_d) = alpha_d + beta * (r_b - rf_d) + eps
    and tests H0: alpha_d = 0 with heteroskedasticity-and-autocorrelation-
    consistent standard errors (Bartlett kernel, lag = floor(4*(n/100)^(2/9)),
    the standard Newey-West plug-in choice).

    Returns (alpha_annualized, t_stat), both None when fewer than 60 aligned
    observations exist. NOTE: this is the arithmetic OLS alpha (the quantity
    the t-stat actually tests); the headline 'alpha' elsewhere is the
    geometric CAPM gap, which is the more intuitive display number. The two
    are close for daily data; the t-stat is reported so the display alpha can
    be read with a significance context instead of as a bare point estimate.
    """
    aligned = pd.concat([daily, benchmark_daily], axis=1).dropna()
    # Drop any residual non-finite rows (±inf can survive dropna when
    # pct_change had a zero denominator and was clipped imperfectly).
    aligned = aligned[np.isfinite(aligned.values).all(axis=1)]
    n = len(aligned)
    if n < 60:
        return None, None

    rf_d = rf / TD
    y = aligned.iloc[:, 0].to_numpy(dtype=float) - rf_d
    x = aligned.iloc[:, 1].to_numpy(dtype=float) - rf_d
    X = np.column_stack([np.ones(n), x])

    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
    if not np.isfinite(coef).all() or not np.isfinite(resid).all():
        return None, None

    lags = int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    Xu = X * resid[:, None]
    S = Xu.T @ Xu
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)          # Bartlett kernel
        gamma = Xu[lag:].T @ Xu[:-lag]
        S += w * (gamma + gamma.T)

    try:
        XtX_inv = np.linalg.inv(X.T @ X)
    except np.linalg.LinAlgError:
        return None, None
    V = XtX_inv @ S @ XtX_inv
    se_alpha = float(np.sqrt(max(V[0, 0], 0.0)))
    if se_alpha == 0.0:
        return float(coef[0] * TD), None
    return float(coef[0] * TD), float(coef[0] / se_alpha)
