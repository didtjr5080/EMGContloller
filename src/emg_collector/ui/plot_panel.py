"""Real-time RAW/ENV waveform display (work order section 6.5).

Incoming samples are appended to a fixed-size ring buffer as fast as they
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
        self._env = deque(maxlen=capacity)
        self._raw = deque(maxlen=capacity)
        self._paused = False

        pg.setConfigOptions(antialias=False)
        self.raw_plot = pg.PlotWidget(title="RAW")
        self.env_plot = pg.PlotWidget(title="ENV")
        self.env_plot.setXLink(self.raw_plot)
        for plot in (self.raw_plot, self.env_plot):
            plot.setLabel("left", "ADC count")
            plot.setLabel("bottom", "time", units="s")
            plot.showGrid(x=True, y=True, alpha=0.2)

        self._raw_curve = self.raw_plot.plot(pen=pg.mkPen(color="#4c8bf5", width=1))
        self._env_curve = self.env_plot.plot(pen=pg.mkPen(color="#f5a623", width=1))

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

    def append_samples(self, times_s, env_values, raw_values) -> None:
        self._t.extend(times_s)
        self._env.extend(env_values)
        self._raw.extend(raw_values)

    def clear(self) -> None:
        self._t.clear()
        self._env.clear()
        self._raw.clear()
        self._raw_curve.clear()
        self._env_curve.clear()

    def _redraw(self) -> None:
        if self._paused or not self._t:
            return
        t = list(self._t)
        self._raw_curve.setData(t, list(self._raw))
        self._env_curve.setData(t, list(self._env))
