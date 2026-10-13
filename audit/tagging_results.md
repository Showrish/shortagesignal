# Root-cause tagging results

Scored against the 99 hand-labeled audit recalls.

| Tagger | Tags | Right |
|---|---|---|
| Rules (sql/root_cause_rules.sql) | 99 of 99 | 99 of 99 (100%) |
| Claude alone | 99 of 99 | 97 of 99 (98%) |
| Claude, on the recalls the rules couldn't tag | 0 of 0 | 0 of 0 (n/a) |
| Rules first, then Claude | 99 of 99 | 99 of 99 (100%) |

## Claude by confidence

| Confidence | Right |
|---|---|
| high | 87 of 87 (100%) |
| medium | 10 of 12 (83%) |

Model: claude-haiku-5-5. This run's new calls cost about $0.0226.
