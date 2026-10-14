# Drug extraction results

Scored against the 74 audited recalls where the drug is clear. Claude only runs when matching names no drug, so the pipeline's own answer always wins. Recall text often leaves the salt off, so the second column counts fentanyl and fentanyl citrate as the same drug.

| | Exact name | Ignoring salts |
|---|---|---|
| Finds the drug, before Claude | 48 of 74 (65%) | 48 of 74 (65%) |
| Finds the drug, with Claude | 58 of 74 (78%) | 61 of 74 (82%) |
| Claude alone, before any checks | 48 of 74 (65%) | 70 of 74 (95%) |

On the 23 recalls matching couldn't name, ignoring salts, Claude's checked answer was right for 13, wrong for 0, and not used for 10 (no drug named, low confidence, or not a known drug).

## Claude by confidence, before the checks

| Confidence | Exact name | Ignoring salts |
|---|---|---|
| high | 43 of 61 (70%) | 58 of 61 (95%) |
| medium | 5 of 13 (38%) | 12 of 13 (92%) |

Model: claude-haiku-5-5. This run's new calls cost about $0.0000.
