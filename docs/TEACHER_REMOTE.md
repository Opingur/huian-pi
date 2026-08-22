# 教师端远程展示 MVP

树莓派运行轻量教师服务：

```bash
cd /home/x/Huian_YOLO
python -m rpi_app.services.teacher_server --host 0.0.0.0 --port 8765
```

Windows 启动 `python -m teaching_console.main`，在“实时系统”输入 `http://huian-pi.local:8765`（也可替换为局域网或 Tailscale 地址）。页面每约 250ms 拉取 `/api/status` 和 `/api/frame.jpg`；网络请求在后台线程，不会阻塞 Tkinter。

“展示演示”由树莓派读取 `demo_cases/<case_id>/dashboard.mp4` 与同目录 `events.jsonl`。开始、暂停、继续、重播和停止均通过 HTTP 发给树莓派；树莓派使用自己的视频时间轴更新画面并通过现有 Pi UART 向 ESP32 发送正式 JSON。Windows 不作为比赛展示时的 ESP32 控制链。

案例由正式处理链导出：

```powershell
python -m rpi_app.runners.demo_case_export --video test_data/000327.mp4 --case-id 000327 --title "人流监测示例"
scp -r demo_cases/000327 x@huian-pi:/home/x/Huian_YOLO/demo_cases/
```

`dashboard.mp4`、`events.jsonl`、`summary.json`、`cover.jpg` 均为案例必须文件；大型案例内容由 `.gitignore` 排除。实时系统所见状态和 Dashboard 来自正式 Pi 主链写入的 `output/runtime/` 原子快照，服务不计算第二套人数、风险或 Crowd Index。