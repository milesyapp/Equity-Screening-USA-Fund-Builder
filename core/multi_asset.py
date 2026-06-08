"""
Multi-asset allocation pipeline (the new top layer).

Flow:
  1. Detect the market regime (VIX-based) -> sizes the cash sleeve.
  2. Fetch the asset-class ETF proxies from Alpaca.
  3. Risk-balance the six RISKY assets (risk parity / ERC -- no return forecast).
  4. Carve out cash per the regime; scale the risky weights to fit.
  5. Metrics on the blended portfolio, a now-meaningful CROSS-ASSET frontier,
     and a transparent 60/40 benchmark plus an S&P-500 context line.

The equity slice is represented here by the broad equity ETF (IVV). A later
pass fills that slice with individually selected stocks (the fundamental-tilted
sleeve), at which point the per-stock detail returns.

`build_allocation()` is pure (takes already-fetched data) so it can be unit
tested without any network access.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import settings
from core import asset_allocator, metrics, portfolio_optimizer

logger = logging.getLogger(__name__)


def _clean_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Prices -> a safe daily-return matrix (same hygiene as the equity path)."""
    prices = prices.loc[:, ~prices.columns.duplicated()].sort_index()
    rets = prices.pct_change(fill_method=None)
    rets = rets.replace([np.inf, -np.inf], np.nan)
    rets = rets.dropna(axis=1, thresh=int(len(rets) * 0.95))
    rets = rets.clip(lower=-0.5, upper=0.5)
    rets = rets.dropna(how="any")
    rets = rets.loc[:, rets.std() > 1e-10]
    return rets


def _bench_block(name: str, daily: pd.Series) -> dict:
    return {
        "name": name,
        "annualReturn": metrics.annual_return(daily),
        "annualVolatility": metrics.annual_volatility(daily),
        "sharpeRatio": metrics.sharpe_ratio(daily),
        "maximumDrawdown": metrics.maximum_drawdown(daily),
    }


def build_allocation(close: pd.DataFrame, market: dict) -> dict:
    """Pure allocation logic. `close` holds adjusted closes for the asset-class
    ETFs (+ cash); `market` is the market_analyzer summary dict."""
    regime = market.get("riskSentiment", "neutral")
    risky_keys = [a["key"] for a in settings.ASSET_CLASSES]
    cash_key = settings.CASH_TICKER

    present = [t for t in (risky_keys + [cash_key]) if t in close.columns]
    cleaned = _clean_returns(close[present])

    risky = [k for k in risky_keys if k in cleaned.columns]
    if len(risky) < 2:
        raise RuntimeError(f"Only {len(risky)} asset-class series usable; need >= 2.")
    risky_daily = cleaned[risky]

    # --- risk-balanced weights over the risky assets (no return forecast) ---
    alloc = asset_allocator.allocate(risky_daily, method=settings.ALLOCATION_METHOD)
    rp_w, rc = alloc["weights"], alloc["riskContributions"]

    # --- cash sleeve sized from the regime ---
    cash_w = settings.CASH_BY_REGIME.get(regime, 0.05)
    if cash_key not in cleaned.columns:
        cash_w = 0.0
    full = {k: rp_w[k] * (1.0 - cash_w) for k in risky}
    if cash_w > 0:
        full[cash_key] = cash_w

    # --- blended portfolio metrics (beta measured vs US equity) ---
    weights_series = pd.Series(full)
    port_daily = metrics.portfolio_daily_returns(
        cleaned[list(weights_series.index)], weights_series
    )
    eq = settings.BENCHMARK_EQUITY
    market_daily = cleaned[eq] if eq in cleaned.columns else None
    metric_summary = metrics.summary(port_daily, market_daily)

    # --- cross-asset efficient frontier (uncapped corners) ---
    frontier = portfolio_optimizer.efficient_frontier(risky_daily, w_max=1.0)

    # --- benchmarks: transparent stock/bond blend + S&P context ---
    bd = settings.BENCHMARK_BOND
    ew = settings.BENCHMARK_EQUITY_WEIGHT
    benchmark = equity_context = None
    if eq in cleaned.columns and bd in cleaned.columns:
        bench_daily = ew * cleaned[eq] + (1.0 - ew) * cleaned[bd]
        benchmark = _bench_block(
            f"{int(ew*100)}/{int((1-ew)*100)} stocks/bonds", bench_daily
        )
    if eq in cleaned.columns:
        equity_context = _bench_block("S&P 500 (100% equity)", cleaned[eq])

    # --- assemble the allocation list ---
    meta = {a["key"]: a for a in settings.ASSET_CLASSES}
    allocation = [
        {
            "key": k,
            "name": meta[k]["name"],
            "assetClass": meta[k]["assetClass"],
            "weight": float(full[k]),
            "riskContribution": float(rc.get(k, 0.0)),
        }
        for k in risky
    ]
    if cash_w > 0:
        allocation.append({
            "key": cash_key,
            "name": settings.CASH_NAME,
            "assetClass": "Cash",
            "weight": float(cash_w),
            "riskContribution": 0.0,
        })
    allocation.sort(key=lambda x: x["weight"], reverse=True)

    logger.info(
        "Multi-asset allocation: %d assets, cash %.0f%%, regime %s",
        len(allocation), cash_w * 100, regime,
    )

    return {
        "date": market.get("date"),
        "approach": "multi-asset",
        "allocationMethod": settings.ALLOCATION_METHOD,
        "marketRegime": regime,
        "cashWeight": float(cash_w),
        "assetAllocation": allocation,
        "metrics": metric_summary,
        "benchmark": benchmark,
        "equityContext": equity_context,
        "efficientFrontier": frontier,
        "marketConditions": market,
    }


class MultiAssetPipeline:
    def run(self) -> dict:
        from reports import market_analyzer  # noqa: PLC0415
        from core import data_fetcher  # noqa: PLC0415

        market = market_analyzer.market_summary()
        logger.info("Detected market regime: %s", market.get("riskSentiment"))

        tickers = [a["key"] for a in settings.ASSET_CLASSES] + [settings.CASH_TICKER]
        close, _volume = data_fetcher.download_price_data(sorted(set(tickers)))
        return build_allocation(close, market)
