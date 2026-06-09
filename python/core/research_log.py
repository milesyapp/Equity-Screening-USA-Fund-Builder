"""
Research instrumentation for the classical-vs-quantum fund experiment.

This module is the comparison backbone. It is deliberately decoupled from the
solver (no dwave import here) and from data fetching — it only consumes fund
arms that have already been built, persists them, and computes the comparison
statistics the paper will rest on.

TWO PERSISTENCE TARGETS
-----------------------
1. The `research` block (build_research_block) is embedded in data/latest.json
   each run. It is a *snapshot*: every arm's full Fund object (reusing the
   existing Fund schema), QUBO diagnostics, pairwise selection overlap, and the
   forward comparison stats. The frontend reads this directly.

2. data/research_log.jsonl is an APPEND-ONLY history, one record per run. Each
   line carries the realized forward daily return of every arm. latest.json is
   overwritten every run; this file is not. It is the accumulating forward
   track record that the significance tests consume. Deduplicated by date so a
   re-run of the same day replaces rather than duplicates.

ARMS
----
An "arm" is one construction methodology:
  greedy          - classical score-weighting (the existing fund; baseline)
  qubo_classical  - the QUBO objective, solved with a CLASSICAL sampler
  qubo_quantum    - the SAME QUBO, solved on real D-Wave hardware
The greedy-vs-qubo_classical gap isolates the objective-function effect; the
qubo_classical-vs-qubo_quantum gap isolates the quantum-solver effect. Logging
all three is what makes the comparison interpretable.

STATISTICAL HONESTY
-------------------
A forward comparison of two highly-correlated equity funds is low-powered and
will not reach significance for a long time. The stats below (HAC t-stat,
bootstrap Sharpe-difference CI) are the right tools but must be read with that
caveat. The parametric Ledoit-Wolf (2008) HAC Sharpe-difference test is the
recommended upgrade; a clearly marked hook is left for it.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_HISTORY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "research_log.jsonl"
TRADING_DAYS = 252

# Arm registry: stable key -> human label. Order is display order.
ARM_LABELS = {
    "greedy":         "Classical (greedy score-weighting)",
    "qubo_classical": "QUBO, classical solver",
    "qubo_quantum":   "QUBO, quantum annealer",
}
BASELINE_ARM = "greedy"


# --------------------------------------------------------------------------- #
# Arm + diagnostics builders
# --------------------------------------------------------------------------- #
def make_diagnostics(
    solver: str,
    is_quantum: bool,
    *,
    num_reads: int | None = None,
    best_energy: float | None = None,
    energy_std: float | None = None,
    chain_break_fraction: float | None = None,
    num_qubits_used: int | None = None,
    wall_seconds: float | None = None,
    lambdas: dict | None = None,
    target_size: int | None = None,
) -> dict:
    """Solver diagnostics for one QUBO arm. None-valued for the greedy arm."""
    return {
        "solver": solver,
        "isQuantum": bool(is_quantum),
        "numReads": num_reads,
        "bestEnergy": _r(best_energy, 6),
        "energyStd": _r(energy_std, 6),
        "chainBreakFraction": _r(chain_break_fraction, 4),
        "numQubitsUsed": num_qubits_used,
        "wallSeconds": _r(wall_seconds, 3),
        "lambdas": lambdas,
        "targetSize": target_size,
    }


def make_arm(
    key: str,
    fund: dict,
    selection: list[str],
    weights: dict[str, float],
    diagnostics: dict | None = None,
) -> dict:
    """
    key        : one of ARM_LABELS
    fund       : the dict returned by fund.build_fund (the 'weights' key, if
                 present, is moved into this arm's own weights and not shared)
    selection  : tickers chosen for this arm
    weights    : {ticker: weight} for this arm (stays inside the arm)
    diagnostics: make_diagnostics(...) for QUBO arms, None for greedy
    """
    if key not in ARM_LABELS:
        raise ValueError(f"unknown arm key {key!r}; expected one of {list(ARM_LABELS)}")
    fund = dict(fund)
    fund.pop("weights", None)  # weights live on the arm, never leak to stocks
    return {
        "key": key,
        "label": ARM_LABELS[key],
        "isQuantum": bool(diagnostics and diagnostics.get("isQuantum")),
        "selection": sorted(selection),
        "weights": {t: round(float(w), 5) for t, w in weights.items()},
        "diagnostics": diagnostics,
        "fund": fund,
    }


# --------------------------------------------------------------------------- #
# Selection comparison — "do the arms even pick different baskets?"
# --------------------------------------------------------------------------- #
def compare_selections(arms: list[dict]) -> list[dict]:
    """Pairwise Jaccard overlap of selected tickers across all arms."""
    out = []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            a, b = arms[i], arms[j]
            sa, sb = set(a["selection"]), set(b["selection"])
            inter = sa & sb
            union = sa | sb
            out.append({
                "pair": f"{a['key']}_vs_{b['key']}",
                "jaccard": round(len(inter) / len(union), 4) if union else None,
                "overlapCount": len(inter),
                "nA": len(sa),
                "nB": len(sb),
                "onlyA": sorted(sa - sb),
                "onlyB": sorted(sb - sa),
            })
    return out


# --------------------------------------------------------------------------- #
# Append-only forward history (data/research_log.jsonl)
# --------------------------------------------------------------------------- #
def append_run_record(
    date: str,
    run_type: str,
    arm_daily_returns: dict[str, float | None],
    arm_nav: dict[str, float] | None = None,
    rebalance: dict | None = None,
    path: Path | None = None,
) -> None:
    """
    Append one run's realized forward marks. Deduplicated by date: a re-run of
    the same day replaces the prior line rather than duplicating it.

    arm_daily_returns : {arm_key: realized return since last mark}
    arm_nav           : {arm_key: cumulative forward NAV, rebased 1.0 at inception}
    rebalance         : weekly-only block {selectionByArm, diagnosticsByArm};
                        None on daily refreshes (no re-selection occurred).
    """
    path = path or _HISTORY_PATH
    record = {
        "date": date,
        "runType": run_type,
        "armReturns": {k: _r(v, 6) for k, v in arm_daily_returns.items()},
        "armNav": {k: _r(v, 6) for k, v in (arm_nav or {}).items()},
        "rebalance": rebalance,
    }
    history = [r for r in load_history(path) if r.get("date") != date]
    history.append(record)
    history.sort(key=lambda r: r.get("date", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in history:
            fh.write(json.dumps(r, default=str) + "\n")
    logger.info("research_log: recorded %s (%s), %d arms, %d total runs",
                date, run_type, len(arm_daily_returns), len(history))


def load_history(path: Path | None = None) -> list[dict]:
    path = path or _HISTORY_PATH
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("research_log: skipping malformed line")
    return out


def forward_return_matrix(history: list[dict]) -> dict[str, np.ndarray]:
    """Stack the per-run realized returns into one aligned series per arm.

    Only runs where *every* arm reported a return are kept, so the series are
    aligned and pairwise comparisons use identical days.
    """
    rows = [r for r in history if r.get("armReturns")]
    if not rows:
        return {}
    arms = set().union(*(r["armReturns"].keys() for r in rows))
    aligned = [r for r in rows
               if all(r["armReturns"].get(a) is not None for a in arms)]
    return {a: np.array([r["armReturns"][a] for r in aligned], float) for a in arms}


# --------------------------------------------------------------------------- #
# Forward comparison statistics
# --------------------------------------------------------------------------- #
def _annualised_sharpe(daily: np.ndarray) -> float:
    sd = daily.std(ddof=1)
    if sd == 0 or len(daily) < 2:
        return float("nan")
    return float(daily.mean() / sd * np.sqrt(TRADING_DAYS))


def _newey_west_t(active: np.ndarray) -> float:
    """HAC (Bartlett) t-stat for H0: mean daily active return = 0."""
    n = len(active)
    if n < 3:
        return float("nan")
    x = active - active.mean()
    L = max(1, int(np.floor(4 * (n / 100.0) ** (2 / 9))))  # Newey-West lag rule
    gamma0 = np.dot(x, x) / n
    var = gamma0
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1)
        cov = np.dot(x[lag:], x[:-lag]) / n
        var += 2 * w * cov
    se = np.sqrt(var / n)
    return float(active.mean() / se) if se > 0 else float("nan")


def _block_bootstrap_sharpe_diff(a: np.ndarray, b: np.ndarray,
                                 n_boot: int = 2000, seed: int = 7) -> dict:
    """Moving-block bootstrap CI + two-sided p-value for Sharpe(a) - Sharpe(b).

    Block bootstrap (not i.i.d.) because daily returns are autocorrelated.
    """
    n = len(a)
    if n < 10:
        return {"difference": None, "ci95": None, "pValue": None,
                "note": "insufficient forward history for bootstrap (need >=10 aligned days)"}
    rng = np.random.default_rng(seed)
    block = max(1, int(round(n ** (1 / 3))))
    n_blocks = int(np.ceil(n / block))
    obs_diff = _annualised_sharpe(a) - _annualised_sharpe(b)
    diffs = np.empty(n_boot)
    for k in range(n_boot):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        diffs[k] = _annualised_sharpe(a[idx]) - _annualised_sharpe(b[idx])
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    # two-sided p-value: how often the resampled diff crosses zero relative to obs
    p = 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return {"difference": _r(obs_diff, 4),
            "ci95": [_r(lo, 4), _r(hi, 4)],
            "pValue": _r(min(p, 1.0), 4),
            "method": f"moving-block bootstrap (block={block}, n_boot={n_boot})"}


def forward_stats(history: list[dict], baseline: str = BASELINE_ARM) -> dict:
    """Forward comparison of each non-baseline arm against the baseline."""
    mat = forward_return_matrix(history)
    if baseline not in mat:
        return {"available": False,
                "reason": "no aligned forward history yet (baseline arm missing returns)",
                "nDays": 0}
    base = mat[baseline]
    n = len(base)
    per_arm = []
    for arm, series in mat.items():
        if arm == baseline:
            continue
        active = series - base
        te = active.std(ddof=1) * np.sqrt(TRADING_DAYS) if n > 1 else float("nan")
        ann_active = active.mean() * TRADING_DAYS
        ir = ann_active / te if te and not np.isnan(te) and te != 0 else None
        per_arm.append({
            "arm": arm,
            "vsBaseline": baseline,
            "nDays": n,
            "activeReturnAnnualised": _r(ann_active, 4),
            "trackingError": _r(te, 4),
            "informationRatio": _r(ir, 3),
            "sharpe": {
                "arm": _r(_annualised_sharpe(series), 3),
                "baseline": _r(_annualised_sharpe(base), 3),
            },
            "neweyWestT_meanActive": _r(_newey_west_t(active), 3),
            "sharpeDifference": _block_bootstrap_sharpe_diff(series, base),
            "ledoitWolfTest": None,  # HOOK: parametric HAC Sharpe-diff test (recommended at scale)
        })
    return {
        "available": n >= 2,
        "nDays": n,
        "baseline": baseline,
        "perArm": per_arm,
        "caveat": ("Forward comparison of highly-correlated equity funds is "
                   "low-powered; significance is not expected for a long time. "
                   "Treat point estimates as descriptive until n is large."),
    }


# --------------------------------------------------------------------------- #
# Assemble the snapshot block embedded in latest.json
# --------------------------------------------------------------------------- #
def build_research_block(arms: list[dict], as_of: str,
                         history: list[dict] | None = None,
                         baseline: str = BASELINE_ARM) -> dict:
    history = history if history is not None else load_history()
    inception = history[0]["date"] if history else as_of
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": as_of,
        "inceptionDate": inception,
        "baselineArm": baseline,
        "armOrder": list(ARM_LABELS.keys()),
        "arms": arms,
        "selectionComparison": compare_selections(arms),
        "forwardStats": forward_stats(history, baseline),
        "disclaimer": (
            "Research instrument. Per-arm 3Y/5Y metrics are in-sample "
            "characterisations of today's basket, not a forward record. The "
            "forward record is the realized series in research_log.jsonl, which "
            "begins at inceptionDate. Quantum advantage, if any, is the "
            "qubo_classical vs qubo_quantum gap, not greedy vs quantum."
        ),
    }


def _r(x, d):
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    if np.isnan(xf) or np.isinf(xf):
        return None
    return round(xf, d)
