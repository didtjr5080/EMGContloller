"""QApplication bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from emg_collector.ui.main_window import MainWindow


def run(dataset_root: Path | None = None) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EMG Dataset Collector")
    window = MainWindow(dataset_root or Path.cwd() / "datasets")
    window.show()
    return app.exec()
