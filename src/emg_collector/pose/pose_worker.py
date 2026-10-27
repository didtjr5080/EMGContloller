from pathlib import Path
import hashlib
import time


class MediaPipePose:
    """Tasks VIDEO API. Construct and call only from the inference worker."""

    def __init__(self, model_path, expected_sha256=None):
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision

        self.mp = mp
        path = Path(model_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"MediaPipe model missing: {path}; run python scripts/download_pose_model.py"
            )
        model_bytes = path.read_bytes()
        self.sha256 = hashlib.sha256(model_bytes).hexdigest()
        if expected_sha256 and self.sha256 != expected_sha256:
            raise ValueError("MediaPipe model SHA-256 mismatch")
        self.model = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                # The native loader cannot reliably open Korean Windows paths.
                base_options=python.BaseOptions(model_asset_buffer=model_bytes),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
            )
        )
        self.last_ms = -1

    def infer(self, frame, capture_ns):
        import cv2

        timestamp = max(self.last_ms + 1, capture_ns // 1_000_000)
        self.last_ms = timestamp
        result = self.model.detect_for_video(
            self.mp.Image(
                image_format=self.mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            ),
            timestamp,
        )
        finished = time.monotonic_ns()
        rows = []
        if result.pose_landmarks:
            world = (
                result.pose_world_landmarks[0] if result.pose_world_landmarks else []
            )
            for i, landmark in enumerate(result.pose_landmarks[0]):
                point = world[i] if world else None
                rows.append(
                    {
                        "landmark_id": i,
                        "capture_host_ns": capture_ns,
                        "infer_host_ns": finished,
                        "x": landmark.x,
                        "y": landmark.y,
                        "z": landmark.z,
                        "world_x": point.x if point else None,
                        "world_y": point.y if point else None,
                        "world_z": point.z if point else None,
                        "visibility": landmark.visibility,
                        "presence": landmark.presence,
                        "validity": "detected",
                    }
                )
        return rows

    def close(self):
        self.model.close()
