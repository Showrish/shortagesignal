# Risk log check

The forward test of the risk flag, checked on Nov 17, 2026. Every new recall is logged with the flag it got on the day it was reported, before anyone could know what came next, and this checks those flags against shortages of the same drug that FDA posted afterward. Nothing here was tuned on.

It counts the way the backtest does: one drug in one recall event, so a pharmacy recalling 40 drugs at once counts as 40. A drug counts as followed when FDA posts a shortage listing of it after the flag and within 365 days. Rates only use flags that have had their full 365 days, since a hit is known sooner than a miss.

**Too early to judge.** A flag needs its full year before it counts, and not enough watch and low flags have had theirs. The first ones finish on Oct 27, 2027.

## Flags under the current points, since Oct 26, 2026

| Flag | Recalled drugs | Full year done | Followed | Rate, with its 95% range | Still in their year | Followed already |
|---|---|---|---|---|---|---|
| high | 1 | 0 | 0 | not yet | 1 | 0 |
| watch | 8 | 0 | 0 | not yet | 8 | 0 |
| low | 23 | 0 | 0 | not yet | 23 | 0 |

## By how long after the flag

Each row only counts the flags old enough to have finished it. Lead time is reported on its own, below, since a horizon says how many were followed, not how early.

| Days after the flag | Watch | Low | High |
|---|---|---|---|
| 30 | none done yet | none done yet | none done yet |
| 90 | none done yet | none done yet | none done yet |
| 180 | none done yet | none done yet | none done yet |
| 365 | none done yet | none done yet | none done yet |

**Lead time:** no flag has been followed yet.

For comparison, the backtest on recalls since 2020 expects about 1.9% for watch and 0.9% for low, counted the same way as here, through any link of the same drug name.

High means the drug was already on FDA's shortage list when it was flagged, so it's a status, not a prediction. For high, followed means another listing of the same drug was posted after the flag.

## Followed so far

None yet.

## Before Oct 26, 2026

43 recalled drugs were flagged under the old points, which counted sterility and few makers, and 0 have been followed so far. They're kept for the record, not used to judge the current flag.

27 logged recalls have no drug name, so they can't be matched to a shortage of the same drug, and they're left out.

32 recalled drugs were logged before the drug and event were saved with each flag, so they're judged on today's name. Every flag logged since is judged on the name it had that day.
