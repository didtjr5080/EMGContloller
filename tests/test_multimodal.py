"""Work-order failure fixtures; all data is synthetic and temporary."""

import json

import pytest

from emg_collector.multimodal.schema import ProfileParser, SetRecord, Attempt, remaining
from emg_collector.sync.clock_alignment import align_previous
from emg_collector.storage.multimodal_writer import MultimodalWriter, recover
from emg_collector.storage.training_export import participant_splits, causal_window
from emg_collector.labeling.repetitions import RepetitionDetector
from emg_collector.protocols import PilotProtocol


def test_profiles_never_relabel_legacy():
    legacy = ProfileParser("legacy_v2")
    modern = ProfileParser("biceps_triceps_v3")
    assert legacy.channels[2].muscle == "brachioradialis"
    assert modern.channels[2].muscle == "triceps"
    with pytest.raises(ValueError, match="header"):
        modern.parse("time_us,biceps_env,biceps_raw,brachio_env,brachio_raw", 1)


def reviewed_set(reason="technical_failure"):
    attempts = [
        Attempt(
            attempt_id=f"A{i}",
            set_id="SET1",
            start_ns=i * 100,
            end_ns=(i + 1) * 100,
            validity="valid",
        )
        for i in range(15)
    ]
    attempts.append(
        Attempt(
            attempt_id="FAIL",
            set_id="SET1",
            start_ns=1600,
            end_ns=1700,
            validity="invalid",
            reasons=["rom"],
        )
    )
    return (
        SetRecord(
            set_id="SET1",
            arm="right",
            set_number=1,
            load_kg=5,
            start_ns=0,
            end_ns=1700,
            termination_reason=reason,
            failure_attempt_id="FAIL" if reason == "technical_failure" else None,
            review_status="confirmed",
            objective_review=True,
        ),
        attempts,
    )


def test_censored_is_null_and_exact_is_n_minus_k():
    record, attempts = reviewed_set("voluntary_stop")
    assert remaining(record, attempts, 10) is None
    record, attempts = reviewed_set()
    assert [remaining(record, attempts, k) for k in (10, 14, 15)] == [5, 1, 0]


@pytest.mark.parametrize(
    "reason",
    [
        "voluntary_stop",
        "pain_discomfort",
        "equipment_failure",
        "tracking_failure",
        "protocol_deviation",
        "planned_stop",
        "other",
    ],
)
def test_every_nonfailure_termination_is_censored(reason):
    record, attempts = reviewed_set(reason)
    assert remaining(record, attempts, 15) is None


def test_unknown_before_failed_attempt_blocks_exact_label():
    record, attempts = reviewed_set()
    attempts[0].validity = "unknown"
    assert remaining(record, attempts, 10) is None


def test_mirroring_preserves_aspect_corrected_angle():
    from emg_collector.pose.metrics import metrics

    points = {
        12: {"x": 0.5, "y": 0.2, "visibility": 1},
        14: {"x": 0.5, "y": 0.5, "visibility": 1},
        16: {"x": 0.7, "y": 0.5, "visibility": 1},
        24: {"x": 0.5, "y": 0.9, "visibility": 1},
    }
    mirrored = {i: {**p, "x": 1 - p["x"]} for i, p in points.items()}
    assert metrics(points, 640, 480, "right")["elbow_angle_deg"] == pytest.approx(90)
    assert (
        metrics(points, 640, 480, "right")["elbow_angle_deg"]
        == metrics(mirrored, 640, 480, "right")["elbow_angle_deg"]
    )


def test_boundary_jitter_never_counts_multiple_repetitions():
    detector = RepetitionDetector(PilotProtocol())
    for i, angle in enumerate([170] * 4 + [149, 151, 148, 152] * 5 + [170] * 4):
        detector.update(i * 30_000_000, angle, 0, 0, True)
    assert detector.attempts == []


def test_time_join_not_row_join():
    frames = [{"capture_host_ns": i * 33_333_333, "frame_id": i} for i in range(30)]
    assert align_previous(frames, 500_000_000, 40_000_000)["frame_id"] == 15
    assert align_previous(frames, 2_000_000_000, 40_000_000) is None


def test_occlusion_is_unknown():
    detector = RepetitionDetector(PilotProtocol())
    detector.update(0, 170, 0, 0, True)
    detector.update(100_000_000, 130, 0, 0, True)
    detector.update(200_000_000, None, None, None, False)
    attempt = detector.finish(300_000_000)
    assert attempt.validity == "unknown"


def test_split_before_windows_and_no_future():
    assignments = participant_splits(["P-AAAA", "P-BBBB", "P-AAAA"], 42)
    assert len(assignments) == 2
    rows = [{"host_receive_ns": i} for i in range(12)]
    assert max(r["host_receive_ns"] for r in causal_window(rows, 10, 10)) == 10


def test_unfinished_video_cannot_be_complete(tmp_path):
    writer = MultimodalWriter(tmp_path / "S", {"synthetic": True}, video_required=True)
    writer.close_incomplete()
    manifest = recover(tmp_path / "S")
    assert manifest["status"] == "incomplete"
    assert (
        json.loads((tmp_path / "S" / "completion_manifest.json").read_text())["status"]
        != "complete"
    )
