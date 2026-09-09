# 无互联网展示模式

树莓派建立 `Huian_Loudao` Wi-Fi 热点，固定地址为 `192.168.50.1`。展示电脑连接该热点后，在本机运行“慧眼疏流安全检测系统”；视频识别在电脑本地完成，报警状态通过树莓派转发到 ESP32。

## 树莓派一次性配置

在已能 SSH 到树莓派的电脑上执行：

```bash
sudo /home/x/Huian_YOLO/scripts/huian-network-mode.sh showcase
```

电脑会暂时断开原 Wi-Fi。改连 `Huian_Loudao` 后，访问 `http://192.168.50.1:8780/api/status`；确认正常后执行：

```bash
sudo /home/x/Huian_YOLO/scripts/huian-network-mode.sh showcase-confirm
```

确认后热点会在每次开机时自动启用。`huian-main.service` 已开机自启。

## 演示使用

1. 给树莓派和 ESP32 通电，等待约一分钟。
2. 电脑连接 `Huian_Loudao`，不需要能访问互联网。
3. 运行展示端。首次没有保存过地址时，它会自动访问 `http://192.168.50.1:8780`。
4. 顶部出现“树莓派在线 · ESP32在线”后开始播放案例。

开发时如需接回普通路由器 Wi-Fi，执行 `huian-network-mode.sh development`；展示模式再执行 `showcase` 和 `showcase-confirm`。