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
python3 test_riskfree.py                        # time-varying rf (offline, synthetic)
python3 validate_and_sample.py                  # full offline pipeline check

# Frontend (run from repo root)
rm -rf .next && npx tsc --noEmit                # typecheck (clear stale .next first)
npm run dev                                      # local dev server
```

Always run the full Python test suite + `tsc --noEmit` before committing
pipeline or type changes. All six Python suites must end "ALL PASS".

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
- **Robustness stats** (v2.2, `core/research_log.py`): per-arm-and-baseline
  `maxDrawdown` (cumulative, ungated), `sortino`, `calmar` (own gate
  `_MIN_CALMAR_DAYS` = 60; tiny-n drawdown denominators explode), and
  `probSharpePositive` (Bailey–López de Prado PSR vs 0; γ₄ is RAW kurtosis,
  scipy `fisher=False` — NOT excess; deliberately not the deflated variant).
  Zero-denominator Sortino/Calmar are None, never 0. All new JSON fields are
  optional in `lib/types/index.ts`. (The original v2.2 zero-rf forward
  Sortino carve-out was RESOLVED by item 6: forward Sharpe/Sortino/PSR are
  now all excess of the time-varying rf, one convention everywhere.)
- **Time-varying risk-free rate** (v2.3, `core/riskfree.py`): every
  rf-dependent metric uses the contemporaneous 3-month T-bill yield. Source
  is the U.S. Treasury daily par curve ("3 Mo" — the series FRED republishes
  as DGS3MO; FRED's own endpoints 403 datacenter IPs / timed out, so Treasury
  is deliberately the PRIMARY). Resilience chain: fetch → committed cache
  `data/riskfree_3mo.csv` → 4% constant with warning. daily rf = annual /
  TRADING_DAYS (simple division — do NOT introduce a geometric convention);
  alignment is ffill onto the trading index (bond holidays, the unpublished
  seam, stale cache all carry the last print forward). Tests are offline
  (`test_riskfree.py` injects synthetic series — never hit Treasury in tests).
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
- ~~**Cross-sector percentile scoring**: capital-light sectors dominate the top
  quintile; sparse-data names can rank on the pillar-50 fallback.~~ **Fixed
  2026-06-12 (roadmap item 1) — and the original diagnosis was wrong**: the
  measured dominator was Financials (32/100 slots, ~2.3× universe share, via
  bank/insurer margins and ROE), not capital-light sectors. Sector-neutral
  ranking rebalanced the mix; the sparse-data half was already fixed by the
  item-2 coverage shrinkage.

## Git workflow

- The daily Action commits to `main` autonomously. ALWAYS `git pull --rebase`
  before a local rescreen, or you'll hit a one-row conflict on
  `research_log.jsonl` / `latest.json` / `data/riskfree_3mo.csv`.
- That conflict resolution: keep the WEEKLY row for a shared date (it carries
  `selectionByArm`); a weekly run supersedes a same-day daily mark. After
  resolving, verify no duplicate dates in the log before pushing.
- After any forward-log edit, validate JSONL parses and has one row per date.
- A conflict on `data/riskfree_3mo.csv` is trivial: take EITHER side — it is a
  cache of public Treasury yields and is refetched/rewritten on the next run.
  Don't puzzle over it like the forward log; nothing in it is evidence.

## Open roadmap (see EquityLens_Methodology_Audit.xlsx for full backlog)

Priority order, roughly:
1. ~~Sector-neutral (within-GICS) percentile scoring.~~ **Done (2026-06-12,
   commit "feat: sector-neutral percentile scoring…")**: health and valuation
   factors rank within GICS sector; momentum stays universe-wide
   (deliberately — cross-sectional momentum captures sector trends). Thin
   sector×factor cells (< `SECTOR_NEUTRAL_MIN_COUNT` = 10 non-NaN names) and
   "Unknown" sectors (regardless of size — a grab-bag, not a peer group) fall
   back to universe-wide ranks per factor, logged when firing. The item-2
   shrinkage line is UNCHANGED: 50 in percentile space is the median of the
   rank population, so imputation moved to the sector median automatically
   (universe median where the fallback fired). Reasons say "of its sector" /
   "of the universe" per name per factor, matching the actual comparison.
   **REGIME CHANGE — structural break in the forward log**: rows in
   `research_log.jsonl` before 2026-06-12 were selected under universe-wide
   ranking. Measured impact on the change date: 28/100 of the top-100
   replaced; Financials 32 → 8 fund slots (they had dominated at ~2.3× their
   universe share via bank/insurer margins and ROE). Disclosed in
   `methodology.limitations[]`. Watch the greedy-vs-QUBO selection overlap
   after the first new-regime weekly run: with Financials no longer flooding
   the pool, the QUBO sector-concentration penalty has less to do and the
   arms' baskets may converge.
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
5. ~~Add Sortino + Calmar + deflated Sharpe to the forward panel — the rigorous
   answer to "is Sharpe robust for this fund" (NOT CQNS, which is a selection
   objective the QUBO already embodies, not an evaluation metric).~~
   **Done**: forward panel (per arm + baseline) gains max drawdown (cumulative,
   honest and ungated from day 1, like `activeReturnCumulative`), Sortino
   (zero-rf to match the panel's raw Sharpe convention — the rf-excess version
   stays in the 3Y/5Y windows; unify when item 6 lands), Calmar (own higher
   floor `_MIN_CALMAR_DAYS = 60`: tiny-n drawdown denominators print absurd
   ratios), and `probSharpePositive` — Bailey & López de Prado PROBABILISTIC
   Sharpe vs 0, with γ₄ = RAW kurtosis (3 for a normal; convention verified
   against the Lo/Mertens normal-case SE by Monte Carlo). Deliberately NOT the
   deflated variant: 3 pre-registered arms, no mined trials to deflate.
   Zero-denominator Sortino/Calmar report None, never 0. In-sample 3Y/5Y
   windows gain `sortinoRatio`/`calmarRatio` via the existing metrics.py
   functions.
6. ~~Time-varying / historical risk-free rate (currently hardcoded 4%).~~
   **Done (2026-06-12)**: 3-month T-bill from the Treasury daily par curve
   (DGS3MO-equivalent; FRED itself blocks datacenter IPs — found before it
   could strand the cache), threaded through `metrics.sharpe_ratio` /
   `sortino_ratio` / `alpha_newey_west` (now accept float | Series),
   `fund._window_metrics` (each window uses ITS OWN mean prevailing rate),
   and the forward panel (Sharpe/Sortino/PSR all excess-of-rf — the item-5
   zero-rf carve-out is resolved; bootstrap Sharpe-diff resamples rf with the
   same block indices). Measured at the change date: 3Y Sharpe −0.05 (window
   rf averaged 4.70%), 5Y ≈ unchanged (3.80%); alpha moved ~1bp because its
   rf sensitivity is (1−β)·Δrf and β≈0.99 — that near-cancellation is
   structural, not a wiring bug (comment at the alpha call site). Selections
   unaffected (scoring never used rf): metric values shifted, NO forward-log
   structural break. Disclosed in `methodology.limitations[]`.
7. Upgrade Alpaca IEX → SIP feed.
8. QUBO lambda sweep; weight selections from the optimiser (currently the
   covariance-aware solution is discarded at the score-weighting step).


