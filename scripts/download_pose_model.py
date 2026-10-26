"""Download the versioned official MediaPipe Pose Lite task; print its hash."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("models/pose_landmarker_lite.task")
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(URL, timeout=60) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        args.output.write_bytes(data)
        args.output.with_suffix(".json").write_text(
            json.dumps(
                {
                    "url": URL,
                    "sha256": digest,
                    "api": "MediaPipe Tasks PoseLandmarker VIDEO",
                    "mediapipe": "0.10.21",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"{args.output}: sha256={digest}")
    except OSError as exc:
        parser.exit(
            1, f"MediaPipe download failed: {exc}; retry or provide --output PATH\n"
        )


if __name__ == "__main__":
    main()
