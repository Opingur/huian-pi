"""K230 fixed left/right passage occupancy counting."""


def count_stair_regions(detections, frame_width):
    """Counts fixed passages only; does not infer real motion direction."""
    middle = frame_width // 2
    left_people = 0
    right_people = 0
    for detection in detections:
        center_x = (int(detection["x1"]) + int(detection["x2"])) // 2
        if center_x < middle:
            left_people += 1
        else:
            right_people += 1
    return left_people, right_people
