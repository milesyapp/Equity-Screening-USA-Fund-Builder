# Frontend Setup — US Equity Screener (v2.0)

This replaces the old multi-asset dashboard with the **US Equity Screener**:
a ranked table of the top 100 US stocks (score-weighted on financial health,
valuation, and momentum), each with a hover breakdown, plus a score-weighted
"mini-fund" with 3Y/5Y metrics (return, volatility, Sharpe, max drawdown,
alpha, beta) and a fund-vs-benchmark NAV chart.

## 1. One new dependency

The screener uses **`lucide-react`** for icons (recharts is already in your
project from the old dashboard). Install it:

```bash
npm install lucide-react
```

If `recharts` somehow isn't present:

```bash
npm install recharts
```

## 2. Files in this zip

```
app/page.tsx                 ← server component; reads data/latest.json
app/components/Screener.tsx  ← the new dashboard (replaces Dashboard.tsx)
app/api/portfolio/route.ts   ← serves the screen JSON at /api/portfolio
lib/types/index.ts           ← new data contract (Screen / StockPick / Fund)
lib/portfolio.ts             ← server-only JSON reader
data/latest.json             ← SAMPLE data so the UI renders immediately
```

> **`Dashboard.tsx` is no longer used.** `page.tsx` now imports `Screener`.
> You can delete the old `app/components/Dashboard.tsx` once you're happy.

## 3. The bundled data is a SAMPLE

`data/latest.json` ships with **synthetic** rows — tickers like `SYN001`,
"Synthetic Company 219". This is so the page renders the moment you start the
dev server, before you've run the real pipeline. It is obviously fake; replace
it with a real run (see the backend zip):

```bash
cd python && python3 run_screen.py > test_output.json && cd ..
cp python/test_output.json data/latest.json
```

## 4. Run it

```bash
npm run dev
# open http://localhost:3000
```

## 5. What you should see

- A masthead with the "ranks as of" date and a one-paragraph methodology line.
- A data-quality strip (universe scanned / passed screen / scored / shown) and
  an expandable **Methodology** panel.
- The **100-row table**: sortable columns (click a header), a search box, and a
  sector filter. Hovering any row updates the **detail panel** on the right
  (click a row to pin it). Top-10 rows carry a faint gold tint.
- A **fund section**: blended fundamentals, 3Y & 5Y metric cards, the growth-of-$1
  chart vs the benchmark, and a sector-allocation breakdown.

The detail panel updates on hover rather than using per-row tooltips — this is
deliberate, and avoids the flashing/overlap issues entirely.

## 6. Notes

- The page is `force-dynamic`, so it re-reads `data/latest.json` on every request
  — no rebuild needed after a daily refresh.
- All numbers are labelled **in-sample**: the fund's NAV/metrics apply today's
  holdings backward over the window. That's a characterisation of the current
  basket, not a live track record (the live tracker is still on the roadmap).
- Layout collapses to a single column under ~1000px; secondary columns hide
  under ~760px.
