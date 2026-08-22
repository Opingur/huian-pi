"""D1-05：实时摄像头画面中的 YOLO 人员检测。"""

from pathlib import Path

import cv2
from ultralytics import YOLO


def main() -> None:
    model_path = Path(__file__).parents[2] / "models" / "yolov8n.pt"
    if not model_path.exists():
        print(f"找不到 YOLO 模型：{model_path}")
        return

    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("无法打开摄像头，请检查摄像头。")
        return

    # 本示例只做“看见人”和“数人数”，不使用 Track ID 或 ByteTrack。
    model = YOLO(str(model_path))
    print("实时人员检测开始，按 q 退出。")
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("没有读取到画面。")
                break

            result = model(frame, classes=[0], conf=0.35, verbose=False)[0]
            preview = result.plot()
            count = len(result.boxes)
            cv2.putText(
                preview,
                f"People: {count}",
                (18, 36),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0),
                2,
            )
            cv2.imshow("D1 - YOLO Camera", preview)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
