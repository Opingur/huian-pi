"""K230 main-flow skeleton; adapt verified CanMV APIs before deployment."""

from detector import K230PersonDetector
from people_flow import PeopleFlowAnalyzer
from region import count_stair_regions
from risk_engine import RiskEngine


def process_frame(frame, frame_width, detector, flow_analyzer, risk_engine):
    detections = detector.detect(frame)
    left_people, right_people = count_stair_regions(detections, frame_width)
    status, snapshot_saved = flow_analyzer.update(left_people, right_people)
    status["device"] = "Huian_Loudao_01"
    status["crowd_level"] = risk_engine.evaluate(
        left_people, right_people, status["occupancy_growth"], status["direction_conflict"])
    return detections, status, snapshot_saved


def main():
    raise RuntimeError("K230 deployment is pending CanMV version and official camera/KPU/UART API confirmation.")


if __name__ == "__main__":
    main()
