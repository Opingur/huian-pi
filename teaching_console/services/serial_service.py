"""Non-blocking pyserial transport for the Tkinter ESP32 lesson page."""
from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Event, Lock, Thread
from time import strftime
from typing import Any


@dataclass(frozen=True)
class SerialEvent:
    direction: str
    text: str
    timestamp: str


class SerialService:
    def __init__(self) -> None:
        self.events: Queue[SerialEvent] = Queue()
        self._serial: Any | None = None
        self._thread: Thread | None = None
        self._stop = Event()
        self._lock = Lock()
        self.port = ""
        self.baud = 115200

    @staticmethod
    def list_ports() -> list[str]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        return [item.device for item in list_ports.comports()]

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._serial is not None and bool(getattr(self._serial, "is_open", False))

    def connect(self, port: str, baud: int = 115200) -> None:
        self.disconnect()
        try:
            import serial
        except ImportError as error:
            raise RuntimeError("未安装 pyserial。请运行：python -m pip install pyserial") from error
        try:
            connection = serial.Serial(port, int(baud), timeout=0.2, write_timeout=1)
        except Exception as error:
            raise RuntimeError(f"无法打开 {port}：{error}") from error
        with self._lock:
            self._serial = connection
            self.port, self.baud = port, int(baud)
        self._stop.clear()
        self._thread = Thread(target=self._read_loop, name="huian-usb-serial", daemon=True)
        self._thread.start()
        self._emit("SYSTEM", f"已连接 {port} @ {baud}")

    def disconnect(self) -> None:
        self._stop.set()
        with self._lock:
            connection, self._serial = self._serial, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def send(self, payload: bytes) -> None:
        with self._lock:
            connection = self._serial
        if connection is None or not getattr(connection, "is_open", False):
            raise RuntimeError("ESP32 未连接。")
        try:
            connection.write(payload)
            connection.flush()
        except Exception as error:
            self._emit("SYSTEM", f"串口写入失败：{error}")
            self.disconnect()
            raise RuntimeError(f"串口写入失败：{error}") from error
        self._emit("TX", payload.decode("utf-8", errors="replace").rstrip("\r\n"))

    def close(self) -> None:
        self.disconnect()

    def _emit(self, direction: str, text: str) -> None:
        self.events.put(SerialEvent(direction, text, strftime("%H:%M:%S")))

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                connection = self._serial
            if connection is None:
                return
            try:
                raw = connection.readline()
            except Exception as error:
                self._emit("SYSTEM", f"串口已断开：{error}")
                self.disconnect()
                return
            if raw:
                self._emit("RX", raw.decode("utf-8", errors="replace").rstrip("\r\n"))
