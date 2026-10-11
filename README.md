# ShortageSignal

An automated pipeline that tracks FDA drug recalls and drug shortages, links the two, checks the data for problems, tags each recall's root cause with AI, and flags new recalls that look like ones historically followed by a shortage.

**Status:** Batch 1, getting the data flowing. Progress is tracked under Issues and Milestones.

## Data sources
- openFDA drug enforcement reports (recalls), updated weekly
- openFDA drug shortages, updated daily
- openFDA NDC directory (added in Batch 1)

## Setup
**Recommended: GitHub Codespaces.** On the repo page, choose Code, then Codespaces, then open the codespace. Python, every package, the GitHub CLI and Claude Code install automatically from `.devcontainer/`, and nothing gets installed on your own computer.

**Local alternative:**
```
python -m venv .venv
.venv\Scripts\activate             # Mac or Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

## Day 1
```
python -m shortagesignal.pull_full_history
python -m shortagesignal.day1_explore
```

## Daily pulls (Day 2)
```
python -m shortagesignal.ingest
```
The first run loads the full recall history. After that, each run re-pulls the last 60 days of recalls and merges them in (keeping FDA's latest version plus a history of every change), saves a dated snapshot of the shortage list, and refreshes the NDC directory once a week. Data lands in `data/` as Parquet files.

## Automation (Day 3)
GitHub Actions runs the pipeline every day at 12:00 UTC. To run it by hand: Actions tab, then **Daily pipeline**, then **Run workflow**.
- **Data:** lives on the `data` branch, which always holds the latest files in one commit
- **Run log:** `run_log.csv` on the `data` branch has one row per run, with counts and any error
- **Backups:** each run's data is kept for 30 days as a download on that run's page
- **Failures:** a failed run leaves the data exactly as it was, logs the error, and GitHub emails you

## Checks
```
ruff check .
pytest
```

## How this repo works
Protected main, one branch and pull request per issue, CI on every change. See [docs/git_workflow.md](docs/git_workflow.md). Every tool choice is explained in [docs/decision_log.md](docs/decision_log.md).

## Disclaimer
Built on public openFDA data for analysis and learning. Not for medical decisions.
