"""D1-01：打开摄像头并显示实时画面。"""

import cv2


def main() -> None:
    # 0 是电脑的默认摄像头；没有画面时可尝试改成 1。
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("无法打开摄像头，请检查摄像头是否被其他程序占用。")
        return

    print("摄像头已打开，按 q 退出。")
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("没有读取到画面。")
                break

            cv2.imshow("D1 - Open Camera", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
