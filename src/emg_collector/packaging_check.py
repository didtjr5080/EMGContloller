"""Exercise packaged native libraries and both UI flows without physical devices."""

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory


def check_distribution(report_path):
    import cv2
    import mediapipe
    import numpy as np
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from emg_collector.models import ParticipantPublic
    from emg_collector.multimodal.controller import CollectionController
    from emg_collector.multimodal.schema import Consent, Visit
    from emg_collector.multimodal.validator import validate_session
    from emg_collector.pose.pose_worker import MediaPipePose
    from emg_collector.protocols import PilotProtocol
    from emg_collector.runtime_paths import default_model_path
    from emg_collector.ui.main_window import MainWindow
    from emg_collector.app import create_main_window
    from emg_collector.ui.multimodal_panel import MultimodalDialog
    from emg_collector.ui.multimodal_review import MultimodalReviewDialog
    from emg_collector.ui.common import TERMINATION_LABELS
    from emg_collector.multimodal.schema import Termination

    model = MediaPipePose(
        default_model_path(),
        "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    )
    try:
        assert (
            model.infer(np.zeros((480, 640, 3), dtype=np.uint8), time.monotonic_ns())
            == []
        )
    finally:
        model.close()
    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory(prefix="EMGController-check-") as folder:
        window = MainWindow(Path(folder))
        dialog = create_main_window(Path(folder))
        assert isinstance(dialog, MultimodalDialog)
        assert Path(dialog.model.text()).is_file()
        dialog.resize(800, 600)
        dialog.show()
        app.processEvents()
        assert dialog.width() <= 800 and dialog.height() <= 600
        assert all(
            dialog.reason.itemText(dialog.reason.findData(reason.value))
            == TERMINATION_LABELS[reason]
            for reason in Termination
        )
        dialog.hide()
        participant = ParticipantPublic(
            participant_id="P-BUILD01",
            age=25,
            height_cm=170,
            exercise_sessions_per_week=0,
            days_since_last_exercise=0,
        )
        window.store.register_participant(None, participant)
        from emg_collector.acquisition.watchdog import WatchdogPolicy

        controller = CollectionController(
            Path(folder),
            participant,
            Consent(
                research=True,
                pose_coordinates=True,
                video_storage=True,
                video_access=True,
            ),
            Visit(visit_id="V-BUILD"),
            PilotProtocol(),
            synthetic=True,
            placement="synthetic build check",
            skin_prepared=True,
            clothing_confirmed=True,
            # Packaging checks also run during native DLL scanning and disk contention.
            watchdog_policy=WatchdogPolicy(shutdown_timeout_s=20),
        )
        controller.start()
        assert controller.started.wait(10), controller.errors
        time.sleep(1)
        controller.stop("voluntary_stop")
        assert controller.done.wait(45), "collection failed to stop"
        assert not controller.errors, controller.errors
        errors = validate_session(controller.writer.root)
        assert not errors, errors
        import csv

        with (controller.writer.root / "labeled_samples.csv").open(
            newline="", encoding="utf-8"
        ) as fh:
            labeled_samples = list(csv.DictReader(fh))
        assert len(labeled_samples) == controller.sample_count
        assert all(row["label_source"] == "mediapipe_pose" for row in labeled_samples)
        assert any(row["pose_valid"] == "True" for row in labeled_samples)
        review = MultimodalReviewDialog(controller.writer.root)
        deadline = time.monotonic() + 10
        while review.data is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert review.data is not None, review.status.text()
        review.resize(800, 600)
        review.show()
        app.processEvents()
        assert review.width() <= 800 and review.height() <= 600
        assert all(
            review.reason.itemText(review.reason.findData(reason.value))
            == TERMINATION_LABELS[reason]
            for reason in Termination
        )
        review.close()
        dialog.close()
        window.show()
        QTimer.singleShot(200, app.quit)
        assert app.exec() == 0
        window.close()
        report = {
            "ok": True,
            "opencv": cv2.__version__,
            "mediapipe": mediapipe.__version__,
            "numpy": np.__version__,
            "model_sha256": model.sha256,
            "qt_main_window": True,
            "v3_dialog": True,
            "review_dialog": True,
            "synthetic_emg_samples": controller.sample_count,
            "synthetic_video_frames": controller.frame_count,
            "validator_errors": errors,
            "physical_devices_tested": False,
            "default_collection_mode": "biceps_triceps_mediapipe",
            "mediapipe_labeled_samples": len(labeled_samples),
            "compact_collection_and_review": True,
            "korean_termination_choices": True,
        }
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
