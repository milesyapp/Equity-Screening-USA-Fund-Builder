#!/usr/bin/env python3
"""
Entry point for the weekly run. Prints a single JSON object on the last line
(stdout) so the Next.js wrapper can parse it. All diagnostic logs go to stderr.

Improvements over v1.0:
  - Calls settings.validate() at startup so missing credentials surface
    immediately with a clear message.
  - Records wall-clock run time in the output JSON.
  - Includes error_type and a traceback summary in failure JSON for easier
    remote debugging without needing to ssh into the server.
  - Emits python_version so support can quickly rule out interpreter issues.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from datetime import datetime

# Logs to stderr so they don't pollute the JSON on stdout.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_weekly_report")


def main() -> int:
    t0 = time.monotonic()

    # Validate configuration before doing any network I/O so the user gets a
    # clear error message for credential problems.
    try:
        from config import settings  # noqa: PLC0415

        settings.validate()
    except RuntimeError as cfg_err:
        elapsed = round(time.monotonic() - t0, 2)
        logger.error("Configuration validation failed: %s", cfg_err)
        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(cfg_err),
                    "error_type": "ConfigurationError",
                    "date": datetime.now().isoformat(),
                    "elapsed_seconds": elapsed,
                    "python_version": sys.version,
                }
            )
        )
        return 1

    try:
        from core.multi_asset import MultiAssetPipeline  # noqa: PLC0415

        portfolio = MultiAssetPipeline().run()
        elapsed = round(time.monotonic() - t0, 2)
        output = {
            "success": True,
            "date": datetime.now().isoformat(),
            "elapsed_seconds": elapsed,
            "python_version": sys.version,
            "backend_version": settings.VERSION,
            "portfolio": portfolio,
            "market_conditions": portfolio.get("marketConditions"),
        }
        print(json.dumps(output, default=str))
        logger.info("Pipeline completed in %.1fs", elapsed)
        return 0

    except Exception as exc:  # noqa: BLE001
        elapsed = round(time.monotonic() - t0, 2)
        tb_lines = traceback.format_exc().splitlines()
        # Provide the last few lines of the traceback (most informative without
        # flooding the JSON); the full trace is already on stderr via logger.
        tb_summary = [ln for ln in tb_lines[-6:] if ln.strip()]
        logger.exception("Pipeline failed after %.1fs", elapsed)
        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "traceback_summary": tb_summary,
                    "date": datetime.now().isoformat(),
                    "elapsed_seconds": elapsed,
                    "python_version": sys.version,
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
