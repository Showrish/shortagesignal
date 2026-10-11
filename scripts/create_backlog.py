"""
One-time setup: create the project backlog on GitHub.

Creates 7 labels, 4 milestones (the batches) and 14 issues (the tasks).
Safe to re-run: anything that already exists is skipped.
Run it BEFORE opening any pull request, so the issues get numbers 1 to 14.

Needs the GitHub CLI, logged in:  gh auth login
Run from inside the repo folder:  python scripts/create_backlog.py
"""
import json
import shutil
import subprocess
import sys

LABELS = {
    "data": ("1D76DB", "Pulling, storing and cleaning data"),
    "pipeline": ("5319E7", "Scheduling and automation"),
    "quality": ("D93F0B", "Data quality checks and audits"),
    "ai": ("0E8A16", "Claude tagging and extraction"),
    "analysis": ("FBCA04", "Patterns, stats and findings"),
    "dashboard": ("0052CC", "Streamlit, email and reports"),
    "docs": ("0075CA", "README, runbook and write-ups"),
}

B1 = "Batch 1: Get the data flowing"
B2 = "Batch 2: Make the data trustworthy"
B3 = "Batch 3: Add AI and find the patterns"
B4 = "Batch 4: Show it and ship it"
MILESTONES = {
    B1: "Pull FDA data automatically and keep a daily history",
    B2: "Clean, match and check the data, plus a hand-audited answer key",
    B3: "Root-cause tagging, gap filling, risk flags and control charts",
    B4: "Live dashboard, weekly email, docs and the v1.0.0 release",
}

# (title, label, milestone, "done when" checklist)
ISSUES = [
    ("Pull the full recall history and shortage list into DuckDB", "data", B1, [
        "Both raw tables load from openFDA",
        "day1_explore output reviewed",
        "Shortage date range and NDC coverage written into the decision log",
    ]),
    ("Daily incremental pulls for recalls, shortages and the NDC directory", "data", B1, [
        "Only new recalls get added on each run",
        "Each day's shortage list saved as a dated snapshot with first-seen and last-seen dates",
        "NDC directory pulled and refreshed weekly",
    ]),
    ("Run the pipeline daily with GitHub Actions", "pipeline", B1, [
        "Scheduled workflow runs with no laptop involved",
        "Each run writes a run log row (time, rows in, status)",
        "Data lands on the data branch, never on main",
    ]),
    ("Extract and normalize NDCs and clean firm names", "data", B2, [
        "NDCs pulled from recall text and converted to the 11-digit format",
        "Firm names standardized",
        "Unit tests cover every NDC layout",
    ]),
    ("Match recalls to shortages and audit the match rate", "data", B2, [
        "Match by NDC first, then drug name, strength and firm",
        "Match rate reported on every run",
        "Unmatched recalls kept in their own table",
    ]),
    ("Data quality checks with alerts", "quality", B2, [
        "Checks for duplicates, missing values, malformed NDCs, schema changes and stale data",
        "A failed check stops the run and sends an email",
        "Check counts logged, with an alert when a check suddenly flags zero or spikes",
    ]),
    ("Hand-audit 200 random recalls", "quality", B2, [
        "200 random recalls reviewed by hand for data problems and root cause",
        "Answer key saved in the repo",
        "Checks compared against the answer key, with the caught X of Y result recorded",
    ]),
    ("Root-cause tagging: rules first, Claude Haiku for the rest", "ai", B3, [
        "Rules tag the standard reason labels",
        "Claude Haiku tags the rest with a category and a confidence score",
        "Accuracy scored against the answer key",
        "Low-confidence tags go to a review sheet",
    ]),
    ("Claude extraction for recalls without an NDC", "ai", B3, [
        "Drug name, strength and dosage form extracted from the product text",
        "Match rate before and after recorded",
    ]),
    ("Recall-to-shortage analysis, risk flags and control chart", "analysis", B3, [
        "Lag from recall to shortage by root cause",
        "Maker counts from the NDC directory",
        "Risk flag on each new recall",
        "Control chart on weekly recall counts",
    ]),
    ("Streamlit dashboard live", "dashboard", B4, [
        "Public link on Streamlit Community Cloud",
        "Updates itself after every pipeline run",
    ]),
    ("Weekly digest email, Excel exception list and Power BI report", "dashboard", B4, [
        "Weekly email with a plain-English summary",
        "Excel list of items that need a look",
        "Power BI report on the same tables",
    ]),
    ("Docs: README, runbook, data dictionary, AI eval and limitations", "docs", B4, [
        "README with findings and the live link",
        "Runbook, data dictionary, AI eval write-up and limitations",
    ]),
    ("Polish and release v1.0.0", "docs", B4, [
        "CHANGELOG updated and the v1.0.0 release published",
        "Optional: Claude vs Luna benchmark",
    ]),
]


def gh(*args, check=True):
    """Run a GitHub CLI command and return the result."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed:\n{result.stderr}")
    return result


def main():
    if not shutil.which("gh"):
        sys.exit("GitHub CLI not found. Install it from https://cli.github.com, then run: gh auth login")
    if gh("auth", "status", check=False).returncode != 0:
        sys.exit("GitHub CLI is not logged in. Run: gh auth login")

    print("Labels")
    for name, (color, desc) in LABELS.items():
        gh("label", "create", name, "--color", color, "--description", desc, "--force")
        print(f"  {name}")

    print("Milestones")
    found = json.loads(gh("api", "repos/{owner}/{repo}/milestones?state=all").stdout)
    existing = {m["title"] for m in found}
    for title, desc in MILESTONES.items():
        if title in existing:
            print(f"  already there: {title}")
            continue
        gh("api", "repos/{owner}/{repo}/milestones", "-f", f"title={title}", "-f", f"description={desc}")
        print(f"  created: {title}")

    print("Issues")
    found = json.loads(gh("issue", "list", "--state", "all", "--limit", "500", "--json", "title").stdout)
    existing = {i["title"] for i in found}
    for title, label, milestone, done in ISSUES:
        if title in existing:
            print(f"  already there: {title}")
            continue
        body = "## Done when\n" + "\n".join(f"- [ ] {item}" for item in done)
        url = gh("issue", "create", "--title", title, "--body", body,
                 "--label", label, "--milestone", milestone).stdout.strip()
        print(f"  {url}")

    print("\nBacklog ready. See it under the Issues and Milestones tabs on GitHub.")


if __name__ == "__main__":
    main()
