from threading import Event
from types import SimpleNamespace
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox
import csv

from emg_collector.app import create_main_window
from emg_collector.ui.participant_form import ParticipantForm


def test_required_participant_ignores_excluded_optional_values(qtbot):
    form = ParticipantForm(required_only=True)
    qtbot.addWidget(form)
    form.show()
    form.age_spin.setValue(25)
    form.height_spin.setValue(170)
    form.name_edit.setText("must not be collected")
    form.notes_edit.setPlainText("excluded notes")
    form.weight_spin.setValue(80)
    private, public = form.build_models()
    assert (
        private is None and public.weight_kg is None and public.participant_notes == ""
    )
    assert public.age == 25 and public.height_cm == 170
    for field in (
        form.name_edit,
        form.sex_combo,
        form.weight_spin,
        form.notes_edit,
        form.strength_sessions_spin,
        form.exercise_minutes_spin,
    ):
        assert not field.isVisibleTo(form)
    assert form.age_spin.isVisibleTo(form)


def test_minimal_collection_keeps_required_start_and_explicit_consents(
    qtbot, tmp_path, monkeypatch
):
    import emg_collector.ui.multimodal_panel as panel

    window = create_main_window(tmp_path / "minimal")
    qtbot.addWidget(window)
    window.show()
    assert not window.model.isVisibleTo(window)
    assert not window.synthetic.isVisibleTo(window)
    assert not window.review_button.isVisibleTo(window)
    assert window.tools_button.menu().actions()
    assert not hasattr(window, "existing") and not hasattr(window, "number")
    assert not window.participant.participant_id_edit.isVisibleTo(window)
    checkboxes = window.findChildren(QCheckBox)
    assert len(checkboxes) == 4
    assert all(
        "동의" in checkbox.text() or "동의" in checkbox.accessibleName()
        for checkbox in checkboxes
    )
    window.device_settings.show()
    assert window.model.isVisibleTo(window.device_settings)
    assert window.synthetic.isVisibleTo(window.device_settings)
    window.device_settings.hide()
    assert not window.pose_consent.isChecked() and not window.video_consent.isChecked()
    window.participant.age_spin.setValue(25)
    window.participant.height_spin.setValue(170)
    window.participant.name_edit.setText("식별 이름 테스트")
    window.participant.consent_checkbox.setChecked(True)
    window.pose_consent.setChecked(True)
    window.placement.setText("이두·삼두 전극 부착 위치 확인")
    window.arm.setCurrentIndex(1)
    window.load.setValue(5)
    window.load.setFocus()
    qtbot.keyClick(window.load, Qt.Key.Key_Up)
    window.dumbbell_count.setFocus()
    qtbot.keyClick(window.dumbbell_count, Qt.Key.Key_Up)
    assert window.load.value() == 5.5 and window.dumbbell_count.value() == 2
    window.preflight_ok = True
    captured = {}

    def fake_controller(root, public, consent, visit, protocol, **kwargs):
        captured.update(public=public, consent=consent, visit=visit, **kwargs)
        done = Event()
        done.set()
        return SimpleNamespace(
            start=lambda: None,
            done=done,
            preview=lambda: {},
            errors=[],
            manifest={"status": "complete"},
        )

    monkeypatch.setattr(panel, "CollectionController", fake_controller)
    window._start()
    window.timer.stop()
    assert captured["arm"] == "left"
    assert captured["load_kg"] == 5.5 and captured["dumbbell_count"] == 2
    assert captured["visit"].hours_since_exercise is None
    assert "rest_before_s" not in captured and "target_repetitions" not in captured
    assert captured["consent"].video_export is False
    assert (
        captured["skin_prepared"] is False and captured["clothing_confirmed"] is False
    )
    assert "set_number" not in captured
    with (window.store.root / "participants_private.csv").open(
        encoding="utf-8", newline=""
    ) as fh:
        assert list(csv.DictReader(fh))[0]["name"] == "식별 이름 테스트"
    assert "식별 이름 테스트" not in (
        window.store.root / "participants_public.csv"
    ).read_text(encoding="utf-8")
    assert window.stop_button.isEnabled()
    window._tick()
    assert not window.start_button.isEnabled()
    window._start()
    assert "1회" in window.status.text()
    with (window.store.root / "participants_public.csv").open(
        encoding="utf-8", newline=""
    ) as fh:
        assert len(list(csv.DictReader(fh))) == 1


def test_old_set_and_assessment_without_count_mean_one_dumbbell():
    from emg_collector.multimodal.schema import SetRecord
    from emg_collector.labeling.review_contract import decision_payload

    record = SetRecord(
        set_id="SET1", arm="right", set_number=1, load_kg=5, start_ns=0, end_ns=1
    )
    old = record.model_dump(mode="json")
    old.pop("dumbbell_count")
    assert SetRecord.model_validate(old).dumbbell_count == 1
    assert decision_payload({"sets": [old], "attempts": []}) == decision_payload(
        {"sets": [record.model_dump(mode="json")], "attempts": []}
    )
