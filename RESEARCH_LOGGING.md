# Research Logging Architecture (classical vs quantum)

The instrumentation backbone for the multi-arm fund experiment. Built and tested
standalone; the two integration edits to the live pipeline are documented below
for you to apply and review (they touch files that drive the live site).

## What an "arm" is

| key              | meaning                                              | role         |
|------------------|------------------------------------------------------|--------------|
| `greedy`         | existing classical score-weighted fund               | baseline     |
| `qubo_classical` | the QUBO objective, solved with a classical sampler  | control      |
| `qubo_quantum`   | the **same** QUBO, solved on real D-Wave hardware    | experimental |

The `greedy → qubo_classical` gap isolates the *objective-function* effect; the
`qubo_classical → qubo_quantum` gap isolates the *quantum-solver* effect. Logging
all three is what makes "quantum advantage" a separable, defensible claim.

## Two persistence targets

1. **`data/latest.json` → `portfolio.research`** — the current snapshot the site
   renders: every arm's full `Fund` object, QUBO diagnostics, pairwise selection
   overlap, and the forward comparison stats. Overwritten each run.
2. **`data/research_log.jsonl`** — **append-only** forward record, one line per
   run, carrying each arm's realized daily return. This is what the significance
   tests consume. It is *never* overwritten (deduped by date). This file is the
   paper's raw data — back it up / commit it.

## New + changed files

| file | status | notes |
|------|--------|-------|
| `python/core/research_log.py` | **new** | the module (no dwave dependency) |
| `python/test_research_log.py` | **new** | offline self-test, no keys/token |
| `lib/types/index.ts` | edited (additive) | research types; reuses `Fund` |
| `lib/portfolio.ts` | edited (additive) | `getResearch()` |
| `python/core/screener.py` | **apply snippet A** | weekly: build arms, log |
| `python/run_daily.py` | **apply snippet B** | daily: re-mark each arm forward |

## Test it now (no keys, no token)

```bash
cd python && python3 test_research_log.py     # expect "ALL PASS"
```

## Snippet A — `screener.py` (weekly)

In `run()`, immediately **after** `the_fund = fund.build_fund(...)` and the
`fw = the_fund.pop("weights", {})` block, before the `return {...}`:

```python
# 9. Research arms + forward logging ------------------------------------
from core import research_log

def _latest_return(weights: dict, rets) -> float | None:
    """Most-recent-day portfolio return for a set of frozen weights."""
    held = [t for t in weights if t in rets.columns]
    if not held or rets.empty:
        return None
    last = rets[held].iloc[-1].fillna(0.0)
    w = pd.Series({t: weights[t] for t in held}); w /= w.sum() or 1.0
    return float((last * w).sum())

greedy_arm = research_log.make_arm(
    "greedy", the_fund,
    selection=[s["ticker"] for s in stocks],
    weights=fw,
)
arms = [greedy_arm]
# When quantum_fund.py lands, append its arms here, e.g.:
#   arms.append(research_log.make_arm("qubo_classical", qf_c["fund"],
#               qf_c["selection"], qf_c["weights"], qf_c["diagnostics"]))
#   arms.append(research_log.make_arm("qubo_quantum",   qf_q["fund"],
#               qf_q["selection"], qf_q["weights"], qf_q["diagnostics"]))

arm_returns = {a["key"]: _latest_return(a["weights"], returns) for a in arms}
research_log.append_run_record(
    market["date"], "weekly", arm_returns,
    rebalance={"selectionByArm": {a["key"]: a["selection"] for a in arms}},
)
research_block = research_log.build_research_block(arms, as_of=market["date"])
```

Then add one key to the returned dict:

```python
        "fund": the_fund,
        "research": research_block,      # <-- add this line
        "marketConditions": market,
```

## Snippet B — `run_daily.py` (daily re-mark)

The daily refresh must re-price the **union** of every arm's holdings (quantum
arms can hold names ranked 101–150 that are not in the classical top-100) and
append a fresh forward mark per arm — **without** re-running the solver
(selection is frozen between weekly runs, so no D-Wave call here; this conserves
Leap minutes). After the existing classical refresh, before writing the file:

```python
from core import research_log
prev = port.get("research")
if prev and prev.get("arms"):
    # union of all arm tickers must be in the downloaded price set
    arm_returns = {}
    for arm in prev["arms"]:
        w = arm.get("weights", {})
        held = [t for t in w if t in close.columns]
        if held:
            last = close[held].pct_change(fill_method=None).iloc[-1].fillna(0.0)
            wser = pd.Series({t: w[t] for t in held}); wser /= wser.sum() or 1.0
            arm_returns[arm["key"]] = float((last * wser).sum())
    research_log.append_run_record(market["date"], "daily", arm_returns)
    # refresh the embedded forward stats from the now-longer history
    prev["forwardStats"] = research_log.forward_stats(research_log.load_history())
    port["research"] = prev
```

> When you wire arm holdings into the daily download set, extend the
> `download_price_data([...])` ticker list to include every arm's selection, not
> just `port["stocks"]`.

## Committing

```bash
git add python/core/research_log.py python/test_research_log.py \
        lib/types/index.ts lib/portfolio.ts RESEARCH_LOGGING.md
# after applying snippets A & B:
git add python/core/screener.py python/run_daily.py
git commit -m "Add classical-vs-quantum research logging architecture"
git push
```

`data/research_log.jsonl` is created on first run and should be committed so the
forward record survives across deploys.

## Statistical honesty (baked in)

`forward_stats` reports active return, tracking error, information ratio, a
Newey-West (HAC) t-stat on mean daily active return, and a moving-block-bootstrap
CI + p-value on the Sharpe difference. Because the arms are highly correlated
equity funds, expect wide CIs and large p-values for a long time — the self-test
demonstrates this directly. The parametric Ledoit-Wolf (2008) HAC Sharpe-difference
test is the recommended upgrade and has a reserved hook (`ledoitWolfTest`).
