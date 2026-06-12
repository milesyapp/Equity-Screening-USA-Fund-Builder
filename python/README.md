# Backend — US Equity Screener (v2.0)

Screens the broad US universe (S&P 500/400/600), scores every eligible name on
three pillars, ranks the top 100, and builds a score-weighted mini-fund.

## Pillars & weights (stated verbatim on the frontend)

| Pillar | Weight | Factors |
|---|---|---|
| **Financial health** | 70% | ROE, operating margin, net margin, FCF margin (matched-period 3-yr average), revenue growth (3-yr elapsed-time CAGR; None below 3 annual filings — no YoY fallback), debt/equity (inverted) |
| **Valuation** | 20% | P/E (inverted, only if > 0), FCF yield (3-yr average FCF / current market cap) |
| **Momentum** | 10% | 6-month and 3-month price return |

Each factor is converted to a **percentile rank** across the scored universe
(robust to outliers and to the different scales of the factors). Missing factors
are imputed at the universe median: each pillar mean is shrunk toward the
neutral 50 in proportion to factor coverage (a name with 1 of 6 health factors
keeps only 1/6 of its distance from the median), so sparse names cannot post
extreme pillar scores from a single ratio. The composite is the weighted
average of the three pillar scores.

## Data sources

- **Prices** — Alpaca daily bars (`ALPACA_FEED=iex` on the free plan).
- **Fundamentals** — SEC EDGAR company-facts (most recent annual 10-K).
- **Universe + GICS sector** — S&P 500/400/600 constituent tables (Wikipedia).

> Alpaca's data API is US-only and carries **no fundamentals**, which is why
> fundamentals come from EDGAR. Europe / emerging markets are **not** built yet
> — see the roadmap. This backend is US-only by design for now.

## Setup

Create `python/.env`:

```
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_FEED=iex
SEC_USER_AGENT="Your Project your@email.com"
```

`SEC_USER_AGENT` must be real contact info or EDGAR will rate-limit/403 you.

Install deps:

```bash
cd python
pip install -r requirements.txt
```

## Run

**Weekly — full screen (re-selects & re-ranks):**

```bash
cd python
python3 run_screen.py > test_output.json
cp test_output.json ../data/latest.json
```

**Daily — re-price the frozen selection (ranks stay put):**

```bash
cd python
python3 run_daily.py          # updates ../data/latest.json in place
```

The weekly job chooses and ranks the 100. The daily job keeps that same
selection and its score weights, refreshing only prices, trailing returns, and
the fund's NAV/metrics — so day-to-day the list is stable while prices stay
current.

## Performance expectations

This screens the **whole** universe (your call — "don't miss hidden gems"), so
the weekly run fetches EDGAR fundamentals for every liquid, 3y+-history name
(~1,500–2,000 requests at <10/s, with retry/back-off). Expect a few minutes.
The daily run only touches ~100 names + the benchmark, so it's quick.

Tune via env vars: `SCREENER_TOP_N` (default 100), `SCREENER_MIN_HISTORY_YEARS`
(3.0), `MIN_AVG_VOLUME`, `MIN_PRICE`, `SCORE_W_HEALTH/VALUATION/MOMENTUM`,
`SCREENER_MAX_WEIGHT` (4% per-name fund cap), `SCREENER_BENCHMARK` (IVV).

## Validate the logic offline (no API keys needed)

```bash
cd python
python3 validate_and_sample.py
```

This exercises the scoring + fund math with synthetic data, asserts the
invariants (scores in [0,100], ranking monotonic, fund weights sum to 1 and
respect the cap, alpha/beta/Sharpe/drawdown all compute, NAV rebased to 1.00),
and writes a `sample_latest.json` you can drop into the frontend's `data/`.

## Files

```
run_screen.py            weekly entry point (full screen → JSON)
run_daily.py             daily entry point (re-price frozen selection)
validate_and_sample.py   offline logic test + sample-data generator
core/screener.py         orchestrates universe → screen → score → rank → fund
core/scoring.py          the 70/20/10 percentile-rank scoring engine
core/fund.py             score-weighted basket, 3Y/5Y metrics, alpha/beta, NAV
core/data_fetcher.py     Alpaca prices + Wikipedia universe (reused)
core/fundamentals.py     SEC EDGAR fundamentals (reused)
core/metrics.py          Sharpe / drawdown / beta / etc. (reused)
reports/market_analyzer.py  VIX / market gauges (reused)
config/settings.py       all tunables (screener config added)
```
