# Changelog

Every notable change, newest first. Each release moves the Unreleased items under its version.

## [Unreleased]
### Changed
- Every daily run works out the risk flag's backtest and saves it to the data branch, so the dashboard and the digest always quote today's numbers

## [1.0.0] - 2026-11-08
### Added
- A live Streamlit dashboard: risk flags, the weekly control chart, what follows a recall, and an About tab
- Ask the data: Claude writes one read-only SQL query over a locked, in-memory copy of six tables and answers from the rows, with the query shown. It sits behind a passcode with 50 questions a day, on its own key with a spend limit, and is scored on 18 test questions
- A weekly digest every Monday, posted as a GitHub issue, with an Excel list of what needs a person's look and a Keeping it running section for credits, key expiry and paused schedules
- A Power BI report on the pipeline's tables, saved as a Power BI project so git tracks it
- Fresh hand labels: 30 recalls labeled blind, none of them tuned on, with tools to draw and score them
- The forward test of the risk flag, `python -m shortagesignal.risk check-log`, which the Monday digest also reports
- A data dictionary built from the real files, so it can't drift
- A workflow that keeps the dashboard awake on Streamlit's free tier
- Docs: a README rewrite with the findings, a runbook, AI evals and limitations
- Evidence queries for the risk flag, with 95% ranges and the strength of each link

### Changed
- The analysis and the backtest count one drug in one recall event instead of one recall event. That cut sterility from about 3 times the average to about 1.3 times, and the old high flag from about 4 times to none
- The risk flag: high now means the drug is on FDA's shortage list right now, and watch means an injectable, the one sign that held up
- Claude's drug name for a combination is used when every part is a known drug, which took recalls with a drug name from 76% to 83%
- The dashboard and the digest quote the latest backtest instead of numbers typed in by hand
- The Risk flags tab shows what each flag means and leads with the drug, the firm and why it was flagged

### Removed
- The sterility and maker-count points from the risk flag. Both are still shown as facts and reported in the backtest

### Fixed
- Ask the data connects recalls and shortages through the links table, after its first live question came back empty
- Eye drops in vials no longer count as injectables

## [0.3.0] - 2026-10-16
### Added
- Root-cause tagging for every recall: SQL rules first, Claude Haiku for the rest, scored against the hand audit
- Claude names the drug for recalls matching can't, checked against known drug names, with before and after match rates
- Recall-to-shortage analysis by root cause, counted by recall event
- A risk flag on every recall, maker counts from the NDC directory, and a control chart on weekly recall events
- A Pipeline numbers table on the run page

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
