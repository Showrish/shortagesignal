"""
Day 10: a risk flag on every recall, maker counts, and a control chart on weekly recalls.

  python -m shortagesignal.risk backtest    how the flag does on drugs recalled since 2020

The flag isn't a trained model. Only a few percent of drugs recalled since 2020 were followed
within a year by a shortage of the same drug that FDA still lists, too few for a model to
learn from. Instead each recall gets points for the signs that the analysis and the shortage
research point to:
  2  the root cause is Sterility (well above the average rate, see sql/lag_by_root_cause.sql)
  2  only 1 or 2 companies list the drug in the NDC directory, or 1 point for 3 to 5
  1  the product is an injectable (vial, syringe, infusion)
4 points or more is high, 2 or 3 is watch, and the rest is low. The backtest reports how
often each level was followed by a shortage, compared with the average.

The backtest's unit is one drug in one recall event, the same as sql/lag_by_root_cause.sql:
a shortage happens to a drug, so the question is whether this drug went short after this
recall. Its lifts are also saved to audit/risk_backtest.json, which the dashboard and the
weekly digest quote, so their numbers always match the latest backtest.

Companies are counted from the NDC directory, leaving out ones that call themselves
repackagers or relabelers. Repackagers that don't say so still count, so common drugs come
out high, which only makes the flag more cautious.

New recalls go into risk_log.csv with the flag they got on the day they were reported, so
later runs can check the flag on recalls it has never seen.

The control chart counts recall events per week by FDA report date. Its limits come from
the two years before the last 13 weeks, using the moving-range method (an XmR chart), which
copes better than a Poisson c-chart with weeks that vary a lot.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import duckdb

from shortagesignal.config import (
    NDC_PATH,
    RECALL_DRUGS_PATH,
    RECALLS_PATH,
    ROOT,
    ROOT_CAUSES_PATH,
)
from shortagesignal.drugs import drug_key
from shortagesignal.firms import firm_key
from shortagesignal.run_sql import read_query
from shortagesignal.storage import load_batch, write_parquet

WEEKLY_SQL = ROOT / "sql" / "weekly_recall_events.sql"
BACKTEST_RESULTS = ROOT / "audit" / "risk_backtest.md"
BACKTEST_JSON = ROOT / "audit" / "risk_backtest.json"
INJECTABLE = re.compile(r"inject|syringe|infusion|intraven|ampul|\bi\.?v\.?\b", re.I)
VIAL = re.compile(r"\bvials?\b", re.I)
# Eye drops and the like often come in single-use vials, but they aren't injected.
NOT_INJECTED = re.compile(r"ophthalmic|\beyes?\b|\botic\b|\bears?\b|nasal|inhal", re.I)
REPACKAGER = re.compile(r"repack|relabel", re.I)
RISK_COLUMNS = ["recall_number", "event_id", "report_date", "recall_class", "root_cause",
                "drug_key", "labelers", "injectable", "points", "flag", "reasons"]
LOG_COLUMNS = ["recall_number", "report_date", "flagged_on", "flag", "points", "reasons"]
WEEKLY_COLUMNS = ["week", "events", "recalls", "center", "ucl", "lcl", "signal"]
LEVELS = ["high", "watch", "low"]


# ---------------------------------------------------------------- the flag

def is_injectable(description):
    if not description:
        return False
    if INJECTABLE.search(description):
        return True
    return bool(VIAL.search(description)) and not NOT_INJECTED.search(description)


def score_recall(root_cause, labelers, injectable):
    """(points, flag, reasons) for one recall. labelers is None when the drug is unknown."""
    points, reasons = 0, []
    if root_cause == "Sterility":
        points += 2
        reasons.append("sterility")
    if labelers is not None and labelers <= 2:
        points += 2
        reasons.append(f"{labelers} labeler" + ("" if labelers == 1 else "s"))
    elif labelers is not None and labelers <= 5:
        points += 1
        reasons.append(f"{labelers} labelers")
    if injectable:
        points += 1
        reasons.append("injectable")
    flag = "high" if points >= 4 else "watch" if points >= 2 else "low"
    return points, flag, ", ".join(reasons)


def drug_labelers(con, ndc_path):
    """Drug key -> how many companies list it in the NDC directory, without obvious repackagers."""
    firms = defaultdict(set)
    for generic, labeler in con.execute(
        f"SELECT generic_name, labeler_name FROM read_parquet('{ndc_path}')"
    ).fetchall():
        key, firm = drug_key(generic), firm_key(labeler)
        if key and firm and not REPACKAGER.search(labeler):
            firms[key].add(firm)
    return {key: len(names) for key, names in firms.items()}


def _parse_day(text):
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except (TypeError, ValueError):
        return None


def build_risk(recalls_path, root_causes_path, recall_drugs_path, ndc_path, risk_path,
               makers_path, log_path, workdir, today):
    """Score every recall, save the maker counts, and log the flags of newly reported recalls."""
    con = duckdb.connect()
    labelers = drug_labelers(con, ndc_path.as_posix())
    load_batch(con, [{"drug_key": k, "labelers": str(n)} for k, n in sorted(labelers.items())],
               ["drug_key", "labelers"], "makers", workdir)
    write_parquet(con, "SELECT drug_key, CAST(labelers AS INTEGER) AS labelers FROM makers "
                       "ORDER BY labelers, drug_key", makers_path)

    rows = con.execute(f"""
        SELECT r.recall_number, r.event_id, r.report_date, r.classification,
               r.product_description, c.root_cause, d.drug_key
        FROM read_parquet('{recalls_path.as_posix()}') r
        LEFT JOIN read_parquet('{root_causes_path.as_posix()}') c ON c.recall_number = r.recall_number
        LEFT JOIN read_parquet('{recall_drugs_path.as_posix()}') d ON d.recall_number = r.recall_number
        ORDER BY r.recall_number
    """).fetchall()
    scored = []
    for number, event_id, report_date, recall_class, description, root_cause, key in rows:
        n = labelers.get(key) if key else None
        injectable = is_injectable(description)
        points, flag, reasons = score_recall(root_cause, n, injectable)
        scored.append({"recall_number": number, "event_id": event_id, "report_date": report_date,
                       "recall_class": recall_class, "root_cause": root_cause, "drug_key": key,
                       "labelers": None if n is None else str(n),
                       "injectable": "true" if injectable else "false",
                       "points": str(points), "flag": flag, "reasons": reasons})
    load_batch(con, scored, RISK_COLUMNS, "recall_risk", workdir)
    write_parquet(con, """
        SELECT recall_number, event_id, report_date, recall_class, root_cause, drug_key,
               CAST(labelers AS INTEGER) AS labelers, CAST(injectable AS BOOLEAN) AS injectable,
               CAST(points AS INTEGER) AS points, flag, reasons
        FROM recall_risk ORDER BY recall_number
    """, risk_path)

    # Recalls reported in the last 30 days go into the log once, with the flag they got then.
    logged = set()
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8") as f:
            logged = {r["recall_number"] for r in csv.DictReader(f)}
    since = today - timedelta(days=30)
    recent = [r for r in scored if (_parse_day(r["report_date"]) or date.min) >= since]
    new = [r for r in recent if r["recall_number"] not in logged]
    needs_header = not log_path.exists() or log_path.stat().st_size == 0
    if new or needs_header:
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS, extrasaction="ignore")
            if needs_header:
                writer.writeheader()
            writer.writerows({**r, "flagged_on": today.isoformat()} for r in new)

    def by_flag(group):
        return {level: sum(1 for r in group if r["flag"] == level) for level in LEVELS}

    return {"all": by_flag(scored), "recent": by_flag(recent), "logged": len(new),
            "drugs_with_labelers": len(labelers)}


# ---------------------------------------------------------------- the control chart

def control_limits(counts):
    """(center, upper limit, lower limit) for an XmR chart of these weekly counts."""
    if len(counts) < 2:
        return None
    center = sum(counts) / len(counts)
    moving = [abs(b - a) for a, b in zip(counts, counts[1:])]
    spread = 2.66 * sum(moving) / len(moving)
    return center, center + spread, max(0.0, center - spread)


def build_control_chart(recalls_path, weekly_path, workdir, today, baseline_weeks=104,
                        recent_weeks=13):
    """Weekly recall events with control limits. Returns the latest complete week's numbers."""
    con = duckdb.connect()
    con.execute(f"CREATE VIEW recalls AS SELECT * FROM read_parquet('{recalls_path.as_posix()}')")
    found = {week: (events, recalls) for week, events, recalls in
             con.execute(read_query(WEEKLY_SQL)).fetchall()}
    this_week = today - timedelta(days=today.weekday())   # Monday, the same as date_trunc('week')
    weeks = []
    if found:
        week = min(found)
        while week < this_week:
            weeks.append((week, *found.get(week, (0, 0))))
            week += timedelta(days=7)

    counts = [events for _, events, _ in weeks]
    baseline = counts[-(baseline_weeks + recent_weeks):-recent_weeks] if len(counts) > recent_weeks else []
    limits = control_limits(baseline)
    rows = []
    for week, events, recalls in weeks:
        signal = ""
        if limits and events > limits[1]:
            signal = "above"
        elif limits and limits[2] > 0 and events < limits[2]:
            signal = "below"
        rows.append({"week": week.isoformat(), "events": str(events), "recalls": str(recalls),
                     "center": None if not limits else f"{limits[0]:.2f}",
                     "ucl": None if not limits else f"{limits[1]:.2f}",
                     "lcl": None if not limits else f"{limits[2]:.2f}", "signal": signal})
    load_batch(con, rows, WEEKLY_COLUMNS, "weekly", workdir)
    write_parquet(con, """
        SELECT CAST(week AS DATE) AS week, CAST(events AS INTEGER) AS events,
               CAST(recalls AS INTEGER) AS recalls, CAST(center AS DOUBLE) AS center,
               CAST(ucl AS DOUBLE) AS ucl, CAST(lcl AS DOUBLE) AS lcl, signal
        FROM weekly ORDER BY week
    """, weekly_path)

    last = rows[-1] if rows else {}
    return {"last_week": last.get("week"), "last_events": int(last.get("events") or 0),
            "center": limits[0] if limits else None, "ucl": limits[1] if limits else None,
            "lcl": limits[2] if limits else None, "signal": last.get("signal", ""),
            "recent_signals": sum(1 for r in rows[-recent_weeks:] if r["signal"])}


# ---------------------------------------------------------------- the backtest

BACKTEST_SQL = """
WITH units AS (
    SELECT k.event_id, k.drug_key,
           MIN(TRY_STRPTIME(r.recall_initiation_date, '%Y%m%d'))::DATE AS recall_date,
           MODE(k.root_cause) AS root_cause
    FROM recall_risk AS k
    INNER JOIN recalls AS r ON r.recall_number = k.recall_number
    WHERE k.drug_key IS NOT NULL AND k.root_cause IS NOT NULL
    GROUP BY k.event_id, k.drug_key
),
followed AS (
    SELECT DISTINCT u.event_id, u.drug_key
    FROM units AS u
    INNER JOIN recall_risk AS k ON k.event_id = u.event_id AND k.drug_key = u.drug_key
    INNER JOIN links AS l ON l.recall_number = k.recall_number
    WHERE l.shortage_list_type = 'shortage'
      AND TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y')::DATE
          BETWEEN u.recall_date AND u.recall_date + INTERVAL 365 DAY
)
SELECT u.event_id, u.drug_key, u.root_cause, f.event_id IS NOT NULL AS was_followed,
       r.product_description
FROM units AS u
INNER JOIN recall_risk AS k ON k.event_id = u.event_id AND k.drug_key = u.drug_key
INNER JOIN recalls AS r ON r.recall_number = k.recall_number
LEFT JOIN followed AS f ON f.event_id = u.event_id AND f.drug_key = u.drug_key
WHERE u.recall_date >= DATE '2020-01-01'
"""


def score_units(rows, labelers):
    """One score per drug in each recall event: the root cause, how many companies make that
    drug, and whether any of its recalled products is an injectable."""
    units = {}
    for event_id, key, root_cause, was_followed, description in rows:
        u = units.setdefault((event_id, key), {"root_cause": root_cause, "followed": bool(was_followed),
                                               "labelers": labelers.get(key), "injectable": False})
        u["injectable"] = u["injectable"] or is_injectable(description)
    for u in units.values():
        u["points"], u["flag"], _ = score_recall(u["root_cause"], u["labelers"], u["injectable"])
    return list(units.values())


def flag_lift(path=BACKTEST_JSON):
    """The latest backtest's numbers, or None before the first backtest."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summarize(events, group):
    """events, followed, rate and lift over the average, for each value of group(event)."""
    overall = sum(e["followed"] for e in events) / len(events) if events else 0
    table = defaultdict(lambda: [0, 0])
    for e in events:
        table[group(e)][0] += 1
        table[group(e)][1] += e["followed"]
    return overall, {k: (n, hit, hit / n if n else 0, (hit / n) / overall if n and overall else 0)
                     for k, (n, hit) in table.items()}


def backtest():
    from shortagesignal.run_sql import connect

    for path in (NDC_PATH, RECALLS_PATH, ROOT_CAUSES_PATH, RECALL_DRUGS_PATH):
        if not path.exists():
            sys.exit(f"{path} is missing. Copy the data branch in first: "
                     "git fetch origin data, then git archive origin/data | tar -x -C data")
    con = connect()
    units = score_units(con.execute(BACKTEST_SQL).fetchall(), drug_labelers(con, NDC_PATH.as_posix()))
    if not units:
        sys.exit("No recalled drugs since 2020 to score.")

    def band(u):
        n = u["labelers"]
        return ("not in the NDC directory" if n is None else "1 or 2" if n <= 2
                else "3 to 5" if n <= 5 else "6 or more")

    sections = [("Flag", lambda u: u["flag"], LEVELS),
                ("Root cause is Sterility", lambda u: "yes" if u["root_cause"] == "Sterility" else "no", ["yes", "no"]),
                ("Companies that make the drug", band, ["1 or 2", "3 to 5", "6 or more", "not in the NDC directory"]),
                ("Injectable", lambda u: "yes" if u["injectable"] else "no", ["yes", "no"])]
    followed = sum(u["followed"] for u in units)
    overall = followed / len(units)
    lines = ["# Risk flag backtest", "",
             f"Drugs recalled since 2020: {len(units):,}, counting each drug in each recall event "
             f"once. Followed within a year by a shortage of the same drug that FDA still lists: "
             f"{followed:,} ({overall:.1%}). Lift is each group's rate divided by that average.", "",
             "The Sterility points came from this same data, so these numbers are optimistic. "
             "The honest test is risk_log.csv: flags given on the day a recall was reported, "
             "checked against shortages that come later.", ""]
    for title, group, order in sections:
        _, table = summarize(units, group)
        lines += [f"## {title}", "", "| | Recalled drugs | Followed | Rate | Lift |", "|---|---|---|---|---|"]
        for key in order:
            if key in table:
                n, hit, rate, lift = table[key]
                lines.append(f"| {key} | {n:,} | {hit:,} | {rate:.1%} | {lift:.1f}x |")
        lines.append("")
    _, by_flag = summarize(units, lambda u: u["flag"])
    _, by_cause = summarize(units, lambda u: u["root_cause"] == "Sterility")
    summary = {"unit": "one drug in one recall event", "since": "2020-01-01",
               "recalled_drugs": len(units), "followed": followed, "rate": round(overall, 4),
               "rate_by_flag": {k: round(v[2], 4) for k, v in by_flag.items()},
               "lift": {k: round(v[3], 2) for k, v in by_flag.items()},
               "sterility_lift": round(by_cause[True][3], 2) if True in by_cause else None}
    BACKTEST_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    BACKTEST_RESULTS.write_text("\n".join(lines), encoding="utf-8")
    BACKTEST_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Saved {BACKTEST_RESULTS} and {BACKTEST_JSON.name}")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["backtest"]:
        backtest()
    else:
        sys.exit("usage: python -m shortagesignal.risk backtest")


if __name__ == "__main__":
    main()
