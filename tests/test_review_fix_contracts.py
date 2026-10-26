# Imported pytest fixtures are resolved by name rather than ordinary references.
# ruff: noqa: F811
import json
import copy
from types import SimpleNamespace

import pytest
import numpy as np
from test_review_fix_regressions import dataset, original_dataset  # noqa: F401

from emg_collector.sync.clock_alignment import (
    map_sample,
    aligned_samples,
    decision_time,
    fit_clock,
    load_clock_mappings,
    publish_alignment,
)
from emg_collector.quality.window import window_quality
from emg_collector.acquisition.watchdog import WatchdogPolicy, StreamWatchdog
from emg_collector.labeling.review import (
    read_sets,
    read_attempts,
    review_history,
    append_review,
    effective_review,
)
from emg_collector.labeling.review_contract import (
    evidence_context,
    disagreement_fields,
    recover_review_transaction,
)
from emg_collector.labeling.edits import edit_attempts
from emg_collector.labeling.validation import validate_annotations
from emg_collector.storage.multimodal_writer import atomic_json, file_info
from emg_collector.storage.training_export import export_training


def mapping(offset=0, epoch=0, available=0, scope="causal", status="validated"):
    return {
        str(epoch): [
            {
                "epoch_id": epoch,
                "mapping_version": f"known-{epoch}",
                "method": "synthetic_reference",
                "offset_ns": offset,
                "drift_ppm": 100,
                "uncertainty_ns": 1000,
                "valid_from_device_us": 0,
                "valid_to_device_us": 10_000_000,
                "available_host_ns": available,
                "fit_scope": scope,
                "status": status,
            }
        ]
    }


def test_mapping_uses_epoch_drift_and_preserves_receipt_availability():
    sample = {"epoch_id": 0, "unwrapped_time_us": 100000, "host_receive_ns": 600000000}
    result = map_sample(sample, mapping())
    assert (
        result["measurement_host_ns"] == 100010000
        and result["alignment_status"] == "aligned"
    )
    assert aligned_samples([sample], mapping(), decision_host_ns=500000000) == []
    assert (
        map_sample(sample, mapping(available=700000000), decision_host_ns=650000000)[
            "measurement_host_ns"
        ]
        is None
    )
    assert (
        map_sample(sample, mapping(scope="posthoc"), decision_host_ns=650000000)[
            "measurement_host_ns"
        ]
        is None
    )
    assert (
        map_sample({**sample, "epoch_id": 1}, mapping())["measurement_host_ns"] is None
    )
    both = {**mapping(), **mapping(offset=2000000000, epoch=1)}
    assert (
        map_sample({**sample, "epoch_id": 1}, both)["measurement_host_ns"] == 2100010000
    )


def test_receive_regression_does_not_claim_physical_validation():
    fitted = fit_clock([(0, 500000000), (100000, 600000000), (200000, 700000000)])
    assert fitted["residual_rms_ns"] < 1 and fitted["latency_bias_ns"] is None
    assert fitted["physical_sync_error_ms"] is None
    assert (
        map_sample({"epoch_id": 0, "unwrapped_time_us": 100000}, {"0": [fitted]})[
            "alignment_status"
        ]
        == "alignment_unverified"
    )


def test_burst_receipts_keep_distinct_measurement_times_and_decision_delay():
    rows = [
        {"epoch_id": 0, "unwrapped_time_us": us, "host_receive_ns": 600000000}
        for us in (100000, 200000, 300000)
    ]
    physical = aligned_samples(rows, mapping(), decision_host_ns=700000000)
    assert [r["measurement_host_ns"] for r in physical] == [
        100010000,
        200020000,
        300030000,
    ]
    attempt = SimpleNamespace(end_ns=300000000)
    poses = [dict(capture_host_ns=300000000, infer_host_ns=350000000)]
    assert decision_time(attempt, poses, 80000000, 500000000) == 380000000
    assert (
        decision_time(
            attempt,
            [dict(capture_host_ns=300000000, infer_host_ns=2000000000)],
            80000000,
            500000000,
        )
        is None
    )


def signal_rows():
    return [
        dict(
            measurement_host_ns=i * 2_000_000,
            epoch_id=0,
            alignment_status="aligned",
            s1_env=400,
            s1_raw=2000,
            s2_env=300,
            s2_raw=2100,
        )
        for i in range(1001)
    ]


def test_normal_and_jittered_emg_quality():
    rows = signal_rows()
    assert window_quality(rows, 0, 2_000_000_000)["eligible"]
    for i, row in enumerate(rows[1:-1]):
        row["measurement_host_ns"] += (i % 3 - 1) * 100000
    q = window_quality(rows, 0, 2_000_000_000)
    assert q["eligible"] and q["coverage_ratio"] > 0.9 and q["expected_samples"] == 1001


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("sparse", "coverage_insufficient"),
        ("gap", "gap_exceeded"),
        ("prefix", "gap_exceeded"),
        ("suffix", "gap_exceeded"),
        ("clip", "clipping_exceeded"),
        ("epoch", "epoch_crossing"),
        ("duplicates", "coverage_insufficient"),
    ],
)
def test_emg_gaps_clipping_epochs_and_duplicate_bursts_are_not_continuous(kind, reason):
    rows = signal_rows()
    if kind == "sparse":
        rows = rows[::1000]
    if kind == "gap":
        rows = rows[:450] + rows[550:]
    if kind == "prefix":
        rows = rows[30:]
    if kind == "suffix":
        rows = rows[:-30]
    if kind == "clip":
        for row in rows:
            row["s1_raw"] = 4095
    if kind == "epoch":
        for row in rows[500:]:
            row["epoch_id"] = 1
    if kind == "duplicates":
        for row in rows:
            row["measurement_host_ns"] = 1000000000
    quality = window_quality(rows, 0, 2_000_000_000)
    assert not quality["eligible"] and reason in quality["reasons"]


def test_watchdog_start_stall_and_jitter_recovery_without_sleep():
    policy = WatchdogPolicy(startup_timeout_s=5, stall_timeout_s=2, grace_s=0.2)
    watchdog = StreamWatchdog(0, policy)
    assert watchdog.check(5_100_000_000) is None
    assert watchdog.check(5_300_000_000) == "start_timeout"
    watchdog.mark_valid(1_000_000_000)
    assert watchdog.check(3_100_000_000) is None
    watchdog.mark_valid(3_100_000_000)
    assert watchdog.check(4_000_000_000) is None
    assert watchdog.check(5_400_000_000) == "stall"


def reset_reviews(session):
    (session / "annotations.jsonl").write_text("", encoding="utf-8")
    manifest = json.loads((session / "completion_manifest.json").read_text())
    manifest["files"]["annotations.jsonl"] = {
        "exists": True,
        **file_info(session / "annotations.jsonl"),
    }
    manifest["labels_confirmed"] = False
    atomic_json(session / "completion_manifest.json", manifest)


def assess(
    session, reviewer, sets=None, attempts=None, objective=True, expected=..., **options
):
    history = review_history(session)
    previous = history[-1]["revision"] if history else None
    return append_review(
        session,
        reviewer,
        "synthetic assessment",
        sets or read_sets(session),
        attempts or read_attempts(session),
        objective,
        mode="independent",
        expected_revision=previous if expected is ... else expected,
        base_revision="acquisition",
        evidence=evidence_context(session),
        **options,
    )


@pytest.mark.parametrize(
    "first_objective,second_reviewer,confirmed",
    [(False, "B", False), (True, "A", False), (True, "B", True)],
)
def test_confirmation_requires_two_completed_different_objective_assessments(
    dataset, first_objective, second_reviewer, confirmed
):
    session = dataset / "sessions/M_SYNTH01"
    reset_reviews(session)
    first = assess(session, "A", objective=first_objective)
    second = assess(session, second_reviewer)
    record = effective_review(session)[0][0]
    assert (record.review_status == "confirmed") == confirmed
    assert (record.censoring_status == "exact") == confirmed
    assert (
        first["completed_at_utc_ns"] is not None
        if first_objective
        else first["completed_at_utc_ns"] is None
    )
    if confirmed:
        assert len(second["confirmation_assessment_ids"]) == 2


def test_stale_revision_and_obsolete_alignment_block_confirmation(dataset):
    session = dataset / "sessions/M_SYNTH01"
    with pytest.raises(ValueError, match="stale_revision"):
        assess(session, "C", expected=None)
    history = review_history(session)
    context = evidence_context(session)
    mappings = load_clock_mappings(session)
    mappings["0"][0]["offset_ns"] += 100000000
    original = (session / "sync.json").read_bytes()
    publish_alignment(session, mappings)
    record = effective_review(session)[0][0]
    assert record.review_status == "provisional" and record.censoring_status != "exact"
    assert (session / "sync.json").read_bytes() == original
    with pytest.raises(ValueError, match="obsolete_evidence"):
        append_review(
            session,
            "C",
            "obsolete",
            read_sets(session),
            read_attempts(session),
            True,
            mode="independent",
            expected_revision=history[-1]["revision"],
            base_revision="acquisition",
            evidence=context,
        )


def test_adjudication_names_two_assessments_and_all_resolutions(dataset):
    session = dataset / "sessions/M_SYNTH01"
    reset_reviews(session)
    a = assess(session, "A")
    attempts = read_attempts(session)
    attempts[0].validity = "invalid"
    b = assess(session, "B", attempts=attempts)
    assert effective_review(session)[0][0].review_status == "provisional"
    differences = disagreement_fields(a, b)
    options = dict(
        mode="adjudication",
        expected_revision=b["revision"],
        evidence=evidence_context(session),
        assessment_ids=[a["assessment_id"], b["assessment_id"]],
    )
    with pytest.raises(ValueError, match="resolution"):
        append_review(
            session, "C", "resolve", read_sets(session), attempts, True, **options
        )
    c = append_review(
        session,
        "C",
        "observed complete video; corrected first attempt",
        read_sets(session),
        attempts,
        True,
        resolved_disagreements=differences,
        **options,
    )
    assert (
        c["sets"][0]["review_status"] == "confirmed"
        and c["sets"][0]["observed_valid_count"] == 14
    )


def test_failed_manifest_write_is_recoverable_and_never_effectively_confirmed(
    dataset, monkeypatch
):
    import emg_collector.labeling.review_contract as contract

    session = dataset / "sessions/M_SYNTH01"
    before = (session / "annotations.jsonl").read_bytes()
    atomic = contract.atomic_json
    count = 0

    def fail_final(path, data):
        nonlocal count
        if path.name == "completion_manifest.json":
            count += 1
            if count == 2:
                raise OSError("injected manifest failure")
        return atomic(path, data)

    monkeypatch.setattr(contract, "atomic_json", fail_final)
    with pytest.raises(OSError):
        assess(session, "C")
    assert (session / "annotations.jsonl").read_bytes().startswith(before)
    assert effective_review(session)[0][0].review_status == "provisional"
    assert (
        json.loads((session / "completion_manifest.json").read_text())[
            "labels_confirmed"
        ]
        is False
    )
    monkeypatch.setattr(contract, "atomic_json", atomic)
    assert recover_review_transaction(session)
    assert effective_review(session)[0][0].review_status == "confirmed"


def test_default_export_isolates_corrupt_incomplete_and_strict_is_transactional(
    dataset, tmp_path
):
    hashes = {
        name: file_info(dataset / "sessions/M_SYNTH01" / name)["sha256"]
        for name in ("samples.csv", "annotations.jsonl")
    }
    corrupt = dataset / "sessions/M_CORRUPT"
    corrupt.mkdir()
    (corrupt / "metadata.json").write_text("not json: PRIVATE-SENTINEL")
    incomplete = dataset / "sessions/M_INCOMPLETE"
    incomplete.mkdir()
    metadata = json.loads((dataset / "sessions/M_SYNTH01/metadata.json").read_text())
    metadata["session_id"] = "M_INCOMPLETE"
    atomic_json(incomplete / "metadata.json", metadata)
    out = tmp_path / "isolated"
    result = export_training(dataset, out, synthetic=True, allow_pilot=True)
    assert result["examples"] == 15
    report = json.loads((out / "exclusion_report.json").read_text())
    assert (
        report["session_counts"]["corrupt"] == 1
        and report["session_counts"]["incomplete"] == 1
    )
    assert "PRIVATE-SENTINEL" not in (out / "exclusion_report.json").read_text()
    for name, digest in hashes.items():
        assert file_info(dataset / "sessions/M_SYNTH01" / name)["sha256"] == digest
    with pytest.raises(ValueError, match="strict"):
        export_training(
            dataset, tmp_path / "strict", synthetic=True, allow_pilot=True, strict=True
        )
    assert not (tmp_path / "strict/export_manifest.json").exists()


def test_export_io_failure_never_publishes_complete_output(
    dataset, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        np,
        "savez_compressed",
        lambda *a, **k: (_ for _ in ()).throw(OSError("injected disk failure")),
    )
    with pytest.raises(OSError):
        export_training(dataset, tmp_path / "failed", synthetic=True, allow_pilot=True)
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob("failed.part-*/export_manifest.json"))


def test_edit_ids_failure_reference_and_phase_order(dataset):
    session = dataset / "sessions/M_SYNTH01"
    sets, attempts = read_sets(session), read_attempts(session)
    raw = (session / "repetitions.csv").read_bytes()
    updated, split = edit_attempts(
        attempts,
        "split",
        [attempts[0].attempt_id],
        split_ns=attempts[0].start_ns + 1_500_000_000,
    )
    assert len(updated) == 17 and len(set(split["created_ids"])) == 2
    assert all(a.validity == "unknown" for a in updated[:2])
    merged, merge = edit_attempts(updated, "merge", split["created_ids"])
    assert len(merged) == 16 and merge["source_ids"] == split["created_ids"]
    deleted, _ = edit_attempts(attempts, "delete", ["A16"])
    with pytest.raises(ValueError, match="failure_attempt_id"):
        validate_annotations(sets, deleted)
    malformed = copy.deepcopy(attempts)
    malformed[0].phases = {
        "concentric": malformed[0].start_ns + 2,
        "top": malformed[0].start_ns + 1,
    }
    with pytest.raises(ValueError, match="phase order"):
        validate_annotations(sets, malformed)
    assert (session / "repetitions.csv").read_bytes() == raw


def test_unverified_alignment_is_excluded_unless_diagnostic_opt_in(dataset, tmp_path):
    session = dataset / "sessions/M_SYNTH01"
    mappings = load_clock_mappings(session)
    mappings["0"][0].update(
        method="software_receive_linear_fit",
        status="estimated_unvalidated",
        uncertainty_ns=None,
    )
    publish_alignment(session, mappings)
    reset_reviews(session)
    assess(session, "A")
    assess(session, "B")
    result = export_training(
        dataset, tmp_path / "default", synthetic=True, allow_pilot=True
    )
    assert result["examples"] == 0 and result["excluded"]["alignment_unverified"] == 15
    diagnostic = export_training(
        dataset,
        tmp_path / "diagnostic",
        synthetic=True,
        allow_pilot=True,
        allow_unverified_alignment=True,
    )
    assert diagnostic["examples"] == 15 and diagnostic["warnings"]
    manifest = json.loads((tmp_path / "diagnostic/export_manifest.json").read_text())
    assert manifest["training_ready"] is False
    assert manifest["allow_unverified_alignment"] is True


def test_missing_evidence_and_legacy_assessment_clear_exact(dataset):
    session = dataset / "sessions/M_SYNTH01"
    history = review_history(session)
    for entry in history:
        entry.pop("review_version", None)
    (session / "annotations.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in history), encoding="utf-8"
    )
    record = effective_review(session)[0][0]
    assert record.review_status == "provisional" and record.censoring_status != "exact"
    for path in (session / "video").glob("*.avi"):
        path.unlink()
    with pytest.raises(ValueError, match="missing_evidence"):
        assess(session, "C")
