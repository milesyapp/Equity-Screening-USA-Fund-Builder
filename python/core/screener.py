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
from core import data_fetcher, fundamentals, metrics, riskfree, scoring, fund
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
    # GICS sector per name (never sub-industry): health/valuation percentiles
    # rank within these groups (v2.3 sector-neutral regime, 2026-06-12).
    sectors = pd.Series(
        {t: meta.get(t, {}).get("sector", "Unknown") for t in scored_tickers})
    scores = scoring.score_universe(
        fund_df, trailing.loc[scored_tickers], sectors=sectors)
    combined = fund_df.join(scores).join(trailing, how="left")

    # Sector P/E medians for valuation context in the reasons.
    combined["sector"] = sectors.reindex(combined.index)
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
    # Time-varying risk-free rate (v2.3): fetched once per run, threaded
    # into every rf-dependent metric. Resilience chain inside riskfree.py.
    rf_series = riskfree.get_rf_series()
    the_fund = fund.build_fund(stocks, returns, bench_daily, rf_series)
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
        f_c, w_c, wdiag_c = quantum_fund.build_fund_from_selection(
            sel_c, candidates, returns, bench_daily, rf_series, problem=problem)
        diag_c.update(wdiag_c)
        arms.append(research_log.make_arm("qubo_classical", f_c, sel_c, w_c, diag_c))

        if quantum_fund.hardware_available():
            sel_q, diag_q = quantum_fund.solve(problem, quantum_fund.production_sampler())
            # IDENTICAL stage-two weighting for the quantum arm: weighting is
            # a deterministic function of selection, so the classical-vs-
            # quantum gap remains a pure solver comparison.
            f_q, w_q, wdiag_q = quantum_fund.build_fund_from_selection(
                sel_q, candidates, returns, bench_daily, rf_series, problem=problem)
            diag_q.update(wdiag_q)
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
    history = research_log.load_history()
    rf_map = riskfree.daily_rf_map(rf_series, [r["date"] for r in history])
    research_block = research_log.build_research_block(
        arms, as_of=market["date"], history=history, rf_daily=rf_map)

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
            # v2.3: health/valuation percentiles rank within GICS sector;
            # momentum is deliberately universe-wide (it exists to capture
            # sector trends). Thin (< minCount) and "Unknown" sectors fall
            # back to universe-wide ranks per factor.
            "sectorNeutral": {
                "pillars": ["health", "valuation"],
                "groupBy": "GICS sector",
                "minCount": settings.SECTOR_NEUTRAL_MIN_COUNT,
                "momentumScope": "universe-wide (deliberate)",
            },
            # Known, disclosed limitations — rendered verbatim on the frontend.
            # These are structural to the data available, not bugs; the forward
            # log (data/research_log.jsonl) is the only out-of-sample evidence.
            "limitations": [
                "Survivorship bias: the universe is CURRENT S&P 1500 membership, so "
                "names delisted or acquired during the lookback are absent and the "
                "backward-looking NAV/metrics are biased upward.",
                "Point-in-time violation: fundamentals come from each company's most "
                "recent annual filing (up to ~15 months old) and are applied to "
                "today's ranks; historical-window metrics apply today's holdings and "
                "weights backward — an in-sample characterisation, not a track record.",
                "Only the forward record accumulated in data/research_log.jsonl from "
                "each arm's inception is out-of-sample evidence.",
                f"Benchmark is {settings.SCREENER_BENCHMARK} (S&P 1500 composite), "
                "matching the selection universe so alpha/beta are not size-exposure "
                "artifacts; no further factor attribution is performed.",
                "On the free IEX feed, volume reflects only IEX's ~2-3% venue share; "
                "the liquidity floor is adjusted accordingly and capacity of the "
                "paper portfolio is not modeled.",
                "Scoring regime change on 2026-06-12: health and valuation factors "
                "are now percentile-ranked within GICS sector (momentum deliberately "
                "remains universe-wide); before that date all ranks were "
                "universe-wide. Measured impact on the change date: 28 of the top "
                "100 replaced; Financials fell from 32 to 8 fund slots after "
                "dominating the universe-wide ranking at ~2.3x their universe share "
                "via bank/insurer margins and ROE. Forward-log rows before "
                "2026-06-12 were selected under the old regime.",
                "Risk-free rate change on 2026-06-12: Sharpe, Sortino, CAPM alpha "
                "and the probabilistic Sharpe ratio now use the contemporaneous "
                "3-month T-bill yield (U.S. Treasury daily par curve — the series "
                "FRED republishes as DGS3MO; cached fallback, then the 4% "
                "constant) instead of a hardcoded 4%. Selections are unaffected — "
                "scoring never used rf — so printed risk-adjusted metrics shift "
                "(3Y Sharpe ~ -0.05 at the change date, rates having averaged "
                "4.7% over that window) but the forward log has no structural "
                "break.",
                "Weighting regime change on 2026-06-12: the QUBO arms moved from "
                "score weights to weights derived from the continuous relaxation "
                "of the QUBO objective (same lambdas and covariance; greedy "
                "remains score-weighted as the baseline). Selections are "
                "unchanged, but forward-log rows before this date used score "
                "weights for all arms. Measured at the change date: weight "
                "turnover ~0.68, predicted vol 10.8% -> 10.5%, effective N "
                "98 -> ~27 with ~21 names at the 4% cap. The concentration is "
                "the continuous optimum, not a tuning artifact — long-only "
                "mean-variance genuinely prefers ~27 effective names — and the "
                "QUBO arms' effective breadth is now jointly set by the "
                "objective and the per-name cap, a cap inherited from the "
                "greedy fund's design rather than chosen for this role.",
            ],
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
