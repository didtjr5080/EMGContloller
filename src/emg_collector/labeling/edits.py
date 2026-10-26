"""Stable new identities for explicit review edits; raw repetitions never change."""

import uuid
from emg_collector.multimodal.schema import Attempt


def new_attempt_id(set_id):
    return set_id + "-R" + uuid.uuid4().hex[:12]


def edit_attempts(
    attempts,
    operation,
    ids=(),
    *,
    set_id=None,
    start_ns=None,
    end_ns=None,
    split_ns=None,
):
    if operation == "add":
        ids = ()
    selected = [
        a for a in sorted(attempts, key=lambda a: a.start_ns) if a.attempt_id in ids
    ]
    if len(selected) != len(set(ids)):
        raise ValueError("selected attempt no longer exists")
    created = []
    if operation == "add":
        created = [
            Attempt(
                attempt_id=new_attempt_id(set_id),
                set_id=set_id,
                start_ns=start_ns,
                end_ns=end_ns,
                validity="unknown",
                reasons=["manual_add_requires_review"],
                provisional=False,
            )
        ]
    elif operation == "delete":
        if not selected:
            raise ValueError("select attempts to delete")
    elif operation == "split":
        if (
            len(selected) != 1
            or split_ns is None
            or not selected[0].start_ns < split_ns < selected[0].end_ns
        ):
            raise ValueError("split boundary must lie inside one selected attempt")
        original = selected[0]
        for start, end in ((original.start_ns, split_ns), (split_ns, original.end_ns)):
            created.append(
                Attempt(
                    attempt_id=new_attempt_id(original.set_id),
                    set_id=original.set_id,
                    start_ns=start,
                    end_ns=end,
                    validity="unknown",
                    reasons=["manual_split_requires_review"],
                    phases={
                        p: t for p, t in original.phases.items() if start <= t <= end
                    },
                    provisional=False,
                )
            )
    elif operation == "merge":
        if len(selected) < 2 or len({a.set_id for a in selected}) != 1:
            raise ValueError("select adjacent attempts from one set")
        between = [
            a
            for a in attempts
            if selected[0].start_ns <= a.start_ns <= selected[-1].start_ns
        ]
        if len(between) != len(selected):
            raise ValueError("merge requires adjacent selected attempts")
        created = [
            Attempt(
                attempt_id=new_attempt_id(selected[0].set_id),
                set_id=selected[0].set_id,
                start_ns=selected[0].start_ns,
                end_ns=selected[-1].end_ns,
                validity="unknown",
                reasons=["manual_merge_requires_review"],
                provisional=False,
            )
        ]
    else:
        raise ValueError("unsupported edit operation")
    if any(a.end_ns <= a.start_ns for a in created):
        raise ValueError("attempt end must follow start")
    keep = [a for a in attempts if a.attempt_id not in ids]
    result = sorted(keep + created, key=lambda a: a.start_ns)
    if any(b.start_ns < a.end_ns for a, b in zip(result, result[1:])):
        raise ValueError("edit would overlap another attempt")
    return result, {
        "operation": operation,
        "source_ids": list(ids),
        "created_ids": [a.attempt_id for a in created],
        "previous": [a.model_dump(mode="json") for a in selected],
    }
