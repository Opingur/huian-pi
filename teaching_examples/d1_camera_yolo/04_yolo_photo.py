"""D1-04：用 YOLO 在一张照片中寻找人。"""

from pathlib import Path

import cv2
from ultralytics import YOLO


def main() -> None:
    # 先运行 02_capture_photo.py，或把这里改成自己的照片路径。
    photo_path = Path(__file__).with_name("captured_photo.jpg")
    model_path = Path(__file__).parents[2] / "models" / "yolov8n.pt"
    if not photo_path.exists():
        print(f"找不到照片：{photo_path}，请先运行 02_capture_photo.py。")
        return
    if not model_path.exists():
        print(f"找不到 YOLO 模型：{model_path}")
        return

    image = cv2.imread(str(photo_path))
    if image is None:
        print("照片无法读取。")
        return

    # classes=[0] 表示只保留 COCO 数据集中的 person（人）类别。
    model = YOLO(str(model_path))
    result = model(image, classes=[0], conf=0.35, verbose=False)[0]
    person_count = len(result.boxes)
    print(f"YOLO 找到 {person_count} 人。")

    # plot() 只用于把本次检测框画在副本上，不会改动原照片。
    preview = result.plot()
    cv2.imshow("D1 - YOLO Photo", preview)
    print("按任意键关闭窗口。")
    cv2.waitKey(0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
