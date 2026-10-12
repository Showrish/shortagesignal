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

## Matching IDs (Day 4)
Every run also builds three ID tables, so recalls and shortages can be matched:
- `recall_ids` and `shortage_ids`: every NDC found for each recall or shortage listing, from the text, FDA's openfda block, or the NDC directory for dash-less codes, plus a cleaned company name
- `ndc_directory`: one row per package in FDA's NDC directory

NDCs always come out in one format: `ndc11` for the package (like 00409-4888-10) and `ndc9` for the product (like 00409-4888).

## Matching (Day 5)
Every run matches recalls to shortages:
- `recall_drugs`: which drug each recall is about, and how we know (NDC directory, FDA's openfda block, or the drug name in the description)
- `recall_shortage_links`: every recall and shortage listing that share a drug, labeled by strength: package, product, drug and firm, or drug
- `unmatched_recalls`: recalls with no NDC and no recognizable drug name, the work queue for the AI step

Two separate numbers come out of it. **Identified** means we know which drug a recall is about. **Linked** means that drug also shows up on the shortage list. Most recalls never link, and that's normal.

## Data checks (Day 6)
Every run ends with 16 checks, before anything gets saved:
- **Errors** stop the run and keep yesterday's data: duplicate keys, a field FDA stopped sending, the recall table shrinking, the shortage list collapsing, or a badly formatted NDC. GitHub emails you
- **Warnings** let the run save but flag it on the run page: stale data, unknown statuses, a drop in the identified rate, and counts that spike or suddenly go to zero

Results land in `check_log.csv`, one row per check per run.

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
