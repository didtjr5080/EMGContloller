"""EMG 2-channel (biceps + brachioradialis) raw serial logger.

Reads "time_us,biceps_env,biceps_raw,brachio_env,brachio_raw" lines from
the ESP32 over serial and writes them to CSV exactly as received. No
filtering, RMS, or frequency-domain processing is applied here -- this
script only captures raw ADC values for later offline analysis (sampling
rate / sample loss / timestamp duplication / clipping checks).

Arduino side is unchanged; only this Python logger was updated for the
second MyoWare channel. Standalone script (does not depend on the
emg_collector package) -- run directly with `python scripts/emg_2ch_logger.py`.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import serial

COM_PORT = "COM3"
BAUD_RATE = 460800
DATA_DIR = Path(r"C:\EMG\data")
CSV_HEADER = ["time_us", "biceps_env", "biceps_raw", "brachio_env", "brachio_raw"]
EXPECTED_FIELD_COUNT = 5
FLUSH_EVERY_N_SAMPLES = 100
STATUS_EVERY_N_SAMPLES = 500


def make_output_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DATA_DIR / f"emg_2ch_{timestamp}.csv"


def parse_line(line: str) -> tuple[int, int, int, int, int] | None:
    parts = line.strip().split(",")
    if len(parts) != EXPECTED_FIELD_COUNT:
        return None
    try:
        return tuple(int(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def main() -> None:
    output_path = make_output_path()
    print(f"[INFO] 저장 파일: {output_path}")
    print(f"[INFO] 포트: {COM_PORT} @ {BAUD_RATE} baud")

    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    sample_count = 0

    try:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)
            f.flush()

            print("[INFO] 측정 시작. Ctrl+C로 종료하세요.")

            while True:
                try:
                    raw_line = ser.readline().decode("utf-8", errors="replace")
                except serial.SerialException as exc:
                    print(f"[ERROR] 시리얼 읽기 오류: {exc}")
                    break

                if not raw_line:
                    continue  # read timeout, no data yet

                parsed = parse_line(raw_line)
                if parsed is None:
                    continue  # malformed/short line: skip, do not save

                time_us, biceps_env, biceps_raw, brachio_env, brachio_raw = parsed
                writer.writerow(parsed)
                sample_count += 1

                if sample_count % FLUSH_EVERY_N_SAMPLES == 0:
                    f.flush()

                if sample_count % STATUS_EVERY_N_SAMPLES == 0:
                    print(
                        f"{sample_count} samples | "
                        f"이두 ENV={biceps_env} RAW={biceps_raw} | "
                        f"상완요골 ENV={brachio_env} RAW={brachio_raw}"
                    )

    except KeyboardInterrupt:
        print(f"\n[INFO] Ctrl+C 감지. 측정 종료. 총 {sample_count} samples 저장됨.")
    finally:
        if ser.is_open:
            ser.close()
            print("[INFO] Serial port 닫음.")
        print(f"[INFO] 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
