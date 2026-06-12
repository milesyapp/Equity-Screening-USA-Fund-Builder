#!/usr/bin/env python3
"""
Offline validation + sample-data generator.

Exercises the pure scoring + fund math with synthetic-but-realistic data (no
network), asserts invariants, and writes a sample latest.json the frontend can
render. This is NOT a substitute for a live run with Alpaca/EDGAR keys — it
validates the LOGIC and the JSON CONTRACT only.
"""
import json
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from config import settings  # noqa: E402
from core import scoring, fund  # noqa: E402

rng = np.random.default_rng(7)

SECTORS = ["Information Technology", "Health Care", "Financials", "Consumer Discretionary",
           "Industrials", "Communication Services", "Consumer Staples", "Energy",
           "Materials", "Utilities", "Real Estate"]

# ── 1. Synthesize a universe of 400 names with correlated, plausible fundamentals
N = 400
tickers = [f"SYN{i:03d}" for i in range(N)]
names = [f"Synthetic Company {i}" for i in range(N)]
sectors = rng.choice(SECTORS, size=N)

# Quality latent factor drives the correlated fundamentals.
quality = rng.normal(0, 1, N)
rev_growth = np.clip(0.05 + 0.10 * quality + rng.normal(0, 0.08, N), -0.3, 0.9)
op_margin = np.clip(0.12 + 0.10 * quality + rng.normal(0, 0.05, N), -0.2, 0.6)
net_margin = np.clip(op_margin - 0.03 + rng.normal(0, 0.02, N), -0.25, 0.5)
fcf_margin = np.clip(op_margin - 0.02 + rng.normal(0, 0.03, N), -0.3, 0.5)
roe = np.clip(0.10 + 0.12 * quality + rng.normal(0, 0.08, N), -0.5, 1.2)
dte = np.clip(0.8 - 0.2 * quality + rng.normal(0, 0.4, N), 0, 4)
pe = np.clip(18 + 8 * quality + rng.normal(0, 6, N), 5, 80)
# A few names with no earnings (negative P/E -> treated as not meaningful).
pe[rng.choice(N, 20, replace=False)] = -1
fcf_yield = np.clip(0.04 + 0.02 * quality + rng.normal(0, 0.015, N), -0.05, 0.12)
div_yield = np.clip(0.015 - 0.005 * quality + rng.normal(0, 0.01, N), 0, 0.06)
gross_margin = np.clip(0.4 + 0.1 * quality + rng.normal(0, 0.08, N), 0.1, 0.85)
mcap = np.exp(rng.normal(23.5, 1.2, N))  # ~$1B–$1T

fund_df = pd.DataFrame({
    "peRatio": pe, "dividendYield": div_yield, "grossMargin": gross_margin,
    "operatingMargin": op_margin, "netMargin": net_margin, "returnOnEquity": roe,
    "fcfMargin": fcf_margin, "fcfYield": fcf_yield, "revenueGrowth": rev_growth,
    "debtToEquity": dte, "marketCap": mcap,
}, index=tickers)

# Momentum correlated with quality but noisy.
r6 = np.clip(0.08 * quality + rng.normal(0, 0.18, N), -0.6, 1.5)
r3 = np.clip(0.5 * r6 + rng.normal(0, 0.10, N), -0.5, 1.0)
trailing = pd.DataFrame({
    "return1W": rng.normal(0.003, 0.02, N),
    "return1M": rng.normal(0.012, 0.05, N),
    "return3M": r3, "return6M": r6,
    "return1Y": np.clip(1.4 * r6 + rng.normal(0, 0.2, N), -0.7, 2.5),
}, index=tickers)

# ── 2. Score the universe (sector-neutral path, as the screener calls it)
sector_series = pd.Series(sectors, index=tickers)
scores = scoring.score_universe(fund_df, trailing, sectors=sector_series)

# ── INVARIANT CHECKS ─────────────────────────────────────────────────────────
assert scores["score"].between(0, 100).all(), "composite out of [0,100]"
assert scores["healthScore"].between(0, 100).all()
assert scores["valuationScore"].between(0, 100).all()
assert scores["momentumScore"].between(0, 100).all()
# Higher-quality names should score higher on average (sanity of the engine).
top_q = scores.loc[fund_df.index[np.argsort(quality)[-50:]], "score"].mean()
bot_q = scores.loc[fund_df.index[np.argsort(quality)[:50]], "score"].mean()
assert top_q > bot_q, f"quality not reflected in score: {top_q:.1f} !> {bot_q:.1f}"
print(f"[ok] scoring: top-quality mean {top_q:.1f} > bottom-quality mean {bot_q:.1f}")

# ── SECTOR-NEUTRAL INVARIANTS (v2.3) ─────────────────────────────────────────
# (a) Two structurally-different sectors: universe-wide ranking lets the
# high-margin sector flood the top decile; sector-neutral must rebalance it
# while preserving within-sector ordering.
_rng2 = np.random.default_rng(11)
_q_hi, _q_lo = _rng2.uniform(0, 1, 60), _rng2.uniform(0, 1, 60)
_two = pd.DataFrame({
    "netMargin":       np.r_[0.30 + 0.10 * _q_hi, 0.15 + 0.06 * _q_lo],
    "operatingMargin": np.r_[0.35 + 0.10 * _q_hi, 0.18 + 0.06 * _q_lo],
    "returnOnEquity":  np.r_[0.20 + 0.15 * _q_hi, 0.08 + 0.06 * _q_lo],
}, index=[f"HI{i:02d}" for i in range(60)] + [f"LO{i:02d}" for i in range(60)])
_two_sec = pd.Series(["HighMargin"] * 60 + ["LowMargin"] * 60, index=_two.index)
_fac3 = {"netMargin": "higher", "operatingMargin": "higher", "returnOnEquity": "higher"}
_uni, _, _ = scoring._pillar_score(_two, _fac3)
_neu, _, _ = scoring._pillar_score(_two, _fac3, _two_sec)
_top_uni = _two_sec.loc[_uni.nlargest(12).index].value_counts()
_top_neu = _two_sec.loc[_neu.nlargest(12).index].value_counts()
assert _top_uni.get("LowMargin", 0) == 0, "universe ranking should exclude LowMargin from top decile"
assert _top_neu.get("LowMargin", 0) >= 4, f"sector-neutral top decile still unbalanced: {_top_neu.to_dict()}"
for _s in ("HighMargin", "LowMargin"):
    _m = _two_sec == _s
    _rho = pd.Series(_uni[_m]).corr(pd.Series(_neu[_m]), method="spearman")
    assert _rho > 0.95, f"within-{_s} ordering not preserved (rho={_rho:.3f})"
print(f"[ok] sector-neutral: top decile {dict(_top_uni)} -> {dict(_top_neu)}, "
      f"within-sector ordering preserved")

# (b) Min-count fallback: a 4-name sector must carry universe-wide percentiles
# bit-for-bit; same for "Unknown" regardless of its size.
_tiny = _two.copy()
for _i in range(4):
    _tiny.loc[f"TY{_i:02d}"] = [0.22, 0.25, 0.14]
for _i in range(15):  # Unknown is big enough to pass min-count — must still fall back
    _tiny.loc[f"UN{_i:02d}"] = [0.20 + 0.005 * _i, 0.23, 0.12]
_tiny_sec = pd.Series(["HighMargin"] * 60 + ["LowMargin"] * 60 + ["TinySector"] * 4
                      + ["Unknown"] * 15, index=_tiny.index)
_, _pct_t, _mask_t = scoring._pillar_score(_tiny, _fac3, _tiny_sec)
_uni_rank = scoring._percentile_rank(_tiny["netMargin"], "higher")
for _grp in ("TY", "UN"):
    _idx = [t for t in _tiny.index if t.startswith(_grp)]
    assert not _mask_t.loc[_idx, "netMargin"].any(), f"{_grp}: fallback did not fire"
    assert np.allclose(_pct_t.loc[_idx, "netMargin"], _uni_rank[_idx]), \
        f"{_grp}: fallback percentiles differ from universe-wide"
print(f"[ok] sector-neutral: min-count fallback (4-name sector) and Unknown "
      f"(15 names) both rank universe-wide")

# (c) Sector-median shrinkage: knocking out one factor must shrink the pillar
# toward the SECTOR's distribution (50 within-sector), not the universe's.
_knock = _two.copy()
_knock.loc["HI00", "netMargin"] = np.nan
_neu_k, _, _ = scoring._pillar_score(_knock, _fac3, _two_sec)
_uni_k, _, _ = scoring._pillar_score(_knock, _fac3)
# With the factor missing, the sector-neutral pillar = 50 + (mean of the two
# remaining WITHIN-SECTOR pctls - 50) * 2/3 exactly:
_, _pct_k, _ = scoring._pillar_score(_knock, _fac3, _two_sec)
_expect = 50.0 + (_pct_k.loc["HI00", ["operatingMargin", "returnOnEquity"]].mean() - 50.0) * (2 / 3)
assert abs(_neu_k["HI00"] - _expect) < 1e-9, "sector-median shrinkage identity broken"
print(f"[ok] sector-neutral: missing factor imputes at sector median "
      f"(pillar {_neu_k['HI00']:.1f} vs universe-regime {_uni_k['HI00']:.1f})")

combined = fund_df.join(scores).join(trailing)
combined["sector"] = sectors
sector_pe = combined.groupby("sector")["peRatio"].median().to_dict()
ranked = combined.sort_values("score", ascending=False).head(settings.SCREENER_TOP_N)
assert len(ranked) == settings.SCREENER_TOP_N
assert (ranked["score"].values == np.sort(ranked["score"].values)[::-1]).all(), "not sorted desc"
print(f"[ok] ranked top {len(ranked)} by score, monotonically descending")

# ── 3. Build per-stock dicts with reasons/flags
RET = ["return1W", "return1M", "return3M", "return6M", "return1Y"]
FFIELDS = ["peRatio", "dividendYield", "grossMargin", "operatingMargin", "netMargin",
           "returnOnEquity", "fcfMargin", "fcfYield", "revenueGrowth", "debtToEquity", "marketCap"]

def f(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return float(x)

stocks = []
for rank, (t, row) in enumerate(ranked.iterrows(), start=1):
    rowd = row.to_dict()
    reasons, flags = scoring.build_reasons(rowd, sector_pe.get(row["sector"]))
    stocks.append({
        "rank": rank, "ticker": t, "name": names[tickers.index(t)],
        "sector": row["sector"], "subIndustry": "",
        "price": round(float(rng.uniform(20, 600)), 2),
        "score": f(row["score"]), "healthScore": f(row["healthScore"]),
        "valuationScore": f(row["valuationScore"]), "momentumScore": f(row["momentumScore"]),
        **{k: f(row.get(k)) for k in FFIELDS},
        **{k: f(row.get(k)) for k in RET},
        "reasons": reasons, "flags": flags,
    })
assert all(s["reasons"] for s in stocks), "every stock needs >=1 reason"
print(f"[ok] {len(stocks)} stock detail dicts built; all have reasons")

# ── 4. Synthesize ~5y of daily returns for held + benchmark, build the fund
DAYS = 252 * 5 + 10
dates = pd.bdate_range(end="2026-06-06", periods=DAYS)
DAYS = len(dates)
held = [s["ticker"] for s in stocks]
# Each name: drift tied to its score, idiosyncratic + market component.
mkt = rng.normal(0.0003, 0.009, DAYS)
ret_cols = {}
for s in stocks:
    drift = 0.0001 + (s["score"] - 50) / 50 * 0.0004
    beta_i = rng.uniform(0.7, 1.3)
    ret_cols[s["ticker"]] = drift + beta_i * mkt + rng.normal(0, 0.012, DAYS)
returns = pd.DataFrame(ret_cols, index=dates)
bench_daily = pd.Series(0.0002 + mkt, index=dates)  # benchmark ~ market

the_fund = fund.build_fund(stocks, returns, bench_daily)

# ── FUND INVARIANT CHECKS ────────────────────────────────────────────────────
w = the_fund["weights"]
assert abs(sum(w.values()) - 1.0) < 1e-3, f"weights sum {sum(w.values())}"
assert max(w.values()) <= settings.SCREENER_MAX_WEIGHT + 1e-6, "cap breached"
assert the_fund["metrics3Y"] is not None, "3Y metrics missing"
assert the_fund["metrics5Y"] is not None, "5Y metrics missing"
for win in ("metrics3Y", "metrics5Y"):
    mm = the_fund[win]
    assert mm["beta"] is not None and 0.3 < mm["beta"] < 2.0, f"{win} beta odd: {mm['beta']}"
    assert mm["sharpeRatio"] is not None
assert len(the_fund["navSeries"]) > 50, "nav series too short"
assert abs(the_fund["navSeries"][0]["fund"] - 1.0) < 1e-6, "nav not rebased to 1"
assert abs(sum(b["weight"] for b in the_fund["sectorBreakdown"]) - 1.0) < 5e-3
print(f"[ok] fund: weights sum=1, cap respected (max {max(w.values()):.3f}), "
      f"3Y β={the_fund['metrics3Y']['beta']}, 5Y β={the_fund['metrics5Y']['beta']}, "
      f"NAV pts={len(the_fund['navSeries'])}")

# Attach fund weights to stocks
for s in stocks:
    s["fundWeight"] = round(w.get(s["ticker"], 0.0), 5)
the_fund.pop("weights", None)

# ── 5. Assemble the full PipelineOutput sample
portfolio = {
    "asOf": "2026-06-06",
    "pricesAsOf": "2026-06-06",
    "universeSize": 2864,
    "screenedCount": 1912,
    "scoredCount": 1788,
    "excludedCount": 1076,
    "exclusionReasons": {
        "insufficientHistory": 642, "lowLiquidity": 214, "lowPrice": 96,
        "missingFundamentals": 0, "noHealthData": 124,
    },
    "minHistoryYears": settings.SCREENER_MIN_HISTORY_YEARS,
    "methodology": {
        "weights": settings.SCORE_WEIGHTS,
        "healthFactors": list(scoring.HEALTH_FACTORS),
        "valuationFactors": list(scoring.VALUATION_FACTORS),
        "momentumFactors": list(scoring.MOMENTUM_FACTORS),
    },
    "stocks": stocks,
    "fund": the_fund,
    "marketConditions": {
        "date": "2026-06-06", "vix": 15.8, "volatilityLevel": "low",
        "riskSentiment": "risk-on", "sp500Return": 0.014, "nasdaqReturn": 0.021,
        "treasuryYield": 4.18,
        "marketSummary": {
            "Russell 2000": {"weeklyReturn": 0.009},
            "Gold": {"weeklyReturn": 0.004},
        },
    },
}
out = {
    "success": True, "date": "2026-06-06", "elapsed_seconds": 287.4,
    "backend_version": settings.VERSION, "run_type": "weekly",
    "portfolio": portfolio,
}

out_path = os.environ.get("SAMPLE_OUT", "sample_latest.json")
with open(out_path, "w") as fh:
    json.dump(out, fh, indent=2, default=str)

size = len(json.dumps(out))
print(f"[ok] {out_path} written ({size/1024:.0f} KB, {len(stocks)} stocks)")
print("\nALL CHECKS PASSED")
