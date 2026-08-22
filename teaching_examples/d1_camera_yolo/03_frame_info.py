"""D1-03：观察一帧画面的尺寸和像素信息。"""

import cv2


def main() -> None:
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("无法打开摄像头，请检查摄像头。")
        return

    try:
        ok, frame = camera.read()
        if not ok:
            print("没有读取到画面。")
            return

        height, width, channels = frame.shape
        print(f"画面宽度：{width} 像素")
        print(f"画面高度：{height} 像素")
        print(f"颜色通道：{channels}（OpenCV 使用 BGR 顺序）")
        print(f"左上角像素 BGR：{frame[0, 0].tolist()}")

        cv2.imshow("D1 - Frame Info", frame)
        print("按任意键关闭窗口。")
        cv2.waitKey(0)
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
