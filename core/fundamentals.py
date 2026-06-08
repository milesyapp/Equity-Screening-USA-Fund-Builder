"""
SEC EDGAR fundamentals for the held names.

We fetch fundamentals ONLY for the final portfolio holdings (8-12 names), so
this is ~12 requests to SEC's free company-facts API -- well within their
10 req/s guidance. Everything degrades gracefully to None: if a company doesn't
report a line item (banks/REITs often omit "gross profit"), or a filing is
missing, or EDGAR is unreachable, that field is simply None and the rest of the
pipeline proceeds. Fundamentals NEVER block portfolio generation.

All figures are drawn from the most recent annual report (10-K) unless noted.
SEC requires a descriptive User-Agent with contact info (settings.SEC_USER_AGENT).

Source of truth: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

Improvements over v1.0:
  - _facts_for now retries up to 3 times with exponential back-off on HTTP
    429 (rate limit) and 503 (service unavailable) — both common on EDGAR.
    A single rate-limit hit no longer silently drops fundamentals for all
    subsequent tickers in the same run.
"""
from __future__ import annotations

import time
import logging

import requests

from config import settings

logger = logging.getLogger(__name__)

_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Concept fallbacks, tried in order (us-gaap taxonomy). Revenue tagging varies
# significantly across filers and eras.
_REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
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


def _annual_series(
    facts: dict,
    concepts: list,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
):
    """Return [(end_date, value), ...] sorted ascending, from annual (FY 10-K)
    filings, for the first concept name that has data. De-duplicates by period
    end, keeping the most recently filed value for each."""
    node = facts.get("facts", {}).get(taxonomy, {})
    for concept in concepts:
        units = node.get(concept, {}).get("units", {})
        items = units.get(unit)
        if not items:
            continue
        annual = [
            it for it in items
            if it.get("form", "").startswith("10-K")
            and it.get("fp") == "FY"
            and it.get("val") is not None
        ]
        if not annual:
            annual = [
                it for it in items
                if it.get("form", "").startswith("10-K") and it.get("val") is not None
            ]
        if not annual:
            continue
        by_end: dict = {}
        for it in annual:
            end = it.get("end")
            if end:
                by_end[end] = it["val"]  # later iterations overwrite -> last filed wins
        if by_end:
            return sorted(by_end.items())
    return None


def _latest(
    facts: dict,
    concepts: list,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
):
    series = _annual_series(facts, concepts, taxonomy, unit)
    return series[-1][1] if series else None


def _safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


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
    rev_series = _annual_series(facts, _REVENUE)
    revenue = rev_series[-1][1] if rev_series else None
    revenue_prev = rev_series[-2][1] if rev_series and len(rev_series) >= 2 else None

    net_income = _latest(facts, _NET_INCOME)
    gross_profit = _latest(facts, _GROSS_PROFIT)
    operating_income = _latest(facts, _OPERATING_INCOME)
    equity = _latest(facts, _EQUITY)
    cfo = _latest(facts, _CFO)
    capex = _latest(facts, _CAPEX)
    eps = _latest(facts, _EPS_DILUTED, unit="USD/shares")
    dps = _latest(facts, _DPS, unit="USD/shares")
    lt_debt = _latest(facts, _LT_DEBT)
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

    return {
        "peRatio": _safe_div(price, eps) if eps and eps > 0 else None,
        "dividendYield": _safe_div(dps, price),
        "grossMargin": _safe_div(gross_profit, revenue),
        "operatingMargin": _safe_div(operating_income, revenue),
        "netMargin": _safe_div(net_income, revenue),
        "returnOnEquity": roe,
        "fcfMargin": _safe_div(fcf, revenue),
        "fcfYield": _safe_div(fcf, market_cap),
        "revenueGrowth": (
            _safe_div(revenue - revenue_prev, revenue_prev)
            if (revenue is not None and revenue_prev)
            else None
        ),
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
