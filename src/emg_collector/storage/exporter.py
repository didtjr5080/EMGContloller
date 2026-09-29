"""De-identified dataset export: everything except participants_private.csv."""

from __future__ import annotations

import shutil
from pathlib import Path

from emg_collector.storage.dataset_store import (
    MANIFEST_NAME,
    PARTICIPANTS_PUBLIC_NAME,
    SESSIONS_DIR_NAME,
    SESSIONS_NAME,
)

EXCLUDED_FROM_EXPORT = {"participants_private.csv"}


def export_deidentified(dataset_root: Path, output_dir: Path) -> Path:
    dataset_root = Path(dataset_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name in (MANIFEST_NAME, PARTICIPANTS_PUBLIC_NAME, SESSIONS_NAME):
        src = dataset_root / name
        if src.exists():
            shutil.copy2(src, output_dir / name)

    src_sessions = dataset_root / SESSIONS_DIR_NAME
    dst_sessions = output_dir / SESSIONS_DIR_NAME
    if src_sessions.exists():
        shutil.copytree(src_sessions, dst_sessions, dirs_exist_ok=True)

    for excluded in EXCLUDED_FROM_EXPORT:
        stray = output_dir / excluded
        if stray.exists():
            stray.unlink()

    return output_dir
