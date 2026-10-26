"""Single bounded writer thread; manifest is the final commit marker."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from pathlib import Path
from queue import Queue, Full
from threading import Thread

from emg_collector.multimodal.schema import Sample

STREAMS = {
    "samples.csv": list(Sample.model_fields),
    "pose_landmarks.csv": [
        "frame_id",
        "landmark_id",
        "capture_host_ns",
        "infer_host_ns",
        "x",
        "y",
        "z",
        "world_x",
        "world_y",
        "world_z",
        "visibility",
        "presence",
        "validity",
    ],
    "pose_metrics.csv": [
        "frame_id",
        "capture_host_ns",
        "infer_host_ns",
        "arm",
        "elbow_angle_deg",
        "trunk_tilt_deg",
        "upperarm_delta_deg",
        "quality_mask",
    ],
    "frame_timestamps.csv": [
        "frame_id",
        "capture_host_ns",
        "timestamp_source",
        "segment",
        "segment_frame",
        "saved",
        "inference_submitted",
    ],
    "sets.csv": [
        "set_id",
        "arm",
        "set_number",
        "exercise",
        "load_kg",
        "dumbbell_count",
        "rest_before_s",
        "target_repetitions",
        "start_ns",
        "end_ns",
        "termination_reason",
        "failure_attempt_id",
        "failure_attempt_observed",
        "review_status",
        "objective_review",
        "observed_valid_count",
        "censoring_status",
    ],
    "repetitions.csv": [
        "attempt_id",
        "set_id",
        "start_ns",
        "end_ns",
        "validity",
        "reasons",
        "phases",
        "rom_deg",
        "provisional",
    ],
    "events.csv": ["host_ns", "sample_index", "event_type", "detail"],
}


def atomic_json(path: Path, data):
    part = path.with_name(path.name + ".tmp")
    with part.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, allow_nan=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(part, path)


def file_info(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    rows = None
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as fh:
            rows = max(0, sum(1 for _ in csv.reader(fh)) - 1)
    return {"sha256": digest.hexdigest(), "rows": rows, "bytes": path.stat().st_size}


def video_playable(path):
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        ok, _ = cap.read()
        if not ok:
            return False
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if count < 1:
            return False
        cap.set(cv2.CAP_PROP_POS_FRAMES, count - 1)
        return bool(cap.read()[0])
    finally:
        cap.release()


def build_manifest(root, video_required, status="complete", failures=None):
    root = Path(root)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    files = {}
    required = [
        *STREAMS,
        "metadata.json",
        "sync.json",
        "quality.json",
        "annotations.jsonl",
    ]
    errors = list(failures or [])
    if metadata.get("labeling", {}).get("sample_labels_file") == "labeled_samples.csv":
        required.append("labeled_samples.csv")
    for name in required:
        path = root / name
        files[name] = {"exists": path.exists()}
        if path.exists():
            files[name].update(file_info(path))
        else:
            errors.append(f"missing stream: {name}")
    video_files = (
        sorted((root / "video").glob("*.avi")) if (root / "video").exists() else []
    )
    if video_required and not video_files:
        errors.append("required video missing or unfinished")
    for path in video_files:
        playable = video_playable(path)
        files[path.relative_to(root).as_posix()] = {
            "exists": True,
            **file_info(path),
            "playable": playable,
        }
        if not playable:
            errors.append(f"unplayable video: {path.name}")
    mapping = root / "frame_timestamps.csv"
    if mapping.exists() and video_files:
        import cv2

        counts = {}
        for path in video_files:
            cap = cv2.VideoCapture(str(path))
            counts[path.name] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
        with mapping.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["saved"] == "True" and (
                    row["segment"] not in counts
                    or not 0 <= int(row["segment_frame"]) < counts[row["segment"]]
                ):
                    errors.append("video frame mapping exceeds playable segment")
                    break
    if list(root.rglob("*.part")):
        errors.append("unfinished .part streams retained")
    manifest = {
        "schema_version": "3.0.0",
        "synthetic": json.loads(
            (root / "metadata.json").read_text(encoding="utf-8")
        ).get("synthetic"),
        "status": "incomplete" if errors or status == "incomplete" else status,
        "video_required": video_required,
        "files": files,
        "errors": errors,
        "labels_confirmed": False,
    }
    atomic_json(root / "completion_manifest.json", manifest)
    return manifest


class MultimodalWriter:
    def __init__(
        self,
        root,
        metadata,
        video_required=False,
        queue_size=20_000,
        shutdown_timeout_s=5,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.video_required = video_required
        self.metadata = metadata
        self.queue = Queue(maxsize=queue_size)
        self.error = None
        self.overflow_count = 0
        self.closed = False
        self.shutdown_timeout_s = shutdown_timeout_s
        atomic_json(self.root / "metadata.json", metadata)
        atomic_json(
            self.root / "completion_manifest.json",
            {"status": "incomplete", "video_required": video_required, "files": {}},
        )
        self.thread = Thread(target=self._run, name="multimodal-writer", daemon=True)
        self.thread.start()

    def submit(self, stream, row):
        if self.closed:
            raise RuntimeError("writer closed")
        if self.error:
            raise RuntimeError(f"writer failed: {self.error}")
        if stream not in STREAMS and stream != "annotations.jsonl":
            raise ValueError(f"unknown stream: {stream}")
        try:
            self.queue.put_nowait((stream, row))
        except Full:
            self.overflow_count += 1
            raise RuntimeError(f"quality failure: {stream} writer queue overflow")

    def _run(self):
        handles = {}
        try:
            writers = {}
            for name, columns in STREAMS.items():
                fh = (self.root / (name + ".part")).open(
                    "x", newline="", encoding="utf-8"
                )
                handles[name] = fh
                writers[name] = csv.DictWriter(fh, fieldnames=columns)
                writers[name].writeheader()
                fh.flush()
            handles["annotations.jsonl"] = (self.root / "annotations.jsonl.part").open(
                "x", encoding="utf-8"
            )
            while True:
                item = self.queue.get()
                if item is None:
                    break
                name, row = item
                if name == "annotations.jsonl":
                    handles[name].write(json.dumps(row, ensure_ascii=False) + "\n")
                else:
                    encoded = {
                        k: json.dumps(v) if isinstance(v, (dict, list)) else v
                        for k, v in row.items()
                    }
                    writers[name].writerow(encoded)
                handles[name].flush()
            for fh in handles.values():
                fh.flush()
                os.fsync(fh.fileno())
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            for fh in handles.values():
                fh.close()

    def _close(self):
        if self.closed:
            return not self.thread.is_alive()
        self.closed = True
        deadline = time.monotonic() + self.shutdown_timeout_s
        while self.thread.is_alive() and time.monotonic() < deadline:
            try:
                self.queue.put(None, timeout=0.1)
                break
            except Full:
                pass
        self.thread.join(timeout=max(0, deadline - time.monotonic()))
        if self.thread.is_alive():
            self.error = "writer_shutdown_timeout; original .part files retained"
            return False
        return True

    def close_incomplete(self):
        return self._close()

    def finalize(self, sync, quality, failures=None):
        if not self._close():
            raise TimeoutError(self.error)
        errors = list(failures or [])
        if self.error:
            errors.append(self.error)
        if self.overflow_count:
            errors.append(f"writer queue overflow: {self.overflow_count}")
        atomic_json(self.root / "sync.json", sync)
        atomic_json(self.root / "quality.json", quality)
        if not self.error:
            for name in [*STREAMS, "annotations.jsonl"]:
                src = self.root / (name + ".part")
                dst = self.root / name
                if dst.exists():
                    raise FileExistsError(dst)
                src.rename(dst)
            if (
                self.metadata.get("labeling", {}).get("sample_labels_file")
                == "labeled_samples.csv"
            ):
                from emg_collector.labeling.sample_labels import write_labeled_samples

                write_labeled_samples(self.root)
        return build_manifest(self.root, self.video_required, failures=errors)


def recover(root):
    """Preserve originals. Recover text as separate copies; never confirm labels."""
    import shutil

    root = Path(root)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    for part in root.glob("*.part"):
        target = part.with_name(part.name + ".recovered")
        if not target.exists():
            with part.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
    return build_manifest(
        root,
        metadata.get("consent", {}).get("video_storage", False),
        status="incomplete",
        failures=[
            "crash recovery; originals retained; manual stream/video verification required"
        ],
    )
