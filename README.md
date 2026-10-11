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

## Checks
```
ruff check .
pytest
```

## How this repo works
Protected main, one branch and pull request per issue, CI on every change. See [docs/git_workflow.md](docs/git_workflow.md). Every tool choice is explained in [docs/decision_log.md](docs/decision_log.md).

## Disclaimer
Built on public openFDA data for analysis and learning. Not for medical decisions.
