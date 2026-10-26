"""Shared host-time cursor for video, EMG, angles and editable attempts."""

import json
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread

import pyqtgraph as pg
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFileDialog,
    QLabel,
    QLineEdit,
    QAbstractItemView,
    QPlainTextEdit,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from emg_collector.labeling.review import (
    append_review,
    effective_review,
    read_csv,
    read_sets,
    read_attempts,
    review_history,
)
from emg_collector.labeling.review_contract import (
    evidence_context,
    disagreement_fields,
    recover_review_transaction,
)
from emg_collector.sync.clock_alignment import aligned_samples, load_clock_mappings
from emg_collector.quality.window import QualityPolicy
from emg_collector.multimodal.schema import Termination
from emg_collector.ui.multimodal_panel import set_frame
from emg_collector.ui.review_editing import ReviewEditing
from emg_collector.ui.common import (
    TERMINATION_LABELS,
    VideoPreview,
    WrappingCheckBox,
    prepare_resizable_dialog,
    wrap_form_labels,
)


class ReviewSignals(QObject):
    loaded = pyqtSignal(dict)
    frame = pyqtSignal(object)
    message = pyqtSignal(str)
    saved = pyqtSignal(dict)


class MultimodalReviewDialog(ReviewEditing, QDialog):
    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.setWindowTitle("v3 검토 — 영상·EMG·각도 공통 시간축")
        prepare_resizable_dialog(self)
        self.signals = ReviewSignals()
        self.signals.loaded.connect(self._loaded)
        self.signals.frame.connect(lambda frame: set_frame(self.video, frame))
        self.signals.message.connect(self._message)
        self.signals.saved.connect(self._saved)
        self.seek_queue = Queue(maxsize=1)
        self.stop_event = Event()
        self.data = None
        self.edit_operations = []
        self.status = QLabel("세션 로딩 중...")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.video = VideoPreview("영상 접근 동의 확인 중")
        self.emg = pg.PlotWidget(title="RAW EMG ADC")
        self.angle = pg.PlotWidget(title="팔꿈치 각도 (deg)")
        self.angle.setXLink(self.emg)
        self.cursors = []
        for plot in (self.emg, self.angle):
            plot.setMinimumHeight(100)
            plot.setLabel("bottom", "session host time", units="s")
            cursor = pg.InfiniteLine(pos=0, pen="#eeeeee")
            plot.addItem(cursor)
            self.cursors.append(cursor)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.valueChanged.connect(self._seek)
        self.table = QTableWidget(0, 7)
        self.table.setMinimumHeight(100)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemChanged.connect(self._sync_failure)
        self.table.setHorizontalHeaderLabels(
            [
                "attempt_id",
                "start_host_ns",
                "end_host_ns",
                "validity",
                "reasons JSON",
                "ROM deg",
                "phases JSON",
            ]
        )
        self.reason = QComboBox()
        for reason in Termination:
            self.reason.addItem(TERMINATION_LABELS[reason], reason.value)
        self.failure = QComboBox()
        self.failure.addItem("실패 시도 확인 불가", None)
        self.failure.addItem("실패 시도 없음", "__none__")
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("비식별 reviewer_id")
        self.revision_reason = QLineEdit()
        self.revision_reason.setPlaceholderText("수정 이유 / 판정 근거")
        self.objective = WrappingCheckBox("영상·EMG·각도·종료 규칙을 검토했습니다")
        self.adjudication = WrappingCheckBox(
            "이전 독립 판정과 불일치 조정 완료 (이유 필수)"
        )
        self.mode = QComboBox()
        self.mode.addItem("독립 판정 (원 자동 결과에서 시작)", "independent")
        self.mode.addItem("불일치 조정 (두 독립 평가 비교)", "adjudication")
        self.mode.addItem("초안 / 미완료 평가", "draft")
        self.assessment_a = QComboBox()
        self.assessment_b = QComboBox()
        self.comparison = QPlainTextEdit()
        self.comparison.setReadOnly(True)
        self.comparison.setMaximumHeight(160)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.assessment_a.currentIndexChanged.connect(self._mode_changed)
        self.assessment_b.currentIndexChanged.connect(self._mode_changed)
        self.save_button = QPushButton("판정 revision 저장")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        self.labels_button = QPushButton(
            "저장된 검토 라벨 + 이두·삼두 EMG CSV 내보내기"
        )
        self.labels_button.setEnabled(False)
        self.labels_button.clicked.connect(self._export_labels)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for label, widget in [
            ("검토 모드", self.mode),
            ("비교 평가 1", self.assessment_a),
            ("비교 평가 2", self.assessment_b),
            ("종료 사유", self.reason),
            ("최초 기술적 실패 시도", self.failure),
            ("검토자", self.reviewer),
            ("변경 이유", self.revision_reason),
            ("", self.objective),
            ("", self.adjudication),
        ]:
            form.addRow(label, widget)
        wrap_form_labels(form)
        self.plot_splitter = QSplitter(Qt.Orientation.Vertical)
        self.plot_splitter.setHandleWidth(8)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.addWidget(self.emg)
        self.plot_splitter.addWidget(self.angle)
        self.media_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.media_splitter.setHandleWidth(8)
        self.media_splitter.setChildrenCollapsible(False)
        self.media_splitter.addWidget(self.video)
        self.media_splitter.addWidget(self.plot_splitter)
        self.media_splitter.setSizes([400, 600])
        timeline = QWidget()
        timeline_layout = QVBoxLayout(timeline)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.addWidget(self.media_splitter)
        timeline_layout.addWidget(self.slider)
        review_controls = QWidget()
        controls_layout = QVBoxLayout(review_controls)
        controls_layout.addLayout(form)
        controls_layout.addWidget(self.comparison)
        self.edit_bar = QWidget()
        edit_layout = QHBoxLayout(self.edit_bar)
        for text, operation in (
            ("시도 추가", "add"),
            ("삭제", "delete"),
            ("분할", "split"),
            ("병합", "merge"),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, op=operation: self._edit(op))
            edit_layout.addWidget(button)
        controls_layout.addWidget(self.edit_bar)
        self.reload_button = QPushButton("판정 다시 불러오기")
        self.reload_button.clicked.connect(self._reload_review)
        self.recover_button = QPushButton("중단된 검토 저장 복구")
        self.recover_button.clicked.connect(lambda: self._reload_review(recover=True))
        controls_layout.addWidget(self.reload_button)
        controls_layout.addWidget(self.recover_button)
        controls_layout.addWidget(self.save_button)
        controls_layout.addWidget(self.labels_button)
        controls_layout.addWidget(self.status)
        self.review_scroll = QScrollArea()
        self.review_scroll.setWidgetResizable(True)
        self.review_scroll.setWidget(review_controls)
        self.review_scroll.setMinimumHeight(100)
        self.sections = QSplitter(Qt.Orientation.Vertical)
        self.sections.setHandleWidth(8)
        self.sections.setChildrenCollapsible(False)
        self.sections.addWidget(timeline)
        self.sections.addWidget(self.table)
        self.sections.addWidget(self.review_scroll)
        self.sections.setSizes([330, 180, 240])
        layout = QVBoxLayout(self)
        layout.addWidget(self.sections)
        self.save_thread = None

        self._reload_review()
        self.decoder_thread = Thread(target=self._decoder, daemon=True)
        self.decoder_thread.start()

    def _reload_review(self, checked=False, recover=False):
        def load():
            try:
                if recover:
                    recover_review_transaction(self.root)
                sets, attempts = read_sets(self.root), read_attempts(self.root)
                if len(sets) != 1:
                    raise ValueError("현재 검토 UI는 세션당 1개 세트를 지원합니다.")
                metadata = json.loads(
                    (self.root / "metadata.json").read_text(encoding="utf-8")
                )
                self.signals.loaded.emit(
                    {
                        "sets": sets,
                        "attempts": attempts,
                        "metadata": metadata,
                        "samples": read_csv(self.root, "samples.csv"),
                        "metrics": read_csv(self.root, "pose_metrics.csv"),
                        "frames": read_csv(self.root, "frame_timestamps.csv"),
                        "history": review_history(self.root),
                        "evidence": evidence_context(self.root),
                        "aligned_samples": aligned_samples(
                            read_csv(self.root, "samples.csv"),
                            load_clock_mappings(self.root),
                            max_uncertainty_ns=QualityPolicy.model_validate(
                                metadata.get("quality_policy", {})
                            ).maximum_uncertainty_ns,
                        ),
                        "effective_sets": effective_review(self.root)[0],
                        "effective_attempts": effective_review(self.root)[1],
                    }
                )
            except Exception as exc:
                self.signals.message.emit(str(exc))

        self.load_thread = Thread(target=load, daemon=True)
        self.load_thread.start()

    def _loaded(self, data):
        self.data = data
        self.expected_revision = (
            data["history"][-1]["revision"] if data["history"] else None
        )
        self.current_evidence = data["evidence"]
        record = data["sets"][0]
        self.origin = data["metadata"]["start_host_ns"]
        self.end = record.end_ns or self.origin + 1
        samples = [
            r for r in data["aligned_samples"] if r["measurement_host_ns"] is not None
        ]
        verified = bool(samples) and all(
            r["alignment_status"] == "aligned" for r in samples
        )
        self.emg.setTitle(
            "RAW EMG ADC — "
            + (
                "측정 시각 정렬"
                if verified
                else "정렬 미검증: 추정 시간축, 물리 동기 확인 필요"
            )
        )
        for plot, cursor in zip((self.emg, self.angle), self.cursors):
            plot.clear()
            plot.addItem(cursor)
        metrics = data["metrics"]
        self.emg.plot(
            [(int(s["measurement_host_ns"]) - self.origin) / 1e9 for s in samples],
            [int(s["s1_raw"]) for s in samples],
            pen="#50aaff",
        )
        self.emg.plot(
            [(int(s["measurement_host_ns"]) - self.origin) / 1e9 for s in samples],
            [int(s["s2_raw"]) for s in samples],
            pen="#ffaa50",
        )
        valid = [m for m in metrics if m["quality_mask"] == "ok"]
        self.angle.plot(
            [(int(m["capture_host_ns"]) - self.origin) / 1e9 for m in valid],
            [float(m["elbow_angle_deg"]) for m in valid],
            pen="#66dd88",
        )
        self._populate_assessments(data["history"])
        self._render(data["sets"], data["attempts"])
        self.save_button.setEnabled(True)
        self.labels_button.setEnabled(True)
        self.video_allowed = bool(
            data["metadata"]["consent"]["video_storage"]
            and data["metadata"]["consent"]["video_access"]
        )
        if not self.video_allowed:
            self.video.setText("저장·접근 동의 영상 없음: exact 라벨 확정 불가")
        self.status.setText(
            "자동 판정은 provisional입니다. PILOT은 서로 다른 2명의 독립 판정 후 일치/조정 시 확정됩니다."
        )
        self._mode_changed()
        self._seek(0)

    def _seek(self, value):
        if not self.data:
            return
        ns = int(self.origin + (self.end - self.origin) * value / 10000)
        for cursor in self.cursors:
            cursor.setValue((ns - self.origin) / 1e9)
        if not self.video_allowed:
            return
        frames = [
            f
            for f in self.data["frames"]
            if int(f["capture_host_ns"]) <= ns and f["saved"] == "True"
        ]
        if not frames:
            return
        item = frames[-1]
        try:
            self.seek_queue.put_nowait(item)
        except Full:
            try:
                self.seek_queue.get_nowait()
            except Empty:
                pass
            try:
                self.seek_queue.put_nowait(item)
            except Full:
                pass

    def _decoder(self):
        import cv2

        cap = None
        segment = None
        try:
            while not self.stop_event.is_set():
                try:
                    item = self.seek_queue.get(timeout=0.1)
                except Empty:
                    continue
                if item["segment"] != segment:
                    if cap:
                        cap.release()
                    segment = item["segment"]
                    cap = cv2.VideoCapture(str(self.root / "video" / segment))
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(item["segment_frame"]))
                okay, frame = cap.read()
                if okay:
                    self.signals.frame.emit(frame)
                else:
                    self.signals.message.emit(
                        "영상 프레임 디코딩 실패: 검토 확정 전에 영상·매핑을 확인하세요."
                    )
        finally:
            if cap:
                cap.release()

    def _save(self):
        try:
            attempts = self._table_attempts()
            record = self._current_record()
            reviewer = self.reviewer.text()
            reason = self.revision_reason.text()
            objective = self.objective.isChecked()
            adjudication = self.adjudication.isChecked()
            mode = self.mode.currentData()
            ids = [self.assessment_a.currentData(), self.assessment_b.currentData()]
            differences = []
            if mode == "adjudication" and all(i in self.assessments for i in ids):
                differences = (
                    disagreement_fields(*(self.assessments[i] for i in ids))
                    if adjudication
                    else []
                )
            options = dict(
                mode=mode,
                expected_revision=self.expected_revision,
                base_revision=(
                    "acquisition" if mode == "independent" else self.expected_revision
                ),
                evidence=self.current_evidence.copy(),
                assessment_ids=ids if mode == "adjudication" else None,
                resolved_disagreements=differences,
                edit_operations=list(self.edit_operations),
            )
            self.save_button.setEnabled(False)
            self.labels_button.setEnabled(False)

            def save():
                try:
                    entry = append_review(
                        self.root,
                        reviewer,
                        reason,
                        [record],
                        attempts,
                        objective,
                        adjudication,
                        **options,
                    )
                    self.signals.saved.emit({"entry": entry})
                except Exception as exc:
                    self.signals.message.emit(f"저장 실패: {exc}")

            self.save_thread = Thread(target=save, daemon=True)
            self.save_thread.start()
        except (ValueError, KeyError) as exc:
            self.status.setText(str(exc))

    def _message(self, message):
        self.status.setText(message)
        if self.data:
            self.save_button.setEnabled(True)
            self.labels_button.setEnabled(True)

    def _export_labels(self):
        output, _ = QFileDialog.getSaveFileName(
            self,
            "저장된 검토 라벨과 이두·삼두 EMG 내보내기",
            str(self.root.parent.parent / (self.root.name + "_labeled.csv")),
            "CSV (*.csv)",
        )
        if not output:
            return
        self.save_button.setEnabled(False)
        self.labels_button.setEnabled(False)

        def export():
            try:
                from emg_collector.labeling.sample_labels import write_labeled_samples

                count = write_labeled_samples(self.root, output, reviewed=True)
                self.signals.message.emit(
                    f"EMG + 저장된 MediaPipe 검토 라벨 {count}행: {output}"
                )
            except (OSError, ValueError) as exc:
                self.signals.message.emit(f"라벨 CSV 내보내기 실패: {exc}")

        self.save_thread = Thread(target=export, daemon=True)
        self.save_thread.start()

    def closeEvent(self, event):
        if self.save_thread and self.save_thread.is_alive():
            event.ignore()
            return
        self.stop_event.set()
        self.decoder_thread.join(timeout=0.3)
        event.accept()
