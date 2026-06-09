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


def test_research_block(arms, hist_file):
    block = R.build_research_block(arms, "2026-06-08",
                                   history=R.load_history(hist_file))
    assert block["schemaVersion"] == R.SCHEMA_VERSION
    assert block["baselineArm"] == "greedy"
    assert len(block["arms"]) == 3
    assert block["forwardStats"]["available"]
    assert "selectionComparison" in block
    import json
    json.dumps(block, default=str)  # must be serialisable for latest.json
    print("  PASS: research block assembles and is JSON-serialisable")


if __name__ == "__main__":
    print("=" * 64)
    print("research_log self-test (offline, synthetic)")
    print("=" * 64)
    test_arm_strips_weights()
    arms = test_selection_comparison()
    with tempfile.TemporaryDirectory() as td:
        hist = test_history_roundtrip_and_stats(Path(td))
        test_research_block(arms, hist)
    print("=" * 64)
    print("ALL PASS")
    print("=" * 64)
