from ultralytics import YOLO
import cv2
import json
from datetime import datetime


# =====================
# 加载YOLO模型
# =====================

model = YOLO("yolov8n.pt")


# =====================
# 摄像头
# =====================

cap = cv2.VideoCapture(0)



# =====================
# 风险判断
# =====================

def judge_risk(count):

    if count < 10:
        return "NORMAL", (0,255,0)

    elif count < 20:
        return "WARNING", (0,255,255)

    else:
        return "DANGER", (0,0,255)



# =====================
# 主循环
# =====================

while True:


    ret, frame = cap.read()

    if not ret:
        break


    # 获取画面宽度

    height, width = frame.shape[:2]


    # 中间分割线

    middle = width // 2



    # YOLO检测

    results = model(frame)

    result = results[0]



    # 左右人数

    down_count = 0   # 左侧，下楼

    up_count = 0     # 右侧，上楼



    # 遍历检测框

    for box in result.boxes:


        cls = int(box.cls[0])


        # 只检测人

        if cls == 0:


            # 坐标

            x1,y1,x2,y2 = map(
                int,
                box.xyxy[0]
            )


            # 人体中心点

            center_x = int(
                (x1+x2)/2
            )


            center_y = int(
                (y1+y2)/2
            )


            # 左右判断

            if center_x < middle:

                down_count += 1


                # 左侧画蓝点

                cv2.circle(
                    frame,
                    (center_x,center_y),
                    5,
                    (255,0,0),
                    -1
                )


            else:

                up_count += 1


                # 右侧画红点

                cv2.circle(
                    frame,
                    (center_x,center_y),
                    5,
                    (0,0,255),
                    -1
                )



    # 风险判断

    down_risk, down_color = judge_risk(down_count)

    up_risk, up_color = judge_risk(up_count)



    # =====================
    # JSON数据
    # =====================

    data = {

        "device":"Huian_Loudao_01",

        "down_people":down_count,

        "down_status":down_risk,

        "up_people":up_count,

        "up_status":up_risk,

        "time":
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    }


    print(
        json.dumps(
            data,
            ensure_ascii=False
        )
    )



    # 绘制YOLO框

    frame = result.plot()



    # 重新画分割线

    cv2.line(
        frame,
        (middle,0),
        (middle,height),
        (255,255,255),
        3
    )



    # 左侧显示

    cv2.putText(
        frame,
        f"DOWN: {down_count}",
        (30,50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        down_color,
        2
    )


    cv2.putText(
        frame,
        down_risk,
        (30,100),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        down_color,
        2
    )



    # 右侧显示

    cv2.putText(
        frame,
        f"UP: {up_count}",
        (middle+30,50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        up_color,
        2
    )


    cv2.putText(
        frame,
        up_risk,
        (middle+30,100),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        up_color,
        2
    )



    # 标题

    cv2.putText(
        frame,
        "Huian Loudao Safety System",
        (30,150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255,255,255),
        2
    )



    cv2.imshow(
        "Huian Loudao",
        frame
    )



    if cv2.waitKey(1)==ord("q"):
        break



cap.release()

cv2.destroyAllWindows()