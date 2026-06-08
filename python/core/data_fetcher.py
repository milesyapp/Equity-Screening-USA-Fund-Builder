"""
Data acquisition layer (Alpaca for prices, Wikipedia for universe + sector).

  * Universe + GICS sector: scraped from the S&P 500/400/600 Wikipedia tables.
  * Prices/volume: Alpaca Market Data API -- a real, keyed API, far more reliable
    than scraping Yahoo. Split/dividend-adjusted daily bars, fetched in chunks.

Fundamentals (margins / FCF / market cap) are intentionally NOT fetched here;
they come from SEC EDGAR via fundamentals.py.

Improvements over v1.0:
  - Added _with_retry decorator: both Wikipedia scraping and Alpaca API calls
    now retry up to 3 times with exponential back-off before failing. A single
    transient network error no longer kills the entire weekly run.
  - Fixed a latent bug in _fetch_symbols where the volumes list could be empty
    while closes is non-empty (e.g. all volume data returned None for a chunk),
    causing pd.concat(volumes) to raise. Now handled gracefully.
"""
from __future__ import annotations

import time
import logging
from functools import wraps
from io import StringIO
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import Adjustment, DataFeed

from config import settings

logger = logging.getLogger(__name__)

_WIKI = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}

# Wikipedia 403s bare urllib requests; send a real browser User-Agent.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


# ── Retry helper ─────────────────────────────────────────────────────────────

# Substrings that mark a PERMANENT (non-transient) Alpaca error. Retrying these
# is pointless and slow — e.g. a symbol Alpaca doesn't carry. When seen, we
# re-raise immediately so _fetch_symbols can isolate and drop the bad name fast,
# instead of burning the full back-off budget on every recursion level.
_PERMANENT_MARKERS = (
    "invalid symbol",
    "not found",
    "subscription does not permit",
    "forbidden",
)


def _is_permanent(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _PERMANENT_MARKERS)


def _with_retry(max_attempts: int = 3, backoff: float = 2.0):
    """
    Decorator: retry the decorated function up to max_attempts times with
    exponential back-off (backoff^attempt seconds between retries).

    Retries on transient exceptions only. A permanent error (see
    _PERMANENT_MARKERS, e.g. "invalid symbol") is re-raised immediately without
    retrying — this keeps one unsupported ticker from stalling the whole run.
    The final attempt re-raises so callers can still handle the failure.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    if _is_permanent(exc) or attempt == max_attempts - 1:
                        raise
                    wait = backoff ** attempt
                    logger.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.0fs",
                        fn.__name__, attempt + 1, max_attempts, exc, wait,
                    )
                    time.sleep(wait)
        return wrapper
    return decorator


# ── Universe ─────────────────────────────────────────────────────────────────

def _clean_ticker(t: str) -> str:
    # Alpaca and the S&P/Wikipedia constituent tables BOTH use the dot form for
    # share classes (e.g. BRK.B, BF.B). yfinance uses a hyphen (BRK-B), but
    # Alpaca's data API REJECTS the hyphen form with "invalid symbol: BRK-B",
    # so we keep the dot. (The market-gauge fetches in market_analyzer use
    # indices like ^VIX, never individual class shares, so there's no conflict.)
    return str(t).strip().upper()


@_with_retry(max_attempts=3, backoff=3.0)
def _read_wiki_tables(url: str) -> list:
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return pd.read_html(StringIO(resp.text))


def get_universe() -> dict:
    """Return {ticker: {"name", "sector", "subIndustry"}} for the broad US
    universe (S&P 500/400/600), scraped from the Wikipedia constituent tables."""
    frames = ["sp500"]
    if settings.USE_MIDCAP:
        frames.append("sp400")
    if settings.USE_SMALLCAP:
        frames.append("sp600")

    meta: dict = {}
    for key in frames:
        try:
            tables = _read_wiki_tables(_WIKI[key])
            df = next(t for t in tables if "Symbol" in t.columns)
            sector_col = next((c for c in df.columns if "Sector" in str(c)), None)
            name_col = next(
                (c for c in df.columns if "Security" in str(c) or "Company" in str(c)),
                None,
            )
            sub_col = next(
                (
                    c for c in df.columns
                    if "Sub-Industry" in str(c) or "Sub-industry" in str(c)
                ),
                None,
            )
            cik_col = next(
                (c for c in df.columns if str(c).strip().upper() == "CIK"), None
            )
            for _, row in df.iterrows():
                tk = _clean_ticker(row["Symbol"])
                cik = None
                if cik_col is not None and not pd.isna(row[cik_col]):
                    try:
                        cik = int(row[cik_col])
                    except (ValueError, TypeError):
                        cik = None
                meta[tk] = {
                    "name": str(row[name_col]).strip() if name_col else tk,
                    "sector": str(row[sector_col]) if sector_col else "Unknown",
                    "subIndustry": str(row[sub_col]).strip() if sub_col else "",
                    "cik": cik,
                }
            logger.info("Loaded %d tickers from %s", len(df), key)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load %s universe: %s", key, e)

    logger.info("Total universe: %d unique tickers", len(meta))
    return meta


# ── Price data ────────────────────────────────────────────────────────────────

def _alpaca_client() -> StockHistoricalDataClient:
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        raise RuntimeError(
            "Missing Alpaca credentials. Add ALPACA_API_KEY and ALPACA_SECRET_KEY "
            "to python/.env"
        )
    return StockHistoricalDataClient(settings.ALPACA_API_KEY, settings.ALPACA_SECRET_KEY)


@_with_retry(max_attempts=3, backoff=5.0)
def _fetch_bars(client, symbols, start, end, feed):
    """Fetch bars for a symbol list with retry; raises on failure."""
    req = StockBarsRequest(
        symbol_or_symbols=list(symbols),
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        adjustment=Adjustment.ALL,
        feed=feed,
    )
    df = client.get_stock_bars(req).df
    if df is None or df.empty:
        return None, None
    return df["close"].unstack(level=0), df["volume"].unstack(level=0)


def _fetch_symbols(client, symbols, start, end, feed):
    """Fetch bars for symbols; on failure split in half and recurse, so a single
    bad ticker (e.g. an unsupported symbol format) only drops itself, not the batch.

    Bug fix v1.1: volumes list is now guarded so an empty volumes list (all
    chunks returned None for volume) does not crash pd.concat."""
    if not symbols:
        return None, None
    try:
        return _fetch_bars(client, symbols, start, end, feed)
    except Exception as e:  # noqa: BLE001
        if len(symbols) == 1:
            logger.warning("Dropping symbol %s: %s", symbols[0], e)
            return None, None
        mid = len(symbols) // 2
        c1, v1 = _fetch_symbols(client, symbols[:mid], start, end, feed)
        c2, v2 = _fetch_symbols(client, symbols[mid:], start, end, feed)
        cs = [c for c in (c1, c2) if c is not None]
        vs = [v for v in (v1, v2) if v is not None]
        if not cs:
            return None, None
        c_merged = pd.concat(cs, axis=1)
        # Guard: if no volume data at all, return an empty DataFrame rather
        # than crashing pd.concat on an empty list.
        v_merged = (
            pd.concat(vs, axis=1)
            if vs
            else pd.DataFrame(index=c_merged.index, columns=c_merged.columns, dtype=float)
        )
        return c_merged, v_merged


def download_price_data(
    tickers: list,
    lookback_years: int | None = None,
    chunk_size: int = 200,
):
    """Download split/dividend-adjusted daily bars from Alpaca, in chunks."""
    lookback_years = lookback_years or settings.LOOKBACK_YEARS
    start = datetime.now() - timedelta(days=365 * lookback_years)
    end = datetime.now() - timedelta(days=1)  # yesterday: all bars fully settled

    client = _alpaca_client()
    feed = DataFeed(settings.ALPACA_FEED)
    n_chunks = (len(tickers) + chunk_size - 1) // chunk_size
    logger.info(
        "Downloading %d tickers from Alpaca (feed=%s) in %d chunks...",
        len(tickers), feed.value, n_chunks,
    )

    closes, volumes = [], []
    for ci in range(n_chunks):
        chunk = tickers[ci * chunk_size : (ci + 1) * chunk_size]
        c, v = _fetch_symbols(client, chunk, start, end, feed)
        if c is not None:
            closes.append(c)
            if v is not None:
                volumes.append(v)
        logger.info("  ...chunk %d/%d done", ci + 1, n_chunks)

    if not closes:
        raise RuntimeError(
            "Alpaca returned no price data. Check your API keys in python/.env "
            "and that ALPACA_FEED is valid ('iex' on the free plan)."
        )

    close = pd.concat(closes, axis=1)
    # Guard: synthesize an empty volume DataFrame if all chunks returned None.
    volume = (
        pd.concat(volumes, axis=1)
        if volumes
        else pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    )
    if getattr(close.index, "tz", None) is not None:
        close.index = close.index.tz_convert(None)
        volume.index = volume.index.tz_convert(None)
    close = close.sort_index().dropna(axis=1, how="all")
    volume = volume.reindex(columns=close.columns).reindex(index=close.index)
    logger.info("Got usable price history for %d tickers", close.shape[1])
    return close, volume
