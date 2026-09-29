"""Participant registration panel (work order section 6.2).

Validation is delegated to the pydantic models in :mod:`emg_collector.models`
so the accepted ranges live in exactly one place. This widget's job is to
collect raw text/number input, surface validation errors next to the
offending field, and hand back typed models once everything is valid.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pydantic import ValidationError

from emg_collector.models import (
    DominantArm,
    ParticipantPrivate,
    ParticipantPublic,
    Sex,
)

ERROR_STYLE = "border: 1px solid #d64545;"
NORMAL_STYLE = ""


def generate_participant_id() -> str:
    return "P-" + secrets.token_hex(3).upper()


@dataclass
class ParticipantValidationResult:
    is_valid: bool
    field_errors: dict[str, str] = field(default_factory=dict)


class ParticipantForm(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.participant_id_edit = QLineEdit(generate_participant_id())
        self.regenerate_id_button = QPushButton("새 ID 생성")
        self.name_edit = QLineEdit()
        self.age_spin = QSpinBox()
        self.age_spin.setRange(0, 200)
        self.sex_combo = QComboBox()
        for sex in Sex:
            self.sex_combo.addItem(sex.value, sex)
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(0, 999)
        self.height_spin.setSuffix(" cm")
        self.weight_spin = QDoubleSpinBox()
        self.weight_spin.setRange(0, 999)
        self.weight_spin.setSuffix(" kg")
        self.weight_spin.setSpecialValueText("미입력")
        self.exercise_sessions_spin = QSpinBox()
        self.exercise_sessions_spin.setRange(0, 999)
        self.exercise_minutes_spin = QSpinBox()
        self.exercise_minutes_spin.setRange(0, 100000)
        self.exercise_minutes_spin.setSpecialValueText("미입력")
        self.days_since_exercise_spin = QDoubleSpinBox()
        self.days_since_exercise_spin.setRange(0, 3650)
        self.dominant_arm_combo = QComboBox()
        for arm in DominantArm:
            self.dominant_arm_combo.addItem(arm.value, arm)
        self.notes_edit = QPlainTextEdit()
        self.notes_warning_label = QLabel(
            "전화번호, 학번, 주소 등 식별 가능한 정보를 적지 마세요."
        )
        self.consent_checkbox = QCheckBox("연구 참여 동의를 확인했습니다.")

        self._error_labels: dict[str, QLabel] = {}
        self._field_widgets = {
            "participant_id": self.participant_id_edit,
            "name": self.name_edit,
            "age": self.age_spin,
            "height_cm": self.height_spin,
            "exercise_sessions_per_week": self.exercise_sessions_spin,
            "days_since_last_exercise": self.days_since_exercise_spin,
        }

        self._build_layout()
        self._connect_signals()

    def _build_layout(self) -> None:
        form = QFormLayout()

        id_row = QHBoxLayout()
        id_row.addWidget(self.participant_id_edit)
        id_row.addWidget(self.regenerate_id_button)
        form.addRow("피험자 ID *", id_row)
        self._add_error_row(form, "participant_id")

        form.addRow("이름 *", self.name_edit)
        self._add_error_row(form, "name")

        form.addRow("나이 *", self.age_spin)
        self._add_error_row(form, "age")

        form.addRow("성별", self.sex_combo)
        form.addRow("키(cm) *", self.height_spin)
        self._add_error_row(form, "height_cm")

        form.addRow("몸무게(kg)", self.weight_spin)
        form.addRow("주당 운동 횟수 *", self.exercise_sessions_spin)
        self._add_error_row(form, "exercise_sessions_per_week")

        form.addRow("주당 총 운동 시간(분)", self.exercise_minutes_spin)
        form.addRow("최근 운동 후 경과일 *", self.days_since_exercise_spin)
        self._add_error_row(form, "days_since_last_exercise")

        form.addRow("주로 사용하는 팔", self.dominant_arm_combo)
        form.addRow("설명/특이사항", self.notes_edit)
        form.addRow("", self.notes_warning_label)
        form.addRow("", self.consent_checkbox)

        layout = QVBoxLayout(self)
        layout.addLayout(form)

    def _add_error_row(self, form: QFormLayout, field_name: str) -> None:
        label = QLabel("")
        label.setStyleSheet("color: #d64545;")
        self._error_labels[field_name] = label
        form.addRow("", label)

    def _connect_signals(self) -> None:
        self.regenerate_id_button.clicked.connect(
            lambda: self.participant_id_edit.setText(generate_participant_id())
        )
        for widget in (
            self.participant_id_edit,
            self.name_edit,
        ):
            widget.textChanged.connect(self.changed.emit)
        for widget in (
            self.age_spin,
            self.height_spin,
            self.weight_spin,
            self.exercise_sessions_spin,
            self.exercise_minutes_spin,
            self.days_since_exercise_spin,
        ):
            widget.valueChanged.connect(self.changed.emit)
        for widget in (self.sex_combo, self.dominant_arm_combo):
            widget.currentIndexChanged.connect(self.changed.emit)
        self.notes_edit.textChanged.connect(self.changed.emit)
        self.consent_checkbox.stateChanged.connect(self.changed.emit)

    # -- locking during recording ----------------------------------------

    def set_locked(self, locked: bool) -> None:
        """Identity fields must not change mid-recording (section 6.6)."""
        self.participant_id_edit.setEnabled(not locked)
        self.regenerate_id_button.setEnabled(not locked)

    # -- validation ----------------------------------------------------------

    def consent_confirmed(self) -> bool:
        return self.consent_checkbox.isChecked()

    def _optional_weight(self) -> float | None:
        return None if self.weight_spin.value() == 0 else self.weight_spin.value()

    def _optional_minutes(self) -> int | None:
        return None if self.exercise_minutes_spin.value() == 0 else self.exercise_minutes_spin.value()

    def build_models(self) -> tuple[ParticipantPrivate, ParticipantPublic]:
        """Raise pydantic.ValidationError if the current input is invalid."""
        private = ParticipantPrivate(
            participant_id=self.participant_id_edit.text().strip(),
            name=self.name_edit.text().strip(),
        )
        public = ParticipantPublic(
            participant_id=self.participant_id_edit.text().strip(),
            age=self.age_spin.value(),
            sex=self.sex_combo.currentData(),
            height_cm=self.height_spin.value(),
            weight_kg=self._optional_weight(),
            dominant_arm=self.dominant_arm_combo.currentData(),
            exercise_sessions_per_week=self.exercise_sessions_spin.value(),
            exercise_minutes_per_week=self._optional_minutes(),
            days_since_last_exercise=self.days_since_exercise_spin.value(),
            participant_notes=self.notes_edit.toPlainText().strip(),
        )
        return private, public

    def validate(self) -> ParticipantValidationResult:
        for label in self._error_labels.values():
            label.setText("")
        for widget in self._field_widgets.values():
            widget.setStyleSheet(NORMAL_STYLE)

        try:
            self.build_models()
        except ValidationError as exc:
            errors: dict[str, str] = {}
            for err in exc.errors():
                field_name = str(err["loc"][0])
                errors[field_name] = err["msg"]
                if field_name in self._error_labels:
                    self._error_labels[field_name].setText(err["msg"])
                if field_name in self._field_widgets:
                    self._field_widgets[field_name].setStyleSheet(ERROR_STYLE)
            return ParticipantValidationResult(is_valid=False, field_errors=errors)

        return ParticipantValidationResult(is_valid=True)
