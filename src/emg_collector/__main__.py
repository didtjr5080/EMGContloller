from __future__ import annotations

import sys
import argparse
from pathlib import Path

from emg_collector.app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="이두·삼두 EMG + MediaPipe 동시 수집")
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument(
        "--legacy-v2", action="store_true", help="기존 이두·상완요골근 화면 열기"
    )
    args = parser.parse_args()
    sys.exit(run(args.dataset_root, legacy_v2=args.legacy_v2))


if __name__ == "__main__":
    main()
