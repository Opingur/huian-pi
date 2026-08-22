"""Non-blocking-friendly standard-library client for the Pi teacher service."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from teaching_console.runtime_paths import ensure_writable_data_root


DEFAULT_PI_URL = "http://huian-pi.local:8765"
_DIRECT_OPENER = build_opener(ProxyHandler({}))


def direct_urlopen(request: Request, *, timeout: float):
    """Reach a local/Tailscale Pi directly even when Windows has a global proxy."""
    return _DIRECT_OPENER.open(request, timeout=timeout)


class TeacherRemoteError(RuntimeError):
    pass


def normalize_base_url(value: str | None) -> str:
    text = (value or "").strip().rstrip("/")
    if not text:
        return DEFAULT_PI_URL
    if not text.startswith(("http://", "https://")):
        text = "http://" + text
    return text


@dataclass(frozen=True)
class TeacherRemoteSettings:
    base_url: str = DEFAULT_PI_URL


class TeacherRemoteSettingsStore:
    def __init__(self, project_root: Path) -> None:
        self.path = ensure_writable_data_root(project_root) / "teacher_remote.json"

    def load(self) -> TeacherRemoteSettings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return TeacherRemoteSettings()
        return TeacherRemoteSettings(normalize_base_url(payload.get("base_url") if isinstance(payload, dict) else None))

    def save(self, settings: TeacherRemoteSettings) -> None:
        self.path.write_text(json.dumps({"base_url": normalize_base_url(settings.base_url)}, ensure_ascii=False, indent=2), encoding="utf-8")


class TeacherRemoteClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 1.5, opener: Callable[..., Any] | None = None) -> None:
        self.base_url = normalize_base_url(base_url)
        self.timeout_seconds = float(timeout_seconds)
        self.opener = opener or direct_urlopen

    def _request(self, path: str, *, method: str = "GET", body: Mapping[str, object] | None = None, binary: bool = False):
        data = None if body is None else json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except (OSError, URLError) as error:
            raise TeacherRemoteError(f"无法连接树莓派：{error}") from error
        if binary:
            return raw
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise TeacherRemoteError("树莓派返回的不是合法 JSON。") from error
        if not isinstance(payload, dict):
            raise TeacherRemoteError("树莓派 JSON 响应必须是对象。")
        if payload.get("ok") is False:
            raise TeacherRemoteError(str(payload.get("error", "树莓派拒绝请求")))
        return payload

    def health(self) -> dict[str, object]: return self._request("/api/health")
    def status(self) -> dict[str, object]: return self._request("/api/status")
    def frame(self) -> bytes: return self._request("/api/frame.jpg", binary=True)
    def cases(self) -> list[dict[str, object]]:
        payload = self._request("/api/cases")
        cases = payload.get("cases", [])
        return [dict(item) for item in cases if isinstance(item, dict)]
    def demo_state(self) -> dict[str, object]: return self._request("/api/demo/state")
    def demo_command(self, action: str, *, case_id: str | None = None) -> dict[str, object]:
        body: dict[str, object] = {} if case_id is None else {"case_id": case_id}
        return self._request(f"/api/demo/{action}", method="POST", body=body)


def live_status_rows(status: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    number = lambda value, places=2: "—" if value is None else f"{float(value):.{places}f}"
    return (
        ("当前人数", str(status.get("total_people", 0))),
        ("当前风险", str(status.get("vision_risk", "NORMAL"))),
        ("Crowd Index", number(status.get("crowd_index"))),
        ("跑动人数", str(status.get("running_count", 0))),
        ("当前事件", str(status.get("current_event", "—"))),
        ("ESP32", "在线" if status.get("esp32_online") else "未连接"),
        ("摄像头", "在线" if status.get("camera_online") else "未连接"),
        ("视频时间", number(status.get("source_time"), 3) + " s" if status.get("source_time") is not None else "—"),
    )


def demo_case_row(case: Mapping[str, object]) -> tuple[str, str, str]:
    return str(case.get("case_id", "")), str(case.get("title", "")), f"{float(case.get('duration', 0.0) or 0.0):.1f} s"