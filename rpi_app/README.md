# 慧安楼道 Raspberry Pi 5 视觉端

rpi_app 是可独立复制到 Raspberry Pi 5 的视觉端：YOLO person 检测、固定左右通道占用统计、30 秒占用趋势、动态拥挤指数、风险 JSON 和标注结果图。

## 重要语义

- LEFT (DOWN) 与 RIGHT (UP) 是安装现场预设的固定空间通道标签。
- 程序只按单帧检测框中心点统计左右区域占用，不推断人员的真实运动方向。
- occupancy_growth 是固定区域占用人数在最近时间窗口中的变化速度；它不是人员通过速度、运动速度或真实上下楼速度。

## Windows 本地运行

在项目根目录执行：

    python rpi_app/main.py

默认配置为图片模式，使用相对路径 ../test_data/people.jpg 与 ../models/yolov8n.pt。当前 Windows 项目没有 test_data/people.jpg 时，将 source 改为已有测试图 ../bus.jpg。

图片结果写入 rpi_app/output/源文件名_annotated.jpg。默认 esp32_dry_run 为 true，控制台只输出一行协议 JSON，不打开真实串口。

## 视频模式

将 source_type 设为 video，并把 source 设为相对于 rpi_app 的视频路径，例如 ../test_data/test.mp4。

视频逐帧推理和绘制；每秒保存一次占用快照、计算最近 30 秒占用变化并输出一次 JSON。设置 display_window 为 true 可显示窗口，按 Q 退出；设置 save_annotated_video 为 true 才会额外生成标注视频。

## Raspberry Pi 5 部署

从 Windows 整体复制 rpi_app（不复制模型）：

    scp -r "C:\Users\33712\Desktop\科创作品——慧安楼道\Huian_YOLO\rpi_app" x@192.168.56.68:/home/x/Huian_YOLO/

树莓派已有模型和测试图片后运行：

    cd ~/Huian_YOLO
    source .venv/bin/activate
    python rpi_app/main.py

配置中的 ../models/yolov8n.pt 与 ../test_data/people.jpg 均相对于 rpi_app 解析，因此同一份代码可在 Windows 与 Raspberry Pi OS 使用。

## JSON 协议

每次输出包含 protocol_version、device、vision_risk、crowd_index、三项评分、左右与总人数、occupancy_growth、direction_conflict、timestamp。dry-run 输出即为将来发送给 ESP32 的内容。

## 当前未实现

- Raspberry Pi CSI 摄像头输入；
- Raspberry Pi 到 ESP32 的真实 USB Serial/UART 通信；
- NCNN 优化。

这些项目需在 Raspberry Pi 5 完成真实硬件验证后再实现。

## 短时拥堵趋势预测

系统复用每秒保存的固定区域占用快照，在最近 15 秒（可配置）内以最小二乘线性回归拟合人数趋势。它输出未来 10、20、30 秒的人员占用预测、对应人数风险，以及按当前上升趋势预计达到 WARNING / DANGER 阈值的时间。

预测只用于提前提示、界面展示与比赛演示，不覆盖当前真实的 vision_risk，也不改变 ESP32 控制状态。prediction_slope 表示人员占用时间序列趋势，不是人员移动速度或真实行为预测。

预测参数位于 config.json 的 prediction：

    "window_seconds": 15
    "min_samples": 5
    "horizons": [10, 20, 30]
    "max_eta_seconds": 120


## ByteTrack 真实画面运动与交汇区

视频模式使用 Ultralytics ByteTrack 为每个 person 建立 Track ID，并以检测框底部中心点保存约两秒轨迹。heading_angle、toward_conflict_zone 与 convergence_eta 都来自连续轨迹；它们描述的是画面中的相对运动与相对到达时间，不是现实米/秒、真实学生行为或精确碰撞时间。

LEFT (DOWN) / RIGHT (UP) 仍只作为旧的固定区域占用兼容字段，不能用于判断真实上下楼方向，也不参与新的 RED 汇合判断。

Conflict Zone 是安装/测试场景的一次人工标定。crossroad_test.json 提供了中央多边形初值；部署时应根据视频画面核验坐标，不是算法自动识别结构。

视频模式使用视频自身时间轴（CAP_PROP_POS_MSEC，回退为帧序号/FPS），因此轨迹时长、每秒快照、30 秒趋势、预测与报警 hold 不受 Raspberry Pi 推理速度影响。

YELLOW 表示单股同向高密度或其短时趋势提示；RED 要求至少两股人数充足、夹角足够且同时朝同一 Conflict Zone 靠近。预测结果不会覆盖当前 vision_risk，也不会直接控制 ESP32。

## Raspberry Pi 59 秒十字路口测试

先复制 rpi_app 和视频，然后在树莓派运行：

    python rpi_app/main.py --config rpi_app/configs/crossroad_test.json --source "/home/x/Huian_YOLO/test_data/十字路口59秒.mp4" --source-type video --no-display

该 profile 生成 output/crossroad_test/crossroad_annotated.mp4、status.jsonl 和 summary.json。Windows 本地不应完整处理该 59 秒视频；应由 Raspberry Pi 5 输出实际 ARM64 性能与算法统计。

可用参数：--config、--source、--source-type、--no-display。
