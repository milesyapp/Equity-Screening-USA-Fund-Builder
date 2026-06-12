#!/usr/bin/env python3
"""
Offline self-test for core/fundamentals.py extraction logic — no network.

Reproduces the exact failure modes found in production data (margins of
400-2,000%, revenue "growth" of 1,000%+) with synthetic SEC company-facts
payloads, and asserts the v2.1 extractor resolves each one:

  1. Q4-stub rejection: a ~91-day row sharing the fiscal-year end date must
     never win over the true ~365-day annual row.
  2. Restatements win: among annual rows sharing an end date, latest 'filed'.
  3. Bank top line: revenue = max across concepts, so fee-income-only
     contract revenue cannot serve as the denominator.
  4. Instant concepts (equity/debt) are exempt from the duration filter.
  5. Plausibility gates: impossible margins / growth report None, not poison.
  6. Growth = 3-yr elapsed-time CAGR (v2.2): exact exponent over the actual
     elapsed days, gap-year series anchor to the point nearest 3 years back,
     3 points degrade to a ~2-yr CAGR, 2 points -> None (no YoY fallback).
  7. FCF = matched-period 3-yr average (v2.2): exact margin/yield ratios from
     per-year CFO-capex pairs, and the capex TAG-SWITCH regression — merged
     capex must align FCF on the most recent fiscal years, never pair current
     CFO with a stale tag's last reported year (the NVDA FY2012 bug).
  8. End-to-end: a realistic facts payload yields sane ratios.

Run:  cd python && python3 test_fundamentals.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import fundamentals as F  # noqa: E402


def _fact(start, end, val, filed="2026-02-15", form="10-K", fp="FY"):
    d = {"end": end, "val": val, "filed": filed, "form": form, "fp": fp}
    if start is not None:
        d["start"] = start
    return d


def _facts(usgaap: dict, dei_shares=1_000_000_000):
    gaap = {}
    for k, v in usgaap.items():
        if k.endswith("/shares"):
            gaap[k[: -len("/shares")]] = {"units": {"USD/shares": v}}
        else:
            gaap[k] = {"units": {"USD": v}}
    return {
        "facts": {
            "us-gaap": gaap,
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {"shares": [
                        {"end": "2025-12-31", "val": dei_shares}
                    ]}
                }
            },
        }
    }


def test_q4_stub_rejected():
    """The NVDA-class bug: Q4 (~91d) and FY (~365d) share end; FY must win."""
    facts = _facts({
        "Revenues": [
            _fact("2025-01-01", "2025-12-31", 130_000_000_000),  # true FY
            _fact("2025-10-01", "2025-12-31", 33_000_000_000,    # Q4 stub
                  filed="2026-02-20"),                            # filed later!
        ],
    })
    series = F._annual_series(facts, ["Revenues"])
    assert series == [("2025-12-31", 130_000_000_000)], series
    print("  PASS: Q4 stub sharing the FY end date is rejected (duration filter)")


def test_restatement_wins():
    facts = _facts({
        "Revenues": [
            _fact("2025-01-01", "2025-12-31", 100, filed="2026-02-01"),
            _fact("2025-01-01", "2025-12-31", 105, filed="2026-06-01"),  # restated
        ],
    })
    series = F._annual_series(facts, ["Revenues"])
    assert series == [("2025-12-31", 105)], series
    print("  PASS: restated annual value (latest 'filed') supersedes the original")


def test_53_week_fiscal_year_accepted():
    # 371-day retail fiscal year must pass the annual filter.
    facts = _facts({"Revenues": [_fact("2025-01-29", "2026-02-03", 50_000)]})
    series = F._annual_series(facts, ["Revenues"])
    assert series and series[-1][1] == 50_000
    print("  PASS: 53-week fiscal year (371 days) accepted as annual")


def test_bank_revenue_uses_broadest_top_line():
    """The RF-class bug: fee income alone made netMargin ~2,000%."""
    facts = _facts({
        "RevenueFromContractWithCustomerExcludingAssessedTax": [
            _fact("2025-01-01", "2025-12-31", 1_300_000_000),    # fee income only
        ],
        "RevenuesNetOfInterestExpense": [
            _fact("2025-01-01", "2025-12-31", 26_000_000_000),   # true top line
        ],
        "NetIncomeLoss": [
            _fact("2025-01-01", "2025-12-31", 2_000_000_000),
        ],
    })
    rev = F._annual_revenue_series(facts)
    assert rev[-1][1] == 26_000_000_000, rev
    m = F._metrics_from_facts(facts, price=20.0)
    assert m["netMargin"] is not None and m["netMargin"] < 0.10, m["netMargin"]
    print(f"  PASS: bank revenue = broadest concept; netMargin {m['netMargin']:.3f} (was ~1.54x)")


def test_instant_concepts_exempt_from_duration():
    facts = _facts({
        "StockholdersEquity": [
            {"end": "2025-12-31", "val": 40_000_000_000,
             "filed": "2026-02-15", "form": "10-K", "fp": "FY"},  # no 'start'
        ],
        "NetIncomeLoss": [_fact("2025-01-01", "2025-12-31", 8_000_000_000)],
    })
    eq = F._latest(facts, F._EQUITY, instant=True)
    assert eq == 40_000_000_000
    m = F._metrics_from_facts(facts, price=None)
    assert abs(m["returnOnEquity"] - 0.2) < 1e-9
    print("  PASS: balance-sheet (instant) facts bypass the duration filter; ROE computes")


def test_plausibility_gates():
    # Construct an extractor-evading fault: gross profit 5x revenue.
    facts = _facts({
        "Revenues":     [_fact("2025-01-01", "2025-12-31", 1_000)],
        "GrossProfit":  [_fact("2025-01-01", "2025-12-31", 5_000)],
        "NetIncomeLoss": [_fact("2025-01-01", "2025-12-31", -200)],
    })
    m = F._metrics_from_facts(facts, price=None)
    assert m["grossMargin"] is None, "impossible >100% margin must be gated to None"
    assert m["netMargin"] == -0.2, "real negative margins must pass through"
    print("  PASS: >100% margin gated to None; genuine negative margin preserved")


def test_growth_cagr_and_gate():
    # Normal case: 4 calendar years -> the anchor is exactly 3 years back and
    # the exponent is the ACTUAL elapsed time (1096 days here), never 3.0.
    facts = _facts({
        "Revenues": [
            _fact("2022-01-01", "2022-12-31", 100_000),
            _fact("2023-01-01", "2023-12-31", 105_000),
            _fact("2024-01-01", "2024-12-31", 110_000),
            _fact("2025-01-01", "2025-12-31", 118_000),
        ],
    })
    m = F._metrics_from_facts(facts, price=None)
    expected = (118_000 / 100_000) ** (365.25 / 1096) - 1.0
    assert abs(m["revenueGrowth"] - expected) < 1e-12, m["revenueGrowth"]

    # Gate: a corrupt value AT the CAGR anchor produces an absurd annualised
    # rate and must be nulled.
    facts2 = _facts({
        "Revenues": [
            _fact("2023-01-01", "2023-12-31", 1),        # corrupt anchor year
            _fact("2024-01-01", "2024-12-31", 100_000),
            _fact("2025-01-01", "2025-12-31", 120_000),
        ],
    })
    m2 = F._metrics_from_facts(facts2, price=None)
    assert m2["revenueGrowth"] is None, "absurd annualised CAGR must be gated"

    # Robustness bonus of the design: a corrupt value in the MIDDLE of the
    # series (not an endpoint) no longer touches the growth figure at all.
    facts3 = _facts({
        "Revenues": [
            _fact("2022-01-01", "2022-12-31", 100_000),
            _fact("2023-01-01", "2023-12-31", 1),        # corrupt mid-series
            _fact("2024-01-01", "2024-12-31", 110_000),
            _fact("2025-01-01", "2025-12-31", 118_000),
        ],
    })
    m3 = F._metrics_from_facts(facts3, price=None)
    assert abs(m3["revenueGrowth"] - expected) < 1e-12
    print("  PASS: 3-yr elapsed-time CAGR exact; corrupt anchor gated; mid-series spike ignored")


def test_growth_gap_year_exponent():
    """A series with a hole (duration filter dropped transition years): the
    anchor is the point CLOSEST to 3 years back — here 4 years back — and the
    exponent must be the elapsed 4.0 years, not an assumed 3."""
    facts = _facts({
        "Revenues": [
            _fact("2020-01-01", "2020-12-31", 100_000),
            _fact("2021-01-01", "2021-12-31", 100_000),   # anchor (4y span)
            _fact("2025-01-01", "2025-12-31", 146_410),   # 1.1^4 * 100_000
        ],
    })
    m = F._metrics_from_facts(facts, price=None)
    # 2021-12-31 -> 2025-12-31 is 1461 days = exactly 4.0 * 365.25.
    assert abs(m["revenueGrowth"] - 0.10) < 1e-9, m["revenueGrowth"]
    print("  PASS: gap-year series annualises over elapsed 4.0 years -> exact 10%/yr")


def test_growth_three_points_degrades_two_points_none():
    # Exactly 3 annual points: nearest earlier point is ~2 years back, so the
    # statistic degrades to a ~2-yr CAGR (same statistic, less smoothing).
    facts = _facts({
        "Revenues": [
            _fact("2023-01-01", "2023-12-31", 100_000),
            _fact("2024-01-01", "2024-12-31", 50_000),    # spike year, ignored
            _fact("2025-01-01", "2025-12-31", 121_000),
        ],
    })
    m = F._metrics_from_facts(facts, price=None)
    expected = (121_000 / 100_000) ** (365.25 / 731) - 1.0
    assert abs(m["revenueGrowth"] - expected) < 1e-12, m["revenueGrowth"]

    # 2 points: None. Deliberately NO single-year YoY fallback — mixing
    # horizons in one percentile column reintroduces spike noise for exactly
    # the fragile names; coverage shrinkage imputes the median instead.
    facts2 = _facts({
        "Revenues": [
            _fact("2024-01-01", "2024-12-31", 100_000),
            _fact("2025-01-01", "2025-12-31", 118_000),
        ],
    })
    m2 = F._metrics_from_facts(facts2, price=None)
    assert m2["revenueGrowth"] is None, "2 points must NOT fall back to YoY"
    print("  PASS: 3 points -> ~2-yr CAGR; 2 points -> None (no YoY fallback)")


def test_matched_period_fcf_averaging():
    """FCF averaged over the 3 most recent years with BOTH CFO and capex;
    margin = avg FCF / avg revenue over the SAME years; yield = avg FCF /
    current market cap. All ratios exact."""
    facts = _facts({
        "Revenues": [
            _fact("2023-01-01", "2023-12-31", 100_000),
            _fact("2024-01-01", "2024-12-31", 90_000),
            _fact("2025-01-01", "2025-12-31", 110_000),
        ],
        "NetCashProvidedByUsedInOperatingActivities": [
            _fact("2023-01-01", "2023-12-31", 30_000),
            _fact("2024-01-01", "2024-12-31", 26_000),
            _fact("2025-01-01", "2025-12-31", 34_000),
        ],
        "PaymentsToAcquirePropertyPlantAndEquipment": [
            _fact("2023-01-01", "2023-12-31", 8_000),
            _fact("2024-01-01", "2024-12-31", 6_000),
            _fact("2025-01-01", "2025-12-31", 10_000),
        ],
        "NetIncomeLoss": [_fact("2025-01-01", "2025-12-31", 20_000)],
        "EarningsPerShareDiluted/shares": [_fact("2025-01-01", "2025-12-31", 4.0)],
    })
    m = F._metrics_from_facts(facts, price=120.0)
    # Per-year FCF: 22_000 / 20_000 / 24_000 -> avg 22_000.
    # Avg revenue over the same years: 100_000 -> margin exactly 0.22.
    assert abs(m["fcfMargin"] - 0.22) < 1e-12, m["fcfMargin"]
    # Market cap = 120 * (20_000 / 4.0) = 600_000 -> yield = 22_000/600_000.
    assert abs(m["fcfYield"] - 22_000 / 600_000) < 1e-12, m["fcfYield"]
    print("  PASS: matched-period 3-yr FCF -> margin 22.0% and yield 11/300 exact")


def test_capex_tag_switch_uses_recent_years():
    """The NVDA-class capex bug: a filer that stopped using the PP&E tag years
    ago must NOT have current CFO paired with the stale tag's last value.
    Merged capex aligns FCF on the most recent fiscal years."""
    facts = _facts({
        "Revenues": [
            _fact("2023-01-01", "2023-12-31", 100_000),
            _fact("2024-01-01", "2024-12-31", 90_000),
            _fact("2025-01-01", "2025-12-31", 110_000),
        ],
        "NetCashProvidedByUsedInOperatingActivities": [
            _fact("2011-01-01", "2011-12-31", 1_000_000),  # poison if matched
            _fact("2023-01-01", "2023-12-31", 30_000),
            _fact("2024-01-01", "2024-12-31", 26_000),
            _fact("2025-01-01", "2025-12-31", 34_000),
        ],
        # Old tag: last real value in 2011 (the stale-pairing trap), plus a
        # smaller duplicate of 2025 to prove the per-year MAX merge.
        "PaymentsToAcquirePropertyPlantAndEquipment": [
            _fact("2011-01-01", "2011-12-31", 500),
            _fact("2025-01-01", "2025-12-31", 1_000),
        ],
        # New tag: the actual recent capex.
        "PaymentsToAcquireProductiveAssets": [
            _fact("2023-01-01", "2023-12-31", 8_000),
            _fact("2024-01-01", "2024-12-31", 6_000),
            _fact("2025-01-01", "2025-12-31", 10_000),
        ],
        "NetIncomeLoss": [_fact("2025-01-01", "2025-12-31", 20_000)],
        "EarningsPerShareDiluted/shares": [_fact("2025-01-01", "2025-12-31", 4.0)],
    })
    m = F._metrics_from_facts(facts, price=120.0)
    # Matched years = 3 most recent of {2011, 2023, 2024, 2025} = 2023-25;
    # 2025 capex = max(1_000, 10_000) = 10_000. Same exact ratios as above —
    # the 2011 poison year and the stale tag must change nothing.
    assert abs(m["fcfMargin"] - 0.22) < 1e-12, m["fcfMargin"]
    assert abs(m["fcfYield"] - 22_000 / 600_000) < 1e-12, m["fcfYield"]
    print("  PASS: capex tag switch -> FCF aligned on recent years (stale FY2011 ignored)")


def test_end_to_end_sane_company():
    facts = _facts({
        "Revenues":          [_fact("2022-01-01", "2022-12-31", 75_000_000_000),
                              _fact("2023-01-01", "2023-12-31", 80_000_000_000),
                              _fact("2024-01-01", "2024-12-31", 90_000_000_000),
                              _fact("2025-01-01", "2025-12-31", 100_000_000_000),
                              _fact("2025-10-01", "2025-12-31", 26_000_000_000)],
        "NetIncomeLoss":     [_fact("2025-01-01", "2025-12-31", 20_000_000_000)],
        "OperatingIncomeLoss": [_fact("2025-01-01", "2025-12-31", 28_000_000_000)],
        "GrossProfit":       [_fact("2025-01-01", "2025-12-31", 55_000_000_000)],
        "NetCashProvidedByUsedInOperatingActivities":
                             [_fact("2025-01-01", "2025-12-31", 30_000_000_000)],
        "PaymentsToAcquirePropertyPlantAndEquipment":
                             [_fact("2025-01-01", "2025-12-31", 8_000_000_000)],
        "StockholdersEquity": [{"end": "2025-12-31", "val": 80_000_000_000,
                                "filed": "2026-02-15", "form": "10-K", "fp": "FY"}],
        "EarningsPerShareDiluted/shares":
                             [_fact("2025-01-01", "2025-12-31", 4.0)],
    })
    m = F._metrics_from_facts(facts, price=120.0)
    assert abs(m["netMargin"] - 0.20) < 1e-9, m["netMargin"]
    assert abs(m["operatingMargin"] - 0.28) < 1e-9
    assert abs(m["grossMargin"] - 0.55) < 1e-9
    # FCF reported for 2025 only -> single matched year (less smoothing, same
    # statistic): (30B - 8B) / 100B.
    assert abs(m["fcfMargin"] - 0.22) < 1e-9
    # 3-yr elapsed-time CAGR anchored on FY2022 (1096 days back).
    assert abs(m["revenueGrowth"] - ((100 / 75) ** (365.25 / 1096) - 1.0)) < 1e-12
    assert abs(m["peRatio"] - 30.0) < 1e-9
    assert abs(m["returnOnEquity"] - 0.25) < 1e-9
    assert m["marketCap"] == 120.0 * (20_000_000_000 / 4.0)
    print("  PASS: end-to-end realistic payload -> every ratio exact and sane")


if __name__ == "__main__":
    print("test_fundamentals.py")
    test_q4_stub_rejected()
    test_restatement_wins()
    test_53_week_fiscal_year_accepted()
    test_bank_revenue_uses_broadest_top_line()
    test_instant_concepts_exempt_from_duration()
    test_plausibility_gates()
    test_growth_cagr_and_gate()
    test_growth_gap_year_exponent()
    test_growth_three_points_degrades_two_points_none()
    test_matched_period_fcf_averaging()
    test_capex_tag_switch_uses_recent_years()
    test_end_to_end_sane_company()
    print("ALL PASS")
