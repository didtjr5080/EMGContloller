"""Shared review/validator invariants, including edited attempt identities."""

PHASE_ORDER = ("ready", "concentric", "top", "eccentric", "completed")


def validate_annotations(sets, attempts):
    own = {s.set_id: s for s in sets}
    if not own or len(own) != len(sets):
        raise ValueError("sets: missing or duplicate set IDs")
    ids = {a.attempt_id for a in attempts}
    if len(ids) != len(attempts):
        raise ValueError("repetitions: duplicate attempt IDs")
    for a in attempts:
        s = own.get(a.set_id)
        if (
            s is None
            or s.end_ns is None
            or not s.start_ns <= a.start_ns < a.end_ns <= s.end_ns
        ):
            raise ValueError(
                f"repetitions/{a.attempt_id}: attempt outside set or reversed boundary"
            )
        if set(a.phases) - set(PHASE_ORDER):
            raise ValueError(f"repetitions/{a.attempt_id}: unsupported phase")
        times = [a.phases[name] for name in PHASE_ORDER if name in a.phases]
        if any(t < a.start_ns or t > a.end_ns for t in times) or any(
            b <= a for a, b in zip(times, times[1:])
        ):
            raise ValueError(
                f"repetitions/{a.attempt_id}: phase order/boundary invalid"
            )
    for s in sets:
        ordered = sorted(
            (a for a in attempts if a.set_id == s.set_id), key=lambda a: a.start_ns
        )
        if any(b.start_ns < a.end_ns for a, b in zip(ordered, ordered[1:])):
            raise ValueError(f"sets/{s.set_id}: overlapping attempts")
        failure = next(
            (a for a in ordered if a.attempt_id == s.failure_attempt_id), None
        )
        if s.failure_attempt_id and (failure is None or failure.validity != "invalid"):
            raise ValueError(
                f"sets/{s.set_id}/failure_attempt_id: select an existing invalid attempt"
            )
