import json

from emg_collector.models import EventRecord, EventType, SampleRecord
from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.ui.session_viewer import SessionData, SessionLoadError, SessionViewerDialog


def make_sample(i: int, label: str = "rest") -> SampleRecord:
    return SampleRecord(
        sample_index=i,
        device_time_us=i * 2000,
        device_time_us_unwrapped=i * 2000,
        elapsed_s=i * 0.002,
        host_elapsed_s=i * 0.002,
        env_adc=1800 + i,
        raw_adc=1800 - i,
        label=label,
    )


def test_session_data_loads_finalized_session(tmp_path):
    store = DatasetStore(tmp_path / "dataset")
    writer = store.create_session_writer("S1")
    writer.write_samples([make_sample(i) for i in range(10)])
    writer.write_event(
        EventRecord(
            event_index=0,
            sample_index=5,
            device_time_us_unwrapped=10000,
            elapsed_s=0.01,
            event_type=EventType.label_change,
            label="flexion",
            note="",
        )
    )
    writer.finalize()
    store.write_session_metadata("S1", {"session_id": "S1", "participant_id": "P-AB12", "status": "complete"})
    store.write_session_quality("S1", {"valid_samples": 10, "actual_sample_rate_hz": 500.0})

    data = SessionData(store.session_dir("S1"))

    assert data.is_unfinalized is False
    assert data.sample_count == 10
    assert data.env_adc[0] == 1800
    assert len(data.events) == 1
    assert data.events[0]["label"] == "flexion"
    assert data.metadata["participant_id"] == "P-AB12"
    assert data.quality["valid_samples"] == 10


def test_session_data_loads_unfinalized_part_session(tmp_path):
    store = DatasetStore(tmp_path / "dataset")
    writer = store.create_session_writer("S_crash")
    writer.write_samples([make_sample(i) for i in range(7)])
    writer.close_without_finalize()

    data = SessionData(store.session_dir("S_crash"))

    assert data.is_unfinalized is True
    assert data.sample_count == 7
    assert data.metadata is None
    assert data.quality is None


def test_session_data_raises_when_no_samples_file(tmp_path):
    empty_dir = tmp_path / "not_a_session"
    empty_dir.mkdir()
    try:
        SessionData(empty_dir)
        assert False, "expected SessionLoadError"
    except SessionLoadError:
        pass


def test_session_viewer_dialog_opens_for_finalized_session(qtbot, tmp_path):
    store = DatasetStore(tmp_path / "dataset")
    writer = store.create_session_writer("S1")
    writer.write_samples([make_sample(i) for i in range(20)])
    writer.finalize()

    dialog = SessionViewerDialog(store.session_dir("S1"))
    qtbot.addWidget(dialog)

    assert dialog.data is not None
    assert dialog.data.sample_count == 20


def test_session_viewer_dialog_shows_error_ui_for_missing_session(qtbot, tmp_path):
    missing_dir = tmp_path / "does_not_exist"

    dialog = SessionViewerDialog(missing_dir)
    qtbot.addWidget(dialog)

    assert dialog.data is None
