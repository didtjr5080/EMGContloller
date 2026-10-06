"""Real-time RAW/ENV waveform display (work order section 6.5).

Two MyoWare 2.0 sensors (biceps, brachioradialis) are shown together: one
RAW plot with both raw curves, one ENV plot with both envelope curves, so
RAW vs ENV stays the primary visual split while both muscles are visible
at once.

Incoming samples are appended to fixed-size ring buffers as fast as they
arrive; a separate QTimer redraws the curves at :data:`PLOT_REFRESH_HZ`, so
plotting is decoupled from data ingestion and from CSV writing. Pausing the
display only stops the redraw timer -- :meth:`append_samples` keeps
accepting data, so recording is unaffected.
"""

from __future__ import annotations

from collections import deque

import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from emg_collector.config import (
    ADC_MAX_VALUE,
    ADC_MIN_VALUE,
    PLOT_REFRESH_HZ,
    PLOT_WINDOW_SECONDS_DEFAULT,
    TARGET_SAMPLE_RATE_HZ,
)

BICEPS_RAW_COLOR = "#4c8bf5"
BRACHIO_RAW_COLOR = "#50e3c2"
BICEPS_ENV_COLOR = "#f5a623"
BRACHIO_ENV_COLOR = "#bd10e0"


class PlotPanel(QWidget):
    def __init__(
        self,
        window_seconds: float = PLOT_WINDOW_SECONDS_DEFAULT,
        sample_rate_hz: float = TARGET_SAMPLE_RATE_HZ,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.window_seconds = window_seconds
        capacity = max(int(window_seconds * sample_rate_hz * 1.5), 100)
        self._t = deque(maxlen=capacity)
        self._biceps_env = deque(maxlen=capacity)
        self._biceps_raw = deque(maxlen=capacity)
        self._brachio_env = deque(maxlen=capacity)
        self._brachio_raw = deque(maxlen=capacity)
        self._paused = False

        pg.setConfigOptions(antialias=False)
        self.raw_plot = pg.PlotWidget(title="RAW (이두근 / 상완요골근)")
        self.env_plot = pg.PlotWidget(title="ENV (이두근 / 상완요골근)")
        self.env_plot.setXLink(self.raw_plot)
        for plot in (self.raw_plot, self.env_plot):
            plot.setLabel("left", "ADC count")
            plot.setLabel("bottom", "time", units="s")
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.addLegend()

        self._biceps_raw_curve = self.raw_plot.plot(
            pen=pg.mkPen(color=BICEPS_RAW_COLOR, width=1), name="이두근 RAW"
        )
        self._brachio_raw_curve = self.raw_plot.plot(
            pen=pg.mkPen(color=BRACHIO_RAW_COLOR, width=1), name="상완요골근 RAW"
        )
        self._biceps_env_curve = self.env_plot.plot(
            pen=pg.mkPen(color=BICEPS_ENV_COLOR, width=1), name="이두근 ENV"
        )
        self._brachio_env_curve = self.env_plot.plot(
            pen=pg.mkPen(color=BRACHIO_ENV_COLOR, width=1), name="상완요골근 ENV"
        )

        self.pause_checkbox = QCheckBox("표시 일시정지")
        self.fixed_range_checkbox = QCheckBox("고정 범위 (0-4095)")
        self.pause_checkbox.toggled.connect(self.set_paused)
        self.fixed_range_checkbox.toggled.connect(self._apply_range_mode)

        controls = QHBoxLayout()
        controls.addWidget(self.pause_checkbox)
        controls.addWidget(self.fixed_range_checkbox)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.raw_plot)
        layout.addWidget(self.env_plot)

        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / PLOT_REFRESH_HZ))
        self._timer.timeout.connect(self._redraw)
        self._timer.start()

        self._apply_range_mode(self.fixed_range_checkbox.isChecked())

    def _apply_range_mode(self, fixed: bool) -> None:
        for plot in (self.raw_plot, self.env_plot):
            if fixed:
                plot.setYRange(ADC_MIN_VALUE, ADC_MAX_VALUE)
                plot.enableAutoRange(y=False)
            else:
                plot.enableAutoRange(y=True)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    @property
    def paused(self) -> bool:
        return self._paused

    def append_samples(
        self,
        times_s,
        biceps_env_values,
        biceps_raw_values,
        brachio_env_values,
        brachio_raw_values,
    ) -> None:
        self._t.extend(times_s)
        self._biceps_env.extend(biceps_env_values)
        self._biceps_raw.extend(biceps_raw_values)
        self._brachio_env.extend(brachio_env_values)
        self._brachio_raw.extend(brachio_raw_values)

    def clear(self) -> None:
        self._t.clear()
        self._biceps_env.clear()
        self._biceps_raw.clear()
        self._brachio_env.clear()
        self._brachio_raw.clear()
        self._biceps_raw_curve.clear()
        self._brachio_raw_curve.clear()
        self._biceps_env_curve.clear()
        self._brachio_env_curve.clear()

    def _redraw(self) -> None:
        if self._paused or not self._t:
            return
        t = list(self._t)
        self._biceps_raw_curve.setData(t, list(self._biceps_raw))
        self._brachio_raw_curve.setData(t, list(self._brachio_raw))
        self._biceps_env_curve.setData(t, list(self._biceps_env))
        self._brachio_env_curve.setData(t, list(self._brachio_env))
