"""Append-only complete review snapshots; acquisition files remain immutable."""

import csv
import json
import os
import time
import uuid
from pathlib import Path

from emg_collector.multimodal.schema import Attempt, SetRecord
from emg_collector.storage.multimodal_writer import atomic_json, file_info


def read_csv(root, name):
    with (Path(root) / name).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def read_attempts(root):
    result = []
    for row in read_csv(root, "repetitions.csv"):
        for key in ("reasons", "phases"):
            row[key] = json.loads(row[key])
        row["rom_deg"] = row["rom_deg"] or None
        result.append(Attempt.model_validate(row))
    return result


def read_sets(root):
    result = []
    for row in read_csv(root, "sets.csv"):
        for key in (
            "rest_before_s",
            "target_repetitions",
            "end_ns",
            "termination_reason",
            "failure_attempt_id",
            "failure_attempt_observed",
        ):
            row[key] = row[key] or None
        result.append(SetRecord.model_validate(row))
    return result


def review_history(root):
    result = []
    previous = None
    with (Path(root) / "annotations.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            entry = json.loads(line)
            if entry.get("kind") != "human_review":
                continue
            if entry["previous_revision"] != previous:
                raise ValueError("annotation revision chain broken")
            previous = entry["revision"]
            result.append(entry)
    return result


def effective_review(root):
    history = review_history(root)
    if history:
        last = history[-1]
        return [SetRecord.model_validate(s) for s in last["sets"]], [
            Attempt.model_validate(a) for a in last["attempts"]
        ]
    return read_sets(root), read_attempts(root)


def agreement_report(previous, current):
    old = {a["attempt_id"]: a for a in previous}
    pairs = [(old[a["attempt_id"]], a) for a in current if a["attempt_id"] in old]
    if not pairs:
        return {
            "paired_attempts": 0,
            "agreement": None,
            "kappa": None,
            "boundary_mae_ms": None,
            "angle_mae_deg": None,
        }
    n = len(pairs)
    observed = sum(a["validity"] == b["validity"] for a, b in pairs) / n
    expected = sum(
        sum(a["validity"] == v for a, b in pairs)
        * sum(b["validity"] == v for a, b in pairs)
        / n**2
        for v in ("valid", "invalid", "unknown")
    )
    boundary = sum(
        abs(a[key] - b[key]) for a, b in pairs for key in ("start_ns", "end_ns")
    ) / (2 * n * 1e6)
    return {
        "paired_attempts": n,
        "agreement": observed,
        "kappa": (observed - expected) / (1 - expected) if expected < 1 else None,
        "boundary_mae_ms": boundary,
        "angle_mae_deg": None,
    }


def append_review(
    root,
    reviewer_id,
    reason,
    sets,
    attempts,
    objective_review=False,
    adjudication=False,
):
    sets = [SetRecord.model_validate(s.model_dump()) for s in sets]
    attempts = [Attempt.model_validate(a.model_dump()) for a in attempts]
    root = Path(root)
    if not reviewer_id.strip() or not reason.strip():
        raise ValueError("reviewer ID and revision reason required")
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (root / "completion_manifest.json").read_text(encoding="utf-8")
    )
    if manifest["status"] != "complete":
        raise ValueError("incomplete/recovered sessions cannot have confirmed labels")
    if objective_review and not (
        metadata["consent"]["video_storage"] and metadata["consent"]["video_access"]
    ):
        raise ValueError(
            "objective review requires accessible consented video; no alternative evidence adapter is configured"
        )
    set_map = {s.set_id: s for s in sets}
    if not set_map or len(set_map) != len(sets):
        raise ValueError("missing or duplicate set IDs")
    if len({a.attempt_id for a in attempts}) != len(attempts):
        raise ValueError("duplicate attempt IDs")
    for a in attempts:
        s = set_map.get(a.set_id)
        if (
            s is None
            or s.end_ns is None
            or a.start_ns < s.start_ns
            or a.end_ns > s.end_ns
        ):
            raise ValueError(f"{a.attempt_id}: attempt outside set")
        if any(t < a.start_ns or t > a.end_ns for t in a.phases.values()):
            raise ValueError(f"{a.attempt_id}: phase outside attempt")
    for s in sets:
        ordered = sorted(
            [a for a in attempts if a.set_id == s.set_id], key=lambda a: a.start_ns
        )
        if any(b.start_ns < a.end_ns for a, b in zip(ordered, ordered[1:])):
            raise ValueError(f"{s.set_id}: overlapping attempts")
    history = review_history(root)
    # Compare independent assessments before marking a pilot adjudicated.
    clean_attempts = [
        a.model_copy(update={"provisional": False}).model_dump(mode="json")
        for a in attempts
    ]
    clean_sets = [
        s.model_copy(
            update={
                "review_status": "provisional",
                "objective_review": objective_review,
            }
        ).model_dump(mode="json")
        for s in sets
    ]
    for row in clean_sets:
        own = [a for a in attempts if a.set_id == row["set_id"]]
        failure = next(
            (a for a in own if a.attempt_id == row["failure_attempt_id"]), None
        )
        row["observed_valid_count"] = sum(
            a.validity == "valid" and (failure is None or a.end_ns <= failure.start_ns)
            for a in own
        )
        row["censoring_status"] = (
            "unknown" if any(a.validity == "unknown" for a in own) else "right_censored"
        )
    previous = history[-1] if history else None
    agreement = False
    if previous and previous["reviewer_id"] != reviewer_id:
        previous_sets = [
            {
                **s,
                "review_status": "provisional",
                "censoring_status": (
                    "right_censored"
                    if s["censoring_status"] == "exact"
                    else s["censoring_status"]
                ),
            }
            for s in previous["sets"]
        ]
        agreement = (
            previous_sets == clean_sets and previous["attempts"] == clean_attempts
        )
    confirm = (
        objective_review
        and bool(previous)
        and previous["reviewer_id"] != reviewer_id
        and (agreement or adjudication)
    )
    for row in clean_sets:
        row["review_status"] = "confirmed" if confirm else "provisional"
        if confirm and row["termination_reason"] == "technical_failure":
            row["censoring_status"] = "exact"
    if confirm:
        from emg_collector.multimodal.schema import remaining

        for row in clean_sets:
            if (
                row["termination_reason"] == "technical_failure"
                and remaining(SetRecord.model_validate(row), attempts, 0) is None
            ):
                raise ValueError(
                    "technical failure confirmation requires definite failed attempt and no earlier unknowns"
                )
    entry = {
        "kind": "human_review",
        "revision": uuid.uuid4().hex,
        "previous_revision": previous["revision"] if previous else None,
        "reviewer_id": reviewer_id,
        "created_at_utc_ns": time.time_ns(),
        "reason": reason,
        "objective_review": objective_review,
        "independent_agreement": agreement,
        "adjudication": adjudication,
        "sets": clean_sets,
        "attempts": clean_attempts,
    }
    entry["agreement_report"] = (
        agreement_report(previous["attempts"], clean_attempts) if previous else None
    )
    with (root / "annotations.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    manifest["files"]["annotations.jsonl"] = {
        "exists": True,
        **file_info(root / "annotations.jsonl"),
    }
    manifest["labels_confirmed"] = confirm
    atomic_json(root / "completion_manifest.json", manifest)
    return entry
