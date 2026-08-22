"""Minimal local-network HTTP service used by the Windows Teaching Console."""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
from typing import Any, Mapping

from rpi_app.communication.esp32 import ESP32Publisher
from rpi_app.services.demo_engine import DemoEngine, scan_demo_cases
from rpi_app.services.runtime_snapshot import PROJECT_ROOT, load_latest_frame, load_latest_status
from rpi_app.utils.config import load_config


class TeacherRuntime:
    """One service-owned demo engine plus read-only access to the formal live snapshot."""

    def __init__(
        self,
        cases_root: Path,
        runtime_directory: Path,
        *,
        esp32_config: Mapping[str, object] | None = None,
        demo_engine: DemoEngine | None = None,
    ) -> None:
        self.cases_root = cases_root.resolve()
        self.runtime_directory = runtime_directory.resolve()
        self.demo_engine = demo_engine or DemoEngine(self.cases_root, ESP32Publisher(esp32_config))

    def health(self) -> dict[str, object]:
        return {"ok": True, "hostname": socket.gethostname(), "service": "huian-teacher", "version": 1}

    def cases(self) -> list[dict[str, object]]:
        return self.demo_engine.cases()

    def _live_status(self) -> dict[str, object]:
        status = load_latest_status(self.runtime_directory)
        if status is None:
            return {
                "mode": "idle", "total_people": 0, "vision_risk": "NORMAL", "crowd_index": 0.0,
                "running_event": False, "running_count": 0, "current_event": "等待正式系统画面",
                "esp32_online": False, "camera_online": False, "source_time": None,
            }
        status = dict(status)
        status.setdefault("mode", "live")
        status.setdefault("current_event", "检测到跑动" if status.get("running_event") else "正式实时监测")
        status.setdefault("esp32_online", False)
        status.setdefault("camera_online", True)
        return status

    def status(self) -> dict[str, object]:
        demo = self.demo_engine.state()
        if demo["state"] != "stopped":
            demo.setdefault("esp32_online", False)
            demo.setdefault("camera_online", False)
            return demo
        return self._live_status()

    def frame(self) -> bytes | None:
        demo = self.demo_engine.frame()
        return demo if demo is not None else load_latest_frame(self.runtime_directory)

    def cover(self, case_id: str) -> bytes | None:
        for item in scan_demo_cases(self.cases_root):
            if item.case_id == case_id:
                try:
                    return (item.directory / "cover.jpg").read_bytes()
                except OSError:
                    return None
        return None

    def command(self, action: str, body: Mapping[str, object]) -> dict[str, object]:
        if action == "start":
            case_id = str(body.get("case_id", "")).strip()
            if not case_id:
                raise ValueError("start 需要 case_id")
            return self.demo_engine.start(case_id)
        if action == "pause":
            return self.demo_engine.pause()
        if action == "resume":
            return self.demo_engine.resume()
        if action == "restart":
            return self.demo_engine.restart()
        if action == "stop":
            return self.demo_engine.stop()
        raise ValueError("未知演示命令")

    def close(self) -> None:
        self.demo_engine.close()


def make_handler(runtime: TeacherRuntime):
    class TeacherRequestHandler(BaseHTTPRequestHandler):
        server_version = "HuianTeacher/1"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _binary(self, payload: bytes) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _not_found(self) -> None:
            self._json({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/health":
                self._json(runtime.health())
            elif path == "/api/status":
                self._json(runtime.status())
            elif path == "/api/cases":
                self._json({"cases": runtime.cases()})
            elif path == "/api/demo/state":
                self._json(runtime.demo_engine.state())
            elif path == "/api/frame.jpg":
                frame = runtime.frame()
                self._not_found() if frame is None else self._binary(frame)
            elif path.startswith("/api/cases/") and path.endswith("/cover.jpg"):
                case_id = path[len("/api/cases/"):-len("/cover.jpg")]
                if not case_id or "/" in case_id or "\\" in case_id:
                    self._not_found()
                else:
                    cover = runtime.cover(case_id)
                    self._not_found() if cover is None else self._binary(cover)
            else:
                self._not_found()

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            prefix = "/api/demo/"
            if not path.startswith(prefix):
                self._not_found()
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 8192)
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("请求体必须是 JSON 对象")
                self._json(runtime.command(path[len(prefix):], body))
            except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
                self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    return TeacherRequestHandler


def run_server(runtime: TeacherRuntime, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(runtime))
    print(f"Huian teacher service listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Huian local-network teacher service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", default=str(PROJECT_ROOT / "rpi_app" / "configs" / "rpi_imx219_live.json"))
    parser.add_argument("--cases-root", default=str(PROJECT_ROOT / "demo_cases"))
    parser.add_argument("--runtime-dir", default=str(PROJECT_ROOT / "output" / "runtime"))
    args = parser.parse_args()
    config = load_config(args.config)
    runtime = TeacherRuntime(Path(args.cases_root), Path(args.runtime_dir), esp32_config=config.get("esp32"))
    run_server(runtime, args.host, args.port)


if __name__ == "__main__":
    main()