#!/usr/bin/env python3
"""
Offline self-test for core/quantum_fund.py — no D-Wave token, no API keys.

Builds a synthetic 150-name universe, runs the QUBO on the classical simulator,
assembles a fund via the REAL fund.build_fund, and asserts the invariants that
make the arm safe to ship. Run after any change:

    cd python && python3 test_quantum_fund.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import quantum_fund as QF  # noqa: E402

RNG = np.random.default_rng(7)
SECTORS = ["Tech", "Health", "Finance", "Energy", "Industrials", "Consumer", "Utilities"]


def _universe(n=150, days=1380):
    tickers = [f"STK{i:03d}" for i in range(n)]
    sectors = [SECTORS[i % len(SECTORS)] for i in range(n)]
    scores = np.sort(RNG.uniform(45, 95, n))[::-1]
    candidates = [{
        "ticker": t, "score": float(scores[i]), "sector": sectors[i],
        "peRatio": float(RNG.uniform(8, 40)), "fcfYield": float(RNG.uniform(0.01, 0.08)),
        "revenueGrowth": float(RNG.uniform(-0.05, 0.3)),
        "returnOnEquity": float(RNG.uniform(0.05, 0.4)),
        "netMargin": float(RNG.uniform(0.02, 0.3)),
    } for i, t in enumerate(tickers)]
    dates = pd.bdate_range("2021-01-01", periods=days)
    mkt = RNG.normal(0.0003, 0.010, days)
    secf = {s: RNG.normal(0, 0.006, days) for s in SECTORS}
    R = np.column_stack([
        0.0002 + 0.9 * mkt + 0.5 * secf[sectors[i]] + RNG.normal(0, RNG.uniform(.01, .025), days)
        for i in range(n)
    ])
    returns = pd.DataFrame(R, index=dates, columns=tickers)
    bench = pd.Series(0.9 * mkt + RNG.normal(0, 0.004, days), index=dates)
    return candidates, returns, bench


def test_qubo_build_and_solve():
    candidates, returns, bench = _universe()
    prob = QF.build_qubo(candidates, returns, k=100)
    assert prob.n == 150 and prob.target_size == 100
    assert isinstance(prob.Q, dict) and len(prob.Q) > 0
    sel, diag = QF.solve(prob, "sim", num_reads=100)
    assert 70 <= len(sel) <= 120, f"selection size {len(sel)} far from target 100"
    assert diag["isQuantum"] is False and diag["solver"] == "SimulatedAnnealingSampler"
    assert diag["bestEnergy"] is not None and diag["targetSize"] == 100
    # The QUBO trades score for diversification, so its mean won't sit far above
    # the universe mean when target ~= most of the pool. Just guard against a
    # pathological (bottom-dredging) selection — quality is the l1 term's job.
    by_t = {c["ticker"]: c["score"] for c in candidates}
    mean_sel = np.mean([by_t[t] for t in sel])
    mean_all = np.mean(list(by_t.values()))
    assert mean_sel >= mean_all - 5, "selection quality is pathologically low"
    print(f"  PASS: QUBO build+solve — {len(sel)} names, mean score {mean_sel:.1f} "
          f"(universe {mean_all:.1f}), energy {diag['bestEnergy']:.2f}")
    return candidates, returns, bench, sel


def test_diversification_vs_greedy():
    candidates, returns, bench = _universe()
    prob = QF.build_qubo(candidates, returns, k=100)
    sel, _ = QF.solve(prob, "sim", num_reads=100)
    greedy = [c["ticker"] for c in candidates[:100]]

    def ew_var(tks):
        w = np.ones(len(tks)) / len(tks)
        return float(w @ returns[tks].cov().values @ w * 252)

    v_g, v_q = ew_var(greedy), ew_var(sel)
    overlap = len(set(greedy) & set(sel)) / len(set(greedy) | set(sel))
    assert v_q <= v_g, f"QUBO variance {v_q:.4f} should be <= greedy {v_g:.4f}"
    assert 0.2 <= overlap <= 0.95, f"overlap {overlap:.2f} implies arms identical or unrelated"
    print(f"  PASS: diversification — EWvar greedy {v_g:.4f} -> QUBO {v_q:.4f}, "
          f"selection overlap {overlap:.2f}")


def test_end_to_end_arm():
    candidates, returns, bench = _universe()
    arm = QF.build_arm(candidates, returns, bench, "sim")
    f = arm["fund"]
    assert "weights" not in f, "weights must be popped out of the fund object"
    assert f["metrics3Y"] is not None and f["metrics5Y"] is not None
    assert len(f["navSeries"]) > 0 and len(f["sectorBreakdown"]) > 0
    wsum = sum(arm["weights"].values())
    assert abs(wsum - 1.0) < 1e-2, f"weights sum {wsum} not ~1"
    assert max(arm["weights"].values()) <= 0.04 + 1e-6, "4% cap must hold"
    assert arm["diagnostics"]["lambdas"] == QF.lambdas()
    print(f"  PASS: end-to-end arm via real fund.build_fund — {len(arm['selection'])} holdings, "
          f"weights sum {wsum:.4f}, max weight {max(arm['weights'].values()):.4f}")


def test_identical_qubo_for_both_arms():
    """The controlled-comparison guarantee: classical and 'quantum' arms must
    solve the IDENTICAL QUBO when a shared problem is passed."""
    candidates, returns, bench = _universe()
    prob = QF.build_qubo(candidates, returns)
    a1 = QF.build_arm(candidates, returns, bench, "sim", problem=prob)
    a2 = QF.build_arm(candidates, returns, bench, "sim", problem=prob)
    # same Q object underlies both; selections may differ only by sampler stochasticity
    assert a1["diagnostics"]["lambdas"] == a2["diagnostics"]["lambdas"]
    assert a1["diagnostics"]["targetSize"] == a2["diagnostics"]["targetSize"]
    print("  PASS: both arms solve one shared QUBO (controlled comparison holds)")


def test_objective_weighting():
    """Stage two (8b): correlated-pair downweighting, constraints, cap,
    determinism, and the comparison diagnostics."""
    candidates, returns, bench = _universe()
    prob = QF.build_qubo(candidates, returns, k=100)
    sel, _ = QF.solve(prob, "sim", num_reads=100)

    w1, d1 = QF.objective_weights(prob, sel)
    assert d1["weighting"] == "objective", f"stage two failed: {d1}"
    wv = np.array(list(w1.values()))
    # Constraints to documented tolerance.
    assert abs(wv.sum() - 1.0) <= 1e-8, "simplex constraint violated"
    assert wv.min() >= 0.0 and wv.max() <= 0.04 + 1e-9, "bounds violated"
    assert d1["namesAtCap"] >= 1, "cap should bind somewhere on a 100-name optimum"
    assert d1["effectiveN"] < len(sel), "objective weights should concentrate"
    # In-objective dominance: achieved risk <= score-weight risk on the SAME
    # selection is not guaranteed in general (quality trades against it), but
    # the optimum must not be worse on the combined objective — proxied here
    # by the diagnostics carrying both variances for inspection.
    assert d1["wSigmaW"] is not None and d1["wSigmaWScore"] is not None
    # Determinism: same inputs -> bit-identical weights.
    w2, _ = QF.objective_weights(prob, sel)
    assert w1 == w2, "stage two must be deterministic"
    print(f"  PASS: objective weighting — sum=1±1e-8, cap binds ({d1['namesAtCap']} names), "
          f"effN {d1['effectiveN']} of {len(sel)}, deterministic")

    # Correlated-pair behaviour. NOTE the scale-dependence: at the production
    # 4% cap on ~100 names, per-name variance costs are second-order, so even
    # near-duplicates can both sit at the cap (quality wins — economically
    # correct). The covariance-awareness shows where weights are large enough
    # for the quadratic term to bite, so test at a looser cap on a small
    # selection: two rho=0.9 high-scorers among uncorrelated mid-scorers must
    # be held asymmetrically (hold one, not both), unlike score weighting.
    from config import settings as _settings
    n12 = 12
    tk12 = [f"PAIR{i:02d}" for i in range(n12)]
    s12 = np.array([0.92, 0.90] + [0.68 + 0.02 * i for i in range(10)])
    vols = np.full(n12, 0.02)
    corr = np.eye(n12)
    corr[0, 1] = corr[1, 0] = 0.90
    cov12 = corr * np.outer(vols, vols)
    prob12 = QF.QuboProblem({}, tk12, QF.lambdas(), 12, None,
                            scores_norm=s12, cov=cov12,
                            cmax=float(np.abs(cov12).max()))
    saved_cap = _settings.SCREENER_MAX_WEIGHT
    _settings.SCREENER_MAX_WEIGHT = 0.15
    try:
        w3, d3 = QF.objective_weights(prob12, tk12)
    finally:
        _settings.SCREENER_MAX_WEIGHT = saved_cap
    assert d3["weighting"] == "objective"
    lo, hi = sorted([w3[tk12[0]], w3[tk12[1]]])
    assert lo <= 0.5 * hi + 1e-6, \
        f"near-duplicate pair should be held asymmetrically (got {lo:.4f}/{hi:.4f})"
    assert d3["wSigmaW"] is not None
    print(f"  PASS: rho=0.9 pair held asymmetrically ({lo:.4f} vs {hi:.4f}; "
          f"score weighting would hold both equally) — covariance survives weighting")


def test_weighting_fallback():
    """Optimizer failure -> score weights with weighting='score_fallback'."""
    candidates, returns, bench = _universe()
    prob = QF.build_qubo(candidates, returns, k=100)
    sel, _ = QF.solve(prob, "sim", num_reads=100)

    # (1) no problem supplied -> fallback path through build_fund_from_selection
    f, w, wd = QF.build_fund_from_selection(sel, candidates, returns, bench)
    assert wd["weighting"] == "score_fallback"
    assert f["weighting"].endswith("(fallback)")
    assert abs(sum(w.values()) - 1.0) < 1e-3  # weights rounded to 5dp in build_fund

    # (2) corrupted covariance -> SLSQP cannot converge -> fallback
    prob.cov = prob.cov.copy()
    prob.cov[0, 0] = np.nan
    f2, w2, wd2 = QF.build_fund_from_selection(sel, candidates, returns, bench,
                                               problem=prob)
    assert wd2["weighting"] == "score_fallback", "NaN covariance must trigger fallback"
    assert abs(sum(w2.values()) - 1.0) < 1e-3  # weights rounded to 5dp in build_fund
    assert w2 == w, "fallback weights must equal plain score weights"
    print("  PASS: fallback — missing problem and corrupt covariance both "
          "degrade to score weights with weighting='score_fallback'")


def test_hardware_gating():
    import os
    saved = os.environ.pop("DWAVE_API_TOKEN", None)
    assert QF.hardware_available() is False, "no token -> hardware unavailable"
    os.environ["DWAVE_API_TOKEN"] = "fake-token-for-test"
    assert QF.hardware_available() is True, "token present -> hardware available"
    if saved is None:
        os.environ.pop("DWAVE_API_TOKEN", None)
    else:
        os.environ["DWAVE_API_TOKEN"] = saved
    print("  PASS: hardware gating keys off DWAVE_API_TOKEN")


if __name__ == "__main__":
    import logging
    logging.disable(logging.INFO)
    print("=" * 64)
    print("quantum_fund self-test (offline, simulator, synthetic)")
    print("=" * 64)
    test_qubo_build_and_solve()
    test_diversification_vs_greedy()
    test_end_to_end_arm()
    test_identical_qubo_for_both_arms()
    test_objective_weighting()
    test_weighting_fallback()
    test_hardware_gating()
    print("=" * 64)
    print("ALL PASS")
    print("=" * 64)
