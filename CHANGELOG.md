# Changelog

Every notable change, newest first. Each release moves the Unreleased items under its version.

## [Unreleased]

## [0.3.0] - 2026-10-16
### Added
- Root-cause tagging for every recall: SQL rules first, Claude Haiku for the rest, scored against the hand audit
- Claude names the drug for recalls matching can't, checked against known drug names, with before and after match rates
- Recall-to-shortage analysis by root cause, counted by recall event
- A risk flag on every recall, maker counts from the NDC directory, and a control chart on weekly recall events
- A Pipeline numbers table on the run page

### Added
- Root-cause tagging: SQL rules first, Claude Haiku for the rest, cached answers, a review list, and an evaluation against the hand audit

## [0.2.0] - 2026-10-12
### Added
- Matching IDs: NDCs normalized to 11 digits from text, openfda and the NDC directory, plus firm keys
- Matching: a drug identity for every recall, links to shortages at four strengths, and an unmatched recalls table
- Data checks: 16 checks per run. Errors stop the run, warnings show on the run page, and the history goes to check_log.csv
- Hand audit tool: a 200-recall review sheet, and scoring that turns it into an answer key

## [0.1.0] - 2026-10-11
### Added
- Project setup: package layout, CI with linting and tests, pull request template, git workflow, backlog script
- Dev container, so the project opens ready to use in GitHub Codespaces
- Day 1 modules to pull the full recall history and shortage list, and to explore them
- Day 1 data findings in the decision log
- Daily ingestion: recalls merged from a 60-day window with a version history, dated shortage snapshots, weekly NDC directory refresh
- Daily GitHub Actions run with a data branch, run log, 30-day backups and all-or-nothing updates
