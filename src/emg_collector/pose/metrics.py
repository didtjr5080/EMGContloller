import math


class BodyStabilityTracker:
    """Single-camera 2D movement estimates against the first visible torso.

    Keep the camera fixed. Missing hips/shoulders produce unknown, never fixed.
    Thresholds are pilot engineering settings, not clinical posture standards.
    """

    def __init__(self, min_visibility=0.6, angle_threshold_deg=5, displacement_threshold=0.05):
        self.min_visibility = min_visibility
        self.angle_threshold_deg = angle_threshold_deg
        self.displacement_threshold = displacement_threshold
        self.reference = None

    def update(self, landmarks, width, height):
        unknown = dict(trunk_fixed=None, pelvis_fixed=None, trunk_delta_deg=None,
                       pelvis_displacement_ratio=None, pelvis_tilt_delta_deg=None)
        rows = [landmarks.get(i) for i in (11, 12, 23, 24)]
        if any(p is None or p.get("visibility", 0) < self.min_visibility
               or (p.get("presence") is not None and p["presence"] < self.min_visibility)
               or not math.isfinite(p["x"]) or not math.isfinite(p["y"])
               or not 0 <= p["x"] <= 1 or not 0 <= p["y"] <= 1 for p in rows):
            return unknown
        ls, rs, lh, rh = [(p["x"] * width, p["y"] * height) for p in rows]
        shoulder = ((ls[0]+rs[0])/2, (ls[1]+rs[1])/2)
        hip = ((lh[0]+rh[0])/2, (lh[1]+rh[1])/2)
        length = math.dist(shoulder, hip)
        if length < 1 or math.dist(lh, rh) < 1:
            return unknown
        trunk_angle = math.degrees(math.atan2(shoulder[0]-hip[0], hip[1]-shoulder[1]))
        pelvis_angle = math.degrees(math.atan2(rh[1]-lh[1], rh[0]-lh[0]))
        if self.reference is None:
            self.reference = (hip, length, trunk_angle, pelvis_angle)
        ref_hip, ref_length, ref_trunk, ref_pelvis = self.reference
        delta = lambda a, b: abs((a-b+180)%360-180)
        trunk_delta = delta(trunk_angle, ref_trunk)
        pelvis_delta = delta(pelvis_angle, ref_pelvis)
        displacement = math.dist(hip, ref_hip) / ref_length
        return dict(trunk_fixed=trunk_delta <= self.angle_threshold_deg,
                    pelvis_fixed=displacement <= self.displacement_threshold and pelvis_delta <= self.angle_threshold_deg,
                    trunk_delta_deg=trunk_delta, pelvis_displacement_ratio=displacement,
                    pelvis_tilt_delta_deg=pelvis_delta)


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
