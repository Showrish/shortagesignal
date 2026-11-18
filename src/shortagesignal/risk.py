"""
Day 10: a risk flag on every recall, maker counts, and a control chart on weekly recalls.

  python -m shortagesignal.risk backtest    how the flag does on drugs recalled since 2020
  python -m shortagesignal.risk check-log   how the flag does on recalls it was given to, later

The flag isn't a trained model, and it doesn't claim to predict much. Only about 1 in 100
drugs recalled since 2020 was followed within a year by a shortage of the same drug that FDA
still lists, too few for a model to learn from. Each recall gets points instead:
  2  the recalled drug is on FDA's shortage list right now (any company, any match level).
     That's a fact, not a prediction, and the most urgent case: the recall can deepen a
     shortage that already exists.
  1  the product is an injectable (vial, syringe, infusion), the one sign that held up when
     each drug in each recall event was counted on its own: about twice the rate of other
     recalls, in both 2020-22 and 2023 on (see sql/flag_evidence.sql)
2 points or more is high, 1 is watch, and 0 is low.

Two earlier signs were dropped on 2026-10-26, and the backtest still reports them. Sterility
added nothing once injectables were accounted for, since 80% of sterility recalls are
injectables. Few makers pointed the wrong way: drugs only 1 or 2 companies list are mostly
niche or compounded products, which the shortage list rarely covers.

The backtest's unit is one drug in one recall event, the same as sql/lag_by_root_cause.sql:
a shortage happens to a drug, so the question is whether this drug went short after this
recall. It tests the watch sign. High is a status, so it isn't backtested. It's built to
avoid flattering the flag:
  - The year starts on the recall's report date, the first day a flag could exist, not the
    day the firm started the recall. A shortage posted in between was already known when
    the flag could have been given.
  - Only recalls with a full year after their report count. A newer one can still be
    followed, so counting it as a miss would pull every rate down.
  - "Followed" is counted three ways, from loose to strict: any link (the same drug name),
    the same route (the same drug given the same way, like injectable or oral, which is
    the primary definition) and the same company. Most outcomes rest on drug-only links,
    which can join an injection recall to a patch shortage.
  - The watch flag is compared with flagging every recall and flagging none, on precision,
    the share of outcomes it catches, the review work and how far ahead it flagged.
  - The split by period is a consistency check, not a holdout, since the injectable rule
    was chosen using all those years. The forward test below is the clean test.
None of that fixes missing history: FDA's feed drops resolved shortages after a while, so
older years are still undercounted, and the report says so next to its numbers. Every daily
run works it out again from the tables it just built and saves it to the data branch, as
risk_backtest.json and risk_backtest.md, which the dashboard and the weekly digest quote. The
command saves the same thing to audit/, as a snapshot.

Companies are counted from the NDC directory, leaving out ones that call themselves
repackagers or relabelers. Repackagers that don't say so still count, so common drugs come
out high, which only makes the flag more cautious.

New recalls go into risk_log.csv with the flag they got on the day they were reported, so
later runs can check the flag on recalls it has never seen. That's the forward test, and
check-log runs it. It counts the way the backtest does, one drug in one recall event, and a
drug counts as followed when FDA posts a shortage listing of it after the flag and within a
year. Rates only use flags that have had their full year: early hits are known sooner than
misses, so counting them before the year is out would flatter the flag. Flags logged before
2026-10-26 used the old points, so they're reported apart and don't judge the current flag.
The weekly digest reports the forward test too.

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
    BACKTEST_PATH,
    LINKS_PATH,
    NDC_PATH,
    RECALL_IDS_PATH,
    RECALLS_PATH,
    RISK_LOG_PATH,
    RISK_PATH,
    ROOT,
    SHORTAGE_DRUGS_PATH,
    SNAPSHOTS_PATH,
)
from shortagesignal.drugs import drug_key
from shortagesignal.firms import firm_key
from shortagesignal.run_sql import read_query
from shortagesignal.storage import load_batch, write_parquet

WEEKLY_SQL = ROOT / "sql" / "weekly_recall_events.sql"
BACKTEST_RESULTS = ROOT / "audit" / "risk_backtest.md"
BACKTEST_JSON = ROOT / "audit" / "risk_backtest.json"
CHECK_RESULTS = ROOT / "audit" / "risk_log_check.md"
CHECK_JSON = ROOT / "audit" / "risk_log_check.json"
FLAG_SINCE = date(2026, 10, 26)   # flags logged before this used the old points
FOLLOW_DAYS = 365
INJECTABLE = re.compile(r"inject|syringe|infusion|intraven|ampul|\bi\.?v\.?\b", re.I)
VIAL = re.compile(r"\bvials?\b", re.I)
# Eye drops and the like often come in single-use vials, but they aren't injected.
NOT_INJECTED = re.compile(r"ophthalmic|\beyes?\b|\botic\b|\bears?\b|nasal|inhal", re.I)
REPACKAGER = re.compile(r"repack|relabel", re.I)
RISK_COLUMNS = ["recall_number", "event_id", "report_date", "recall_class", "root_cause",
                "drug_key", "labelers", "injectable", "in_shortage", "points", "flag", "reasons"]
LOG_COLUMNS = ["recall_number", "report_date", "flagged_on", "flag", "points", "reasons",
               "event_id", "drug_key"]   # the drug and event as they were on the day of the flag
HORIZONS = (30, 90, 180, 365)
WEEKLY_COLUMNS = ["week", "events", "recalls", "center", "ucl", "lcl", "signal"]
LEVELS = ["high", "watch", "low"]


# ---------------------------------------------------------------- the flag

def is_injectable(description):
    if not description:
        return False
    if INJECTABLE.search(description):
        return True
    return bool(VIAL.search(description)) and not NOT_INJECTED.search(description)


def score_recall(in_shortage, injectable):
    """(points, flag, reasons) for one recall: 2 when its drug is on FDA's shortage list right
    now, 1 for an injectable. 2 or more is high, 1 is watch, 0 is low."""
    points, reasons = 0, []
    if in_shortage:
        points += 2
        reasons.append("on the shortage list now")
    if injectable:
        points += 1
        reasons.append("injectable")
    flag = "high" if points >= 2 else "watch" if points == 1 else "low"
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
               makers_path, log_path, workdir, today, links_path=None):
    """Score every recall, save the maker counts, and log the flags of newly reported recalls.
    links_path holds the recall-to-shortage links, which say whether a drug is short now."""
    con = duckdb.connect()
    short_now = set()
    if links_path is not None and Path(links_path).exists():
        short_now = {n for (n,) in con.execute(f"""
            SELECT DISTINCT recall_number FROM read_parquet('{Path(links_path).as_posix()}')
            WHERE shortage_list_type = 'shortage' AND lower(shortage_status) = 'current'
        """).fetchall()}
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
        injectable, in_shortage = is_injectable(description), number in short_now
        points, flag, reasons = score_recall(in_shortage, injectable)
        scored.append({"recall_number": number, "event_id": event_id, "report_date": report_date,
                       "recall_class": recall_class, "root_cause": root_cause, "drug_key": key,
                       "labelers": None if n is None else str(n),
                       "injectable": "true" if injectable else "false",
                       "in_shortage": "true" if in_shortage else "false",
                       "points": str(points), "flag": flag, "reasons": reasons})
    load_batch(con, scored, RISK_COLUMNS, "recall_risk", workdir)
    write_parquet(con, """
        SELECT recall_number, event_id, report_date, recall_class, root_cause, drug_key,
               CAST(labelers AS INTEGER) AS labelers, CAST(injectable AS BOOLEAN) AS injectable,
               CAST(in_shortage AS BOOLEAN) AS in_shortage, CAST(points AS INTEGER) AS points,
               flag, reasons
        FROM recall_risk ORDER BY recall_number
    """, risk_path)

    # Recalls reported in the last 30 days go into the log once, with the flag they got then,
    # and the drug and event they were matched to then, so a later renaming can't change what
    # the flag is judged on. A log from before those columns gets them added, with old rows
    # left blank, which the forward test reads as "use today's name".
    old_rows, header_ok = [], False
    if log_path.exists() and log_path.stat().st_size:
        with open(log_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header_ok = reader.fieldnames == LOG_COLUMNS
            old_rows = list(reader)
    logged = {r["recall_number"] for r in old_rows}
    since = today - timedelta(days=30)
    recent = [r for r in scored if (_parse_day(r["report_date"]) or date.min) >= since]
    new = [r for r in recent if r["recall_number"] not in logged]
    if new or not header_ok:
        with open(log_path, "a" if header_ok else "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS, restval="", extrasaction="ignore")
            if not header_ok:
                writer.writeheader()
                writer.writerows(old_rows)
            writer.writerows({**r, "flagged_on": today.isoformat(), "drug_key": r["drug_key"] or ""}
                             for r in new)

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

SINCE = date(2020, 1, 1)
PRIMARY = "same_route"
DEFINITIONS = {
    "any_link": "Any link: the same drug name",
    "same_route": "Same route: the same drug given the same way (primary)",
    "same_company": "Same company: the same drug from the same company",
}
MISSING_HISTORY = ("Counting only recalls with a full year after their report fixes incomplete "
                   "follow-up, not missing history. FDA's feed drops resolved shortages after a "
                   "while, so older years are still undercounted, and these numbers describe this "
                   "dataset, not every shortage.")
ROUTES = [   # the first match wins, so eye drops in vials come out ophthalmic, not injectable
    ("ophthalmic", re.compile(r"ophthalm|\beyes?\b", re.I)),
    ("otic", re.compile(r"\botic\b|\bears?\b", re.I)),
    ("nasal", re.compile(r"nasal", re.I)),
    ("inhaled", re.compile(r"inhal|nebuli", re.I)),
    ("injectable", re.compile(r"inject|syringe|infusion|intraven|intramuscular|subcutaneous|ampul"
                              r"|\bi\.?v\.?\b|\bvials?\b", re.I)),
    ("transdermal", re.compile(r"transdermal|\bpatch", re.I)),
    ("rectal or vaginal", re.compile(r"rectal|vaginal|suppositor|enema", re.I)),
    ("topical", re.compile(r"topical|cream|ointment|\bgel\b|lotion|\bfoam\b|shampoo", re.I)),
    ("oral", re.compile(r"\boral|tablet|capsule|caplet|chewable|syrup|elixir|lozenge|\bdrops?\b", re.I)),
]

UNITS_SQL = """
WITH causes AS (
    -- each drug in each recall event's most common root cause. A tie goes to the cause that
    -- comes first A to Z, so the same data always gives the same answer, where MODE picked
    -- among tied causes at random and a rerun could move a drug from one cause to another.
    SELECT event_id, drug_key, first(root_cause ORDER BY n DESC, root_cause) AS root_cause
    FROM (
        SELECT k.event_id, k.drug_key, k.root_cause, COUNT(*) AS n
        FROM recall_risk AS k
        INNER JOIN recalls AS r ON r.recall_number = k.recall_number
        WHERE k.drug_key IS NOT NULL AND k.root_cause IS NOT NULL
        GROUP BY k.event_id, k.drug_key, k.root_cause
    )
    GROUP BY event_id, drug_key
)
SELECT k.event_id, k.drug_key,
       MIN(TRY_STRPTIME(k.report_date, '%Y%m%d'))::DATE AS reported,
       any_value(c.root_cause) AS root_cause,
       list(DISTINCT k.recall_number) AS recall_numbers,
       list(DISTINCT r.product_description) AS products
FROM recall_risk AS k
INNER JOIN recalls AS r ON r.recall_number = k.recall_number
INNER JOIN causes AS c ON c.event_id = k.event_id AND c.drug_key = k.drug_key
WHERE k.drug_key IS NOT NULL AND k.root_cause IS NOT NULL
GROUP BY k.event_id, k.drug_key
"""

SHORTAGE_LINKS_SQL = """
SELECT l.recall_number, TRY_STRPTIME(l.shortage_posted, '%m/%d/%Y')::DATE AS posted,
       d.firm_key, s.dosage_form, s.presentation, s.generic_name
FROM links AS l
LEFT JOIN shortage_drugs AS d ON d.shortage_key = l.shortage_key
LEFT JOIN (SELECT shortage_key, arg_max(dosage_form, snapshot_date) AS dosage_form,
                  arg_max(presentation, snapshot_date) AS presentation,
                  arg_max(generic_name, snapshot_date) AS generic_name
           FROM snapshots GROUP BY shortage_key) AS s ON s.shortage_key = l.shortage_key
WHERE l.shortage_list_type = 'shortage'
"""

RECALL_FIRMS_SQL = "SELECT recall_number, any_value(firm_key) FROM recall_ids GROUP BY recall_number"


def route_of(text):
    """How a product is given, read from its text: injectable, oral, topical, ophthalmic and
    so on. None when the text doesn't say."""
    for route, pattern in ROUTES:
        if text and pattern.search(text):
            return route
    return None


def backtest_units(con, labelers, today, days=FOLLOW_DAYS):
    """One dict per drug in each recall event reported since 2020: its watch sign, the dropped
    signs, whether it has had a full year after its report, and, for each definition of the
    same drug, the first shortage of it posted in that year."""
    firms = dict(con.execute(RECALL_FIRMS_SQL).fetchall())
    shortages = defaultdict(list)
    for number, posted, firm, form, presentation, name in con.execute(SHORTAGE_LINKS_SQL).fetchall():
        if posted:
            shortages[number].append((posted, firm, route_of(" ".join(filter(None, (form, presentation, name))))))
    units = []
    for event_id, key, reported, root_cause, numbers, products in con.execute(UNITS_SQL).fetchall():
        if reported is None or reported < SINCE:
            continue
        products = [p for p in products if p]
        routes = {route_of(p) for p in products} - {None}
        companies = {firms.get(n) for n in numbers} - {None}
        end = reported + timedelta(days=days)
        first = dict.fromkeys(DEFINITIONS)
        unread = False          # a link in the year to a shortage whose route can't be read
        for number in numbers:
            for posted, firm, route in shortages.get(number, []):
                if not reported < posted <= end:     # only after the report, within the year
                    continue
                unread = unread or route is None
                matches = {"any_link": True, "same_route": route is not None and route in routes,
                           "same_company": firm is not None and firm in companies}
                for definition, matched in matches.items():
                    if matched and (first[definition] is None or posted < first[definition]):
                        first[definition] = posted
        injectable = any(is_injectable(p) for p in products)
        units.append({"event_id": event_id, "drug_key": key, "reported": reported,
                      "root_cause": root_cause, "labelers": labelers.get(key),
                      "injectable": injectable, "flag": score_recall(False, injectable)[1],
                      "route_known": bool(routes), "full_year": end <= today, "first": first,
                      "unread_shortage_route": unread and not first["same_route"]})
    return units


def _quartiles(values):
    if not values:
        return None
    values = sorted(values)
    pick = lambda q: values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]  # noqa: E731
    return {"median": pick(0.5), "p25": pick(0.25), "p75": pick(0.75)}


def counted(cohort, definition):
    """The recalled drugs a definition can judge. Same route needs the recall's route, so the
    ones whose text doesn't say are left out, rather than counted as never followed."""
    return [u for u in cohort if u["route_known"]] if definition == "same_route" else cohort


def score_definition(cohort, definition, weeks):
    """Precision, capture, workload, lift and lead time of the watch flag under one definition."""
    cohort = counted(cohort, definition)
    followed = [u for u in cohort if u["first"][definition]]
    watch = [u for u in cohort if u["flag"] == "watch"]
    low = [u for u in cohort if u["flag"] == "low"]
    watch_hit = sum(1 for u in watch if u["first"][definition])
    low_hit = sum(1 for u in low if u["first"][definition])
    rate = len(followed) / len(cohort)
    watch_rate = watch_hit / len(watch) if watch else None
    return {"counted": len(cohort), "followed": len(followed), "rate": rate,
            "range": wilson(len(followed), len(cohort)),
            "watch": len(watch), "watch_followed": watch_hit, "watch_rate": watch_rate,
            "watch_range": wilson(watch_hit, len(watch)),
            "low": len(low), "low_followed": low_hit,
            "low_rate": low_hit / len(low) if low else None,
            "capture": watch_hit / len(followed) if followed else None,
            "workload": len(watch) / len(cohort), "watch_per_week": len(watch) / weeks,
            "all_per_week": len(cohort) / weeks,
            "lift": watch_rate / rate if watch_rate is not None and rate else None,
            "lead_days": _quartiles([(u["first"][definition] - u["reported"]).days
                                     for u in watch if u["first"][definition]])}


def _pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def _with_range(rate, rng):
    return "n/a" if rate is None else f"{rate:.1%} ({rng[0]:.1%} to {rng[1]:.1%})"


def flag_lift(path=None):
    """The latest backtest's numbers: the daily run's copy if there is one, then the snapshot
    in audit/. None before the first backtest."""
    for candidate in ([path] if path else [BACKTEST_PATH, BACKTEST_JSON]):
        try:
            return json.loads(Path(candidate).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
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


def run_backtest(paths, today=None):
    """(lines, summary): the backtest as Markdown lines and the numbers the dashboard and the
    digest quote. paths maps recalls, risk, links, ndc, recall_ids, shortage_drugs and
    snapshots to their files. (None, None) when no recall has had its full year yet."""
    today = today or date.today()
    con = duckdb.connect()
    for view, name in (("recalls", "recalls"), ("recall_risk", "risk"), ("links", "links"),
                       ("recall_ids", "recall_ids"), ("shortage_drugs", "shortage_drugs"),
                       ("snapshots", "snapshots")):
        con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet('{Path(paths[name]).as_posix()}')")
    units = backtest_units(con, drug_labelers(con, Path(paths["ndc"]).as_posix()), today)
    cohort = [u for u in units if u["full_year"]]
    if not cohort:
        return None, None
    waiting = len(units) - len(cohort)
    first_day, last_day = min(u["reported"] for u in cohort), max(u["reported"] for u in cohort)
    weeks = max(1.0, ((last_day - first_day).days + 1) / 7)
    scores = {d: score_definition(cohort, d, weeks) for d in DEFINITIONS}
    primary = scores[PRIMARY]
    judged = counted(cohort, PRIMARY)           # the recalled drugs the headline can judge
    for u in judged:
        u["followed"] = bool(u["first"][PRIMARY])

    lines = ["# Risk flag backtest", "",
             f"Drugs reported in a recall from {_day(first_day)} to {_day(last_day)}: "
             f"{len(cohort):,}, counting each drug in each recall event once. Each one's year "
             "starts on its report date, the first day a flag could exist, and only recalls with "
             f"a full year since are counted, which leaves out {waiting:,} newer ones for now.", "",
             f"**{MISSING_HISTORY}**", "",
             "The watch flag means an injectable. High means the drug was already short, a status "
             "rather than a prediction, so it isn't backtested here. The signs were chosen by "
             "looking at this same data, so these numbers are optimistic. The honest test is the "
             "forward test on risk_log.csv.", "",
             "## What counts as the same drug going short", "",
             "| Definition | Recalled drugs judged | Followed | Rate, with its 95% range | Watch | Low "
             "| Lift | Watch catches |",
             "|---|---|---|---|---|---|---|---|"]
    for d, label in DEFINITIONS.items():
        s = scores[d]
        lift = "n/a" if s["lift"] is None else f"{s['lift']:.1f}x"
        lines.append(f"| {label} | {s['counted']:,} | {s['followed']:,} | "
                     f"{_with_range(s['rate'], s['range'])} | {_pct(s['watch_rate'])} | "
                     f"{_pct(s['low_rate'])} | {lift} | {_pct(s['capture'])} |")
    unknown = len(cohort) - len(judged)
    unread = sum(1 for u in judged if u["unread_shortage_route"])
    lines += ["", f"Of {scores['any_link']['followed']:,} recalled drugs followed through any link, "
                  f"{scores['same_route']['followed']:,} were followed by a shortage of the same "
                  f"route and {scores['same_company']['followed']:,} by one from the same company. "
                  f"The route couldn't be read from the recall for {unknown:,} recalled drugs, so the "
                  f"same-route numbers leave them out rather than count them as never followed. "
                  f"Another {unread:,} were linked in their year only to shortage listings whose "
                  "route couldn't be read, so same route may miss a few real outcomes. Same company "
                  "compares cleaned company names, so a subsidiary and its parent count as different "
                  "companies, which makes it a lower bound.", "",
              f"## The watch flag against the simplest choices, same route, on the {len(judged):,} "
              "recalled drugs whose route can be read", "",
              "| Approach | Recalled drugs flagged | Share of the review work | Flags per week "
              "| Precision | Outcomes caught |", "|---|---|---|---|---|---|",
              f"| Flag none | 0 | 0% | 0 | n/a | 0 of {primary['followed']:,} |",
              f"| Flag every recall | {len(judged):,} | 100% | {primary['all_per_week']:.1f} | "
              f"{_with_range(primary['rate'], primary['range'])} | {primary['followed']:,} of "
              f"{primary['followed']:,} |",
              f"| Watch: an injectable | {primary['watch']:,} | {_pct(primary['workload'])} | "
              f"{primary['watch_per_week']:.1f} | {_with_range(primary['watch_rate'], primary['watch_range'])} "
              f"| {primary['watch_followed']:,} of {primary['followed']:,} |", ""]
    if primary["lead_days"]:
        q = primary["lead_days"]
        lines += [f"For watch flags that were followed, the shortage was posted a median of "
                  f"{q['median']} days after the recall was reported, and the middle half took "
                  f"{q['p25']} to {q['p75']} days.", ""]
    lines += ["## Consistency over time, same route", "",
              "Not a holdout: the injectable rule was chosen looking at all of these years.", "",
              "| Reported | Recalled drugs | Watch | Low |", "|---|---|---|---|"]
    for label, keep in (("2020 to 2022", lambda u: u["reported"].year <= 2022),
                        ("2023 on", lambda u: u["reported"].year >= 2023)):
        part = [u for u in judged if keep(u)]
        if part:
            s = score_definition(part, PRIMARY, weeks)
            lines.append(f"| {label} | {len(part):,} | {_pct(s['watch_rate'])} | {_pct(s['low_rate'])} |")
    lines.append("")

    def band(u):
        n = u["labelers"]
        return ("not in the NDC directory" if n is None else "1 or 2" if n <= 2
                else "3 to 5" if n <= 5 else "6 or more")

    def cause_and_form(u):
        return (("sterility" if u["root_cause"] == "Sterility" else "other cause") + ", "
                + ("injectable" if u["injectable"] else "not injectable"))

    combos = [f"{c}, {f}" for c in ("sterility", "other cause") for f in ("injectable", "not injectable")]
    for title, group, order in [
            ("Dropped: root cause is Sterility",
             lambda u: "yes" if u["root_cause"] == "Sterility" else "no", ["yes", "no"]),
            ("Why Sterility was dropped: it adds nothing within injectables", cause_and_form, combos),
            ("Dropped: companies that make the drug", band,
             ["1 or 2", "3 to 5", "6 or more", "not in the NDC directory"])]:
        _, table = summarize(judged, group)
        lines += [f"## {title}, same route", "", "| | Recalled drugs | Followed | Rate | Lift |",
                  "|---|---|---|---|---|"]
        for key in order:
            if key in table:
                n, hit, rate, lift = table[key]
                lines.append(f"| {key} | {n:,} | {hit:,} | {rate:.1%} | {lift:.1f}x |")
        lines.append("")
    _, by_cause = summarize(judged, lambda u: u["root_cause"] == "Sterility")

    def r4(x):
        return None if x is None else round(x, 4)

    summary = {"unit": "one drug in one recall event", "since": SINCE.isoformat(),
               "window": "from the report date to 365 days after",
               "cohort_end": (today - timedelta(days=FOLLOW_DAYS)).isoformat(),
               "recalled_drugs": len(cohort), "waiting_for_full_year": waiting, "primary": PRIMARY,
               "followed": primary["followed"], "rate": r4(primary["rate"]),
               "rate_by_flag": {"watch": r4(primary["watch_rate"]), "low": r4(primary["low_rate"])},
               "lift": {"watch": None if primary["lift"] is None else round(primary["lift"], 2)},
               "sterility_lift": round(by_cause[True][3], 2) if True in by_cause else None,
               "definitions": {d: {"counted": s["counted"], "followed": s["followed"],
                                   "rate": r4(s["rate"]),
                                   "watch_rate": r4(s["watch_rate"]), "low_rate": r4(s["low_rate"]),
                                   "capture": r4(s["capture"])} for d, s in scores.items()},
               "baselines": {"flag_all": {"flagged": len(judged), "precision": r4(primary["rate"]),
                                          "per_week": round(primary["all_per_week"], 1)},
                             "watch": {"flagged": primary["watch"], "precision": r4(primary["watch_rate"]),
                                       "capture": r4(primary["capture"]), "workload": r4(primary["workload"]),
                                       "per_week": round(primary["watch_per_week"], 1)}},
               "lead_days": primary["lead_days"], "caveat": MISSING_HISTORY,
               "computed_on": today.isoformat()}
    return lines, summary


def save_backtest(lines, summary, report_path, json_path):
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text("\n".join(lines), encoding="utf-8")
    Path(json_path).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def backtest():
    """The command: the backtest on DATA_DIR, printed and saved to audit/ as a snapshot."""
    paths = {"recalls": RECALLS_PATH, "risk": RISK_PATH, "links": LINKS_PATH, "ndc": NDC_PATH,
             "recall_ids": RECALL_IDS_PATH, "shortage_drugs": SHORTAGE_DRUGS_PATH,
             "snapshots": SNAPSHOTS_PATH}
    for path in paths.values():
        if not path.exists():
            sys.exit(f"{path} is missing. Copy the data branch in first: "
                     "git fetch origin data, then git archive origin/data | tar -x -C data")
    lines, summary = run_backtest(paths)
    if not lines:
        sys.exit("No recalled drug since 2020 has had its full year yet.")
    save_backtest(lines, summary, BACKTEST_RESULTS, BACKTEST_JSON)
    print("\n".join(lines))
    print(f"Saved {BACKTEST_RESULTS} and {BACKTEST_JSON.name}")


# ---------------------------------------------------------------- the forward test

CHECK_SQL = """
WITH logged AS (
    -- the drug and event saved with the flag, or today's for rows logged before they were saved
    SELECT l.recall_number, TRY_CAST(l.flagged_on AS DATE) AS flagged_on, l.flag,
           {event} AS event_id, {drug} AS drug_key, {saved} AS saved
    FROM read_csv('{log}', header = true, all_varchar = true) AS l
    LEFT JOIN read_parquet('{risk}') AS k ON k.recall_number = l.recall_number
),
units AS (
    -- one drug in one recall event, from the first day any of its recalls was flagged,
    -- with the highest flag any of them got
    SELECT event_id, drug_key, MIN(flagged_on) AS flagged_on,
           CASE MAX(CASE flag WHEN 'high' THEN 3 WHEN 'watch' THEN 2 ELSE 1 END)
               WHEN 3 THEN 'high' WHEN 2 THEN 'watch' ELSE 'low' END AS flag,
           bool_and(saved) AS saved
    FROM logged
    WHERE drug_key IS NOT NULL AND flagged_on IS NOT NULL
    GROUP BY event_id, drug_key
),
followed AS (
    -- the first shortage FDA posted after the flag, within the window, linked to any of the
    -- unit's logged recalls
    SELECT u.event_id, u.drug_key,
           MIN(TRY_STRPTIME(s.shortage_posted, '%m/%d/%Y')::DATE) AS first_posted
    FROM units AS u
    INNER JOIN logged AS g ON g.event_id = u.event_id AND g.drug_key = u.drug_key
    INNER JOIN read_parquet('{links}') AS s ON s.recall_number = g.recall_number
    WHERE s.shortage_list_type = 'shortage'
      AND TRY_STRPTIME(s.shortage_posted, '%m/%d/%Y')::DATE > u.flagged_on
      AND TRY_STRPTIME(s.shortage_posted, '%m/%d/%Y')::DATE <= u.flagged_on + INTERVAL {days} DAY
    GROUP BY u.event_id, u.drug_key
)
SELECT u.event_id, u.drug_key, u.flag, u.flagged_on, f.first_posted, u.saved
FROM units AS u
LEFT JOIN followed AS f ON f.event_id = u.event_id AND f.drug_key = u.drug_key
ORDER BY u.flagged_on, u.drug_key
"""

UNNAMED_SQL = """
SELECT COUNT(*)
FROM read_csv('{log}', header = true, all_varchar = true) AS l
LEFT JOIN read_parquet('{risk}') AS k ON k.recall_number = l.recall_number
WHERE {drug} IS NULL
"""


def wilson(hit, n, z=1.96):
    """The 95% range for hit out of n, a Wilson interval, as (low, high). None when n is 0."""
    if not n:
        return None
    p = hit / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5 / (1 + z * z / n)
    return max(0.0, center - half), min(1.0, center + half)


def log_units(con, risk_path, links_path, log_path, days=FOLLOW_DAYS):
    """(units, unnamed): every logged flag as a drug in a recall event, with the first
    shortage of that drug posted after the flag and within days, and how many logged recalls
    have no drug name, which can't be followed by a shortage of the same drug."""
    log_path = Path(log_path)
    if not log_path.exists():
        return [], 0
    with open(log_path, newline="", encoding="utf-8") as f:
        if not any(True for _ in csv.DictReader(f)):
            return [], 0
    with open(log_path, newline="", encoding="utf-8") as f:
        header = set(next(csv.reader(f), []))
    # a log written before the drug and event were saved with each flag uses today's
    saved = {"event_id", "drug_key"} <= header
    keys = {"event": "COALESCE(NULLIF(l.event_id, ''), k.event_id)" if saved else "k.event_id",
            "drug": "COALESCE(NULLIF(l.drug_key, ''), k.drug_key)" if saved else "k.drug_key",
            "saved": "NULLIF(l.drug_key, '') IS NOT NULL" if saved else "FALSE"}
    paths = {"risk": Path(risk_path).as_posix(), "links": Path(links_path).as_posix(),
             "log": log_path.as_posix()}
    rows = con.execute(CHECK_SQL.format(days=int(days), **paths, **keys)).fetchall()
    units = [{"event_id": event_id, "drug_key": key, "flag": flag, "flagged_on": flagged_on,
              "first_posted": first_posted, "saved": bool(was_saved)}
             for event_id, key, flag, flagged_on, first_posted, was_saved in rows]
    return units, con.execute(UNNAMED_SQL.format(**paths, **keys)).fetchone()[0]


def judge_log(units, today, since=FLAG_SINCE, days=FOLLOW_DAYS):
    """How the flags given since `since` turned out. For each flag: how many recalled drugs,
    how many have had their full year, how many of those were followed, the rate with its 95%
    range, and the ones still in their year, with any of those followed already. Rates only
    use full years, since hits are known sooner than misses."""
    window = timedelta(days=days)
    current = [u for u in units if u["flagged_on"] >= since]
    old = [u for u in units if u["flagged_on"] < since]
    table = {}
    for level in LEVELS:
        group = [u for u in current if u["flag"] == level]
        done = [u for u in group if u["flagged_on"] + window <= today]
        waiting = [u for u in group if u["flagged_on"] + window > today]
        hit = sum(1 for u in done if u["first_posted"])
        table[level] = {"recalled_drugs": len(group), "full_year": len(done), "followed": hit,
                        "rate": hit / len(done) if done else None,
                        "range": wilson(hit, len(done)),
                        "in_their_year": len(waiting),
                        "followed_already": sum(1 for u in waiting if u["first_posted"])}
    watch, low = table["watch"], table["low"]
    if not watch["full_year"] or not low["full_year"]:
        verdict = "too early"
    elif watch["range"][0] > low["range"][1]:
        verdict = "working"
    elif watch["range"][1] < low["range"][0]:
        verdict = "not working"
    else:
        verdict = "can't tell"
    ends = [u["flagged_on"] + window for u in current
            if u["flag"] in ("watch", "low") and u["flagged_on"] + window > today]
    # each horizon only counts the flags old enough to have finished it
    horizons = {}
    for h in (h for h in HORIZONS if h <= days):
        span, row = timedelta(days=h), {}
        for level in LEVELS:
            done = [u for u in current if u["flag"] == level and u["flagged_on"] + span <= today]
            hit = sum(1 for u in done if u["first_posted"] and u["first_posted"] <= u["flagged_on"] + span)
            row[level] = {"done": len(done), "followed": hit,
                          "rate": hit / len(done) if done else None, "range": wilson(hit, len(done))}
        horizons[h] = row
    return {"since": since, "days": days, "table": table, "verdict": verdict, "horizons": horizons,
            "lead_days": _quartiles([(u["first_posted"] - u["flagged_on"]).days
                                     for u in current if u["first_posted"]]),
            "names_today": sum(1 for u in current if not u.get("saved", True)),
            "first_full_year": min(ends) if ends else None,
            "followed": sorted((u for u in current if u["first_posted"]),
                               key=lambda u: (u["flagged_on"], u["drug_key"])),
            "old": {"recalled_drugs": len(old),
                    "followed": sum(1 for u in old if u["first_posted"])}}


def _day(d):
    return f"{d:%b} {d.day}, {d.year}"


def _count(n, singular, plural):
    return f"{n:,} {singular if n == 1 else plural}"


def _rate(row):
    if row["rate"] is None:
        return "not yet"
    low, high = row["range"]
    return f"{row['rate']:.1%} ({low:.1%} to {high:.1%})"


def verdict_text(result):
    """The forward test's verdict in a sentence or two."""
    t = result["table"]
    watch, low = t["watch"], t["low"]
    if result["verdict"] == "too early":
        if not sum(row["recalled_drugs"] for row in t.values()):
            return "**Nothing to judge yet.** No recall has been flagged under the current points."
        text = ("**Too early to judge.** A flag needs its full year before it counts, and not "
                "enough watch and low flags have had theirs.")
        if result["first_full_year"] and not (watch["full_year"] or low["full_year"]):
            text += f" The first ones finish on {_day(result['first_full_year'])}."
        return text
    rates = f"Watch flags were followed {watch['rate']:.1%} of the time, against {low['rate']:.1%} for low"
    return {"working": f"**The flag is working so far.** {rates}, and the 95% ranges don't overlap.",
            "not working": f"**The flag isn't working.** {rates}, and the 95% ranges don't overlap.",
            "can't tell": f"**Can't tell yet.** {rates}, but the 95% ranges overlap, so the "
                          "difference could be chance."}[result["verdict"]]


def check_report(result, unnamed, today, backtest=None):
    """The forward test as Markdown lines."""
    since, days = result["since"], result["days"]
    lines = ["# Risk log check", "",
             f"The forward test of the risk flag, checked on {_day(today)}. Every new recall is "
             "logged with the flag it got on the day it was reported, before anyone could know "
             "what came next, and this checks those flags against shortages of the same drug "
             "that FDA posted afterward. Nothing here was tuned on.", "",
             "It counts the way the backtest does: one drug in one recall event, so a pharmacy "
             "recalling 40 drugs at once counts as 40. A drug counts as followed when FDA posts a "
             f"shortage listing of it after the flag and within {days} days. Rates only use flags "
             f"that have had their full {days} days, since a hit is known sooner than a miss.", "",
             verdict_text(result), "",
             f"## Flags under the current points, since {_day(since)}", "",
             "| Flag | Recalled drugs | Full year done | Followed | Rate, with its 95% range "
             "| Still in their year | Followed already |",
             "|---|---|---|---|---|---|---|"]
    for level in LEVELS:
        row = result["table"][level]
        lines.append(f"| {level} | {row['recalled_drugs']:,} | {row['full_year']:,} | "
                     f"{row['followed']:,} | {_rate(row)} | {row['in_their_year']:,} | "
                     f"{row['followed_already']:,} |")
    lines.append("")
    lines += ["## By how long after the flag", "",
              "Each row only counts the flags old enough to have finished it. Lead time is "
              "reported on its own, below, since a horizon says how many were followed, not how "
              "early.", "",
              "| Days after the flag | Watch | Low | High |", "|---|---|---|---|"]

    def cell(c):
        if not c["done"]:
            return "none done yet"
        return f"{c['followed']:,} of {c['done']:,} ({c['rate']:.1%})"

    for h, row in result["horizons"].items():
        lines.append(f"| {h} | {cell(row['watch'])} | {cell(row['low'])} | {cell(row['high'])} |")
    q = result["lead_days"]
    lines += ["", (f"**Lead time:** for flags followed so far, the shortage was posted a median of "
                   f"{q['median']} days after the flag, and the middle half took {q['p25']} to "
                   f"{q['p75']} days." if q else "**Lead time:** no flag has been followed yet."), ""]
    # this test counts any link of the same drug name, so it's compared with the backtest
    # counted the same way, not with its same-route headline
    any_link = (backtest or {}).get("definitions", {}).get("any_link")
    rates = ({"watch": any_link.get("watch_rate"), "low": any_link.get("low_rate")} if any_link
             else (backtest or {}).get("rate_by_flag", {}))
    if rates.get("watch") and rates.get("low"):
        lines += [f"For comparison, the backtest on recalls since 2020 expects about "
                  f"{rates['watch']:.1%} for watch and {rates['low']:.1%} for low, counted the "
                  "same way as here, through any link of the same drug name.", ""]
    lines += ["High means the drug was already on FDA's shortage list when it was flagged, so "
              "it's a status, not a prediction. For high, followed means another listing of the "
              "same drug was posted after the flag.", "", "## Followed so far", ""]
    if result["followed"]:
        lines += ["| Drug | Flag | Flagged on | Shortage posted | Days |", "|---|---|---|---|---|"]
        lines += [f"| {u['drug_key']} | {u['flag']} | {u['flagged_on']} | {u['first_posted']} | "
                  f"{(u['first_posted'] - u['flagged_on']).days} |" for u in result["followed"]]
    else:
        lines.append("None yet.")
    old = result["old"]
    lines += ["", f"## Before {_day(since)}", ""]
    if old["recalled_drugs"]:
        lines.append(f"{_count(old['recalled_drugs'], 'recalled drug was', 'recalled drugs were')} "
                     "flagged under the old points, which counted sterility and few makers, and "
                     f"{_count(old['followed'], 'has', 'have')} been followed so far. They're kept "
                     "for the record, not used to judge the current flag.")
    else:
        lines.append("No recall was logged under the old points.")
    if unnamed:
        lines += ["", f"{_count(unnamed, 'logged recall has', 'logged recalls have')} no drug name, "
                      "so they can't be matched to a shortage of the same drug, and they're left out."]
    if result.get("names_today"):
        lines += ["", f"{_count(result['names_today'], 'recalled drug was', 'recalled drugs were')} "
                      "logged before the drug and event were saved with each flag, so they're judged "
                      "on today's name. Every flag logged since is judged on the name it had that day."]
    return lines


def check_log(today=None):
    """Run the forward test on the data in DATA_DIR, and save it to audit/."""
    for path in (RISK_PATH, LINKS_PATH, RISK_LOG_PATH):
        if not path.exists():
            sys.exit(f"{path} is missing. Copy the data branch in first: "
                     "git fetch origin data, then git archive origin/data | tar -x -C data")
    today = today or date.today()
    units, unnamed = log_units(duckdb.connect(), RISK_PATH, LINKS_PATH, RISK_LOG_PATH)
    result = judge_log(units, today)
    lines = check_report(result, unnamed, today, flag_lift())
    summary = {"checked_on": today.isoformat(), "since": result["since"].isoformat(),
               "window_days": result["days"], "verdict": result["verdict"],
               "first_full_year": (result["first_full_year"].isoformat()
                                   if result["first_full_year"] else None),
               "flags": {level: {**row, "rate": None if row["rate"] is None else round(row["rate"], 4),
                                 "range": None if row["range"] is None
                                 else [round(x, 4) for x in row["range"]]}
                         for level, row in result["table"].items()},
               "followed_so_far": len(result["followed"]), "old_points": result["old"],
               "no_drug_name": unnamed, "judged_on_todays_name": result["names_today"],
               "lead_days": result["lead_days"],
               "horizons": {str(h): {level: {"done": c["done"], "followed": c["followed"],
                                             "rate": None if c["rate"] is None else round(c["rate"], 4)}
                                     for level, c in row.items()}
                            for h, row in result["horizons"].items()}}
    CHECK_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    CHECK_RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    CHECK_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved {CHECK_RESULTS} and {CHECK_JSON.name}")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["backtest"]:
        backtest()
    elif args[:1] == ["check-log"]:
        check_log()
    else:
        sys.exit("usage: python -m shortagesignal.risk backtest | check-log")


if __name__ == "__main__":
    main()
