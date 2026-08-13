import json
from pathlib import Path

src = Path(r"rpi_app/configs/demo_000345_explain.json")
dst = Path(r"rpi_app/configs/demo_000345_explain_windows.json")

cfg = json.loads(src.read_text(encoding="utf-8"))

cfg["source"] = r"C:\Users\33712\Desktop\Test_IITB-Corridor\Test_IITB-Corridor\演示候选_mp4\000345.mp4"
cfg["output_dir"] = "output/demo_000345_explain_windows"
cfg["output_video_name"] = "000345_explain_latest.mp4"

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
