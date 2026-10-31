# Imported pytest fixtures are resolved by name rather than ordinary references.
# ruff: noqa: F811
import json
from types import SimpleNamespace

import pytest

from test_review_fix_regressions import dataset, original_dataset  # noqa: F401
from emg_collector.multimodal.controller import CollectionController
from emg_collector.multimodal.schema import Consent, Visit
from emg_collector.models import ParticipantPublic
from emg_collector.protocols import PilotProtocol
from emg_collector.labeling.repetitions import RepetitionDetector
from emg_collector.labeling.review import review_history
from emg_collector.labeling.sample_labels import write_labeled_samples
from emg_collector.storage.multimodal_writer import MultimodalWriter


def controller(tmp_path, clock):
    result = CollectionController(
        tmp_path,
        ParticipantPublic(
            participant_id="P-BOUND01",
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
        clock_ns=lambda: clock.ns,
    )
    result.writer = SimpleNamespace(submit=lambda *args: None)
    return result


@pytest.mark.parametrize(
    "scenario,code,count",
    [
        ("startup", "serial_start_timeout", 0),
        ("malformed", "serial_stall", 1),
        ("disconnect", "serial_failure", 1),
        ("recover", None, 2),
    ],
)
def test_serial_deadlines_without_real_wait(
    tmp_path, monkeypatch, scenario, code, count
):
    import serial

    clock = SimpleNamespace(ns=0)
    c = controller(tmp_path, clock)
    lines = [b"time_us,biceps_env,biceps_raw,triceps_env,triceps_raw\n"]
    if scenario != "startup":
        lines.append(b"0,1,2,3,4\n")

    class Serial:
        reads = 0
        is_open = True

        def readline(self):
            clock.ns += 500_000_000
            self.reads += 1
            if lines:
                return lines.pop(0)
            if scenario == "disconnect":
                raise OSError("disconnected")
            if scenario == "recover" and self.reads == 5:
                return b"2000,1,2,3,4\n"
            if scenario == "recover" and self.reads == 6:
                c.stop("target_reps")
            if self.reads > 30:
                raise AssertionError("watchdog did not terminate")
            return b"not,a,valid,sample\n" if scenario == "malformed" else b""

        def close(self):
            pass

    monkeypatch.setattr(
        "emg_collector.acquisition.esp32_serial.open_esp32_stream",
        lambda *args, **kwargs: Serial(),
    )
    c._serial()
    assert c.sample_count == count
    if code:
        assert c.termination == "equipment_failure" and c.faults[-1]["code"] == code
        c.stop("target_reps")
        assert c.termination == "equipment_failure"
        assert (
            c.faults[-1]["last_valid_sample_host_ns"]
            == c.last_valid_sample_monotonic_ns
        )
    else:
        assert not c.errors


def test_failure_after_user_stop_is_preserved(tmp_path):
    c = controller(tmp_path, SimpleNamespace(ns=123))
    c.stop("target_reps")
    c.fail("camera", OSError("lost"))
    assert c.termination == "equipment_failure" and c.motion_end_ns == 123


def test_writer_shutdown_is_bounded_and_retains_parts(tmp_path):
    from queue import Queue

    writer = MultimodalWriter.__new__(MultimodalWriter)
    joined = []
    writer.closed = False
    writer.shutdown_timeout_s = 0
    writer.queue = Queue()
    writer.thread = SimpleNamespace(
        is_alive=lambda: True, join=lambda timeout: joined.append(timeout)
    )
    assert not writer.close_incomplete()
    assert joined == [0] and "writer_shutdown_timeout" in writer.error


def test_tracking_loss_precedes_partial_and_finish_only_once():
    detector = RepetitionDetector(PilotProtocol())
    ns = 0
    for angle, valid in (
        [(170, True)] * 3 + [(125, True)] * 4 + [(None, False)] + [(170, True)] * 4
    ):
        detector.update(ns, angle, 0, 0, valid)
        ns += 100_000_000
    assert len(detector.attempts) == 1 and detector.attempts[0].validity == "unknown"
    assert detector.finish(ns) is None
    assert len(detector.attempts) == 1


def test_review_ui_edit_save_reopen_export(qtbot, dataset, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QInputDialog
    from emg_collector.ui.multimodal_review import MultimodalReviewDialog

    session = dataset / "sessions/M_SYNTH01"
    raw = (session / "repetitions.csv").read_bytes()
    dialog = MultimodalReviewDialog(session)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.data is not None, timeout=15000)
    dialog.mode.setCurrentIndex(dialog.mode.findData("draft"))
    first = dialog._table_attempts()[0]
    dialog.table.selectRow(0)
    dialog._edit("delete")
    assert dialog.table.rowCount() == 15
    answers = iter(
        [(first.start_ns - dialog.origin) / 1e9, (first.end_ns - dialog.origin) / 1e9]
    )
    monkeypatch.setattr(
        QInputDialog, "getDouble", lambda *a, **kw: (next(answers), True)
    )
    dialog._edit("add")
    assert dialog.table.rowCount() == 16
    added = dialog._table_attempts()[0]
    assert added.attempt_id != first.attempt_id
    dialog.table.selectRow(0)
    monkeypatch.setattr(
        QInputDialog,
        "getDouble",
        lambda *a, **kw: (
            ((added.start_ns + added.end_ns) / 2 - dialog.origin) / 1e9,
            True,
        ),
    )
    dialog._edit("split")
    assert dialog.table.rowCount() == 17, dialog.status.text()
    dialog.table.clearSelection()
    dialog.table.selectRow(0)
    for col in range(dialog.table.columnCount()):
        dialog.table.item(1, col).setSelected(True)
    dialog._edit("merge")
    ids = [a.attempt_id for a in dialog._table_attempts()]
    assert len(ids) == 16 and ids[0] != added.attempt_id
    final_id = ids[0]
    assert [e["operation"] for e in dialog.edit_operations] == [
        "delete",
        "add",
        "split",
        "merge",
    ]
    dialog.reviewer.setText("UI-reviewer")
    dialog.revision_reason.setText("recovered missing attempt")
    dialog._save()
    qtbot.waitUntil(
        lambda: dialog.save_thread is not None and not dialog.save_thread.is_alive(),
        timeout=15000,
    )
    qtbot.waitUntil(
        lambda: review_history(session)[-1].get("reviewer_id") == "UI-reviewer"
    )
    dialog.close()
    reopened = MultimodalReviewDialog(session)
    qtbot.addWidget(reopened)
    qtbot.waitUntil(lambda: reopened.data is not None, timeout=15000)
    assert (
        reopened._table_attempts()[0].attempt_id == first.attempt_id
    )  # blind acquisition basis
    reopened.mode.setCurrentIndex(reopened.mode.findData("draft"))
    assert reopened._table_attempts()[0].attempt_id == final_id
    output = tmp_path / "edited_labels.csv"
    assert write_labeled_samples(session, output, reviewed=True) > 0
    assert final_id in output.read_text(encoding="utf-8")
    assert (session / "repetitions.csv").read_bytes() == raw
    assert (
        json.loads((session / "completion_manifest.json").read_text())[
            "labels_confirmed"
        ]
        is False
    )
    reopened.close()
