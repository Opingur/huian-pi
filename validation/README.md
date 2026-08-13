# 慧安楼道实验验证

本目录只提供真实实验的流程、空白标注模板和自动对比工具；没有人工标注时，不能宣称任何准确率。

## 人数验证

1. 选取视频中的若干时间点，人工数出画面人数。
2. 在 `templates/count_annotations.csv` 填写视频名、源视频时间和人工人数。
3. 使用同一视频运行系统，获得 `status.jsonl`。
4. 运行：

```bash
python validation/scripts/validate.py count \
  --video 000327 --annotations validation/annotations/count_annotations.csv \
  --status rpi_app/output/demo_000327/status.jsonl \
  --output validation/results/count_comparison.csv
```

脚本会输出样本数、MAE、最大绝对误差和完全正确比例。空标注不会生成虚假结果。

## 方向验证

人工填写 `direction_annotations.csv`：记录时间区间和真实方向。由于 ByteTrack ID 不承诺跨时段永久稳定，`track_reference` 可写屏幕位置描述；若能可靠对应，再填写 `system_track_id`。系统方向需从真实轨迹导出到 `system_directions.csv` 后再比对。

## 趋势验证

```bash
python validation/scripts/validate.py prediction \
  --video 000318 --status rpi_app/output/demo_000318/status.jsonl \
  --output validation/results/prediction_comparison.csv
```

脚本只比较实际存在的未来 10/20/30 秒时间点，视频结尾不足的样本会跳过，不补零。

## 预警验证

人工填写预期场景时间区间后运行 `alarm` 子命令。当前没有真实烟雾视频或传感器联动数据时，不应填写或宣称烟雾报警验证结论。
