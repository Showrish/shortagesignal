# Risk flag backtest

Drugs recalled since 2020: 3,421, counting each drug in each recall event once. Followed within a year by a shortage of the same drug that FDA still lists: 45 (1.3%). Lift is each group's rate divided by that average.

High means the recalled drug is on FDA's shortage list right now. That's a status, not a prediction, so it isn't backtested here. Watch means an injectable. The signs were chosen by looking at this same data, so these numbers are optimistic. The honest test is risk_log.csv: flags given on the day a recall was reported, checked against shortages that come later.

## Flag: watch is an injectable

| | Recalled drugs | Followed | Rate | Lift |
|---|---|---|---|---|
| watch | 1,091 | 23 | 2.1% | 1.6x |
| low | 2,330 | 22 | 0.9% | 0.7x |

## Dropped: root cause is Sterility

| | Recalled drugs | Followed | Rate | Lift |
|---|---|---|---|---|
| yes | 735 | 14 | 1.9% | 1.4x |
| no | 2,686 | 31 | 1.2% | 0.9x |

## Why Sterility was dropped: it adds nothing within injectables

| | Recalled drugs | Followed | Rate | Lift |
|---|---|---|---|---|
| sterility, injectable | 591 | 13 | 2.2% | 1.7x |
| sterility, not injectable | 144 | 1 | 0.7% | 0.5x |
| other cause, injectable | 500 | 10 | 2.0% | 1.5x |
| other cause, not injectable | 2,186 | 21 | 1.0% | 0.7x |

## Dropped: companies that make the drug

| | Recalled drugs | Followed | Rate | Lift |
|---|---|---|---|---|
| 1 or 2 | 321 | 2 | 0.6% | 0.5x |
| 3 to 5 | 246 | 1 | 0.4% | 0.3x |
| 6 or more | 2,852 | 42 | 1.5% | 1.1x |
| not in the NDC directory | 2 | 0 | 0.0% | 0.0x |
