"""Versioned manual labels, independent of acquisition and expert review files."""

import csv
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field, model_validator
from emg_collector.multimodal.schema import Record
from emg_collector.labeling.review import read_sets
from emg_collector.labeling.review_contract import review_lock
from emg_collector.storage.multimodal_writer import file_info


class TruthInterval(Record):
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    elbow_angle_deg: float = Field(ge=0, le=180)
    trunk_fixed: bool | None = None
    pelvis_fixed: bool | None = None
    note: str = ""

    @model_validator(mode="after")
    def bounds(self):
        if self.end_s <= self.start_s:
            raise ValueError("종료 시각은 시작 시각보다 커야 합니다.")
        return self


class ManualTruth(Record):
    reviewer_id: str = Field(min_length=1)
    note: str = ""
    intervals: list[TruthInterval] = Field(min_length=1)

    @model_validator(mode="after")
    def consistency(self):
        if not self.reviewer_id.strip():
            raise ValueError("입력자 ID를 입력하세요.")
        ordered = sorted(self.intervals, key=lambda i: i.start_s)
        if any(b.start_s < a.end_s for a, b in zip(ordered, ordered[1:])):
            raise ValueError("정답 시간 구간이 서로 겹칩니다.")
        return self


def truth_history(root):
    path = Path(root) / "ground_truth.jsonl"
    if not path.exists():
        return []
    previous = None
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["previous_revision"] != previous:
            raise ValueError("정답 수정 이력이 손상되었습니다.")
        ManualTruth.model_validate(entry["data"])
        result.append(entry)
        previous = entry["revision"]
    return result


def save_truth(root, truth, expected_revision=None):
    root = Path(root)
    truth = ManualTruth.model_validate(truth.model_dump() if isinstance(truth, ManualTruth) else truth)
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    records = read_sets(root)
    if len(records) != 1 or records[0].end_ns is None:
        raise ValueError("측정을 종료하고 저장한 뒤 정답을 입력하세요.")
    duration = (records[0].end_ns - metadata["start_host_ns"]) / 1e9
    if any(i.end_s > duration for i in truth.intervals):
        raise ValueError("정답 구간이 측정 종료 시각을 벗어납니다.")
    with review_lock(root):
        history = truth_history(root)
        previous = history[-1]["revision"] if history else None
        if previous != expected_revision:
            raise ValueError("다른 창에서 정답이 변경되었습니다. 닫고 다시 열어주세요.")
        entry = dict(kind="manual_ground_truth", version=1,
                     revision=uuid.uuid4().hex, previous_revision=previous,
                     session_id=root.name, created_at_utc=datetime.now(timezone.utc).isoformat(),
                     status="manual_unverified", origin_host_ns=metadata["start_host_ns"],
                     synthetic=bool(metadata.get("synthetic", False)),
                     samples=file_info(root / "samples.csv"),
                     data=truth.model_dump(mode="json"))
        with (root / "ground_truth.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return entry


def export_truth(root, output):
    history = truth_history(root)
    if not history:
        raise ValueError("먼저 정답을 저장하세요.")
    entry = history[-1]
    if entry["samples"] != file_info(Path(root) / "samples.csv"):
        raise ValueError("원본 측정 파일이 변경되어 정답을 다시 확인해야 합니다.")
    data = entry["data"]
    fields = ["session_id", "revision", "status", "synthetic", "reviewer_id", "session_note", "interval", "start_s", "end_s", "elbow_angle_deg", "trunk_fixed", "pelvis_fixed", "note"]
    if Path(output).resolve() in {p.resolve() for p in Path(root).rglob("*") if p.is_file()}:
        raise ValueError("측정 파일을 덮어쓸 수 없습니다. 새 CSV 경로를 선택하세요.")
    with Path(output).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for i, interval in enumerate(sorted(data["intervals"], key=lambda r: r["start_s"]), 1):
            writer.writerow(dict(session_id=entry["session_id"], revision=entry["revision"], status=entry["status"],
                                 synthetic=entry["synthetic"],
                                 reviewer_id=data["reviewer_id"], session_note=data["note"],
                                 interval=i, **interval))
    return entry


def export_training_truth(root, output):
    """Join manual angle/posture labels to raw EMG by session host time."""
    from bisect import bisect_right

    root = Path(root)
    history = truth_history(root)
    if not history:
        raise ValueError("먼저 각도 정답을 저장하세요.")
    entry = history[-1]
    if entry["samples"] != file_info(root / "samples.csv"):
        raise ValueError("측정 파일이 변경되었습니다. 정답을 다시 확인하세요.")
    if Path(output).resolve().is_relative_to(root.resolve()):
        raise ValueError("원본 보호를 위해 세션 폴더 밖에 내보내세요.")
    intervals = sorted(entry["data"]["intervals"], key=lambda r: r["start_s"])
    starts = [entry["origin_host_ns"] + round(r["start_s"] * 1e9) for r in intervals]
    ends = [entry["origin_host_ns"] + round(r["end_s"] * 1e9) for r in intervals]
    count = 0
    with (root / "samples.csv").open(encoding="utf-8", newline="") as source, Path(output).open("w", encoding="utf-8-sig", newline="") as target:
        reader = csv.DictReader(source)
        extra = ["session_id", "truth_revision", "truth_status", "truth_synthetic", "truth_time_basis", "elapsed_s", "truth_elbow_angle_deg", "truth_trunk_fixed", "truth_pelvis_fixed"]
        writer = csv.DictWriter(target, fieldnames=list(reader.fieldnames) + extra)
        writer.writeheader()
        for row in reader:
            ns = int(row["host_receive_ns"])
            index = bisect_right(starts, ns) - 1
            if index < 0 or ns >= ends[index]:
                continue
            interval = intervals[index]
            writer.writerow(dict(row, session_id=entry["session_id"], truth_revision=entry["revision"],
                                 truth_status="manual_unverified", truth_time_basis="host_receive_unverified_sync",
                                 truth_synthetic=entry["synthetic"],
                                 elapsed_s=(ns-entry["origin_host_ns"])/1e9,
                                 truth_elbow_angle_deg=interval["elbow_angle_deg"],
                                 truth_trunk_fixed=interval["trunk_fixed"], truth_pelvis_fixed=interval["pelvis_fixed"]))
            count += 1
    return count
