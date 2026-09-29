"""Simulated EMG signal source, usable with or without ESP32 hardware.

Produces the exact same ``time_us,env,raw`` text lines the real ESP32
firmware emits, so it can be fed through the same :class:`LineParser` and
:class:`TimeUnwrapper` pipeline as a real serial connection. Error-injection
toggles let tests (and a developer/test-mode UI panel) reproduce each
failure scenario in section 8.2 of the work order on demand.
"""

from __future__ import annotations

import math
import random
import time

from emg_collector.config import (
    ADC_MAX_VALUE,
    ADC_MIN_VALUE,
    MICROS_WRAP_MODULUS,
    RAW_PIN,
    ENV_PIN,
    TARGET_SAMPLE_INTERVAL_US,
)


class MockSourceDisconnected(Exception):
    """Raised by :meth:`MockSampleSource.next_line` after a disconnect is injected."""


class MockSampleSource:
    """Generates a synthetic 500 Hz EMG-like stream, line by line.

    All error injection is off by default (normal mode). Call the
    ``inject_*`` / ``trigger_*`` methods to turn on a specific failure mode
    for the *next* generated line(s); most injections are one-shot so tests
    can precisely target a single anomalous sample.
    """

    def __init__(
        self,
        sample_interval_us: int = TARGET_SAMPLE_INTERVAL_US,
        start_time_us: int = 0,
        seed: int | None = None,
        baseline_adc: int = 1800,
    ) -> None:
        self.sample_interval_us = sample_interval_us
        self._time_us = start_time_us
        self._baseline_adc = baseline_adc
        self._rng = random.Random(seed)
        self._sample_count = 0

        self._burst_remaining = 0
        self._burst_amplitude = 0.0
        self._auto_burst_period_samples = 0

        self._pending_malformed = False
        self._pending_out_of_range = False
        self._pending_duplicate_timestamp = False
        self._pending_wrap = False
        self._pending_missing_samples = 0
        self._pending_disconnect = False
        self._paused = False

    # -- error injection controls ---------------------------------------

    def inject_malformed_line(self) -> None:
        self._pending_malformed = True

    def inject_out_of_range(self) -> None:
        self._pending_out_of_range = True

    def inject_duplicate_timestamp(self) -> None:
        self._pending_duplicate_timestamp = True

    def inject_wrap(self) -> None:
        """Force the next sample's raw device time to be just past the 32-bit boundary."""
        self._pending_wrap = True

    def inject_missing_samples(self, count: int) -> None:
        self._pending_missing_samples += count

    def trigger_disconnect(self) -> None:
        self._pending_disconnect = True

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def trigger_burst(self, amplitude: float = 800.0, duration_samples: int = 150) -> None:
        self._burst_remaining = duration_samples
        self._burst_amplitude = amplitude

    def set_auto_burst(self, period_samples: int) -> None:
        self._auto_burst_period_samples = period_samples

    @property
    def paused(self) -> bool:
        return self._paused

    # -- generation --------------------------------------------------------

    def _next_signal_values(self) -> tuple[int, int]:
        if self._auto_burst_period_samples and (
            self._sample_count % self._auto_burst_period_samples == 0
        ):
            self.trigger_burst()

        raw_noise = self._rng.gauss(0, 60)
        burst_signal = 0.0
        if self._burst_remaining > 0:
            phase = self._rng.random() * 2 * math.pi
            burst_signal = self._burst_amplitude * math.sin(phase) * self._rng.random()
            self._burst_remaining -= 1

        raw_value = self._baseline_adc + raw_noise + burst_signal
        env_value = self._baseline_adc + abs(burst_signal) * 0.6 + self._rng.gauss(0, 5)

        raw_value = int(max(ADC_MIN_VALUE, min(ADC_MAX_VALUE, round(raw_value))))
        env_value = int(max(ADC_MIN_VALUE, min(ADC_MAX_VALUE, round(env_value))))
        return env_value, raw_value

    def next_line(self) -> str:
        """Return the next raw text line, or raise :class:`MockSourceDisconnected`."""
        if self._pending_disconnect:
            self._pending_disconnect = False
            raise MockSourceDisconnected("mock source disconnected")

        if self._pending_missing_samples > 0:
            self._pending_missing_samples -= 1
            self._time_us = (self._time_us + self.sample_interval_us) % MICROS_WRAP_MODULUS
            # Fall through: this call still produces a line, but the
            # timestamp has already skipped one interval, simulating a
            # dropped sample the receiver never saw.

        env_value, raw_value = self._next_signal_values()
        self._sample_count += 1

        if self._pending_wrap:
            self._pending_wrap = False
            self._time_us = MICROS_WRAP_MODULUS - self.sample_interval_us // 2
        time_us = self._time_us
        self._time_us = (self._time_us + self.sample_interval_us) % MICROS_WRAP_MODULUS

        if self._pending_malformed:
            self._pending_malformed = False
            return "bad,row"

        if self._pending_out_of_range:
            self._pending_out_of_range = False
            return f"{time_us},{ADC_MAX_VALUE + 1},{raw_value}"

        if self._pending_duplicate_timestamp:
            self._pending_duplicate_timestamp = False
            time_us = max(time_us - self.sample_interval_us, 0)

        return f"{time_us},{env_value},{raw_value}"

    def header_line(self) -> str:
        return "time_us,env,raw"


class RealtimePacedLineSource:
    """Wraps a :class:`MockSampleSource` so ``next_line()`` blocks to real time.

    Used only for the live, on-screen "모의 EMG 신호" mode so the UI sees a
    genuine ~500 Hz stream. Tests drive :class:`MockSampleSource` directly
    (unpaced) so they don't have to wait on a wall clock.
    """

    # NOTE: an earlier version of this class busy-spun the last ~1ms of each
    # wait for tighter timing accuracy. That starved the GIL badly enough
    # under Qt's threading model to hang the entire GUI thread (a real bug
    # found while smoke-testing this app), so it was reverted. A plain
    # time.sleep() is used instead: on Windows this may cap the live mock
    # preview below the configured 500 Hz (per-sample Python overhead and
    # OS timer granularity both apply), but it never blocks the event loop.
    # The actual received rate is always shown to the user rather than
    # assumed -- it is never silently exaggerated. Real ESP32 hardware is
    # unaffected, since it is driven by blocking reads of real serial data.
    def __init__(self, source: MockSampleSource) -> None:
        self._source = source
        self._next_due = time.monotonic()

    def next_line(self) -> str:
        while self._source.paused:
            time.sleep(0.01)

        now = time.monotonic()
        if now < self._next_due:
            time.sleep(self._next_due - now)
            now = time.monotonic()

        interval_s = self._source.sample_interval_us / 1_000_000
        self._next_due = max(self._next_due, now) + interval_s
        return self._source.next_line()
