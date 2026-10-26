"""Allowlisted signal archive; private records, video and free text never copied."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from emg_collector.config import DEFAULT_LABELS
from emg_collector.storage.multimodal_writer import atomic_json

PUBLIC_FIELDS = [
    "participant_id",
    "age",
    "sex",
    "height_cm",
    "weight_kg",
    "dominant_arm",
    "exercise_sessions_per_week",
    "exercise_minutes_per_week",
    "days_since_last_exercise",
]


def _csv(src, dst, fields, labels=False):
    if not src.exists():
        return
    with (
        src.open(newline="", encoding="utf-8") as inp,
        dst.open("x", newline="", encoding="utf-8") as out,
    ):
        reader = csv.DictReader(inp)
        columns = [key for key in fields if key in (reader.fieldnames or [])]
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for row in reader:
            clean = {key: row[key] for key in columns}
            if labels and clean.get("label") not in DEFAULT_LABELS:
                clean["label"] = "unknown"
            writer.writerow(clean)


def export_deidentified(dataset_root: Path, output_dir: Path) -> Path:
    from emg_collector.config import SAMPLES_CSV_HEADER
    from emg_collector.storage.multimodal_writer import STREAMS

    root = Path(dataset_root)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    _csv(
        root / "participants_public.csv",
        output / "participants_public.csv",
        PUBLIC_FIELDS,
    )
    (output / "sessions").mkdir()
    for path in sorted((root / "sessions").glob("*/metadata.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        dst = output / "sessions" / path.parent.name
        dst.mkdir()
        schema = metadata.get("schema_version", "2.0.0")
        if schema not in ("2.0.0", "3.0.0"):
            raise ValueError(f"unsupported schema: {schema}")
        safe = {
            key: metadata[key]
            for key in ("schema_version", "participant_id", "session_id", "synthetic")
            if key in metadata
        }
        safe["archive_type"] = (
            "deidentified_signals; use training exporter for reviewed exact labels"
        )
        if schema == "3.0.0":
            safe["channels"] = [
                {
                    key: c[key]
                    for key in (
                        "channel_id",
                        "sensor_id",
                        "muscle",
                        "signal",
                        "gpio",
                        "side",
                    )
                }
                for c in metadata["channels"]
            ]
            for name in ("samples.csv", "pose_landmarks.csv", "pose_metrics.csv"):
                _csv(path.parent / name, dst / name, STREAMS[name])
        else:
            _csv(
                path.parent / "samples.csv",
                dst / "samples.csv",
                SAMPLES_CSV_HEADER,
                labels=True,
            )
        atomic_json(dst / "metadata.json", safe)
    atomic_json(
        output / "export_manifest.json",
        {
            "type": "deidentified_signal_archive",
            "allowlist": True,
            "excluded": [
                "private",
                "video",
                "video paths",
                "free text",
                "annotations",
                "events",
            ],
            "collection_dataset": False,
        },
    )
    return output
