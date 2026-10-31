"""Manual elbow-angle and body-stability labels in session seconds."""

import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QVBoxLayout,
)
from emg_collector.ui.common import prepare_resizable_dialog
from emg_collector.labeling.review import read_sets
from emg_collector.storage.ground_truth import ManualTruth, TruthInterval, truth_history, save_truth, export_truth, export_training_truth


class GroundTruthDialog(QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.setWindowTitle("정답 데이터 입력 — " + self.root.name)
        prepare_resizable_dialog(self)
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("입력자 ID")
        self.target_angle = QDoubleSpinBox()
        self.target_angle.setRange(0, 180)
        self.target_angle.setValue(90)
        self.target_angle.setSuffix(" °")
        self.note = QLineEdit()
        self.note.setPlaceholderText("판정 근거, 관찰 내용")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["시작 (세션 초)", "종료 (세션 초)", "팔꿈치 정답 각도 (°)", "허리", "둔부 / 골반", "판정 메모"])
        self.info = QLabel("해당 각도를 실제로 유지한 시간 구간에 정답 각도를 입력하세요. 180°는 편 팔입니다.\n허리·둔부는 각각 고정/움직임/판단 불가로 표시합니다. 구간은 [시작, 종료)이며 자동 측정값과 별도 저장됩니다.\n자동 고정 판단은 카메라를 고정한 상태에서 첫 유효 자세와 비교한 영상 추정입니다.")
        self.info.setWordWrap(True)
        form = QFormLayout()
        for label, widget in [("입력자 *", self.reviewer), ("새 구간 정답 각도", self.target_angle), ("전체 메모", self.note)]:
            form.addRow(label, widget)
        self.add_button = QPushButton("각도 유지 구간 추가")
        self.add_button.clicked.connect(lambda: self._add())
        delete = QPushButton("선택 구간 삭제")
        delete.clicked.connect(self._delete)
        self.save_button = QPushButton("정답 저장")
        self.save_button.clicked.connect(self._save)
        self.export_button = QPushButton("저장된 정답 CSV 내보내기")
        self.export_button.clicked.connect(self._export)
        self.training_button = QPushButton("EMG + 정답 학습 CSV 내보내기")
        self.training_button.clicked.connect(self._export_training)
        edits = QHBoxLayout()
        for button in (self.add_button, delete):
            edits.addWidget(button)
        actions = QHBoxLayout()
        actions.addWidget(self.save_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.training_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addLayout(form)
        layout.addWidget(self.table)
        layout.addLayout(edits)
        layout.addLayout(actions)
        layout.addWidget(self.status)
        self.duration = 0
        self.expected_revision = None
        try:
            metadata = json.loads((self.root / "metadata.json").read_text(encoding="utf-8"))
            record = read_sets(self.root)[0]
            self.origin = metadata["start_host_ns"]
            if record.end_ns is None:
                raise ValueError("측정을 종료하고 저장한 뒤 입력하세요.")
            self.duration = (record.end_ns - self.origin) / 1e9
            history = truth_history(self.root)
            if history:
                entry = history[-1]
                self.expected_revision = entry["revision"]
                data = ManualTruth.model_validate(entry["data"])
                self.reviewer.setText(data.reviewer_id)
                self.note.setText(data.note)
                for interval in data.intervals:
                    self._add(interval)
            self.status.setText(f"측정 길이 {self.duration:.3f}초 | 저장된 정답을 불러왔습니다." if history else f"측정 길이 {self.duration:.3f}초 | 아직 입력된 정답이 없습니다.")
            self.export_button.setEnabled(bool(history))
            self.training_button.setEnabled(bool(history))
        except (OSError, ValueError, KeyError, IndexError) as exc:
            self.save_button.setEnabled(False)
            self.add_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.training_button.setEnabled(False)
            self.status.setText(str(exc))

    def _add(self, interval=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in [(0, interval.start_s if interval else 0),
                           (1, interval.end_s if interval else min(1, self.duration))]:
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(0, max(self.duration, 0))
            spin.setValue(value)
            self.table.setCellWidget(row, col, spin)
        angle = QDoubleSpinBox()
        angle.setRange(0, 180)
        angle.setDecimals(1)
        angle.setValue(interval.elbow_angle_deg if interval else self.target_angle.value())
        self.table.setCellWidget(row, 2, angle)
        for col, value in [(3, interval.trunk_fixed if interval else None), (4, interval.pelvis_fixed if interval else None)]:
            combo = QComboBox()
            for label, code in [("판단 불가", None), ("고정", True), ("움직임", False)]:
                combo.addItem(label, code)
            combo.setCurrentIndex(0 if value is None else (1 if value else 2))
            self.table.setCellWidget(row, col, combo)
        self.table.setCellWidget(row, 5, QLineEdit(interval.note if interval else ""))
        self.table.resizeColumnsToContents()

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        for row in rows:
            self.table.removeRow(row)

    def _save(self):
        try:
            truth = ManualTruth(
                reviewer_id=self.reviewer.text().strip(), note=self.note.text(),
                intervals=[TruthInterval(start_s=self.table.cellWidget(i, 0).value(),
                                         end_s=self.table.cellWidget(i, 1).value(),
                                         elbow_angle_deg=self.table.cellWidget(i, 2).value(),
                                         trunk_fixed=self.table.cellWidget(i, 3).currentData(),
                                         pelvis_fixed=self.table.cellWidget(i, 4).currentData(),
                                         note=self.table.cellWidget(i, 5).text()) for i in range(self.table.rowCount())],
            )
            entry = save_truth(self.root, truth, self.expected_revision)
            self.expected_revision = entry["revision"]
            self.export_button.setEnabled(True)
            self.training_button.setEnabled(True)
            self.status.setText("정답 저장 완료 · 수정 이력 보존 | " + str(self.root / "ground_truth.jsonl"))
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "저장된 정답 CSV 내보내기", str(self.root.parent.parent / (self.root.name + "_ground_truth.csv")), "CSV (*.csv)")
        if path:
            try:
                export_truth(self.root, path)
                self.status.setText("저장된 정답 CSV 내보내기 완료: " + path)
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))

    def _export_training(self):
        path, _ = QFileDialog.getSaveFileName(self, "EMG + 각도 정답 학습 CSV", str(self.root.parent.parent / (self.root.name + "_angle_training.csv")), "CSV (*.csv)")
        if path:
            try:
                count = export_training_truth(self.root, path)
                self.status.setText(f"EMG + 수동 각도·허리·둔부 정답 {count}행 저장: {path} | 수신 시간 기준 · 물리 동기 미검증")
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))
