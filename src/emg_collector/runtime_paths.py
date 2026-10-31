"""Read bundled assets separately from persistent recording data."""

import sys
from pathlib import Path


def default_model_path() -> Path:
    candidates = model_candidates()
    return next((p for p in candidates if p.is_file()), candidates[0])


def model_candidates() -> list[Path]:
    """Search a bounded set of portable, bundled and source asset locations."""
    name = "pose_landmarker_lite.task"
    if getattr(sys, "frozen", False):
        primary = Path(sys._MEIPASS) / "models" / name
        bases = [Path(sys.executable).resolve().parent,
                 Path(sys.executable).resolve().parent.parent]
    else:
        primary = Path("models") / name
        bases = [Path(__file__).resolve().parents[2]]
    bases += [Path.cwd(), Path.cwd().parent]
    return list(dict.fromkeys([primary] + [p / sub / name for p in bases for sub in ("models", "")]))


def resolve_model_path(preferred=None) -> Path:
    if preferred and Path(preferred).is_file():
        return Path(preferred).resolve()
    path = default_model_path()
    if path.is_file():
        return path.resolve()
    raise FileNotFoundError(
        "MediaPipe 모델을 찾을 수 없습니다. 프로그램 옆 models 폴더에 "
        "pose_landmarker_lite.task를 넣거나 장치 설정에서 모델을 선택하세요."
    )


def default_dataset_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "datasets"
    return Path.cwd() / "datasets"
