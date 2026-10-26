"""Reproducible participant-first split and strictly causal feature export."""

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from emg_collector.labeling.review import effective_review, read_csv
from emg_collector.multimodal.schema import remaining
from emg_collector.storage.multimodal_writer import atomic_json
from emg_collector.sync.clock_alignment import align_previous


def participant_splits(ids, seed):
    # Hash assignment is stable when visits or participants are added.
    output = {}
    for participant in sorted(set(ids)):
        value = (
            int(hashlib.sha256(f"{seed}:{participant}".encode()).hexdigest()[:8], 16)
            / 2**32
        )
        output[participant] = (
            "train" if value < 0.7 else ("validation" if value < 0.85 else "test")
        )
    return output


def causal_window(rows, end_ns, duration_ns, start_ns=None, key="host_receive_ns"):
    lower = max(end_ns - duration_ns, start_ns if start_ns is not None else 0)
    return [r for r in rows if lower <= int(r[key]) <= end_ns]


def export_training(
    dataset_root,
    output,
    *,
    seed=42,
    synthetic=False,
    window_s=5.0,
    last_k=None,
    stride_reps=1,
    include_personal=False,
    include_load=False,
    allow_pilot=False,
):
    from emg_collector.multimodal.validator import validate_session

    if window_s <= 0 or stride_reps < 1 or (last_k is not None and last_k < 1):
        raise ValueError("window, K and stride must be positive")
    root = Path(dataset_root)
    output = Path(output)
    sessions = []
    excluded = {}

    def exclude(reason):
        excluded[reason] = excluded.get(reason, 0) + 1

    for path in sorted((root / "sessions").glob("*/metadata.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != "3.0.0":
            exclude("legacy_schema")
            continue
        if metadata.get("synthetic") is not synthetic:
            exclude("different_synthetic_mode")
            continue
        errors = validate_session(path.parent)
        if errors:
            raise ValueError(f"{path.parent.name}: " + "; ".join(errors))
        if metadata["protocol"]["status"] == "PILOT" and not allow_pilot:
            exclude("pilot_protocol")
            continue
        sessions.append((path.parent, metadata))
    assignments = participant_splits([m["participant_id"] for _, m in sessions], seed)
    output.mkdir(parents=True, exist_ok=False)
    (output / "sequences").mkdir()
    atomic_json(
        output / "split_manifest.json",
        {
            "seed": seed,
            "unit": "participant_id",
            "assignments": assignments,
            "synthetic": synthetic,
            "algorithm": "sha256(seed:participant), 70/15/15; small cohorts may have empty splits",
        },
    )
    feature_names = [
        "s1_raw_rms",
        "s1_raw_mav",
        "s2_raw_rms",
        "s2_raw_mav",
        "s1_env_mean",
        "s2_env_mean",
        "elbow_mean_deg",
        "trunk_max_deg",
        "upperarm_max_deg",
        "recent_rom_deg",
        "recent_duration_s",
        "rom_change_deg",
    ]
    if include_personal:
        feature_names += [
            "age_years",
            "height_cm",
            "weight_kg",
            "strength_training_months",
        ]
    if include_load:
        feature_names += ["load_kg"]
    index = []
    features = []
    for path, metadata in sessions:
        sets, attempts = effective_review(path)
        samples = read_csv(path, "samples.csv")
        poses = read_csv(path, "pose_metrics.csv")
        for row in samples:
            row["host_receive_ns"] = int(row["host_receive_ns"])
        for row in poses:
            row["capture_host_ns"] = int(row["capture_host_ns"])
        poses.sort(key=lambda r: r["capture_host_ns"])
        for record in sets:
            failure = next(
                (
                    a
                    for a in attempts
                    if a.attempt_id == record.failure_attempt_id
                    and a.set_id == record.set_id
                ),
                None,
            )
            valid = sorted(
                [
                    a
                    for a in attempts
                    if a.set_id == record.set_id
                    and a.validity == "valid"
                    and (failure is None or a.end_ns <= failure.start_ns)
                ],
                key=lambda a: a.end_ns,
            )
            k = 0
            for attempt in valid:
                label = remaining(record, attempts, k + 1)
                if label is None:
                    exclude("unconfirmed_or_censored")
                    break
                k += 1
                if (k - 1) % stride_reps:
                    continue
                end = attempt.end_ns
                start = (
                    valid[max(0, k - last_k)].start_ns if last_k else record.start_ns
                )
                duration = end - start if last_k else int(window_s * 1e9)
                window = causal_window(samples, end, duration, start_ns=start)
                if not window:
                    exclude("missing_emg")
                    continue
                emg = np.asarray(
                    [
                        [
                            float(r[key])
                            for key in ("s1_env", "s1_raw", "s2_env", "s2_raw")
                        ]
                        for r in window
                    ],
                    dtype=np.float32,
                )
                mask = []
                motion = []
                available_poses = [p for p in poses if int(p["infer_host_ns"]) <= end]
                for row in window:
                    joined = align_previous(
                        available_poses,
                        row["host_receive_ns"],
                        metadata["protocol"]["max_pose_gap_ns"],
                    )
                    okay = joined is not None and joined["quality_mask"] == "ok"
                    mask.append([True] * 4 + [okay] * 3)
                    motion.append(
                        [
                            float(joined[key]) if okay else 0.0
                            for key in (
                                "elbow_angle_deg",
                                "trunk_tilt_deg",
                                "upperarm_delta_deg",
                            )
                        ]
                    )
                motion = np.asarray(motion, dtype=np.float32)
                okay = np.asarray(mask)[:, 4]
                if not okay.any():
                    exclude("missing_motion_common_evaluation")
                    continue
                sequence = np.concatenate([emg, motion], axis=1)
                sample_id = f"W{len(index):07d}"
                np.savez_compressed(
                    output / "sequences" / f"{sample_id}.npz",
                    values=sequence,
                    mask=np.asarray(mask, dtype=bool),
                    host_ns=np.asarray(
                        [r["host_receive_ns"] for r in window], dtype=np.int64
                    ),
                )
                values = []
                for channel in (1, 3):
                    centered = emg[:, channel] - 2048  # ADC midscale, no full-set fit.
                    values += [
                        float(np.sqrt(np.mean(centered**2))),
                        float(np.mean(np.abs(centered))),
                    ]

                def observed_rom(rep):
                    angles = [
                        float(p["elbow_angle_deg"])
                        for p in available_poses
                        if rep.start_ns <= p["capture_host_ns"] <= rep.end_ns
                        and p["quality_mask"] == "ok"
                    ]
                    return max(angles) - min(angles) if len(angles) > 1 else None

                rom = observed_rom(attempt)
                previous_rom = observed_rom(valid[k - 2]) if k > 1 else None
                values += [
                    float(emg[:, 0].mean()),
                    float(emg[:, 2].mean()),
                    float(motion[okay, 0].mean()),
                    float(motion[okay, 1].max()),
                    float(motion[okay, 2].max()),
                    rom,
                    (attempt.end_ns - attempt.start_ns) / 1e9,
                    (
                        rom - previous_rom
                        if rom is not None and previous_rom is not None
                        else None
                    ),
                ]
                if include_personal:
                    p = metadata["participant"]
                    values += [
                        p.get("age"),
                        p.get("height_cm"),
                        p.get("weight_kg"),
                        p.get("strength_training_months"),
                    ]
                if include_load:
                    values += [record.load_kg]
                features.append(
                    dict(zip(["window_id", *feature_names], [sample_id, *values]))
                )
                following = sorted(
                    [
                        a
                        for a in attempts
                        if a.set_id == record.set_id and a.start_ns >= attempt.end_ns
                    ],
                    key=lambda a: a.start_ns,
                )
                index.append(
                    {
                        "window_id": sample_id,
                        "participant_id": metadata["participant_id"],
                        "session_id": metadata["session_id"],
                        "set_id": record.set_id,
                        "attempt_id": attempt.attempt_id,
                        "split": assignments[metadata["participant_id"]],
                        "prediction_host_ns": end,
                        "remaining_valid_reps": label,
                        "next_attempt_failure": bool(
                            following
                            and following[0].attempt_id == record.failure_attempt_id
                        ),
                        "synthetic": synthetic,
                    }
                )
    for name, rows, columns in [
        ("tabular_features.csv", features, ["window_id", *feature_names]),
        (
            "index.csv",
            index,
            [
                "window_id",
                "participant_id",
                "session_id",
                "set_id",
                "attempt_id",
                "split",
                "prediction_host_ns",
                "remaining_valid_reps",
                "next_attempt_failure",
                "synthetic",
            ],
        ),
    ]:
        with (output / name).open("x", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    atomic_json(
        output / "export_manifest.json",
        {
            "synthetic": synthetic,
            "examples": len(index),
            "excluded": excluded,
            "window_s": window_s,
            "last_k": last_k,
            "stride_reps": stride_reps,
            "sequence_columns": [
                "s1_env_adc",
                "s1_raw_adc",
                "s2_env_adc",
                "s2_raw_adc",
                "elbow_deg",
                "trunk_deg",
                "upperarm_delta_deg",
            ],
            "alignment": "causal previous neighbor; maximum gap from protocol; invalid values zero with mask=False",
            "preprocessing": "raw ADC minus fixed midscale 2048 for RMS/MAV only; no fitted transform, no filtering",
            "spectral_features": "MDF/MNF omitted: analog bandwidth and anti-alias not validated",
            "EMG_only": "prediction features only; repetition segmentation uses pose",
            "next_attempt_failure": "the immediately following reviewed attempt is the terminal technical failure; separate target, not remaining<=1",
            "comparison": "same index for EMG, motion, combined; sequence columns select modalities",
            "personal_features": include_personal,
            "load_feature": include_load,
            "fit_policy": "none; any downstream imputer/scaler fits train only",
            "evaluation": [
                "MAE",
                "low-remaining overprediction frequency and magnitude (threshold preregistered)",
                "per-participant error",
                "inference latency; final test once after selection",
            ],
        },
    )
    return {"examples": len(index), "excluded": excluded}
