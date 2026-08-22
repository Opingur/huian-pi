# 教师端演示案例

案例文件由真实正式算法导出，但大型视频与事件数据不纳入 Git：

```text
demo_cases/<case_id>/
  dashboard.mp4
  events.jsonl
  summary.json
  cover.jpg
```

生成 000327：

```powershell
python -m rpi_app.runners.demo_case_export --video test_data/000327.mp4 --case-id 000327 --title "人流监测示例"
```

将完整目录复制到树莓派 `/home/x/Huian_YOLO/demo_cases/000327/`。Dashboard 视频必须由本项目正式处理链生成，不能使用旧成品视频。