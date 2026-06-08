"""
Central configuration for the portfolio optimization system.
Values can be overridden via environment variables (python/.env).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load python/.env (this file is python/config/settings.py -> parent.parent = python/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

VERSION = "2.0.0"

# ── US STOCK SCREENER (the active product as of v2.0) ────────────────────────
#
# Screens the broad US universe (S&P 500/400/600), scores every name that has
# >= SCREENER_MIN_HISTORY_YEARS of price history and usable fundamentals, ranks
# the top SCREENER_TOP_N, and builds a score-weighted "mini-fund" from them.
#
# Methodology weights (must sum to 1.0). Stated verbatim on the frontend.
SCREENER_TOP_N = int(os.getenv("SCREENER_TOP_N", 100))
SCREENER_MIN_HISTORY_YEARS = float(os.getenv("SCREENER_MIN_HISTORY_YEARS", 3.0))

SCORE_WEIGHTS = {
    "health":    float(os.getenv("SCORE_W_HEALTH", 0.70)),
    "valuation": float(os.getenv("SCORE_W_VALUATION", 0.20)),
    "momentum":  float(os.getenv("SCORE_W_MOMENTUM", 0.10)),
}

# Per-name cap inside the score-weighted fund (renormalized after capping).
SCREENER_MAX_WEIGHT = float(os.getenv("SCREENER_MAX_WEIGHT", 0.04))

# Benchmark the fund is measured against (alpha/beta). US large-cap proxy.
SCREENER_BENCHMARK = os.getenv("SCREENER_BENCHMARK", "IVV")

# History windows for the fund's rolling metrics.
FUND_WINDOWS_YEARS = (3, 5)

# --- Alpaca credentials / data feed ---
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_FEED = os.getenv("ALPACA_FEED", "iex")  # 'iex' (free) or 'sip' (full volume)

# --- SEC EDGAR (fundamentals) ---
# SEC requires a descriptive User-Agent with real contact info, or it 403s.
# Set this in python/.env, e.g.  SEC_USER_AGENT="Portfolio Project you@example.com"
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "Portfolio Project contact@example.com")
FETCH_FUNDAMENTALS = os.getenv("FETCH_FUNDAMENTALS", "true").lower() == "true"

# --- Multi-asset universe (ETF proxies for the top-layer allocation) ---
# The six RISKY building blocks the allocator balances; cash is sized separately.
ASSET_CLASSES = [
    {"key": "IVV", "name": "US Equities",            "assetClass": "Equity"},
    {"key": "VEA", "name": "International Developed", "assetClass": "Equity"},
    {"key": "VWO", "name": "Emerging Markets",        "assetClass": "Equity"},
    {"key": "AGG", "name": "US Bonds",                "assetClass": "Fixed Income"},
    {"key": "GLD", "name": "Gold",                    "assetClass": "Commodity"},
    {"key": "VNQ", "name": "Real Estate (REITs)",     "assetClass": "Real Estate"},
]
CASH_TICKER = "BIL"
CASH_NAME = "Cash & T-Bills"
# Cash sleeve sized from the detected regime; the rest is risk-balanced.
CASH_BY_REGIME = {"risk-on": 0.0, "neutral": 0.05, "risk-off": 0.15}
ALLOCATION_METHOD = os.getenv("ALLOCATION_METHOD", "risk_parity")  # or 'min_variance'

# Benchmark: a transparent stock/bond blend, plus the S&P as a context line.
BENCHMARK_EQUITY = "IVV"
BENCHMARK_BOND = "AGG"
BENCHMARK_EQUITY_WEIGHT = float(os.getenv("BENCHMARK_EQUITY_WEIGHT", 0.60))

# --- Universe ---
# Broad US universe = S&P 500 (large) + S&P 400 (mid) + S&P 600 (small).
# Set USE_SMALLCAP=False for a faster run.
USE_MIDCAP = os.getenv("USE_MIDCAP", "true").lower() == "true"
USE_SMALLCAP = os.getenv("USE_SMALLCAP", "true").lower() == "true"

# --- Lookback / rebalance ---
#
# WHY 3 YEARS (changed from 5 in v1.2):
#   Risk parity's primary input is the covariance matrix. A 5-year window through
#   2026 captures 2022, when bonds suffered their worst drawdown since 1788 and the
#   stock/bond correlation inverted — an anomalous regime that inflates bond
#   volatility estimates and distorts risk contributions relative to today's market
#   structure. 3 years (~750 daily observations) is statistically sufficient while
#   reflecting current correlations. Bridgewater, AQR, and most institutional
#   risk-parity desks use a 3-year or shorter lookback for covariance estimation,
#   supplemented by EWMA weighting (see COV_METHOD) to further down-weight shocks.
#
LOOKBACK_YEARS = int(os.getenv("LOOKBACK_YEARS", 3))
REBALANCE_FREQUENCY = os.getenv("REBALANCE_FREQUENCY", "monthly")  # informational

# --- Covariance estimation method ---
#
# "ewma"   — Exponentially-weighted moving average (default).
#             Places more weight on recent days using exponential decay.
#             EWMA_HALFLIFE=63 (~3 months) is the RiskMetrics industry standard:
#             a 2022-style shock fades to 50% influence after 63 days rather than
#             persisting at full weight for the entire lookback window.
#             Standard at most systematic quant desks for daily covariance.
#
# "ledoit" — Ledoit-Wolf shrinkage of the simple historical covariance.
#             More stable than the raw sample covariance; treats all days equally.
#             Appropriate for very long lookbacks or when regime stability matters.
#
COV_METHOD = os.getenv("COV_METHOD", "ewma")
EWMA_HALFLIFE = int(os.getenv("EWMA_HALFLIFE", 63))  # trading days (~3 months)

# --- Liquidity / quality screens (NOT return-based — avoids look-ahead bias) ---
#
# IMPORTANT — volume depends on which Alpaca feed you use:
#   * SIP (paid) reports CONSOLIDATED volume across all US venues.
#   * IEX (free) reports ONLY volume that printed on IEX, a single exchange that
#     handles ~2-3% of total US equity volume. So IEX volume is ~30-50x smaller
#     than consolidated volume for the same stock. A 1,000,000-share floor that
#     is sensible for SIP rejects almost the entire S&P on IEX (only the very
#     highest-volume names clear it). We therefore use a separate, much lower
#     floor for the IEX feed. The screener picks the right one from ALPACA_FEED.
#
# Note: S&P 500/400/600 membership already enforces minimum liquidity (S&P's
# index methodology requires a minimum traded value and volume for inclusion),
# so this floor is a light safety net to catch anomalies, not the primary gate.
MIN_AVG_VOLUME = int(os.getenv("MIN_AVG_VOLUME", 1_000_000))       # SIP / consolidated
MIN_AVG_VOLUME_IEX = int(os.getenv("MIN_AVG_VOLUME_IEX", 25_000))  # IEX-only volume
MIN_PRICE = float(os.getenv("MIN_PRICE", 5.0))                # avoid penny stocks
MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", 1e9))      # $1B+ floor

# Fundamental quality gates (applied only to liquidity survivors)
MIN_OPERATING_MARGIN = float(os.getenv("MIN_OPERATING_MARGIN", 0.0))
MIN_FCF_MARGIN = float(os.getenv("MIN_FCF_MARGIN", 0.0))       # >0 = generates cash

# --- Portfolio construction ---
MIN_STOCKS = int(os.getenv("MIN_STOCKS", 8))
MAX_STOCKS = int(os.getenv("MAX_STOCKS", 12))
MAX_WEIGHT = float(os.getenv("MAX_WEIGHT", 0.30))   # cap any single name at 30%
RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", 0.04))

# Shrinkage intensity for expected returns (0 = raw means, 1 = all toward grand mean)
RETURN_SHRINKAGE = float(os.getenv("RETURN_SHRINKAGE", 0.5))

# --- Market regime detection ---
# VIX thresholds for the risk-on / neutral / risk-off heuristic
VIX_RISK_ON_BELOW = float(os.getenv("VIX_RISK_ON_BELOW", 16.0))
VIX_RISK_OFF_ABOVE = float(os.getenv("VIX_RISK_OFF_ABOVE", 24.0))

# Trading days per year (annualization factor).
# SINGLE SOURCE OF TRUTH — import this constant from here; do not redefine it
# in other modules. Keeping one definition prevents silent drift if you ever
# change the value (e.g. switching to calendar-day annualization).
TRADING_DAYS = 252


def validate() -> None:
    """
    Validate required configuration at startup.

    Call this before running the pipeline so that missing credentials or
    obviously wrong settings surface immediately with a clear message, rather
    than as a cryptic error deep inside the pipeline.

    Raises RuntimeError if any hard requirement is unmet.
    Emits warnings for soft issues (e.g. placeholder SEC User-Agent).
    """
    import warnings  # noqa: PLC0415

    errors: list[str] = []

    if not ALPACA_API_KEY:
        errors.append("ALPACA_API_KEY is not set — add it to python/.env.")
    if not ALPACA_SECRET_KEY:
        errors.append("ALPACA_SECRET_KEY is not set — add it to python/.env.")
    if ALPACA_FEED not in ("iex", "sip"):
        errors.append(
            f"ALPACA_FEED='{ALPACA_FEED}' is invalid; use 'iex' (free) or 'sip'."
        )
    if LOOKBACK_YEARS < 1 or LOOKBACK_YEARS > 20:
        errors.append(
            f"LOOKBACK_YEARS={LOOKBACK_YEARS} is outside the sensible range [1, 20]."
        )
    if COV_METHOD not in ("ewma", "ledoit"):
        errors.append(
            f"COV_METHOD='{COV_METHOD}' is invalid; use 'ewma' or 'ledoit'."
        )
    if not (0.0 < MAX_WEIGHT <= 1.0):
        errors.append(f"MAX_WEIGHT={MAX_WEIGHT} must be in (0, 1].")
    if MIN_STOCKS < 2:
        errors.append(f"MIN_STOCKS={MIN_STOCKS} must be >= 2 for the optimizer.")
    if MAX_STOCKS < MIN_STOCKS:
        errors.append(f"MAX_STOCKS={MAX_STOCKS} must be >= MIN_STOCKS={MIN_STOCKS}.")

    if errors:
        raise RuntimeError(
            "Configuration errors — fix python/.env before running:\n  "
            + "\n  ".join(errors)
        )

    if "example.com" in (SEC_USER_AGENT or ""):
        warnings.warn(
            "SEC_USER_AGENT is still the placeholder value. SEC EDGAR may "
            'rate-limit or block requests. Set SEC_USER_AGENT="Your Project '
            'your@email.com" in python/.env.',
            UserWarning,
            stacklevel=2,
        )
