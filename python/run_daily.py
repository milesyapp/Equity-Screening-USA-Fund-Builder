#!/usr/bin/env python3
"""
Daily refresh — re-price the frozen weekly selection.

Reads the existing data/latest.json, keeps the SAME ranked holdings and their
score weights (frozen from the weekly run), and refreshes only the price-derived
fields: trailing returns per name and the fund's NAV / rolling metrics. Ranks do
NOT change between weekly runs — this keeps the day-to-day view stable while
prices stay current.

Usage:
    cd python && python3 run_daily.py            # updates ../data/latest.json in place

If no prior weekly run exists, it tells you to run run_screen.py first.
"""
from __future__ import annotations

import json
import sys
import time
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("run_daily")

_DATA = Path(__file__).resolve().parent.parent / "data" / "latest.json"
_RETURN_WINDOWS = {"return1W": 5, "return1M": 21, "return3M": 63,
                   "return6M": 126, "return1Y": 252}


def main() -> int:
    from config import settings
    try:
        settings.validate()
    except RuntimeError as e:
        logger.error("%s", e)
        return 1

    if not _DATA.exists():
        logger.error("No %s found. Run run_screen.py first to create the weekly selection.", _DATA)
        return 1

    blob = json.loads(_DATA.read_text())
    if not blob.get("success") or "portfolio" not in blob:
        logger.error("latest.json has no usable portfolio. Run run_screen.py.")
        return 1

    port = blob["portfolio"]
    stocks = port["stocks"]
    tickers = [s["ticker"] for s in stocks]
    bench = port.get("fund", {}).get("benchmark", settings.SCREENER_BENCHMARK)

    from core import data_fetcher, metrics, fund
    from reports import market_analyzer

    t0 = time.time()
    max_years = max(settings.FUND_WINDOWS_YEARS)
    close, _ = data_fetcher.download_price_data(
        sorted(set(tickers + [bench])), lookback_years=max_years
    )
    if close.empty:
        logger.error("Price refresh returned nothing — leaving latest.json unchanged.")
        return 1

    px = close.ffill()
    last = px.iloc[-1]

    # 1. Refresh trailing returns per held name.
    for s in stocks:
        t = s["ticker"]
        if t not in px.columns:
            continue
        for name, days in _RETURN_WINDOWS.items():
            s[name] = (float(last[t] / px[t].iloc[-days - 1]) - 1.0) if len(px) > days else None
        s["price"] = float(last[t]) if t in last else s.get("price")

    # 2. Rebuild fund NAV / rolling metrics on the SAME holdings & weights.
    held = [t for t in tickers if t in close.columns]
    rets = close[held].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).clip(-0.5, 0.5)
    bench_daily = (
        close[bench].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).clip(-0.5, 0.5)
        if bench in close.columns else pd.Series(dtype=float)
    )
    refreshed = fund.build_fund(stocks, rets, bench_daily)
    refreshed.pop("weights", None)
    # Preserve the frozen weekly weights already attached to each stock.
    port["fund"] = refreshed

    market = market_analyzer.market_summary()
    port["marketConditions"] = market
    port["pricesAsOf"] = market["date"]

    blob["run_type"] = "daily"
    blob["elapsed_seconds"] = round(time.time() - t0, 1)
    blob["date"] = market["date"]

    _DATA.write_text(json.dumps(blob, default=str))
    logger.info("Daily refresh done in %.1fs — %d holdings re-priced, ranks frozen.",
                blob["elapsed_seconds"], len(held))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
