# v2.1 Methodology Fixes — Implementation Guide

Every file in this zip is a **drop-in replacement** (or new file) at the same
relative path inside your repo root. Nothing else changes.

## What's fixed (summary)

| # | Issue | Fix | File(s) |
|---|-------|-----|---------|
| 1 | Impossible margins (NVDA 446%, RF 2,073%, growth 1,173%) — 24/100 holdings corrupted | Duration-aware annual extraction (330–400d spans), restatement-aware dedupe (latest `filed` wins), broadest-top-line revenue for banks/insurers, plausibility gates | `python/core/fundamentals.py` |
| 2 | COV_METHOD/EWMA documented but never implemented; QUBO used raw sample cov with global dropna | New estimator module (EWMA / Ledoit-Wolf / sample), windowed + coverage-filtered; QUBO now uses it; scikit-learn dependency now real | `python/core/covariance.py` (new), `python/core/quantum_fund.py`, `python/config/settings.py` |
| 3 | Benchmark mismatch: all-cap fund vs large-cap IVV → size exposure leaked into "alpha" | Default benchmark → **SPTM** (S&P 1500 — exactly the selection universe) | `python/config/settings.py` |
| 4 | Bare alpha point estimate, no significance | Newey-West HAC t-stat on the daily OLS alpha, shipped as `alphaTStat` | `python/core/metrics.py`, `python/core/fund.py`, `lib/types/index.ts`, `app/components/FundDetail.tsx` |
| 5 | Survivorship / point-in-time biases undisclosed in the data contract | Machine-readable `methodology.limitations[]` written by the pipeline, rendered verbatim on the fund page | `python/core/screener.py`, `lib/types/index.ts`, `app/components/FundDetail.tsx` |
| 6 | `run_daily` could write `NaN` into latest.json → invalid JSON → blank site | NaN-guarded trailing-return refresh; also pins the refreshed benchmark label to the frozen series | `python/run_daily.py` |
| 7 | Dead v1 multi-asset config (allocator, cash sleeves, 60/40 benchmark, unused gates) | Removed; `validate()` now checks what actually exists, incl. SCORE_WEIGHTS sum to 1 | `python/config/settings.py` |
| 8 | Stale docstring claiming regime "drives the sector tilt" | Corrected: display-only | `python/reports/market_analyzer.py` |
| 9 | Frontend hardcoded "IVV"; broken `/screener` link | Dynamic `fund.benchmark`; dead link removed | `app/components/FundDetail.tsx` |

## Install

```bash
# from your repo root
unzip -o portfolio-optimizer-v2.1-fixes.zip
rm -rf .next                      # stale generated types reference deleted routes
```

## Verify (all offline, no keys)

```bash
cd python
python3 test_fundamentals.py      # ALL PASS — the margin-bug fix
python3 test_covariance.py        # ALL PASS — EWMA / Ledoit-Wolf
python3 test_quantum_fund.py      # ALL PASS — regression vs new estimator
python3 test_research_log.py      # ALL PASS — regression
python3 validate_and_sample.py    # ALL CHECKS PASSED — full pipeline
cd .. && npx tsc --noEmit         # frontend types clean
```

## Regenerate data, then ship

```bash
cd python && python3 run_screen.py > ../data/latest.json && cd ..
npm run dev      # inspect /fund/greedy: sane margins, alpha (t …), SPTM, limitations panel
git add -A && git commit -m "v2.1: fundamentals extraction fix, real covariance estimator, SPTM benchmark, alpha t-stat, disclosed limitations" && git push
```

GitHub Actions takes over from there (weekly screen + daily refresh unchanged).

## Notes

- **Forward log continuity**: arm daily returns are benchmark-independent, so
  `data/research_log.jsonl` keeps accumulating seamlessly. Only alpha/beta
  definitions change (disclosed in the limitations block).
- **Score discontinuity is expected**: ~24% of holdings had corrupted health
  inputs, so the first post-fix weekly run will reshuffle ranks. That's the
  fix working, not a regression.
- Old `latest.json` (pre-2.1) renders fine: new fields are optional in TS.
