"""Append-only complete review snapshots; acquisition files remain immutable."""

import csv
import json
from pathlib import Path

from emg_collector.multimodal.schema import Attempt, SetRecord


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
    from emg_collector.labeling.review_contract import effective_state

    return effective_state(root, review_history(root))


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
    **options,
):
    from emg_collector.labeling.review_contract import append_assessment

    return append_assessment(
        root,
        reviewer_id,
        reason,
        sets,
        attempts,
        objective_review,
        adjudication,
        **options,
    )
