"""
Market-conditions snapshot for the dashboard: weekly moves across headline
gauges (S&P, Nasdaq, Russell, VIX, 10Y, gold) plus a VIX-threshold regime
label (risk-on / neutral / risk-off). DISPLAY ONLY — the regime annotates the
page and the run record; it does not alter selection, scoring, or weights.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from config import settings

logger = logging.getLogger(__name__)

# Representative gauges across risk appetite, rates, and safe havens.
_GAUGES = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^RUT": "Russell 2000",
    "^VIX": "VIX",
    "^TNX": "10Y Treasury Yield",
    "GLD": "Gold",
}


def _weekly_change(ticker: str) -> dict | None:
    try:
        end = datetime.now()
        start = end - timedelta(days=10)  # buffer for non-trading days
        hist = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if hist.empty:
            return None
        close = hist["Close"].dropna()
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        last = float(close.iloc[-1])
        prev = float(close.iloc[0])
        return {"ticker": ticker, "price": last, "weeklyReturn": (last / prev) - 1.0}
    except Exception as e:  # noqa: BLE001
        logger.debug("Gauge failed for %s: %s", ticker, e)
        return None


def detect_regime(vix_level: float | None) -> str:
    if vix_level is None:
        return "neutral"
    if vix_level < settings.VIX_RISK_ON_BELOW:
        return "risk-on"
    if vix_level > settings.VIX_RISK_OFF_ABOVE:
        return "risk-off"
    return "neutral"


def market_summary() -> dict:
    """Returns a dict shaped to match the frontend MarketConditions type."""
    gauges = {}
    for tk, name in _GAUGES.items():
        res = _weekly_change(tk)
        if res:
            gauges[name] = res

    vix = gauges.get("VIX", {}).get("price")
    sp500 = gauges.get("S&P 500", {}).get("weeklyReturn", 0.0)
    nasdaq = gauges.get("Nasdaq Composite", {}).get("weeklyReturn", 0.0)
    tnx = gauges.get("10Y Treasury Yield", {}).get("price", 0.0)

    regime = detect_regime(vix)
    vol_level = "high" if (vix and vix > 30) else "moderate" if (vix and vix > 20) else "low"

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "vix": round(vix, 2) if vix else None,
        "sp500Return": sp500,
        "nasdaqReturn": nasdaq,
        "treasuryYield": tnx,
        "riskSentiment": regime,
        "volatilityLevel": vol_level,
        "marketSummary": gauges,
    }
