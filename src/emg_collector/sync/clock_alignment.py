from bisect import bisect_right
import hashlib
import json
import math
from pathlib import Path
import numpy as np

ALIGNMENT_VERSION = "alignment-1"


def alignment_fingerprint(mappings):
    return hashlib.sha256(
        json.dumps(mappings, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def load_clock_mappings(root):
    root = Path(root)
    pointer = root / "alignment_current.json"
    path = root / "sync.json"
    if pointer.exists():
        name = json.loads(pointer.read_text(encoding="utf-8"))["file"]
        if Path(name).name != name or not name.startswith("alignment-"):
            raise ValueError("invalid alignment file reference")
        path = root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != json.loads(
            pointer.read_text(encoding="utf-8")
        ).get("sha256"):
            raise ValueError("alignment file hash mismatch")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    mappings = data.get("epochs", {})
    metadata = root / "metadata.json"
    if metadata.exists() and not json.loads(metadata.read_text(encoding="utf-8")).get(
        "synthetic", False
    ):
        for candidates in mappings.values():
            for mapping in candidates if isinstance(candidates, list) else [candidates]:
                if mapping.get("method") == "synthetic_reference":
                    mapping["status"] = (
                        "synthetic_reference_invalid_for_real_acquisition"
                    )
    return mappings


def publish_alignment(root, mappings):
    """Publish a new derived alignment, preserving acquisition and prior versions."""
    from emg_collector.storage.multimodal_writer import atomic_json, file_info

    root = Path(root)
    name = "alignment-" + alignment_fingerprint(mappings)[:20] + ".json"
    path = root / name
    if not path.exists():
        with path.open("x", encoding="utf-8") as fh:
            json.dump(
                {"alignment_version": ALIGNMENT_VERSION, "epochs": mappings},
                fh,
                sort_keys=True,
                allow_nan=False,
            )
    info = file_info(path)
    atomic_json(
        root / "alignment_current.json", {"file": name, "sha256": info["sha256"]}
    )
    manifest = json.loads(
        (root / "completion_manifest.json").read_text(encoding="utf-8")
    )
    manifest["files"][name] = {"exists": True, **info}
    manifest["files"]["alignment_current.json"] = {
        "exists": True,
        **file_info(root / "alignment_current.json"),
    }
    manifest["labels_confirmed"] = False
    atomic_json(root / "completion_manifest.json", manifest)
    return name


def map_sample(
    sample, mappings, *, decision_host_ns=None, max_uncertainty_ns=50_000_000
):
    """Separate physical-time estimates from receipt and coefficient availability."""
    epoch = str(sample["epoch_id"])
    device = int(sample["unwrapped_time_us"])
    candidates = mappings.get(epoch, [])
    if isinstance(candidates, dict):
        candidates = [candidates]
    eligible = []
    for mapping in candidates:
        if str(mapping.get("epoch_id", epoch)) != epoch:
            continue
        if (
            not mapping.get("valid_from_device_us", 0)
            <= device
            <= mapping.get("valid_to_device_us", -1)
        ):
            continue
        if decision_host_ns is not None:
            if (
                mapping.get("fit_scope") != "causal"
                or mapping.get("available_host_ns", 2**63) > decision_host_ns
            ):
                continue
        if mapping.get("offset_ns") is not None:
            eligible.append(mapping)
    result = {
        "measurement_host_ns": None,
        "alignment_status": "alignment_unverified",
        "alignment_uncertainty_ns": None,
        "mapping_version": "unmapped",
    }
    if not eligible:
        return result
    mapping = max(eligible, key=lambda m: m.get("available_host_ns", 0))
    slope = 1 + float(mapping.get("drift_ppm", 0)) / 1e6
    offset = float(mapping["offset_ns"])
    uncertainty = mapping.get("uncertainty_ns")
    if not math.isfinite(slope) or slope <= 0 or not math.isfinite(offset):
        return result
    result.update(
        measurement_host_ns=round(offset + slope * device * 1000),
        alignment_uncertainty_ns=uncertainty,
        mapping_version=mapping.get("mapping_version", "legacy-unverified"),
    )
    if (
        mapping.get("status") == "validated"
        and mapping.get("method") in ("reference_event", "synthetic_reference")
        and uncertainty is not None
        and math.isfinite(uncertainty)
        and 0 <= uncertainty <= max_uncertainty_ns
        and (
            mapping.get("method") != "reference_event"
            or mapping.get("reference_event_ids")
        )
    ):
        result["alignment_status"] = "aligned"
    return result


def aligned_samples(
    samples, mappings, *, decision_host_ns=None, max_uncertainty_ns=50_000_000
):
    return [
        {
            **s,
            **map_sample(
                s,
                mappings,
                decision_host_ns=decision_host_ns,
                max_uncertainty_ns=max_uncertainty_ns,
            ),
        }
        for s in samples
        if decision_host_ns is None or int(s["host_receive_ns"]) <= decision_host_ns
    ]


def decision_time(attempt, poses, debounce_ns, max_latency_ns):
    endpoints = [p for p in poses if int(p["capture_host_ns"]) >= attempt.end_ns]
    if not endpoints:
        return None
    endpoint = min(endpoints, key=lambda p: int(p["capture_host_ns"]))
    decision = max(int(endpoint["infer_host_ns"]), attempt.end_ns + debounce_ns)
    return decision if 0 <= decision - attempt.end_ns <= max_latency_ns else None


def fit_clock(observations):
    """Fit per epoch, retaining receive latency in residuals (not exposure sync)."""
    if len(observations) < 3 or observations[-1][0] <= observations[0][0]:
        return {
            "method": "software_receive_linear_fit",
            "status": "insufficient_data",
            "offset_ns": None,
            "drift_ppm": None,
            "residual_rms_ns": None,
        }
    x = np.asarray([r[0] * 1000 for r in observations], dtype=np.float64)
    y = np.asarray([r[1] for r in observations], dtype=np.float64)
    origin_x, origin_y = x[0], y[0]
    slope, intercept = np.polyfit(x - origin_x, y - origin_y, 1)
    residual = y - (origin_y + intercept + slope * (x - origin_x))
    return {
        "method": "software_receive_linear_fit",
        "status": "estimated_unvalidated",
        "offset_ns": float(origin_y + intercept - slope * origin_x),
        "drift_ppm": float((slope - 1) * 1e6),
        "residual_rms_ns": float(np.sqrt(np.mean(residual**2))),
        "residual_max_ns": float(np.max(np.abs(residual))),
        "physical_sync_error_ms": None,
        "latency_bias_ns": None,
        "uncertainty_ns": None,
        "fit_scope": "posthoc",
        "available_host_ns": int(max(y)),
        "observed_device_us": [int(min(x) / 1000), int(max(x) / 1000)],
        "observed_receive_ns": [int(min(y)), int(max(y))],
        "valid_from_device_us": int(min(x) / 1000),
        "valid_to_device_us": int(max(x) / 1000),
        "mapping_version": "receive-fit-"
        + hashlib.sha256(repr(observations).encode()).hexdigest()[:16],
    }


def align_previous(rows, target_ns, max_gap_ns, key="capture_host_ns"):
    """Causal previous-neighbor; never use future frames or bridge long gaps."""
    if max_gap_ns < 0:
        raise ValueError("maximum gap must be nonnegative")
    index = bisect_right([r[key] for r in rows], target_ns) - 1
    if index < 0 or target_ns - rows[index][key] > max_gap_ns:
        return None
    return rows[index]
