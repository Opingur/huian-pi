# Porting map

| PC prototype | K230 target | Status |
| --- | --- | --- |
| Ultralytics detector | `k230_app/detector.py` KPU adapter | pending firmware/API |
| Fixed-passage region | `k230_app/region.py` | logic prepared |
| Occupancy trend | `k230_app/people_flow.py` | logic prepared |
| Risk rules | `k230_app/risk_engine.py` | logic prepared |
| JSON output | `k230_app/uart_protocol.py` | protocol prepared |

`left_people` and `right_people` are fixed-passage occupancy counts. They do not prove real movement direction from one frame.
