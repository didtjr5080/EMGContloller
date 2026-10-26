"""Fast deterministic example with MJPG video and two synthetic review revisions."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from emg_collector.labeling.review import append_review
from emg_collector.models import ParticipantPublic
from emg_collector.multimodal.schema import Attempt, SetRecord, channels
from emg_collector.protocols import PilotProtocol
from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.storage.multimodal_writer import MultimodalWriter
from emg_collector.sync.clock_alignment import fit_clock


def create(root):
    import cv2
    import numpy as np

    root = Path(root)
    if root.exists():
        raise FileExistsError(root)
    store = DatasetStore(root)
    participant = ParticipantPublic(
        participant_id="P-SYNTH01",
        age=30,
        height_cm=175,
        exercise_sessions_per_week=0,
        exercise_minutes_per_week=0,
        days_since_last_exercise=0,
    )
    store.register_participant(None, participant)
    origin = 1_000_000_000
    metadata = {
        "schema_version": "3.0.0",
        "session_id": "M_SYNTH01",
        "participant_id": participant.participant_id,
        "participant": participant.model_dump(mode="json"),
        "visit_id": "V_SYNTH01",
        "visit": {"visit_id": "V_SYNTH01"},
        "profile": "biceps_triceps_v3",
        "labeling": {
            "source": "mediapipe_pose",
            "sample_labels_file": "labeled_samples.csv",
            "mode": "retrospective_provisional",
        },
        "channels": [c.model_dump() for c in channels("biceps_triceps_v3")],
        "start_host_ns": origin,
        "synthetic": True,
        "consent": {
            "research": True,
            "pose_coordinates": True,
            "video_storage": True,
            "video_access": True,
            "video_export": False,
        },
        "protocol": PilotProtocol().model_dump(),
    }
    writer = MultimodalWriter(
        store.session_dir("M_SYNTH01"), metadata, video_required=True, queue_size=100000
    )
    observations = []
    for i in range(24001):
        device = i * 2000
        host = origin + device * 1000
        writer.submit(
            "samples.csv",
            {
                "sample_index": i,
                "epoch_id": 0,
                "device_time_us": device,
                "unwrapped_time_us": device,
                "host_receive_ns": host,
                "s1_env": 500,
                "s1_raw": 2000 + i % 100,
                "s2_env": 400,
                "s2_raw": 2100 - i % 100,
            },
        )
        if i % 500 == 0:
            observations.append((device, host))
    (writer.root / "video").mkdir()
    encoder = cv2.VideoWriter(
        str(writer.root / "video" / "segment_000.avi"),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (320, 240),
    )
    if not encoder.isOpened():
        raise RuntimeError("MJPG encoder unavailable")
    for i in range(481):
        host = origin + i * 100_000_000
        image = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(
            image,
            f"SYNTHETIC {i}",
            (20, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            1,
        )
        encoder.write(image)
        writer.submit(
            "frame_timestamps.csv",
            {
                "frame_id": i,
                "capture_host_ns": host,
                "timestamp_source": "synthetic_host",
                "segment": "segment_000.avi",
                "segment_frame": i,
                "saved": True,
                "inference_submitted": True,
            },
        )
        writer.submit(
            "pose_metrics.csv",
            {
                "frame_id": i,
                "capture_host_ns": host,
                "infer_host_ns": host + 10_000_000,
                "arm": "right",
                "elbow_angle_deg": 170 - 130 * (1 - abs(2 * (i % 30) / 30 - 1)),
                "trunk_tilt_deg": 0,
                "upperarm_delta_deg": 0,
                "quality_mask": "ok",
            },
        )
        for j in range(33):
            writer.submit(
                "pose_landmarks.csv",
                {
                    "frame_id": i,
                    "landmark_id": j,
                    "capture_host_ns": host,
                    "infer_host_ns": host + 10_000_000,
                    "x": 0.5,
                    "y": 0.5,
                    "z": 0,
                    "world_x": None,
                    "world_y": None,
                    "world_z": None,
                    "visibility": 1,
                    "presence": 1,
                    "validity": "synthetic",
                },
            )
    encoder.release()
    attempts = []
    for i in range(16):
        a = Attempt(
            attempt_id=f"A{i+1}",
            set_id="SET1",
            start_ns=origin + i * 3_000_000_000,
            end_ns=origin + (i + 1) * 3_000_000_000,
            validity="valid" if i < 15 else "invalid",
            reasons=[] if i < 15 else ["rom"],
            rom_deg=130 if i < 15 else 40,
            phases={
                "concentric": origin + i * 3_000_000_000,
                **(
                    {
                        "top": origin + i * 3_000_000_000 + 1_000_000_000,
                        "eccentric": origin + i * 3_000_000_000 + 1_500_000_000,
                        "completed": origin + (i + 1) * 3_000_000_000,
                    }
                    if i < 15
                    else {}
                ),
            },
        )
        attempts.append(a)
        writer.submit("repetitions.csv", a.model_dump(mode="json"))
    record = SetRecord(
        set_id="SET1",
        arm="right",
        set_number=1,
        load_kg=5,
        start_ns=origin,
        end_ns=origin + 48_000_000_000,
        termination_reason="technical_failure",
        failure_attempt_id="A16",
    )
    writer.submit("sets.csv", record.model_dump(mode="json"))
    writer.finalize(
        {"method": "synthetic_known_clock", "epochs": {"0": fit_clock(observations)}},
        {
            "synthetic": True,
            "valid_samples": 24001,
            "frame_count": 481,
            "actual_sample_rate_hz": 500,
            "actual_fps": 10,
        },
    )
    append_review(
        writer.root,
        "SYNTH-reviewer-1",
        "synthetic fixture assessment",
        [record],
        attempts,
        True,
    )
    append_review(
        writer.root,
        "SYNTH-reviewer-2",
        "independent synthetic fixture agreement",
        [record],
        attempts,
        True,
    )
    store.append_session_row(
        {
            "session_id": "M_SYNTH01",
            "participant_id": participant.participant_id,
            "status": "complete",
        }
    )
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        print(create(args.output))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
