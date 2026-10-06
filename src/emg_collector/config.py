"""Fixed hardware/protocol constants and app-wide defaults.

These values mirror the reference ESP32 firmware in
``firmware/emg_streamer_reference.ino``. They must not be changed without
an explicit request, since the parser and dataset schema depend on them.
"""

from __future__ import annotations

APP_VERSION = "0.2.0"
SCHEMA_VERSION = "2.0.0"

DEFAULT_BAUD_RATE = 460800
TARGET_SAMPLE_RATE_HZ = 500
TARGET_SAMPLE_INTERVAL_US = 2000

# Two MyoWare 2.0 sensors: biceps (envelope + raw) and brachioradialis
# (envelope + raw), 4 ADC channels in total per sample.
SERIAL_HEADER_LINE = "time_us,biceps_env,biceps_raw,brachio_env,brachio_raw"
SERIAL_FIELD_COUNT = 5  # time_us + 4 ADC channels

ADC_RESOLUTION_BITS = 12
ADC_MIN_VALUE = 0
ADC_MAX_VALUE = 4095

BICEPS_ENV_PIN = 33
BICEPS_RAW_PIN = 34
BRACHIO_ENV_PIN = 32
BRACHIO_RAW_PIN = 35

# 32-bit unsigned micros() rollover point.
MICROS_WRAP_MODULUS = 2**32

# How close a raw timestamp must be to the 32-bit boundary (on either side)
# to be classified as a genuine micros() rollover rather than a device
# reboot. See acquisition/time_unwrapper.py for the full decision rule.
WRAP_EDGE_WINDOW_US = 10_000_000  # 10 s

# A backward jump larger than this, away from the wrap boundary, is treated
# as a device reboot rather than sample jitter.
REBOOT_DROP_THRESHOLD_US = 50_000_000  # 50 s

# Batch delivery from the serial worker to the rest of the app.
BATCH_INTERVAL_MS = 40
BATCH_MAX_SAMPLES = 25

# Bounded inter-thread queue capacity (samples).
SAMPLE_QUEUE_MAX_SIZE = 20_000

# Missing-sample estimation: a gap between consecutive *unwrapped* device
# timestamps larger than this multiple of the target interval is treated as
# one or more dropped samples. This is an estimate, not a certainty: it
# cannot fully distinguish real serial/radio loss from ESP32 scheduling
# jitter.
GAP_MULTIPLIER_THRESHOLD = 1.5

DEFAULT_LABELS = [
    "rest",
    "flexion",
    "extension",
    "isometric_hold",
    "fatigue",
    "recovery",
    "unknown",
]
DEFAULT_LABEL = "unknown"

PLOT_WINDOW_SECONDS_DEFAULT = 8.0
PLOT_REFRESH_HZ = 25

SAMPLES_CSV_HEADER = [
    "sample_index",
    "device_time_us",
    "device_time_us_unwrapped",
    "elapsed_s",
    "host_elapsed_s",
    "biceps_env_adc",
    "biceps_raw_adc",
    "brachio_env_adc",
    "brachio_raw_adc",
    "label",
]

EVENTS_CSV_HEADER = [
    "event_index",
    "sample_index",
    "device_time_us_unwrapped",
    "elapsed_s",
    "event_type",
    "label",
    "note",
]

PARTICIPANTS_PRIVATE_HEADER = ["participant_id", "name", "created_at_utc"]

PARTICIPANTS_PUBLIC_HEADER = [
    "participant_id",
    "age",
    "sex",
    "height_cm",
    "weight_kg",
    "dominant_arm",
    "exercise_sessions_per_week",
    "exercise_minutes_per_week",
    "days_since_last_exercise",
    "participant_notes",
]

SESSIONS_CSV_HEADER = [
    "session_id",
    "participant_id",
    "start_time_utc",
    "end_time_utc",
    "duration_s",
    "muscle",
    "arm",
    "exercise",
    "load_kg",
    "set_number",
    "target_repetitions",
    "pre_fatigue_score",
    "pain_score",
    "expected_sample_rate_hz",
    "actual_sample_rate_hz",
    "valid_samples",
    "status",
    "session_path",
]

SESSION_STATUS_COMPLETE = "complete"
SESSION_STATUS_INCOMPLETE = "incomplete"
SESSION_STATUS_RECOVERED = "recovered"
