"""Six work-order reproducers, run against the reviewed HEAD before fixes."""

import csv
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from emg_collector.labeling.review import append_review, read_sets, read_attempts
from emg_collector.labeling.sample_labels import labeled_rows, write_labeled_samples
from emg_collector.labeling.repetitions import RepetitionDetector
from emg_collector.multimodal.schema import Consent, Visit
from emg_collector.models import ParticipantPublic
from emg_collector.multimodal.controller import CollectionController
from emg_collector.protocols import PilotProtocol
from emg_collector.storage.multimodal_writer import atomic_json, file_info
from emg_collector.storage.training_export import export_training


@pytest.fixture(scope="module")
def original_dataset(tmp_path_factory):
    path = Path(__file__).resolve().parents[1] / "scripts/create_synthetic_dataset.py"
    spec = importlib.util.spec_from_file_location("fix_synthetic", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create(tmp_path_factory.mktemp("fix-baseline") / "dataset")


@pytest.fixture
def dataset(original_dataset, tmp_path):
    target = tmp_path / "dataset"
    shutil.copytree(original_dataset, target)
    return target


def test_f1_known_mapping_uses_measurement_not_receipt():
    sample = dict(
        sample_index=0,
        epoch_id=0,
        device_time_us=100000,
        unwrapped_time_us=100000,
        host_receive_ns=600000000,
        s1_env=1,
        s1_raw=2,
        s2_env=3,
        s2_raw=4,
    )
    poses = [
        dict(
            frame_id=i,
            capture_host_ns=ns,
            infer_host_ns=ns + 1,
            elbow_angle_deg=angle,
            trunk_tilt_deg=0,
            upperarm_delta_deg=0,
            quality_mask="ok",
        )
        for i, ns, angle in [(0, 100000000, 170), (1, 600000000, 60)]
    ]
    mappings = {
        "0": [
            dict(
                mapping_version="known-v1",
                epoch_id=0,
                method="synthetic_reference",
                status="validated",
                offset_ns=0,
                drift_ppm=0,
                uncertainty_ns=0,
                valid_from_device_us=0,
                valid_to_device_us=1000000,
                available_host_ns=0,
                fit_scope="causal",
            )
        ]
    }
    row = next(
        labeled_rows([sample], poses, [], [], 100000000, clock_mappings=mappings)
    )
    assert row["pose_frame_id"] == 0 and row["measurement_host_ns"] == 100000000


def test_f2_sparse_emg_cannot_be_exported_as_normal(dataset, tmp_path):
    session = dataset / "sessions/M_SYNTH01"
    path = session / "samples.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = list(reader)[::1500]
    for i, row in enumerate(rows):
        row["sample_index"] = str(i)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    quality = json.loads((session / "quality.json").read_text())
    quality.update(valid_samples=len(rows), actual_sample_rate_hz=1 / 3)
    atomic_json(session / "quality.json", quality)
    output = tmp_path / "new_labels.csv"
    write_labeled_samples(session, output)
    shutil.copyfile(output, session / "labeled_samples.csv")
    manifest = json.loads((session / "completion_manifest.json").read_text())
    for name in ("samples.csv", "quality.json", "labeled_samples.csv"):
        manifest["files"][name] = {"exists": True, **file_info(session / name)}
    atomic_json(session / "completion_manifest.json", manifest)
    result = export_training(
        dataset, tmp_path / "sparse_export", synthetic=True, allow_pilot=True
    )
    assert result["examples"] == 0


def test_f3_one_sample_then_silence_triggers_watchdog(monkeypatch, tmp_path):
    import emg_collector.multimodal.controller as controller_module

    class Clock:
        ns = 0

        def perf_counter_ns(self):
            return self.ns

        def monotonic(self):
            return self.ns / 1e9

    clock = Clock()
    c = CollectionController(
        tmp_path,
        ParticipantPublic(
            participant_id="P-FAIL01",
            age=25,
            height_cm=170,
            exercise_sessions_per_week=0,
            days_since_last_exercise=0,
        ),
        Consent(research=True, pose_coordinates=True),
        Visit(visit_id="V1"),
        PilotProtocol(),
        placement="synthetic test",
        skin_prepared=True,
        clothing_confirmed=True,
    )
    lines = [b"time_us,biceps_env,biceps_raw,triceps_env,triceps_raw\n", b"0,1,2,3,4\n"]

    class Serial:
        count = 0
        is_open = True

        def readline(self):
            clock.ns += 500000000
            self.count += 1
            if self.count > 40:
                c.stop_event.set()
            return lines.pop(0) if lines else b""

        def close(self):
            pass

    monkeypatch.setattr(controller_module, "time", clock)
    import serial

    monkeypatch.setattr(
        "emg_collector.acquisition.esp32_serial.open_esp32_stream",
        lambda *a, **kw: Serial(),
    )
    c.writer = SimpleNamespace(submit=lambda *a, **kw: None)
    c._serial()
    assert c.sample_count == 1
    assert c.termination == "equipment_failure" and any(
        "serial_stall" in e for e in c.errors
    )


def test_f4_incomplete_session_does_not_block_good_session(dataset, tmp_path):
    incomplete = dataset / "sessions/M_INCOMPLETE"
    incomplete.mkdir()
    metadata = json.loads((dataset / "sessions/M_SYNTH01/metadata.json").read_text())
    metadata["session_id"] = "M_INCOMPLETE"
    atomic_json(incomplete / "metadata.json", metadata)
    result = export_training(
        dataset, tmp_path / "mixed_export", synthetic=True, allow_pilot=True
    )
    assert result["examples"] == 15
    assert (tmp_path / "mixed_export/exclusion_report.json").exists()


def test_f5_three_partial_curls_are_three_attempts():
    d = RepetitionDetector(PilotProtocol())
    ns = 0
    for angle in [170] * 3 + ([125] * 4 + [170] * 4) * 3:
        d.update(ns, angle, 0, 0, True)
        ns += 100000000
    assert len(d.attempts) == 3
    assert all(
        a.validity == "invalid" and "return_before_top" in a.reasons for a in d.attempts
    )


def test_f6_draft_then_adjudication_cannot_confirm(dataset):
    session = dataset / "sessions/M_SYNTH01"
    (session / "annotations.jsonl").write_text("", encoding="utf-8")
    manifest = json.loads((session / "completion_manifest.json").read_text())
    manifest["files"]["annotations.jsonl"] = {
        "exists": True,
        **file_info(session / "annotations.jsonl"),
    }
    manifest["labels_confirmed"] = False
    atomic_json(session / "completion_manifest.json", manifest)
    sets, attempts = read_sets(session), read_attempts(session)
    append_review(session, "draft-reviewer", "draft", sets, attempts, False)
    entry = append_review(
        session, "second-reviewer", "adjudication", sets, attempts, True, True
    )
    assert entry["sets"][0]["review_status"] == "provisional"
