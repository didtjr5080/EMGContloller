#!/usr/bin/env python
"""Launch the EMG Dataset Collector GUI.

Usage:
    python scripts/run_app.py [--dataset-root PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from emg_collector.app import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path.cwd() / "datasets",
        help="Directory where dataset_root will be created (default: ./datasets)",
    )
    args = parser.parse_args()
    sys.exit(run(args.dataset_root))


if __name__ == "__main__":
    main()
