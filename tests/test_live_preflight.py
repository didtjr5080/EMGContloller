from unittest.mock import Mock
from itertools import chain, repeat

import numpy as np

from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.ui.multimodal_panel import MultimodalDialog


def test_preview_keeps_updating_and_can_restart(qtbot, tmp_path):
    dialog = MultimodalDialog(DatasetStore(tmp_path))
    qtbot.addWidget(dialog)
    dialog.synthetic.setCurrentIndex(dialog.synthetic.findData(True))
    frames = []
    dialog.signals.result.connect(lambda result: frames.append(result) if "frame" in result else None)
    dialog._preflight()
    qtbot.waitUntil(lambda: len(frames) >= 3)
    qtbot.waitUntil(lambda: len(dialog.trace) >= 10)
    assert len(dialog.line1.getData()[0]) >= 10
    assert "아직 저장하지 않음" in dialog.status.text()
    assert dialog.preflight_thread.is_alive()
    dialog._preflight()  # Stop using the same button.
    qtbot.waitUntil(lambda: dialog.preflight_thread is None)
    before = len(frames)
    dialog._preflight()
    qtbot.waitUntil(lambda: len(frames) >= before + 2)
    dialog._invalidate()
    qtbot.waitUntil(lambda: dialog.preflight_thread is None)
    assert not dialog.preflight_ok


def test_live_camera_released_before_recording_and_on_close(qtbot, tmp_path, monkeypatch):
    import cv2
    import emg_collector.pose.pose_worker as pose_module
    import emg_collector.acquisition.esp32_serial as serial_module

    cap = Mock()
    cap.read.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
    pose = Mock()
    pose.infer.return_value = []
    conn = Mock()
    conn.readline.side_effect = chain([
        b"time_us,biceps_env,biceps_raw,triceps_env,triceps_raw\n",
        b"2000,100,200,300,400\n",
    ], repeat(b"4000,101,201,301,401\n"))
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: cap)
    monkeypatch.setattr(pose_module, "MediaPipePose", lambda *args: pose)
    monkeypatch.setattr(serial_module, "open_esp32_stream", lambda port: conn)
    dialog = MultimodalDialog(DatasetStore(tmp_path))
    qtbot.addWidget(dialog)
    frames = []
    dialog.signals.result.connect(lambda result: frames.append(result) if "frame" in result else None)
    dialog._preflight()
    qtbot.waitUntil(lambda: len(frames) >= 3)
    conn.close.assert_not_called()  # EMG stays live throughout preview.
    qtbot.waitUntil(lambda: len(dialog.trace) >= 2)
    assert dialog.preflight_ok  # Tracking loss must not block EMG recording.
    resumed = []

    def validate_after_release():
        cap.release.assert_called_once()
        pose.close.assert_called_once()
        conn.close.assert_called_once()  # Port is released before recording reopens it.
        resumed.append(True)
        raise ValueError("validation boundary")

    monkeypatch.setattr(dialog.participant, "build_models", validate_after_release)
    dialog.preflight_ok = True
    dialog._start()
    qtbot.waitUntil(lambda: bool(resumed))
    assert dialog.controller is None

    # Closing a running preview requests cancellation and closes after cleanup.
    dialog.synthetic.setCurrentIndex(dialog.synthetic.findData(True))
    dialog.show()
    dialog._preflight()
    qtbot.waitUntil(lambda: dialog.preflight_thread is not None)
    dialog.close()
    qtbot.waitUntil(lambda: dialog.preflight_thread is None)
    assert not dialog.isVisible()


def test_preview_serial_failure_explains_why_start_is_blocked(qtbot, tmp_path, monkeypatch):
    import cv2
    import emg_collector.pose.pose_worker as pose_module
    import emg_collector.acquisition.esp32_serial as serial_module

    cap = Mock()
    cap.read.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
    pose = Mock()
    pose.infer.return_value = []
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: cap)
    monkeypatch.setattr(pose_module, "MediaPipePose", lambda *args: pose)
    monkeypatch.setattr(serial_module, "open_esp32_stream", Mock(side_effect=OSError("COM3 disconnected")))
    dialog = MultimodalDialog(DatasetStore(tmp_path))
    qtbot.addWidget(dialog)
    dialog._preflight()
    qtbot.waitUntil(lambda: dialog.preflight_thread is None)
    assert not dialog.preflight_ok
    dialog._start()
    assert "COM3 disconnected" in dialog.status.text()
    assert dialog.controller is None


def test_preview_to_recording_saves_samples_and_keeps_plot_live(qtbot, tmp_path):
    import csv

    dialog = MultimodalDialog(DatasetStore(tmp_path))
    qtbot.addWidget(dialog)
    dialog.synthetic.setCurrentIndex(dialog.synthetic.findData(True))
    dialog.participant.age_spin.setValue(25)
    dialog.participant.height_spin.setValue(170)
    dialog.participant.consent_checkbox.setChecked(True)
    dialog.pose_consent.setChecked(True)
    dialog.placement.setText("test electrodes")
    dialog._preflight()
    qtbot.waitUntil(lambda: dialog.preflight_ok and len(dialog.trace) >= 10)
    dialog._start()
    qtbot.waitUntil(lambda: dialog.controller is not None)
    c = dialog.controller
    qtbot.waitUntil(lambda: c.sample_count >= 100 and len(dialog.trace) >= 20, timeout=5000)
    dialog._stop("voluntary_stop")
    qtbot.waitUntil(lambda: c.done.is_set(), timeout=8000)
    assert not c.errors
    with (c.writer.root / "samples.csv").open(encoding="utf-8", newline="") as fh:
        assert len(list(csv.DictReader(fh))) == c.sample_count
    dialog._tick()
    assert dialog.controller is None
