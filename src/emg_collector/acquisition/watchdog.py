"""Monotonic watchdog; only valid data extends the deadline."""

from pydantic import Field
from emg_collector.multimodal.schema import Record


class WatchdogPolicy(Record):
    version: str = "watchdog-1"
    startup_timeout_s: float = Field(default=5, gt=0)
    stall_timeout_s: float = Field(default=3, gt=0)
    grace_s: float = Field(default=0.5, ge=0)
    shutdown_timeout_s: float = Field(default=5, gt=0)


class StreamWatchdog:
    def __init__(self, start_ns, policy=None):
        self.start_ns = start_ns
        self.policy = policy or WatchdogPolicy()
        self.last_valid_ns = None

    def mark_valid(self, ns):
        self.last_valid_ns = ns

    def check(self, ns):
        origin = self.start_ns if self.last_valid_ns is None else self.last_valid_ns
        seconds = (
            self.policy.startup_timeout_s
            if self.last_valid_ns is None
            else self.policy.stall_timeout_s
        )
        if ns - origin > (seconds + self.policy.grace_s) * 1e9:
            return "start_timeout" if self.last_valid_ns is None else "stall"
        return None
