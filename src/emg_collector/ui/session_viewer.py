"""Read-only viewer for a previously saved session: full RAW/ENV waveform,
label-change/event markers, and the metadata/quality summary.

This is a playback view, not the live acquisition view in
:mod:`plot_panel`: it loads the *entire* ``samples.csv`` at once (with
pyqtgraph's auto-downsampling for rendering performance) rather than
streaming into a bounded ring buffer.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from emg_collector.config import ADC_MAX_VALUE, ADC_MIN_VALUE

LABEL_MARKER_COLORS = [
    "#4c8bf5",
    "#f5a623",
    "#7ed321",
    "#d0021b",
    "#9013fe",
    "#50e3c2",
    "#bd10e0",
]


class SessionLoadError(Exception):
    pass


def _read_samples_csv(path: Path) -> tuple[list[float], list[int], list[int], list[str]]:
    elapsed_s: list[float] = []
    env_adc: list[int] = []
    raw_adc: list[int] = []
    labels: list[str] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                elapsed_s.append(float(row["elapsed_s"]))
                env_adc.append(int(row["env_adc"]))
                raw_adc.append(int(row["raw_adc"]))
                labels.append(row["label"])
            except (KeyError, ValueError, TypeError):
                # Tolerate a truncated final row (possible in an unfinalized
                # .part file if the process died mid-write).
                continue
    return elapsed_s, env_adc, raw_adc, labels


def _read_events_csv(path: Path) -> list[dict]:
    events: list[dict] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                events.append(
                    {
                        "elapsed_s": float(row["elapsed_s"]),
                        "event_type": row["event_type"],
                        "label": row["label"],
                        "note": row["note"],
                    }
                )
            except (KeyError, ValueError, TypeError):
                continue
    return events


class SessionData:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = Path(session_dir)
        self.is_unfinalized = False

        samples_path = self.session_dir / "samples.csv"
        samples_part_path = self.session_dir / "samples.csv.part"
        if samples_path.exists():
            used_path = samples_path
        elif samples_part_path.exists():
            used_path = samples_part_path
            self.is_unfinalized = True
        else:
            raise SessionLoadError(f"samples.csv를 찾을 수 없습니다: {self.session_dir}")

        self.elapsed_s, self.env_adc, self.raw_adc, self.labels = _read_samples_csv(used_path)

        events_path = self.session_dir / "events.csv"
        events_part_path = self.session_dir / "events.csv.part"
        events_file = (
            events_path if events_path.exists() else (events_part_path if events_part_path.exists() else None)
        )
        self.events = _read_events_csv(events_file) if events_file else []

        self.metadata = self._read_json("metadata.json")
        self.quality = self._read_json("quality.json")

    def _read_json(self, name: str) -> dict | None:
        path = self.session_dir / name
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    @property
    def sample_count(self) -> int:
        return len(self.elapsed_s)


class SessionViewerDialog(QDialog):
    def __init__(self, session_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"세션 보기 - {Path(session_dir).name}")
        self.resize(1100, 750)

        try:
            self.data = SessionData(session_dir)
        except SessionLoadError as exc:
            self.data = None
            self._build_error_ui(str(exc))
            return

        self._build_ui()

    def _build_error_ui(self, message: str) -> None:
        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

    def _build_ui(self) -> None:
        data = self.data
        layout = QVBoxLayout(self)

        if data.is_unfinalized:
            warning = QLabel(
                "⚠ 이 세션은 정상 종료되지 않았습니다 (samples.csv.part). "
                "앱 재실행 시 복구를 진행하기 전까지의 임시 데이터입니다."
            )
            warning.setStyleSheet("color: #f5a623;")
            layout.addWidget(warning)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        info_panel = QPlainTextEdit()
        info_panel.setReadOnly(True)
        info_panel.setPlainText(self._summary_text())
        info_panel.setMaximumWidth(380)
        splitter.addWidget(info_panel)

        plot_container = QWidget()
        plot_layout = QVBoxLayout(plot_container)
        raw_plot = pg.PlotWidget(title="RAW")
        env_plot = pg.PlotWidget(title="ENV")
        env_plot.setXLink(raw_plot)
        for plot in (raw_plot, env_plot):
            plot.setLabel("left", "ADC count")
            plot.setLabel("bottom", "elapsed", units="s")
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setYRange(ADC_MIN_VALUE, ADC_MAX_VALUE)
            plot.setDownsampling(auto=True, mode="peak")
            plot.setClipToView(True)

        raw_plot.plot(data.elapsed_s, data.raw_adc, pen=pg.mkPen(color="#4c8bf5", width=1))
        env_plot.plot(data.elapsed_s, data.env_adc, pen=pg.mkPen(color="#f5a623", width=1))
        self._add_event_markers(raw_plot, data.events)
        self._add_event_markers(env_plot, data.events)

        plot_layout.addWidget(raw_plot)
        plot_layout.addWidget(env_plot)
        splitter.addWidget(plot_container)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _add_event_markers(self, plot: pg.PlotWidget, events: list[dict]) -> None:
        label_colors: dict[str, str] = {}
        for event in events:
            color = label_colors.setdefault(
                event["label"], LABEL_MARKER_COLORS[len(label_colors) % len(LABEL_MARKER_COLORS)]
            )
            line = pg.InfiniteLine(
                pos=event["elapsed_s"],
                angle=90,
                pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine),
                label=f"{event['event_type']}:{event['label']}",
                labelOpts={"position": 0.95, "color": color, "movable": False},
            )
            plot.addItem(line)

    def _summary_text(self) -> str:
        data = self.data
        lines: list[str] = []
        lines.append(f"세션 폴더: {data.session_dir}")
        lines.append(f"저장된 샘플 수: {data.sample_count}")
        if data.elapsed_s:
            lines.append(f"기록 길이: {data.elapsed_s[-1]:.2f} s")
        lines.append(f"이벤트 수: {len(data.events)}")
        lines.append("")

        metadata = data.metadata
        if metadata:
            lines.append("--- metadata.json ---")
            lines.append(f"session_id: {metadata.get('session_id')}")
            lines.append(f"participant_id: {metadata.get('participant_id')}")
            lines.append(f"start_time_utc: {metadata.get('start_time_utc')}")
            lines.append(f"end_time_utc: {metadata.get('end_time_utc')}")
            lines.append(f"status: {metadata.get('status')}")
            lines.append(f"input_source: {metadata.get('input_source')}")
            session_info = metadata.get("session_info") or {}
            for key in ("muscle", "arm", "exercise", "load_kg", "pre_fatigue_score", "pain_score"):
                if key in session_info:
                    lines.append(f"{key}: {session_info[key]}")
            lines.append("")
        else:
            lines.append("(metadata.json 없음)")
            lines.append("")

        quality = data.quality
        if quality:
            lines.append("--- quality.json ---")
            lines.append(f"valid_samples: {quality.get('valid_samples')}")
            lines.append(f"actual_sample_rate_hz: {quality.get('actual_sample_rate_hz'):.2f}"
                          if quality.get("actual_sample_rate_hz") is not None else "actual_sample_rate_hz: -")
            lines.append(f"malformed_rows: {quality.get('malformed_rows')}")
            lines.append(f"out_of_range_rows: {quality.get('out_of_range_rows')}")
            lines.append(f"estimated_missing_samples: {quality.get('estimated_missing_samples')}")
            lines.append(f"clipping_ratio: {quality.get('clipping_ratio')}")
        else:
            lines.append("(quality.json 없음)")

        labels_present = sorted(set(data.labels))
        lines.append("")
        lines.append(f"라벨 종류: {', '.join(labels_present) if labels_present else '-'}")

        return "\n".join(lines)
