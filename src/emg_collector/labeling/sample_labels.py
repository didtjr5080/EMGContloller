"""Join both EMG sensors to MediaPipe labels using host time, never row numbers."""

import csv
import json
import os
from bisect import bisect_right
from pathlib import Path
from emg_collector.sync.clock_alignment import map_sample, load_clock_mappings

from emg_collector.labeling.review import (
    effective_review,
    read_attempts,
    read_csv,
    read_sets,
    review_history,
)

LABELED_SAMPLES_NAME = "labeled_samples.csv"
LABEL_COLUMNS = [
    "sample_index",
    "epoch_id",
    "device_time_us",
    "unwrapped_time_us",
    "host_receive_ns",
    "measurement_host_ns",
    "alignment_status",
    "alignment_uncertainty_ns",
    "mapping_version",
    "pose_alignment_basis",
    "pose_alignment_host_ns",
    "biceps_env_adc",
    "biceps_raw_adc",
    "triceps_env_adc",
    "triceps_raw_adc",
    "set_id",
    "pose_frame_id",
    "pose_capture_host_ns",
    "pose_infer_host_ns",
    "pose_age_ms",
    "elbow_angle_deg",
    "trunk_tilt_deg",
    "upperarm_delta_deg",
    "auto_trunk_fixed",
    "auto_pelvis_fixed",
    "pose_valid",
    "phase",
    "attempt_id",
    "attempt_validity",
    "label_source",
    "label_status",
    "label_revision",
    "synthetic",
]


def labeled_rows(
    samples,
    poses,
    sets,
    attempts,
    max_gap_ns,
    *,
    synthetic=False,
    revision="automatic",
    clock_mappings=None,
    allow_unverified=False,
    max_uncertainty_ns=50_000_000,
):
    poses = sorted(poses, key=lambda p: int(p["capture_host_ns"]))
    times = [int(p["capture_host_ns"]) for p in poses]
    sets = sorted(sets, key=lambda s: s.start_ns)
    set_starts = [s.start_ns for s in sets]
    attempts = sorted(attempts, key=lambda a: a.start_ns)
    attempt_starts = [a.start_ns for a in attempts]
    for sample in samples:
        alignment = map_sample(
            sample, clock_mappings or {}, max_uncertainty_ns=max_uncertainty_ns
        )
        ns = (
            alignment["measurement_host_ns"]
            if alignment["alignment_status"] == "aligned" or allow_unverified
            else None
        )
        basis = (
            "validated_measurement"
            if alignment["alignment_status"] == "aligned"
            else "unavailable"
        )
        if allow_unverified and alignment["alignment_status"] != "aligned":
            # Preserve estimates as estimates; receipt time is only a fallback.
            basis = "estimated_measurement" if ns is not None else "host_receive"
            if ns is None:
                ns = int(sample["host_receive_ns"])
        set_index = bisect_right(set_starts, ns) - 1 if ns is not None else -1
        record = sets[set_index] if set_index >= 0 else None
        if record and (record.end_ns is None or ns > record.end_ns):
            record = None
        index = bisect_right(times, ns) - 1 if ns is not None else -1
        pose = poses[index] if index >= 0 and ns - times[index] <= max_gap_ns else None
        pose_valid = bool(pose and pose["quality_mask"] == "ok")
        attempt_index = bisect_right(attempt_starts, ns) - 1 if ns is not None else -1
        attempt = attempts[attempt_index] if attempt_index >= 0 else None
        if attempt and (
            record is None or attempt.set_id != record.set_id or ns > attempt.end_ns
        ):
            attempt = None
        phase = "ready" if pose_valid else "unknown"
        if attempt and pose_valid:
            phases = [(at, name) for name, at in attempt.phases.items() if at <= ns]
            phase = max(phases)[1] if phases else "unknown"
        yield {
            **alignment,
            "pose_alignment_basis": basis,
            "pose_alignment_host_ns": ns,
            **{
                key: sample[key]
                for key in (
                    "sample_index",
                    "epoch_id",
                    "device_time_us",
                    "unwrapped_time_us",
                    "host_receive_ns",
                )
            },
            "biceps_env_adc": sample["s1_env"],
            "biceps_raw_adc": sample["s1_raw"],
            "triceps_env_adc": sample["s2_env"],
            "triceps_raw_adc": sample["s2_raw"],
            "set_id": record.set_id if record else "",
            "pose_frame_id": pose["frame_id"] if pose else None,
            "pose_capture_host_ns": pose["capture_host_ns"] if pose else None,
            "pose_infer_host_ns": pose["infer_host_ns"] if pose else None,
            "pose_age_ms": (ns - int(pose["capture_host_ns"])) / 1e6 if pose else None,
            **{
                key: pose[key] if pose_valid else None
                for key in ("elbow_angle_deg", "trunk_tilt_deg", "upperarm_delta_deg")
            },
            "pose_valid": pose_valid,
            "auto_trunk_fixed": pose.get("trunk_fixed") if pose else None,
            "auto_pelvis_fixed": pose.get("pelvis_fixed") if pose else None,
            "phase": phase,
            "attempt_id": attempt.attempt_id if attempt else "",
            "attempt_validity": attempt.validity if attempt else "unknown",
            "label_source": (
                "mediapipe_pose"
                if revision == "automatic"
                else "reviewed_mediapipe_pose"
            ),
            "label_status": (
                (record.review_status if record else "provisional")
                if alignment["alignment_status"] == "aligned"
                else "alignment_unverified"
            ),
            "label_revision": revision,
            "synthetic": synthetic,
        }


def write_labeled_samples(root, output=None, *, reviewed=False):
    root = Path(root)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    from emg_collector.quality.window import QualityPolicy

    policy = QualityPolicy.model_validate(metadata.get("quality_policy", {}))
    if (
        metadata.get("schema_version") != "3.0.0"
        or metadata.get("profile") != "biceps_triceps_v3"
    ):
        raise ValueError(
            "combined biceps/triceps labels require the explicit v3 biceps_triceps profile"
        )
    output = Path(output) if output is not None else root / LABELED_SAMPLES_NAME
    part = output.with_name(output.name + ".part")
    if output.exists() or part.exists():
        raise FileExistsError(f"refusing to overwrite existing labels: {output}")
    if reviewed:
        sets, attempts = effective_review(root)
        history = review_history(root)
        revision = history[-1]["revision"] if history else "automatic"
    else:
        sets, attempts = read_sets(root), read_attempts(root)
        revision = "automatic"
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with (
        (root / "samples.csv").open(newline="", encoding="utf-8") as source,
        part.open("x", newline="", encoding="utf-8") as target,
    ):
        writer = csv.DictWriter(target, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        for row in labeled_rows(
            csv.DictReader(source),
            read_csv(root, "pose_metrics.csv"),
            sets,
            attempts,
            metadata["protocol"]["max_pose_gap_ns"],
            synthetic=metadata["synthetic"],
            revision=revision,
            clock_mappings=load_clock_mappings(root),
            allow_unverified=True,
            max_uncertainty_ns=policy.maximum_uncertainty_ns,
        ):
            writer.writerow(row)
            count += 1
        target.flush()
        os.fsync(target.fileno())
    part.rename(output)
    return count
