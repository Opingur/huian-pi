"""K230 KPU adapter interface; no unverified hardware setup is included."""


def normalize_person_detections(raw_detections):
    detections = []
    for item in raw_detections:
        if item.get("class") not in (0, "person"):
            continue
        detections.append({"class": "person", "confidence": round(float(item["confidence"]), 3),
                           "x1": int(item["x1"]), "y1": int(item["y1"]),
                           "x2": int(item["x2"]), "y2": int(item["y2"])})
    return detections


class K230PersonDetector:
    def __init__(self, backend=None):
        self.backend = backend

    def detect(self, image):
        if self.backend is None:
            raise RuntimeError("Configure the verified CanMV camera/KPU backend first.")
        return normalize_person_detections(self.backend.detect(image))
