# Fresh hand labels, as first labeled

The first score, before 9 drug labels that broke the labeling rules (brand names, purpose words, a kit, typos) were fixed. The current score is in fresh_labels.md.

30 recalls labeled blind on 2026-11-02. None of them was in the first audit, so nothing was tuned on them. They were drawn as three groups of 10: root cause tagged by the rules, root cause tagged by Claude, and drug named by Claude, with at most one recall per recall event. The scores below count every recall by who actually tagged or named it, so the rows don't add up to 10 each.

## Root causes

| Tagged by | Right |
|---|---|
| Rules | 18 of 20 (90%) |
| Claude | 5 of 9 (56%) |
| All | 23 of 29 (79%) |

## Drug names

| Named by | Exact name | Ignoring salts |
|---|---|---|
| Claude | 9 of 15 (60%) | 10 of 15 (67%) |
| Matching (NDC, FDA's annotations or the text) | 6 of 12 (50%) | 8 of 12 (67%) |

The pipeline named no drug for 3 recalls where the label did. 0 recalls didn't say which drug they were, so they're left out.

## Misses

| Recall | Group | What | Label | Pipeline |
|---|---|---|---|---|
| D-0047-2015 | rules | drug | benzalkonium cl + lidocaine hydrochloride | cvs |
| D-0066-2015 | claude_drug | drug | cefazolin forte + opthalmic | cefazolin sodium |
| D-0289-2018 | rules | drug | medline suture removal | nothing |
| D-0357-2016 | rules | drug | salicylic acid | edetate calcium disodium |
| D-0457-2026 | claude_tag | drug | menthol cough suppressant | menthol flavor cough drop |
| D-0457-2026 | claude_tag | root cause | Potency | CGMP |
| D-0799-2018 | rules | drug | kisqali | ribociclib |
| D-0799-2018 | rules | root cause | Other | CGMP |
| D-0978-2022 | claude_drug | root cause | CGMP | Labeling or packaging |
| D-1226-2020 | claude_tag | drug | caffeine + ergotamine tartrate | ergotamine tartrate |
| D-1226-2020 | claude_tag | root cause | Other | CGMP |
| D-1286-2014 | claude_tag | drug | dextromethorphan + expectorant + guaifenesin | dextromethorphan hydrobromide + guaifenesin |
| D-1286-2014 | claude_tag | root cause | CGMP | Particulates |
| D-1310-2014 | claude_tag | drug | atorvastin + ezetimibe | nothing |
| D-1310-2014 | claude_tag | root cause | Labeling or packaging | Container or device defect |
| D-1363-2020 | claude_tag | drug | biotin + minoxidil + spironolactone | nothing |
| D-1522-2019 | claude_drug | drug | gericare diocto docusate sodium | docusate sodium |
| D-444-2013 | claude_drug | drug | lloyd thyro tab | levothyroxine sodium |
