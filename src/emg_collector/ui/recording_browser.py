"""Browse saved measurements without exposing filesystem selection to the user."""

import json
from pathlib import Path
from threading import Thread
from datetime import datetime, timezone, timedelta

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from emg_collector.ui.common import prepare_resizable_dialog


class BrowserSignals(QObject):
    loaded = pyqtSignal(list)


def list_recordings(dataset_root):
    records = []
    for root in sorted((Path(dataset_root) / "sessions").glob("*"), reverse=True):
        if not root.is_dir():
            continue
        try:
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            quality = json.loads((root / "quality.json").read_text(encoding="utf-8")) if (root / "quality.json").exists() else {}
            modern = (root / "sets.csv").exists()
            manifest_path = root / "completion_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
            status = manifest.get("status", "complete" if (root / "samples.csv").exists() else "incomplete")
            start = metadata.get("start_time_utc", "")
            if start:
                start = datetime.fromisoformat(start).astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
            records.append(dict(root=root, modern=modern, start=start, status=status,
                                samples=quality.get("valid_samples", "—"),
                                rate=quality.get("actual_sample_rate_hz"),
                                truth=(root / "ground_truth.jsonl").exists(), error=""))
        except (OSError, ValueError, TypeError) as exc:
            records.append(dict(root=root, modern=False, start="", status="읽기 오류", samples="—", rate=None, truth=False, error=str(exc)))
    return sorted(records, key=lambda r: (r["start"], r["root"].name), reverse=True)


class RecordingBrowserDialog(QDialog):
    def __init__(self, dataset_root, parent=None):
        super().__init__(parent)
        self.dataset_root = Path(dataset_root)
        self.records = []
        self.setWindowTitle("저장 기록 · 그래프 확인 · 정답 데이터")
        prepare_resizable_dialog(self)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["측정 시작 (한국)", "기록 ID", "저장 상태", "EMG 샘플", "수신 Hz", "수동 정답"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda *_: self._open())
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.table.itemSelectionChanged.connect(self._selection)
        self.open_button = QPushButton("영상·근전도·각도 보기")
        self.open_button.clicked.connect(self._open)
        self.truth_button = QPushButton("정답 데이터 입력 / 수정")
        self.truth_button.clicked.connect(self._truth)
        refresh = QPushButton("새로고침")
        refresh.clicked.connect(self.refresh)
        folder = QPushButton("다른 데이터 폴더")
        folder.clicked.connect(self._folder)
        row = QHBoxLayout()
        for button in (self.open_button, self.truth_button, refresh, folder):
            row.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.summary)
        layout.addLayout(row)
        self.signals = BrowserSignals()
        self.signals.loaded.connect(self._loaded)
        self.refresh()

    def refresh(self):
        self.open_button.setEnabled(False)
        self.truth_button.setEnabled(False)
        self.summary.setText("저장 기록을 찾는 중...")
        root = self.dataset_root
        self.load_thread = Thread(target=lambda: self.signals.loaded.emit(list_recordings(root)), daemon=True)
        self.load_thread.start()

    def _loaded(self, records):
        self.records = records
        self.table.setRowCount(len(records))
        for i, r in enumerate(records):
            values = [r["start"], r["root"].name,
                      {"complete": "저장 완료", "incomplete": "미완료", "recovered": "복구됨"}.get(r["status"], r["status"]),
                      str(r["samples"]), f"{r['rate']:.1f}" if r["rate"] is not None else "—",
                      "입력됨" if r["truth"] else "미입력"]
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        if records:
            self.table.selectRow(0)
            self._selection()
        else:
            self.summary.setText("저장된 측정이 없습니다. 데이터 폴더: " + str(self.dataset_root))

    def _selected(self):
        row = self.table.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    def _selection(self):
        r = self._selected()
        if not r:
            return
        ready = not r["error"] and (r["root"] / "samples.csv").exists()
        self.open_button.setEnabled(ready)
        self.truth_button.setEnabled(ready and r["modern"])
        self.summary.setText(str(r["root"]) + ("\n" + r["error"] if r["error"] else "\n미완료 기록도 확인할 수 있습니다. 수동 정답은 원본과 별도 저장됩니다."))

    def _open(self):
        r = self._selected()
        if not r or not self.open_button.isEnabled():
            return
        if r["modern"]:
            from emg_collector.ui.multimodal_review import MultimodalReviewDialog
            dialog = MultimodalReviewDialog(r["root"], self)
        else:
            from emg_collector.ui.session_viewer import SessionViewerDialog
            dialog = SessionViewerDialog(r["root"], self)
        dialog.exec()

    def _truth(self):
        r = self._selected()
        if r and self.truth_button.isEnabled():
            from emg_collector.ui.ground_truth import GroundTruthDialog
            GroundTruthDialog(r["root"], self).exec()
            self.refresh()

    def _folder(self):
        path = QFileDialog.getExistingDirectory(self, "datasets 폴더 선택", str(self.dataset_root))
        if path:
            self.dataset_root = Path(path)
            self.refresh()

    def closeEvent(self, event):
        if self.load_thread.is_alive():
            event.ignore()
            return
        event.accept()
