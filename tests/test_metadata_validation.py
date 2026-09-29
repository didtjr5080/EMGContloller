import pytest
from pydantic import ValidationError

from emg_collector.models import (
    Arm,
    ParticipantPrivate,
    ParticipantPublic,
    SessionInfo,
)


def make_valid_public(**overrides):
    data = dict(
        participant_id="P-AB12",
        age=30,
        height_cm=175.0,
        exercise_sessions_per_week=3,
        days_since_last_exercise=1,
    )
    data.update(overrides)
    return ParticipantPublic(**data)


def test_participant_private_requires_name_and_id_format():
    ParticipantPrivate(participant_id="P-AB12", name="Hong Gildong")

    with pytest.raises(ValidationError):
        ParticipantPrivate(participant_id="not-an-id", name="Hong Gildong")

    with pytest.raises(ValidationError):
        ParticipantPrivate(participant_id="P-AB12", name="")


def test_participant_public_rejects_out_of_range_values():
    make_valid_public()  # sanity: valid input passes

    with pytest.raises(ValidationError):
        make_valid_public(age=0)
    with pytest.raises(ValidationError):
        make_valid_public(age=121)
    with pytest.raises(ValidationError):
        make_valid_public(height_cm=49)
    with pytest.raises(ValidationError):
        make_valid_public(height_cm=251)
    with pytest.raises(ValidationError):
        make_valid_public(exercise_sessions_per_week=-1)
    with pytest.raises(ValidationError):
        make_valid_public(days_since_last_exercise=-0.5)


def test_participant_public_optional_fields_can_be_omitted():
    participant = make_valid_public()
    assert participant.weight_kg is None
    assert participant.exercise_minutes_per_week is None


def test_participant_public_never_carries_a_name_field():
    assert "name" not in ParticipantPublic.model_fields


def test_session_info_requires_explicit_consent():
    base = dict(
        session_id="S-1",
        participant_id="P-AB12",
        muscle="biceps",
        arm=Arm.left,
        exercise="flexion",
    )

    with pytest.raises(ValidationError):
        SessionInfo(**base, consent_confirmed=False)

    session = SessionInfo(**base, consent_confirmed=True)
    assert session.arm is Arm.left


def test_session_info_rejects_invalid_scores():
    base = dict(
        session_id="S-1",
        participant_id="P-AB12",
        muscle="biceps",
        arm=Arm.left,
        exercise="flexion",
        consent_confirmed=True,
    )
    with pytest.raises(ValidationError):
        SessionInfo(**base, pain_score=11)
    with pytest.raises(ValidationError):
        SessionInfo(**base, pre_fatigue_score=-1)
