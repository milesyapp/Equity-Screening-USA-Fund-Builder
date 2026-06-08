#!/usr/bin/env python3
"""
Weekly screen — the full pipeline.

Scans the broad US universe, scores every eligible name, ranks the top N, and
builds the score-weighted fund. Writes the PipelineOutput JSON the Next.js
frontend reads (wrap below matches lib/types/index.ts).

Usage:
    cd python && python3 run_screen.py > test_output.json
    cp test_output.json ../data/latest.json

This is the WEEKLY job: it re-selects and re-ranks holdings. Between weekly
runs, run_daily.py refreshes only the prices/returns of the frozen selection.
"""
from __future__ import annotations

import json
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("run_screen")


def main() -> int:
    from config import settings
    try:
        settings.validate()
    except RuntimeError as e:
        logger.error("%s", e)
        print(json.dumps({"success": False, "error": str(e)}))
        return 1

    from core import screener

    t0 = time.time()
    try:
        result = screener.run()
    except Exception as e:  # noqa: BLE001
        logger.exception("Screen failed")
        print(json.dumps({"success": False, "error": str(e)}))
        return 1

    elapsed = round(time.time() - t0, 1)
    out = {
        "success": True,
        "date": result["asOf"],
        "elapsed_seconds": elapsed,
        "backend_version": settings.VERSION,
        "run_type": "weekly",
        "portfolio": result,
    }
    print(json.dumps(out, default=str))
    logger.info("Screen completed in %.1fs — %d ranked, %d scored of %d universe",
                elapsed, len(result["stocks"]), result["scoredCount"], result["universeSize"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
