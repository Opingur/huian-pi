"""Export the PC model to ONNX. This does not create a K230 kmodel."""

from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "yolov8n.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--opset", type=int, default=12)
    args = parser.parse_args()
    if not args.model.is_file():
        raise FileNotFoundError("Missing model: {}".format(args.model))
    exported = YOLO(str(args.model)).export(format="onnx", imgsz=args.imgsz, opset=args.opset)
    print("ONNX exported: {}".format(exported))


if __name__ == "__main__":
    main()
