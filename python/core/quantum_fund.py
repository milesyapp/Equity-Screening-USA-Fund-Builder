"""
Quantum-annealing fund construction via QUBO.

The classical greedy fund takes the top-N names by score and weights them. It
never accounts for *covariance* between holdings — two highly-correlated
high-scorers both get in. This module formulates selection as a QUBO (Quadratic
Unconstrained Binary Optimisation) that balances quality against correlation,
and solves it either on a classical simulator or on real D-Wave hardware. The
SELECTION is the quantum step; the continuous weighting afterwards reuses the
existing classical `fund.build_fund`, so the output matches the Fund schema.

OBJECTIVE (minimise)
    -l1 * sum_i  s_i * x_i                         quality   (reward)
    +l2 * sum_ij c_ij * x_i * x_j                   risk      (penalty)
    +l3 * (sum_i x_i - K)^2                          size      (constraint)
    +l4 * sum_{i<j, same sector} x_i * x_j           diversify (constraint)
where x_i in {0,1} selects candidate i, s_i is its normalised score, c_ij the
normalised return covariance, and K the target portfolio size.

THREE ARMS (see research_log.py)
    greedy          - the existing classical fund (built elsewhere)
    qubo_classical  - this QUBO, solved with a CLASSICAL sampler ("sim")
    qubo_quantum    - the SAME QUBO, solved on real D-Wave ("hybrid"/"qpu")
qubo_classical isolates the objective-function effect; the gap from it to
qubo_quantum isolates the quantum-solver effect. Build the QUBO ONCE and solve
it with each sampler so both arms attack an identical problem.

SAMPLERS
    "sim"    SimulatedAnnealingSampler  - classical, local, free, no token
    "hybrid" LeapHybridSampler          - decomposes large problems, mostly CPU
    "qpu"    DWaveSampler + embedding    - pure QPU (dense 150-var QUBO needs
                                           heavy minor-embedding; quality may
                                           degrade — see notes)
Hardware ("hybrid"/"qpu") requires DWAVE_API_TOKEN in the environment.

CONFIG (env vars, all optional)
    QUANTUM_CANDIDATE_POOL  default 150   candidates fed to the QUBO
    QUANTUM_TARGET_SIZE     default = SCREENER_TOP_N   target holdings (K)
    QUANTUM_SAMPLER         default hybrid  sampler for the qubo_quantum arm
    QUANTUM_NUM_READS       default 200   reads for sim/qpu (hybrid ignores it)
    QUANTUM_L1..QUANTUM_L4  default tuned  the lambda hyperparameters
    DWAVE_API_TOKEN         (none)        presence enables the quantum arm
    COV_METHOD / EWMA_HALFLIFE / LOOKBACK_YEARS   covariance estimator for the
                            risk term (core/covariance.py; EWMA by default)
"""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import pandas as pd

from config import settings
from core import fund

logger = logging.getLogger(__name__)

# Tuned defaults (validated on synthetic 150-name universes targeting ~100):
# l3 dominates so selection size tracks the target; l1/l2/l4 then trade quality
# against correlation and sector concentration. These are STARTING values — the
# main Week-3/4 tuning happens here, on real selections. Raise l2 for more
# diversification (lower correlation, lower mean score); lower it to track score.
_DEFAULT_LAMBDAS = {"l1": 1.0, "l2": 1.0, "l3": 3.0, "l4": 0.1}


# --------------------------------------------------------------------------- #
# Config helpers
# --------------------------------------------------------------------------- #
def _cfg_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def candidate_pool_size() -> int:
    return _cfg_int("QUANTUM_CANDIDATE_POOL", 150)


def target_size() -> int:
    return _cfg_int("QUANTUM_TARGET_SIZE", settings.SCREENER_TOP_N)


def lambdas() -> dict:
    out = dict(_DEFAULT_LAMBDAS)
    for k in out:
        v = os.getenv(f"QUANTUM_{k.upper()}")
        if v is not None:
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out


def hardware_available() -> bool:
    """True when a D-Wave Leap token is configured (enables the quantum arm)."""
    return bool(os.getenv("DWAVE_API_TOKEN"))


def production_sampler() -> str:
    """Sampler kind used for the qubo_quantum arm in production ('hybrid'/'qpu')."""
    return os.getenv("QUANTUM_SAMPLER", "hybrid").lower()


# --------------------------------------------------------------------------- #
# QUBO construction
# --------------------------------------------------------------------------- #
class QuboProblem:
    """A built QUBO: the matrix plus the metadata needed to interpret solutions."""

    def __init__(self, Q: dict, tickers: list[str], lam: dict, k: int,
                 cov_condition: float | None):
        self.Q = Q
        self.tickers = tickers
        self.lambdas = lam
        self.target_size = k
        self.n = len(tickers)
        self.cov_condition = cov_condition  # diagnostic: covariance conditioning


def build_qubo(candidates: list[dict], returns: pd.DataFrame,
               lam: dict | None = None, k: int | None = None) -> QuboProblem:
    """
    candidates : ranked candidate stock dicts (need 'ticker','score','sector').
    returns    : daily-return DataFrame covering at least the candidate tickers.
    Builds the QUBO over the candidates whose returns are available.
    """
    lam = lam or lambdas()
    k = k or target_size()

    tickers = [c["ticker"] for c in candidates if c["ticker"] in returns.columns]
    if len(tickers) < 2:
        raise ValueError("need >=2 candidates with available returns to build a QUBO")
    by_t = {c["ticker"]: c for c in candidates}

    # Covariance via the configured estimator (settings.COV_METHOD: EWMA by
    # default, Ledoit-Wolf optional), windowed to settings.LOOKBACK_YEARS and
    # coverage-filtered — see core/covariance.py. This replaces the v2.0 raw
    # sample covariance whose global dropna let one short-history candidate
    # truncate the estimation window for all names. Candidates that fail the
    # coverage filter are excluded from the QUBO (logged), so every array
    # below stays aligned with the covariance matrix ordering.
    from core import covariance
    cov, cov_info = covariance.estimate(returns[tickers])
    if cov_info["dropped"]:
        logger.info("QUBO: %d candidates excluded for sparse return history: %s",
                    len(cov_info["dropped"]), cov_info["dropped"][:10])
    tickers = cov_info["tickers"]

    n = len(tickers)
    scores = np.array([max(float(by_t[t].get("score") or 0.0), 0.0) for t in tickers])
    s = scores / 100.0  # normalise scores to ~[0,1]
    sectors = [by_t[t].get("sector", "Unknown") for t in tickers]

    cmax = np.max(np.abs(cov)) or 1.0
    c = cov / cmax  # normalise so lambdas are scale-stable across universes
    try:
        cov_condition = float(np.linalg.cond(cov))
    except np.linalg.LinAlgError:
        cov_condition = None

    l1, l2, l3, l4 = lam["l1"], lam["l2"], lam["l3"], lam["l4"]
    Q: dict = {}

    def add(i, j, val):
        key = (i, j) if i <= j else (j, i)
        Q[key] = Q.get(key, 0.0) + val

    # Quality (linear reward -> negative diagonal)
    for i in range(n):
        add(i, i, -l1 * s[i])

    # Risk (quadratic penalty); symmetric double-sum -> 2*c on unordered pairs
    for i in range(n):
        add(i, i, l2 * c[i, i])
        for j in range(i + 1, n):
            if c[i, j] != 0.0:
                add(i, j, l2 * 2.0 * c[i, j])

    # Size constraint (sum x - K)^2 -> diagonal (1-2K), off-diagonal +2
    for i in range(n):
        add(i, i, l3 * (1.0 - 2.0 * k))
        for j in range(i + 1, n):
            add(i, j, l3 * 2.0)

    # Sector diversification: penalise each same-sector selected pair
    for i in range(n):
        for j in range(i + 1, n):
            if sectors[i] == sectors[j]:
                add(i, j, l4)

    logger.info("QUBO built: %d candidates, target K=%d, lambdas=%s", n, k, lam)
    return QuboProblem(Q, tickers, lam, k, cov_condition)


# --------------------------------------------------------------------------- #
# Sampling
# --------------------------------------------------------------------------- #
def _make_sampler(kind: str):
    """Return (sampler, is_quantum, solver_name). Hardware needs DWAVE_API_TOKEN."""
    kind = (kind or "sim").lower()
    if kind == "sim":
        from dwave.samplers import SimulatedAnnealingSampler
        return SimulatedAnnealingSampler(), False, "SimulatedAnnealingSampler"
    if kind == "hybrid":
        from dwave.system import LeapHybridSampler
        return LeapHybridSampler(), True, "LeapHybridSampler"
    if kind == "qpu":
        from dwave.system import DWaveSampler, EmbeddingComposite
        return EmbeddingComposite(DWaveSampler()), True, "DWaveSampler(EmbeddingComposite)"
    raise ValueError(f"unknown sampler kind {kind!r}; use 'sim', 'hybrid', or 'qpu'")


def solve(problem: QuboProblem, kind: str = "sim",
          num_reads: int | None = None) -> tuple[list[str], dict]:
    """Solve the QUBO; return (selected_tickers, diagnostics)."""
    from core import research_log  # for make_diagnostics (no circular import at module load)

    num_reads = num_reads or _cfg_int("QUANTUM_NUM_READS", 200)
    sampler, is_quantum, solver_name = _make_sampler(kind)

    t0 = time.time()
    if kind == "hybrid":
        sampleset = sampler.sample_qubo(problem.Q)          # hybrid ignores num_reads
    else:
        sampleset = sampler.sample_qubo(problem.Q, num_reads=num_reads)
    wall = time.time() - t0

    best = sampleset.first.sample
    selected = [problem.tickers[i] for i in range(problem.n) if best.get(i, 0) == 1]

    energies = np.array([rec.energy for rec in sampleset.record]) if len(sampleset.record) else np.array([])
    chain_break = None
    qubits_used = None
    info = getattr(sampleset, "info", {}) or {}
    try:
        if "chain_break_fraction" in sampleset.record.dtype.names:
            cbf = sampleset.record["chain_break_fraction"]
            chain_break = float(np.mean(cbf)) if len(cbf) else None
    except (AttributeError, TypeError):
        pass
    emb = info.get("embedding_context", {}) if isinstance(info, dict) else {}
    if isinstance(emb, dict) and emb.get("embedding"):
        qubits_used = int(sum(len(v) for v in emb["embedding"].values()))

    diagnostics = research_log.make_diagnostics(
        solver=solver_name,
        is_quantum=is_quantum,
        num_reads=(None if kind == "hybrid" else num_reads),
        best_energy=float(sampleset.first.energy),
        energy_std=float(energies.std()) if energies.size > 1 else None,
        chain_break_fraction=chain_break,
        num_qubits_used=qubits_used,
        wall_seconds=wall,
        lambdas=problem.lambdas,
        target_size=problem.target_size,
    )
    logger.info("QUBO solved (%s): %d names selected (target %d), best energy %.3f, %.2fs",
                solver_name, len(selected), problem.target_size,
                sampleset.first.energy, wall)
    return selected, diagnostics


# --------------------------------------------------------------------------- #
# Assemble a Fund object from a QUBO selection
# --------------------------------------------------------------------------- #
def build_fund_from_selection(selected: list[str], candidates: list[dict],
                              returns: pd.DataFrame,
                              bench_daily: pd.Series) -> tuple[dict, dict]:
    """Weight the selected names with the existing classical weighting and build
    the Fund object. Returns (fund_dict, weights_dict). The fund's 'weights' key
    is popped out and returned separately (kept on the arm, never on stocks)."""
    chosen = [c for c in candidates if c["ticker"] in set(selected)]
    if not chosen:
        raise ValueError("QUBO selection is empty; check lambdas/target size")
    f = fund.build_fund(chosen, returns, bench_daily)
    f["name"] = "US Quality-Tilted Fund (QUBO)"
    f["weighting"] = "QUBO-selected, score-weighted"
    weights = f.pop("weights", {})
    return f, weights


# --------------------------------------------------------------------------- #
# Convenience: build one full arm end to end (build QUBO, solve, assemble)
# --------------------------------------------------------------------------- #
def build_arm(candidates: list[dict], returns: pd.DataFrame, bench_daily: pd.Series,
              kind: str = "sim", *, problem: QuboProblem | None = None) -> dict:
    """Returns {'fund','selection','weights','diagnostics'} for one sampler.
    Pass a pre-built `problem` to guarantee multiple arms solve the IDENTICAL
    QUBO (the controlled-comparison requirement)."""
    problem = problem or build_qubo(candidates, returns)
    selection, diagnostics = solve(problem, kind)
    f, weights = build_fund_from_selection(selection, candidates, returns, bench_daily)
    return {"fund": f, "selection": selection, "weights": weights, "diagnostics": diagnostics}
