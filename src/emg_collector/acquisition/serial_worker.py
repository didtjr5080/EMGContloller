"""Background worker that reads a line source, parses it, and batches samples.

Runs on a :class:`QThread` in the real app (see :meth:`SerialWorker.start_in_thread`),
but the class itself only depends on Qt signals/slots, not on any specific
transport: it is driven by anything exposing ``next_line() -> str`` that
raises on disconnect, which both :class:`~emg_collector.acquisition.mock_source.MockSampleSource`
and the real serial adapter below implement. This keeps serial reading and
CSV writing off the GUI thread per the work order's threading requirements,
and keeps the class unit-testable without a real COM port.
"""

from __future__ import annotations

import time
from typing import Protocol

from PyQt6.QtCore import QObject, pyqtSignal

from emg_collector.acquisition.mock_source import MockSourceDisconnected
from emg_collector.acquisition.parser import LineParser, ParsedSample
from emg_collector.acquisition.time_unwrapper import TimeUnwrapper
from emg_collector.config import BATCH_INTERVAL_MS, BATCH_MAX_SAMPLES


class LineSource(Protocol):
    def next_line(self) -> str: ...


class SerialDisconnected(Exception):
    """Raised by the real serial-port line source on a lost connection."""


class SerialPortLineSource:
    """Adapts a ``pyserial.Serial`` instance to the ``LineSource`` protocol."""

    def __init__(self, serial_connection) -> None:
        self._serial = serial_connection

    def next_line(self) -> str:
        import serial  # local import: optional dependency for non-serial builds

        try:
            raw = self._serial.readline()
        except serial.SerialException as exc:
            raise SerialDisconnected(str(exc)) from exc
        if raw == b"" and not self._serial.is_open:
            raise SerialDisconnected("serial port closed")
        return raw.decode("utf-8", errors="replace")


class UnwrappedSample:
    __slots__ = (
        "time_us",
        "time_us_unwrapped",
        "biceps_env",
        "biceps_raw",
        "brachio_env",
        "brachio_raw",
        "wrapped",
        "regression",
    )

    def __init__(
        self,
        time_us: int,
        time_us_unwrapped: int,
        biceps_env: int,
        biceps_raw: int,
        brachio_env: int,
        brachio_raw: int,
        wrapped: bool,
        regression: bool,
    ) -> None:
        self.time_us = time_us
        self.time_us_unwrapped = time_us_unwrapped
        self.biceps_env = biceps_env
        self.biceps_raw = biceps_raw
        self.brachio_env = brachio_env
        self.brachio_raw = brachio_raw
        self.wrapped = wrapped
        self.regression = regression


class SerialWorker(QObject):
    batch_ready = pyqtSignal(list)
    diagnostics_updated = pyqtSignal(dict)
    disconnected = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        line_source: LineSource,
        parser: LineParser | None = None,
        time_unwrapper: TimeUnwrapper | None = None,
        batch_interval_ms: int = BATCH_INTERVAL_MS,
        batch_max_samples: int = BATCH_MAX_SAMPLES,
    ) -> None:
        super().__init__()
        self._line_source = line_source
        self.parser = parser or LineParser()
        self.time_unwrapper = time_unwrapper or TimeUnwrapper()
        self._batch_interval_s = batch_interval_ms / 1000.0
        self._batch_max_samples = batch_max_samples
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        batch: list[UnwrappedSample] = []
        last_flush = time.monotonic()

        while self._running:
            try:
                line = self._line_source.next_line()
            except (MockSourceDisconnected, SerialDisconnected) as exc:
                if batch:
                    self.batch_ready.emit(batch)
                self.diagnostics_updated.emit(self.parser.diagnostics.as_dict())
                self.disconnected.emit(str(exc))
                self._running = False
                batch = []
                break

            parsed: ParsedSample | None = self.parser.parse_line(line)
            if parsed is not None:
                result = self.time_unwrapper.unwrap(parsed.time_us)
                if not result.reboot_detected:
                    batch.append(
                        UnwrappedSample(
                            time_us=parsed.time_us,
                            time_us_unwrapped=result.value_us,
                            biceps_env=parsed.biceps_env,
                            biceps_raw=parsed.biceps_raw,
                            brachio_env=parsed.brachio_env,
                            brachio_raw=parsed.brachio_raw,
                            wrapped=result.wrapped,
                            regression=result.regression,
                        )
                    )

            now = time.monotonic()
            should_flush = (now - last_flush) >= self._batch_interval_s
            if batch and (len(batch) >= self._batch_max_samples or should_flush):
                self.batch_ready.emit(batch)
                batch = []
            if should_flush:
                # Emitted on a wall-clock cadence regardless of whether any
                # sample validated, so the UI keeps getting live feedback
                # (error counts, "still polling") even when nothing usable
                # is arriving -- e.g. wrong baud rate or a silent port.
                # Previously this was nested inside "if batch:", so a
                # connection that never produced one valid sample looked
                # completely frozen with no diagnostics at all.
                self.diagnostics_updated.emit(self.parser.diagnostics.as_dict())
                last_flush = now

        if batch:
            self.batch_ready.emit(batch)
        self.finished.emit()
