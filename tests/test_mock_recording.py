"""Mock-mode tests: disconnect handling (9.4) and a full 10s integration
recording (9.6). Both avoid waiting on a real wall clock: the mock source
is driven directly, unpaced, rather than through the realtime-paced wrapper
used by the live UI.
"""

from __future__ import annotations

import csv
import json

from emg_collector.acquisition.mock_source import MockSampleSource
from emg_collector.acquisition.parser import LineParser
from emg_collector.acquisition.serial_worker import SerialWorker
from emg_collector.acquisition.time_unwrapper import TimeUnwrapper
from emg_collector.config import DEFAULT_LABEL, TARGET_SAMPLE_INTERVAL_US
from emg_collector.models import EventRecord, EventType, SampleRecord
from emg_collector.quality.metrics import QualityAccumulator
from emg_collector.storage.dataset_store import DatasetStore


class _SilentThenDisconnectSource:
    """Simulates a real serial port that is open but sends nothing usable
    (wrong baud rate, wrong device, idle port): every read times out and
    returns an empty line, until a fixed number of reads, then disconnects.
    """

    def __init__(self, empty_reads_before_disconnect: int) -> None:
        self._remaining = empty_reads_before_disconnect

    def next_line(self) -> str:
        if self._remaining <= 0:
            from emg_collector.acquisition.mock_source import MockSourceDisconnected

            raise MockSourceDisconnected("no data ever arrived")
        self._remaining -= 1
        return ""


def test_diagnostics_reported_even_when_zero_valid_samples_arrive(qtbot):
    """Regression test: a connection that never parses a single valid
    sample must still surface diagnostics (so the UI doesn't look frozen
    with no feedback at all -- a real bug found via a user report that the
    plot and status panel stayed completely blank while "connected")."""
    source = _SilentThenDisconnectSource(empty_reads_before_disconnect=5)
    worker = SerialWorker(source, batch_interval_ms=0, batch_max_samples=1000)

    diagnostics_events = []
    batches = []
    worker.diagnostics_updated.connect(diagnostics_events.append)
    worker.batch_ready.connect(batches.append)

    with qtbot.waitSignal(worker.finished, timeout=2000):
        worker.run()

    assert len(diagnostics_events) >= 1
    assert diagnostics_events[-1]["valid_rows"] == 0
    assert diagnostics_events[-1]["blank_lines"] == 5
    assert batches == []  # never a valid sample, so never a batch


def test_mock_source_lines_parse_as_valid_samples():
    source = MockSampleSource(seed=1)
    parser = LineParser()

    for _ in range(50):
        line = source.next_line()
        sample = parser.parse_line(line)
        assert sample is not None

    assert parser.diagnostics.valid_rows == 50
    assert parser.diagnostics.malformed_rows == 0


def test_disconnect_mid_recording_preserves_batches_and_emits_status(qtbot):
    source = MockSampleSource(seed=2)
    source.inject_missing_samples(0)
    # Disconnect after a handful of samples.
    disconnect_after = 8
    original_next_line = source.next_line
    count = {"n": 0}

    def counting_next_line():
        if count["n"] == disconnect_after:
            source.trigger_disconnect()
        count["n"] += 1
        return original_next_line()

    source.next_line = counting_next_line  # type: ignore[method-assign]

    worker = SerialWorker(source, batch_interval_ms=100_000, batch_max_samples=1_000_000)

    received_batches = []
    disconnect_messages = []
    worker.batch_ready.connect(received_batches.append)
    worker.disconnected.connect(disconnect_messages.append)

    with qtbot.waitSignal(worker.finished, timeout=2000):
        worker.run()

    assert len(disconnect_messages) == 1
    total_samples = sum(len(b) for b in received_batches)
    assert total_samples == disconnect_after  # all pre-disconnect samples preserved
    assert worker._running is False


def test_10s_mock_integration_matches_dataset_schema(tmp_path):
    target_hz = 1_000_000 / TARGET_SAMPLE_INTERVAL_US
    duration_s = 10.0
    expected_samples = int(target_hz * duration_s)

    source = MockSampleSource(seed=3, baseline_adc=1800)
    parser = LineParser()
    unwrapper = TimeUnwrapper()
    quality = QualityAccumulator()

    store = DatasetStore(tmp_path / "dataset")
    session_id = "S_integration"
    writer = store.create_session_writer(session_id)

    first_elapsed_us: int | None = None
    label = DEFAULT_LABEL
    label_switch_index = expected_samples // 2
    event_index = 0

    records: list[SampleRecord] = []
    for i in range(expected_samples):
        if i == label_switch_index:
            label = "flexion"
            writer.write_event(
                EventRecord(
                    event_index=event_index,
                    sample_index=i,
                    device_time_us_unwrapped=0,
                    elapsed_s=0.0,
                    event_type=EventType.label_change,
                    label=label,
                    note="",
                )
            )
            event_index += 1

        line = source.next_line()
        parsed = parser.parse_line(line)
        assert parsed is not None
        result = unwrapper.unwrap(parsed.time_us)
        if first_elapsed_us is None:
            first_elapsed_us = result.value_us
        elapsed_s = (result.value_us - first_elapsed_us) / 1_000_000

        quality.record_sample(
            result.value_us, parsed.biceps_env, parsed.biceps_raw, parsed.brachio_env, parsed.brachio_raw
        )

        records.append(
            SampleRecord(
                sample_index=i,
                device_time_us=parsed.time_us,
                device_time_us_unwrapped=result.value_us,
                elapsed_s=elapsed_s,
                host_elapsed_s=elapsed_s,
                biceps_env_adc=parsed.biceps_env,
                biceps_raw_adc=parsed.biceps_raw,
                brachio_env_adc=parsed.brachio_env,
                brachio_raw_adc=parsed.brachio_raw,
                label=label,
            )
        )

    writer.write_samples(records)
    samples_path, events_path = writer.finalize()

    store.append_session_row(
        {
            "session_id": session_id,
            "participant_id": "P-TEST",
            "start_time_utc": "2026-01-01T00:00:00+00:00",
            "end_time_utc": "2026-01-01T00:00:10+00:00",
            "duration_s": duration_s,
            "muscle": "biceps",
            "arm": "left",
            "exercise": "flexion",
            "expected_sample_rate_hz": target_hz,
            "actual_sample_rate_hz": quality.actual_sample_rate_hz(duration_s),
            "valid_samples": quality.valid_samples,
            "status": "complete",
            "session_path": str(store.session_dir(session_id)),
        }
    )
    store.write_session_metadata(
        session_id,
        {"schema_version": "2.0.0", "session_id": session_id, "participant_id": "P-TEST"},
    )
    store.write_session_quality(session_id, quality.to_dict(duration_s))

    # -- assertions -----------------------------------------------------

    assert quality.valid_samples == expected_samples

    with open(samples_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == expected_samples

    sample_indices = [int(r["sample_index"]) for r in rows]
    assert sample_indices == list(range(expected_samples))

    unwrapped_times = [int(r["device_time_us_unwrapped"]) for r in rows]
    assert unwrapped_times == sorted(unwrapped_times)
    assert len(set(unwrapped_times)) == len(unwrapped_times)

    labels_seen = {r["label"] for r in rows}
    assert labels_seen == {DEFAULT_LABEL, "flexion"}
    assert rows[label_switch_index]["label"] == "flexion"
    assert rows[label_switch_index - 1]["label"] == DEFAULT_LABEL

    with open(events_path, newline="", encoding="utf-8") as fh:
        event_rows = list(csv.DictReader(fh))
    assert len(event_rows) == 1
    assert event_rows[0]["event_type"] == "label_change"

    metadata = json.loads((store.session_dir(session_id) / "metadata.json").read_text())
    quality_json = json.loads((store.session_dir(session_id) / "quality.json").read_text())
    assert metadata["session_id"] == session_id
    assert quality_json["valid_samples"] == expected_samples

    assert not (store.session_dir(session_id) / "samples.csv.part").exists()
    assert not (store.session_dir(session_id) / "events.csv.part").exists()

    with open(store.root / "sessions.csv", newline="", encoding="utf-8") as fh:
        sessions_rows = list(csv.DictReader(fh))
    assert len(sessions_rows) == 1
    assert sessions_rows[0]["session_id"] == session_id
