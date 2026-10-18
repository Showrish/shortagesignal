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

## Hand audit (Day 7)
```
python -m shortagesignal.audit sample
python -m shortagesignal.audit score
```
`sample` puts 200 random recalls (the same 200 every time) into `audit/audit_sheet.xlsx`, next to what the pipeline concluded. Fill in the yellow columns, then `score` turns the answers into `audit/answer_key.csv`, the answer key for scoring Claude, and `audit/audit_results.md`, which says how often the pipeline was right.

## Root causes (Day 8)
```
python -m shortagesignal.run_sql sql/root_cause_rules.sql
python -m shortagesignal.tagging rules
python -m shortagesignal.tagging eval
```
Every recall gets one of 12 root causes. The rules in `sql/root_cause_rules.sql` go first. Whatever they can't tag goes to Claude Haiku, which has to answer through a tool that only allows the 12 names. Each distinct reason is asked once and cached, unsure answers (low or medium confidence) land in `tag_review.csv` with one row per reason, and `tagging eval` scores the rules, Claude, and both together against the hand audit.

`run_sql` runs any SQL file against the project's tables by short name, like `FROM recalls`.

## Drug names (Day 9)
```
python -m shortagesignal.extract eval
```
Recalls that matching can't name a drug for go to Claude Haiku, which reads the product description and answers through a tool: the active ingredients by generic name, the strength, the dosage form, whether it was compounded, and how sure it is. Matching only uses the answer when Claude is fairly sure and the name is a real drug, one in the NDC directory, on the shortage list, or on a past recall. Then matching runs again, so those recalls can link to shortages. Answers that weren't used land in `extract_review.csv` with the reason, and `extract eval` scores Claude against the drugs in the hand audit.

## Risk flags and the control chart (Day 10)
```
python -m shortagesignal.risk backtest
```
About 2% of recall events since 2020 were followed within a year by a shortage FDA still lists today, usually 3 to 5 months later. Sterility recalls stand out at about three times the average. Every recall gets a risk flag from simple points (a Sterility root cause, how many companies list the drug, an injectable product), new recalls are logged with the flag they got that day, and a control chart marks weeks with unusually many recall events. The queries behind the analysis are in `sql/`.

## Dashboard (Day 11)
```
pip install -r app/requirements.txt
streamlit run app/streamlit_app.py
```
The live dashboard runs on Streamlit Community Cloud. It reads the pipeline's latest files straight from the `data` branch, at most once an hour, so it shows each daily run without being redeployed. It has the recent risk flags, the weekly control chart, and the recall-to-shortage analysis, which runs the same SQL files that are in `sql/`. Put `SHORTAGESIGNAL_DATA=local` in front of the second command to read the local `data/` folder instead.

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
