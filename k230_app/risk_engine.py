"""K230 risk rules aligned with the PC prototype."""


class RiskEngine:
    def __init__(self, warning_people=8, danger_people=16):
        self.warning_people = warning_people
        self.danger_people = danger_people

    def evaluate(self, left_people, right_people, occupancy_growth=0.0,
                 direction_conflict=False, smoke=None, temperature=None,
                 smoke_fire_threshold=1.0, temperature_fire_threshold=60.0):
        if ((smoke is not None and smoke >= smoke_fire_threshold) or
                (temperature is not None and temperature >= temperature_fire_threshold)):
            return "FIRE"
        total_people = left_people + right_people
        level = "NORMAL" if total_people < self.warning_people else "WARNING" if total_people < self.danger_people else "DANGER"
        if direction_conflict and level == "NORMAL":
            return "WARNING"
        if direction_conflict and level == "WARNING":
            return "DANGER"
        return level
