"""
End-to-end equity pipeline. Output dict matches the TypeScript `PortfolioData`
shape the Next.js frontend expects.

Note: the active entry point for the multi-asset weekly run is
core/multi_asset.py (MultiAssetPipeline). This equity-only pipeline is retained
for reference and future use as the stock-selection sub-layer.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import settings
from core import data_fetcher, filters, metrics, portfolio_optimizer, fundamentals
from reports import market_analyzer

logger = logging.getLogger(__name__)


class PortfolioPipeline:
    def run(self) -> dict:
        # 1. Market regime (drives the sector tilt) ---------------------------
        market = market_analyzer.market_summary()
        regime = market["riskSentiment"]
        logger.info("Detected market regime: %s", regime)

        # 2. Universe (ticker -> {name, sector, subIndustry}) + Alpaca prices
        meta = data_fetcher.get_universe()
        sector_map = {t: m["sector"] for t, m in meta.items()}
        universe = list(meta)
        close, volume = data_fetcher.download_price_data(universe)

        # 3. Liquidity floor, then regime-based sector tilt -----------------
        liquid = filters.liquidity_screen(close, volume)
        quality = filters.quality_screen(liquid, sector_map, regime)

        if len(quality) < settings.MIN_STOCKS:
            raise RuntimeError(f"Only {len(quality)} names passed screening.")

        # 4. Build a CLEAN return matrix, then optimize ---------------------
        daily = _clean_returns(close[quality])
        if daily.shape[0] < 200 or daily.shape[1] < settings.MIN_STOCKS:
            raise RuntimeError(
                f"Insufficient clean data ({daily.shape[0]} days, "
                f"{daily.shape[1]} names). The price download was likely "
                "incomplete (rate-limited / cache error). Clear the yfinance "
                "cache and re-run, or wait a while and retry."
            )
        result = portfolio_optimizer.optimize(daily)
        weights = result["weights"]

        # 5. Metrics on the realized portfolio series ------------------------
        held = list(weights.index)
        port_daily = metrics.portfolio_daily_returns(daily[held], weights)
        metric_summary = metrics.summary(port_daily, None)

        # 6. Efficient frontier for the chart --------------------------------
        frontier = portfolio_optimizer.efficient_frontier(daily[held])

        # 7. Per-stock detail (matches Stock type) ---------------------------
        avg_vol = volume.mean()
        first_last = close[held].ffill()
        total_ret = (first_last.iloc[-1] / first_last.iloc[0]) - 1.0
        prices_now = first_last.iloc[-1]

        # 7b. Fundamentals from SEC EDGAR for the held names (graceful on failure)
        try:
            funds = fundamentals.fetch_for(held, meta, prices_now.to_dict())
        except Exception as e:  # noqa: BLE001
            logger.warning("Fundamentals stage failed wholesale: %s", e)
            funds = {}

        stocks = []
        for t in held:
            m = meta.get(t, {})
            f = funds.get(t, {})
            stocks.append({
                "ticker": t,
                "name": m.get("name", t),
                "weight": float(weights[t]),
                "avgVolume": _clean(avg_vol.get(t), 0.0),
                "totalReturn": float(total_ret.get(t, 0)),
                "sector": m.get("sector", "Unknown"),
                "subIndustry": m.get("subIndustry", ""),
                "peRatio": f.get("peRatio"),
                "dividendYield": f.get("dividendYield"),
                "grossMargin": f.get("grossMargin"),
                "operatingMargin": f.get("operatingMargin"),
                "netMargin": f.get("netMargin"),
                "returnOnEquity": f.get("returnOnEquity"),
                "fcfMargin": f.get("fcfMargin"),
                "fcfYield": f.get("fcfYield"),
                "revenueGrowth": f.get("revenueGrowth"),
                "debtToEquity": f.get("debtToEquity"),
                "marketCap": f.get("marketCap"),
            })
        stocks.sort(key=lambda s: s["weight"], reverse=True)

        return {
            "date": market["date"],
            "weights": {t: float(w) for t, w in weights.items()},
            "metrics": metric_summary,
            "stocks": stocks,
            "fundamentals": fundamentals.portfolio_aggregates(stocks),
            "marketRegime": regime,
            "efficientFrontier": frontier,
            "marketConditions": market,
        }


def _clean(value, default=None):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    return float(value)


def _clean_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Convert prices to a daily-return matrix safe for covariance math."""
    prices = prices.loc[:, ~prices.columns.duplicated()].sort_index()
    rets = prices.pct_change(fill_method=None)
    rets = rets.replace([np.inf, -np.inf], np.nan)
    rets = rets.dropna(axis=1, thresh=int(len(rets) * 0.95))
    rets = rets.clip(lower=-0.5, upper=0.5)
    rets = rets.dropna(how="any")
    rets = rets.loc[:, rets.std() > 1e-8]
    return rets
