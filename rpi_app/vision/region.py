"""固定左右楼道区域划分。"""

from __future__ import annotations

from typing import Mapping


def count_stair_regions(
    detections: list[Mapping[str, int | float | str]], frame_width: int
) -> tuple[int, int]:
    """统计固定左右通道的区域占用人数。

    左侧预设为下行通道、右侧预设为上行通道；本函数仅按检测框中心点
    统计固定空间区域，不根据单帧结果推断人员的实际运动方向。
    """
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
