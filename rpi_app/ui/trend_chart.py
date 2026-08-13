"""Evidence trend chart with an optional experiment-calibrated danger reference."""

from __future__ import annotations

import cv2


TIME_MIN_SECONDS = -15.0
TIME_MAX_SECONDS = 30.0


def plot_bounds(rect):
    x, y, width, height = rect
    return x + 42, x + width - 18, y + 28, y + height - 30


def map_time_to_x(rect, relative_seconds):
    left, right, _, _ = plot_bounds(rect)
    time_value = max(TIME_MIN_SECONDS, min(TIME_MAX_SECONDS, float(relative_seconds)))
    return int(left + (time_value - TIME_MIN_SECONDS) / (TIME_MAX_SECONDS - TIME_MIN_SECONDS) * (right - left))


def draw_trend_chart(image, rect, history, status, danger_people=None):
    """Draw evidence trends; danger reference appears only after experimental calibration."""
    x, y, width, height = rect
    samples = list(history or [])
    if not samples:
        return False
    now = float(samples[-1][0])
    real = [
        (float(item[0]) - now, int(item[1]) + int(item[2]))
        for item in samples
        if float(item[0]) >= now - 15.0
    ]
    future = [
        (10.0, status.get("predicted_people_10s")),
        (20.0, status.get("predicted_people_20s")),
        (30.0, status.get("predicted_people_30s")),
    ] if status.get("prediction_valid") else []
    calibrated = (
        bool(status.get("crowd_calibrated", False))
        and isinstance(danger_people, int)
        and not isinstance(danger_people, bool)
        and danger_people > 0
    )
    values = [people for _, people in real] + [float(people) for _, people in future if people is not None]
    if calibrated:
        values.append(float(danger_people))
    low, high = min(values) - 1, max(values) + 1
    left, right, top, bottom = plot_bounds(rect)

    def pixel(time_value, people):
        return map_time_to_x(rect, time_value), int(
            bottom - (float(people) - low) / (high - low) * (bottom - top)
        )

    cv2.rectangle(image, (x, y), (x + width, y + height), (250, 250, 250), -1)
    cv2.rectangle(image, (x, y), (x + width, y + height), (185, 185, 185), 1)
    for index in range(5):
        value = low + (high - low) * index / 4
        tick_y = pixel(0, value)[1]
        cv2.line(image, (left, tick_y), (right, tick_y), (232, 232, 232), 1)
        cv2.line(image, (left - 4, tick_y), (left, tick_y), (150, 150, 150), 1)
        cv2.putText(image, f"{value:.0f}", (x + 5, tick_y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (100, 100, 100), 1, cv2.LINE_AA)
    cv2.line(image, (left, bottom), (right, bottom), (170, 170, 170), 1)
    cv2.line(image, (left, top), (left, bottom), (170, 170, 170), 1)
    if calibrated:
        danger_y = pixel(0, danger_people)[1]
        cv2.line(image, (left, danger_y), (right, danger_y), (80, 80, 220), 1, cv2.LINE_AA)
    real_pixels = [pixel(time_value, people) for time_value, people in real]
    for first, second in zip(real_pixels, real_pixels[1:]):
        cv2.line(image, first, second, (150, 110, 55), 1)
    for point in real_pixels:
        cv2.circle(image, point, 3, (70, 50, 25), -1)
    now_pixel = pixel(0, real[-1][1])
    cv2.line(image, (now_pixel[0], top), (now_pixel[0], bottom), (100, 150, 80), 1)
    if status.get("prediction_valid"):
        slope, current = float(status.get("prediction_slope", 0.0)), real[-1][1]
        cv2.line(image, pixel(-15, current - slope * 15), now_pixel, (0, 130, 255), 1)
        previous = now_pixel
        for time_value, people in future:
            if people is None:
                continue
            target = pixel(time_value, people)
            cv2.line(image, previous, target, (0, 130, 255), 1, cv2.LINE_AA)
            cv2.circle(image, target, 5, (0, 130, 255), 1)
            previous = target
    return True
