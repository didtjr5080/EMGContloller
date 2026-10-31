import sys
from pathlib import Path

from emg_collector.runtime_paths import default_dataset_root, default_model_path, resolve_model_path


def test_frozen_model_is_bundled_but_data_persists_beside_exe(monkeypatch, tmp_path):
    bundle = tmp_path / "extracted"
    (bundle / "models").mkdir(parents=True)
    (bundle / "models" / "pose_landmarker_lite.task").write_bytes(b"model fixture")
    executable = tmp_path / "portable" / "EMGController.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    assert default_model_path() == bundle / "models" / "pose_landmarker_lite.task"
    assert default_dataset_root() == executable.parent / "datasets"


def test_source_model_is_found_when_launched_from_another_folder(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.chdir(tmp_path)
    assert default_model_path() == Path(__file__).resolve().parents[1] / "models/pose_landmarker_lite.task"
    assert default_dataset_root() == tmp_path / "datasets"


def test_frozen_model_falls_back_to_portable_models(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "missing_bundle"), raising=False)
    executable = tmp_path / "portable" / "EMGController.exe"
    monkeypatch.setattr(sys, "executable", str(executable))
    model = executable.parent / "models" / "pose_landmarker_lite.task"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model fixture")
    assert resolve_model_path(tmp_path / "old_installation.task") == model
