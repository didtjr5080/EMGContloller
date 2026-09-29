"""Dataset-root layout, participant/session registries, and crash recovery.

Directory layout (see work order section 7.1)::

    dataset_root/
    ├─ dataset_manifest.json
    ├─ participants_private.csv
    ├─ participants_public.csv
    ├─ sessions.csv
    └─ sessions/<SESSION_ID>/{samples.csv, events.csv, metadata.json, quality.json}
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from emg_collector.config import (
    APP_VERSION,
    PARTICIPANTS_PRIVATE_HEADER,
    PARTICIPANTS_PUBLIC_HEADER,
    SCHEMA_VERSION,
    SESSION_STATUS_RECOVERED,
    SESSIONS_CSV_HEADER,
)
from emg_collector.models import ParticipantPrivate, ParticipantPublic
from emg_collector.storage.session_writer import (
    EVENTS_FINAL_NAME,
    EVENTS_PART_NAME,
    SAMPLES_FINAL_NAME,
    SAMPLES_PART_NAME,
    SessionWriter,
)

MANIFEST_NAME = "dataset_manifest.json"
PARTICIPANTS_PRIVATE_NAME = "participants_private.csv"
PARTICIPANTS_PUBLIC_NAME = "participants_public.csv"
SESSIONS_NAME = "sessions.csv"
SESSIONS_DIR_NAME = "sessions"


class DatasetStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / SESSIONS_DIR_NAME).mkdir(exist_ok=True)

        self._manifest_path = self.root / MANIFEST_NAME
        self._private_path = self.root / PARTICIPANTS_PRIVATE_NAME
        self._public_path = self.root / PARTICIPANTS_PUBLIC_NAME
        self._sessions_path = self.root / SESSIONS_NAME

        self._ensure_csv(self._private_path, PARTICIPANTS_PRIVATE_HEADER)
        self._ensure_csv(self._public_path, PARTICIPANTS_PUBLIC_HEADER)
        self._ensure_csv(self._sessions_path, SESSIONS_CSV_HEADER)
        self._ensure_manifest()

    @staticmethod
    def _ensure_csv(path: Path, header: list[str]) -> None:
        if not path.exists():
            with open(path, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(header)

    def _ensure_manifest(self) -> None:
        if self._manifest_path.exists():
            return
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "files": {
                "participants_private.csv": PARTICIPANTS_PRIVATE_HEADER,
                "participants_public.csv": PARTICIPANTS_PUBLIC_HEADER,
                "sessions.csv": SESSIONS_CSV_HEADER,
            },
        }
        self._manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def sessions_dir(self) -> Path:
        return self.root / SESSIONS_DIR_NAME

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_dir() / session_id

    # -- participants --------------------------------------------------

    def register_participant(
        self, private: ParticipantPrivate, public: ParticipantPublic
    ) -> None:
        if private.participant_id != public.participant_id:
            raise ValueError("participant_id mismatch between private/public records")
        with open(self._private_path, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(
                [private.participant_id, private.name, private.created_at_utc]
            )
        with open(self._public_path, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(
                [
                    public.participant_id,
                    public.age,
                    public.sex.value,
                    public.height_cm,
                    public.weight_kg if public.weight_kg is not None else "",
                    public.dominant_arm.value,
                    public.exercise_sessions_per_week,
                    (
                        public.exercise_minutes_per_week
                        if public.exercise_minutes_per_week is not None
                        else ""
                    ),
                    public.days_since_last_exercise,
                    public.participant_notes,
                ]
            )

    # -- sessions --------------------------------------------------------

    def create_session_writer(self, session_id: str) -> SessionWriter:
        return SessionWriter(self.session_dir(session_id))

    def append_session_row(self, row: dict) -> None:
        with open(self._sessions_path, "a", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow([row.get(col, "") for col in SESSIONS_CSV_HEADER])

    def write_session_metadata(self, session_id: str, metadata: dict) -> None:
        path = self.session_dir(session_id) / "metadata.json"
        path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    def write_session_quality(self, session_id: str, quality: dict) -> None:
        path = self.session_dir(session_id) / "quality.json"
        path.write_text(json.dumps(quality, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- crash recovery ---------------------------------------------------

    def find_incomplete_sessions(self) -> list[str]:
        """Session ids with a leftover ``samples.csv.part`` (crashed mid-write)."""
        incomplete = []
        sessions_dir = self.sessions_dir()
        if not sessions_dir.exists():
            return incomplete
        for entry in sorted(sessions_dir.iterdir()):
            if entry.is_dir() and (entry / SAMPLES_PART_NAME).exists():
                incomplete.append(entry.name)
        return incomplete

    def recover_session(self, session_id: str) -> tuple[Path, Path]:
        """Finalize a crashed session's .part files in place, without deleting data."""
        session_dir = self.session_dir(session_id)
        samples_part = session_dir / SAMPLES_PART_NAME
        events_part = session_dir / EVENTS_PART_NAME
        if not samples_part.exists():
            raise FileNotFoundError(f"no recoverable session at {session_dir}")

        import os

        with open(samples_part, "a", encoding="utf-8") as fh:
            fh.flush()
            os.fsync(fh.fileno())
        samples_final = session_dir / SAMPLES_FINAL_NAME
        os.replace(samples_part, samples_final)

        events_final = session_dir / EVENTS_FINAL_NAME
        if events_part.exists():
            with open(events_part, "a", encoding="utf-8") as fh:
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(events_part, events_final)

        return samples_final, events_final
