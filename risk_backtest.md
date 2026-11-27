# Risk flag backtest

Drugs reported in a recall from Jan 1, 2020 to Nov 26, 2025: 3,311, counting each drug in each recall event once. Each one's year starts on its report date, the first day a flag could exist, and only recalls with a full year since are counted, which leaves out 480 newer ones for now.

**Counting only recalls with a full year after their report fixes incomplete follow-up, not missing history. FDA's feed drops resolved shortages after a while, so older years are still undercounted, and these numbers describe this dataset, not every shortage.**

The watch flag means an injectable. High means the drug was already short, a status rather than a prediction, so it isn't backtested here. The signs were chosen by looking at this same data, so these numbers are optimistic. The honest test is the forward test on risk_log.csv.

## What counts as the same drug going short

| Definition | Recalled drugs judged | Followed | Rate, with its 95% range | Watch | Low | Lift | Watch catches |
|---|---|---|---|---|---|---|---|
| Any link: the same drug name | 3,311 | 41 | 1.2% (0.9% to 1.7%) | 1.9% | 0.9% | 1.5x | 53.7% |
| Same route: the same drug given the same way (primary) | 2,872 | 27 | 0.9% (0.6% to 1.4%) | 1.7% | 0.4% | 1.8x | 74.1% |
| Same company: the same drug from the same company | 3,311 | 4 | 0.1% (0.0% to 0.3%) | 0.0% | 0.2% | 0.0x | 0.0% |

Of 41 recalled drugs followed through any link, 27 were followed by a shortage of the same route and 4 by one from the same company. The route couldn't be read from the recall for 439 recalled drugs, so the same-route numbers leave them out rather than count them as never followed. Another 6 were linked in their year only to shortage listings whose route couldn't be read, so same route may miss a few real outcomes. Same company compares cleaned company names, so a subsidiary and its parent count as different companies, which makes it a lower bound.

## The watch flag against the simplest choices, same route, on the 2,872 recalled drugs whose route can be read

| Approach | Recalled drugs flagged | Share of the review work | Flags per week | Precision | Outcomes caught |
|---|---|---|---|---|---|
| Flag none | 0 | 0% | 0 | n/a | 0 of 27 |
| Flag every recall | 2,872 | 100% | 9.3 | 0.9% (0.6% to 1.4%) | 27 of 27 |
| Watch: an injectable | 1,152 | 40.1% | 3.7 | 1.7% (1.1% to 2.7%) | 20 of 27 |

For watch flags that were followed, the shortage was posted a median of 154 days after the recall was reported, and the middle half took 104 to 203 days.

## Consistency over time, same route

Not a holdout: the injectable rule was chosen looking at all of these years.

| Reported | Recalled drugs | Watch | Low |
|---|---|---|---|
| 2020 to 2022 | 1,581 | 2.2% | 0.6% |
| 2023 on | 1,291 | 1.2% | 0.1% |

## Dropped: root cause is Sterility, same route

| | Recalled drugs | Followed | Rate | Lift |
|---|---|---|---|---|
| yes | 739 | 10 | 1.4% | 1.4x |
| no | 2,133 | 17 | 0.8% | 0.8x |

## Why Sterility was dropped: it adds nothing within injectables, same route

| | Recalled drugs | Followed | Rate | Lift |
|---|---|---|---|---|
| sterility, injectable | 698 | 10 | 1.4% | 1.5x |
| sterility, not injectable | 41 | 0 | 0.0% | 0.0x |
| other cause, injectable | 454 | 10 | 2.2% | 2.3x |
| other cause, not injectable | 1,679 | 7 | 0.4% | 0.4x |

## Dropped: companies that make the drug, same route

| | Recalled drugs | Followed | Rate | Lift |
|---|---|---|---|---|
| 1 or 2 | 214 | 2 | 0.9% | 1.0x |
| 3 to 5 | 187 | 1 | 0.5% | 0.6x |
| 6 or more | 2,263 | 24 | 1.1% | 1.1x |
| not in the NDC directory | 208 | 0 | 0.0% | 0.0x |
