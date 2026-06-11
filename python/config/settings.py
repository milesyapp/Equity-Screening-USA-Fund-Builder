"""
Central configuration for the US equity screener + research pipeline.
Values can be overridden via environment variables (python/.env).

v2.1: removed the dead v1 multi-asset allocator block (ASSET_CLASSES, cash
sleeves, risk-parity/min-variance knobs, 60/40 benchmark) — nothing imported
it. COV_METHOD / EWMA_HALFLIFE / LOOKBACK_YEARS are now genuinely consumed by
core/covariance.py (the QUBO risk term), so the documented covariance
methodology finally matches the code. Default benchmark corrected to SPTM.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load python/.env (this file is python/config/settings.py -> parent.parent = python/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

VERSION = "2.1.0"

# ── US STOCK SCREENER ────────────────────────────────────────────────────────
#
# Screens the broad US universe (S&P 500/400/600), scores every name that has
# >= SCREENER_MIN_HISTORY_YEARS of price history and usable fundamentals, ranks
# the top SCREENER_TOP_N, and builds a score-weighted "mini-fund" from them.
#
# Methodology weights (must sum to 1.0 — enforced in validate()). Stated
# verbatim on the frontend.
SCREENER_TOP_N = int(os.getenv("SCREENER_TOP_N", 100))
SCREENER_MIN_HISTORY_YEARS = float(os.getenv("SCREENER_MIN_HISTORY_YEARS", 3.0))

SCORE_WEIGHTS = {
    "health":    float(os.getenv("SCORE_W_HEALTH", 0.70)),
    "valuation": float(os.getenv("SCORE_W_VALUATION", 0.20)),
    "momentum":  float(os.getenv("SCORE_W_MOMENTUM", 0.10)),
}

# Per-name cap inside the score-weighted fund (renormalized after capping).
SCREENER_MAX_WEIGHT = float(os.getenv("SCREENER_MAX_WEIGHT", 0.04))

# Benchmark the fund is measured against (alpha/beta).
#
# WHY SPTM (changed from IVV in v2.1): the selection universe is the S&P
# Composite 1500 (500 large + 400 mid + 600 small). IVV tracks only the S&P
# 500, so part of every "alpha" measured against it was simply mid/small-cap
# size exposure, not selection skill. SPTM tracks the S&P 1500 itself — the
# benchmark now spans exactly the universe the screener picks from, so
# alpha/beta isolate selection rather than size.
SCREENER_BENCHMARK = os.getenv("SCREENER_BENCHMARK", "SPTM")

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

# --- Universe ---
# Broad US universe = S&P 500 (large) + S&P 400 (mid) + S&P 600 (small).
# Set USE_SMALLCAP=False for a faster run.
USE_MIDCAP = os.getenv("USE_MIDCAP", "true").lower() == "true"
USE_SMALLCAP = os.getenv("USE_SMALLCAP", "true").lower() == "true"

# --- Covariance estimation (consumed by core/covariance.py for the QUBO) ---
#
# LOOKBACK_YEARS: estimation window for the candidate-pool covariance that
#   feeds the QUBO risk term. 3 years (~750 daily observations) is enough for
#   a 150-name matrix while staying representative of the current correlation
#   regime; longer windows drag in stale regimes at full weight.
#
# COV_METHOD:
#   "ewma"   — exponentially-weighted covariance (default). EWMA_HALFLIFE=63
#              (~3 months) is the RiskMetrics standard: a shock decays to 50%
#              influence after 63 trading days instead of persisting at full
#              weight for the whole window.
#   "ledoit" — Ledoit-Wolf shrinkage of the sample covariance; the
#              well-conditioned choice when names ≈ observations.
#   "sample" — plain sample covariance (escape hatch / tests).
LOOKBACK_YEARS = int(os.getenv("LOOKBACK_YEARS", 3))
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

# --- Risk-free rate for Sharpe / CAPM alpha (annualized) ---
RISK_FREE_RATE = float(os.getenv("RISK_FREE_RATE", 0.04))

# --- Market regime detection (display only — does not alter selection) ---
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
    if abs(sum(SCORE_WEIGHTS.values()) - 1.0) > 1e-6:
        errors.append(
            f"SCORE_WEIGHTS must sum to 1.0 (got {sum(SCORE_WEIGHTS.values()):.4f}); "
            "the frontend states these weights verbatim."
        )
    if not (0.0 < SCREENER_MAX_WEIGHT <= 1.0):
        errors.append(
            f"SCREENER_MAX_WEIGHT={SCREENER_MAX_WEIGHT} must be in (0, 1]."
        )
    if LOOKBACK_YEARS < 1 or LOOKBACK_YEARS > 20:
        errors.append(
            f"LOOKBACK_YEARS={LOOKBACK_YEARS} is outside the sensible range [1, 20]."
        )
    if COV_METHOD not in ("ewma", "ledoit", "sample"):
        errors.append(
            f"COV_METHOD='{COV_METHOD}' is invalid; use 'ewma', 'ledoit', or 'sample'."
        )
    if EWMA_HALFLIFE < 2:
        errors.append(f"EWMA_HALFLIFE={EWMA_HALFLIFE} must be >= 2 trading days.")

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
