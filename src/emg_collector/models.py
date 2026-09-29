"""Pydantic models for participant, session, sample, event and quality data.

These models are the single source of truth for validation rules described
in the work order (required vs optional fields, numeric ranges). They are
deliberately separate from the CSV/JSON writers in ``storage/`` so the
validation rules can be unit tested without touching disk.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Sex(str, Enum):
    male = "male"
    female = "female"
    unspecified = "unspecified"


class DominantArm(str, Enum):
    left = "left"
    right = "right"
    both = "both"
    unspecified = "unspecified"


class Arm(str, Enum):
    left = "left"
    right = "right"


PARTICIPANT_ID_PATTERN = re.compile(r"^P-[A-Za-z0-9]{4,}$")


class ParticipantPrivate(BaseModel):
    """Identifying information. Stored only in ``participants_private.csv``."""

    participant_id: str = Field(pattern=PARTICIPANT_ID_PATTERN.pattern)
    name: str = Field(min_length=1)
    created_at_utc: str = Field(default_factory=utc_now_iso)


class ParticipantPublic(BaseModel):
    """De-identified participant fields, safe for the training dataset."""

    participant_id: str = Field(pattern=PARTICIPANT_ID_PATTERN.pattern)
    age: int = Field(ge=1, le=120)
    sex: Sex = Sex.unspecified
    height_cm: float = Field(ge=50, le=250)
    weight_kg: Optional[float] = Field(default=None, ge=10, le=350)
    dominant_arm: DominantArm = DominantArm.unspecified
    exercise_sessions_per_week: int = Field(ge=0, le=21)
    exercise_minutes_per_week: Optional[int] = Field(default=None, ge=0)
    days_since_last_exercise: float = Field(ge=0)
    participant_notes: str = ""

    @field_validator("participant_notes")
    @classmethod
    def warn_on_identifying_notes(cls, value: str) -> str:
        # Validation only rejects negative/garbage input per the work
        # order; free-text screening for identifiers is a UI-level warning,
        # not a hard block, so this validator intentionally passes text
        # through unchanged.
        return value


class SessionInfo(BaseModel):
    """Measurement-session metadata, independent of the recorded waveform."""

    session_id: str
    participant_id: str = Field(pattern=PARTICIPANT_ID_PATTERN.pattern)
    muscle: str = Field(min_length=1)
    arm: Arm
    exercise: str = Field(min_length=1)
    load_kg: Optional[float] = Field(default=None, ge=0)
    set_number: Optional[int] = Field(default=None, ge=1)
    target_repetitions: Optional[int] = Field(default=None, ge=0)
    electrode_placement: str = ""
    skin_prepared: bool = False
    pre_fatigue_score: int = Field(default=0, ge=0, le=10)
    pain_score: Optional[int] = Field(default=None, ge=0, le=10)
    session_notes: str = ""
    expected_sample_rate_hz: float = 500.0
    consent_confirmed: bool = False

    @field_validator("consent_confirmed")
    @classmethod
    def must_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("recording cannot start without consent_confirmed=True")
        return value


class EventType(str, Enum):
    label_change = "label_change"
    user_marker = "user_marker"
    reconnect_attempt = "reconnect_attempt"
    disconnect = "disconnect"
    warning = "warning"
    session_start = "session_start"
    session_end = "session_end"


class SampleRecord(BaseModel):
    sample_index: int = Field(ge=0)
    device_time_us: int = Field(ge=0, lt=2**32)
    device_time_us_unwrapped: int = Field(ge=0)
    elapsed_s: float = Field(ge=0)
    host_elapsed_s: float = Field(ge=0)
    env_adc: int = Field(ge=0, le=4095)
    raw_adc: int = Field(ge=0, le=4095)
    label: str


class EventRecord(BaseModel):
    event_index: int = Field(ge=0)
    sample_index: int = Field(ge=0)
    device_time_us_unwrapped: int = Field(ge=0)
    elapsed_s: float = Field(ge=0)
    event_type: EventType
    label: str
    note: str = ""
