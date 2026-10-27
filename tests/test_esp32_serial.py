from unittest.mock import Mock, patch

import pytest

from emg_collector.acquisition.esp32_serial import open_esp32_stream


def test_reset_preserves_boot_header():
    events = []

    class Port:
        def __setattr__(self, name, value):
            events.append((name, value))

        def reset_input_buffer(self):
            events.append("flush")

    conn = Port()
    with patch("emg_collector.acquisition.esp32_serial.serial.Serial", return_value=conn), patch(
        "emg_collector.acquisition.esp32_serial.time.sleep", side_effect=lambda seconds: events.append(("sleep", seconds))
    ):
        assert open_esp32_stream("COM3") is conn
    assert events == [("dtr", False), ("rts", True), ("sleep", 0.15), "flush", ("rts", False)]


def test_reset_failure_closes_port():
    conn = Mock()
    conn.reset_input_buffer.side_effect = OSError("disconnected")
    with patch("emg_collector.acquisition.esp32_serial.serial.Serial", return_value=conn), patch(
        "emg_collector.acquisition.esp32_serial.time.sleep"
    ):
        with pytest.raises(OSError, match="disconnected"):
            open_esp32_stream("COM3")
    conn.close.assert_called_once()
