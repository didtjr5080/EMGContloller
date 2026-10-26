"""One session eligibility decision for CLI/UI export and diagnostics."""

import json
from pathlib import Path
from emg_collector.labeling.review import effective_review
from emg_collector.multimodal.validator import inspect_session
from emg_collector.multimodal.schema import remaining


def session_eligibility(root, *, synthetic, allow_pilot=False, quality_policy=None):
    root = Path(root)
    result = {
        "session_id": root.name,
        "status": "corrupt",
        "error_codes": [],
        "fields": [],
    }
    try:
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("schema_version") != "3.0.0":
            result["status"] = "wrong_schema"
            return result
        if metadata.get("synthetic") is not synthetic:
            result["status"] = "different_mode"
            return result
        manifest_path = root / "completion_manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {}
        )
        if manifest.get("status") != "complete":
            result["status"] = (
                "recovered" if manifest.get("status") == "recovered" else "incomplete"
            )
            result["error_codes"] = ["acquisition_not_complete"]
            return result
        inspection = inspect_session(root, quality_policy)
        result["quality"] = inspection["quality"]
        if inspection["integrity_errors"]:
            result["error_codes"] = ["integrity_invalid"]
            allowed = {
                "metadata.json",
                "samples.csv",
                "pose_metrics.csv",
                "pose_landmarks.csv",
                "sets",
                "repetitions",
                "sync.json",
                "quality.json",
                "annotations.jsonl",
                "completion_manifest",
                "review",
                "schema",
                "video",
                "labeled_samples",
            }
            fields = []
            for error in inspection["integrity_errors"]:
                field = error.split("/", 1)[-1].split("]", 1)[0].split("/", 1)[0]
                fields.append(field if field in allowed else "dataset")
            result["fields"] = sorted(set(fields))
            if all(f == "review" for f in fields):
                result["status"] = "unreviewed"
            if inspection["quality"] and any(
                r != "alignment_unverified" for r in inspection["quality"]["reasons"]
            ):
                result["status"] = "quality_failed"
                result["error_codes"] += inspection["quality"]["reasons"]
            return result
        if metadata["protocol"]["status"] == "PILOT" and not allow_pilot:
            result.update(
                status="pilot_protocol", error_codes=["pilot_requires_opt_in"]
            )
            return result
        sets, attempts = effective_review(root)
        if not any(s.review_status == "confirmed" for s in sets):
            result["status"] = "unreviewed"
            return result
        if not any(remaining(s, attempts, 0) is not None for s in sets):
            result["status"] = "censored"
            return result
        result["status"] = "eligible"
        return result
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        result["error_codes"] = ["session_structure_invalid"]
        result["fields"] = ["metadata"]
        return result
