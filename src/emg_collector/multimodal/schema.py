from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "3.0.0"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Channel(Record):
    sensor_id: str
    channel_id: str
    muscle: str
    signal: Literal["RAW", "ENV"]
    gpio: int
    side: Literal["left", "right"] = "right"
    electrode_placement: str = ""
    skin_prepared: bool = False
    sensor_settings: str = "12-bit ADC; analog bandwidth unverified"


def channels(profile: str, side: str = "right") -> list[Channel]:
    if profile not in ("legacy_v2", "biceps_triceps_v3"):
        raise ValueError(f"unsupported profile: {profile}")
    second = "brachioradialis" if profile == "legacy_v2" else "triceps"
    return [
        Channel(
            sensor_id=f"sensor{slot}",
            channel_id=f"s{slot}_{signal.lower()}",
            muscle=muscle,
            signal=signal,
            gpio=pin,
            side=side,
        )
        for slot, muscle, signal, pin in [
            (1, "biceps", "ENV", 33),
            (1, "biceps", "RAW", 34),
            (2, second, "ENV", 32),
            (2, second, "RAW", 35),
        ]
    ]


class Sample(Record):
    sample_index: int = Field(ge=0)
    epoch_id: int = Field(ge=0)
    device_time_us: int = Field(ge=0, lt=2**32)
    unwrapped_time_us: int = Field(ge=0)
    host_receive_ns: int = Field(ge=0)
    s1_env: int = Field(ge=0, le=4095)
    s1_raw: int = Field(ge=0, le=4095)
    s2_env: int = Field(ge=0, le=4095)
    s2_raw: int = Field(ge=0, le=4095)


class ProfileParser:
    def __init__(self, profile: str, side: str = "right"):
        self.channels = channels(profile, side)
        second = "brachio" if profile == "legacy_v2" else "triceps"
        self.header = f"time_us,biceps_env,biceps_raw,{second}_env,{second}_raw"
        self.header_seen = False

    def parse(self, line: str, host_ns: int):
        text = line.strip()
        if text.startswith("time_us,"):
            if text != self.header:
                raise ValueError(
                    f"header mismatch: expected {self.header}; received {text}"
                )
            self.header_seen = True
            return None
        if not text or "," not in text:
            return None
        if not self.header_seen:
            raise ValueError(
                "matching device header required before recording; reconnect/reset device"
            )
        parts = text.split(",")
        if len(parts) != 5:
            raise ValueError("sample requires exactly five fields")
        values = [int(part) for part in parts]
        return Sample(
            sample_index=0,
            epoch_id=0,
            device_time_us=values[0],
            unwrapped_time_us=values[0],
            host_receive_ns=host_ns,
            **dict(zip(("s1_env", "s1_raw", "s2_env", "s2_raw"), values[1:])),
        )


class Consent(Record):
    research: bool = False
    pose_coordinates: bool = False
    video_storage: bool = False
    video_access: bool = False
    video_export: bool = False

    @model_validator(mode="after")
    def permissions(self):
        if (self.video_access or self.video_export) and not self.video_storage:
            raise ValueError("video access/export requires video storage consent")
        return self


class Visit(Record):
    visit_id: str = Field(min_length=1)
    hours_since_exercise: float | None = Field(default=None, ge=0)
    hours_since_upper_body_exercise: float | None = Field(default=None, ge=0)
    fatigue_score: int | None = Field(default=None, ge=0, le=10)
    pain_score: int | None = Field(default=None, ge=0, le=10)


class Termination(str, Enum):
    technical_failure = "technical_failure"
    voluntary_stop = "voluntary_stop"
    pain_discomfort = "pain_discomfort"
    equipment_failure = "equipment_failure"
    tracking_failure = "tracking_failure"
    protocol_deviation = "protocol_deviation"
    planned_stop = "planned_stop"
    other = "other"


class Attempt(Record):
    attempt_id: str
    set_id: str
    start_ns: int = Field(ge=0)
    end_ns: int = Field(ge=0)
    validity: Literal["valid", "invalid", "unknown"]
    reasons: list[str] = Field(default_factory=list)
    phases: dict[str, int] = Field(default_factory=dict)
    rom_deg: float | None = None
    provisional: bool = True

    @model_validator(mode="after")
    def boundaries(self):
        if self.end_ns < self.start_ns:
            raise ValueError("attempt end precedes start")
        return self


class SetRecord(Record):
    set_id: str
    arm: Literal["left", "right"]
    set_number: int = Field(ge=1)
    exercise: str = "unilateral_dumbbell_curl"
    load_kg: float = Field(ge=0)
    dumbbell_count: int = Field(default=1, ge=1)
    rest_before_s: float | None = Field(default=None, ge=0)
    target_repetitions: int | None = Field(default=None, ge=0)
    start_ns: int = Field(ge=0)
    end_ns: int | None = Field(default=None, ge=0)
    termination_reason: Termination | None = None
    failure_attempt_id: str | None = None
    failure_attempt_observed: bool | None = None
    review_status: Literal["provisional", "confirmed"] = "provisional"
    objective_review: bool = False
    observed_valid_count: int = Field(default=0, ge=0)
    censoring_status: Literal["unreviewed", "right_censored", "exact", "unknown"] = (
        "unreviewed"
    )

    @model_validator(mode="after")
    def boundaries(self):
        if self.end_ns is not None and self.end_ns < self.start_ns:
            raise ValueError("set end precedes start")
        if self.failure_attempt_id is not None:
            if self.failure_attempt_observed is False:
                raise ValueError(
                    "failure attempt ID contradicts absence of a failure attempt"
                )
            self.failure_attempt_observed = True
        return self


def remaining(record: SetRecord, attempts: list[Attempt], k: int) -> int | None:
    if (
        record.termination_reason != Termination.technical_failure
        or record.review_status != "confirmed"
        or not record.objective_review
    ):
        return None
    own = sorted(
        (a for a in attempts if a.set_id == record.set_id), key=lambda a: a.start_ns
    )
    failure = next((a for a in own if a.attempt_id == record.failure_attempt_id), None)
    if (
        failure is None
        or failure.validity != "invalid"
        or any(a.validity == "unknown" for a in own if a.start_ns <= failure.start_ns)
    ):
        return None
    total = sum(a.validity == "valid" for a in own if a.end_ns <= failure.start_ns)
    if not 0 <= k <= total:
        raise ValueError("completed count outside confirmed set")
    return total - k
