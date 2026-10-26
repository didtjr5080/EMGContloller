"""PILOT values are starting hypotheses, never validated movement standards."""

from typing import Literal
from pydantic import Field, model_validator
from emg_collector.multimodal.schema import Record


class PilotProtocol(Record):
    protocol_id: str = "unilateral_curl_pilot"
    version: str = "0.1.0"
    status: Literal["PILOT"] = "PILOT"
    start_angle_deg: float = Field(default=155, gt=0, le=180)
    top_angle_deg: float = Field(default=60, gt=0, le=180)
    min_rom_deg: float = Field(default=80, gt=0, le=180)
    hysteresis_deg: float = Field(default=5, gt=0)
    debounce_ns: int = Field(default=80_000_000, gt=0)
    phase_timeout_s: float = Field(default=8, gt=0)
    min_duration_s: float = Field(default=0.5, gt=0)
    max_duration_s: float = Field(default=12, gt=0)
    max_trunk_tilt_deg: float = Field(default=20, gt=0)
    max_upperarm_delta_deg: float = Field(default=25, gt=0)
    violation_duration_s: float = Field(default=0.25, ge=0)
    min_visibility: float = Field(default=0.6, ge=0, le=1)
    max_pose_gap_ns: int = Field(default=150_000_000, gt=0)
    target_sync_error_ms: float = Field(default=50, gt=0)
    termination_rule: str = (
        "Reviewer confirms first sustained failed attempt; later attempts excluded."
    )
    rest_rule: str = (
        "Record actual rest; load change, assistance or extended rest is a deviation."
    )

    @model_validator(mode="after")
    def thresholds(self):
        if (
            self.top_angle_deg + self.hysteresis_deg
            >= self.start_angle_deg - self.hysteresis_deg
        ):
            raise ValueError("top/start thresholds overlap with hysteresis")
        if self.min_duration_s >= self.max_duration_s:
            raise ValueError("minimum duration must be smaller than maximum")
        if self.min_rom_deg > self.start_angle_deg - self.top_angle_deg:
            raise ValueError("minimum ROM exceeds configured start/top range")
        return self
