"""Strict v3 stream, reference, boundary and completion validation."""

import json
import math
from pathlib import Path

from emg_collector.labeling.review import effective_review, read_csv, review_history
from emg_collector.multimodal.schema import Sample, channels, Consent, Visit, remaining
from emg_collector.models import ParticipantPublic
from emg_collector.protocols import PilotProtocol
from emg_collector.storage.multimodal_writer import STREAMS, file_info, video_playable
from emg_collector.labeling.validation import validate_annotations
from emg_collector.labeling.review_contract import (
    TRANSACTION,
    confirmation_valid,
    evidence_context,
)
from emg_collector.sync.clock_alignment import aligned_samples, load_clock_mappings
from emg_collector.quality.window import window_quality, QualityPolicy


def validate_session(root):
    root = Path(root)
    errors = []

    def error(field, message):
        errors.append(f"[{root.name}/{field}] {message}")

    try:
        m = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        if m.get("schema_version") != "3.0.0":
            error(
                "schema_version",
                "unsupported; only v2 and v3 supported, v1 is unsupported",
            )
            return errors
        if not isinstance(m.get("synthetic"), bool):
            error("synthetic", "explicit boolean required")
        if m["session_id"] != root.name:
            error("session_id", "directory mismatch")
        consent = Consent.model_validate(m["consent"])
        if not consent.research or not consent.pose_coordinates:
            error("consent", "research and pose consent required")
        visit = Visit.model_validate(m["visit"])
        if visit.visit_id != m["visit_id"]:
            error("visit_id", "visit snapshot mismatch")
        participant = ParticipantPublic.model_validate(m["participant"])
        if participant.participant_id != m["participant_id"]:
            error("participant_id", "participant snapshot mismatch")
        PilotProtocol.model_validate(m["protocol"])
        expected = channels(m["profile"], m["channels"][0]["side"])
        for actual, wanted in zip(m["channels"], expected, strict=True):
            for key in ("channel_id", "sensor_id", "muscle", "signal", "gpio", "side"):
                if actual[key] != getattr(wanted, key):
                    error("channels", f"{key} does not match explicit profile")
        manifest = json.loads(
            (root / "completion_manifest.json").read_text(encoding="utf-8")
        )
        if manifest["status"] != "complete":
            error(
                "completion_manifest",
                "session incomplete or recovered; labels cannot be inferred from file presence",
            )
        required = [
            *STREAMS,
            "metadata.json",
            "sync.json",
            "quality.json",
            "annotations.jsonl",
        ]
        if m.get("labeling", {}).get("sample_labels_file") == "labeled_samples.csv":
            required.append("labeled_samples.csv")
        for name in required:
            path = root / name
            if not path.exists():
                error(name, "missing stream")
                continue
            info = manifest.get("files", {}).get(name, {})
            actual = file_info(path)
            if (
                info.get("sha256") != actual["sha256"]
                or info.get("rows") != actual["rows"]
            ):
                error(name, "manifest hash/row count mismatch")
        for part in root.rglob("*.part*"):
            error(part.name, "unfinished stream retained")
        if m["consent"]["video_storage"]:
            videos = list((root / "video").glob("*.avi"))
            if not videos:
                error("video", "consented recording missing")
            for video in videos:
                info = manifest.get("files", {}).get(
                    video.relative_to(root).as_posix(), {}
                )
                if info.get("sha256") != file_info(video)[
                    "sha256"
                ] or not video_playable(video):
                    error("video", "hash mismatch or decode failed")
        samples = read_csv(root, "samples.csv")
        if not samples:
            error("samples", "empty required stream")
        previous_ns = None
        previous_epoch = -1
        epoch_time = {}
        for i, row in enumerate(samples):
            try:
                s = Sample.model_validate(row)
                if s.sample_index != i:
                    error(f"samples/{i}/sample_index", "must be contiguous")
                if previous_ns is not None and s.host_receive_ns < previous_ns:
                    error(f"samples/{i}/host_receive_ns", "regressed")
                if s.epoch_id < previous_epoch:
                    error(f"samples/{i}/epoch_id", "regressed")
                if s.unwrapped_time_us < epoch_time.get(s.epoch_id, 0):
                    error(f"samples/{i}/unwrapped_time_us", "regressed within epoch")
                previous_ns = s.host_receive_ns
                previous_epoch = s.epoch_id
                epoch_time[s.epoch_id] = s.unwrapped_time_us
            except ValueError as exc:
                error(f"samples/{i}", str(exc))
        quality = json.loads((root / "quality.json").read_text(encoding="utf-8"))
        if quality["valid_samples"] != len(samples):
            error("quality/valid_samples", "sample count mismatch")
        if quality.get("errors") or quality.get("writer_queue_overflow"):
            error("quality", "acquisition failures present")
        sync = json.loads((root / "sync.json").read_text(encoding="utf-8"))
        for epoch in epoch_time:
            if str(epoch) not in sync["epochs"]:
                error("sync/epochs", f"missing epoch {epoch}")
        frames = read_csv(root, "frame_timestamps.csv")
        import cv2

        video_counts = {}
        for video in (root / "video").glob("*.avi"):
            cap = cv2.VideoCapture(str(video))
            video_counts[video.name] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
        for f in frames:
            if f["saved"] == "True" and (
                f["segment"] not in video_counts
                or not 0 <= int(f["segment_frame"]) < video_counts[f["segment"]]
            ):
                error(
                    "frame_timestamps", "saved frame references missing segment/frame"
                )
        frame_ids = {int(f["frame_id"]) for f in frames}
        frame_map = {int(f["frame_id"]): int(f["capture_host_ns"]) for f in frames}
        if not frames or len(frame_ids) != len(frames):
            error("frame_timestamps", "empty or duplicate frame IDs")
        if any(
            int(b["capture_host_ns"]) <= int(a["capture_host_ns"])
            for a, b in zip(frames, frames[1:])
        ):
            error("frame_timestamps", "timestamps must increase")
        for row in read_csv(root, "pose_landmarks.csv"):
            for key in (
                "x",
                "y",
                "z",
                "world_x",
                "world_y",
                "world_z",
                "visibility",
                "presence",
            ):
                if row[key] and not math.isfinite(float(row[key])):
                    error(f"pose_landmarks/{key}", "non-finite value")
            for key in ("visibility", "presence"):
                if row[key] and not 0 <= float(row[key]) <= 1:
                    error(f"pose_landmarks/{key}", "confidence outside 0..1")
            if (
                int(row["frame_id"]) not in frame_ids
                or not 0 <= int(row["landmark_id"]) < 33
            ):
                error("pose_landmarks", "unknown frame/landmark reference")
            if int(row["infer_host_ns"]) < int(row["capture_host_ns"]):
                error("pose_landmarks", "inference precedes capture")
        for row in read_csv(root, "pose_metrics.csv"):
            for key in ("elbow_angle_deg", "trunk_tilt_deg", "upperarm_delta_deg"):
                if row[key] and (
                    not math.isfinite(float(row[key]))
                    or not 0 <= float(row[key]) <= 180
                ):
                    error(f"pose_metrics/{key}", "angle outside finite 0..180 degrees")
            if frame_map.get(int(row["frame_id"])) != int(row["capture_host_ns"]):
                error("pose_metrics", "frame timestamp mismatch")
            if row["quality_mask"] == "ok" and not row["elbow_angle_deg"]:
                error("pose_metrics", "valid metric lacks angle")
            if int(row["infer_host_ns"]) < int(row["capture_host_ns"]):
                error("pose_metrics", "inference precedes capture")
        if (
            "labeled_samples.csv" in required
            and (root / "labeled_samples.csv").exists()
        ):
            labels = read_csv(root, "labeled_samples.csv")
            if len(labels) != len(samples):
                error("labeled_samples", "row count differs from EMG sample count")
            for label, sample in zip(labels, samples):
                if (
                    label["sample_index"] != sample["sample_index"]
                    or label["host_receive_ns"] != sample["host_receive_ns"]
                ):
                    error("labeled_samples", "EMG sample/time reference mismatch")
                for name, slot in (
                    ("biceps_env_adc", "s1_env"),
                    ("biceps_raw_adc", "s1_raw"),
                    ("triceps_env_adc", "s2_env"),
                    ("triceps_raw_adc", "s2_raw"),
                ):
                    if label[name] != sample[slot]:
                        error(
                            "labeled_samples/" + name, "EMG value differs from source"
                        )
                if label["pose_frame_id"]:
                    capture = frame_map.get(int(label["pose_frame_id"]))
                    if capture is None or capture != int(label["pose_capture_host_ns"]):
                        error(
                            "labeled_samples/pose_frame_id",
                            "unknown frame/time reference",
                        )
                    elif (
                        not 0
                        <= int(
                            label.get("measurement_host_ns") or label["host_receive_ns"]
                        )
                        - capture
                        <= m["protocol"]["max_pose_gap_ns"]
                    ):
                        error(
                            "labeled_samples/pose_frame_id",
                            "future or stale pose reference",
                        )
                if (
                    label["label_source"] != "mediapipe_pose"
                    or label["label_revision"] != "automatic"
                    or label["label_status"]
                    not in ("provisional", "alignment_unverified")
                ):
                    error(
                        "labeled_samples",
                        "acquisition labels must remain provisional MediaPipe labels",
                    )
                if label["pose_valid"] != "True" and label["phase"] != "unknown":
                    error("labeled_samples/phase", "missing tracking must be unknown")
        sets, attempts = effective_review(root)
        validate_annotations(sets, attempts)
        if (root / TRANSACTION).exists():
            error("review_transaction", "pending review save; recovery required")
        own = {s.set_id: s for s in sets}
        if not own or len(own) != len(sets):
            error("sets", "missing or duplicate set IDs")
        seen = set()
        for a in sorted(attempts, key=lambda a: a.start_ns):
            if a.attempt_id in seen:
                error("repetitions", "duplicate attempt ID")
            seen.add(a.attempt_id)
            record = own.get(a.set_id)
            if (
                record is None
                or record.end_ns is None
                or a.start_ns < record.start_ns
                or a.end_ns > record.end_ns
            ):
                error(
                    f"repetitions/{a.attempt_id}",
                    "outside set boundaries or missing set",
                )
            if any(t < a.start_ns or t > a.end_ns for t in a.phases.values()):
                error(f"repetitions/{a.attempt_id}", "phase outside attempt boundaries")
        history = review_history(root)
        expected_confirmed = (
            bool(history)
            and not (root / TRANSACTION).exists()
            and confirmation_valid(history[-1], history, evidence_context(root))
        )
        if bool(manifest.get("labels_confirmed")) != expected_confirmed:
            error(
                "review/labels_confirmed",
                "manifest and effective independent review disagree",
            )
        for s in sets:
            if s.failure_attempt_id and s.failure_attempt_id not in seen:
                error(f"sets/{s.set_id}/failure_attempt_id", "unknown attempt")
            if (
                s.review_status == "confirmed"
                and s.termination_reason == "technical_failure"
                and remaining(s, attempts, 0) is None
            ):
                error(
                    f"sets/{s.set_id}",
                    "confirmed failure lacks definite evidence/valid failed attempt",
                )
            if s.review_status == "confirmed":
                if not expected_confirmed:
                    error(
                        f"sets/{s.set_id}/review",
                        "two different reviewer revisions required",
                    )
                if not (
                    m["consent"]["video_storage"]
                    and m["consent"]["video_access"]
                    and s.objective_review
                ):
                    error(
                        f"sets/{s.set_id}/review",
                        "accessible objective evidence required",
                    )
            ordered = sorted(
                [a for a in attempts if a.set_id == s.set_id], key=lambda a: a.start_ns
            )
            if any(b.start_ns < a.end_ns for a, b in zip(ordered, ordered[1:])):
                error(f"sets/{s.set_id}/repetitions", "overlapping attempts")
        for row in read_csv(root, "events.csv"):
            if row["sample_index"] and not 0 <= int(row["sample_index"]) < len(samples):
                error("events/sample_index", "unknown sample reference")
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        error("schema", f"{type(exc).__name__}: {exc}")
    return errors


def inspect_session(root, quality_policy=None):
    """Keep the legacy integrity list API while exposing separate quality state."""
    root = Path(root)
    errors = validate_session(root)
    report = {"integrity_errors": errors, "quality": None}
    try:
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        policy = QualityPolicy.model_validate(
            quality_policy
            if quality_policy is not None
            else metadata.get("quality_policy", {})
        )
        samples = aligned_samples(
            read_csv(root, "samples.csv"),
            load_clock_mappings(root),
            max_uncertainty_ns=policy.maximum_uncertainty_ns,
        )
        sets, _ = effective_review(root)
        start = min(s.start_ns for s in sets)
        end = max(s.end_ns for s in sets if s.end_ns is not None)
        report["quality"] = window_quality(samples, start, end, policy)
    except (OSError, ValueError, KeyError, TypeError):
        report["quality"] = {"eligible": False, "reasons": ["quality_unavailable"]}
    return report
