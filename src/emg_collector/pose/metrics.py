import math


def angle(a, b, c):
    u = (a[0] - b[0], a[1] - b[1])
    v = (c[0] - b[0], c[1] - b[1])
    norm = math.hypot(*u) * math.hypot(*v)
    if norm == 0:
        return None
    return math.degrees(math.acos(max(-1, min(1, (u[0] * v[0] + u[1] * v[1]) / norm))))


def metrics(landmarks, width, height, arm, min_visibility=0.6, baseline=None):
    ids = (11, 13, 15, 23) if arm == "left" else (12, 14, 16, 24)
    selected = [landmarks.get(i) for i in ids]
    if any(
        p is None
        or p.get("visibility", 0) < min_visibility
        or (p.get("presence") is not None and p["presence"] < min_visibility)
        for p in selected
    ):
        return {
            "elbow_angle_deg": None,
            "trunk_tilt_deg": None,
            "upperarm_delta_deg": None,
            "quality_mask": "tracking_loss",
        }
    points = [(p["x"] * width, p["y"] * height) for p in selected]
    shoulder, elbow, wrist, hip = points
    elbow_angle = angle(shoulder, elbow, wrist)
    trunk = math.degrees(
        math.atan2(abs(shoulder[0] - hip[0]), abs(shoulder[1] - hip[1]))
    )
    upper = math.degrees(math.atan2(elbow[0] - shoulder[0], elbow[1] - shoulder[1]))
    delta = abs((upper - (upper if baseline is None else baseline) + 180) % 360 - 180)
    return {
        "elbow_angle_deg": elbow_angle,
        "trunk_tilt_deg": trunk,
        "upperarm_delta_deg": delta,
        "quality_mask": "ok" if elbow_angle is not None else "degenerate",
        "upperarm_orientation_deg": upper,
    }
