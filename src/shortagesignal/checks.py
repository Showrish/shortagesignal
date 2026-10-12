"""
Day 6: data checks. They run at the end of every run, on the staged files, before
anything gets saved.

  error    something is broken: duplicates, a field FDA stopped sending, the recall
           table shrinking, the shortage list collapsing, a badly formatted NDC.
           The run stops, yesterday's data stays, and GitHub emails you.
  warning  something looks off: stale data, an unknown status, a spike, or a count that
           suddenly drops to zero. The run still saves, and the warning shows on the
           run page and in check_log.csv.

Every check writes one row per run to check_log.csv, which is also the history the
spike and "went silent" rules compare against.
"""
import csv
import os
from dataclasses import dataclass
from datetime import date
from statistics import median

KNOWN_STATUSES = {"Current", "Resolved", "To Be Discontinued", "Discontinued"}
RECALL_FIELDS = ["recall_number", "report_date", "classification", "product_description",
                 "recalling_firm", "reason_for_recall"]
SHORTAGE_FIELDS = ["generic_name", "company_name", "status", "package_ndc",
                   "initial_posting_date", "update_date"]
CHECK_LOG_COLUMNS = ["run_at_utc", "check", "severity", "value", "status", "detail"]
NDC11_RE = r"\d{5}-\d{4}-\d{2}"
NDC9_RE = r"\d{5}-\d{4}"
STATUS_LIST = ", ".join(f"'{s}'" for s in sorted(KNOWN_STATUSES))


class DataCheckError(Exception):
    """One or more error-level checks failed."""


@dataclass
class Check:
    name: str
    severity: str   # "error" or "warning"
    value: float
    ok: bool
    detail: str = ""

    @property
    def status(self):
        if self.ok:
            return "pass"
        return "fail" if self.severity == "error" else "warn"


# ---------------------------------------------------------------- history rules

def history_flag(value, previous):
    """'spike' if value jumped well above its usual level, 'silent' if a count that is
    normally above zero dropped to zero, otherwise None. Needs a few earlier runs first."""
    if len(previous) >= 5 and all(v > 0 for v in previous[-5:]) and value == 0:
        return "silent"
    if len(previous) >= 3:
        usual = median(previous[-7:])
        if value > 2 * usual and value - usual > 20:
            return "spike"
    return None


def read_history(path):
    """Earlier values per check name from check_log.csv."""
    history = {}
    if not path.exists():
        return history
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                history.setdefault(row["check"], []).append(float(row["value"]))
            except (KeyError, ValueError):
                continue
    return history


def last_good_run(run_log_path):
    """The most recent successful row of run_log.csv, or {} if there isn't one."""
    if not run_log_path.exists():
        return {}
    with open(run_log_path, newline="", encoding="utf-8") as f:
        good = [row for row in csv.DictReader(f) if row.get("status") == "success"]
    return good[-1] if good else {}


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the checks

def _columns(con, path):
    return set(con.sql(f"SELECT * FROM read_parquet('{path}') LIMIT 0").columns)


def _fields_gone_empty(con, path, fields, where):
    """Required fields that came back completely empty in this run's rows."""
    present = _columns(con, path)
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{path}') WHERE {where}").fetchone()[0]
    if rows == 0:
        return [], rows
    gone = []
    for field in fields:
        if field not in present:
            gone.append(field)
            continue
        filled = con.execute(f"""
            SELECT count(*) FROM read_parquet('{path}')
            WHERE {where} AND nullif(trim(CAST("{field}" AS VARCHAR)), '') IS NOT NULL
        """).fetchone()[0]
        if filled == 0:
            gone.append(field)
    return gone, rows


def collect_checks(con, f, stats, state, today, now, previous_run, history):
    """f maps names to staged file paths. Returns a list of Check results."""
    p = {name: path.as_posix() for name, path in f.items()}
    day = f"DATE '{today.isoformat()}'"
    this_batch = f"_pulled_at = TIMESTAMP '{now:%Y-%m-%d %H:%M:%S}'"
    checks = []

    # ---- errors: the data would be wrong if we saved it
    dupes = con.execute(
        f"SELECT count(*) - count(DISTINCT recall_number) FROM read_parquet('{p['recalls']}')"
    ).fetchone()[0]
    checks.append(Check("recall numbers are unique", "error", dupes, dupes == 0,
                        f"{dupes} duplicate recall numbers" if dupes else ""))

    dupes = con.execute(f"""
        SELECT count(*) - count(DISTINCT shortage_key) FROM read_parquet('{p['snapshots']}')
        WHERE snapshot_date = {day}
    """).fetchone()[0]
    checks.append(Check("shortage keys are unique today", "error", dupes, dupes == 0,
                        f"{dupes} duplicate shortage keys" if dupes else ""))

    gone, _ = _fields_gone_empty(con, p["recalls"], RECALL_FIELDS, this_batch)
    checks.append(Check("recall fields still arriving", "error", len(gone), not gone,
                        "came back empty: " + ", ".join(gone) if gone else ""))

    gone, today_rows = _fields_gone_empty(con, p["snapshots"], SHORTAGE_FIELDS,
                                          f"snapshot_date = {day}")
    checks.append(Check("shortage fields still arriving", "error", len(gone), not gone,
                        "came back empty: " + ", ".join(gone) if gone else ""))

    before = _number(previous_run.get("recalls_total"))
    total = stats.get("recalls_total", 0)
    shrunk = before is not None and total < before
    checks.append(Check("recall table never shrinks", "error", total, not shrunk,
                        f"went from {before:,.0f} to {total:,}" if shrunk else ""))

    before = _number(previous_run.get("shortage_rows"))
    collapsed = before is not None and today_rows < 0.5 * before
    checks.append(Check("shortage list didn't collapse", "error", today_rows, not collapsed,
                        f"{today_rows:,} rows today vs {before:,.0f} last run" if collapsed else ""))

    bad = 0
    for name in ("recall_ids", "shortage_ids", "ndc_directory"):
        bad += con.execute(f"""
            SELECT count(*) FROM read_parquet('{p[name]}')
            WHERE (ndc11 IS NOT NULL AND NOT regexp_full_match(ndc11, '{NDC11_RE}'))
               OR (ndc9 IS NOT NULL AND NOT regexp_full_match(ndc9, '{NDC9_RE}'))
        """).fetchone()[0]
    checks.append(Check("NDCs are well formed", "error", bad, bad == 0,
                        f"{bad} badly formatted NDCs" if bad else ""))

    # ---- warnings: worth a look, but the data is still fine to save
    latest = con.execute(f"""
        SELECT max(try_strptime(report_date, '%Y%m%d')) FROM read_parquet('{p['recalls']}')
    """).fetchone()[0]
    days = (today - latest.date()).days if latest else None
    checks.append(Check("recalls are fresh", "warning", days if days is not None else -1,
                        days is not None and days <= 14,
                        f"newest recall report is {days} days old" if days is not None and days > 14
                        else ("no readable report dates" if days is None else "")))

    latest = con.execute(f"""
        SELECT max(try_strptime(update_date, '%m/%d/%Y')) FROM read_parquet('{p['snapshots']}')
        WHERE snapshot_date = {day}
    """).fetchone()[0]
    days = (today - latest.date()).days if latest else None
    checks.append(Check("shortage list is fresh", "warning", days if days is not None else -1,
                        days is not None and days <= 14,
                        f"newest shortage update is {days} days old" if days is not None and days > 14
                        else ("no readable update dates" if days is None else "")))

    refreshed = state.get("ndc_refreshed")
    days = (today - date.fromisoformat(refreshed)).days if refreshed else None
    checks.append(Check("NDC directory is fresh", "warning", days if days is not None else -1,
                        days is not None and days <= 10,
                        f"last refreshed {days} days ago" if days is not None and days > 10
                        else ("never refreshed" if days is None else "")))

    unknown = con.execute(f"""
        SELECT count(*) FROM read_parquet('{p['snapshots']}')
        WHERE snapshot_date = {day} AND status NOT IN ({STATUS_LIST})
    """).fetchone()[0]
    checks.append(Check("shortage statuses are known", "warning", unknown, unknown == 0,
                        f"{unknown} rows with a status we haven't seen before" if unknown else ""))

    before = _number(previous_run.get("recalls_identified_pct"))
    now_pct = stats.get("recalls_identified_pct")
    dropped = before is not None and now_pct is not None and now_pct < before - 5
    checks.append(Check("identified rate is steady", "warning", now_pct or 0, not dropped,
                        f"dropped from {before}% to {now_pct}%" if dropped else ""))

    # ---- tracked counts: warn on a spike, or when a normally busy count goes quiet
    present = _columns(con, p["recalls"])
    empty_field = " OR ".join(f"nullif(trim(CAST(\"{c}\" AS VARCHAR)), '') IS NULL"
                              for c in RECALL_FIELDS if c in present) or "false"
    missing = con.execute(f"""
        SELECT count(*) FROM read_parquet('{p['recalls']}')
        WHERE {this_batch} AND ({empty_field})
    """).fetchone()[0]
    tracked = {
        "recalls pulled": stats.get("recalls_pulled", 0),
        "shortage rows": today_rows,
        "unmatched recalls": stats.get("recalls_unmatched", 0),
        "recalls missing a field": missing,
    }
    for name, value in tracked.items():
        previous = history.get(name, [])
        flag = history_flag(value, previous)
        detail = ""
        if flag == "spike":
            detail = f"jumped to {value:,} from a usual {median(previous[-7:]):,.0f}"
        elif flag == "silent":
            detail = "dropped to 0 after being above 0 every recent run"
        checks.append(Check(name, "warning", value, flag is None, detail))
    return checks


# ---------------------------------------------------------------- reporting

def report(checks, check_log_path, run_at):
    """Log every check, show them on the GitHub run page, and stop the run on a failed error."""
    new_file = not check_log_path.exists()
    with open(check_log_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CHECK_LOG_COLUMNS)
        if new_file:
            writer.writeheader()
        for c in checks:
            writer.writerow({"run_at_utc": run_at, "check": c.name, "severity": c.severity,
                             "value": c.value, "status": c.status, "detail": c.detail})

    failed = [c for c in checks if c.status == "fail"]
    warned = [c for c in checks if c.status == "warn"]
    print(f"Checks: {len(checks) - len(failed) - len(warned)} passed, "
          f"{len(warned)} warnings, {len(failed)} failed")
    for c in failed + warned:
        level = "error" if c.status == "fail" else "warning"
        print(f"  {c.status.upper()}: {c.name}: {c.detail}")
        if os.getenv("GITHUB_ACTIONS"):
            print(f"::{level} title=Data check: {c.name}::{c.detail}")

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Data checks\n\n| | Check | Value | Detail |\n|---|---|---|---|\n")
            for c in checks:
                fh.write(f"| {icon[c.status]} | {c.name} | {c.value:g} | {c.detail} |\n")

    if failed:
        raise DataCheckError(f"{len(failed)} data check(s) failed: "
                             + "; ".join(f"{c.name} ({c.detail})" for c in failed))
    return len(warned)
