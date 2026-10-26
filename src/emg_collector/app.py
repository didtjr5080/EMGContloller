"""QApplication bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from emg_collector.ui.main_window import MainWindow
from emg_collector.ui.multimodal_panel import MultimodalDialog
from emg_collector.storage.dataset_store import DatasetStore
from emg_collector.runtime_paths import default_dataset_root


def create_main_window(dataset_root: Path, *, legacy_v2: bool = False):
    if legacy_v2:
        return MainWindow(dataset_root)
    return MultimodalDialog(DatasetStore(dataset_root))


def run(dataset_root: Path | None = None, *, legacy_v2: bool = False) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EMG Dataset Collector")
    window = create_main_window(
        dataset_root or default_dataset_root(), legacy_v2=legacy_v2
    )
    window.show()
    return app.exec()
