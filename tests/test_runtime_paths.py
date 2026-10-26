import sys
from pathlib import Path

from emg_collector.runtime_paths import default_dataset_root, default_model_path


def test_frozen_model_is_bundled_but_data_persists_beside_exe(monkeypatch, tmp_path):
    bundle = tmp_path / "extracted"
    executable = tmp_path / "portable" / "EMGController.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    assert default_model_path() == bundle / "models" / "pose_landmarker_lite.task"
    assert default_dataset_root() == executable.parent / "datasets"


def test_source_paths_preserve_existing_behavior(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.chdir(tmp_path)
    assert default_model_path() == Path("models/pose_landmarker_lite.task")
    assert default_dataset_root() == tmp_path / "datasets"
