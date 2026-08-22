"""Windows MP4 demonstration using the same formal tracked-frame pipeline as Pi video mode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


from rpi_app.main import _run_config
from rpi_app.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Huian formal MP4 dashboard demo (real YOLO + ByteTrack).")
    parser.add_argument("--video", required=True, help="Raw MP4/AVI/MOV input; never use a rendered dashboard video.")
    parser.add_argument("--config", default=None, help="Optional rpi_app JSON configuration.")
    parser.add_argument("--no-esp32", action="store_true", help="Disable serial output (recommended when Pi owns ESP32).")
    parser.add_argument("--serial-port", default=None, help="Windows USB serial port, for example COM6.")
    parser.add_argument("--no-display", action="store_true", help="Process without the OpenCV dashboard window.")
    args = parser.parse_args()
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        parser.error(f"video not found: {video}")

    config = load_config(args.config) if args.config else load_config()
    config.update({
        "source_type": "video",
        "source": str(video),
        "display_window": not args.no_display,
        "output_dir": f"../output/video_demo_{video.stem}",
        "save_annotated_video": False,
    })
    esp32 = dict(config.get("esp32", {}))
    if args.no_esp32:
        esp32.update({"enabled": False, "dry_run": True})
    elif args.serial_port:
        esp32.update({"enabled": True, "dry_run": False, "port": args.serial_port})
    else:
        # Never accidentally open a Pi UART from a Windows presentation PC.
        esp32.update({"enabled": False, "dry_run": True})
    config["esp32"] = esp32
    _run_config(config)


if __name__ == "__main__":
    main()
