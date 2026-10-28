"""Camera read and video encoding stay off the Qt thread."""

import math
import time
from queue import Full


def synthetic_frame(frame_id, start_ns, arm="right", occlusion=False):
    import cv2
    import numpy as np

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    seconds = (time.monotonic_ns() - start_ns) / 1e9
    phase = seconds % 3 / 3
    angle_deg = 170 - 130 * (1 - abs(2 * phase - 1))
    # After fifteen full attempts, the sixteenth cannot reach the top.
    if seconds >= 45:
        angle_deg = 170 - 45 * (1 - abs(2 * phase - 1))
    shoulder = (320, 120)
    elbow = (320, 240)
    hip = (320, 390)
    radians = math.radians(270 + angle_deg)
    wrist = (elbow[0] + 120 * math.cos(radians), elbow[1] + 120 * math.sin(radians))
    visibility = 0.1 if occlusion and 8 < seconds < 9 else 0.99
    landmarks = []
    for i in range(33):
        point = {
            11: shoulder,
            12: shoulder,
            13: elbow,
            14: elbow,
            15: wrist,
            16: wrist,
            23: hip,
            24: hip,
        }.get(i, (320, 50))
        landmarks.append(
            {
                "landmark_id": i,
                "capture_host_ns": time.monotonic_ns(),
                "infer_host_ns": time.monotonic_ns(),
                "x": point[0] / 640,
                "y": point[1] / 480,
                "z": 0,
                "world_x": None,
                "world_y": None,
                "world_z": None,
                "visibility": visibility,
                "presence": visibility,
                "validity": "synthetic",
            }
        )
    for a, b in [(shoulder, elbow), (elbow, wrist), (shoulder, hip)]:
        cv2.line(frame, tuple(map(int, a)), tuple(map(int, b)), (80, 200, 80), 4)
    cv2.putText(
        frame,
        f"SYNTHETIC frame {frame_id}",
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        1,
    )
    return frame, landmarks


def capture_loop(controller):
    cap = None
    encoder = None
    video_part = None
    count = 0
    try:
        import cv2

        if not controller.synthetic:
            cap = cv2.VideoCapture(controller.camera_index)
            if not cap.isOpened():
                raise RuntimeError(f"camera {controller.camera_index} cannot open")
        if controller.consent.video_storage:
            folder = controller.writer.root / "video"
            folder.mkdir()
            video_part = folder / "segment_000.part.avi"
        while not controller.stop_event.is_set():
            if controller.synthetic:
                frame, landmarks = synthetic_frame(
                    count,
                    controller.start_ns,
                    controller.arm,
                    controller.mock_occlusion,
                )
            else:
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError("camera disconnected/read failed")
                landmarks = None
            captured = controller.clock_ns()
            controller.last_frame_ns = captured
            height, width = frame.shape[:2]
            if video_part and encoder is None:
                encoder = cv2.VideoWriter(
                    str(video_part),
                    cv2.VideoWriter_fourcc(*"MJPG"),
                    30,
                    (width, height),
                )
                if not encoder.isOpened():
                    raise RuntimeError("video encoder MJPG could not open")
            if encoder:
                encoder.write(frame)
            submitted = True
            try:
                controller.pose_queue.put_nowait((count, captured, frame, landmarks))
            except Full:
                controller.inference_skipped += 1
                submitted = False
            controller.writer.submit(
                "frame_timestamps.csv",
                {
                    "frame_id": count,
                    "capture_host_ns": captured,
                    "timestamp_source": (
                        "synthetic_host"
                        if controller.synthetic
                        else "opencv_read_completion"
                    ),
                    "segment": "segment_000.avi" if encoder else "",
                    "segment_frame": count if encoder else None,
                    "saved": bool(encoder),
                    "inference_submitted": submitted,
                },
            )
            controller.frame_count += 1
            controller.frame_times.append(captured)
            count += 1
            if controller.synthetic:
                controller.stop_event.wait(1 / 30)
    except Exception as exc:
        controller.fail("camera", exc)
    finally:
        if cap:
            cap.release()
        if encoder:
            encoder.release()
            # Final name appears only after encoder close; manifest verifies decode.
            final = video_part.with_name("segment_000.avi")
            if not final.exists():
                video_part.rename(final)
