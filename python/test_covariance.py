#!/usr/bin/env python3
"""
Offline self-test for core/covariance.py — no network, no keys.

Asserts the estimator's contract:
  1. Shapes/ordering: cov is n x n over info["tickers"], symmetric.
  2. Coverage filter: a sparse-history name is dropped and reported.
  3. EWMA recency: a recent volatility spike weighs more under EWMA than in
     the plain sample estimate (the whole point of the halflife).
  4. Ledoit-Wolf runs, is symmetric PSD-ish, and shrinks off-diagonals
     relative to the sample estimate.
  5. Windowing: only the last LOOKBACK_YEARS*252 rows inform the estimate.

Run:  cd python && python3 test_covariance.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import covariance as C  # noqa: E402
from config import settings  # noqa: E402


def _returns(n_days=1300, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-06-05", periods=n_days)
    mkt = rng.normal(0.0003, 0.009, n_days)
    data = {}
    for i in range(5):
        beta = 0.7 + 0.15 * i
        data[f"T{i}"] = beta * mkt + rng.normal(0, 0.010, n_days)
    return pd.DataFrame(data, index=dates), rng


def test_shapes_and_symmetry():
    rets, _ = _returns()
    cov, info = C.estimate(rets, method="sample")
    n = len(info["tickers"])
    assert cov.shape == (n, n) and n == 5
    assert np.allclose(cov, cov.T, atol=1e-12)
    assert info["nObs"] <= settings.LOOKBACK_YEARS * settings.TRADING_DAYS
    print(f"  PASS: sample cov {n}x{n}, symmetric, windowed to {info['nObs']} obs")


def test_coverage_filter_drops_sparse_name():
    rets, rng = _returns()
    sparse = pd.Series(np.nan, index=rets.index)
    tail = 120  # ~16% of the 3y window — far under the 60% floor
    sparse.iloc[-tail:] = rng.normal(0, 0.01, tail)
    rets["SPARSE"] = sparse
    cov, info = C.estimate(rets, method="sample")
    assert "SPARSE" in info["dropped"] and "SPARSE" not in info["tickers"]
    assert cov.shape == (5, 5)
    print("  PASS: sparse-history name dropped and reported; others unaffected")


def test_ewma_weights_recent_shock():
    rets, rng = _returns()
    # Triple T0's volatility for the final 40 days only.
    rets.iloc[-40:, rets.columns.get_loc("T0")] = rng.normal(0, 0.030, 40)
    cov_s, info_s = C.estimate(rets, method="sample")
    cov_e, info_e = C.estimate(rets, method="ewma")
    i = info_s["tickers"].index("T0")
    assert info_e["tickers"] == info_s["tickers"]
    assert cov_e[i, i] > 1.5 * cov_s[i, i], (
        f"EWMA var {cov_e[i,i]:.2e} should dominate sample {cov_s[i,i]:.2e} "
        "after a recent vol spike"
    )
    print(f"  PASS: EWMA var(T0) {cov_e[i,i]:.2e} > 1.5x sample {cov_s[i,i]:.2e} after recent spike")


def test_ledoit_runs_and_shrinks():
    rets, _ = _returns()
    cov_s, _ = C.estimate(rets, method="sample")
    cov_l, info = C.estimate(rets, method="ledoit")
    assert np.allclose(cov_l, cov_l.T, atol=1e-12)
    eig = np.linalg.eigvalsh(cov_l)
    assert eig.min() > -1e-12, "Ledoit-Wolf estimate must be PSD"
    off = ~np.eye(5, dtype=bool)
    assert np.abs(cov_l[off]).sum() <= np.abs(cov_s[off]).sum() + 1e-12, (
        "shrinkage should not increase aggregate off-diagonal mass"
    )
    print("  PASS: Ledoit-Wolf symmetric, PSD, off-diagonals shrunk vs sample")


def test_window_excludes_ancient_history():
    rets, rng = _returns(n_days=1300)
    # Make the FIRST 500 days (outside the 756-day window) insanely volatile.
    rets.iloc[:500, :] = rng.normal(0, 0.10, (500, 5))
    cov, info = C.estimate(rets, method="sample")
    daily_vol = np.sqrt(np.diag(cov))
    assert daily_vol.max() < 0.05, (
        f"pre-window chaos leaked into the estimate: max daily vol {daily_vol.max():.3f}"
    )
    print(f"  PASS: pre-window history ignored (max daily vol {daily_vol.max():.4f})")


def test_too_few_names_raises():
    rets, _ = _returns()
    try:
        C.estimate(rets[["T0"]])
    except ValueError:
        print("  PASS: <2 usable tickers raises ValueError (caller decides fallback)")
        return
    raise AssertionError("expected ValueError for a single ticker")


if __name__ == "__main__":
    print("test_covariance.py")
    test_shapes_and_symmetry()
    test_coverage_filter_drops_sparse_name()
    test_ewma_weights_recent_shock()
    test_ledoit_runs_and_shrinks()
    test_window_excludes_ancient_history()
    test_too_few_names_raises()
    print("ALL PASS")
