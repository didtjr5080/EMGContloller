"""Open an ESP32 stream and request its boot-time profile header."""

import time

import serial


def open_esp32_stream(port: str, baud: int = 460800):
    conn = serial.Serial(port, baud, timeout=0.5)
    try:
        # Keep GPIO0 released, pulse EN, and discard only pre-reset bytes.
        # Do not flush after releasing EN: that could discard the new header.
        conn.dtr = False
        conn.rts = True
        time.sleep(0.15)
        conn.reset_input_buffer()
        conn.rts = False
        return conn
    except BaseException:
        conn.close()
        raise
