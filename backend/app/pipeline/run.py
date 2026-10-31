"""CLI entry point for the data pipeline.

Usage (from ``backend/``)::

    python -m app.pipeline.run --generate
    python -m app.pipeline.run
"""

from __future__ import annotations

import argparse
import json
import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.pipeline.process import run_pipeline


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    parser = argparse.ArgumentParser(description="Generate and load the analytics dataset")
    parser.add_argument("--generate", action="store_true", help="Regenerate raw synthetic CSVs")
    args = parser.parse_args()
    summary = run_pipeline(settings, force_generate=args.generate)
    print(json.dumps(summary["tables"], indent=2))
    print(f"rows_read={summary['rows_read']} rows_valid={summary['rows_valid']} rows_rejected={summary['rows_rejected']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
