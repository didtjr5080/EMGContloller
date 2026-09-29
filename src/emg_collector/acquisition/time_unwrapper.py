"""Unwrap the ESP32's 32-bit ``micros()`` timer and detect device reboots.

``micros()`` on ESP32 is a 32-bit unsigned integer that rolls over to zero
roughly every 71.58 minutes. A rollover must be distinguished from a device
reboot (which also resets the timer near zero, but after far less than a
full 32-bit span) and from small backward jitter in a single sample.
"""

from __future__ import annotations

from dataclasses import dataclass

from emg_collector.config import (
    MICROS_WRAP_MODULUS,
    REBOOT_DROP_THRESHOLD_US,
    WRAP_EDGE_WINDOW_US,
)


@dataclass(frozen=True)
class UnwrapResult:
    """Outcome of feeding one raw device timestamp to :class:`TimeUnwrapper`.

    ``value_us`` is always a monotonically non-decreasing unwrapped
    timestamp suitable for plotting/elapsed-time math, except that callers
    must check ``reboot_detected`` themselves: on a reboot this class does
    *not* attempt to splice device time bases together, and the caller is
    expected to end/flag the current recording segment instead of trusting
    ``value_us`` to represent continuous device time across the reboot.
    """

    value_us: int
    wrapped: bool
    reboot_detected: bool
    regression: bool


class TimeUnwrapper:
    """Stateful unwrapper for a single, contiguous stream of device timestamps."""

    def __init__(
        self,
        wrap_edge_window_us: int = WRAP_EDGE_WINDOW_US,
        reboot_drop_threshold_us: int = REBOOT_DROP_THRESHOLD_US,
    ) -> None:
        self._wrap_edge_window_us = wrap_edge_window_us
        self._reboot_drop_threshold_us = reboot_drop_threshold_us
        self._last_raw: int | None = None
        self._last_unwrapped: int | None = None
        self._offset = 0
        self._wrap_count = 0

    @property
    def wrap_count(self) -> int:
        return self._wrap_count

    def unwrap(self, raw_time_us: int) -> UnwrapResult:
        if not (0 <= raw_time_us < MICROS_WRAP_MODULUS):
            raise ValueError(f"raw_time_us out of 32-bit range: {raw_time_us}")

        if self._last_raw is None:
            self._last_raw = raw_time_us
            self._last_unwrapped = raw_time_us
            return UnwrapResult(raw_time_us, False, False, False)

        delta = raw_time_us - self._last_raw

        if delta >= 0:
            unwrapped = raw_time_us + self._offset
            self._last_raw = raw_time_us
            self._last_unwrapped = unwrapped
            return UnwrapResult(unwrapped, False, False, False)

        near_wrap_edge = (
            self._last_raw >= MICROS_WRAP_MODULUS - self._wrap_edge_window_us
            and raw_time_us < self._wrap_edge_window_us
        )
        if near_wrap_edge:
            self._offset += MICROS_WRAP_MODULUS
            self._wrap_count += 1
            unwrapped = raw_time_us + self._offset
            self._last_raw = raw_time_us
            self._last_unwrapped = unwrapped
            return UnwrapResult(unwrapped, True, False, False)

        drop = -delta
        assert self._last_unwrapped is not None
        if drop > self._reboot_drop_threshold_us:
            # Device reboot: do not advance internal state. The caller
            # should end the current session segment rather than rely on
            # this value as a continuation of device time.
            return UnwrapResult(self._last_unwrapped, False, True, False)

        # Small backward jitter: clamp to the last known-good unwrapped
        # value so downstream time never regresses, but flag it so quality
        # metrics can count it.
        return UnwrapResult(self._last_unwrapped, False, False, True)
