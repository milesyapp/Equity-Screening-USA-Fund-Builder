"""
US stock screener — the v2.0 pipeline.

  1. Universe: S&P 500/400/600 constituents (+ GICS sector) from Wikipedia.
  2. Prices: Alpaca daily bars, FUND_WINDOWS max-years lookback.
  3. Screen: keep names with >= SCREENER_MIN_HISTORY_YEARS of clean history,
     above the liquidity/price floors.
  4. Momentum: 1W / 1M / 3M / 6M / 1Y trailing price returns per name.
  5. Fundamentals: SEC EDGAR for every survivor (graceful per-name).
  6. Score: health / valuation / momentum -> composite (scoring.py).
  7. Rank: top SCREENER_TOP_N by composite score.
  8. Fund: score-weighted basket + rolling metrics + NAV series (fund.py).

The output dict is wrapped by run_screen.py into the PipelineOutput shape the
Next.js frontend reads from data/latest.json.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import settings
from core import data_fetcher, fundamentals, metrics, scoring, fund
from reports import market_analyzer

logger = logging.getLogger(__name__)

_RETURN_WINDOWS = {
    "return1W": 5,
    "return1M": 21,
    "return3M": 63,
    "return6M": 126,
    "return1Y": 252,
}

_FUND_FIELDS = (
    "peRatio", "dividendYield", "grossMargin", "operatingMargin", "netMargin",
    "returnOnEquity", "fcfMargin", "fcfYield", "revenueGrowth", "debtToEquity",
    "marketCap",
)


def _clean_returns(prices: pd.DataFrame) -> pd.DataFrame:
    prices = prices.loc[:, ~prices.columns.duplicated()].sort_index()
    rets = prices.pct_change(fill_method=None)
    rets = rets.replace([np.inf, -np.inf], np.nan)
    rets = rets.clip(lower=-0.5, upper=0.5)
    return rets


def _trailing_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Trailing simple price returns over each window, per ticker."""
    px = prices.ffill()
    last = px.iloc[-1]
    out = {}
    for name, days in _RETURN_WINDOWS.items():
        if len(px) > days:
            out[name] = (last / px.iloc[-days - 1]) - 1.0
        else:
            out[name] = pd.Series(np.nan, index=px.columns)
    return pd.DataFrame(out)


def run() -> dict:
    market = market_analyzer.market_summary()

    # 1. Universe ------------------------------------------------------------
    meta = data_fetcher.get_universe()
    universe = list(meta)
    universe_size = len(universe)

    # 2. Prices (max window so we can compute 5Y fund metrics) --------------
    max_years = max(settings.FUND_WINDOWS_YEARS)
    close, volume = data_fetcher.download_price_data(universe, lookback_years=max_years)

    # 3. Screen on history length + liquidity + price -----------------------
    min_obs = int(settings.SCREENER_MIN_HISTORY_YEARS * settings.TRADING_DAYS)
    # Volume floor depends on the feed: IEX reports only its own ~2-3% slice of
    # total volume, so it needs a far lower floor than consolidated SIP volume.
    on_iex = settings.ALPACA_FEED == "iex"
    vol_floor = settings.MIN_AVG_VOLUME_IEX if on_iex else settings.MIN_AVG_VOLUME
    logger.info(
        "Liquidity floor: %s avg shares/day (%s feed)",
        f"{vol_floor:,}", settings.ALPACA_FEED,
    )
    exclusions = {"insufficientHistory": 0, "lowLiquidity": 0, "lowPrice": 0,
                  "missingFundamentals": 0, "noHealthData": 0}

    survivors = []
    avg_vol = volume.mean()
    last_px = close.ffill().iloc[-1]
    for t in close.columns:
        series = close[t].dropna()
        if len(series) < min_obs:
            exclusions["insufficientHistory"] += 1
            continue
        if avg_vol.get(t, 0) < vol_floor:
            exclusions["lowLiquidity"] += 1
            continue
        if last_px.get(t, 0) < settings.MIN_PRICE:
            exclusions["lowPrice"] += 1
            continue
        survivors.append(t)

    logger.info(
        "Screen: %d/%d names passed history+liquidity (%d too short, %d illiquid, %d sub-$%g)",
        len(survivors), universe_size, exclusions["insufficientHistory"],
        exclusions["lowLiquidity"], exclusions["lowPrice"], settings.MIN_PRICE,
    )

    # 4. Momentum / trailing returns ----------------------------------------
    trailing = _trailing_returns(close[survivors])

    # 5. Fundamentals (EDGAR) for survivors ---------------------------------
    prices_now = last_px[survivors].to_dict()
    funds = fundamentals.fetch_for(survivors, meta, prices_now)
    fund_df = pd.DataFrame.from_dict(funds, orient="index")

    # Drop names with NO health data at all — too opaque to rank honestly.
    health_cols = [c for c in scoring.HEALTH_FACTORS if c in fund_df.columns]
    has_health = fund_df[health_cols].notna().any(axis=1)
    dropped_no_health = (~has_health).sum()
    exclusions["noHealthData"] = int(dropped_no_health)
    fund_df = fund_df[has_health]
    scored_tickers = list(fund_df.index)
    logger.info("Fundamentals usable for scoring on %d names (%d dropped: no health data)",
                len(scored_tickers), int(dropped_no_health))

    # 6. Score ---------------------------------------------------------------
    scores = scoring.score_universe(fund_df, trailing.loc[scored_tickers])
    combined = fund_df.join(scores).join(trailing, how="left")

    # Sector P/E medians for valuation context in the reasons.
    combined["sector"] = [meta.get(t, {}).get("sector", "Unknown") for t in combined.index]
    sector_pe = combined.groupby("sector")["peRatio"].median().to_dict()

    # 7. Rank top N ----------------------------------------------------------
    ranked = combined.sort_values("score", ascending=False).head(settings.SCREENER_TOP_N)

    stocks = []
    for rank, (t, row) in enumerate(ranked.iterrows(), start=1):
        m = meta.get(t, {})
        rowd = row.to_dict()
        reasons, flags = scoring.build_reasons(rowd, sector_pe.get(m.get("sector")))
        stocks.append({
            "rank": rank,
            "ticker": t,
            "name": m.get("name", t),
            "sector": m.get("sector", "Unknown"),
            "subIndustry": m.get("subIndustry", ""),
            "price": _f(last_px.get(t)),
            "score": _f(row.get("score")),
            "healthScore": _f(row.get("healthScore")),
            "valuationScore": _f(row.get("valuationScore")),
            "momentumScore": _f(row.get("momentumScore")),
            **{k: _f(row.get(k)) for k in _FUND_FIELDS},
            **{k: _f(row.get(k)) for k in _RETURN_WINDOWS},
            "reasons": reasons,
            "flags": flags,
        })

    # 8. Fund ----------------------------------------------------------------
    returns = _clean_returns(close[scored_tickers])
    bench_close, _ = data_fetcher.download_price_data(
        [settings.SCREENER_BENCHMARK], lookback_years=max_years
    )
    bench_daily = _clean_returns(bench_close).iloc[:, 0] if not bench_close.empty else pd.Series(dtype=float)
    the_fund = fund.build_fund(stocks, returns, bench_daily)
    # Attach each stock's fund weight for display.
    fw = the_fund.pop("weights", {})
    for s in stocks:
        s["fundWeight"] = round(fw.get(s["ticker"], 0.0), 5)

    # 9. Research arms + forward logging ------------------------------------
    from core import research_log

    def _latest_return(weights: dict, rets) -> float | None:
        """Most-recent-day portfolio return for a set of frozen weights."""
        held = [t for t in weights if t in rets.columns]
        if not held or rets.empty:
            return None
        last = rets[held].iloc[-1].fillna(0.0)
        w = pd.Series({t: weights[t] for t in held}); w /= (w.sum() or 1.0)
        return float((last * w).sum())

    # Key the forward record on the actual last PRICE date, never the run date:
    # the daily job runs Tue-Sun, so run-date keying would log the same Friday
    # return again on Sat/Sun. Price-date keying dedups those onto the real day.
    price_date = (returns.index[-1].strftime("%Y-%m-%d")
                  if not returns.empty else market["date"])

    greedy_arm = research_log.make_arm(
        "greedy", the_fund,
        selection=[s["ticker"] for s in stocks],
        weights=fw,
    )
    arms = [greedy_arm]

    # --- QUBO arms ---------------------------------------------------------
    # Build the candidate pool, build the QUBO ONCE, and solve that identical
    # problem with (a) a classical sampler -> qubo_classical, and (b) when a
    # D-Wave token is configured, real hardware -> qubo_quantum. Solving the
    # SAME QUBO with both isolates the quantum-solver effect from the
    # objective-function effect. Wrapped so a quantum failure can never break
    # the live classical pipeline.
    try:
        from core import quantum_fund
        cand_ranked = combined.sort_values("score", ascending=False).head(
            quantum_fund.candidate_pool_size()
        )
        candidates = []
        for t, row in cand_ranked.iterrows():
            m = meta.get(t, {})
            candidates.append({
                "ticker": t,
                "score": _f(row.get("score")),
                "sector": m.get("sector", "Unknown"),
                **{k: _f(row.get(k)) for k in _FUND_FIELDS},
            })

        problem = quantum_fund.build_qubo(candidates, returns)

        sel_c, diag_c = quantum_fund.solve(problem, "sim")
        f_c, w_c = quantum_fund.build_fund_from_selection(sel_c, candidates, returns, bench_daily)
        arms.append(research_log.make_arm("qubo_classical", f_c, sel_c, w_c, diag_c))

        if quantum_fund.hardware_available():
            sel_q, diag_q = quantum_fund.solve(problem, quantum_fund.production_sampler())
            f_q, w_q = quantum_fund.build_fund_from_selection(sel_q, candidates, returns, bench_daily)
            arms.append(research_log.make_arm("qubo_quantum", f_q, sel_q, w_q, diag_q))
        else:
            logger.info("No DWAVE_API_TOKEN — qubo_quantum skipped; logging classical QUBO only.")
    except Exception as e:  # noqa: BLE001 — never let the quantum arm break the pipeline
        logger.exception("Quantum fund arm failed; continuing with available arms: %s", e)

    arm_returns = {a["key"]: _latest_return(a["weights"], returns) for a in arms}
    research_log.append_run_record(
        price_date, "weekly", arm_returns,
        rebalance={"selectionByArm": {a["key"]: a["selection"] for a in arms}},
    )
    research_block = research_log.build_research_block(arms, as_of=market["date"])

    return {
        "asOf": market["date"],
        "universeSize": universe_size,
        "screenedCount": len(survivors),
        "scoredCount": len(scored_tickers),
        "excludedCount": universe_size - len(scored_tickers),
        "exclusionReasons": exclusions,
        "minHistoryYears": settings.SCREENER_MIN_HISTORY_YEARS,
        "methodology": {
            "weights": settings.SCORE_WEIGHTS,
            "healthFactors": list(scoring.HEALTH_FACTORS),
            "valuationFactors": list(scoring.VALUATION_FACTORS),
            "momentumFactors": list(scoring.MOMENTUM_FACTORS),
        },
        "stocks": stocks,
        "fund": the_fund,
        "research": research_block,
        "marketConditions": market,
    }


def _f(x):
    if x is None:
        return None
    try:
        if isinstance(x, float) and np.isnan(x):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(x, (np.floating, np.integer)):
        return float(x)
    return x
