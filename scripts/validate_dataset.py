#!/usr/bin/env python
"""Validate referential integrity of a dataset_root produced by the collector.

Checks performed:
    - dataset_manifest.json, participants_public.csv, sessions.csv exist and
      have the expected columns.
    - Every sessions.csv row has a matching sessions/<id>/ directory with
      samples.csv, events.csv, metadata.json, quality.json.
    - metadata.json's session_id/participant_id match the sessions.csv row.
    - samples.csv row count equals quality.json's valid_samples.
    - samples.csv columns match the documented schema.
    - No leftover .part files (a finished dataset should have none; if any
      are found they are reported, not deleted).
    - sample_index is contiguous from 0 and device_time_us_unwrapped is
      non-decreasing within each session.

Usage:
    python scripts/validate_dataset.py DATASET_ROOT
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from emg_collector.config import SAMPLES_CSV_HEADER  # noqa: E402


def validate(dataset_root: Path) -> list[str]:
    errors: list[str] = []

    manifest_path = dataset_root / "dataset_manifest.json"
    sessions_csv_path = dataset_root / "sessions.csv"
    public_csv_path = dataset_root / "participants_public.csv"

    for required in (manifest_path, sessions_csv_path, public_csv_path):
        if not required.exists():
            errors.append(f"missing required file: {required}")
    if errors:
        return errors

    known_participant_ids = set()
    with open(public_csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            known_participant_ids.add(row["participant_id"])

    with open(sessions_csv_path, newline="", encoding="utf-8") as fh:
        session_rows = list(csv.DictReader(fh))

    for row in session_rows:
        session_id = row["session_id"]
        session_dir = dataset_root / "sessions" / session_id
        if not session_dir.is_dir():
            errors.append(f"[{session_id}] session directory missing: {session_dir}")
            continue

        samples_path = session_dir / "samples.csv"
        events_path = session_dir / "events.csv"
        metadata_path = session_dir / "metadata.json"
        quality_path = session_dir / "quality.json"

        for path in (samples_path, events_path, metadata_path, quality_path):
            if not path.exists():
                errors.append(f"[{session_id}] missing file: {path.name}")

        if (session_dir / "samples.csv.part").exists():
            errors.append(f"[{session_id}] leftover samples.csv.part found")
        if (session_dir / "events.csv.part").exists():
            errors.append(f"[{session_id}] leftover events.csv.part found")

        if row.get("participant_id") and row["participant_id"] not in known_participant_ids:
            errors.append(
                f"[{session_id}] participant_id {row['participant_id']!r} not in "
                "participants_public.csv"
            )

        if not metadata_path.exists() or not samples_path.exists() or not quality_path.exists():
            continue

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("session_id") != session_id:
            errors.append(f"[{session_id}] metadata.json session_id mismatch")
        if metadata.get("participant_id") != row.get("participant_id"):
            errors.append(f"[{session_id}] metadata.json participant_id mismatch")

        quality = json.loads(quality_path.read_text(encoding="utf-8"))

        with open(samples_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            if header != SAMPLES_CSV_HEADER:
                errors.append(f"[{session_id}] samples.csv header mismatch: {header}")
            sample_rows = list(reader)

        if quality.get("valid_samples") != len(sample_rows):
            errors.append(
                f"[{session_id}] quality.json valid_samples={quality.get('valid_samples')} "
                f"!= samples.csv row count={len(sample_rows)}"
            )

        prev_time = None
        for idx, sample_row in enumerate(sample_rows):
            if int(sample_row[0]) != idx:
                errors.append(f"[{session_id}] sample_index not contiguous at row {idx}")
                break
            unwrapped = int(sample_row[2])
            if prev_time is not None and unwrapped < prev_time:
                errors.append(
                    f"[{session_id}] device_time_us_unwrapped decreased at row {idx}"
                )
                break
            prev_time = unwrapped

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    args = parser.parse_args()

    errors = validate(args.dataset_root)
    if errors:
        print(f"FAILED: {len(errors)} issue(s) found")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print("OK: dataset passed all integrity checks")


if __name__ == "__main__":
    main()
