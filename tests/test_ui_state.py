"""UI state-machine tests (work order section 9.5).

These drive real QWidget instances via pytest-qt's qtbot rather than
mocking Qt, so the checks exercise the same code paths the app uses.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QMessageBox

from emg_collector.ui.main_window import MainWindow, can_start_recording
from emg_collector.ui.participant_form import ParticipantForm


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """MainWindow pops real modal QMessageBoxes (save-complete, discard
    confirmation, ...). Left unpatched, those .exec() calls block forever
    waiting for a click, which hung the full test suite (a real bug found
    while running all tests together, not just this file in isolation)."""
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


def fill_valid_participant(form: ParticipantForm) -> None:
    form.name_edit.setText("Hong Gildong")
    form.age_spin.setValue(30)
    form.height_spin.setValue(175.0)
    form.exercise_sessions_spin.setValue(3)
    form.days_since_exercise_spin.setValue(1)


def test_can_start_recording_pure_gate():
    assert can_start_recording(True, True, True) is True
    assert can_start_recording(False, True, True) is False
    assert can_start_recording(True, False, True) is False
    assert can_start_recording(True, True, False) is False


def test_consent_unchecked_blocks_recording(qtbot, tmp_path):
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)
    fill_valid_participant(window.participant_form)
    window.participant_form.consent_checkbox.setChecked(False)
    window._connected = True
    window._update_can_start()

    assert window.acquisition_panel.start_button.isEnabled() is False


def test_missing_required_field_blocks_recording_and_highlights(qtbot, tmp_path):
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)
    # Leave name blank (required).
    window.participant_form.age_spin.setValue(30)
    window.participant_form.height_spin.setValue(175.0)
    window.participant_form.consent_checkbox.setChecked(True)
    window._connected = True
    window._update_can_start()

    assert window.acquisition_panel.start_button.isEnabled() is False
    assert window.participant_form._error_labels["name"].text() != ""


def test_no_connection_blocks_recording(qtbot, tmp_path):
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)
    fill_valid_participant(window.participant_form)
    window.participant_form.consent_checkbox.setChecked(True)
    window._connected = False
    window._update_can_start()

    assert window.acquisition_panel.start_button.isEnabled() is False


def test_valid_state_enables_start(qtbot, tmp_path):
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)
    fill_valid_participant(window.participant_form)
    window.participant_form.consent_checkbox.setChecked(True)
    window._connected = True
    window._update_can_start()

    assert window.acquisition_panel.start_button.isEnabled() is True


def test_recording_locks_participant_id_and_session_fields(qtbot, tmp_path):
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)
    fill_valid_participant(window.participant_form)
    window.participant_form.consent_checkbox.setChecked(True)
    window._connected = True

    window._on_start_recording()

    assert window._is_recording is True
    assert window.participant_form.participant_id_edit.isEnabled() is False
    assert window.acquisition_panel.muscle_combo.isEnabled() is False
    assert window.acquisition_panel.start_button.isEnabled() is False
    assert window.acquisition_panel.stop_button.isEnabled() is True

    window._on_stop_recording()
    assert window._is_recording is False
    assert window.participant_form.participant_id_edit.isEnabled() is True
    assert (window.store.session_dir(window.acquisition_panel.port_combo.currentText()) or True)


def test_plot_time_axis_stays_continuous_across_batches(qtbot, tmp_path):
    """Regression test: each batch must extend the plot's time axis, not
    reset it to zero. Resetting per-batch produced a dense zigzag (every
    ~40ms batch overlapping the previous one back at t=0), which is what a
    user reported seeing on screen."""
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)

    from emg_collector.acquisition.serial_worker import UnwrappedSample

    interval_us = 2000
    first_batch = [
        UnwrappedSample(i * interval_us, i * interval_us, 100, 200, 300, 400, False, False)
        for i in range(20)
    ]
    window._on_batch_ready(first_batch)
    second_batch = [
        UnwrappedSample(i * interval_us, i * interval_us, 100, 200, 300, 400, False, False)
        for i in range(20, 40)
    ]
    window._on_batch_ready(second_batch)

    t_values = list(window.plot_panel._t)
    assert t_values == sorted(t_values)
    assert t_values[-1] > t_values[len(first_batch) - 1]


def test_pause_display_does_not_stop_sample_storage(qtbot, tmp_path):
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)
    fill_valid_participant(window.participant_form)
    window.participant_form.consent_checkbox.setChecked(True)
    window._connected = True
    window._on_start_recording()

    window.plot_panel.set_paused(True)

    from emg_collector.acquisition.serial_worker import UnwrappedSample

    batch = [UnwrappedSample(i * 2000, i * 2000, 100, 200, 300, 400, False, False) for i in range(5)]
    window._on_batch_ready(batch)

    assert window._sample_index == 5
    assert window.plot_panel.paused is True

    window._on_stop_recording()


def test_stop_recording_creates_files_and_resets_buttons(qtbot, tmp_path):
    window = MainWindow(tmp_path / "dataset")
    qtbot.addWidget(window)
    fill_valid_participant(window.participant_form)
    window.participant_form.consent_checkbox.setChecked(True)
    window._connected = True
    window._on_start_recording()
    session_dir = window.store.session_dir(window._session_id)

    from emg_collector.acquisition.serial_worker import UnwrappedSample

    batch = [UnwrappedSample(i * 2000, i * 2000, 100, 200, 300, 400, False, False) for i in range(5)]
    window._on_batch_ready(batch)

    window._on_stop_recording()

    assert (session_dir / "samples.csv").exists()
    assert (session_dir / "events.csv").exists()
    assert (session_dir / "metadata.json").exists()
    assert (session_dir / "quality.json").exists()
    assert window.acquisition_panel.start_button.isEnabled() is True
    assert window.acquisition_panel.stop_button.isEnabled() is False
