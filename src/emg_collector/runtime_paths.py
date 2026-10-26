"""Read bundled assets separately from persistent recording data."""

import sys
from pathlib import Path


def default_model_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "models" / "pose_landmarker_lite.task"
    return Path("models/pose_landmarker_lite.task")


def default_dataset_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "datasets"
    return Path.cwd() / "datasets"
