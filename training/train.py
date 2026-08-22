"""Editable, real YOLOv8 fine-tune entry point for the generated Colab package.

This script is copied into the package.  It is not imported or executed by the
teaching console, so the local Windows machine never begins training.
"""
from __future__ import annotations

import argparse

from ultralytics import YOLO


DEFAULT_MODEL = "yolov8n.pt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="慧安 person detection YOLOv8 fine-tune")
    parser.add_argument("--data", default="data.yaml")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--project", default="output/training/huian_finetune")
    parser.add_argument("--name", default="yolov8n_person")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    model = YOLO(args.model)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        project=args.project,
        name=args.name,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
