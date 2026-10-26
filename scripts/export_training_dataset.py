"""Export causal v3 inputs. Output directory must not already exist."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from emg_collector.storage.training_export import export_training


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--allow-pilot", action="store_true")
    parser.add_argument("--window-s", type=float, default=5)
    parser.add_argument("--last-k", type=int)
    parser.add_argument("--stride-reps", type=int, default=1)
    parser.add_argument("--include-personal", action="store_true")
    parser.add_argument("--include-load", action="store_true")
    args = parser.parse_args()
    try:
        print(export_training(**vars(args)))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"export failed: {exc}\n")


if __name__ == "__main__":
    main()
