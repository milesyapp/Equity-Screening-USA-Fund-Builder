#!/usr/bin/env python3
"""
Offline self-test for core/riskfree.py and the rf plumbing — NEVER hits
Treasury/FRED: the fetch is monkeypatched with synthetic series. Run after
any change:

    cd python && python3 test_riskfree.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import settings  # noqa: E402
from core import metrics, riskfree, research_log  # noqa: E402

TD = settings.TRADING_DAYS


def _synthetic_series() -> pd.Series:
    """Business-day yields stepping 2% -> 5%, with a bond-holiday gap."""
    idx = pd.bdate_range("2024-01-01", "2024-03-29")
    vals = np.linspace(0.02, 0.05, len(idx))
    s = pd.Series(vals, index=idx, name="rfAnnual")
    return s.drop(s.index[20])  # bond holiday: published series skips a day


def test_conversion_convention():
    s = _synthetic_series()
    m = riskfree.daily_rf_map(s, ["2024-02-01"])
    expected = float(s.asof(pd.Timestamp("2024-02-01"))) / TD
    assert abs(m["2024-02-01"] - expected) < 1e-15, "daily rf != annual / TRADING_DAYS"
    print("  PASS: daily rf = annual yield / TRADING_DAYS (simple division)")


def test_alignment():
    s = _synthetic_series()
    holiday = pd.bdate_range("2024-01-01", "2024-03-29")[20]  # the dropped day

    # (1) bond holiday that is an equity trading day -> ffill from prior obs
    aligned = riskfree.align_annual(s, pd.DatetimeIndex([holiday]))
    prev = s.asof(holiday)
    assert abs(aligned.iloc[0] - prev) < 1e-15, "bond-holiday gap not forward-filled"

    # (2) the seam: trading days after the last published yield carry it forward
    seam = pd.DatetimeIndex(["2024-04-01", "2024-04-05"])
    aligned = riskfree.align_annual(s, seam)
    assert (aligned == s.iloc[-1]).all(), "seam days must ffill the last print"

    # (3) left edge: trading days before the first obs -> constant, not NaN/drop
    early = pd.DatetimeIndex(["2023-06-01"])
    aligned = riskfree.align_annual(s, early)
    assert abs(aligned.iloc[0] - settings.RISK_FREE_RATE) < 1e-15

    # (4) tz-aware index must not raise
    tz = pd.DatetimeIndex(["2024-02-01"]).tz_localize("America/New_York")
    assert len(riskfree.align_annual(s, tz)) == 1
    print("  PASS: alignment — holiday ffill, seam carry-forward, left-edge "
          "constant, tz-aware index")


def test_fallback_chain(tmp_path):
    s = _synthetic_series()
    cache = tmp_path / "riskfree_3mo.csv"
    real_fetch = riskfree._fetch_from_treasury

    # (1) successful fetch writes the cache
    riskfree._fetch_from_treasury = lambda today=None: s
    got = riskfree.get_rf_series(cache_path=cache)
    assert cache.exists() and len(got) == len(s)

    # (2) fetch failure -> cached series
    def _boom(today=None):
        raise ConnectionError("synthetic outage")
    riskfree._fetch_from_treasury = _boom
    got = riskfree.get_rf_series(cache_path=cache)
    assert len(got) == len(s), "cache fallback did not return the cached series"
    assert abs(float(got.iloc[-1]) - float(s.iloc[-1])) < 1e-12

    # (3) fetch failure AND no cache -> constant 4% single-point series
    got = riskfree.get_rf_series(cache_path=tmp_path / "missing.csv")
    assert len(got) == 1 and float(got.iloc[0]) == settings.RISK_FREE_RATE
    aligned = riskfree.align_annual(got, pd.DatetimeIndex(["2024-02-01"]))
    assert float(aligned.iloc[0]) == settings.RISK_FREE_RATE, \
        "constant fallback must align to the constant everywhere"

    riskfree._fetch_from_treasury = real_fetch
    print("  PASS: resilience chain — fetch->cache write, outage->cache, "
          "no cache->4% constant")


def test_metrics_series_rf():
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2023-01-02", periods=504)
    daily = pd.Series(rng.normal(0.0006, 0.01, len(idx)), index=idx)
    flat = pd.Series(0.04, index=pd.bdate_range("2020-01-01", "2025-01-01"))

    # A flat 4% series must reproduce the constant exactly (regression guard).
    for fn in (metrics.sharpe_ratio, metrics.sortino_ratio):
        a, b = fn(daily, 0.04), fn(daily, flat)
        assert abs(a - b) < 1e-12, f"{fn.__name__}: flat series != constant ({a} vs {b})"
    a_const = metrics.alpha_newey_west(daily, daily * 0.9 + 0.0001, 0.04)
    a_series = metrics.alpha_newey_west(daily, daily * 0.9 + 0.0001, flat)
    assert abs(a_const[0] - a_series[0]) < 1e-12

    # Higher rf must lower Sharpe/Sortino (direction sanity).
    hi = pd.Series(0.08, index=flat.index)
    assert metrics.sharpe_ratio(daily, hi) < metrics.sharpe_ratio(daily, 0.04)
    assert metrics.sortino_ratio(daily, hi) < metrics.sortino_ratio(daily, 0.04)
    print("  PASS: metrics accept yield Series — flat==constant, "
          "higher rf lowers Sharpe/Sortino")


def test_forward_excess_convention(tmp_path):
    """forward_stats with an injected rf map: Sharpe/Sortino/PSR are excess."""
    rng = np.random.default_rng(9)
    hist_file = tmp_path / "log.jsonl"
    n = 40
    for d in range(n):
        date = f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}"
        r = float(rng.normal(0.001, 0.01))
        research_log.append_run_record(
            date, "daily", {"greedy": r, "qubo_classical": r + 0.0002},
            path=hist_file)
    history = research_log.load_history(hist_file)
    dates = [r["date"] for r in history]
    rf_map = {d: 0.05 / TD for d in dates}  # flat 5% injected, never fetched

    raw = research_log.forward_stats(history)["perArm"][0]
    exc = research_log.forward_stats(history, rf_daily=rf_map)["perArm"][0]
    assert exc["sharpe"]["arm"] < raw["sharpe"]["arm"], \
        "excess-of-5% Sharpe must be lower than raw"
    assert exc["sortino"]["arm"] < raw["sortino"]["arm"]
    assert exc["probSharpePositive"]["arm"] < raw["probSharpePositive"]["arm"]
    # rf cancels in active return / TE / maxDD — must be identical.
    for k in ("activeReturnCumulative", "trackingError"):
        assert exc[k] == raw[k], f"{k} must be rf-invariant"
    assert exc["maxDrawdown"]["arm"] == raw["maxDrawdown"]["arm"]
    print("  PASS: forward stats — Sharpe/Sortino/PSR excess-of-rf; "
          "active/TE/maxDD rf-invariant")


if __name__ == "__main__":
    print("=" * 64)
    print("riskfree self-test (offline, synthetic — no Treasury/FRED calls)")
    print("=" * 64)
    test_conversion_convention()
    test_alignment()
    with tempfile.TemporaryDirectory() as td:
        test_fallback_chain(Path(td))
    test_metrics_series_rf()
    with tempfile.TemporaryDirectory() as td:
        test_forward_excess_convention(Path(td))
    print("=" * 64)
    print("ALL PASS")
    print("=" * 64)
