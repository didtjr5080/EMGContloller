"""Crash-recoverable CSV writer for one recording session.

Both ``samples.csv`` and ``events.csv`` are written to a ``.part`` file
while recording is in progress. On a clean finish, :meth:`SessionWriter.finalize`
flushes, ``fsync``s, and atomically renames each ``.part`` file to its final
name. If the process dies mid-recording, the ``.part`` files remain on disk
with whatever rows were flushed, and :mod:`emg_collector.storage.dataset_store`
detects and offers to recover them.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from emg_collector.config import EVENTS_CSV_HEADER, SAMPLES_CSV_HEADER
from emg_collector.models import EventRecord, SampleRecord

SAMPLES_PART_NAME = "samples.csv.part"
SAMPLES_FINAL_NAME = "samples.csv"
EVENTS_PART_NAME = "events.csv.part"
EVENTS_FINAL_NAME = "events.csv"


class SessionWriter:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._samples_part_path = self.session_dir / SAMPLES_PART_NAME
        self._events_part_path = self.session_dir / EVENTS_PART_NAME

        self._samples_file = open(
            self._samples_part_path, "w", newline="", encoding="utf-8"
        )
        self._samples_writer = csv.writer(self._samples_file)
        self._samples_writer.writerow(SAMPLES_CSV_HEADER)
        self._samples_file.flush()

        self._events_file = open(
            self._events_part_path, "w", newline="", encoding="utf-8"
        )
        self._events_writer = csv.writer(self._events_file)
        self._events_writer.writerow(EVENTS_CSV_HEADER)
        self._events_file.flush()

        self.sample_count = 0
        self.event_count = 0
        self._finalized = False

    def write_samples(self, samples: list[SampleRecord]) -> None:
        for sample in samples:
            self._samples_writer.writerow(
                [
                    sample.sample_index,
                    sample.device_time_us,
                    sample.device_time_us_unwrapped,
                    f"{sample.elapsed_s:.6f}",
                    f"{sample.host_elapsed_s:.6f}",
                    sample.env_adc,
                    sample.raw_adc,
                    sample.label,
                ]
            )
            self.sample_count += 1
        self._samples_file.flush()

    def write_event(self, event: EventRecord) -> None:
        self._events_writer.writerow(
            [
                event.event_index,
                event.sample_index,
                event.device_time_us_unwrapped,
                f"{event.elapsed_s:.6f}",
                event.event_type.value,
                event.label,
                event.note,
            ]
        )
        self.event_count += 1
        self._events_file.flush()

    def fsync(self) -> None:
        self._samples_file.flush()
        os.fsync(self._samples_file.fileno())
        self._events_file.flush()
        os.fsync(self._events_file.fileno())

    def finalize(self) -> tuple[Path, Path]:
        """Flush, fsync, close, and atomically rename .part -> final. Idempotent."""
        if self._finalized:
            return (
                self.session_dir / SAMPLES_FINAL_NAME,
                self.session_dir / EVENTS_FINAL_NAME,
            )

        self.fsync()
        self._samples_file.close()
        self._events_file.close()

        samples_final = self.session_dir / SAMPLES_FINAL_NAME
        events_final = self.session_dir / EVENTS_FINAL_NAME
        os.replace(self._samples_part_path, samples_final)
        os.replace(self._events_part_path, events_final)

        self._finalized = True
        return samples_final, events_final

    def close_without_finalize(self) -> None:
        """Close file handles but leave .part files in place. For crash simulation."""
        self._samples_file.close()
        self._events_file.close()
