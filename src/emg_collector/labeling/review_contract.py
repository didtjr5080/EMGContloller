"""Versioned independent assessments and recoverable optimistic revision writes."""

import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from emg_collector.multimodal.schema import Attempt, SetRecord, remaining
from emg_collector.labeling.validation import validate_annotations
from emg_collector.storage.multimodal_writer import (
    atomic_json,
    file_info,
    video_playable,
)
from emg_collector.sync.clock_alignment import (
    ALIGNMENT_VERSION,
    alignment_fingerprint,
    load_clock_mappings,
)

REVIEW_VERSION = "review-2"
TRANSACTION = "review_transaction.json"


@contextmanager
def review_lock(root):
    with (Path(root) / ".review.lock").open("a+b") as fh:
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        fh.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError(
                    "review_conflict: another save is in progress"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError(
                    "review_conflict: another save is in progress"
                ) from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh, fcntl.LOCK_UN)


def evidence_context(root, verify_video=False):
    root = Path(root)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    if verify_video and not (
        metadata["consent"]["video_storage"] and metadata["consent"]["video_access"]
    ):
        raise ValueError("objective review requires accessible consented video")
    manifest = json.loads(
        (root / "completion_manifest.json").read_text(encoding="utf-8")
    )
    names = [
        "metadata.json",
        "samples.csv",
        "pose_metrics.csv",
        "pose_landmarks.csv",
        "frame_timestamps.csv",
        "sets.csv",
        "repetitions.csv",
        "sync.json",
        "quality.json",
    ]
    names += sorted(
        p.relative_to(root).as_posix() for p in (root / "video").glob("*.avi")
    )
    hashes = {}
    for name in names:
        path = root / name
        if not path.is_file():
            raise ValueError(f"missing_evidence: {name}")
        actual = file_info(path)["sha256"]
        if actual != manifest.get("files", {}).get(name, {}).get("sha256"):
            raise ValueError(
                f"evidence_changed: {name}; acquisition integrity must be reviewed"
            )
        hashes[name] = actual
    if verify_video:
        if not (
            metadata["consent"]["video_storage"] and metadata["consent"]["video_access"]
        ):
            raise ValueError("objective review requires accessible consented video")
        videos = list((root / "video").glob("*.avi"))
        if not videos or any(not video_playable(p) for p in videos):
            raise ValueError("missing_evidence: playable video required")
    mappings = load_clock_mappings(root)
    return {
        "source_acquisition_hash": hashlib.sha256(
            json.dumps(hashes, sort_keys=True).encode()
        ).hexdigest(),
        "alignment_version": ALIGNMENT_VERSION + ":" + alignment_fingerprint(mappings),
        "protocol_version": metadata["protocol"]["version"],
        "review_version": REVIEW_VERSION,
    }


def normalize_sets(sets, attempts, objective, confirmed=False):
    result = []
    for s in sets:
        own = [a for a in attempts if a.set_id == s.set_id]
        failure = next((a for a in own if a.attempt_id == s.failure_attempt_id), None)
        relevant = [a for a in own if failure is None or a.start_ns <= failure.start_ns]
        count = sum(
            a.validity == "valid" and (failure is None or a.end_ns <= failure.start_ns)
            for a in own
        )
        status = (
            "unknown"
            if any(a.validity == "unknown" for a in relevant)
            else "right_censored"
        )
        if confirmed and s.termination_reason == "technical_failure":
            status = "exact"
        row = s.model_copy(
            update={
                "review_status": "confirmed" if confirmed else "provisional",
                "objective_review": objective,
                "observed_valid_count": count,
                "censoring_status": status,
            }
        )
        if (
            confirmed
            and s.termination_reason == "technical_failure"
            and remaining(row, attempts, 0) is None
        ):
            raise ValueError(
                "technical failure confirmation requires definite failed attempt and no earlier unknowns"
            )
        result.append(row.model_dump(mode="json"))
    return result


def decision_payload(entry):
    ignored = {
        "review_status",
        "objective_review",
        "observed_valid_count",
        "censoring_status",
    }
    return {
        "sets": [
            {
                k: v
                for k, v in SetRecord.model_validate(s).model_dump(mode="json").items()
                if k not in ignored
            }
            for s in entry["sets"]
        ],
        "attempts": [
            {k: v for k, v in a.items() if k != "provisional"}
            for a in sorted(entry["attempts"], key=lambda a: a["attempt_id"])
        ],
    }


def disagreement_fields(first, second):
    a, b = decision_payload(first), decision_payload(second)
    output = []
    for kind, key in (("sets", "set_id"), ("attempts", "attempt_id")):
        left = {x[key]: x for x in a[kind]}
        right = {x[key]: x for x in b[kind]}
        for identity in sorted(set(left) | set(right)):
            if identity not in left or identity not in right:
                output.append(f"{kind}/{identity}")
                continue
            for field in sorted(set(left[identity]) | set(right[identity])):
                if left[identity].get(field) != right[identity].get(field):
                    output.append(f"{kind}/{identity}/{field}")
    return output


def independent_assessments(history, context):
    return [
        e
        for e in history
        if e.get("review_version") == REVIEW_VERSION
        and e.get("mode") == "independent"
        and e.get("objective_review") is True
        and e.get("completed_at_utc_ns")
        and e.get("base_revision") == "acquisition"
        and e.get("evidence") == context
    ]


def confirmation_valid(entry, history, context):
    if (
        entry.get("evidence") != context
        or not entry.get("objective_review")
        or entry.get("review_version") != REVIEW_VERSION
    ):
        return False
    assessments = {
        e["assessment_id"]: e for e in independent_assessments(history, context)
    }
    ids = entry.get("confirmation_assessment_ids", [])
    if len(ids) != 2 or any(i not in assessments for i in ids):
        return False
    a, b = [assessments[i] for i in ids]
    if a["reviewer_id"] == b["reviewer_id"]:
        return False
    differences = disagreement_fields(a, b)
    if entry.get("mode") == "independent":
        return not differences and entry.get("assessment_id") in ids
    return (
        entry.get("mode") == "adjudication"
        and bool(entry.get("reason", "").strip())
        and set(entry.get("resolved_disagreements", [])) == set(differences)
    )


def effective_state(root, history):
    from emg_collector.labeling.review import read_sets, read_attempts

    root = Path(root)
    if not history:
        return read_sets(root), read_attempts(root)
    last = history[-1]
    sets = [SetRecord.model_validate(s) for s in last["sets"]]
    attempts = [Attempt.model_validate(a) for a in last["attempts"]]
    try:
        context = evidence_context(root)
        confirmed = not (root / TRANSACTION).exists() and confirmation_valid(
            last, history, context
        )
    except (OSError, ValueError, KeyError):
        confirmed = False
    clean = normalize_sets(
        sets, attempts, bool(last.get("objective_review")), confirmed
    )
    return [SetRecord.model_validate(s) for s in clean], attempts


def append_assessment(
    root,
    reviewer_id,
    reason,
    sets,
    attempts,
    objective_review=False,
    adjudication=False,
    *,
    mode=None,
    expected_revision=...,
    base_revision=None,
    evidence=None,
    assessment_ids=None,
    resolved_disagreements=None,
    edit_operations=None,
):
    from emg_collector.labeling.review import review_history, agreement_report

    root = Path(root)
    if not reviewer_id.strip() or not reason.strip():
        raise ValueError("reviewer ID and revision reason required")
    sets = [SetRecord.model_validate(s.model_dump()) for s in sets]
    attempts = [Attempt.model_validate(a.model_dump()) for a in attempts]
    validate_annotations(sets, attempts)
    with review_lock(root):
        if (root / TRANSACTION).exists():
            raise ValueError("review_recovery_required: pending revision transaction")
        history = review_history(root)
        previous = history[-1]["revision"] if history else None
        if expected_revision is not ... and expected_revision != previous:
            raise ValueError("stale_revision: reload before saving")
        manifest = json.loads(
            (root / "completion_manifest.json").read_text(encoding="utf-8")
        )
        if manifest["status"] != "complete":
            raise ValueError(
                "incomplete/recovered sessions cannot have confirmed labels"
            )
        context = evidence_context(root, verify_video=objective_review)
        mode = mode or "draft"
        if mode not in ("draft", "independent", "adjudication"):
            raise ValueError("unknown review mode")
        if mode != "draft":
            if expected_revision is ...:
                raise ValueError("expected_revision required for completed review")
            if evidence != context:
                raise ValueError("obsolete_evidence: reload before saving")
            if mode == "independent" and base_revision != "acquisition":
                raise ValueError("independent assessment must start from acquisition")
        clean_attempts = [
            a.model_copy(update={"provisional": False}).model_dump(mode="json")
            for a in attempts
        ]
        entry = {
            "kind": "human_review",
            "review_version": REVIEW_VERSION,
            "revision": uuid.uuid4().hex,
            "previous_revision": previous,
            "base_revision": base_revision,
            "reviewer_id": reviewer_id,
            "created_at_utc_ns": time.time_ns(),
            "reason": reason,
            "objective_review": objective_review,
            "mode": mode,
            "adjudication": mode == "adjudication",
            "evidence": context,
            "assessment_id": uuid.uuid4().hex if mode == "independent" else None,
            "completed_at_utc_ns": (
                time.time_ns() if mode == "independent" and objective_review else None
            ),
            "sets": normalize_sets(sets, attempts, objective_review),
            "attempts": clean_attempts,
            "edit_operations": edit_operations or [],
            "resolved_disagreements": resolved_disagreements or [],
            "confirmation_assessment_ids": [],
            "agreement_report": None,
            "independent_agreement": False,
        }
        assessments = independent_assessments(history + [entry], context)
        if mode == "independent" and objective_review:
            other = next(
                (a for a in reversed(assessments) if a["reviewer_id"] != reviewer_id),
                None,
            )
            if other:
                entry["agreement_report"] = agreement_report(
                    other["attempts"], clean_attempts
                )
                entry["independent_agreement"] = not disagreement_fields(other, entry)
                if entry["independent_agreement"]:
                    entry["confirmation_assessment_ids"] = [
                        other["assessment_id"],
                        entry["assessment_id"],
                    ]
        elif mode == "adjudication":
            entry["confirmation_assessment_ids"] = assessment_ids or []
            available = {a["assessment_id"]: a for a in assessments}
            if len(assessment_ids or []) != 2 or any(
                i not in available for i in assessment_ids
            ):
                raise ValueError(
                    "adjudication requires two completed independent objective assessments"
                )
            a, b = [available[i] for i in assessment_ids]
            if a["reviewer_id"] == b["reviewer_id"]:
                raise ValueError("adjudication requires different reviewers")
            if set(resolved_disagreements or []) != set(disagreement_fields(a, b)):
                raise ValueError(
                    "all disagreement fields require an explicit resolution"
                )
            entry["agreement_report"] = agreement_report(a["attempts"], b["attempts"])
        confirmed = confirmation_valid(entry, history + [entry], context)
        entry["sets"] = normalize_sets(sets, attempts, objective_review, confirmed)
        _commit_entry(root, entry, manifest, confirmed)
        return entry


def _commit_entry(root, entry, manifest, confirmed):
    before = (root / "annotations.jsonl").read_bytes()
    after = before + (
        json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    staged = root / "annotations.jsonl.next"
    # No intent means the previous save failed before publishing a transaction.
    # The current journal is authoritative; retain that abandoned candidate.
    if staged.exists():
        staged.rename(root / ("annotations.jsonl.abandoned-" + uuid.uuid4().hex))
    with staged.open("xb") as fh:
        fh.write(after)
        fh.flush()
        os.fsync(fh.fileno())
    transaction = {
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "revision": entry["revision"],
    }
    atomic_json(root / TRANSACTION, transaction)
    manifest["labels_confirmed"] = False
    atomic_json(root / "completion_manifest.json", manifest)
    os.replace(staged, root / "annotations.jsonl")
    manifest["files"]["annotations.jsonl"] = {
        "exists": True,
        **file_info(root / "annotations.jsonl"),
    }
    manifest["labels_confirmed"] = confirmed
    atomic_json(root / "completion_manifest.json", manifest)
    (root / TRANSACTION).unlink()


def recover_review_transaction(root):
    from emg_collector.labeling.review import review_history

    root = Path(root)
    with review_lock(root):
        path = root / TRANSACTION
        if not path.exists():
            return False
        transaction = json.loads(path.read_text(encoding="utf-8"))
        current = file_info(root / "annotations.jsonl")["sha256"]
        if current == transaction["before_sha256"]:
            staged = root / "annotations.jsonl.next"
            if (
                not staged.exists()
                or file_info(staged)["sha256"] != transaction["after_sha256"]
            ):
                raise ValueError(
                    "review recovery staged journal missing or changed; originals retained"
                )
            os.replace(staged, root / "annotations.jsonl")
        elif current != transaction["after_sha256"]:
            raise ValueError("review recovery journal conflict; originals retained")
        history = review_history(root)
        confirmed = confirmation_valid(history[-1], history, evidence_context(root))
        manifest = json.loads(
            (root / "completion_manifest.json").read_text(encoding="utf-8")
        )
        manifest["files"]["annotations.jsonl"] = {
            "exists": True,
            **file_info(root / "annotations.jsonl"),
        }
        manifest["labels_confirmed"] = confirmed
        atomic_json(root / "completion_manifest.json", manifest)
        path.unlink()
        return True
