import numpy as np

from emg_collector.pose.overlay import draw_pose


def landmark(index, x, y, visibility=1):
    return {"landmark_id": index, "x": x, "y": y,
            "visibility": visibility, "presence": 1}


def test_selected_arm_has_points_and_connected_lines_without_changing_original():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    rows = [landmark(12, .2, .2), landmark(14, .5, .5), landmark(16, .8, .2)]
    result = draw_pose(frame, rows, "right")
    assert not frame.any()
    assert tuple(result[20, 20]) == (0, 220, 255)
    assert tuple(result[50, 50]) == (0, 220, 255)
    assert result[35, 35].any()  # Shoulder-to-elbow segment.
    assert result[35, 65].any()  # Elbow-to-wrist segment.


def test_hidden_missing_and_out_of_frame_landmarks_are_not_drawn():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    rows = [landmark(12, .2, .2, .1), landmark(14, -1, .5),
            landmark(16, float("nan"), .2)]
    assert not draw_pose(frame, rows, "right").any()
    assert not draw_pose(frame, [], "left").any()


def test_selected_side_changes_highlight():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    rows = [landmark(11, .2, .2), landmark(12, .8, .2)]
    result = draw_pose(frame, rows, "left")
    assert tuple(result[20, 20]) == (0, 220, 255)
    assert tuple(result[20, 80]) == (70, 220, 70)
