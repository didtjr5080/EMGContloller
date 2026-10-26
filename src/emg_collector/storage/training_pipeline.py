"""Session isolation, causal availability, window quality and transactional output."""

import csv
import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path
import numpy as np

from emg_collector.labeling.review import effective_review, read_csv, review_history
from emg_collector.multimodal.schema import remaining
from emg_collector.multimodal.eligibility import session_eligibility
from emg_collector.quality.window import QualityPolicy, window_quality
from emg_collector.storage.multimodal_writer import atomic_json
from emg_collector.sync.clock_alignment import (
    ALIGNMENT_VERSION,
    aligned_samples,
    alignment_fingerprint,
    load_clock_mappings,
    decision_time,
)


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
    strict=False,
    allow_unverified_alignment=False,
    quality_policy=None,
):
    from emg_collector.storage.training_export import participant_splits

    if window_s <= 0 or stride_reps < 1 or (last_k is not None and last_k < 1):
        raise ValueError("window, K and stride must be positive")
    root, output = Path(dataset_root), Path(output)
    if not (root / "sessions").is_dir():
        raise ValueError("dataset sessions directory missing")
    if output.exists():
        raise FileExistsError(output)
    policy = QualityPolicy.model_validate(quality_policy or {})
    reports = [
        session_eligibility(
            p,
            synthetic=synthetic,
            allow_pilot=allow_pilot,
            quality_policy=quality_policy,
        )
        for p in sorted((root / "sessions").iterdir())
        if p.is_dir()
    ]
    problematic = {
        "incomplete",
        "recovered",
        "unreviewed",
        "censored",
        "corrupt",
        "quality_failed",
    }
    if strict and any(r["status"] in problematic for r in reports):
        raise ValueError("strict export: excluded session(s); no output committed")
    eligible = [r for r in reports if r["status"] == "eligible"]
    metas = {
        r["session_id"]: json.loads(
            (root / "sessions" / r["session_id"] / "metadata.json").read_text(
                encoding="utf-8"
            )
        )
        for r in eligible
    }
    assignments = participant_splits(
        [m["participant_id"] for m in metas.values()], seed
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(output.name + ".part-" + uuid.uuid4().hex)
    staging.mkdir()
    (staging / "sequences").mkdir()
    atomic_json(staging / "export_state.json", {"status": "incomplete"})
    excluded = Counter()
    window_reports = []
    index = []
    features = []
    provenance = []
    set_exclusions = Counter()
    policies_used = {}
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
        feature_names += ["load_kg", "dumbbell_count"]
    try:
        for report in eligible:
            sid = report["session_id"]
            path = root / "sessions" / sid
            metadata = metas[sid]
            policy = QualityPolicy.model_validate(
                quality_policy
                if quality_policy is not None
                else metadata.get("quality_policy", {})
            )
            policy_hash = hashlib.sha256(
                json.dumps(policy.model_dump(), sort_keys=True).encode()
            ).hexdigest()
            policies_used[policy_hash] = policy.model_dump()
            sets, attempts = effective_review(path)
            samples = read_csv(path, "samples.csv")
            poses = read_csv(path, "pose_metrics.csv")
            for row in poses:
                row["capture_host_ns"] = int(row["capture_host_ns"])
            poses.sort(key=lambda r: r["capture_host_ns"])
            mappings = load_clock_mappings(path)
            history = review_history(path)
            provenance.append(
                {
                    "session_id": sid,
                    "alignment_version": ALIGNMENT_VERSION,
                    "mapping_fingerprint": alignment_fingerprint(mappings),
                    "quality_policy": policy.version,
                    "quality_policy_fingerprint": policy_hash,
                    "protocol_version": metadata["protocol"]["version"],
                    "review_revision": history[-1]["revision"] if history else None,
                    "source_acquisition_hash": (
                        history[-1].get("evidence", {}).get("source_acquisition_hash")
                        if history
                        else None
                    ),
                }
            )
            before = len(index)
            for record in sets:
                if remaining(record, attempts, 0) is None:
                    set_exclusions["unconfirmed_or_censored"] += 1
                    continue
                failure = next(
                    a
                    for a in attempts
                    if a.attempt_id == record.failure_attempt_id
                    and a.set_id == record.set_id
                )
                valid = sorted(
                    (
                        a
                        for a in attempts
                        if a.set_id == record.set_id
                        and a.validity == "valid"
                        and a.end_ns <= failure.start_ns
                    ),
                    key=lambda a: a.end_ns,
                )
                for k, attempt in enumerate(valid, 1):
                    if (k - 1) % stride_reps:
                        continue
                    end = attempt.end_ns
                    start = (
                        valid[max(0, k - last_k)].start_ns
                        if last_k
                        else max(record.start_ns, end - int(window_s * 1e9))
                    )
                    decision = decision_time(
                        attempt,
                        poses,
                        metadata["protocol"]["debounce_ns"],
                        policy.maximum_decision_latency_ns,
                    )
                    if decision is None:
                        excluded["decision_unavailable"] += 1
                        continue
                    aligned = aligned_samples(
                        samples,
                        mappings,
                        decision_host_ns=decision,
                        max_uncertainty_ns=policy.maximum_uncertainty_ns,
                    )
                    window = [
                        s
                        for s in aligned
                        if s["measurement_host_ns"] is not None
                        and start <= s["measurement_host_ns"] <= end
                    ]
                    window.sort(key=lambda s: s["measurement_host_ns"])
                    quality = window_quality(window, start, end, policy)
                    reasons = [
                        r
                        for r in quality["reasons"]
                        if not (
                            allow_unverified_alignment and r == "alignment_unverified"
                        )
                    ]
                    window_reports.append(
                        {
                            "session_id": sid,
                            "attempt_id": attempt.attempt_id,
                            "prediction_capture_ns": end,
                            "decision_host_ns": decision,
                            **quality,
                            "excluded_reasons": reasons,
                        }
                    )
                    if reasons:
                        excluded.update(reasons)
                        continue
                    emg = np.asarray(
                        [
                            [
                                float(s[key])
                                for key in ("s1_env", "s1_raw", "s2_env", "s2_raw")
                            ]
                            for s in window
                        ],
                        dtype=np.float32,
                    )
                    emg_mask = (emg > 0) & (emg < 4095)
                    available = [
                        p
                        for p in poses
                        if int(p["infer_host_ns"]) <= decision
                        and p["capture_host_ns"] <= end
                    ]
                    keys = [p["capture_host_ns"] for p in available]
                    from bisect import bisect_right

                    motion = []
                    motion_valid = []
                    for s in window:
                        t = s["measurement_host_ns"]
                        i = bisect_right(keys, t) - 1
                        joined = (
                            available[i]
                            if i >= 0
                            and t - keys[i] <= metadata["protocol"]["max_pose_gap_ns"]
                            else None
                        )
                        okay = joined is not None and joined["quality_mask"] == "ok"
                        motion_valid.append(okay)
                        motion.append(
                            [
                                float(joined[key]) if okay else 0
                                for key in (
                                    "elbow_angle_deg",
                                    "trunk_tilt_deg",
                                    "upperarm_delta_deg",
                                )
                            ]
                        )
                    good = np.asarray(motion_valid, dtype=bool)
                    if not good.any():
                        excluded["missing_motion_common_evaluation"] += 1
                        continue
                    motion = np.asarray(motion, dtype=np.float32)
                    mask = np.concatenate(
                        [emg_mask, np.repeat(good[:, None], 3, axis=1)], axis=1
                    )
                    sequence = np.concatenate(
                        [np.where(emg_mask, emg, 0), motion], axis=1
                    )
                    wid = f"W{len(index):07d}"
                    measurement = np.asarray(
                        [s["measurement_host_ns"] for s in window], dtype=np.int64
                    )
                    np.savez_compressed(
                        staging / "sequences" / f"{wid}.npz",
                        values=sequence,
                        mask=mask,
                        host_ns=measurement,
                        measurement_host_ns=measurement,
                        host_receive_ns=np.asarray(
                            [int(s["host_receive_ns"]) for s in window], dtype=np.int64
                        ),
                        gap_before_ns=np.diff(measurement, prepend=start),
                        epoch_id=np.asarray([int(s["epoch_id"]) for s in window]),
                        synthetic=synthetic,
                    )
                    values = []
                    for col in (1, 3):
                        centered = emg[emg_mask[:, col], col] - 2048
                        values += [
                            float(np.sqrt(np.mean(centered**2))),
                            float(np.mean(np.abs(centered))),
                        ]

                    def rom(rep):
                        angles = [
                            float(p["elbow_angle_deg"])
                            for p in available
                            if rep.start_ns <= p["capture_host_ns"] <= rep.end_ns
                            and p["quality_mask"] == "ok"
                        ]
                        return max(angles) - min(angles) if len(angles) > 1 else None

                    current = rom(attempt)
                    previous = rom(valid[k - 2]) if k > 1 else None
                    values += [
                        float(emg[emg_mask[:, 0], 0].mean()),
                        float(emg[emg_mask[:, 2], 2].mean()),
                        float(motion[good, 0].mean()),
                        float(motion[good, 1].max()),
                        float(motion[good, 2].max()),
                        current,
                        (attempt.end_ns - attempt.start_ns) / 1e9,
                        (
                            current - previous
                            if current is not None and previous is not None
                            else None
                        ),
                    ]
                    if include_personal:
                        values += [
                            metadata["participant"].get(x)
                            for x in (
                                "age",
                                "height_cm",
                                "weight_kg",
                                "strength_training_months",
                            )
                        ]
                    if include_load:
                        values += [record.load_kg, record.dumbbell_count]
                    features.append(
                        dict(zip(["window_id", *feature_names], [wid, *values]))
                    )
                    following = sorted(
                        (
                            a
                            for a in attempts
                            if a.set_id == record.set_id
                            and a.start_ns >= attempt.end_ns
                        ),
                        key=lambda a: a.start_ns,
                    )
                    index.append(
                        {
                            "window_id": wid,
                            "participant_id": metadata["participant_id"],
                            "session_id": sid,
                            "set_id": record.set_id,
                            "attempt_id": attempt.attempt_id,
                            "split": assignments[metadata["participant_id"]],
                            "prediction_capture_ns": end,
                            "prediction_host_ns": end,
                            "decision_host_ns": decision,
                            "remaining_valid_reps": remaining(record, attempts, k),
                            "next_attempt_failure": bool(
                                following
                                and following[0].attempt_id == record.failure_attempt_id
                            ),
                            "synthetic": synthetic,
                        }
                    )
            if len(index) == before:
                report["status"] = "quality_failed"
                report["error_codes"] = ["no_eligible_windows"]
        session_counts = Counter(r["status"] for r in reports)
        if strict and (excluded or any(r["status"] in problematic for r in reports)):
            raise ValueError(
                "strict export: unusable windows/sessions; no complete manifest"
            )
        for name, rows, fields in [
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
                    "prediction_capture_ns",
                    "prediction_host_ns",
                    "decision_host_ns",
                    "remaining_valid_reps",
                    "next_attempt_failure",
                    "synthetic",
                ],
            ),
        ]:
            with (staging / name).open("x", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        atomic_json(
            staging / "split_manifest.json",
            {
                "seed": seed,
                "unit": "participant_id",
                "assignments": assignments,
                "synthetic": synthetic,
            },
        )
        atomic_json(
            staging / "exclusion_report.json",
            {
                "sessions": reports,
                "session_counts": dict(session_counts),
                "window_counts": dict(excluded),
                "set_counts": dict(set_exclusions),
                "candidate_windows": len(window_reports),
            },
        )
        atomic_json(staging / "window_quality.json", window_reports)
        counts = Counter(r["split"] for r in index)
        empty = [s for s in ("train", "validation", "test") if not counts[s]]
        manifest = {
            "status": "complete",
            "examples": len(index),
            "synthetic": synthetic,
            "excluded": dict(excluded),
            "excluded_sessions": dict(session_counts),
            "empty_splits": empty,
            "training_ready": bool(index)
            and not empty
            and not allow_unverified_alignment,
            "quality_policy": policy.model_dump(),
            "alignment_version": ALIGNMENT_VERSION,
            "review_baseline_revision": "829e24c932dbaaaf61bacc8b7dd449decdff6df4",
            "implementation_version": "review-fixes-1",
            "quality_policies": policies_used,
            "provenance": provenance,
            "window_s": window_s,
            "last_k": last_k,
            "stride_reps": stride_reps,
            "include_personal": include_personal,
            "include_load": include_load,
            "strict": strict,
            "allow_pilot": allow_pilot,
            "allow_unverified_alignment": allow_unverified_alignment,
            "warnings": (
                ["diagnostic alignment; physical synchronization unverified"]
                if allow_unverified_alignment
                else []
            ),
            "sequence_layout": "irregular observations; missing times are represented by timestamps and gap_before_ns, not implicit all-True continuity",
            "sequence_columns": [
                "s1_env_adc",
                "s1_raw_adc",
                "s2_env_adc",
                "s2_raw_adc",
                "elbow_deg",
                "trunk_deg",
                "upperarm_delta_deg",
            ],
            "alignment": "measurement time joins; receipt/inference and causal mapping available by decision_host_ns only",
            "EMG_only": "prediction features only; pose-based reviewed segmentation",
            "fit_policy": "no fitted transforms; downstream scaler/imputer/selection train only",
            "preprocessing": "fixed ADC midscale 2048 for RAW RMS/MAV; no spectral validity claim",
            "comparison": "one common index for all modalities; no IDs or reviewed targets in model features",
            "evaluation": [
                "MAE",
                "low-remaining overprediction",
                "per-participant error",
                "decision/inference latency",
                "final test once after selection",
            ],
        }
        atomic_json(staging / "export_state.json", {"status": "complete"})
        atomic_json(staging / "export_manifest.json", manifest)
        staging.rename(output)
        return {
            "examples": len(index),
            "excluded": dict(excluded),
            "excluded_sessions": dict(session_counts),
            "empty_splits": empty,
            "warnings": manifest["warnings"],
        }
    except Exception:
        if (staging / "export_manifest.json").exists():
            (staging / "export_manifest.json").unlink()
        atomic_json(
            staging / "export_state.json",
            {"status": "incomplete", "reason": "export_failed"},
        )
        raise
