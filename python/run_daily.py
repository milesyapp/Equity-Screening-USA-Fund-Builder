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

    # Include every research arm's holdings: quantum arms can hold names ranked
    # 101-150 that aren't in the classical top-100, and they must be re-priced
    # too or their forward marks would silently drop those names.
    arm_tickers = set()
    for arm in port.get("research", {}).get("arms", []):
        arm_tickers.update(arm.get("weights", {}).keys())

    from core import data_fetcher, metrics, fund
    from reports import market_analyzer

    t0 = time.time()
    max_years = max(settings.FUND_WINDOWS_YEARS)
    close, _ = data_fetcher.download_price_data(
        sorted(set(tickers) | arm_tickers | {bench}), lookback_years=max_years
    )
    if close.empty:
        logger.error("Price refresh returned nothing — leaving latest.json unchanged.")
        return 1

    px = close.ffill()
    last = px.iloc[-1]

    # 1. Refresh trailing returns per held name.
    #    NaN-guarded: a name with leading-NaN history inside the window would
    #    otherwise write float('nan') into latest.json, which json.dumps emits
    #    as a bare NaN token — invalid JSON that JS's JSON.parse rejects,
    #    silently blanking the whole site until the next weekly run.
    for s in stocks:
        t = s["ticker"]
        if t not in px.columns:
            continue
        cur = float(last[t]) if t in last and np.isfinite(last[t]) else None
        for name, days in _RETURN_WINDOWS.items():
            if cur is None or len(px) <= days:
                s[name] = None
                continue
            prev = px[t].iloc[-days - 1]
            s[name] = (cur / float(prev) - 1.0) if np.isfinite(prev) and prev > 0 else None
        if cur is not None:
            s["price"] = cur

    # 2. Rebuild fund NAV / rolling metrics on the SAME holdings & weights.
    held = [t for t in tickers if t in close.columns]
    rets = close[held].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).clip(-0.5, 0.5)
    bench_daily = (
        close[bench].pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).clip(-0.5, 0.5)
        if bench in close.columns else pd.Series(dtype=float)
    )
    # Time-varying rf (v2.3) — one fetch per run; chain inside riskfree.py.
    from core import riskfree
    rf_series = riskfree.get_rf_series()
    refreshed = fund.build_fund(stocks, rets, bench_daily, rf_series)
    refreshed.pop("weights", None)
    # The daily job re-prices against the benchmark FROZEN in latest.json (the
    # one the weekly run selected). Pin the label to that series so a changed
    # settings default can't mislabel the chart between weekly runs.
    refreshed["benchmark"] = bench
    # Preserve the frozen weekly weights already attached to each stock.
    port["fund"] = refreshed

    market = market_analyzer.market_summary()
    port["marketConditions"] = market
    port["pricesAsOf"] = market["date"]

    # 3. Re-mark research arms forward (no re-selection; selection is frozen
    #    between weekly runs, so no solver/D-Wave call here). Keyed on the last
    #    PRICE date so weekend/holiday re-runs dedup onto the real trading day.
    from core import research_log
    prev = port.get("research")
    if prev and prev.get("arms"):
        price_date = (close.index[-1].strftime("%Y-%m-%d")
                      if not close.empty else market["date"])
        arm_returns = {}
        for arm in prev["arms"]:
            w = arm.get("weights", {})
            held_arm = [t for t in w if t in close.columns]
            if not held_arm:
                continue
            last_ret = (close[held_arm].pct_change(fill_method=None)
                        .replace([np.inf, -np.inf], np.nan).iloc[-1].fillna(0.0))
            wser = pd.Series({t: w[t] for t in held_arm}); wser /= (wser.sum() or 1.0)
            arm_returns[arm["key"]] = float((last_ret * wser).sum())
        if arm_returns:
            research_log.append_run_record(price_date, "daily", arm_returns)
            history = research_log.load_history()
            rf_map = riskfree.daily_rf_map(rf_series, [r["date"] for r in history])
            prev["forwardStats"] = research_log.forward_stats(history, rf_daily=rf_map)
            port["research"] = prev

    blob["run_type"] = "daily"
    blob["elapsed_seconds"] = round(time.time() - t0, 1)
    blob["date"] = market["date"]

    _DATA.write_text(json.dumps(blob, default=str))
    logger.info("Daily refresh done in %.1fs — %d holdings re-priced, ranks frozen.",
                blob["elapsed_seconds"], len(held))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
