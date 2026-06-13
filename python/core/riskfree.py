"""
Time-varying risk-free rate (roadmap item 6).

Source: the U.S. Treasury daily par yield curve ("3 Mo" column) from
home.treasury.gov — the PRIMARY source that FRED's DGS3MO republishes. FRED's
own no-key CSV endpoint was the original plan but its WAF 403s datacenter IPs
(including GitHub Actions runners) and timed out from the dev machine, which
would have stranded the cache; Treasury serves the identical series with no
key and no WAF (verified 2026-06-12).

RESILIENCE CHAIN (mirrors the quantum-arm pattern: an outage must never break
the pipeline):
  1. fetch per-year CSVs from Treasury (one small file per calendar year);
  2. on any failure, fall back to the last good series cached in
     data/riskfree_3mo.csv (committed, like latest.json);
  3. with no cache either, fall back to the constant settings.RISK_FREE_RATE
     with a logged warning.
A successful fetch rewrites the cache, so the committed copy tracks the last
run that could reach Treasury.

CONVENTIONS
  - The series holds ANNUAL yields as decimals (0.0378 = 3.78%), indexed by
    publication date (bond-market business days).
  - daily rf = annual yield / settings.TRADING_DAYS — simple division,
    matching how the rest of the codebase annualises. No geometric convention
    is introduced here.
  - Alignment to a trading-day index is forward-fill: each trading day uses
    the most recent published yield on or before it. This covers weekends,
    bond holidays that are equity trading days, and the seam where today's
    yield is not yet published (or the cache is a few days stale) — yields
    move slowly, so carrying the last print forward is a rounding error
    compared to a constant that can be ~70bp wrong.
"""
from __future__ import annotations

import logging
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

from config import settings

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "riskfree_3mo.csv"

_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/daily-treasury-rates.csv/{year}/all"
        "?type=daily_treasury_yield_curve&field_tdr_date_value={year}"
        "&page&_format=csv")
_HEADERS = {"User-Agent": "equitylens-research/2.3 (https://equitylens.xyz)"}
_TENOR_COLUMN = "3 Mo"

# Fetch enough calendar years to cover the longest metrics window (5Y) plus a
# buffer year for the left edge of the alignment ffill.
_LOOKBACK_YEARS = max(settings.FUND_WINDOWS_YEARS) + 1


def _fetch_from_treasury(today: date | None = None) -> pd.Series:
    """Download and stitch the per-year par-yield CSVs. Raises on any failure
    (network, schema change, empty result) — the caller owns the fallback."""
    today = today or date.today()
    frames = []
    for year in range(today.year - _LOOKBACK_YEARS, today.year + 1):
        resp = requests.get(_URL.format(year=year), headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        if "Date" not in df.columns or _TENOR_COLUMN not in df.columns:
            raise ValueError(f"Treasury CSV schema changed for {year}: {list(df.columns)[:6]}")
        frames.append(df[["Date", _TENOR_COLUMN]])
    merged = pd.concat(frames)
    merged["Date"] = pd.to_datetime(merged["Date"])
    series = (pd.to_numeric(merged.set_index("Date")[_TENOR_COLUMN], errors="coerce")
              .dropna().sort_index() / 100.0)
    series = series[~series.index.duplicated(keep="last")]
    if series.empty:
        raise ValueError("Treasury fetch produced an empty yield series")
    return series.rename("rfAnnual")


def _load_cache(path: Path) -> pd.Series | None:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        series = df.set_index("date")["rfAnnual"].dropna().sort_index()
        return series if not series.empty else None
    except Exception as e:  # noqa: BLE001 — a corrupt cache must not break the run
        logger.warning("riskfree: cache at %s unreadable (%s); ignoring it", path, e)
        return None


def _save_cache(series: pd.Series, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    series.rename("rfAnnual").rename_axis("date").reset_index().to_csv(path, index=False)


def get_rf_series(cache_path: Path | None = None) -> pd.Series:
    """Annual 3-month T-bill yields (decimal) by date, via the resilience
    chain. Always returns a non-empty Series: the terminal fallback is a
    single-point series at settings.RISK_FREE_RATE (ffill alignment then
    behaves exactly like the old constant)."""
    path = cache_path or CACHE_PATH
    try:
        series = _fetch_from_treasury()
        _save_cache(series, path)
        logger.info("riskfree: Treasury 3-Mo yields %s..%s (%d obs, last %.2f%%)",
                    series.index[0].date(), series.index[-1].date(),
                    len(series), series.iloc[-1] * 100)
        return series
    except Exception as e:  # noqa: BLE001 — never let a rates outage break the pipeline
        logger.warning("riskfree: Treasury fetch failed (%s); trying cache", e)
    cached = _load_cache(path)
    if cached is not None:
        logger.warning("riskfree: using cached series (last obs %s = %.2f%%); "
                       "alignment will ffill it forward",
                       cached.index[-1].date(), cached.iloc[-1] * 100)
        return cached
    logger.warning("riskfree: no cache either — falling back to constant %.2f%%. "
                   "Metrics this run use a flat rf.", settings.RISK_FREE_RATE * 100)
    return pd.Series([settings.RISK_FREE_RATE],
                     index=pd.DatetimeIndex([pd.Timestamp("1990-01-01")]),
                     name="rfAnnual")


def align_annual(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """ANNUAL yields aligned to a trading-day index (ffill; left-edge gaps —
    index days before the first observation — fill with the constant and a
    warning rather than silently dropping days)."""
    # Alpaca indices can be tz-aware; the Treasury series is naive dates.
    naive = index.tz_localize(None) if index.tz is not None else index
    aligned = series.reindex(naive.normalize(), method="ffill")
    aligned.index = index
    if aligned.isna().any():
        logger.warning("riskfree: %d trading days precede the yield series; "
                       "filling them with the constant %.2f%%",
                       int(aligned.isna().sum()), settings.RISK_FREE_RATE * 100)
        aligned = aligned.fillna(settings.RISK_FREE_RATE)
    return aligned


def daily_rf_map(series: pd.Series, dates: list[str]) -> dict[str, float]:
    """{ISO date: DAILY rf} for the forward log. Daily = annual /
    settings.TRADING_DAYS (the codebase-wide convention). research_log stays
    pandas-free; this map is its interface to the rates series."""
    if not dates:
        return {}
    idx = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in set(dates)))
    aligned = align_annual(series, idx) / settings.TRADING_DAYS
    return {d.strftime("%Y-%m-%d"): float(v) for d, v in aligned.items()}
