import json
from pathlib import Path

src = Path(r"rpi_app/configs/demo_000345_explain.json")
dst = Path(r"rpi_app/configs/demo_desktop_ui_test.json")

cfg = json.loads(src.read_text(encoding="utf-8"))

cfg["source"] = r"C:\Users\33712\Desktop\商场扶梯46秒.mp4"
cfg["output_dir"] = "output/demo_desktop_ui_test"
cfg["output_video_name"] = "desktop_ui_test_annotated.mp4"

cfg.setdefault("display", {})["layout"] = "dashboard"
cfg["display"]["mode"] = "explain"
cfg["display"]["show_subtitle"] = False
cfg["display"]["explain_track_id"] = None

dst.write_text(
    json.dumps(cfg, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("created:", dst)
print("source:", cfg["source"])
print("mode:", cfg["display"]["mode"])
