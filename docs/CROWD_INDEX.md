# Crowd Index

动态 Crowd Index 用于描述楼道固定区域的占用、增长和空间汇合风险：

```text
I = wd × density_score + wg × growth_score + wc × conflict_score
```

三个分量均限制在 `[0, 1]`：

- `density_score`：左右区域人数相对总容量。
- `growth_score`：正向 `occupancy_growth` 相对最大增长率；它是区域占用变化，不是跑动速度。
- `conflict_score`：正式空间汇合分数；未提供时才可按配置使用旧 fixed-region conflict。

正式默认权重来自 `rpi_app/config.json` 与各运行配置：density `0.5`、growth `0.3`、conflict `0.2`。实现位于 `rpi_app/decision/crowd_index.py`。

风险映射实现位于 `rpi_app/decision/risk_engine.py`：`<0.30` 为 `NORMAL`，`0.30–0.59` 为 `WARNING`，`≥0.60` 为 `CROWD`。人数安全兜底也只会提升到 `CROWD`；`DANGER` 不表示普通拥挤。