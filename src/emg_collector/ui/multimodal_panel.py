"""Version 3 flow within the existing PyQt application."""

from pathlib import Path
from threading import Event, Thread
import time
import uuid

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
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from emg_collector.multimodal.controller import CollectionController
from emg_collector.acquisition.serial_worker import SerialPortLineSource
from emg_collector.pose.overlay import draw_pose
from emg_collector.multimodal.schema import Consent, ProfileParser, Termination, Visit
from emg_collector.protocols import PilotProtocol
from emg_collector.runtime_paths import default_model_path, resolve_model_path
from emg_collector.ui.participant_form import ParticipantForm
from emg_collector.ui.common import (
    body_stability_text,
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


class MultimodalDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.controller = None
        self.measurement_started = False
        self.preflight_ok = False
        self.preflight_error = "먼저 카메라·시리얼 점검을 실행하세요."
        self.preflight_thread = None
        self.preflight_stop = Event()
        self.preview_start_pending = False
        self.preview_close_pending = False
        self.setWindowTitle("전완·이두 EMG + MediaPipe 동시 측정·자동 라벨링 | PILOT")
        prepare_resizable_dialog(self)
        self.participant = ParticipantForm(required_only=True, single_measurement=True)
        self.synthetic = QComboBox()
        self.synthetic.addItem("실장치", False)
        self.synthetic.addItem("모의 입력 (synthetic)", True)
        self.diagnostic_alignment = QComboBox()
        self.diagnostic_alignment.addItem("검증된 정렬만 사용", False)
        self.diagnostic_alignment.addItem("진단용: 미검증 정렬 허용", True)
        self.mock_occlusion = QComboBox()
        self.mock_occlusion.addItem("가림 없음", False)
        self.mock_occlusion.addItem("가림 구간 주입", True)
        self.mock_delay = QSpinBox()
        self.mock_delay.setRange(0, 1000)
        self.mock_delay.setSuffix(" ms / 50 samples")
        self.port = QLineEdit()
        self.port.setPlaceholderText("COM3")
        self.camera = QSpinBox()
        self.camera.setRange(0, 20)
        self.model = QLineEdit(str(default_model_path()))
        self.model_auto_button = QPushButton("모델 자동 찾기")
        self.model_auto_button.clicked.connect(self._find_model)
        self.model_browse_button = QPushButton("모델 파일 선택")
        self.model_browse_button.clicked.connect(self._browse_model)
        self.arm = QComboBox()
        self.arm.addItem("오른팔", "right")
        self.arm.addItem("왼팔", "left")
        self.load = QDoubleSpinBox()
        self.load.setRange(0, 150)
        self.load.setSuffix(" kg")
        self.load.setSingleStep(0.5)
        self.load.setToolTip(
            "덤벨 한 개의 무게입니다. 사용하는 개수는 아래에서 따로 입력하세요."
        )
        self.dumbbell_count = QSpinBox()
        self.dumbbell_count.setRange(1, 100)
        self.dumbbell_count.setSuffix(" 개")
        self.placement = QLineEdit()
        self.placement.setPlaceholderText("전극 위치·좌우·센서 부착 기록")
        self.pose_consent = WrappingCheckBox(
            "자세 좌표 수집 동의 (영상 미저장 시에도 연구자료로 저장)"
        )
        self.video_consent = WrappingCheckBox("판정용 원본 영상 저장 동의")
        self.access_consent = WrappingCheckBox("검토자의 영상 접근 동의")
        self.protocol = PilotProtocol()
        self.protocol_label = QLabel(
            "unilateral_curl_pilot 0.1.0 | PILOT — 임계값·실제 동기 오차 미검증"
        )
        self.protocol_label.setWordWrap(True)
        self.protocol_button = QPushButton("프로토콜 JSON 선택")
        self.protocol_button.clicked.connect(self._protocol)
        self.preview_button = QPushButton("카메라·시리얼·추적 점검")
        self.preview_button.clicked.connect(self._preflight)
        self.start_button = QPushButton("전완·이두 + MediaPipe 동시 기록 시작")
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
        self.status = QLabel("필수 항목 입력 → 장치 점검 → 기록 시작")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.video = VideoPreview("카메라 미리보기")
        self.plot = pg.PlotWidget(title="실시간 RAW ADC | s1 전완 / s2 이두")
        self.plot.setMinimumHeight(100)
        self.plot.setLabel("bottom", "기록 시간", units="s")
        self.plot.setLabel("left", "ADC")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.addLegend()
        self.line1 = self.plot.plot(pen="#50aaff", name="전완")
        self.line2 = self.plot.plot(pen="#ffaa50", name="이두")
        self.trace = []
        self.review_button = QPushButton("저장 기록 검토 / 수정")
        self.review_button.clicked.connect(self._review)
        self.records_button = QPushButton("저장 기록 보기 / 정답 입력")
        self.records_button.clicked.connect(self._records)
        self.export_button = QPushButton("검증 후 학습 입력 export")
        self.export_button.clicked.connect(self._export)
        self.recovery_button = QPushButton("미완료 데이터 확인·복구")
        self.recovery_button.clicked.connect(self._recover)
        self.tools_button = QPushButton("저장 데이터 관리")
        tools_menu = QMenu(self.tools_button)
        for button in (self.review_button, self.export_button, self.recovery_button):
            button.setParent(self)
            button.hide()
            tools_menu.addAction(button.text(), button.click)
        self.tools_button.setMenu(tools_menu)
        self.device_settings = QDialog(self)
        self.device_settings.setWindowTitle("장치·진단 설정")
        prepare_resizable_dialog(self.device_settings)
        settings_form = QFormLayout()
        for title, widget in [
            ("MediaPipe 모델", self.model),
            ("", self.model_auto_button),
            ("", self.model_browse_button),
            ("프로토콜", self.protocol_label),
            ("", self.protocol_button),
            ("입력 모드", self.synthetic),
            ("Mock 가림", self.mock_occlusion),
            ("Mock 수신 지연", self.mock_delay),
            ("export 정렬", self.diagnostic_alignment),
        ]:
            settings_form.addRow(title, widget)
        wrap_form_labels(settings_form)
        settings_body = QWidget()
        settings_body.setLayout(settings_form)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(settings_body)
        settings_layout = QVBoxLayout(self.device_settings)
        settings_layout.addWidget(settings_scroll)
        settings_close = QPushButton("닫기")
        settings_close.clicked.connect(self.device_settings.accept)
        settings_layout.addWidget(settings_close)
        self.settings_button = QPushButton("장치·진단 설정")
        self.settings_button.clicked.connect(self.device_settings.exec)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for title, widget in [
            ("", self.participant),
            ("시리얼 포트 *", self.port),
            ("카메라", self.camera),
            ("", self.settings_button),
            ("측정 팔 *", self.arm),
            ("덤벨 무게 *", self.load),
            ("덤벨 개수 *", self.dumbbell_count),
            ("전극 위치 *", self.placement),
            ("", self.pose_consent),
            ("", self.video_consent),
            ("", self.access_consent),
        ]:
            form.addRow(title, widget)
        wrap_form_labels(form)
        self.setup = QGroupBox("필수 수집 정보")
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
            self.records_button,
            self.tools_button,
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
        self.synthetic.currentIndexChanged.connect(self._invalidate)

    def _find_model(self):
        try:
            path = resolve_model_path()
            self.model.setText(str(path))
            self.status.setText("모델 자동 탐색 완료: " + str(path))
        except FileNotFoundError as exc:
            self.status.setText(str(exc))

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "MediaPipe 모델 선택", self.model.text(), "Pose model (*.task)")
        if path:
            self.model.setText(path)

    def _records(self):
        from emg_collector.ui.recording_browser import RecordingBrowserDialog

        dialog = RecordingBrowserDialog(self.store.root, self)
        dialog.exec()

    def _invalidate(self, *args):
        self.preflight_ok = False
        self.preflight_stop.set()

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
            self.preflight_stop.set()
            self.preview_button.setEnabled(False)
            return
        try:
            self.model.setText(str(resolve_model_path(self.model.text())))
        except FileNotFoundError as exc:
            self.preflight_ok = False
            self.preflight_error = str(exc)
            self.status.setText(str(exc))
            return
        self.preflight_ok = False
        self.trace = []
        self.line1.clear()
        self.line2.clear()
        self.preflight_stop = Event()
        stop = self.preflight_stop
        options = (
            self.synthetic.currentData(),
            self.camera.value(),
            self.port.text().strip(),
            self.model.text(),
            self.arm.currentData(),
        )
        self.preview_button.setText("점검 중지")
        self.status.setText("모델·카메라·헤더 점검 중 (최대 약 8초)...")

        def run():
            cap = None
            conn = None
            pose = None
            serial_thread = None
            stream_stop = Event()
            stream_errors = []
            try:
                import cv2
                from emg_collector.pose.metrics import metrics, BodyStabilityTracker

                stability = BodyStabilityTracker()

                if options[0]:
                    from emg_collector.acquisition.camera_worker import synthetic_frame

                    frame, rows = synthetic_frame(0, time.perf_counter_ns())
                else:
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
                    rows = pose.infer(frame, time.perf_counter_ns())
                    from emg_collector.acquisition.esp32_serial import open_esp32_stream

                    conn = open_esp32_stream(options[2])
                    source = SerialPortLineSource(conn)
                    parser = ProfileParser("biceps_triceps_v3")
                    deadline = time.monotonic() + 5
                    sample = None
                    while not stop.is_set() and time.monotonic() < deadline and sample is None:
                        line = source.next_line()
                        if not parser.header_seen and not line.strip().startswith("time_us,"):
                            continue
                        sample = parser.parse(line, time.perf_counter_ns())
                    if stop.is_set():
                        return
                    if sample is None:
                        raise RuntimeError(
                            "일치하는 헤더/샘플 없음: ESP32를 리셋하고 신규 펌웨어를 확인하세요."
                        )
                def stream_emg():
                    try:
                        if options[0]:
                            from emg_collector.acquisition.mock_source import MockSampleSource

                            mock = MockSampleSource()
                            preview_parser = ProfileParser("biceps_triceps_v3")
                            preview_parser.parse(preview_parser.header, time.perf_counter_ns())
                        batch = [] if options[0] else [sample.model_dump()]
                        last_valid = time.monotonic()
                        last_emit = last_valid
                        while not stop.is_set() and not stream_stop.is_set():
                            if options[0]:
                                stop.wait(0.002)
                                parsed = preview_parser.parse(mock.next_line(), time.perf_counter_ns())
                            else:
                                try:
                                    parsed = parser.parse(source.next_line(), time.perf_counter_ns())
                                except ValueError as exc:
                                    if "header" in str(exc):
                                        raise
                                    parsed = None
                            now = time.monotonic()
                            if parsed is not None:
                                batch.append(parsed.model_dump())
                                last_valid = now
                            if now - last_valid > 3:
                                raise RuntimeError("근전도 수신이 3초 이상 중단되었습니다. 시리얼 연결을 확인하세요.")
                            if batch and now - last_emit >= 0.05:
                                self.signals.result.emit({"kind": "preflight_emg", "emg_samples": batch})
                                batch = []
                                last_emit = now
                    except Exception as exc:
                        stream_errors.append(str(exc))

                serial_thread = Thread(target=stream_emg, daemon=True)
                serial_thread.start()
                while not stop.is_set():
                    if stream_errors:
                        raise RuntimeError(stream_errors[0])
                    if options[0]:
                        frame, rows = synthetic_frame(0, time.perf_counter_ns())
                    else:
                        ok, frame = cap.read()
                        if not ok:
                            raise RuntimeError("카메라 프레임 수신 실패; 연결을 확인하고 다시 점검하세요.")
                        rows = pose.infer(frame, time.perf_counter_ns())
                    result = metrics(
                        {r["landmark_id"]: r for r in rows},
                        frame.shape[1], frame.shape[0], options[4],
                    )
                    result.update(stability.update({r["landmark_id"]: r for r in rows}, frame.shape[1], frame.shape[0]))
                    angle = result["elbow_angle_deg"]
                    angle_text = f"{angle:.1f}°" if angle is not None else "확인 불가"
                    self.signals.result.emit({
                        "kind": "preflight", "ok": True,
                        "frame": draw_pose(frame, rows, options[4]),
                        "message": f"점검 중 · 아직 저장하지 않음 | 근전도 수신 중 | 팔꿈치 {angle_text} / {body_stability_text(result)}. 기록 시작 버튼을 누르면 저장합니다. 카메라를 고정하고 양쪽 어깨·골반을 화면에 맞추세요. 보이지 않는 부위는 판단 불가입니다.",
                    })
                    stop.wait(0.08)
            except Exception as exc:
                self.signals.result.emit(
                    {"kind": "preflight", "ok": False, "message": str(exc)}
                )
            finally:
                stream_stop.set()
                if serial_thread:
                    serial_thread.join(timeout=2)
                if cap:
                    cap.release()
                if conn:
                    conn.close()
                if pose:
                    pose.close()
                self.signals.result.emit({"kind": "preflight_stopped"})

        self.preflight_thread = Thread(target=run, daemon=True)
        self.preflight_thread.start()

    def _result(self, result):
        if result["kind"] == "preflight_stopped":
            self.preflight_thread = None
            self.preview_button.setText("카메라·시리얼·추적 점검")
            self.preview_button.setEnabled(True)
            if self.preview_close_pending:
                self.close()
            elif self.preview_start_pending:
                self.preview_start_pending = False
                self._start()
            return
        if result["kind"] in ("preflight", "preflight_emg") and self.preflight_stop.is_set():
            return
        if result["kind"] == "preflight_emg":
            self._plot_emg(result["emg_samples"])
            return
        self.status.setText(result["message"])
        if result["kind"] == "preflight":
            self.preflight_ok = result["ok"]
            self.preflight_error = result["message"] if not result["ok"] else ""
            self.preview_button.setEnabled(True)
            if "frame" in result:
                set_frame(self.video, result["frame"])
        elif result["kind"] == "export":
            self.export_button.setEnabled(True)
        elif result["kind"] == "recovery":
            self.recovery_button.setEnabled(True)

    def _start(self):
        if self.measurement_started:
            self.status.setText(
                "1회 측정이 이미 시작되었습니다. 추가 측정은 새로 실행하세요."
            )
            return
        if not self.preflight_ok:
            self.status.setText("기록을 시작할 수 없습니다: " + self.preflight_error)
            return
        try:
            if self.preflight_thread is not None:
                self.preview_start_pending = True
                self.preflight_stop.set()
                return
            private, public = self.participant.build_models()
            consent = Consent(
                research=self.participant.consent_confirmed(),
                pose_coordinates=self.pose_consent.isChecked(),
                video_storage=self.video_consent.isChecked(),
                video_access=self.access_consent.isChecked(),
                video_export=False,
            )

            visit = Visit(visit_id="V-" + uuid.uuid4().hex)
            self.controller = CollectionController(
                self.store.root,
                public,
                consent,
                visit,
                self.protocol,
                arm=self.arm.currentData(),
                load_kg=self.load.value(),
                dumbbell_count=self.dumbbell_count.value(),
                port=self.port.text().strip(),
                camera_index=self.camera.value(),
                model_path=self.model.text(),
                synthetic=self.synthetic.currentData(),
                placement=self.placement.text(),
                skin_prepared=False,
                clothing_confirmed=False,
                mock_occlusion=self.mock_occlusion.currentData(),
                mock_receive_batch_delay_ms=self.mock_delay.value(),
            )
            # Participant registration is small; stream flush/encoding/inference run on workers.
            self.store.register_participant(private, public)
            self.controller.start()
            self.measurement_started = True
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

    def _plot_emg(self, samples):
        if samples:
            if not self.trace:
                self.trace_origin_ns = samples[0]["host_receive_ns"]
            self.trace.extend(
                ((s["host_receive_ns"] - self.trace_origin_ns) / 1e9,
                 s["s1_raw"], s["s2_raw"])
                for s in samples
            )
            self.trace = self.trace[-2500:]
            self.line1.setData([v[0] for v in self.trace], [v[1] for v in self.trace])
            self.line2.setData([v[0] for v in self.trace], [v[2] for v in self.trace])

    def _tick(self):
        c = self.controller
        if c is None:
            return
        data = c.preview()
        if "frame" in data:
            set_frame(self.video, draw_pose(
                data["frame"], data.get("landmarks", []), c.arm, c.protocol.min_visibility
            ))
        self._plot_emg(data.get("emg_samples", []))
        attempts = data.get("attempts", [])
        for attempt in attempts:
            if self.failure.findData(attempt["attempt_id"]) < 0:
                self.failure.addItem(
                    f"{attempt['attempt_id']} ({attempt['validity']})",
                    attempt["attempt_id"],
                )
        if c.done.is_set():
            self.controller = None
            self.recovery_button.setEnabled(True)
            self.start_button.setText("1회 측정 종료")
            self.start_button.setEnabled(False)
            self.preview_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.pain_button.setEnabled(False)
            self.status.setText(
                (
                    "미완료: "
                    if c.errors
                    or getattr(c, "manifest", {}).get("status") != "complete"
                    else "완료: "
                )
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
            + " | " + body_stability_text(data.get("metrics", {}))
        )
        if c.errors:
            self.status.setText("장애로 중지·미완료 저장 중: " + "; ".join(c.errors))

    def _review(self):
        from emg_collector.ui.multimodal_review import MultimodalReviewDialog

        path = QFileDialog.getExistingDirectory(
            self,
            "검토할 측정 기록",
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
        synthetic = self.synthetic.currentData()
        diagnostic = self.diagnostic_alignment.currentData()
        output = Path(path) / ("training_" + time.strftime("%Y%m%d_%H%M%S"))
        self.export_button.setEnabled(False)

        def run():
            try:
                from emg_collector.storage.training_export import export_training

                result = export_training(
                    self.store.root,
                    output,
                    synthetic=synthetic,
                    allow_pilot=True,
                    allow_unverified_alignment=diagnostic,
                )
                message = f"PILOT export {output}: 예제 {result['examples']}개, 세션 {result['excluded_sessions']}, 창 제외 {result['excluded']}, 빈 split {result['empty_splits']}. 제외 보고서: exclusion_report.json"
                if diagnostic:
                    message += " / 경고: 물리 동기 미검증 진단 자료입니다."
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
            self.preview_close_pending = True
            self.preflight_stop.set()
            event.ignore()
            return
        event.accept()
