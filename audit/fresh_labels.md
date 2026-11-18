# Fresh hand labels

30 recalls labeled blind on 2026-11-18. None of them was in the first audit, so nothing was tuned on them. They were drawn as three groups of 10: root cause tagged by the rules, root cause tagged by Claude, and drug named by Claude, with at most one recall per recall event. The scores below count every recall by who actually tagged or named it, so the rows don't add up to 10 each.

For the scores on the first audit, see tagging_results.md and extraction_results.md.

## Root causes

| Tagged by | Right |
|---|---|
| Rules | 18 of 20 (90%) |
| Claude | 5 of 9 (56%) |
| All | 23 of 29 (79%) |

## Drug names

Recall text often leaves the salt off, so the second column counts fentanyl and fentanyl citrate as the same drug.

| Named by | Exact name | Ignoring salts |
|---|---|---|
| Claude | 12 of 15 (80%) | 15 of 15 (100%) |
| Matching (NDC, FDA's annotations or the text) | 7 of 12 (58%) | 9 of 12 (75%) |

The pipeline named no drug for 2 recalls where the label did. 1 recalls didn't say which drug they were, so they're left out.

## Misses

| Recall | Group | What | Label | Pipeline |
|---|---|---|---|---|
| D-0047-2015 | rules | drug | benzalkonium chloride + lidocaine hydrochloride | cvs |
| D-0457-2026 | claude_tag | drug | menthol | menthol flavor cough drop |
| D-0457-2026 | claude_tag | root cause | Potency | CGMP |
| D-0799-2018 | rules | root cause | Other | CGMP |
| D-0978-2022 | claude_drug | root cause | CGMP | Labeling or packaging |
| D-1226-2020 | claude_tag | drug | caffeine + ergotamine tartrate | ergotamine tartrate |
| D-1226-2020 | claude_tag | root cause | Other | CGMP |
| D-1286-2014 | claude_tag | root cause | CGMP | Particulates |
| D-1310-2014 | claude_tag | drug | atorvastatin + ezetimibe | nothing |
| D-1310-2014 | claude_tag | root cause | Labeling or packaging | Container or device defect |
| D-1363-2020 | claude_tag | drug | biotin + minoxidil + spironolactone | nothing |

## Label fixes

After the first score, 10 drug labels were fixed. 9 broke the labeling rules: brand names given instead of generic names, purpose words like expectorant, a kit with no drug named, and typos. 1 named the wrong drug: D-0357-2016's product text says EDTA Calcium Disodium, which is edetate, and it was labeled salicylic acid, so the pipeline's answer, which the score had counted wrong, was right. Each fixed row says so in its notes, and the first score is kept in fresh_labels_as_labeled.md. Root causes were left exactly as labeled, since changing judgment calls after seeing the pipeline's answers would bias the score.
