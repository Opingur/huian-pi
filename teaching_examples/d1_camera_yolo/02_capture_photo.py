"""D1-02：从摄像头拍一张照片。"""

from pathlib import Path

import cv2


def main() -> None:
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("无法打开摄像头，请检查摄像头。")
        return

    photo_path = Path(__file__).with_name("captured_photo.jpg")
    print("按空格拍照，按 q 退出。")
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("没有读取到画面。")
                break

            cv2.imshow("D1 - Capture Photo", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(" "):
                cv2.imwrite(str(photo_path), frame)
                print(f"照片已保存：{photo_path}")
            elif key == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
