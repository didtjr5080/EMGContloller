import csv

from emg_collector.models import SampleRecord
from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.storage.session_writer import SessionWriter


def make_sample(i: int) -> SampleRecord:
    return SampleRecord(
        sample_index=i,
        device_time_us=i * 2000,
        device_time_us_unwrapped=i * 2000,
        elapsed_s=i * 0.002,
        host_elapsed_s=i * 0.002,
        env_adc=100,
        raw_adc=200,
        label="rest",
    )


def test_clean_finalize_produces_final_csv_with_no_part_left(tmp_path):
    writer = SessionWriter(tmp_path / "S1")
    writer.write_samples([make_sample(i) for i in range(10)])
    samples_final, events_final = writer.finalize()

    assert samples_final.exists()
    assert events_final.exists()
    assert not (tmp_path / "S1" / "samples.csv.part").exists()
    assert not (tmp_path / "S1" / "events.csv.part").exists()

    with open(samples_final, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) == 11  # header + 10 samples


def test_crash_mid_write_leaves_part_file_and_prior_sessions_untouched(tmp_path):
    dataset_root = tmp_path / "dataset"
    store = DatasetStore(dataset_root)

    good_writer = store.create_session_writer("S_good")
    good_writer.write_samples([make_sample(i) for i in range(5)])
    good_writer.finalize()

    crashing_writer = store.create_session_writer("S_crash")
    crashing_writer.write_samples([make_sample(i) for i in range(100)])
    crashing_writer.close_without_finalize()  # simulate abrupt process death

    # The prior, cleanly-finalized session must be untouched.
    assert (store.session_dir("S_good") / "samples.csv").exists()
    with open(store.session_dir("S_good") / "samples.csv", newline="", encoding="utf-8") as fh:
        assert len(list(csv.reader(fh))) == 6

    # The crashed session must have left a recoverable .part file with all
    # flushed rows, and no samples.csv yet.
    part_path = store.session_dir("S_crash") / "samples.csv.part"
    assert part_path.exists()
    assert not (store.session_dir("S_crash") / "samples.csv").exists()
    with open(part_path, newline="", encoding="utf-8") as fh:
        assert len(list(csv.reader(fh))) == 101  # header + 100 samples


def test_app_restart_detects_incomplete_session_and_recovers_it(tmp_path):
    dataset_root = tmp_path / "dataset"
    store = DatasetStore(dataset_root)

    crashing_writer = store.create_session_writer("S_crash")
    crashing_writer.write_samples([make_sample(i) for i in range(100)])
    crashing_writer.close_without_finalize()

    # Simulate a fresh app process reopening the same dataset root.
    reopened_store = DatasetStore(dataset_root)
    incomplete = reopened_store.find_incomplete_sessions()
    assert incomplete == ["S_crash"]

    samples_final, events_final = reopened_store.recover_session("S_crash")
    assert samples_final.exists()
    assert events_final.exists()
    assert not (reopened_store.session_dir("S_crash") / "samples.csv.part").exists()
    assert reopened_store.find_incomplete_sessions() == []

    with open(samples_final, newline="", encoding="utf-8") as fh:
        assert len(list(csv.reader(fh))) == 101
