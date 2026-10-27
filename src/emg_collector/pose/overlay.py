"""Pose overlay for previews; original frames remain untouched."""

import math


CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
)


def draw_pose(frame, rows, arm, min_visibility=0.6):
    import cv2

    image = frame.copy()
    height, width = image.shape[:2]
    points = {}
    for row in rows:
        x, y = row["x"], row["y"]
        if (not math.isfinite(x) or not math.isfinite(y)
                or not 0 <= x <= 1 or not 0 <= y <= 1
                or row.get("visibility", 0) < min_visibility
                or (row.get("presence") is not None and row["presence"] < min_visibility)):
            continue
        points[row["landmark_id"]] = (
            min(width - 1, round(x * width)), min(height - 1, round(y * height))
        )
    selected = (11, 13, 15, 23) if arm == "left" else (12, 14, 16, 24)
    highlighted = {frozenset(pair) for pair in zip(selected, selected[1:3])}
    highlighted.add(frozenset((selected[0], selected[3])))
    thickness = max(2, round(min(width, height) / 240))
    for a, b in CONNECTIONS:
        if a in points and b in points:
            color = (0, 220, 255) if frozenset((a, b)) in highlighted else (70, 220, 70)
            cv2.line(image, points[a], points[b], (20, 20, 20), thickness + 2, cv2.LINE_AA)
            cv2.line(image, points[a], points[b], color, thickness, cv2.LINE_AA)
    for index, point in points.items():
        color = (0, 220, 255) if index in selected else (70, 220, 70)
        cv2.circle(image, point, thickness + 3, (20, 20, 20), -1, cv2.LINE_AA)
        cv2.circle(image, point, thickness + 1, color, -1, cv2.LINE_AA)
    return image
