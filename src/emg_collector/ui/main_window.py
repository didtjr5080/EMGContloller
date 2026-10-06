"""Top-level window: wires the connection/session/plot panels to a live
:class:`SerialWorker` thread, a :class:`SessionWriter`, and quality metrics.

State-machine rules this module is responsible for enforcing (work order
section 6.6 / 9.5):

* Recording cannot start without a connection, consent, and valid
  participant metadata.
* Identity/device fields lock once recording starts.
* Pausing the plot only pauses the plot; samples keep being written.
* On app close while recording, the user is asked to save, keep recording,
  or exit without saving (default: save).
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import QThread, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QWidget,
    QVBoxLayout,
)

import serial
from serial.tools import list_ports

from emg_collector.acquisition.mock_source import MockSampleSource, RealtimePacedLineSource
from emg_collector.acquisition.parser import LineParser
from emg_collector.acquisition.serial_worker import SerialPortLineSource, SerialWorker
from emg_collector.acquisition.time_unwrapper import TimeUnwrapper
from emg_collector.config import (
    ADC_MAX_VALUE,
    ADC_MIN_VALUE,
    APP_VERSION,
    BICEPS_ENV_PIN,
    BICEPS_RAW_PIN,
    BRACHIO_ENV_PIN,
    BRACHIO_RAW_PIN,
    DEFAULT_LABEL,
    SCHEMA_VERSION,
    SERIAL_HEADER_LINE,
    SESSION_STATUS_COMPLETE,
    SESSION_STATUS_INCOMPLETE,
    TARGET_SAMPLE_INTERVAL_US,
    TARGET_SAMPLE_RATE_HZ,
)
from emg_collector.models import EventRecord, EventType, SampleRecord
from emg_collector.quality.metrics import QualityAccumulator
from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.ui.acquisition_panel import SOURCE_MOCK, AcquisitionPanel
from emg_collector.ui.participant_form import ParticipantForm
from emg_collector.ui.plot_panel import PlotPanel
from emg_collector.ui.session_viewer import SessionViewerDialog


def generate_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"S_{stamp}_{uuid.uuid4().hex[:8]}"


def can_start_recording(is_connected: bool, consent_confirmed: bool, participant_valid: bool) -> bool:
    """Pure gating rule (section 9.5), kept separate from widgets for easy testing."""
    return is_connected and consent_confirmed and participant_valid


class MainWindow(QMainWindow):
    def __init__(self, dataset_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EMG Dataset Collector")
        self.resize(1280, 800)

        self.store = DatasetStore(dataset_root)

        self.participant_form = ParticipantForm()
        self.acquisition_panel = AcquisitionPanel()
        self.plot_panel = PlotPanel()
        self.open_folder_button = QPushButton("저장 폴더 열기")
        self.load_session_button = QPushButton("저장된 세션 불러오기")

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.addWidget(self.participant_form)
        left_layout.addWidget(self.acquisition_panel)
        load_row = QHBoxLayout()
        load_row.addWidget(self.open_folder_button)
        load_row.addWidget(self.load_session_button)
        left_layout.addLayout(load_row)
        left_layout.addStretch(1)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_container)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(self.plot_panel)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.status_elapsed_label = self._status_label("경과: -")
        self.status_samples_label = self._status_label("저장 샘플: 0")
        self.status_path_label = self._status_label("파일: -")
        self.status_warning_label = self._status_label("")

        self._thread: QThread | None = None
        self._worker: SerialWorker | None = None
        self._connected = False
        self._is_recording = False
        self._session_writer = None
        self._session_id: str | None = None
        self._participant_id: str | None = None
        self._quality: QualityAccumulator | None = None
        self._sample_index = 0
        self._event_index = 0
        self._current_label = DEFAULT_LABEL
        self._recording_started_monotonic = 0.0
        self._first_unwrapped_us: int | None = None
        self._plot_first_unwrapped_us: int | None = None
        self._recent_sample_times: deque[float] = deque()
        self._total_valid_samples = 0
        self._first_sample_monotonic: float | None = None
        self._active_source_kind: str | None = None
        self._active_serial_conn = None
        self._session_viewers: list[SessionViewerDialog] = []

        self._connect_signals()
        self._refresh_ports()
        self._update_can_start()

        self._prompt_recovery_if_needed()

    def _status_label(self, text: str) -> object:
        from PyQt6.QtWidgets import QLabel

        label = QLabel(text)
        self.statusBar().addWidget(label)
        return label

    # -- wiring -------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.participant_form.changed.connect(self._update_can_start)
        self.acquisition_panel.refresh_ports_requested.connect(self._refresh_ports)
        self.acquisition_panel.connect_requested.connect(self._on_connect_requested)
        self.acquisition_panel.disconnect_requested.connect(self._on_disconnect_requested)
        self.acquisition_panel.start_recording_requested.connect(self._on_start_recording)
        self.acquisition_panel.stop_recording_requested.connect(self._on_stop_recording)
        self.acquisition_panel.discard_requested.connect(self._on_discard)
        self.acquisition_panel.label_changed.connect(self._on_label_changed)
        self.acquisition_panel.user_event_requested.connect(self._on_user_event)
        self.open_folder_button.clicked.connect(self._open_dataset_folder)
        self.load_session_button.clicked.connect(self._on_load_session_requested)

    def _refresh_ports(self) -> None:
        ports = [p.device for p in list_ports.comports()]
        self.acquisition_panel.set_available_ports(ports)

    def _open_dataset_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))

    def _on_load_session_requested(self) -> None:
        start_dir = self.store.sessions_dir()
        if not start_dir.exists():
            start_dir = self.store.root
        session_dir = QFileDialog.getExistingDirectory(
            self, "불러올 세션 폴더 선택", str(start_dir)
        )
        if not session_dir:
            return
        # SessionViewerDialog never raises: a load failure (e.g. no
        # samples.csv in the chosen folder) renders as an in-dialog error
        # message instead, so the user still gets a window to close.
        viewer = SessionViewerDialog(Path(session_dir), self)
        self._session_viewers.append(viewer)
        viewer.finished.connect(lambda _=None, v=viewer: self._forget_session_viewer(v))
        viewer.show()

    def _forget_session_viewer(self, viewer: SessionViewerDialog) -> None:
        if viewer in self._session_viewers:
            self._session_viewers.remove(viewer)

    # -- validation / gating -------------------------------------------------

    def _update_can_start(self) -> None:
        result = self.participant_form.validate()
        can_start = can_start_recording(
            self._connected, self.participant_form.consent_confirmed(), result.is_valid
        )
        self.acquisition_panel.set_can_start(can_start)

    # -- connection -----------------------------------------------------

    def _on_connect_requested(self, port: str, baud: int, source: str) -> None:
        try:
            if source == SOURCE_MOCK:
                line_source = RealtimePacedLineSource(MockSampleSource())
                self._active_serial_conn = None
            else:
                if not port:
                    QMessageBox.warning(self, "연결 오류", "시리얼 포트를 선택하세요.")
                    return
                conn = serial.Serial(port, baud, timeout=1)
                self._active_serial_conn = conn
                line_source = SerialPortLineSource(conn)
        except serial.SerialException as exc:
            QMessageBox.warning(self, "연결 오류", f"포트를 열 수 없습니다: {exc}")
            return

        self._active_source_kind = source
        self._recent_sample_times.clear()
        self._total_valid_samples = 0
        self._first_sample_monotonic = None
        self._plot_first_unwrapped_us = None
        self.plot_panel.clear()

        self._worker = SerialWorker(line_source, LineParser(), TimeUnwrapper())
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.batch_ready.connect(self._on_batch_ready)
        self._worker.diagnostics_updated.connect(self._on_diagnostics_updated)
        self._worker.disconnected.connect(self._on_worker_disconnected)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

        self._connected = True
        self.acquisition_panel.set_connection_state(True, "연결됨")
        self._update_can_start()

    def _on_disconnect_requested(self) -> None:
        self._stop_worker()
        self._connected = False
        self.acquisition_panel.set_connection_state(False, "연결 해제됨")
        self._update_can_start()

    def _stop_worker(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        if self._active_serial_conn is not None:
            try:
                self._active_serial_conn.close()
            except Exception:
                pass
            self._active_serial_conn = None
        self._worker = None
        self._thread = None

    def _on_worker_disconnected(self, message: str) -> None:
        self._connected = False
        self.acquisition_panel.set_connection_state(False, f"연결 끊김: {message}")
        if self._is_recording and self._session_writer is not None:
            self._log_event(EventType.disconnect, message)
        self._update_can_start()

    # -- batch handling ----------------------------------------------------

    def _on_batch_ready(self, batch: list) -> None:
        if not batch:
            return

        now = time.monotonic()
        if self._first_sample_monotonic is None:
            self._first_sample_monotonic = now

        for _ in batch:
            self._recent_sample_times.append(now)
        cutoff = now - 5.0
        while self._recent_sample_times and self._recent_sample_times[0] < cutoff:
            self._recent_sample_times.popleft()
        self._total_valid_samples += len(batch)

        recent_hz = len(self._recent_sample_times) / 5.0
        overall_elapsed = max(now - self._first_sample_monotonic, 1e-6)
        overall_hz = self._total_valid_samples / overall_elapsed
        self.acquisition_panel.set_rate(recent_hz, overall_hz)
        self.acquisition_panel.set_last_received(
            datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        )

        if self._plot_first_unwrapped_us is None:
            self._plot_first_unwrapped_us = batch[0].time_us_unwrapped
        base_t = self._plot_first_unwrapped_us
        times_s = [(s.time_us_unwrapped - base_t) / 1_000_000 for s in batch]
        self.plot_panel.append_samples(
            times_s,
            [s.biceps_env for s in batch],
            [s.biceps_raw for s in batch],
            [s.brachio_env for s in batch],
            [s.brachio_raw for s in batch],
        )

        if self._is_recording and self._session_writer is not None:
            self._write_recording_batch(batch)

    def _on_diagnostics_updated(self, diag: dict) -> None:
        """Fires on a steady cadence even when zero valid samples have
        arrived, so a stuck connection (wrong baud rate, wrong port, no
        device sending) is visible instead of leaving the status panel
        frozen on its initial placeholder values."""
        estimated_missing = self._quality.estimated_missing_samples if self._quality else 0
        self.acquisition_panel.set_error_counts(
            diag["malformed_rows"], diag["out_of_range_rows"], estimated_missing
        )
        if diag["valid_rows"] == 0:
            total_lines = sum(diag.values())
            if total_lines == 0:
                self.acquisition_panel.set_last_received("수신 대기 중 (포트에서 아무 응답 없음)")
            else:
                self.acquisition_panel.set_last_received(
                    f"유효 샘플 없음 (누적 {total_lines}줄 수신 - baud rate/포트/펌웨어 확인 필요)"
                )

    def _write_recording_batch(self, batch: list) -> None:
        assert self._quality is not None
        assert self._session_writer is not None
        records: list[SampleRecord] = []
        host_start = self._recording_started_monotonic
        for sample in batch:
            if self._first_unwrapped_us is None:
                self._first_unwrapped_us = sample.time_us_unwrapped
            elapsed_s = (sample.time_us_unwrapped - self._first_unwrapped_us) / 1_000_000
            host_elapsed_s = max(time.monotonic() - host_start, 0.0)
            self._quality.record_sample(
                sample.time_us_unwrapped,
                sample.biceps_env,
                sample.biceps_raw,
                sample.brachio_env,
                sample.brachio_raw,
            )
            if sample.wrapped:
                self._quality.record_wrap()
            records.append(
                SampleRecord(
                    sample_index=self._sample_index,
                    device_time_us=sample.time_us,
                    device_time_us_unwrapped=sample.time_us_unwrapped,
                    elapsed_s=elapsed_s,
                    host_elapsed_s=host_elapsed_s,
                    biceps_env_adc=sample.biceps_env,
                    biceps_raw_adc=sample.biceps_raw,
                    brachio_env_adc=sample.brachio_env,
                    brachio_raw_adc=sample.brachio_raw,
                    label=self._current_label,
                )
            )
            self._sample_index += 1
        self._session_writer.write_samples(records)
        self.status_samples_label.setText(f"저장 샘플: {self._sample_index}")
        elapsed = time.monotonic() - self._recording_started_monotonic
        self.status_elapsed_label.setText(f"경과: {elapsed:0.1f}s")

    # -- labels / events -----------------------------------------------

    def _on_label_changed(self, label: str) -> None:
        previous = self._current_label
        self._current_label = label
        if self._is_recording and self._session_writer is not None and label != previous:
            self._log_event(EventType.label_change, "")

    def _on_user_event(self, note: str) -> None:
        if self._is_recording and self._session_writer is not None:
            self._log_event(EventType.user_marker, note)
        else:
            QMessageBox.information(self, "이벤트 표시", "기록 중에만 이벤트를 표시할 수 있습니다.")

    def _log_event(self, event_type: EventType, note: str) -> None:
        assert self._session_writer is not None
        elapsed_s = 0.0
        if self._first_unwrapped_us is not None:
            elapsed_s = max(time.monotonic() - self._recording_started_monotonic, 0.0)
        event = EventRecord(
            event_index=self._event_index,
            sample_index=self._sample_index,
            device_time_us_unwrapped=self._first_unwrapped_us or 0,
            elapsed_s=elapsed_s,
            event_type=event_type,
            label=self._current_label,
            note=note,
        )
        self._session_writer.write_event(event)
        self._event_index += 1

    # -- recording lifecycle -------------------------------------------

    def _on_start_recording(self) -> None:
        validation = self.participant_form.validate()
        if not validation.is_valid:
            QMessageBox.warning(self, "입력 오류", "필수 항목을 확인하세요.")
            return
        if not self.participant_form.consent_confirmed():
            QMessageBox.warning(self, "동의 필요", "연구 동의를 먼저 확인하세요.")
            return
        if not self._connected:
            QMessageBox.warning(self, "연결 필요", "장치를 먼저 연결하세요.")
            return

        private, public = self.participant_form.build_models()
        self._ensure_participant_registered(private, public)

        session_fields = self.acquisition_panel.session_field_values()
        self._session_id = generate_session_id()
        self._participant_id = private.participant_id
        self._session_writer = self.store.create_session_writer(self._session_id)
        self._quality = QualityAccumulator()
        self._sample_index = 0
        self._event_index = 0
        self._first_unwrapped_us = None
        self._recording_started_monotonic = time.monotonic()
        self._session_start_utc = datetime.now(timezone.utc).isoformat()
        self._session_fields = session_fields
        self._participant_public_snapshot = public.model_dump(mode="json")

        self._is_recording = True
        self.participant_form.set_locked(True)
        self.acquisition_panel.set_session_fields_locked(True)
        self.acquisition_panel.set_recording_active(True)
        self.status_path_label.setText(f"파일: {self.store.session_dir(self._session_id)}")
        self.status_warning_label.setText("")

    def _finish_recording(self, status: str) -> None:
        if self._session_writer is None or self._quality is None or self._session_id is None:
            return
        samples_path, events_path = self._session_writer.finalize()
        duration_s = max(time.monotonic() - self._recording_started_monotonic, 1e-6)
        end_utc = datetime.now(timezone.utc).isoformat()

        metadata = {
            "schema_version": SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "session_id": self._session_id,
            "participant_id": self._participant_id,
            "start_time_utc": self._session_start_utc,
            "end_time_utc": end_utc,
            "participant_public": self._participant_public_snapshot,
            "session_info": {
                "muscle": self._session_fields.muscle,
                "arm": self._session_fields.arm,
                "exercise": self._session_fields.exercise,
                "load_kg": self._session_fields.load_kg,
                "set_number": self._session_fields.set_number,
                "target_repetitions": self._session_fields.target_repetitions,
                "electrode_placement": self._session_fields.electrode_placement,
                "skin_prepared": self._session_fields.skin_prepared,
                "pre_fatigue_score": self._session_fields.pre_fatigue_score,
                "pain_score": self._session_fields.pain_score,
                "session_notes": self._session_fields.session_notes,
            },
            "serial_port": self.acquisition_panel.port_combo.currentText(),
            "baud_rate": self.acquisition_panel.baud_combo.currentText(),
            "input_source": self._active_source_kind,
            "firmware_spec": {
                "header": SERIAL_HEADER_LINE,
                "biceps_env_pin": BICEPS_ENV_PIN,
                "biceps_raw_pin": BICEPS_RAW_PIN,
                "brachio_env_pin": BRACHIO_ENV_PIN,
                "brachio_raw_pin": BRACHIO_RAW_PIN,
                "target_sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
                "target_sample_interval_us": TARGET_SAMPLE_INTERVAL_US,
                "adc_min": ADC_MIN_VALUE,
                "adc_max": ADC_MAX_VALUE,
            },
            "labels": list({self._current_label}),
            "status": status,
            "files": {
                "samples.csv": [
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
                ],
                "events.csv": [
                    "event_index",
                    "sample_index",
                    "device_time_us_unwrapped",
                    "elapsed_s",
                    "event_type",
                    "label",
                    "note",
                ],
            },
        }
        self.store.write_session_metadata(self._session_id, metadata)
        self.store.write_session_quality(self._session_id, self._quality.to_dict(duration_s))
        self.store.append_session_row(
            {
                "session_id": self._session_id,
                "participant_id": self._participant_id,
                "start_time_utc": self._session_start_utc,
                "end_time_utc": end_utc,
                "duration_s": f"{duration_s:.3f}",
                "muscle": self._session_fields.muscle,
                "arm": self._session_fields.arm,
                "exercise": self._session_fields.exercise,
                "load_kg": self._session_fields.load_kg or "",
                "set_number": self._session_fields.set_number or "",
                "target_repetitions": self._session_fields.target_repetitions or "",
                "pre_fatigue_score": self._session_fields.pre_fatigue_score,
                "pain_score": self._session_fields.pain_score or "",
                "expected_sample_rate_hz": TARGET_SAMPLE_RATE_HZ,
                "actual_sample_rate_hz": f"{self._quality.actual_sample_rate_hz(duration_s):.2f}",
                "valid_samples": self._quality.valid_samples,
                "status": status,
                "session_path": str(self.store.session_dir(self._session_id)),
            }
        )

        self._is_recording = False
        self.participant_form.set_locked(False)
        self.acquisition_panel.set_session_fields_locked(False)
        self.acquisition_panel.set_recording_active(False)
        self._session_writer = None
        self._update_can_start()
        return samples_path

    def _on_stop_recording(self) -> None:
        samples_path = self._finish_recording(SESSION_STATUS_COMPLETE)
        if samples_path is not None:
            QMessageBox.information(self, "저장 완료", f"세션이 저장되었습니다:\n{samples_path}")

    def _on_discard(self) -> None:
        if self._session_writer is None or self._session_id is None:
            return
        session_dir = self.store.session_dir(self._session_id)
        self._session_writer.close_without_finalize()
        import shutil

        shutil.rmtree(session_dir, ignore_errors=True)

        self._session_writer = None
        self._is_recording = False
        self.participant_form.set_locked(False)
        self.acquisition_panel.set_session_fields_locked(False)
        self.acquisition_panel.set_recording_active(False)
        self.status_path_label.setText("파일: -")
        self.status_samples_label.setText("저장 샘플: 0")
        self._update_can_start()

    def _ensure_participant_registered(self, private, public) -> None:
        if self._participant_already_registered(private.participant_id):
            return
        self.store.register_participant(private, public)

    def _participant_already_registered(self, participant_id: str) -> bool:
        import csv

        path = self.store.root / "participants_private.csv"
        if not path.exists():
            return False
        with open(path, newline="", encoding="utf-8") as fh:
            return any(row.get("participant_id") == participant_id for row in csv.DictReader(fh))

    # -- crash recovery ---------------------------------------------------

    def _prompt_recovery_if_needed(self) -> None:
        incomplete = self.store.find_incomplete_sessions()
        for session_id in incomplete:
            reply = QMessageBox.question(
                self,
                "미완료 세션 발견",
                f"이전에 완료되지 않은 세션이 있습니다: {session_id}\n복구하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.store.recover_session(session_id)
                self._mark_session_status(session_id, "recovered")

    def _mark_session_status(self, session_id: str, status: str) -> None:
        # sessions.csv may not have a row yet if the crash happened before
        # any row was appended; recovered .part files are still preserved
        # on disk either way, which is the load-bearing guarantee.
        pass

    # -- shutdown -----------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._is_recording:
            box = QMessageBox(self)
            box.setWindowTitle("기록 중")
            box.setText("기록 중인 세션이 있습니다. 어떻게 종료할까요?")
            save_btn = box.addButton("저장 후 종료", QMessageBox.ButtonRole.AcceptRole)
            continue_btn = box.addButton("계속 기록", QMessageBox.ButtonRole.RejectRole)
            discard_exit_btn = box.addButton(
                "미완료 상태로 종료", QMessageBox.ButtonRole.DestructiveRole
            )
            box.setDefaultButton(save_btn)
            box.exec()
            clicked = box.clickedButton()

            if clicked is continue_btn:
                event.ignore()
                return
            if clicked is save_btn:
                self._finish_recording(SESSION_STATUS_COMPLETE)
            elif clicked is discard_exit_btn:
                if self._session_writer is not None:
                    self._session_writer.fsync()
                    self._session_writer.close_without_finalize()
                    if self._session_id is not None:
                        self.store.append_session_row(
                            {
                                "session_id": self._session_id,
                                "participant_id": self._participant_id,
                                "status": SESSION_STATUS_INCOMPLETE,
                                "session_path": str(self.store.session_dir(self._session_id)),
                            }
                        )

        self._stop_worker()
        event.accept()
