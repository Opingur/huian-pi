"""Small read-only HTTP server for the Pi competition display page."""
from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from rpi_app.services.runtime_snapshot import load_latest_frame, runtime_directory
from rpi_app.web.runtime_adapter import RuntimeStatusAdapter


STATIC_ROOT = Path(__file__).resolve().parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHOWCASE_VIDEO_DIRECTORY = PROJECT_ROOT / "showcase_videos"
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".webm", ".mov"}


class WebRuntime:
    def __init__(self, runtime_dir: Path | None = None, showcase_dir: Path | None = None) -> None:
        self.runtime_directory = runtime_dir or runtime_directory()
        self.status_adapter = RuntimeStatusAdapter(self.runtime_directory)
        self.showcase_directory = (showcase_dir or SHOWCASE_VIDEO_DIRECTORY).resolve()

    def status(self) -> dict[str, object]:
        return self.status_adapter.status()

    def frame(self) -> bytes | None:
        return load_latest_frame(self.runtime_directory)

    def showcase_videos(self) -> list[dict[str, str]]:
        """Return only deliberately curated local competition videos."""
        try:
            videos = sorted(
                (
                    item for item in self.showcase_directory.iterdir()
                    if item.is_file() and item.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            return []
        return [
            {
                "id": item.name,
                "name": item.stem.replace("_", " "),
                "url": f"/showcase/{quote(item.name, safe='')}",
            }
            for item in videos
        ]

    def showcase_video(self, requested_name: str) -> Path | None:
        try:
            candidate = (self.showcase_directory / unquote(requested_name)).resolve()
            candidate.relative_to(self.showcase_directory)
        except (OSError, ValueError):
            return None
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            return None
        return candidate


def make_handler(runtime: WebRuntime):
    class HuianWebHandler(BaseHTTPRequestHandler):
        server_version = "HuianPiWeb/1.0"

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _json(self, payload: dict[str, object], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _binary(self, body: bytes, content_type: str) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _video(self, path: Path) -> None:
            """Serve a local video with browser seeking support (HTTP Range / 206)."""
            try:
                total_size = path.stat().st_size
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            start, end = 0, total_size - 1
            partial = False
            requested_range = self.headers.get("Range")
            if requested_range:
                try:
                    unit, value = requested_range.split("=", 1)
                    if unit.strip().lower() != "bytes" or "," in value:
                        raise ValueError
                    first, last = value.strip().split("-", 1)
                    if first:
                        start = int(first)
                        end = int(last) if last else total_size - 1
                    else:
                        suffix_length = int(last)
                        if suffix_length <= 0:
                            raise ValueError
                        start = max(total_size - suffix_length, 0)
                    if start < 0 or start >= total_size or end < start:
                        raise ValueError
                    end = min(end, total_size - 1)
                    partial = True
                except (TypeError, ValueError):
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{total_size}")
                    self.end_headers()
                    return

            length = end - start + 1
            mime_type, _encoding = mimetypes.guess_type(path.name)
            self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
            self.send_header("Content-Type", mime_type or "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(length))
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
            self.end_headers()
            try:
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = length
                    while remaining:
                        chunk = source.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _static(self, relative_path: str) -> None:
            candidate = (STATIC_ROOT / relative_path).resolve()
            try:
                candidate.relative_to(STATIC_ROOT.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = candidate.read_bytes()
            mime_type, _encoding = mimetypes.guess_type(candidate.name)
            self.send_response(HTTPStatus.OK)
            content_type = mime_type or "application/octet-stream"
            if candidate.suffix in {".html", ".css", ".js"}:
                content_type += "; charset=utf-8"
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/status":
                self._json(runtime.status())
                return
            if path == "/api/showcases":
                self._json({"videos": runtime.showcase_videos()})
                return
            if path == "/api/frame.jpg":
                frame = runtime.frame()
                if frame is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self._binary(frame, "image/jpeg")
                return
            if path == "/api/health":
                self._json({"ok": True, "service": "huian-pi-web", "version": 1})
                return
            if path.startswith("/showcase/"):
                video = runtime.showcase_video(path[len("/showcase/"):])
                if video is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self._video(video)
                return
            if path in {"/", "/index.html", "/teacher", "/teacher.html", "/static/teacher.html"}:
                self._redirect("/display")
                return
            aliases = {"/display": "display.html", "/display.html": "display.html"}
            relative_path = aliases.get(path, path[len("/static/"):] if path.startswith("/static/") else path.lstrip("/"))
            self._static(relative_path)

        def do_POST(self) -> None:
            # The competition display is deliberately read-only. Hardware commands
            # are accepted only by the formal Pi main process on its separate port.
            self.send_error(HTTPStatus.NOT_FOUND)
    return HuianWebHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Huian Pi offline competition display Web service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--runtime-dir", type=Path, default=None, help="formal Runtime Snapshot directory")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    selected_runtime = args.runtime_dir or runtime_directory()
    runtime = WebRuntime(selected_runtime)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(runtime))
    print(f"Huian Pi Web service listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
