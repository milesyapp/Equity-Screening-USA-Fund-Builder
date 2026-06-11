"""
SEC EDGAR fundamentals for the screened names.

Fetches the company-facts JSON for every survivor of the liquidity/history
screen (~1,500-2,000 requests at <10/s with retry/back-off) and derives the
ratio set the scoring engine consumes. Everything degrades gracefully to None:
if a company doesn't report a line item (banks/REITs often omit "gross
profit"), or a filing is missing, or EDGAR is unreachable, that field is simply
None and the rest of the pipeline proceeds. Fundamentals NEVER block the run.

Source of truth: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

v2.1 — CORRECTNESS OVERHAUL of the extraction layer
---------------------------------------------------
The v2.0 extractor deduplicated annual facts by period END date only. SEC
company-facts returns MULTIPLE rows sharing one end date — the full fiscal
year, the Q4 stub (a 10-K's fourth quarter ends on the same day as the year),
and restated values from later filings. "Last row wins" therefore sometimes
kept a ~90-day figure as the "annual" number, deflating the revenue
denominator ~4x and producing impossible outputs (net margins of 400%+,
revenue "growth" of 1,000%+) for ~a quarter of the universe. Fixes:

  1. DURATION FILTER (flow concepts). Income-statement / cash-flow facts must
     span an annual period: 330 <= (end - start) <= 400 days. This admits
     calendar years (365/366d) and 52/53-week fiscal years (364/371d) while
     rejecting quarterly stubs and short transition periods. Balance-sheet
     facts are point-in-time ("instant=True") and carry no duration.

  2. RESTATEMENTS WIN. When several annual rows still share an end date, the
     one with the latest 'filed' date is kept — a restated figure supersedes
     the original, deterministically.

  3. BROADEST TOP LINE (banks / insurers / REITs). For financials,
     "RevenueFromContractWithCustomerExcludingAssessedTax" captures only fee
     income — a sliver of the true top line — which exploded net margins
     (e.g. a bank at 2,000%+). Revenue is now the per-year MAX across all
     candidate revenue concepts, including RevenuesNetOfInterestExpense,
     InterestAndDividendIncomeOperating and PremiumsEarnedNet. Taking the max
     of alternative *definitions of the same top line* is conservative for
     screening: it can only shrink margins toward (or below) their true value,
     never inflate them.

  4. PLAUSIBILITY GATES. Any margin > 100% is accounting-impossible for an
     annual consolidated period and is reported as None (logged) rather than
     poisoning the percentile ranks. Revenue growth > 1,000% is likewise
     nulled as a residual guard. Genuine one-off cases sacrificed by these
     gates are far rarer than the data errors they catch.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import requests

from config import settings

logger = logging.getLogger(__name__)

_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# ── Concept fallbacks (us-gaap taxonomy) ─────────────────────────────────────
# Revenue tagging varies enormously across filers, eras, and industries. The
# first four cover most industrials/tech; the last three are the financial-
# sector top lines (banks, brokers, insurers) whose absence caused the v2.0
# margin blow-ups. ALL are gathered and merged per-year (max) — see
# _annual_revenue_series.
_REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "RevenuesNetOfInterestExpense",          # banks / brokers (net top line)
    "InterestAndDividendIncomeOperating",    # banks (gross interest income)
    "PremiumsEarnedNet",                     # insurers
]
_NET_INCOME = ["NetIncomeLoss", "ProfitLoss"]
_GROSS_PROFIT = ["GrossProfit"]
_COST_OF_REVENUE = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]
_OPERATING_INCOME = ["OperatingIncomeLoss"]
_EQUITY = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
_CFO = ["NetCashProvidedByUsedInOperatingActivities"]
_CAPEX = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]
_EPS_DILUTED = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]
_DPS = ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"]
_LT_DEBT = ["LongTermDebtNoncurrent", "LongTermDebt"]

# Annual-period bounds in days: admits 52/53-week fiscal years (364/371) and
# calendar years (365/366); rejects quarters (~91) and transition stubs.
_ANNUAL_MIN_DAYS = 330
_ANNUAL_MAX_DAYS = 400

# Margins above this are accounting-impossible for a consolidated annual
# period and indicate a data fault upstream; report None instead.
_MARGIN_CAP = 1.005
# Residual guard on YoY revenue growth (1,000%+ is a data fault in practice).
_GROWTH_CAP = 10.0

# HTTP status codes that warrant a retry (transient server-side issues).
_RETRYABLE_STATUS = {429, 503, 500, 502, 504}


def _facts_for(cik: int) -> dict | None:
    """
    Fetch the company-facts JSON from SEC EDGAR for the given CIK.

    Retries up to 3 times with exponential back-off on retryable HTTP errors
    (429 rate-limit, 503 service unavailable). Non-retryable errors (e.g. 404
    for companies with no XBRL filings) return None immediately.
    """
    url = _FACTS_URL.format(cik=cik)
    headers = {
        "User-Agent": settings.SEC_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            if attempt == max_attempts - 1:
                logger.warning("EDGAR network error for CIK %s: %s", cik, exc)
                return None
            wait = 5 * (2 ** attempt)
            logger.warning(
                "EDGAR network error for CIK %s: %s — retrying in %ds",
                cik, exc, wait,
            )
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code in _RETRYABLE_STATUS:
            if attempt == max_attempts - 1:
                logger.warning(
                    "EDGAR HTTP %s for CIK %s after %d attempts — giving up.",
                    resp.status_code, cik, max_attempts,
                )
                return None
            wait = 5 * (2 ** attempt)
            logger.warning(
                "EDGAR HTTP %s for CIK %s — retrying in %ds",
                resp.status_code, cik, wait,
            )
            time.sleep(wait)
            continue

        # Non-retryable (e.g. 404 = no XBRL filings for this company).
        logger.warning("EDGAR %s -> HTTP %s (non-retryable)", cik, resp.status_code)
        return None

    return None


# ── Annual-series extraction (the v2.1 core fix) ─────────────────────────────

def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _is_annual_span(it: dict) -> bool:
    """True when the fact's start->end span is a plausible fiscal YEAR."""
    start = _parse_date(it.get("start"))
    end = _parse_date(it.get("end"))
    if start is None or end is None:
        return False
    return _ANNUAL_MIN_DAYS <= (end - start).days <= _ANNUAL_MAX_DAYS


def _annual_series(
    facts: dict,
    concepts: list,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
    instant: bool = False,
):
    """Return [(end_date, value), ...] sorted ascending, drawn from 10-K
    filings, for the first concept name that has usable data.

    instant=False (flow concepts — revenue, income, cash flow, per-share):
        only facts whose start->end span is a full fiscal YEAR are admitted
        (see _is_annual_span). This is what excludes the Q4 stubs that share
        the fiscal-year end date and previously corrupted the series.
    instant=True (stock concepts — equity, debt):
        balance-sheet facts are point-in-time and have no meaningful duration;
        no span filter is applied.

    When several admitted rows share one end date (original + restatements),
    the row with the LATEST 'filed' date wins, so restated figures
    deterministically supersede the originals.
    """
    node = facts.get("facts", {}).get(taxonomy, {})
    for concept in concepts:
        units = node.get(concept, {}).get("units", {})
        items = units.get(unit)
        if not items:
            continue
        rows = [
            it for it in items
            if it.get("form", "").startswith("10-K") and it.get("val") is not None
        ]
        if not instant:
            rows = [it for it in rows if _is_annual_span(it)]
        if not rows:
            continue
        best: dict = {}   # end -> (filed, val)
        for it in rows:
            end = it.get("end")
            if not end:
                continue
            filed = it.get("filed") or ""
            if end not in best or filed >= best[end][0]:
                best[end] = (filed, it["val"])
        if best:
            return sorted((end, fv[1]) for end, fv in best.items())
    return None


def _annual_revenue_series(facts: dict):
    """Merged annual revenue: for each fiscal-year end, the MAX across every
    revenue concept that reports it.

    Rationale: alternative revenue tags are alternative *definitions of the
    same top line* (e.g. fee income alone vs total revenues net of interest
    expense), never additive components — so the max is the broadest
    consolidated figure. For a bank, contract-with-customer fee income might
    be $2B while RevenuesNetOfInterestExpense is $25B; dividing net income by
    the former produced the 2,000% "margins" this rewrite removes. A larger
    denominator can only pull margins DOWN toward truth, which is the
    conservative direction for a quality screen.
    """
    merged: dict = {}
    node = facts.get("facts", {}).get("us-gaap", {})
    for concept in _REVENUE:
        units = node.get(concept, {}).get("units", {})
        items = units.get("USD")
        if not items:
            continue
        best: dict = {}
        for it in items:
            if not it.get("form", "").startswith("10-K"):
                continue
            if it.get("val") is None or not _is_annual_span(it):
                continue
            end = it.get("end")
            if not end:
                continue
            filed = it.get("filed") or ""
            if end not in best or filed >= best[end][0]:
                best[end] = (filed, it["val"])
        for end, (_, val) in best.items():
            if end not in merged or val > merged[end]:
                merged[end] = val
    if not merged:
        return None
    return sorted(merged.items())


def _latest(
    facts: dict,
    concepts: list,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
    instant: bool = False,
):
    series = _annual_series(facts, concepts, taxonomy, unit, instant=instant)
    return series[-1][1] if series else None


def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _gated_margin(numerator, revenue, label: str, ticker_hint: str = ""):
    """Margin with the accounting-plausibility gate. Negative margins are real
    (pre-profit companies) and pass through; > ~100% is a data fault."""
    m = _safe_div(numerator, revenue)
    if m is not None and m > _MARGIN_CAP:
        logger.debug("Gated implausible %s=%.2f %s (revenue mis-tagged?)",
                     label, m, ticker_hint)
        return None
    return m


def _shares_outstanding(facts: dict):
    # dei taxonomy, in 'shares' units; take most recent reported value.
    node = facts.get("facts", {}).get("dei", {})
    units = node.get("EntityCommonStockSharesOutstanding", {}).get("units", {})
    items = units.get("shares")
    if not items:
        return None
    dated = [
        (it.get("end", ""), it.get("val"))
        for it in items
        if it.get("val") is not None
    ]
    return max(dated)[1] if dated else None


def _metrics_from_facts(facts: dict, price: float | None) -> dict:
    rev_series = _annual_revenue_series(facts)
    revenue = rev_series[-1][1] if rev_series else None
    revenue_prev = rev_series[-2][1] if rev_series and len(rev_series) >= 2 else None
    # A non-positive consolidated annual revenue is a tagging fault, not a
    # business reality, at S&P-1500 scale — don't divide by it.
    if revenue is not None and revenue <= 0:
        revenue = None

    net_income = _latest(facts, _NET_INCOME)
    gross_profit = _latest(facts, _GROSS_PROFIT)
    operating_income = _latest(facts, _OPERATING_INCOME)
    equity = _latest(facts, _EQUITY, instant=True)
    cfo = _latest(facts, _CFO)
    capex = _latest(facts, _CAPEX)
    eps = _latest(facts, _EPS_DILUTED, unit="USD/shares")
    dps = _latest(facts, _DPS, unit="USD/shares")
    lt_debt = _latest(facts, _LT_DEBT, instant=True)
    shares = _shares_outstanding(facts)
    cost_of_rev = _latest(facts, _COST_OF_REVENUE)

    fcf = (cfo - capex) if (cfo is not None and capex is not None) else None

    # Gross profit: prefer the reported tag, else derive from revenue - COGS.
    if gross_profit is None and revenue is not None and cost_of_rev is not None:
        gross_profit = revenue - cost_of_rev

    # Equity-based ratios are NOT meaningful when book equity <= 0 (common for
    # heavy buyback names like MCK/STX/CAH). Report None rather than garbage.
    equity_ok = equity is not None and equity > 0
    roe = _safe_div(net_income, equity) if equity_ok else None
    dte = _safe_div(lt_debt, equity) if equity_ok else None

    # Market cap: prefer share count implied by EPS (internally consistent with
    # the P/E displayed); fall back to reported shares outstanding.
    implied_shares = (
        (net_income / eps)
        if (eps and eps > 0 and net_income and net_income > 0)
        else None
    )
    use_shares = implied_shares or shares
    market_cap = (price * use_shares) if (price is not None and use_shares) else None

    growth = (
        _safe_div(revenue - revenue_prev, revenue_prev)
        if (revenue is not None and revenue_prev and revenue_prev > 0)
        else None
    )
    if growth is not None and growth > _GROWTH_CAP:
        logger.debug("Gated implausible revenueGrowth=%.2f", growth)
        growth = None

    return {
        "peRatio": _safe_div(price, eps) if eps and eps > 0 else None,
        "dividendYield": _safe_div(dps, price),
        "grossMargin": _gated_margin(gross_profit, revenue, "grossMargin"),
        "operatingMargin": _gated_margin(operating_income, revenue, "operatingMargin"),
        "netMargin": _gated_margin(net_income, revenue, "netMargin"),
        "returnOnEquity": roe,
        "fcfMargin": _gated_margin(fcf, revenue, "fcfMargin"),
        "fcfYield": _safe_div(fcf, market_cap),
        "revenueGrowth": growth,
        "debtToEquity": dte,
        "marketCap": market_cap,
    }


_EMPTY = {
    "peRatio": None, "dividendYield": None, "grossMargin": None,
    "operatingMargin": None, "netMargin": None, "returnOnEquity": None,
    "fcfMargin": None, "fcfYield": None, "revenueGrowth": None,
    "debtToEquity": None, "marketCap": None,
}


def fetch_for(tickers: list, meta: dict, prices: dict) -> dict:
    """Return {ticker: {fundamental metrics}} for the given (held) tickers.

    `meta`   : {ticker: {... "cik": int|None}} from data_fetcher.get_universe()
    `prices` : {ticker: latest_close_price}
    Always returns a dict for every ticker (all-None if unavailable)."""
    out: dict = {}
    if not settings.FETCH_FUNDAMENTALS:
        logger.info("Fundamentals disabled (FETCH_FUNDAMENTALS=false).")
        return {t: dict(_EMPTY) for t in tickers}

    if "example.com" in (settings.SEC_USER_AGENT or ""):
        logger.warning(
            "SEC_USER_AGENT is unset/placeholder; SEC may rate-limit or 403. "
            'Set SEC_USER_AGENT="Your Project your@email" in python/.env.'
        )

    for t in tickers:
        cik = meta.get(t, {}).get("cik")
        if not cik:
            out[t] = dict(_EMPTY)
            continue
        try:
            facts = _facts_for(cik)
            out[t] = (
                _metrics_from_facts(facts, prices.get(t)) if facts else dict(_EMPTY)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Fundamentals fetch failed for %s (CIK %s): %s", t, cik, e
            )
            out[t] = dict(_EMPTY)
        time.sleep(0.15)  # be polite to SEC (<10 req/s)

    got = sum(1 for v in out.values() if v.get("netMargin") is not None)
    logger.info(
        "Fundamentals: usable data for %d / %d holdings", got, len(tickers)
    )
    return out


def portfolio_aggregates(stocks: list) -> dict:
    """Weight-weighted portfolio fundamentals, computed only over holdings that
    report each metric (so a couple of gaps don't void the aggregate)."""
    def wavg(field: str):
        num = 0.0
        wsum = 0.0
        for s in stocks:
            v = s.get(field)
            w = s.get("weight", 0.0)
            if v is not None:
                num += v * w
                wsum += w
        return (num / wsum) if wsum > 0 else None

    return {
        "weightedPe": wavg("peRatio"),
        "weightedDividendYield": wavg("dividendYield"),
        "weightedNetMargin": wavg("netMargin"),
        "weightedFcfYield": wavg("fcfYield"),
        "weightedRevenueGrowth": wavg("revenueGrowth"),
        "coverage": sum(1 for s in stocks if s.get("netMargin") is not None),
    }
