"""End-to-end fixtures exercise files, review revisions, causal export and Qt."""

import csv
import importlib.util
import json
from pathlib import Path
import time

import numpy as np
import pytest

from emg_collector.labeling.review import (
    append_review,
    effective_review,
    review_history,
)
from emg_collector.models import ParticipantPublic
from emg_collector.multimodal.controller import CollectionController
from emg_collector.multimodal.schema import Consent, ProfileParser, Visit
from emg_collector.multimodal.validator import validate_session
from emg_collector.protocols import PilotProtocol
from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.storage.exporter import export_deidentified
from emg_collector.storage.multimodal_writer import MultimodalWriter, recover
from emg_collector.storage.training_export import export_training
from emg_collector.sync.clock_alignment import fit_clock


@pytest.fixture(scope="module")
def synthetic_dataset(tmp_path_factory):
    path = Path(__file__).resolve().parents[1] / "scripts/create_synthetic_dataset.py"
    spec = importlib.util.spec_from_file_location("synthetic_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create(tmp_path_factory.mktemp("v3") / "dataset")


def test_synthetic_review_and_causal_training(synthetic_dataset, tmp_path):
    root = synthetic_dataset / "sessions/M_SYNTH01"
    assert validate_session(root) == []
    with (root / "labeled_samples.csv").open(newline="", encoding="utf-8") as fh:
        labeled = list(csv.DictReader(fh))
    assert len(labeled) == 24001
    assert labeled[100]["biceps_raw_adc"] == "2000"
    assert labeled[100]["triceps_raw_adc"] == "2100"
    assert labeled[100]["phase"] == "concentric"
    assert len(review_history(root)) == 2
    assert review_history(root)[-1]["agreement_report"]["kappa"] == pytest.approx(1)
    assert effective_review(root)[0][0].review_status == "confirmed"
    output = tmp_path / "training"
    assert (
        export_training(synthetic_dataset, output, synthetic=True, allow_pilot=True)[
            "examples"
        ]
        == 15
    )
    with (output / "index.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert [int(rows[i - 1]["remaining_valid_reps"]) for i in (10, 14, 15)] == [5, 1, 0]
    assert (
        rows[13]["next_attempt_failure"] == "False"
        and rows[14]["next_attempt_failure"] == "True"
    )
    assert len({r["split"] for r in rows}) == 1
    for row in rows:
        with np.load(output / "sequences" / f"{row['window_id']}.npz") as data:
            assert data["host_ns"].max() <= int(row["prediction_host_ns"])
            assert data["values"].shape == data["mask"].shape
    assert (
        export_training(synthetic_dataset, tmp_path / "real", synthetic=False)[
            "examples"
        ]
        == 0
    )


def test_allowlist_archive(synthetic_dataset, tmp_path):
    out = export_deidentified(synthetic_dataset, tmp_path / "archive")
    assert not list(out.rglob("*.avi"))
    assert not list(out.rglob("annotations.jsonl"))
    assert not (out / "participants_private.csv").exists()
    for path in out.rglob("metadata.json"):
        text = path.read_text()
        assert "electrode_placement" not in text and "participant_notes" not in text


def test_reviewed_sample_export_uses_revision_and_preserves_automatic_labels(
    synthetic_dataset, tmp_path
):
    import shutil
    from emg_collector.labeling.sample_labels import write_labeled_samples

    copied = tmp_path / "reviewed"
    shutil.copytree(synthetic_dataset / "sessions/M_SYNTH01", copied)
    automatic = (copied / "labeled_samples.csv").read_bytes()
    sets, attempts = effective_review(copied)
    attempts[0].validity = "invalid"
    entry = append_review(
        copied, "SYNTH-reviewer-3", "synthetic adjudication", sets, attempts, True, True
    )
    output = tmp_path / "reviewed_labels.csv"
    assert write_labeled_samples(copied, output, reviewed=True) == 24001
    with output.open(newline="", encoding="utf-8") as fh:
        first = next(csv.DictReader(fh))
    assert first["attempt_validity"] == "invalid"
    assert first["label_revision"] == entry["revision"]
    assert first["label_source"] == "reviewed_mediapipe_pose"
    assert (copied / "labeled_samples.csv").read_bytes() == automatic


def test_protocol_and_synthetic_export_require_explicit_opt_in(
    synthetic_dataset, tmp_path
):
    assert (
        export_training(synthetic_dataset, tmp_path / "no_pilot", synthetic=True)[
            "examples"
        ]
        == 0
    )


def test_late_inference_is_not_available_at_prediction(synthetic_dataset, tmp_path):
    import shutil
    from emg_collector.storage.multimodal_writer import atomic_json, file_info

    copied = tmp_path / "late"
    shutil.copytree(synthetic_dataset, copied)
    session = copied / "sessions/M_SYNTH01"
    path = session / "pose_metrics.csv"
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)
    for row in rows:
        row["infer_host_ns"] = str(100_000_000_000)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest = json.loads((session / "completion_manifest.json").read_text())
    manifest["files"]["pose_metrics.csv"] = {"exists": True, **file_info(path)}
    atomic_json(session / "completion_manifest.json", manifest)
    result = export_training(
        copied, tmp_path / "late_export", synthetic=True, allow_pilot=True
    )
    assert result["examples"] == 0
    assert result["excluded"]["missing_motion_common_evaluation"] == 15


def test_confirmed_label_rejects_missing_video_consent(synthetic_dataset, tmp_path):
    import shutil
    from emg_collector.storage.multimodal_writer import atomic_json

    copied = tmp_path / "no_access"
    shutil.copytree(synthetic_dataset / "sessions/M_SYNTH01", copied)
    metadata = json.loads((copied / "metadata.json").read_text())
    metadata["consent"]["video_access"] = False
    atomic_json(copied / "metadata.json", metadata)
    sets, attempts = effective_review(copied)
    with pytest.raises(ValueError, match="accessible consented video"):
        append_review(copied, "reviewer-3", "review", sets, attempts, True)


def test_writer_overflow_is_explicit(tmp_path, monkeypatch):
    from threading import Event

    gate = Event()
    monkeypatch.setattr(MultimodalWriter, "_run", lambda self: gate.wait(2))
    writer = MultimodalWriter(tmp_path / "queue", {"synthetic": True}, queue_size=1)
    writer.submit("events.csv", {"host_ns": 1})
    with pytest.raises(RuntimeError, match="queue overflow"):
        writer.submit("events.csv", {"host_ns": 2})
    assert writer.overflow_count == 1
    gate.set()
    writer.close_incomplete()


@pytest.mark.parametrize(
    "row",
    ["4294967296,0,0,0,0", "-1,0,0,0,0", "1,4096,0,0,0", "1,0,0,0", "nan,0,0,0,0"],
)
def test_v3_parser_rejects_bad_samples(row):
    parser = ProfileParser("biceps_triceps_v3")
    parser.parse(parser.header, 1)
    with pytest.raises(ValueError):
        parser.parse(row, 2)


def test_known_clock_drift_and_latency_residual():
    assert fit_clock([(1, 1), (1, 2), (1, 3)])["status"] == "insufficient_data"
    observations = [
        (i * 1000000, 1_000_000_000 + i * 1_000_100_000 + (i % 2) * 1000000)
        for i in range(100)
    ]
    result = fit_clock(observations)
    assert result["drift_ppm"] == pytest.approx(100, abs=1)
    assert result["residual_rms_ns"] > 400000
    assert result["physical_sync_error_ms"] is None


def test_partial_finalize_never_overwrites_or_reports_complete(tmp_path, monkeypatch):
    writer = MultimodalWriter(tmp_path / "crash", {"synthetic": True})
    rename = Path.rename

    def fail_second(path, target):
        if path.name == "pose_landmarks.csv.part":
            raise OSError("injected disk failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_second)
    with pytest.raises(OSError):
        writer.finalize({}, {})
    samples = (writer.root / "samples.csv").read_bytes()
    assert recover(writer.root)["status"] == "incomplete"
    assert (writer.root / "samples.csv").read_bytes() == samples
    assert (writer.root / "pose_landmarks.csv.part").exists()


def test_disk_failure_preserves_parts(tmp_path, monkeypatch):
    original = csv.DictWriter.writerow

    def fail_sample(writer, row):
        if "sample_index" in row:
            raise OSError("injected no space left")
        return original(writer, row)

    # Patch after headers are written; header dictionaries also include sample_index.
    writer = MultimodalWriter(tmp_path / "disk", {"synthetic": True})
    deadline = time.monotonic() + 2
    while (
        not (writer.root / "annotations.jsonl.part").exists()
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    monkeypatch.setattr(csv.DictWriter, "writerow", fail_sample)
    writer.submit("samples.csv", {"sample_index": 0})
    writer.close_incomplete()
    assert "injected no space left" in writer.error
    assert (writer.root / "samples.csv.part").exists()


def test_realtime_workers_finalize_video_and_emg(tmp_path):
    store = DatasetStore(tmp_path / "realtime")
    participant = ParticipantPublic(
        participant_id="P-MOCK01",
        age=25,
        height_cm=170,
        exercise_sessions_per_week=0,
        days_since_last_exercise=0,
    )
    store.register_participant(None, participant)
    c = CollectionController(
        store.root,
        participant,
        Consent(
            research=True, pose_coordinates=True, video_storage=True, video_access=True
        ),
        Visit(visit_id="V1"),
        PilotProtocol(),
        synthetic=True,
        placement="synthetic biceps/triceps",
        mock_receive_batch_delay_ms=10,
        skin_prepared=True,
        clothing_confirmed=True,
    )
    c.start()
    assert c.started.wait(3)
    time.sleep(0.6)
    c.stop("voluntary_stop")
    assert c.done.wait(8)
    assert c.errors == []
    assert c.sample_count > 0 and c.frame_count > 0
    assert validate_session(c.writer.root) == []


def test_anonymous_zero_minutes_and_v3_dialog(qtbot, tmp_path):
    from emg_collector.ui.multimodal_panel import MultimodalDialog

    dialog = MultimodalDialog(DatasetStore(tmp_path / "ui"))
    qtbot.addWidget(dialog)
    form = dialog.participant
    form.age_spin.setValue(25)
    form.height_spin.setValue(170)
    form.exercise_minutes_spin.setValue(0)
    private, public = form.build_models()
    assert private is None and public.exercise_minutes_per_week == 0
    form.exercise_minutes_spin.setValue(-1)
    assert form.build_models()[1].exercise_minutes_per_week is None


def test_review_dialog_loads_common_timeline(qtbot, synthetic_dataset):
    from emg_collector.ui.multimodal_review import MultimodalReviewDialog

    dialog = MultimodalReviewDialog(synthetic_dataset / "sessions/M_SYNTH01")
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.data is not None, timeout=5000)
    assert dialog.table.rowCount() == 16
    dialog.slider.setValue(5000)
    assert dialog.cursors[0].value() == pytest.approx(24)
    dialog.close()


def test_review_dialog_resizes_and_localizes_termination(qtbot, synthetic_dataset):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap
    from emg_collector.ui.multimodal_review import MultimodalReviewDialog
    from emg_collector.ui.common import TERMINATION_LABELS
    from emg_collector.multimodal.schema import Termination

    dialog = MultimodalReviewDialog(synthetic_dataset / "sessions/M_SYNTH01")
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.data is not None, timeout=5000)
    for reason in Termination:
        index = dialog.reason.findData(reason.value)
        assert (
            index >= 0 and dialog.reason.itemText(index) == TERMINATION_LABELS[reason]
        )
    frame = QPixmap(1920, 1080)
    frame.fill(Qt.GlobalColor.blue)
    dialog.video.setPixmap(frame)
    dialog.resize(640, 480)
    dialog.show()
    qtbot.wait(30)
    assert dialog.width() <= 640 and dialog.height() <= 480
    assert dialog.video.pixmap().width() <= dialog.video.contentsRect().width()
    assert dialog.review_scroll.verticalScrollBar().maximum() > 0
    assert dialog.sections.count() == 3
    dialog.close()
