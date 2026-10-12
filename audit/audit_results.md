# Hand audit results

Audited 99 of 200 sampled recalls, scored on 2026-10-12.
The audited recalls were reported between 2018-11-07 and 2026-06-10, so these results describe that period.

| What the pipeline does | Caught |
|---|---|
| Names the right drug, when it names one | 49 of 51 (96%) |
| Finds the drug, for recalls where the drug is clear | 49 of 77 (64%) |
| Finds every NDC in the description | 67 of 67 (100%), plus 0 recalls with a wrong code. 6 rows had leftover code-like numbers and were checked by hand, the rest were clear |
| Flags recalls missing a required field | nothing to score yet, plus 0 false alarms |

## Root causes (99 labeled)

| Root cause | Recalls |
|---|---|
| CGMP | 37 |
| Sterility | 27 |
| Microbial contamination | 11 |
| Chemical or foreign contamination | 6 |
| Failed specification | 4 |
| Impurities | 4 |
| Particulates | 3 |
| Labeling or packaging | 2 |
| Unapproved drug | 2 |
| Potency | 2 |
| Container or device defect | 1 |
