"""
Screening logic.

We screen on characteristics, never on past return over the optimization window
(that would be look-ahead bias). With Alpaca's free IEX feed reporting only
partial volume, tradeable liquidity is assured primarily by S&P-index membership
(the universe itself), so the explicit screen is a light price floor plus the
regime-based sector tilt.
"""
from __future__ import annotations

import logging

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

# Official GICS sector names, exactly as they appear in the Wikipedia tables.
_DEFENSIVE = {"Health Care", "Consumer Staples", "Utilities"}
_CYCLICAL = {"Information Technology", "Industrials",
             "Consumer Discretionary", "Financials"}


def liquidity_screen(close: pd.DataFrame, volume: pd.DataFrame) -> list:
    """Light price floor. S&P-index membership already guarantees liquidity."""
    last_price = close.ffill().iloc[-1]
    passes = last_price > settings.MIN_PRICE
    survivors = passes[passes].index.tolist()
    logger.info(
        "Liquidity screen (price > $%.0f): %d / %d passed",
        settings.MIN_PRICE, len(survivors), close.shape[1],
    )
    return survivors


def quality_screen(tickers: list, sector_map: dict, regime: str) -> list:
    """Soft regime-based sector tilt. Never starves the optimizer of names."""
    if regime == "risk-off":
        preferred = [t for t in tickers if sector_map.get(t) in _DEFENSIVE]
    elif regime == "risk-on":
        preferred = [t for t in tickers if sector_map.get(t) in _CYCLICAL]
    else:
        preferred = list(tickers)

    result = preferred if len(preferred) >= settings.MAX_STOCKS else list(tickers)
    logger.info("Sector tilt (%s regime): %d names", regime, len(result))
    return result
