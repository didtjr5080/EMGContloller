from unittest.mock import Mock

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
    conn.readline.side_effect = [
        b"time_us,biceps_env,biceps_raw,triceps_env,triceps_raw\n",
        b"2000,100,200,300,400\n",
    ]
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: cap)
    monkeypatch.setattr(pose_module, "MediaPipePose", lambda *args: pose)
    monkeypatch.setattr(serial_module, "open_esp32_stream", lambda port: conn)
    dialog = MultimodalDialog(DatasetStore(tmp_path))
    qtbot.addWidget(dialog)
    frames = []
    dialog.signals.result.connect(lambda result: frames.append(result) if "frame" in result else None)
    dialog._preflight()
    qtbot.waitUntil(lambda: len(frames) >= 3)
    conn.close.assert_called_once()  # Preview does not hold the serial port.
    assert not dialog.preflight_ok  # Missing pose must still block recording.
    resumed = []

    def validate_after_release():
        cap.release.assert_called_once()
        pose.close.assert_called_once()
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
