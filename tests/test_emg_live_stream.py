from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_review_fix_boundaries import controller
from emg_collector.acquisition.serial_worker import SerialPortLineSource
from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.ui.multimodal_panel import MultimodalDialog


def test_serial_timeout_preserves_header_and_sample_fragments():
    port = Mock(is_open=True)
    port.readline.side_effect = [
        b"\xff\x00\xf8boot bytes time_us,biceps_env,biceps_raw,", b"", b"triceps_env,triceps_raw\n",
        b"2000,100,200,", b"300,400\n",
    ]
    source = SerialPortLineSource(port)
    assert [source.next_line() for _ in range(5)] == [
        "", "", "time_us,biceps_env,biceps_raw,triceps_env,triceps_raw\n",
        "", "2000,100,200,300,400\n",
    ]


@pytest.mark.parametrize("wrong_profile", [False, True])
def test_recording_waits_for_header_and_delivers_all_plot_samples(
    tmp_path, monkeypatch, wrong_profile
):
    clock = SimpleNamespace(ns=0)
    c = controller(tmp_path, clock)
    written = []
    c.writer = SimpleNamespace(submit=lambda name, row: written.append((name, row)))
    second = b"brachio" if wrong_profile else b"triceps"
    lines = iter([
        b"9000,100,200,300,400\n",  # stale row before reset
        b"rst:0x1, booting\n",
        b"time_us,biceps_env,biceps_raw," + second + b"_env," + second + b"_raw\n",
        b"0,100,200,300,400\n", b"2000,101,201,301,401\n",
    ])

    def read():
        clock.ns += 2_000_000
        line = next(lines, None)
        if line is None:
            c.stop("voluntary_stop")
            return b""
        return line

    port = Mock(is_open=True)
    port.readline.side_effect = read
    monkeypatch.setattr(
        "emg_collector.acquisition.esp32_serial.open_esp32_stream",
        lambda *args: port,
    )
    c._serial()
    port.close.assert_called_once()
    if wrong_profile:
        assert c.sample_count == 0
        assert "header mismatch" in c.errors[0]
        return
    assert not c.errors
    assert c.sample_count == 2
    assert len([row for name, row in written if name == "samples.csv"]) == 2
    samples = c.preview()["emg_samples"]
    assert [s["s1_raw"] for s in samples] == [200, 201]
    assert c.preview()["emg_samples"] == []  # no duplicated points on idle ticks


def test_plot_displays_whole_batch_once(qtbot, tmp_path):
    dialog = MultimodalDialog(DatasetStore(tmp_path))
    qtbot.addWidget(dialog)
    samples = [
        {"host_receive_ns": 1_000_000_000 + i * 2_000_000,
         "s1_raw": 200 + i, "s2_raw": 400 - i}
        for i in range(50)
    ]
    c = Mock(arm="right", errors=[], phase="recording", sample_count=50,
             frame_count=0, inference_skipped=0)
    c.done.is_set.return_value = False
    c.preview.side_effect = [{"emg_samples": samples}, {"emg_samples": []}]
    dialog.controller = c
    dialog._tick()
    dialog._tick()
    x, y = dialog.line1.getData()
    assert len(x) == 50
    assert list(y) == list(range(200, 250))
    assert x[0] == 0 and x[-1] == pytest.approx(0.098)
    dialog.controller = None


def test_camera_drops_duplicate_capture_times_without_stopping(tmp_path, monkeypatch):
    from queue import Queue
    from threading import Event
    import numpy as np
    import cv2
    from emg_collector.acquisition.camera_worker import capture_loop

    times = iter([100, 100, 90, 200])
    saved = []
    c = SimpleNamespace(
        synthetic=False, camera_index=0,
        consent=SimpleNamespace(video_storage=False), stop_event=Event(),
        clock_ns=lambda: next(times), pose_queue=Queue(),
        inference_skipped=0, frame_count=0, frame_times=[], fail=Mock(),
        writer=SimpleNamespace(submit=lambda name, row: saved.append((name, row))),
    )
    cap = Mock()
    frame = np.zeros((48, 64, 3), dtype=np.uint8)

    def read():
        if len(saved) == 1 and c.inference_skipped == 2:
            c.stop_event.set()
        return True, frame

    cap.read.side_effect = read
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: cap)
    capture_loop(c)
    assert [row["capture_host_ns"] for _, row in saved] == [100, 200]
    assert c.frame_count == 2 and c.inference_skipped == 2
    c.fail.assert_not_called()
    cap.release.assert_called_once()
