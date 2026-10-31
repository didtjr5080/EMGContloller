"""Workers own I/O; the Qt thread receives only bounded preview snapshots."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
import json
from pathlib import Path
from queue import Queue, Empty
from threading import Event, Lock, Thread
import time
import uuid
from pydantic import PositiveInt, TypeAdapter

from emg_collector.acquisition.camera_worker import capture_loop
from emg_collector.acquisition.time_unwrapper import TimeUnwrapper
from emg_collector.acquisition.serial_worker import SerialPortLineSource
from emg_collector.acquisition.watchdog import StreamWatchdog, WatchdogPolicy
from emg_collector.labeling.repetitions import RepetitionDetector
from emg_collector.multimodal.schema import ProfileParser, SetRecord, channels
from emg_collector.pose.metrics import metrics, BodyStabilityTracker
from emg_collector.pose.pose_worker import MediaPipePose
from emg_collector.runtime_paths import default_model_path
from emg_collector.storage.multimodal_writer import MultimodalWriter
from emg_collector.sync.clock_alignment import fit_clock
from emg_collector.quality.window import QualityPolicy


class CollectionController:
    def __init__(
        self,
        root,
        participant,
        consent,
        visit,
        protocol,
        *,
        arm="right",
        load_kg=0,
        dumbbell_count=1,
        set_number=1,
        rest_before_s=None,
        target_repetitions=None,
        port="",
        baud=460800,
        camera_index=0,
        model_path=None,
        synthetic=False,
        placement="",
        skin_prepared=False,
        clothing_confirmed=False,
        mock_occlusion=False,
        mock_receive_batch_delay_ms=0,
        clock_ns=None,
        watchdog_policy=None,
    ):
        if not consent.research or not consent.pose_coordinates:
            raise ValueError("research and pose-coordinate consent are required")
        if not placement:
            raise ValueError("전극 위치를 입력하세요.")
        self.root = Path(root)
        # Python 3.11 on Windows uses a coarse clock for monotonic_ns;
        # QPC keeps rapid camera reads distinct. All capture/inference/serial
        # timestamps use this same high-resolution time domain.
        self.clock_ns = clock_ns or (lambda: time.perf_counter_ns())
        self.watchdog_policy = watchdog_policy or WatchdogPolicy()
        self.last_valid_sample_monotonic_ns = None
        self.last_frame_ns = None
        self.last_pose_ns = None
        self.motion_end_ns = None
        self.faults = []
        self.state_lock = Lock()
        self.participant = participant
        self.consent = consent
        self.visit = visit
        self.protocol = protocol
        self.arm = arm
        self.load = load_kg
        self.dumbbell_count = TypeAdapter(PositiveInt).validate_python(
            dumbbell_count, strict=True
        )
        self.set_number = set_number
        self.rest = rest_before_s
        self.target_repetitions = target_repetitions
        self.port = port
        self.baud = baud
        self.camera_index = camera_index
        self.model_path = model_path if model_path is not None else default_model_path()
        self.synthetic = synthetic
        self.mock_occlusion = mock_occlusion
        if not 0 <= mock_receive_batch_delay_ms <= 1000:
            raise ValueError("mock batch delay must be within 0..1000 ms")
        self.mock_receive_batch_delay_ms = mock_receive_batch_delay_ms
        self.placement = placement
        self.skin_prepared = skin_prepared
        self.clothing_confirmed = clothing_confirmed
        self.stop_event = Event()
        self.pose_queue = Queue(maxsize=2)
        self.snapshot_lock = Lock()
        self.snapshot = {}
        self.emg_preview = deque(maxlen=2500)
        self.errors = []
        self.sample_count = 0
        self.frame_count = 0
        self.inference_skipped = 0
        self.tracking_loss = 0
        self.clipping_count = 0
        self.malformed_count = 0
        self.regressions = 0
        self.estimated_missing = 0
        self.epoch_observations = {}
        self.clock_mappings = {}
        self.frame_times = deque(maxlen=10000)
        self.emg_times = deque(maxlen=10000)
        self.termination = "other"
        self.failure_attempt_id = None
        self.failure_attempt_observed = None
        self.started = Event()
        self.done = Event()
        self.phase = "initializing"
        self.thread = None

    def start(self):
        self.thread = Thread(
            target=self._run, name="collection-coordinator", daemon=True
        )
        self.thread.start()

    def stop(self, reason="other", failure_attempt_id=None):
        with self.state_lock:
            self.termination = "equipment_failure" if self.errors else reason
            if self.motion_end_ns is None:
                self.motion_end_ns = self.clock_ns()
        self.failure_attempt_observed = (
            False
            if failure_attempt_id == "__none__"
            else (True if failure_attempt_id else None)
        )
        self.failure_attempt_id = (
            None if failure_attempt_id == "__none__" else failure_attempt_id
        )
        self.stop_event.set()

    def fail(self, stream, exc, code=None):
        now = self.clock_ns()
        code = code or f"{stream}_failure"
        with self.state_lock:
            self.errors.append(f"{code}: {type(exc).__name__}: {exc}")
            self.termination = "equipment_failure"
            if self.motion_end_ns is None:
                self.motion_end_ns = now
            fault = {
                "code": code,
                "detected_host_ns": now,
                "last_valid_sample_host_ns": self.last_valid_sample_monotonic_ns,
            }
            self.faults.append(fault)
        if hasattr(self, "writer") and not getattr(self.writer, "closed", False):
            try:
                self.writer.submit(
                    "events.csv",
                    {
                        "host_ns": now,
                        "sample_index": (
                            self.sample_count - 1 if self.sample_count else None
                        ),
                        "event_type": code,
                        "detail": json.dumps(fault),
                    },
                )
            except (OSError, RuntimeError):
                pass
        self.stop_event.set()

    def preview(self):
        with self.snapshot_lock:
            data = self.snapshot.copy()
            data["emg_samples"] = list(self.emg_preview)
            self.emg_preview.clear()
            return data

    def _run(self):
        pose = None
        try:
            self.start_ns = self.clock_ns()
            self.session_id = (
                "M_"
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                + "_"
                + uuid.uuid4().hex[:8]
            )
            self.set_id = self.session_id + "-SET1"
            self.detector = RepetitionDetector(self.protocol, self.set_id)
            channel_map = channels("biceps_triceps_v3", self.arm)
            for channel in channel_map:
                channel.electrode_placement = self.placement
                channel.skin_prepared = self.skin_prepared
            model_hash = None
            if not self.synthetic:
                # Preflight inference API/model before creating a recording directory.
                expected = (
                    "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"
                )
                pose = MediaPipePose(self.model_path, expected)
                model_hash = pose.sha256
                if not self.port:
                    raise ValueError("serial port required for real acquisition")
            metadata = {
                "schema_version": "3.0.0",
                "profile": "biceps_triceps_v3",
                "labeling": {
                    "source": "mediapipe_pose",
                    "sample_labels_file": "labeled_samples.csv",
                    "alignment": "measurement_estimate_or_host_receive_vs_capture_previous_neighbor_software_only",
                    "mode": "retrospective_provisional; review required for confirmed repetitions",
                },
                "participant_id": self.participant.participant_id,
                "session_id": self.session_id,
                "visit_id": self.visit.visit_id,
                "visit": self.visit.model_dump(mode="json"),
                "participant": {
                    k: v
                    for k, v in self.participant.model_dump(mode="json").items()
                    if k != "participant_notes"
                },
                "start_host_ns": self.start_ns,
                "start_time_utc": datetime.now(timezone.utc).isoformat(),
                "synthetic": self.synthetic,
                "watchdog_policy": self.watchdog_policy.model_dump(),
                "alignment_version": "alignment-1",
                "quality_policy": QualityPolicy().model_dump(),
                "equipment": {
                    "dumbbell_count": self.dumbbell_count,
                    "load_kg_per_dumbbell": self.load,
                },
                "mock_receive_batch_delay_ms": (
                    self.mock_receive_batch_delay_ms if self.synthetic else None
                ),
                "consent": self.consent.model_dump(),
                "channels": [c.model_dump() for c in channel_map],
                "protocol": self.protocol.model_dump(),
                "clothing_confirmed": self.clothing_confirmed,
                "preparation_confirmation": (
                    "confirmed"
                    if self.skin_prepared and self.clothing_confirmed
                    else "not_confirmed"
                ),
                "camera": {
                    "index": self.camera_index,
                    "coordinates": "normalized_unmirrored",
                    "timestamp_source": "opencv_read_completion",
                    "view": "single_arm_side_view",
                },
                "pose": {
                    "api": "Tasks PoseLandmarker VIDEO",
                    "mediapipe_version": "0.10.21",
                    "model_sha256": model_hash,
                    "metrics_version": "aspect_corrected_2d_v1",
                    "world_coordinates": "MediaPipe inferred; not clinical 3D",
                    "body_stability": {"method": "fixed_camera_2d_first_visible_torso", "angle_threshold_deg": 5,
                                       "pelvis_displacement_torso_ratio": 0.05, "status": "pilot_unvalidated"},
                },
                "emg": {
                    "baud": self.baud,
                    "expected_rate_hz": 500,
                    "unit": "ADC count",
                    "spectral_validity": "unverified",
                },
                "session_relation": "standalone recording; visit and set IDs are internal file references",
            }
            self.writer = MultimodalWriter(
                self.root / "sessions" / self.session_id,
                metadata,
                self.consent.video_storage,
                shutdown_timeout_s=self.watchdog_policy.shutdown_timeout_s,
            )
            self.writer.submit(
                "events.csv",
                {
                    "host_ns": self.start_ns,
                    "sample_index": None,
                    "event_type": "software_sync_start",
                    "detail": "not a shared hardware trigger; physical error unmeasured",
                },
            )
            workers = [
                Thread(target=self._serial, name="emg-acquisition", daemon=True),
                Thread(
                    target=capture_loop,
                    args=(self,),
                    name="camera-capture",
                    daemon=True,
                ),
                Thread(
                    target=self._pose, args=(pose,), name="pose-inference", daemon=True
                ),
            ]
            self._workers = workers
            for worker in workers:
                worker.start()
            self.phase = "collecting"
            self.started.set()
            while not self.stop_event.wait(0.05):
                for stream, last in (
                    ("serial", self.last_valid_sample_monotonic_ns),
                    ("camera", self.last_frame_ns),
                    ("pose", self.last_pose_ns),
                ):
                    watchdog = StreamWatchdog(self.start_ns, self.watchdog_policy)
                    watchdog.last_valid_ns = last
                    state = watchdog.check(self.clock_ns())
                    if state:
                        self.fail(
                            stream,
                            TimeoutError(f"no valid {stream} data"),
                            f"{stream}_{state}",
                        )
                        break
            self.phase = "finalizing"
            shutdown_deadline = (
                time.monotonic() + self.watchdog_policy.shutdown_timeout_s
            )
            for worker in workers:
                worker.join(timeout=max(0, shutdown_deadline - time.monotonic()))
                if worker.is_alive():
                    self.fail(
                        worker.name,
                        TimeoutError(
                            "worker failed to stop; original streams retained"
                        ),
                        "worker_shutdown_timeout",
                    )
            if any(worker.is_alive() for worker in workers):
                self.writer.close_incomplete()
                from emg_collector.storage.multimodal_writer import atomic_json

                atomic_json(
                    self.writer.root / "completion_manifest.json",
                    {
                        "status": "incomplete",
                        "errors": self.errors.copy(),
                        "faults": self.faults.copy(),
                    },
                )
                return
            end = (
                self.motion_end_ns
                if self.motion_end_ns is not None
                else self.clock_ns()
            )
            partial = self.detector.finish(end)
            if partial:
                self.writer.submit("repetitions.csv", partial.model_dump(mode="json"))
            record = SetRecord(
                set_id=self.set_id,
                arm=self.arm,
                set_number=self.set_number,
                load_kg=self.load,
                dumbbell_count=self.dumbbell_count,
                rest_before_s=self.rest,
                target_repetitions=self.target_repetitions,
                start_ns=self.start_ns,
                end_ns=end,
                termination_reason=self.termination,
                failure_attempt_id=self.failure_attempt_id,
                failure_attempt_observed=self.failure_attempt_observed,
                observed_valid_count=sum(
                    a.validity == "valid" for a in self.detector.attempts
                ),
            )
            self.writer.submit("sets.csv", record.model_dump(mode="json"))
            self.writer.submit(
                "events.csv",
                {
                    "host_ns": end,
                    "sample_index": (
                        self.sample_count - 1 if self.sample_count else None
                    ),
                    "event_type": "software_sync_end",
                    "detail": "physical sync error remains unmeasured",
                },
            )
            sync = {
                "alignment_version": "alignment-1",
                "method": "software_only",
                "motion_end_host_ns": end,
                "acquisition_end_host_ns": self.clock_ns(),
                "stop_grace_ns": 0,
                "physical_sync_error_ms": None,
                "events": ["software_sync_start", "software_sync_end"],
                "posthoc_receive_fits": {
                    str(epoch): fit_clock(obs)
                    for epoch, obs in self.epoch_observations.items()
                },
                "epochs": self.clock_mappings,
            }

            def rate(times):
                return (
                    (len(times) - 1) * 1e9 / (times[-1] - times[0])
                    if len(times) > 1 and times[-1] > times[0]
                    else None
                )

            quality = {
                "synthetic": self.synthetic,
                "valid_samples": self.sample_count,
                "frame_count": self.frame_count,
                "actual_sample_rate_hz": rate(self.emg_times),
                "actual_fps": rate(self.frame_times),
                "rate_scope": "last 10000 observations",
                "inference_skipped": self.inference_skipped,
                "tracking_loss_frames": self.tracking_loss,
                "clipping_values": self.clipping_count,
                "malformed_rows": self.malformed_count,
                "timestamp_regressions": self.regressions,
                "estimated_missing_samples": self.estimated_missing,
                "writer_queue_overflow": self.writer.overflow_count,
                "physical_sync_error_ms": None,
                "original_camera_drop_count": None,
                "sync_validated": False,
                "errors": self.errors.copy(),
                "faults": self.faults.copy(),
            }
            if not self.sample_count or not self.frame_count:
                self.errors.append("required EMG/camera stream is empty")
            self.manifest = self.writer.finalize(sync, quality, self.errors)
            # Existing root registries stay v2; session metadata selects its reader.
            from emg_collector.storage.dataset_store import DatasetStore

            store = DatasetStore(self.root)
            store.append_session_row(
                {
                    "session_id": self.session_id,
                    "participant_id": self.participant.participant_id,
                    "start_time_utc": metadata["start_time_utc"],
                    "arm": self.arm,
                    "load_kg": self.load,
                    "set_number": self.set_number,
                    "status": self.manifest["status"],
                    "valid_samples": self.sample_count,
                    "session_path": str(self.writer.root),
                }
            )
        except Exception as exc:
            self.fail("coordinator", exc)
            if hasattr(self, "writer"):
                self.writer.close_incomplete()
        finally:
            if pose and not any(w.is_alive() for w in getattr(self, "_workers", [])):
                pose.close()
            self.phase = "finished"
            self.done.set()

    def _serial(self):
        conn = None
        try:
            if not self.synthetic:
                from emg_collector.acquisition.esp32_serial import open_esp32_stream

                conn = open_esp32_stream(self.port, self.baud)
                source = SerialPortLineSource(conn)
            parser = ProfileParser("biceps_triceps_v3", self.arm)
            unwrapper = TimeUnwrapper()
            epoch = 0
            last_raw = None
            first_header = True
            last_unwrapped = None
            watchdog = StreamWatchdog(self.clock_ns(), self.watchdog_policy)
            next_tick = time.monotonic()
            synthetic_origin = self.clock_ns() + 2_000_000
            if self.synthetic:
                self.clock_mappings["0"] = [
                    {
                        "mapping_version": "alignment-1:synthetic-e0",
                        "epoch_id": 0,
                        "method": "synthetic_reference",
                        "status": "validated",
                        "offset_ns": synthetic_origin,
                        "drift_ppm": 0,
                        "uncertainty_ns": 0,
                        "available_host_ns": self.clock_ns(),
                        "fit_scope": "causal",
                        "valid_from_device_us": 0,
                        "valid_to_device_us": 2**63 - 1,
                        "latency_bias_ns": 0,
                    }
                ]
            mock_time = 0
            while not self.stop_event.is_set():
                state = watchdog.check(self.clock_ns())
                if state:
                    self.fail(
                        "serial",
                        TimeoutError("valid EMG sample deadline exceeded"),
                        f"serial_{state}",
                    )
                    break
                if self.synthetic:
                    if not parser.header_seen:
                        line = parser.header
                    else:
                        value = int(2000 + 200 * math.sin(mock_time / 100_000))
                        line = f"{mock_time%2**32},500,{value},400,{4095-value}"
                        mock_time += 2000
                        next_tick += 0.002
                        self.stop_event.wait(max(0, next_tick - time.monotonic()))
                else:
                    line = source.next_line()
                if (
                    self.synthetic
                    and self.mock_receive_batch_delay_ms
                    and mock_time
                    and mock_time % 100_000 == 0
                ):
                    self.stop_event.wait(self.mock_receive_batch_delay_ms / 1000)
                received = self.clock_ns()
                state = watchdog.check(received)
                if state:
                    self.fail(
                        "serial",
                        TimeoutError("valid EMG sample deadline exceeded"),
                        f"serial_{state}",
                    )
                    break
                if line.strip().startswith("time_us,"):
                    parser.parse(line, received)
                    if not first_header:
                        epoch += 1
                        unwrapper = TimeUnwrapper()
                        last_raw = None
                        last_unwrapped = None
                    first_header = False
                    continue
                # Old rows and boot noise may precede the new header after
                # reopening a port. Wait for it within the watchdog deadline.
                if not parser.header_seen:
                    continue
                try:
                    sample = parser.parse(line, received)
                except ValueError as exc:
                    if "header" in str(exc):
                        raise
                    self.malformed_count += 1
                    continue
                if sample is None:
                    continue
                result = unwrapper.unwrap(sample.device_time_us)
                # A non-rollover timer reset > 1 s needs a new clock epoch even early in a visit.
                reset = result.reboot_detected or (
                    last_raw is not None
                    and last_raw - sample.device_time_us > 1_000_000
                    and not result.wrapped
                )
                if reset:
                    epoch += 1
                    unwrapper = TimeUnwrapper()
                    result = unwrapper.unwrap(sample.device_time_us)
                    last_unwrapped = None
                    self.writer.submit(
                        "events.csv",
                        {
                            "host_ns": received,
                            "sample_index": self.sample_count,
                            "event_type": "device_epoch_reset",
                            "detail": "timer reset/reboot inferred; inspect hardware logs",
                        },
                    )
                if result.regression:
                    self.regressions += 1
                if (
                    last_unwrapped is not None
                    and result.value_us - last_unwrapped > 3000
                ):
                    self.estimated_missing += max(
                        0, round((result.value_us - last_unwrapped) / 2000) - 1
                    )
                sample.sample_index = self.sample_count
                sample.epoch_id = epoch
                sample.unwrapped_time_us = result.value_us
                self.writer.submit("samples.csv", sample.model_dump())
                self.sample_count += 1
                watchdog.mark_valid(received)
                self.last_valid_sample_monotonic_ns = received
                self.emg_times.append(received)
                values = [sample.s1_env, sample.s1_raw, sample.s2_env, sample.s2_raw]
                self.clipping_count += sum(value in (0, 4095) for value in values)
                if self.sample_count % 50 == 1:
                    self.epoch_observations.setdefault(epoch, []).append(
                        (result.value_us, received)
                    )
                    obs = self.epoch_observations[epoch]
                    if (
                        not self.synthetic
                        and (len(obs) == 3 or self.sample_count % 500 == 1)
                        and len(obs) >= 3
                    ):
                        mapping = fit_clock(obs[-120:])
                        mapping.update(
                            epoch_id=epoch,
                            fit_scope="causal",
                            valid_to_device_us=result.value_us + 5_000_000,
                        )
                        self.clock_mappings.setdefault(str(epoch), []).append(mapping)
                with self.snapshot_lock:
                    self.snapshot.update(sample=sample.model_dump())
                    self.emg_preview.append(sample.model_dump())
                last_raw = sample.device_time_us
                last_unwrapped = result.value_us
        except Exception as exc:
            self.fail("serial", exc)
        finally:
            if conn:
                conn.close()

    def _pose(self, pose):
        baseline = None
        stability = BodyStabilityTracker(self.protocol.min_visibility)
        try:
            while not self.stop_event.is_set() or not self.pose_queue.empty():
                try:
                    frame_id, captured, frame, synthetic_landmarks = (
                        self.pose_queue.get(timeout=0.1)
                    )
                except Empty:
                    continue
                rows = (
                    synthetic_landmarks
                    if self.synthetic
                    else pose.infer(frame, captured)
                )
                self.last_pose_ns = self.clock_ns()
                if self.synthetic:
                    for row in rows:
                        row["capture_host_ns"] = captured
                        row["infer_host_ns"] = time.perf_counter_ns()
                for row in rows:
                    self.writer.submit(
                        "pose_landmarks.csv", {"frame_id": frame_id, **row}
                    )
                derived = metrics(
                    {r["landmark_id"]: r for r in rows},
                    frame.shape[1],
                    frame.shape[0],
                    self.arm,
                    self.protocol.min_visibility,
                    baseline,
                )
                derived.update(stability.update({r["landmark_id"]: r for r in rows}, frame.shape[1], frame.shape[0]))
                if baseline is None and derived["quality_mask"] == "ok":
                    baseline = derived["upperarm_orientation_deg"]
                derived.pop("upperarm_orientation_deg", None)
                self.writer.submit(
                    "pose_metrics.csv",
                    {
                        "frame_id": frame_id,
                        "capture_host_ns": captured,
                        "infer_host_ns": time.perf_counter_ns(),
                        "arm": self.arm,
                        **derived,
                    },
                )
                valid = derived["quality_mask"] == "ok"
                if not valid:
                    self.tracking_loss += 1
                if self.motion_end_ns is not None and captured > self.motion_end_ns:
                    continue
                attempt = self.detector.update(
                    captured,
                    derived["elbow_angle_deg"],
                    derived["trunk_tilt_deg"],
                    derived["upperarm_delta_deg"],
                    valid,
                )
                if attempt:
                    self.writer.submit(
                        "repetitions.csv", attempt.model_dump(mode="json")
                    )
                    self.writer.submit(
                        "annotations.jsonl",
                        {
                            "revision": str(uuid.uuid4()),
                            "previous_revision": None,
                            "reviewer_id": "automatic",
                            "created_at_ns": time.time_ns(),
                            "reason": "provisional protocol state machine",
                            "attempt": attempt.model_dump(mode="json"),
                        },
                    )
                with self.snapshot_lock:
                    self.snapshot.update(
                        frame=frame.copy(),
                        landmarks=[row.copy() for row in rows],
                        metrics=derived,
                        phase=self.detector.phase,
                        attempts=[
                            a.model_dump(mode="json") for a in self.detector.attempts
                        ],
                    )
        except Exception as exc:
            self.fail("pose", exc)
