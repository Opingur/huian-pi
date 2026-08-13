"""ESP32 通信预留接口；第一阶段不建立串口连接。"""

from __future__ import annotations

from typing import Mapping


class ESP32Client:
    def send_status(self, status: Mapping[str, object]) -> None:
        """第二阶段实现串口/Wi-Fi 发送；当前刻意保持无副作用。"""
        _ = status
