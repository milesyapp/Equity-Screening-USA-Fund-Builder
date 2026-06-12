@AGENTS.md

# EquityLens — project context for Claude Code

US equity research instrument. Screens the S&P Composite 1500, scores every
name, builds a 100-stock score-weighted "fund", and runs a classical-vs-quantum
(QUBO) portfolio-construction experiment. Public site: equitylens.xyz.

**Framing matters:** this is an honest *research instrument*, not a performance
product. In-sample metrics are characterisations of today's basket, never a
track record. The forward log is the only out-of-sample evidence. Preserve this
framing in any copy or methodology you touch — do not overstate results.

## Architecture

- **Frontend** — Next.js (App Router). Entry: `app/page.tsx` → `Landing` →
  `/fund/[arm]` → `FundDetail` + `Research`. Reads `data/latest.json`. No
  server runtime for data; the page renders a committed JSON blob.
- **Pipeline** — Python in `python/`. Orchestrators: `run_screen.py` (weekly,
  full rescreen) and `run_daily.py` (daily, re-prices frozen holdings — no
  re-selection). Core modules in `python/core/`, config in
  `python/config/settings.py`.
- **Three arms** — `greedy` (score-weighted, the baseline), `qubo_classical`
  (simulated annealing), `qubo_quantum` (D-Wave; only runs if `DWAVE_API_TOKEN`
  is set). All three select from the same candidate pool; the QUBO is built
  ONCE and solved by both samplers (controlled comparison).
- **Forward record** — `data/research_log.jsonl`, append-only, one row per
  trading day. Keyed on the last PRICE date (not run date) so weekend re-runs
  dedup. This is the project's core evidence; treat it as sacred.
- **Automation** — GitHub Actions: `.github/workflows/weekly_screen.yml` and
  `daily_refresh.yml`. The daily job auto-commits a refreshed `latest.json`.

## Commands

```bash
# Python (run from python/)
cd python
python3 run_screen.py > ../data/latest.json   # full weekly rescreen (~10 min, hits EDGAR+Alpaca)
python3 run_daily.py                            # daily re-price of frozen holdings
python3 test_fundamentals.py                    # SEC extraction logic
python3 test_covariance.py                      # EWMA / Ledoit-Wolf estimator
python3 test_quantum_fund.py                    # QUBO build/solve regression
python3 test_research_log.py                    # forward-stats regression
python3 validate_and_sample.py                  # full offline pipeline check

# Frontend (run from repo root)
rm -rf .next && npx tsc --noEmit                # typecheck (clear stale .next first)
npm run dev                                      # local dev server
```

Always run the full Python test suite + `tsc --noEmit` before committing
pipeline or type changes. All five Python suites must end "ALL PASS".

## Conventions & environment

- Read the Next.js docs in `node_modules/next/dist/docs/` before frontend work
  (see AGENTS.md — this Next.js has breaking changes vs training data).
- Secrets live in `python/.env` (gitignored, never committed). Never write key
  values into any tracked file, including this one.
- `settings.TRADING_DAYS` (252) is the single source of truth for
  annualisation — import it, never redefine.
- New fields added to the data contract must be OPTIONAL in `lib/types/index.ts`
  so old `latest.json` blobs still render.
- macOS Python 3.9 + system numpy emits spurious matmul RuntimeWarnings; the
  code wraps the affected matmuls in `np.errstate(...)` and validates outputs.
  Keep that pattern when adding linear-algebra code.

## State as of v2.1 (already fixed — do not regress)

- **Fundamentals extraction** (`core/fundamentals.py`): annual SEC facts are
  duration-filtered (330–400 day spans for flow concepts; instant concepts
  exempt), restatement-aware (latest `filed` wins), revenue is the per-year MAX
  across concepts incl. bank/insurer top lines, and margins >100% / growth
  >1000% are gated to None. This killed the old "446% net margin" class of bug.
- **Covariance** (`core/covariance.py`): real EWMA / Ledoit-Wolf / sample
  estimator, windowed to LOOKBACK_YEARS with a 60% coverage filter. Feeds the
  QUBO risk term. COV_METHOD/EWMA_HALFLIFE are now genuinely used.
- **Benchmark**: SPTM (S&P 1500), matching the selection universe — alpha/beta
  are not size artifacts. (Was IVV.)
- **Alpha**: CAPM alpha now ships with a Newey-West HAC t-stat (`alphaTStat`).
- **Forward stats** (`core/research_log.py`): annualised active return / TE /
  IR / arm-Sharpe are gated behind `_MIN_ANNUALISE_DAYS` (20). Below that they
  are None and the UI shows "—". A `activeReturnCumulative` field is honest at
  any n. This fixed a spurious −48% annualised figure at n=2.
- **Limitations**: `screener.py` writes a machine-readable
  `methodology.limitations[]`, rendered verbatim on the fund page.
- Dead code removed: `Screener.tsx`, v1 multi-asset config block.

## Known limitations (disclosed, structural — not bugs)

- **Survivorship bias**: universe is CURRENT S&P 1500 membership. Backward
  metrics are biased upward. Fixing needs point-in-time constituent data.
- **In-sample NAV**: applies today's weights backward; not walk-forward, no
  costs/turnover. Disclosed on the UI.
- **Free IEX feed**: volume is ~2-3% of consolidated, distorting the liquidity
  screen. SIP feed would fix it.
- **Cross-sector percentile scoring**: capital-light sectors dominate the top
  quintile; sparse-data names can rank on the pillar-50 fallback.

## Git workflow

- The daily Action commits to `main` autonomously. ALWAYS `git pull --rebase`
  before a local rescreen, or you'll hit a one-row conflict on
  `research_log.jsonl` / `latest.json`.
- That conflict resolution: keep the WEEKLY row for a shared date (it carries
  `selectionByArm`); a weekly run supersedes a same-day daily mark. After
  resolving, verify no duplicate dates in the log before pushing.
- After any forward-log edit, validate JSONL parses and has one row per date.

## Open roadmap (see EquityLens_Methodology_Audit.xlsx for full backlog)

Priority order, roughly:
1. Sector-neutral (within-GICS) percentile scoring.
2. ~~Min factor-coverage gate before ranking (stop pillar-50 fallback
   gaming).~~ **Done (linear shrinkage)**: pillar scores shrink toward 50 in
   proportion to factor coverage — missing factors are imputed at the universe
   median; the empty-pillar 50 is now the coverage-0 limit, not a special case.
3. ~~3yr CAGR for growth; 2-3yr average FCF (replace noisy single-year).~~
   **Done**: revenue growth → 3-yr elapsed-time CAGR (exponent = actual days
   between filings / 365.25; degrades to ~2-yr at 3 annual points; None below
   that — deliberately NO YoY fallback, shrinkage imputes the median). FCF →
   matched-period 3-yr average (margin = avg FCF ÷ avg revenue over the SAME
   years; yield = avg FCF ÷ current mcap). Rode along: fixed a latent capex
   period mismatch — first-concept-wins paired current CFO with a stale tag's
   last reported year for 45 scored names (NVDA: FY2026 CFO − FY2012 capex);
   capex is now per-year max across tags via `_merged_annual_series`, the
   revenue-merge generalised.
4. ~~Fix PEG to use earnings growth, or drop it (currently uses revenue
   growth).~~ **Done** (commit 7548d5d): PEG factor removed as a category
   error; weights renormalised.
5. Add Sortino + Calmar + deflated Sharpe to the forward panel — the rigorous
   answer to "is Sharpe robust for this fund" (NOT CQNS, which is a selection
   objective the QUBO already embodies, not an evaluation metric).
6. Time-varying / historical risk-free rate (currently hardcoded 4%).
7. Upgrade Alpaca IEX → SIP feed.
8. QUBO lambda sweep; weight selections from the optimiser (currently the
   covariance-aware solution is discarded at the score-weighting step).


