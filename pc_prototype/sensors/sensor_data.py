"""未来 ESP32/MQ-2/温度模块使用的传感器数据接口。"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class SensorData:
    smoke: float | None = None
    temperature: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)
