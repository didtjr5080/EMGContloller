from copy import deepcopy
from emg_collector.pose.metrics import BodyStabilityTracker


def torso():
    return {i: {"x": x, "y": y, "visibility": 1, "presence": 1}
            for i, x, y in [(11, .35, .2), (12, .65, .2), (23, .4, .6), (24, .6, .6)]}


def test_body_stability_separates_leaning_from_pelvis_motion():
    tracker = BodyStabilityTracker()
    base = torso()
    assert tracker.update(base, 640, 480)["trunk_fixed"] is True
    lean = deepcopy(base)
    lean[11]["x"] += .1
    lean[12]["x"] += .1
    result = tracker.update(lean, 640, 480)
    assert result["trunk_fixed"] is False and result["pelvis_fixed"] is True
    translated = deepcopy(base)
    for p in translated.values():
        p["x"] += .1
    result = tracker.update(translated, 640, 480)
    assert result["trunk_fixed"] is True and result["pelvis_fixed"] is False


def test_body_stability_never_calls_hidden_or_out_of_frame_hips_fixed():
    tracker = BodyStabilityTracker()
    points = torso()
    tracker.update(points, 640, 480)
    points[23]["visibility"] = .1
    result = tracker.update(points, 640, 480)
    assert result["trunk_fixed"] is None and result["pelvis_fixed"] is None
    points = torso()
    points[24]["x"] = 1.1
    assert tracker.update(points, 640, 480)["pelvis_fixed"] is None
