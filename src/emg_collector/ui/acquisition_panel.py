"""Connection, session-metadata, label/event, and recording-control UI
(work order sections 6.1, 6.3, 6.4, 6.6). Wiring to the actual serial
worker / session writer lives in :mod:`main_window`; this widget only
emits intent signals and exposes setters for status display so it can be
unit tested independently of any live connection.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from emg_collector.config import (
    BICEPS_ENV_PIN,
    BICEPS_RAW_PIN,
    BRACHIO_ENV_PIN,
    BRACHIO_RAW_PIN,
    DEFAULT_BAUD_RATE,
    DEFAULT_LABEL,
    DEFAULT_LABELS,
    TARGET_SAMPLE_RATE_HZ,
)

SOURCE_SERIAL = "serial"
SOURCE_MOCK = "mock"


@dataclass
class SessionFieldValues:
    muscle: str
    arm: str
    exercise: str
    load_kg: float | None
    set_number: int | None
    target_repetitions: int | None
    electrode_placement: str
    skin_prepared: bool
    pre_fatigue_score: int
    pain_score: int | None
    session_notes: str


class AcquisitionPanel(QWidget):
    connect_requested = pyqtSignal(str, int, str)  # port, baud, source
    disconnect_requested = pyqtSignal()
    refresh_ports_requested = pyqtSignal()
    start_recording_requested = pyqtSignal()
    stop_recording_requested = pyqtSignal()
    discard_requested = pyqtSignal()
    label_changed = pyqtSignal(str)
    user_event_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_connection_group()
        self._build_session_group()
        self._build_label_group()
        self._build_recording_group()

        layout = QVBoxLayout(self)
        layout.addWidget(self.connection_group)
        layout.addWidget(self.session_group)
        layout.addWidget(self.label_group)
        layout.addWidget(self.recording_group)
        layout.addStretch(1)

    # -- 6.1 connection ---------------------------------------------------

    def _build_connection_group(self) -> None:
        self.connection_group = QGroupBox("장치 연결")
        self.port_combo = QComboBox()
        self.refresh_ports_button = QPushButton("포트 새로고침")
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems(["460800", "115200", "230400", "921600"])
        self.baud_combo.setCurrentText(str(DEFAULT_BAUD_RATE))

        self.source_serial_radio = QRadioButton("ESP32 시리얼")
        self.source_mock_radio = QRadioButton("모의 EMG 신호")
        self.source_serial_radio.setChecked(True)

        self.connect_button = QPushButton("연결")
        self.disconnect_button = QPushButton("연결 해제")
        self.disconnect_button.setEnabled(False)

        self.connection_status_label = QLabel("연결 해제됨")
        self.last_received_label = QLabel("마지막 수신: -")
        self.rate_label = QLabel("수신률: - Hz (최근 5초) / - Hz (전체)")
        self.error_counts_label = QLabel(
            "잘못된 행: 0 · 범위 오류: 0 · 추정 누락: 0"
        )

        form = QFormLayout()
        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo)
        port_row.addWidget(self.refresh_ports_button)
        form.addRow("시리얼 포트", port_row)
        form.addRow("Baud rate", self.baud_combo)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_serial_radio)
        source_row.addWidget(self.source_mock_radio)
        form.addRow("입력 소스", source_row)
        connect_row = QHBoxLayout()
        connect_row.addWidget(self.connect_button)
        connect_row.addWidget(self.disconnect_button)
        form.addRow("", connect_row)
        form.addRow(self.connection_status_label)
        form.addRow(self.last_received_label)
        form.addRow(self.rate_label)
        form.addRow(self.error_counts_label)
        self.connection_group.setLayout(form)

        self.refresh_ports_button.clicked.connect(self.refresh_ports_requested.emit)
        self.connect_button.clicked.connect(self._emit_connect_requested)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)

    def _emit_connect_requested(self) -> None:
        source = SOURCE_SERIAL if self.source_serial_radio.isChecked() else SOURCE_MOCK
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "Baud rate는 정수여야 합니다.")
            return
        self.connect_requested.emit(self.port_combo.currentText(), baud, source)

    def set_available_ports(self, ports: list[str]) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if current in ports:
            self.port_combo.setCurrentText(current)

    def set_connection_state(self, connected: bool, status_text: str) -> None:
        self.connection_status_label.setText(status_text)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        self.source_serial_radio.setEnabled(not connected)
        self.source_mock_radio.setEnabled(not connected)

    def set_last_received(self, text: str) -> None:
        self.last_received_label.setText(f"마지막 수신: {text}")

    def set_rate(self, recent_hz: float, overall_hz: float) -> None:
        self.rate_label.setText(f"수신률: {recent_hz:.1f} Hz (최근 5초) / {overall_hz:.1f} Hz (전체)")

    def set_error_counts(self, malformed: int, out_of_range: int, estimated_missing: int) -> None:
        self.error_counts_label.setText(
            f"잘못된 행: {malformed} · 범위 오류: {out_of_range} · 추정 누락: {estimated_missing}"
        )

    def is_mock_source_selected(self) -> bool:
        return self.source_mock_radio.isChecked()

    # -- 6.3 session metadata --------------------------------------------

    def _build_session_group(self) -> None:
        self.session_group = QGroupBox("측정 세션 정보")
        self.muscle_combo = QComboBox()
        self.muscle_combo.setEditable(True)
        self.muscle_combo.addItems(["이두근", "삼두근"])
        self.arm_left_radio = QRadioButton("왼쪽")
        self.arm_right_radio = QRadioButton("오른쪽")
        self.arm_left_radio.setChecked(True)
        self.exercise_combo = QComboBox()
        self.exercise_combo.setEditable(True)
        self.exercise_combo.addItems(["팔꿈치 굴곡", "신전", "최대 수축", "휴식"])
        self.load_spin = QDoubleSpinBox()
        self.load_spin.setRange(0, 999)
        self.load_spin.setSpecialValueText("미입력")
        self.set_number_spin = QSpinBox()
        self.set_number_spin.setRange(0, 999)
        self.set_number_spin.setSpecialValueText("미입력")
        self.target_reps_spin = QSpinBox()
        self.target_reps_spin.setRange(0, 999)
        self.target_reps_spin.setSpecialValueText("미입력")
        self.electrode_placement_edit = QLineEdit()
        self.skin_prepared_checkbox = QCheckBox("피부 준비 완료")
        self.pre_fatigue_spin = QSpinBox()
        self.pre_fatigue_spin.setRange(0, 10)
        self.pain_score_spin = QSpinBox()
        self.pain_score_spin.setRange(-1, 10)
        self.pain_score_spin.setSpecialValueText("미입력")
        self.pain_score_spin.setValue(-1)
        self.session_notes_edit = QPlainTextEdit()
        self.sample_rate_label = QLabel(f"{TARGET_SAMPLE_RATE_HZ} Hz")
        self.pins_label = QLabel(
            f"이두근 ENV: GPIO{BICEPS_ENV_PIN} / RAW: GPIO{BICEPS_RAW_PIN}  ·  "
            f"상완요골근 ENV: GPIO{BRACHIO_ENV_PIN} / RAW: GPIO{BRACHIO_RAW_PIN}"
        )

        form = QFormLayout()
        form.addRow("측정 부위/근육", self.muscle_combo)
        arm_row = QHBoxLayout()
        arm_row.addWidget(self.arm_left_radio)
        arm_row.addWidget(self.arm_right_radio)
        form.addRow("측정 팔", arm_row)
        form.addRow("운동 종류", self.exercise_combo)
        form.addRow("부하(kg)", self.load_spin)
        form.addRow("세트 번호", self.set_number_spin)
        form.addRow("반복 횟수 목표", self.target_reps_spin)
        form.addRow("전극 위치 설명", self.electrode_placement_edit)
        form.addRow("", self.skin_prepared_checkbox)
        form.addRow("운동 전 자각 피로도(0-10)", self.pre_fatigue_spin)
        form.addRow("통증 점수(0-10)", self.pain_score_spin)
        form.addRow("세션 설명", self.session_notes_edit)
        form.addRow("예상 샘플링 주파수", self.sample_rate_label)
        form.addRow("측정 센서 핀 (4개)", self.pins_label)
        self.session_group.setLayout(form)

    def session_field_values(self) -> SessionFieldValues:
        return SessionFieldValues(
            muscle=self.muscle_combo.currentText().strip(),
            arm="left" if self.arm_left_radio.isChecked() else "right",
            exercise=self.exercise_combo.currentText().strip(),
            load_kg=None if self.load_spin.value() == 0 else self.load_spin.value(),
            set_number=None if self.set_number_spin.value() == 0 else self.set_number_spin.value(),
            target_repetitions=(
                None if self.target_reps_spin.value() == 0 else self.target_reps_spin.value()
            ),
            electrode_placement=self.electrode_placement_edit.text().strip(),
            skin_prepared=self.skin_prepared_checkbox.isChecked(),
            pre_fatigue_score=self.pre_fatigue_spin.value(),
            pain_score=None if self.pain_score_spin.value() < 0 else self.pain_score_spin.value(),
            session_notes=self.session_notes_edit.toPlainText().strip(),
        )

    def set_session_fields_locked(self, locked: bool) -> None:
        for widget in (
            self.muscle_combo,
            self.arm_left_radio,
            self.arm_right_radio,
            self.exercise_combo,
            self.load_spin,
            self.set_number_spin,
            self.target_reps_spin,
        ):
            widget.setEnabled(not locked)

    # -- 6.4 label / events -----------------------------------------------

    def _build_label_group(self) -> None:
        self.label_group = QGroupBox("라벨 및 이벤트")
        self.label_combo = QComboBox()
        self.label_combo.addItems(DEFAULT_LABELS)
        self.label_combo.setCurrentText(DEFAULT_LABEL)
        self.event_note_edit = QLineEdit()
        self.event_note_edit.setPlaceholderText("이벤트 메모 (선택)")
        self.mark_event_button = QPushButton("사용자 이벤트 표시")

        layout = QHBoxLayout()
        layout.addWidget(QLabel("현재 라벨"))
        layout.addWidget(self.label_combo)
        layout.addWidget(self.event_note_edit)
        layout.addWidget(self.mark_event_button)
        self.label_group.setLayout(layout)

        self.label_combo.currentTextChanged.connect(self.label_changed.emit)
        self.mark_event_button.clicked.connect(
            lambda: self.user_event_requested.emit(self.event_note_edit.text().strip())
        )

    def current_label(self) -> str:
        return self.label_combo.currentText()

    # -- 6.6 recording controls -------------------------------------------

    def _build_recording_group(self) -> None:
        self.recording_group = QGroupBox("기록 제어")
        self.start_button = QPushButton("기록 시작")
        self.stop_button = QPushButton("기록 종료 및 저장")
        self.discard_button = QPushButton("현재 세션 폐기")
        self.stop_button.setEnabled(False)
        self.discard_button.setEnabled(False)

        layout = QHBoxLayout()
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.discard_button)
        self.recording_group.setLayout(layout)

        self.start_button.clicked.connect(self.start_recording_requested.emit)
        self.stop_button.clicked.connect(self.stop_recording_requested.emit)
        self.discard_button.clicked.connect(self._confirm_discard)

    def _confirm_discard(self) -> None:
        reply = QMessageBox.question(
            self,
            "세션 폐기",
            "현재 기록 중인 세션을 폐기하시겠습니까? 저장되지 않은 데이터는 삭제됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.discard_requested.emit()

    def set_recording_active(self, active: bool) -> None:
        self.start_button.setEnabled(not active)
        self.stop_button.setEnabled(active)
        self.discard_button.setEnabled(active)

    def set_can_start(self, can_start: bool) -> None:
        if not self.stop_button.isEnabled():
            self.start_button.setEnabled(can_start)
