# Dynamic crowd index

Fixed people thresholds are retained as a safety floor, but they cannot show whether a corridor is filling quickly or both fixed passages are occupied together. The dynamic index adds those signals.

## Formula

`I = wd * C + wg * G + wr * R`, clamped to `[0, 1]`.

- `C` is `(left_people + right_people) / (left_capacity + right_capacity)`, capped at 1.
- `G` is positive `occupancy_growth / growth_rate_max`, capped at 1. `occupancy_growth` comes from the existing 30-second snapshot window; it is an occupancy-change rate, not a person-passing speed.
- `R` is 1 when the existing fixed-passage conflict rule is true, otherwise 0. It does not infer real walking direction from one frame.

Default weights are density 0.5, growth 0.3 and conflict 0.2. They are configurable in `pc_prototype/config.json`.

## Risk mapping

| Index | Risk |
| --- | --- |
| `< 0.30` | NORMAL |
| `0.30–0.59` | WARNING |
| `0.60–0.79` | CROWD |
| `>= 0.80` | DANGER |

The legacy people-count safety floor can only raise a result: 8 people produces at least WARNING and 16 produces DANGER. FIRE remains reserved for future sensor thresholds.

## K230 migration

`crowd_index.py` uses only functions, numbers and dictionaries. Copy the module and the matching risk mapping to K230 after the CanMV board and firmware are confirmed; no K230 code is changed in this PC validation round.
