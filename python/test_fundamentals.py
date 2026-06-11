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
  6. End-to-end: a realistic facts payload yields sane ratios.

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


def test_growth_gate_and_normal_growth():
    facts = _facts({
        "Revenues": [
            _fact("2023-01-01", "2023-12-31", 100_000),
            _fact("2024-01-01", "2024-12-31", 1),        # corrupt prior year
            _fact("2025-01-01", "2025-12-31", 120_000),
        ],
    })
    m = F._metrics_from_facts(facts, price=None)
    assert m["revenueGrowth"] is None, "12,000,000% growth must be gated"
    facts2 = _facts({
        "Revenues": [
            _fact("2024-01-01", "2024-12-31", 100_000),
            _fact("2025-01-01", "2025-12-31", 118_000),
        ],
    })
    m2 = F._metrics_from_facts(facts2, price=None)
    assert abs(m2["revenueGrowth"] - 0.18) < 1e-9
    print("  PASS: absurd growth gated; normal 18% YoY growth computes exactly")


def test_end_to_end_sane_company():
    facts = _facts({
        "Revenues":          [_fact("2024-01-01", "2024-12-31", 90_000_000_000),
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
    assert abs(m["fcfMargin"] - 0.22) < 1e-9
    assert abs(m["revenueGrowth"] - (1 / 9)) < 1e-9
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
    test_growth_gate_and_normal_growth()
    test_end_to_end_sane_company()
    print("ALL PASS")
