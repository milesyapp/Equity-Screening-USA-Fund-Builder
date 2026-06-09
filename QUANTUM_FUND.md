# Quantum Fund (QUBO portfolio selection)

`core/quantum_fund.py` builds a fund by solving a QUBO that balances quality
against correlation, instead of greedily taking the top-N by score. Selection is
the quantum step; weighting reuses the existing `fund.build_fund`, so the output
matches the `Fund` schema and renders with existing components.

## The three arms

| arm | how it's built | what it isolates |
|-----|----------------|------------------|
| `greedy` | top-N by score, score-weighted (the existing fund) | baseline |
| `qubo_classical` | the QUBO, solved with a classical simulator | objective-function effect |
| `qubo_quantum` | the **same** QUBO, solved on real D-Wave hardware | quantum-solver effect |

The QUBO is built **once** and solved by both samplers, so the only difference
between `qubo_classical` and `qubo_quantum` is the solver. That's what lets you
attribute any difference to "quantum" rather than to the objective.

## What runs when

- **`qubo_classical` runs everywhere, no token.** It uses the classical
  `SimulatedAnnealingSampler`. This is live the moment you deploy Phase 1.
- **`qubo_quantum` runs only when `DWAVE_API_TOKEN` is set.** Without a token it
  is skipped and the pipeline logs greedy + classical-QUBO. With a token it uses
  the sampler named by `QUANTUM_SAMPLER` (default `hybrid`).
- **Selection happens only in the weekly run.** The daily refresh re-prices the
  frozen selections (including the quantum one) — no D-Wave call daily, so Leap
  minutes are spent ~once a week.
- The whole quantum block is wrapped in try/except: a D-Wave outage or QUBO
  error can never break the classical pipeline.

## Run it locally (Week 1, simulator, no token)

```bash
cd python
pip install -r requirements.txt           # installs dwave-ocean-sdk
python3 test_quantum_fund.py               # offline self-test, expect ALL PASS
python3 run_screen.py > /tmp/out.json      # full pipeline with your Alpaca/SEC keys
python3 -c "import json; d=json.load(open('/tmp/out.json')); print([a['key'] for a in d['portfolio']['research']['arms']])"
# -> ['greedy', 'qubo_classical']
```

## Turn on real quantum (Week 2)

1. Get your token from the D-Wave Leap dashboard (Solver API token).
2. Add it as a GitHub repo secret named `DWAVE_API_TOKEN`
   (Settings → Secrets and variables → Actions → New repository secret).

That's it. Both workflows already pass `DWAVE_API_TOKEN` into `.env`, so the next
weekly run will add the `qubo_quantum` arm automatically. To test locally first:

```bash
cd python
export DWAVE_API_TOKEN=your-token-here
python3 -c "from core import quantum_fund as Q; print('hardware:', Q.hardware_available(), '| sampler:', Q.production_sampler())"
python3 run_screen.py > /tmp/out.json
python3 -c "import json; d=json.load(open('/tmp/out.json')); print([a['key'] for a in d['portfolio']['research']['arms']])"
# -> ['greedy', 'qubo_classical', 'qubo_quantum']
```

`hybrid` (LeapHybridSampler) is recommended for 150 variables — it decomposes the
problem and is robust. `qpu` (pure DWaveSampler) runs entirely on the annealer but
a dense 150-variable QUBO needs heavy minor-embedding with long chains, which
degrades solution quality; use it only to study the QPU directly.

## Tuning knobs (Week 3-4, the real research work)

All optional env vars (defaults shown):

```
QUANTUM_CANDIDATE_POOL=150     # candidates fed to the QUBO
QUANTUM_TARGET_SIZE=100        # target holdings K (defaults to SCREENER_TOP_N)
QUANTUM_SAMPLER=hybrid         # sampler for the quantum arm: hybrid | qpu
QUANTUM_NUM_READS=200          # reads for sim/qpu (hybrid ignores it)
QUANTUM_L1=1.0                 # quality reward
QUANTUM_L2=1.0                 # risk (covariance) penalty  -> raise for more diversification
QUANTUM_L3=3.0                 # size constraint            -> raise to push size toward K
QUANTUM_L4=0.1                 # sector concentration penalty
```

The lambdas are the experiment's main lever. Defaults were tuned on synthetic
150-name universes to hit ~K holdings and cut portfolio variance vs greedy; they
are a starting point, to be refined on real selections. Higher `l2` trades mean
score for lower correlation; `l3` controls how tightly size tracks `K`.

Note: at target ~= most of the pool (100 of 150), the quality term has little room
to act — the diversification terms drive which ~50 names are dropped. For a
stronger quality signal, lower `QUANTUM_TARGET_SIZE` or raise the pool.
