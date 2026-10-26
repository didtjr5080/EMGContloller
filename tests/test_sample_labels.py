import json

import pytest

from emg_collector.labeling.sample_labels import labeled_rows, write_labeled_samples
from emg_collector.multimodal.schema import Attempt, SetRecord


def sample(ns, index=0):
    return dict(
        sample_index=index,
        epoch_id=0,
        device_time_us=ns * 1000,
        unwrapped_time_us=ns * 1000,
        host_receive_ns=ns * 1_000_000,
        s1_env=100,
        s1_raw=200,
        s2_env=300,
        s2_raw=400,
    )


def pose(ns, index=0, quality="ok"):
    return dict(
        frame_id=index,
        capture_host_ns=ns * 1_000_000,
        infer_host_ns=ns * 1_000_000 + 50,
        elbow_angle_deg=100,
        trunk_tilt_deg=0,
        upperarm_delta_deg=0,
        quality_mask=quality,
    )


def test_both_muscles_receive_the_same_time_based_pose_label():
    record = SetRecord(
        set_id="SET1",
        arm="right",
        set_number=1,
        load_kg=5,
        start_ns=0,
        end_ns=1_000_000_000,
    )
    attempt = Attempt(
        attempt_id="A1",
        set_id="SET1",
        start_ns=100_000_000,
        end_ns=500_000_000,
        validity="valid",
        phases={
            "concentric": 100_000_000,
            "top": 300_000_000,
            "eccentric": 400_000_000,
        },
    )
    rows = list(
        labeled_rows(
            [sample(250), sample(450, 1)],
            [pose(200, 10), pose(400, 11)],
            [record],
            [attempt],
            100_000_000,
            synthetic=True,
            clock_mappings={
                "0": [
                    {
                        "mapping_version": "known",
                        "method": "synthetic_reference",
                        "status": "validated",
                        "uncertainty_ns": 0,
                        "offset_ns": 0,
                        "drift_ppm": 0,
                        "valid_from_device_us": 0,
                        "valid_to_device_us": 1_000_000,
                    }
                ]
            },
        )
    )
    assert [(r["biceps_raw_adc"], r["triceps_raw_adc"]) for r in rows] == [
        (200, 400),
        (200, 400),
    ]
    assert [(r["pose_frame_id"], r["phase"]) for r in rows] == [
        (10, "concentric"),
        (11, "eccentric"),
    ]
    assert all(
        r["attempt_validity"] == "valid" and r["label_source"] == "mediapipe_pose"
        for r in rows
    )
    assert all(r["label_status"] == "provisional" for r in rows)


@pytest.mark.parametrize(
    "time,quality", [(50, "ok"), (1000, "ok"), (150, "tracking_loss")]
)
def test_missing_future_stale_or_occluded_pose_is_unknown(time, quality):
    row = list(labeled_rows([sample(time)], [pose(100, quality=quality)], [], [], 100))[
        0
    ]
    assert (
        not row["pose_valid"]
        and row["phase"] == "unknown"
        and row["attempt_validity"] == "unknown"
    )


def test_legacy_muscle_data_cannot_be_relabelled_as_triceps(tmp_path):
    (tmp_path / "metadata.json").write_text(
        json.dumps({"schema_version": "2.0.0", "profile": "legacy_v2"})
    )
    with pytest.raises(ValueError, match="explicit v3"):
        write_labeled_samples(tmp_path)


def test_default_window_is_dual_emg_with_mediapipe(qtbot, tmp_path):
    from emg_collector.app import create_main_window
    from emg_collector.ui.multimodal_panel import MultimodalDialog
    from emg_collector.ui.main_window import MainWindow

    window = create_main_window(tmp_path / "v3")
    qtbot.addWidget(window)
    assert isinstance(window, MultimodalDialog)
    assert "MediaPipe" in window.start_button.text() and "삼두" in window.windowTitle()
    legacy = create_main_window(tmp_path / "v2", legacy_v2=True)
    qtbot.addWidget(legacy)
    assert isinstance(legacy, MainWindow)
