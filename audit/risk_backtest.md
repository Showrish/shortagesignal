# Risk flag backtest

Recall events since 2020: 2,133. Followed within a year by a shortage FDA still lists: 40 (1.9%). Lift is each group's rate divided by that average.

The Sterility points came from this same data, so these numbers are optimistic. The honest test is risk_log.csv: flags given on the day a recall was reported, checked against shortages that come later.

## Flag

| | Events | Followed | Rate | Lift |
|---|---|---|---|---|
| high | 79 | 6 | 7.6% | 4.0x |
| watch | 314 | 12 | 3.8% | 2.0x |
| low | 1,740 | 22 | 1.3% | 0.7x |

## Root cause is Sterility

| | Events | Followed | Rate | Lift |
|---|---|---|---|---|
| yes | 210 | 13 | 6.2% | 3.3x |
| no | 1,923 | 27 | 1.4% | 0.7x |

## Labelers in the NDC directory

| | Events | Followed | Rate | Lift |
|---|---|---|---|---|
| 1 or 2 | 204 | 9 | 4.4% | 2.4x |
| 3 to 5 | 133 | 3 | 2.3% | 1.2x |
| 6 or more | 1,637 | 28 | 1.7% | 0.9x |
| unknown drug | 159 | 0 | 0.0% | 0.0x |

## Injectable

| | Events | Followed | Rate | Lift |
|---|---|---|---|---|
| yes | 536 | 26 | 4.9% | 2.6x |
| no | 1,597 | 14 | 0.9% | 0.5x |
