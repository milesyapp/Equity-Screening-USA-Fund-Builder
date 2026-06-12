#!/usr/bin/env python3
"""
Offline self-test for core/research_log.py — no API keys, no D-Wave token.

Synthesises three fund arms and a forward return history, exercises every part
of the comparison pipeline, and asserts the invariants. Run after any change:

    cd python && python3 test_research_log.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import research_log as R  # noqa: E402


def _fake_fund(name, sharpe_seed):
    """Minimal object matching the Fund schema (enough for the block)."""
    return {
        "name": name, "constituents": 30, "weighting": "score-weighted",
        "benchmark": "IVV",
        "blended": {"pe": 22.0, "fcfYield": 0.04, "revenueGrowth": 0.08,
                    "returnOnEquity": 0.21, "netMargin": 0.15},
        "metrics3Y": {"annualReturn": 0.12, "annualVolatility": 0.16,
                      "sharpeRatio": 0.7, "maximumDrawdown": -0.2,
                      "alpha": 0.01, "beta": 1.0, "benchmarkReturn": 0.11},
        "metrics5Y": None,
        "navSeries": [{"date": "2026-06-08", "fund": 1.0, "benchmark": 1.0}],
        "sectorBreakdown": [{"sector": "Tech", "weight": 0.4}],
        "weights": {"AAA": 0.5, "BBB": 0.5},  # should be stripped by make_arm
    }


def test_arm_strips_weights():
    arm = R.make_arm("greedy", _fake_fund("X", 1), ["AAA", "BBB"],
                     {"AAA": 0.5, "BBB": 0.5})
    assert "weights" not in arm["fund"], "fund weights must not leak into arm.fund"
    assert arm["weights"] == {"AAA": 0.5, "BBB": 0.5}
    assert arm["isQuantum"] is False
    print("  PASS: make_arm seals weights inside the arm")


def test_selection_comparison():
    arms = [
        R.make_arm("greedy", _fake_fund("g", 1), ["A", "B", "C", "D"], {}),
        R.make_arm("qubo_classical", _fake_fund("c", 2), ["B", "C", "D", "E"], {},
                   R.make_diagnostics("SimulatedAnnealingSampler", False)),
        R.make_arm("qubo_quantum", _fake_fund("q", 3), ["B", "C", "D", "F"], {},
                   R.make_diagnostics("DWaveSampler", True, chain_break_fraction=0.02)),
    ]
    cmp = R.compare_selections(arms)
    pair = next(c for c in cmp if c["pair"] == "greedy_vs_qubo_classical")
    assert pair["overlapCount"] == 3 and pair["jaccard"] == round(3 / 5, 4)
    assert pair["onlyA"] == ["A"] and pair["onlyB"] == ["E"]
    print("  PASS: pairwise selection overlap (Jaccard, set diffs)")
    return arms


def test_history_roundtrip_and_stats(tmp_path):
    hist_file = tmp_path / "research_log.jsonl"
    rng = np.random.default_rng(0)
    days = 300
    dates = [f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}" for d in range(days)]

    # Common market factor + tiny arm-specific edges so they're highly correlated
    # (realistic) but not identical.
    market = rng.normal(0.0004, 0.011, days)
    series = {
        "greedy":         market + rng.normal(0.0000, 0.0015, days),
        "qubo_classical": market + rng.normal(0.0001, 0.0014, days),
        "qubo_quantum":   market + rng.normal(0.00012, 0.0014, days),
    }
    nav = {k: 1.0 for k in series}
    for d in range(days):
        rets = {k: float(series[k][d]) for k in series}
        for k in series:
            nav[k] *= (1 + rets[k])
        R.append_run_record(dates[d], "daily", rets,
                            {k: nav[k] for k in series}, path=hist_file)

    # Dedup: re-record the last day, count must not grow.
    before = len(R.load_history(hist_file))
    R.append_run_record(dates[-1], "daily",
                        {k: float(series[k][-1]) for k in series},
                        path=hist_file)
    after = len(R.load_history(hist_file))
    assert before == after == days, f"dedup failed: {before} -> {after}"
    print(f"  PASS: append + dedup ({after} forward runs, one per day)")

    mat = R.forward_return_matrix(R.load_history(hist_file))
    assert all(len(v) == days for v in mat.values()), "series misaligned"
    print("  PASS: forward return matrix aligned across arms")

    fs = R.forward_stats(R.load_history(hist_file))
    assert fs["available"] and fs["nDays"] == days
    for arm in fs["perArm"]:
        assert arm["trackingError"] is not None
        assert arm["sharpeDifference"]["ci95"] is not None
        assert arm["sharpeDifference"]["pValue"] is not None
        lo, hi = arm["sharpeDifference"]["ci95"]
        assert lo <= hi
    qq = next(a for a in fs["perArm"] if a["arm"] == "qubo_quantum")
    print(f"  PASS: forward stats — qubo_quantum vs greedy: "
          f"active={qq['activeReturnAnnualised']:+.4f}, "
          f"IR={qq['informationRatio']}, "
          f"SharpeDiff p={qq['sharpeDifference']['pValue']}")
    print(f"        (correlated funds -> p is large, as it should be: {qq['sharpeDifference']['note'] if 'note' in qq['sharpeDifference'] else 'CI spans 0'})")
    return hist_file


def test_probabilistic_sharpe():
    """PSR unit tests (Bailey & López de Prado 2012)."""
    from scipy import stats

    rng = np.random.default_rng(3)
    n = 120

    # (1) Convention check: independently re-derive the formula with RAW
    # kurtosis (gamma4 = 3 for a normal; scipy fisher=False). If the
    # implementation ever switches to excess kurtosis, this fails.
    r = rng.normal(0.0015, 0.01, n)
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = stats.skew(r), stats.kurtosis(r, fisher=False)
    expected = stats.norm.cdf(sr * np.sqrt(n - 1)
                              / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr * sr))
    got = R._prob_sharpe_positive(r)
    assert abs(got - expected) < 1e-12, f"PSR formula mismatch: {got} vs {expected}"
    print(f"  PASS: PSR matches the raw-kurtosis formula exactly ({got:.4f})")

    # (2) Normal returns, positive Sharpe: PSR ~ Phi(SR*sqrt(n-1)) since the
    # sample moments are near (0, 3). Tolerance covers moment noise at n=120.
    approx = stats.norm.cdf(sr * np.sqrt(n - 1))
    assert abs(got - approx) < 0.02, f"normal-case PSR {got} far from {approx}"
    print(f"  PASS: normal positive-SR series gives PSR ≈ Phi(SR·sqrt(n-1)) "
          f"({got:.4f} vs {approx:.4f})")

    # (3) Non-normality penalty: same first two moments (so identical SR), but
    # a 5% crash mixture injecting negative skew + fat tails must LOWER PSR.
    crash = rng.random(n) < 0.05
    c = np.where(crash, rng.normal(-0.025, 0.012, n), rng.normal(0.0027, 0.007, n))
    c = (c - c.mean()) / c.std(ddof=1) * r.std(ddof=1) + r.mean()
    assert stats.skew(c) < -0.5, "test construction failed to inject skew"
    psr_c = R._prob_sharpe_positive(c)
    assert psr_c < got, f"PSR penalty failed: skewed {psr_c} >= normal {got}"
    print(f"  PASS: negative skew / fat tails at identical SR lower PSR "
          f"({psr_c:.4f} < {got:.4f})")

    # Degenerate inputs -> None, not a crash.
    assert R._prob_sharpe_positive(np.array([0.01, 0.01, 0.01])) is None  # sd=0
    assert R._prob_sharpe_positive(np.array([0.01, -0.01])) is None       # n<3
    print("  PASS: PSR degrades to None on degenerate inputs")


def test_gating_tiers(tmp_path):
    """maxDrawdown ungated; Sortino/PSR gate at 20; Calmar gates at 60."""
    rng = np.random.default_rng(11)
    rets = rng.normal(0.0005, 0.01, 60)
    hist_file = tmp_path / "gating_log.jsonl"

    def current_stats():
        return R.forward_stats(R.load_history(hist_file))["perArm"][0]

    n_written = 0

    def grow_to(n):
        nonlocal n_written
        for d in range(n_written, n):
            R.append_run_record(
                f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}", "daily",
                {"greedy": float(rets[d]), "qubo_classical": float(rets[d]) + 0.0001},
                path=hist_file)
        n_written = n

    grow_to(1)
    p = current_stats()
    assert p["maxDrawdown"]["arm"] is not None, "day-1 maxDrawdown must be present"
    assert p["sortino"]["arm"] is None and p["probSharpePositive"]["arm"] is None
    assert p["calmar"]["arm"] is None
    print("  PASS: day 1 — maxDrawdown present, annualised stats gated")

    grow_to(19)
    p = current_stats()
    assert p["sortino"]["arm"] is None and p["probSharpePositive"]["arm"] is None
    grow_to(20)
    p = current_stats()
    assert p["sortino"]["arm"] is not None, "Sortino must appear at 20 days"
    assert p["probSharpePositive"]["arm"] is not None, "PSR must appear at 20 days"
    assert 0.0 <= p["probSharpePositive"]["arm"] <= 1.0
    assert p["calmar"]["arm"] is None, "Calmar must still be gated at 20 days"
    print("  PASS: Sortino + PSR — None at 19 days, present at 20")

    grow_to(59)
    p = current_stats()
    assert p["calmar"]["arm"] is None, "Calmar must be None at 59 days"
    grow_to(60)
    p = current_stats()
    assert p["calmar"]["arm"] is not None, "Calmar must appear at 60 days"
    assert p["minDaysForCalmar"] == 60
    print("  PASS: Calmar — None at 59 days, present at 60 (own higher floor)")


def test_research_block(arms, hist_file):
    block = R.build_research_block(arms, "2026-06-08",
                                   history=R.load_history(hist_file))
    assert block["schemaVersion"] == R.SCHEMA_VERSION
    assert block["baselineArm"] == "greedy"
    assert len(block["arms"]) == 3
    assert block["forwardStats"]["available"]
    assert "selectionComparison" in block
    nav = block["forwardNav"]
    assert len(nav) == 300, f"forwardNav should have one point per run, got {len(nav)}"
    assert all(k in nav[0] for k in ("date", "greedy", "qubo_classical", "qubo_quantum"))
    assert all(abs(p) < 10 for k, p in nav[-1].items() if k != "date"), "NAV blew up"
    assert nav[0]["date"] < nav[-1]["date"], "forwardNav must be date-sorted"
    import json
    json.dumps(block, default=str)  # must be serialisable for latest.json
    print(f"  PASS: research block assembles (incl. {len(nav)}-point forwardNav) and is JSON-serialisable")


if __name__ == "__main__":
    print("=" * 64)
    print("research_log self-test (offline, synthetic)")
    print("=" * 64)
    test_arm_strips_weights()
    arms = test_selection_comparison()
    test_probabilistic_sharpe()
    with tempfile.TemporaryDirectory() as td:
        test_gating_tiers(Path(td))
        hist = test_history_roundtrip_and_stats(Path(td))
        test_research_block(arms, hist)
    print("=" * 64)
    print("ALL PASS")
    print("=" * 64)
