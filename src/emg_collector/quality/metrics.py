"""Streaming quality-metric accumulation for a single recording session.

Metrics are computed incrementally as samples arrive so ``quality.json`` can
be produced without re-reading the whole ``samples.csv`` from disk. The gap
estimate is explicitly a heuristic (see :data:`GAP_MULTIPLIER_THRESHOLD`)
and is documented as such in the output and in the README, per the work
order: it cannot fully separate real sample loss from ESP32 scheduling
jitter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from emg_collector.config import (
    ADC_MAX_VALUE,
    ADC_MIN_VALUE,
    GAP_MULTIPLIER_THRESHOLD,
    TARGET_SAMPLE_INTERVAL_US,
)


@dataclass
class _RunningStats:
    """Welford's online mean/variance algorithm."""

    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    minimum: float = float("inf")
    maximum: float = float("-inf")

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)

    @property
    def std(self) -> float:
        if self.count < 2:
            return 0.0
        return (self.m2 / self.count) ** 0.5

    def as_dict(self) -> dict[str, float]:
        if self.count == 0:
            return {"min": None, "max": None, "mean": None, "std": None}
        return {
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
            "std": self.std,
        }


@dataclass
class QualityAccumulator:
    target_interval_us: int = TARGET_SAMPLE_INTERVAL_US
    gap_multiplier_threshold: float = GAP_MULTIPLIER_THRESHOLD

    valid_samples: int = 0
    malformed_rows: int = 0
    out_of_range_rows: int = 0
    duplicate_timestamp_count: int = 0
    timestamp_regression_count: int = 0
    micros_wrap_count: int = 0
    gap_count: int = 0
    estimated_missing_samples: int = 0
    writer_queue_max_size: int = 0
    writer_queue_overflow_count: int = 0

    _biceps_env_stats: _RunningStats = field(default_factory=_RunningStats)
    _biceps_raw_stats: _RunningStats = field(default_factory=_RunningStats)
    _brachio_env_stats: _RunningStats = field(default_factory=_RunningStats)
    _brachio_raw_stats: _RunningStats = field(default_factory=_RunningStats)
    _clipped_samples: int = 0
    _last_unwrapped_us: int | None = None

    def record_sample(
        self,
        device_time_us_unwrapped: int,
        biceps_env_adc: int,
        biceps_raw_adc: int,
        brachio_env_adc: int,
        brachio_raw_adc: int,
    ) -> None:
        self.valid_samples += 1
        self._biceps_env_stats.update(biceps_env_adc)
        self._biceps_raw_stats.update(biceps_raw_adc)
        self._brachio_env_stats.update(brachio_env_adc)
        self._brachio_raw_stats.update(brachio_raw_adc)

        channel_values = (biceps_env_adc, biceps_raw_adc, brachio_env_adc, brachio_raw_adc)
        if any(value in (ADC_MIN_VALUE, ADC_MAX_VALUE) for value in channel_values):
            self._clipped_samples += 1

        if self._last_unwrapped_us is not None:
            delta = device_time_us_unwrapped - self._last_unwrapped_us
            if delta == 0:
                self.duplicate_timestamp_count += 1
            elif delta < 0:
                self.timestamp_regression_count += 1
            elif delta > self.target_interval_us * self.gap_multiplier_threshold:
                self.gap_count += 1
                missed = round(delta / self.target_interval_us) - 1
                self.estimated_missing_samples += max(missed, 0)

        self._last_unwrapped_us = device_time_us_unwrapped

    def record_malformed_row(self) -> None:
        self.malformed_rows += 1

    def record_out_of_range_row(self) -> None:
        self.out_of_range_rows += 1

    def record_wrap(self) -> None:
        self.micros_wrap_count += 1

    def record_writer_queue_size(self, current_size: int) -> None:
        self.writer_queue_max_size = max(self.writer_queue_max_size, current_size)

    def record_writer_queue_overflow(self) -> None:
        self.writer_queue_overflow_count += 1

    def actual_sample_rate_hz(self, duration_s: float) -> float:
        if duration_s <= 0:
            return 0.0
        return self.valid_samples / duration_s

    def clipping_ratio(self) -> float:
        if self.valid_samples == 0:
            return 0.0
        return self._clipped_samples / self.valid_samples

    def to_dict(self, duration_s: float, recent_sample_rate_hz: float | None = None) -> dict:
        return {
            "valid_samples": self.valid_samples,
            "duration_s": duration_s,
            "actual_sample_rate_hz": self.actual_sample_rate_hz(duration_s),
            "recent_sample_rate_hz": recent_sample_rate_hz,
            "malformed_rows": self.malformed_rows,
            "out_of_range_rows": self.out_of_range_rows,
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "timestamp_regression_count": self.timestamp_regression_count,
            "micros_wrap_count": self.micros_wrap_count,
            "gap_count": self.gap_count,
            "estimated_missing_samples": self.estimated_missing_samples,
            "estimated_missing_samples_method": (
                f"gap detected when unwrapped device-time delta > "
                f"{self.gap_multiplier_threshold} x target interval "
                f"({self.target_interval_us} us); this is an estimate and "
                f"cannot fully separate real loss from ESP32 scheduling jitter"
            ),
            "biceps_env_adc": self._biceps_env_stats.as_dict(),
            "biceps_raw_adc": self._biceps_raw_stats.as_dict(),
            "brachio_env_adc": self._brachio_env_stats.as_dict(),
            "brachio_raw_adc": self._brachio_raw_stats.as_dict(),
            "clipping_ratio": self.clipping_ratio(),
            "writer_queue_max_size": self.writer_queue_max_size,
            "writer_queue_overflow_count": self.writer_queue_overflow_count,
        }
