import csv
import json
from pathlib import Path

import pytest

from emg_collector.storage.ground_truth import ManualTruth, TruthInterval, save_truth, truth_history, export_truth, export_training_truth
from emg_collector.ui.ground_truth import GroundTruthDialog
from emg_collector.ui.recording_browser import RecordingBrowserDialog, list_recordings


@pytest.fixture
def recording(tmp_path):
    root = tmp_path / "sessions" / "M_TEST"
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(json.dumps({"start_host_ns": 1_000_000_000, "start_time_utc": "2026-10-28T06:59:41+00:00"}), encoding="utf-8")
    (root / "samples.csv").write_text("sample_index,host_receive_ns,s1_raw,s2_raw\n0,2000000000,200,400\n1,4000000000,201,401\n2,5000000000,202,402\n3,7000000000,203,403\n", encoding="utf-8")
    from emg_collector.multimodal.schema import SetRecord
    row = SetRecord(set_id="S1", arm="right", set_number=1, load_kg=5,
                    start_ns=1_000_000_000, end_ns=11_000_000_000).model_dump(mode="json")
    with (root / "sets.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    (root / "quality.json").write_text(json.dumps({"valid_samples": 1, "actual_sample_rate_hz": 500}), encoding="utf-8")
    (root / "completion_manifest.json").write_text('{"status":"complete"}', encoding="utf-8")
    return root


def truth():
    return ManualTruth(reviewer_id="R1",
                       intervals=[TruthInterval(start_s=1, end_s=3, elbow_angle_deg=90, trunk_fixed=True, pelvis_fixed=True),
                                  TruthInterval(start_s=4, end_s=6, elbow_angle_deg=60, trunk_fixed=False)])


def test_truth_revision_export_and_raw_files_unchanged(recording, tmp_path):
    before = {p.name: p.read_bytes() for p in recording.iterdir()}
    first = save_truth(recording, truth())
    with pytest.raises(ValueError, match="다른 창"):
        save_truth(recording, truth())
    edited = truth().model_copy(update={"note": "각도계로 확인"})
    second = save_truth(recording, edited, first["revision"])
    assert truth_history(recording)[-1]["data"]["note"] == "각도계로 확인"
    assert second["previous_revision"] == first["revision"]
    assert all((recording / name).read_bytes() == content for name, content in before.items())
    output = tmp_path / "truth.csv"
    export_truth(recording, output)
    with output.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [float(r["elbow_angle_deg"]) for r in rows] == [90, 60]
    assert rows[0]["trunk_fixed"] == "True"
    with pytest.raises(ValueError, match="덮어쓸"):
        export_truth(recording, recording / "samples.csv")


def test_truth_rejects_overlap_angles_and_session_bounds(recording):
    with pytest.raises(ValueError, match="겹칩니다"):
        ManualTruth(reviewer_id="R",
                    intervals=[TruthInterval(start_s=1, end_s=4, elbow_angle_deg=90),
                               TruthInterval(start_s=3, end_s=5, elbow_angle_deg=60)])
    with pytest.raises(ValueError):
        TruthInterval(start_s=1, end_s=2, elbow_angle_deg=181)
    data = truth()
    data.intervals.append(TruthInterval(start_s=11, end_s=12, elbow_angle_deg=30))
    with pytest.raises(ValueError, match="종료 시각"):
        save_truth(recording, data)


def test_ground_truth_ui_round_trip(qtbot, recording):
    dialog = GroundTruthDialog(recording)
    qtbot.addWidget(dialog)
    dialog.reviewer.setText("R-test")
    dialog.note.setText("각도계로 확인")
    dialog._add(TruthInterval(start_s=2, end_s=4, elbow_angle_deg=90, trunk_fixed=True, pelvis_fixed=False, note="90도 유지"))
    dialog._save()
    assert "저장 완료" in dialog.status.text()
    reopened = GroundTruthDialog(recording)
    qtbot.addWidget(reopened)
    assert reopened.table.cellWidget(0, 0).value() == 2
    assert reopened.table.cellWidget(0, 2).value() == 90
    assert reopened.table.cellWidget(0, 3).currentData() is True
    assert reopened.table.cellWidget(0, 4).currentData() is False
    assert reopened.note.text() == "각도계로 확인"


def test_training_join_respects_boundaries_and_unknown_body_labels(recording, tmp_path):
    save_truth(recording, truth())
    output = tmp_path / "training.csv"
    assert export_training_truth(recording, output) == 2
    with output.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["sample_index"] for r in rows] == ["0", "2"]
    assert [float(r["truth_elbow_angle_deg"]) for r in rows] == [90, 60]
    assert rows[1]["truth_pelvis_fixed"] == ""
    assert rows[1]["truth_trunk_fixed"] == "False"
    assert rows[0]["truth_time_basis"] == "host_receive_unverified_sync"


def test_browser_lists_completed_incomplete_and_corrupt_records(qtbot, recording):
    broken = recording.parent / "M_BROKEN"
    broken.mkdir()
    (broken / "metadata.json").write_text("{bad", encoding="utf-8")
    data = list_recordings(recording.parent.parent)
    assert len(data) == 2
    assert data[0]["root"] == recording
    assert data[0]["start"] == "2026-10-28 15:59:41"
    dialog = RecordingBrowserDialog(recording.parent.parent)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.table.rowCount() == 2)
    assert dialog.open_button.isEnabled() and dialog.truth_button.isEnabled()
    dialog.table.selectRow(1)
    assert not dialog.open_button.isEnabled()
