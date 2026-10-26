"""Version 3 flow within the existing PyQt application."""

import csv
import json
from pathlib import Path
from threading import Thread
import time

import pyqtgraph as pg
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from emg_collector.multimodal.controller import CollectionController
from emg_collector.multimodal.schema import Consent, ProfileParser, Termination, Visit
from emg_collector.protocols import PilotProtocol
from emg_collector.runtime_paths import default_model_path
from emg_collector.ui.participant_form import ParticipantForm
from emg_collector.ui.common import (
    TERMINATION_LABELS,
    VideoPreview,
    WrappingCheckBox,
    prepare_resizable_dialog,
    wrap_form_labels,
)


class ResultSignals(QObject):
    result = pyqtSignal(dict)


def set_frame(label, frame):
    import cv2

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = QImage(
        rgb.data,
        rgb.shape[1],
        rgb.shape[0],
        rgb.strides[0],
        QImage.Format.Format_RGB888,
    ).copy()
    label.setPixmap(QPixmap.fromImage(image))


def optional_spin(maximum=1_000_000):
    spin = QDoubleSpinBox()
    spin.setRange(-1, maximum)
    spin.setValue(-1)
    spin.setSpecialValueText("미입력")
    return spin


class MultimodalDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.controller = None
        self.preflight_ok = False
        self.preflight_thread = None
        self.setWindowTitle("이두·삼두 EMG + MediaPipe 동시 측정·자동 라벨링 | PILOT")
        prepare_resizable_dialog(self)
        self.participant = ParticipantForm()
        self.existing = QComboBox()
        self.existing.addItem("신규 참가자", None)
        with (store.root / "participants_public.csv").open(
            newline="", encoding="utf-8"
        ) as fh:
            for row in csv.DictReader(fh):
                self.existing.addItem(row["participant_id"], row)
        self.existing.currentIndexChanged.connect(self._select_participant)
        self.synthetic = WrappingCheckBox("Mock (모든 산출물 synthetic=true)")
        self.mock_occlusion = WrappingCheckBox("Mock: 가림 구간 주입")
        self.mock_delay = QSpinBox()
        self.mock_delay.setRange(0, 1000)
        self.mock_delay.setSuffix(" ms / 50 samples")
        self.port = QLineEdit()
        self.port.setPlaceholderText("COM3")
        self.camera = QSpinBox()
        self.camera.setRange(0, 20)
        self.model = QLineEdit(str(default_model_path()))
        self.arm = QComboBox()
        self.arm.addItems(["right", "left"])
        self.load = QDoubleSpinBox()
        self.load.setRange(0, 150)
        self.load.setSuffix(" kg / 덤벨 1개")
        self.number = QSpinBox()
        self.number.setRange(1, 100)
        self.target = QSpinBox()
        self.target.setRange(-1, 1000)
        self.target.setValue(-1)
        self.target.setSpecialValueText("미정")
        self.rest = optional_spin()
        self.rest.setSuffix(" s")
        self.visit = QLineEdit("V-" + time.strftime("%Y%m%d"))
        self.hours = optional_spin()
        self.upper_hours = optional_spin()
        self.fatigue = optional_spin(10)
        self.pain = optional_spin(10)
        self.placement = QLineEdit()
        self.placement.setPlaceholderText("전극 위치·좌우·센서 부착 기록")
        self.skin = WrappingCheckBox("피부 준비 및 GPIO 33/34, 32/35 배선 확인")
        self.clothing = WrappingCheckBox(
            "따뜻한 실내, 전극 노출·소매/케이블 간섭 없음, 가동범위 확인"
        )
        self.pose_consent = WrappingCheckBox(
            "자세 좌표 수집 동의 (영상 미저장 시에도 연구자료로 저장)"
        )
        self.video_consent = WrappingCheckBox("판정용 원본 영상 저장 동의")
        self.access_consent = WrappingCheckBox("검토자의 영상 접근 동의")
        self.export_consent = WrappingCheckBox(
            "영상 내보내기 동의 (기본 export에는 항상 제외)"
        )
        self.protocol = PilotProtocol()
        self.protocol_label = QLabel(
            "unilateral_curl_pilot 0.1.0 | PILOT — 임계값·실제 동기 오차 미검증"
        )
        self.protocol_label.setWordWrap(True)
        self.protocol_button = QPushButton("프로토콜 JSON 선택")
        self.protocol_button.clicked.connect(self._protocol)
        self.preview_button = QPushButton("카메라·시리얼·추적 점검")
        self.preview_button.clicked.connect(self._preflight)
        self.start_button = QPushButton("이두·삼두 + MediaPipe 동시 기록 시작")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("선택 사유로 즉시 중지")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        self.pain_button = QPushButton("통증: 즉시 중지")
        self.pain_button.setEnabled(False)
        self.pain_button.clicked.connect(lambda: self._stop("pain_discomfort"))
        self.reason = QComboBox()
        self.reason.addItem("종료 사유 선택", None)
        for reason in Termination:
            self.reason.addItem(TERMINATION_LABELS[reason], reason.value)
        self.failure = QComboBox()
        self.failure.addItem("실패 시도 확인 불가", None)
        self.failure.addItem("실패 시도 없음", "__none__")
        self.status = QLabel(
            "센서 1 이두·센서 2 삼두와 카메라를 함께 기록합니다. MediaPipe 동작 단계·반복 판정이 두 EMG 신호에 시간으로 연결됩니다."
        )
        self.status.setWordWrap(True)
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.video = VideoPreview("카메라 미리보기")
        self.plot = pg.PlotWidget(title="실시간 RAW ADC | s1 이두 / s2 삼두")
        self.plot.setMinimumHeight(100)
        self.plot.addLegend()
        self.line1 = self.plot.plot(pen="#50aaff", name="이두")
        self.line2 = self.plot.plot(pen="#ffaa50", name="삼두")
        self.trace = []
        self.review_button = QPushButton("저장 세션 검토 / 수정")
        self.review_button.clicked.connect(self._review)
        self.export_button = QPushButton("검증 후 학습 입력 export")
        self.export_button.clicked.connect(self._export)
        self.recovery_button = QPushButton("미완료 데이터 확인·복구")
        self.recovery_button.clicked.connect(self._recover)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for title, widget in [
            ("기존 참가자", self.existing),
            ("", self.participant),
            ("", self.synthetic),
            ("", self.mock_occlusion),
            ("Mock 수신 batch 지연", self.mock_delay),
            ("시리얼 460800 baud", self.port),
            ("카메라", self.camera),
            ("MediaPipe 모델", self.model),
            ("프로토콜", self.protocol_label),
            ("", self.protocol_button),
            ("방문 ID", self.visit),
            ("최근 운동 후 시간(h)", self.hours),
            ("최근 상지운동 후 시간(h)", self.upper_hours),
            ("방문 피로(0–10)", self.fatigue),
            ("방문 통증(0–10)", self.pain),
            ("측정 팔", self.arm),
            ("실제 중량", self.load),
            ("세트 번호", self.number),
            ("계획 반복 수 (실제 한계와 별도)", self.target),
            ("직전 세트 후 휴식", self.rest),
            ("센서 1 이두 / 센서 2 삼두", self.placement),
            ("", self.skin),
            ("", self.clothing),
            ("", self.pose_consent),
            ("", self.video_consent),
            ("", self.access_consent),
            ("", self.export_consent),
        ]:
            form.addRow(title, widget)
        wrap_form_labels(form)
        self.setup = QGroupBox("참가자 → 방문 → 채널/복장 → 동의")
        self.setup.setLayout(form)
        self.setup_scroll = QScrollArea()
        self.setup_scroll.setWidgetResizable(True)
        self.setup_scroll.setWidget(self.setup)
        self.setup_scroll.setMinimumWidth(220)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_splitter = QSplitter(Qt.Orientation.Vertical)
        self.preview_splitter.setHandleWidth(8)
        self.preview_splitter.setChildrenCollapsible(False)
        self.preview_splitter.addWidget(self.video)
        self.preview_splitter.addWidget(self.plot)
        self.preview_splitter.setSizes([240, 160])
        right_layout.addWidget(self.preview_splitter, 2)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        for widget in [
            self.preview_button,
            self.start_button,
            self.reason,
            self.failure,
            self.status,
            self.review_button,
            self.export_button,
            self.recovery_button,
        ]:
            controls_layout.addWidget(widget)
        self.controls_scroll = QScrollArea()
        self.controls_scroll.setWidgetResizable(True)
        self.controls_scroll.setWidget(controls)
        self.controls_scroll.setMinimumSize(240, 100)
        right_layout.addWidget(self.controls_scroll, 1)
        stop_row = QHBoxLayout()
        stop_row.addWidget(self.stop_button)
        stop_row.addWidget(self.pain_button)
        right_layout.addLayout(stop_row)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.setup_scroll)
        self.main_splitter.addWidget(right)
        self.main_splitter.setSizes([450, 550])
        layout = QVBoxLayout(self)
        layout.addWidget(self.main_splitter)
        self.signals = ResultSignals()
        self.signals.result.connect(self._result)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        for edit in (self.port, self.model):
            edit.textChanged.connect(self._invalidate)
        self.camera.valueChanged.connect(self._invalidate)
        self.arm.currentIndexChanged.connect(self._invalidate)
        self.synthetic.toggled.connect(self._invalidate)

    def _invalidate(self, *args):
        self.preflight_ok = False

    def _select_participant(self):
        row = self.existing.currentData()
        if not row:
            from emg_collector.ui.participant_form import generate_participant_id

            self.participant.participant_id_edit.setText(generate_participant_id())
            return
        self.participant.participant_id_edit.setText(row["participant_id"])
        self.participant.name_edit.clear()
        # Registry columns remain compatible with v2; v3 additions live in snapshots.
        snapshot = {}
        for path in sorted(self.store.sessions_dir().glob("*/metadata.json")):
            try:
                metadata = json.loads(path.read_text(encoding="utf-8"))
                if metadata.get("participant_id") == row["participant_id"]:
                    snapshot = metadata.get("participant", snapshot)
            except (OSError, ValueError):
                continue
        for key, spin in [
            ("strength_sessions_per_week", self.participant.strength_sessions_spin),
            ("strength_training_months", self.participant.strength_months_spin),
        ]:
            spin.setValue(snapshot[key] if snapshot.get(key) is not None else -1)
        for key, spin in [
            ("age", self.participant.age_spin),
            ("height_cm", self.participant.height_spin),
            ("weight_kg", self.participant.weight_spin),
            ("exercise_sessions_per_week", self.participant.exercise_sessions_spin),
            ("exercise_minutes_per_week", self.participant.exercise_minutes_spin),
            ("days_since_last_exercise", self.participant.days_since_exercise_spin),
        ]:
            number = float(row[key]) if row[key] else spin.minimum()
            spin.setValue(int(number) if isinstance(spin, QSpinBox) else number)
        for key, combo in [
            ("sex", self.participant.sex_combo),
            ("dominant_arm", self.participant.dominant_arm_combo),
        ]:
            combo.setCurrentIndex(max(0, combo.findText(row[key])))

    def _protocol(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "프로토콜 선택", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            protocol = PilotProtocol.model_validate_json(
                Path(path).read_text(encoding="utf-8")
            )
            # This implementation only ships a pilot; external approval is not inferred.
            if protocol.status != "PILOT":
                raise ValueError(
                    "현재 구현은 PILOT 프로토콜만 지원합니다. 승인 절차·하드웨어 검증 후 확장하세요."
                )
            self.protocol = protocol
            self.protocol_label.setText(
                f"{protocol.protocol_id} {protocol.version} | PILOT"
            )
            self.preflight_ok = False
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _preflight(self):
        if self.preflight_thread and self.preflight_thread.is_alive():
            return
        options = (
            self.synthetic.isChecked(),
            self.camera.value(),
            self.port.text().strip(),
            self.model.text(),
            self.arm.currentText(),
        )
        self.preview_button.setEnabled(False)
        self.status.setText("모델·카메라·헤더 점검 중 (최대 약 8초)...")

        def run():
            cap = None
            conn = None
            pose = None
            try:
                import cv2
                from emg_collector.pose.metrics import metrics

                if options[0]:
                    from emg_collector.acquisition.camera_worker import synthetic_frame

                    frame, rows = synthetic_frame(0, time.monotonic_ns())
                else:
                    import serial
                    from emg_collector.pose.pose_worker import MediaPipePose

                    pose = MediaPipePose(
                        options[3],
                        "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
                    )
                    cap = cv2.VideoCapture(options[1])
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError(
                            "카메라 읽기 실패; 카메라 인덱스·권한·연결을 확인하세요."
                        )
                    rows = pose.infer(frame, time.monotonic_ns())
                    conn = serial.Serial(options[2], 460800, timeout=0.5)
                    parser = ProfileParser("biceps_triceps_v3")
                    deadline = time.monotonic() + 5
                    sample = None
                    while time.monotonic() < deadline and sample is None:
                        line = conn.readline().decode("utf-8", errors="replace")
                        if not parser.header_seen and not line.startswith("time_us,"):
                            continue
                        sample = parser.parse(line, time.monotonic_ns())
                    if sample is None:
                        raise RuntimeError(
                            "일치하는 헤더/샘플 없음: ESP32를 리셋하고 신규 펌웨어를 확인하세요."
                        )
                result = metrics(
                    {r["landmark_id"]: r for r in rows},
                    frame.shape[1],
                    frame.shape[0],
                    options[4],
                )
                self.signals.result.emit(
                    {
                        "kind": "preflight",
                        "ok": result["quality_mask"] == "ok",
                        "frame": frame,
                        "message": f"추적 {result['quality_mask']} / 팔꿈치 {result['elbow_angle_deg']}°; software-only 동기 오차 미측정 (PILOT)",
                    }
                )
            except Exception as exc:
                self.signals.result.emit(
                    {"kind": "preflight", "ok": False, "message": str(exc)}
                )
            finally:
                if cap:
                    cap.release()
                if conn:
                    conn.close()
                if pose:
                    pose.close()

        self.preflight_thread = Thread(target=run, daemon=True)
        self.preflight_thread.start()

    def _result(self, result):
        self.status.setText(result["message"])
        if result["kind"] == "preflight":
            self.preflight_ok = result["ok"]
            self.preview_button.setEnabled(True)
            if "frame" in result:
                set_frame(self.video, result["frame"])
        elif result["kind"] == "export":
            self.export_button.setEnabled(True)
        elif result["kind"] == "recovery":
            self.recovery_button.setEnabled(True)

    def _start(self):
        if not self.preflight_ok:
            self.status.setText("먼저 카메라·시리얼·추적 점검을 통과하세요.")
            return
        try:
            private, public = self.participant.build_models()
            consent = Consent(
                research=self.participant.consent_confirmed(),
                pose_coordinates=self.pose_consent.isChecked(),
                video_storage=self.video_consent.isChecked(),
                video_access=self.access_consent.isChecked(),
                video_export=self.export_consent.isChecked(),
            )

            def value(spin):
                return None if spin.value() < 0 else spin.value()

            visit = Visit(
                visit_id=self.visit.text(),
                hours_since_exercise=value(self.hours),
                hours_since_upper_body_exercise=value(self.upper_hours),
                fatigue_score=value(self.fatigue),
                pain_score=value(self.pain),
            )
            self.controller = CollectionController(
                self.store.root,
                public,
                consent,
                visit,
                self.protocol,
                arm=self.arm.currentText(),
                load_kg=self.load.value(),
                set_number=self.number.value(),
                rest_before_s=value(self.rest),
                target_repetitions=(
                    None if self.target.value() < 0 else self.target.value()
                ),
                port=self.port.text().strip(),
                camera_index=self.camera.value(),
                model_path=self.model.text(),
                synthetic=self.synthetic.isChecked(),
                placement=self.placement.text(),
                skin_prepared=self.skin.isChecked(),
                clothing_confirmed=self.clothing.isChecked(),
                mock_occlusion=self.mock_occlusion.isChecked(),
                mock_receive_batch_delay_ms=self.mock_delay.value(),
            )
            # Participant registration is small; stream flush/encoding/inference run on workers.
            with (self.store.root / "participants_public.csv").open(
                newline="", encoding="utf-8"
            ) as fh:
                known = {r["participant_id"] for r in csv.DictReader(fh)}
            if public.participant_id not in known:
                self.store.register_participant(private, public)
            self.controller.start()
            self.setup.setEnabled(False)
            self.recovery_button.setEnabled(False)
            self.start_button.setEnabled(False)
            self.preview_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.pain_button.setEnabled(True)
            self.reason.setCurrentIndex(0)
            self.failure.clear()
            self.failure.addItem("실패 시도 확인 불가", None)
            self.failure.addItem("실패 시도 없음", "__none__")
            self.trace = []
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))

    def _stop(self, reason=None):
        if not self.controller:
            return
        reason = reason if isinstance(reason, str) else self.reason.currentData()
        if reason is None:
            self.status.setText(
                "종료 사유를 선택하세요. 통증은 통증 즉시 중지 버튼을 사용할 수 있습니다."
            )
            return
        self.controller.stop(reason, self.failure.currentData())
        self.stop_button.setEnabled(False)
        self.pain_button.setEnabled(False)
        self.status.setText("기록 중지됨. worker 종료·영상 닫기·manifest 검증 중...")

    def _tick(self):
        c = self.controller
        if c is None:
            return
        data = c.preview()
        if "frame" in data:
            set_frame(self.video, data["frame"])
        if "sample" in data:
            sample = data["sample"]
            self.trace.append(
                (sample["host_receive_ns"] / 1e9, sample["s1_raw"], sample["s2_raw"])
            )
            self.trace = self.trace[-200:]
            self.line1.setData([v[0] for v in self.trace], [v[1] for v in self.trace])
            self.line2.setData([v[0] for v in self.trace], [v[2] for v in self.trace])
        attempts = data.get("attempts", [])
        for attempt in attempts:
            if self.failure.findData(attempt["attempt_id"]) < 0:
                self.failure.addItem(
                    f"{attempt['attempt_id']} ({attempt['validity']})",
                    attempt["attempt_id"],
                )
        if c.done.is_set():
            self.controller = None
            self.setup.setEnabled(True)
            self.recovery_button.setEnabled(True)
            self.start_button.setEnabled(True)
            self.preview_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.pain_button.setEnabled(False)
            self.status.setText(
                "완료: "
                + str(getattr(c, "writer", None).root if hasattr(c, "writer") else "")
                + " | "
                + (
                    "; ".join(c.errors)
                    if c.errors
                    else "자동 판정 provisional; 검토 필요"
                )
            )
            self.last_session = c.writer.root if hasattr(c, "writer") else None
            return
        counts = {
            key: sum(a["validity"] == key for a in attempts)
            for key in ("valid", "invalid", "unknown")
        }
        self.status.setText(
            f"{c.phase} | EMG {c.sample_count}, frames {c.frame_count}, {data.get('phase','ready')} | "
            f"유효 {counts['valid']} / 무효 {counts['invalid']} / 불명 {counts['unknown']} | "
            f"각도 {data.get('metrics',{}).get('elbow_angle_deg')} | 추론 생략 {c.inference_skipped}"
        )

    def _review(self):
        from emg_collector.ui.multimodal_review import MultimodalReviewDialog

        path = QFileDialog.getExistingDirectory(
            self,
            "검토할 v3 세션",
            str(getattr(self, "last_session", None) or self.store.sessions_dir()),
        )
        if path:
            dialog = MultimodalReviewDialog(Path(path), self)
            dialog.exec()

    def _export(self):
        path = QFileDialog.getExistingDirectory(
            self, "내보내기 상위 폴더", str(self.store.root)
        )
        if not path:
            return
        synthetic = self.synthetic.isChecked()
        output = Path(path) / ("training_" + time.strftime("%Y%m%d_%H%M%S"))
        self.export_button.setEnabled(False)

        def run():
            try:
                from emg_collector.storage.training_export import export_training

                result = export_training(
                    self.store.root, output, synthetic=synthetic, allow_pilot=True
                )
                message = f"PILOT export {output}: {result}"
            except Exception as exc:
                message = f"export 실패: {exc}"
            self.signals.result.emit({"kind": "export", "message": message})

        Thread(target=run, daemon=True).start()

    def _recover(self):
        self.recovery_button.setEnabled(False)

        def run():
            messages = []
            for session_id in self.store.find_incomplete_sessions():
                try:
                    self.store.recover_session(session_id)
                    messages.append(session_id + ": 원본 보존 복구; v3는 미완료 유지")
                except (OSError, ValueError) as exc:
                    messages.append(session_id + ": " + str(exc))
            self.signals.result.emit(
                {
                    "kind": "recovery",
                    "message": "\n".join(messages) or "미완료 데이터가 없습니다.",
                }
            )

        Thread(target=run, daemon=True).start()

    def closeEvent(self, event):
        if self.controller and not self.controller.done.is_set():
            self._stop("other")
            self.status.setText(
                "즉시 중지 요청됨. 저장 완료 후 창을 닫으세요. 종료 사유 other는 검토에서 수정하세요."
            )
            event.ignore()
            return
        if self.preflight_thread and self.preflight_thread.is_alive():
            event.ignore()
            return
        event.accept()
