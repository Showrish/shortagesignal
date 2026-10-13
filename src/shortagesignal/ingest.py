"""
Day 2: daily pulls that keep a history.

Every run does three things:
  1. Recalls: re-pull the last 60 days of reports and merge them in by recall_number.
     The recalls table keeps FDA's latest version of each recall, plus the date we first
     saw it. The recall_versions table keeps every version we've ever seen, adding a new
     one only when FDA actually changes a recall. Nothing is ever deleted.
     The very first run loads the full history from the bulk files instead.
  2. Shortages: save today's full shortage list as a dated snapshot. Running twice in
     one day replaces that day's snapshot instead of counting it twice.
  3. NDC directory: refreshed once a week.
  4. Matching IDs: normalized NDCs and firm keys for recalls, shortages and the
     NDC directory (see identify.py).
  5. Matching: a drug identity for every recall, and links to shortages (see match.py).
  6. Root causes: rules first, then Claude Haiku for what the rules can't tag
     (see tagging.py). Claude is only called when SHORTAGESIGNAL_USE_CLAUDE=1.
  7. Data checks: a failed error check stops the run before anything is saved
     (see checks.py).

Storage: one Parquet file per table in DATA_DIR, plus state.json for bookkeeping and
run_log.csv with one row per run. DuckDB is only the engine that reads and writes them.

All or nothing: the run works on a staged copy of the files and only swaps them in if
every step succeeds. A failed run leaves the data exactly as it was, and still logs a row.

Run:  python -m shortagesignal.ingest
"""
import csv
import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import requests

from shortagesignal.checks import collect_checks, last_good_run, read_history, report
from shortagesignal.config import (
    CHECK_LOG_PATH,
    CLAUDE_TAGS_PATH,
    CURRENT_SHORTAGES_PATH,
    DATA_DIR,
    HISTORY_PATH,
    LINKS_PATH,
    NDC_DIRECTORY_PATH,
    NDC_PATH,
    RECALL_DRUGS_PATH,
    RECALL_IDS_PATH,
    RECALL_VERSIONS_PATH,
    RECALLS_PATH,
    ROOT_CAUSES_PATH,
    RUN_LOG_PATH,
    SHORTAGE_DRUGS_PATH,
    SHORTAGE_IDS_PATH,
    SNAPSHOTS_PATH,
    STATE_PATH,
    TAG_REVIEW_PATH,
    UNMATCHED_PATH,
)
from shortagesignal.identify import build_ids
from shortagesignal.match import build_matches
from shortagesignal.tagging import build_root_causes, make_client
from shortagesignal.pull_full_history import API_KEY, API_URL, HEADERS, MANIFEST_URL
from shortagesignal.pull_full_history import from_bulk_files, get_json
from shortagesignal.storage import flatten, load_batch, write_parquet

RECALL_WINDOW_DAYS = 60   # FDA sometimes corrects past reports, so re-pull a safety window
NDC_REFRESH_DAYS = 7
NDC_COLUMNS = [
    "product_ndc", "generic_name", "brand_name", "labeler_name", "dosage_form", "route",
    "product_type", "marketing_category", "active_ingredients", "packaging",
    "marketing_start_date", "marketing_end_date", "listing_expiration_date", "finished",
]
# The daily history keeps only these columns. Today's full rows go to shortages_current.
SNAPSHOT_COLUMNS = [
    "snapshot_date", "shortage_key", "list_type", "fda_listings", "package_ndc", "generic_name",
    "company_name", "presentation", "dosage_form", "status", "availability", "shortage_reason",
    "therapeutic_category", "initial_posting_date", "update_date", "update_type",
    "discontinued_date", "change_date", "resolved_note",
]
RUN_LOG_COLUMNS = [
    "run_at_utc", "status", "seconds", "recalls_mode", "recalls_pulled", "recalls_new",
    "recalls_changed", "recalls_total", "shortage_rows", "shortages_new", "shortages_dropped",
    "shortage_status_changes", "duplicate_listings_merged", "ndc_refreshed",
    "recalls_with_ndc_pct", "shortages_with_ndc_pct", "recalls_identified_pct",
    "recalls_unmatched", "recalls_linked", "shortages_linked", "recalls_tagged_pct",
    "tag_backlog", "claude_calls", "claude_cost_usd", "checks_warned", "checks_failed", "error",
]
DATA_FILES = [p.name for p in (RECALLS_PATH, RECALL_VERSIONS_PATH, SNAPSHOTS_PATH,
                               CURRENT_SHORTAGES_PATH, HISTORY_PATH, NDC_PATH,
                               NDC_DIRECTORY_PATH, RECALL_IDS_PATH, SHORTAGE_IDS_PATH,
                               RECALL_DRUGS_PATH, SHORTAGE_DRUGS_PATH, LINKS_PATH,
                               UNMATCHED_PATH, ROOT_CAUSES_PATH, CLAUDE_TAGS_PATH,
                               TAG_REVIEW_PATH, STATE_PATH)]


# ---------------------------------------------------------------- helpers

def fetch_api(endpoint, search=None):
    """Page through the live API. Returns an empty list when the search matches nothing."""
    url = API_URL.format(endpoint=endpoint)
    records, skip = [], 0
    while True:
        params = {"limit": 1000, "skip": skip}
        if search:
            params["search"] = search
        if API_KEY:
            params["api_key"] = API_KEY
        for attempt in range(4):
            resp = requests.get(url, params=params, headers=HEADERS, timeout=120)
            if resp.status_code in (200, 404):
                break
            print(f"    got HTTP {resp.status_code}, retrying...")
            time.sleep(2 ** attempt)
        if resp.status_code == 404:   # openFDA's way of saying "no matches"
            return records
        resp.raise_for_status()
        page = resp.json()
        results = page.get("results", [])
        records.extend(results)
        skip += len(results)
        if not results or skip >= page["meta"]["results"]["total"]:
            return records
        if skip >= 25000:
            raise RuntimeError("API paging stops at 25,000 records. This needs the bulk files.")
        time.sleep(0.3)   # be polite to the server


def read_state(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write_state(state, path):
    path.write_text(json.dumps(state, indent=2) + "\n")


def append_run_log(path, row):
    """Add one row per run to run_log.csv. GitHub shows CSV files as a table.

    If the columns changed since the file was started, it gets rewritten with the new
    header. Old rows keep their values, with blanks in the new columns.
    """
    old_rows, header_ok = [], False
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header_ok = reader.fieldnames == RUN_LOG_COLUMNS
            if not header_ok:
                old_rows = list(reader)
    mode = "a" if header_ok else "w"
    with open(path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUN_LOG_COLUMNS, restval="", extrasaction="ignore")
        if not header_ok:
            writer.writeheader()
            writer.writerows(old_rows)
        writer.writerow(row)


# ---------------------------------------------------------------- recalls

def merge_recalls(con, records, path, versions_path, today, now, workdir):
    """Merge a batch of recalls into storage.

    Two tables come out of it:
      recalls          one row per recall, FDA's latest version, used for the analysis
      recall_versions  every distinct version we've seen, saved again only when FDA
                       actually changes a recall's content
    """
    rows, columns = flatten(records)
    numbered = [r for r in rows if r.get("recall_number")]
    no_number = len(rows) - len(numbered)

    if not numbered:
        total = 0
        if path.exists():
            total = con.execute(f"SELECT count(*) FROM read_parquet('{path.as_posix()}')").fetchone()[0]
        return {"pulled": len(rows), "new": 0, "changed": 0, "total": total, "no_number": no_number}

    # A fingerprint of the recall report itself. openfda is FDA's annotation layer, which
    # gets refreshed on its own schedule, so it's left out to avoid fake "changes".
    for r in numbered:
        report = {k: v for k, v in r.items() if k != "openfda"}
        r["_content_hash"] = hashlib.md5(json.dumps(report, sort_keys=True).encode()).hexdigest()
    columns = sorted(set(columns) | {"_content_hash"})

    stamps = (f"DATE '{today.isoformat()}' AS _first_seen, "
              f"TIMESTAMP '{now:%Y-%m-%d %H:%M:%S}' AS _pulled_at")
    load_batch(con, numbered, columns, "recall_batch", workdir, extra=stamps)

    # New = recall numbers that weren't stored by any earlier run.
    if path.exists():
        new = con.execute(f"""
            SELECT count(DISTINCT recall_number) FROM recall_batch
            WHERE recall_number NOT IN (SELECT recall_number FROM read_parquet('{path.as_posix()}'))
        """).fetchone()[0]
    else:
        new = con.execute("SELECT count(DISTINCT recall_number) FROM recall_batch").fetchone()[0]

    # Version history: keep a batch row only if we've never seen that exact content before.
    v = versions_path.as_posix()
    if versions_path.exists():
        con.execute(f"""
            CREATE OR REPLACE TABLE recall_fresh AS
            SELECT DISTINCT * FROM recall_batch b
            WHERE NOT EXISTS (
                SELECT 1 FROM read_parquet('{v}') o
                WHERE o.recall_number = b.recall_number AND o._content_hash = b._content_hash
            )
        """)
        changed = con.execute(f"""
            SELECT count(DISTINCT recall_number) FROM recall_fresh
            WHERE recall_number IN (SELECT recall_number FROM read_parquet('{v}'))
        """).fetchone()[0]
        write_parquet(con, f"SELECT * FROM read_parquet('{v}') "
                           "UNION ALL BY NAME SELECT * FROM recall_fresh", versions_path)
    else:
        con.execute("CREATE OR REPLACE TABLE recall_fresh AS SELECT DISTINCT * FROM recall_batch")
        changed = 0
        write_parquet(con, "SELECT * FROM recall_fresh", versions_path)

    # Latest table: the newest version of each recall wins, keeping the earliest first-seen date.
    source = "SELECT * FROM recall_batch"
    if path.exists():
        source = (f"SELECT * FROM read_parquet('{path.as_posix()}') "
                  "UNION ALL BY NAME SELECT * FROM recall_batch")
    con.execute(f"""
        CREATE OR REPLACE TABLE recalls AS
        WITH combined AS ({source}),
        ranked AS (
            SELECT *,
                   min(_first_seen) OVER (PARTITION BY recall_number) AS first_seen_min,
                   row_number() OVER (PARTITION BY recall_number ORDER BY _pulled_at DESC) AS rn
            FROM combined
        )
        SELECT * EXCLUDE (_first_seen, first_seen_min, rn), first_seen_min AS _first_seen
        FROM ranked
        WHERE rn = 1
    """)
    write_parquet(con, "SELECT * FROM recalls ORDER BY recall_number", path)
    total = con.execute("SELECT count(*) FROM recalls").fetchone()[0]
    return {"pulled": len(rows), "new": new, "changed": changed, "total": total,
            "no_number": no_number}


# ---------------------------------------------------------------- shortages

def save_snapshot(con, records, path, current_path, today, workdir):
    """Store today's full shortage list as a dated snapshot and report what changed.

    Key: package NDC + list type + company. The same package can sit on the shortage
    list and the discontinuation list at the same time, or be listed under two
    companies, so the NDC alone isn't unique. If FDA still lists the exact same key
    twice, one row is kept and fda_listings records how many there were.
    """
    rows, columns = flatten(records)
    for needed in ("package_ndc", "generic_name", "company_name", "presentation", "status",
                   "update_date"):
        if needed not in columns:
            columns.append(needed)
    load_batch(con, rows, columns, "shortage_batch", workdir)

    day = f"DATE '{today.isoformat()}'"
    con.execute(f"""
        CREATE OR REPLACE TABLE shortage_today AS
        WITH base AS (
            SELECT *,
                   CASE WHEN status ILIKE '%discontinu%' THEN 'discontinuation'
                        ELSE 'shortage' END AS list_type
            FROM shortage_batch
        ),
        keyed AS (
            SELECT {day} AS snapshot_date,
                   CASE WHEN nullif(trim(package_ndc), '') IS NOT NULL
                        THEN concat_ws('|', trim(package_ndc), list_type, lower(trim(company_name)))
                        ELSE 'h:' || md5(lower(concat_ws('|', generic_name, company_name,
                                                         presentation, list_type)))
                   END AS shortage_key,
                   *
            FROM base
        ),
        ranked AS (
            SELECT *,
                   count(*) OVER (PARTITION BY shortage_key) AS fda_listings,
                   row_number() OVER (
                       PARTITION BY shortage_key
                       ORDER BY try_strptime(update_date, '%m/%d/%Y') DESC NULLS LAST
                   ) AS rn
            FROM keyed
        )
        SELECT * EXCLUDE (rn) FROM ranked WHERE rn = 1
    """)

    # Today's full rows, every column, replaced each run.
    write_parquet(con, "SELECT * FROM shortage_today ORDER BY shortage_key", current_path)

    # The daily history keeps the lean columns, so the file stays small for years.
    today_columns = {c for (c,) in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'shortage_today'"
    ).fetchall()}
    lean = ", ".join(f'"{c}"' for c in SNAPSHOT_COLUMNS if c in today_columns)
    source = f"SELECT {lean} FROM shortage_today"
    if path.exists():
        source = (f"SELECT * FROM read_parquet('{path.as_posix()}') WHERE snapshot_date <> {day} "
                  f"UNION ALL BY NAME SELECT {lean} FROM shortage_today")
    con.execute(f"CREATE OR REPLACE TABLE shortage_snapshots AS {source}")
    write_parquet(con, "SELECT * FROM shortage_snapshots ORDER BY snapshot_date, shortage_key", path)

    n_rows, n_new, n_dropped, n_status, prev = con.execute(f"""
        WITH prev_day AS (
            SELECT max(snapshot_date) AS d FROM shortage_snapshots WHERE snapshot_date < {day}
        ),
        prev AS (
            SELECT shortage_key, status FROM shortage_snapshots
            WHERE snapshot_date = (SELECT d FROM prev_day)
        ),
        cur AS (
            SELECT shortage_key, status FROM shortage_snapshots WHERE snapshot_date = {day}
        )
        SELECT
            (SELECT count(*) FROM cur),
            (SELECT count(*) FROM cur WHERE shortage_key NOT IN (SELECT shortage_key FROM prev)),
            (SELECT count(*) FROM prev WHERE shortage_key NOT IN (SELECT shortage_key FROM cur)),
            (SELECT count(*) FROM cur JOIN prev USING (shortage_key)
             WHERE cur.status IS DISTINCT FROM prev.status),
            (SELECT d FROM prev_day)
    """).fetchone()
    return {"rows": n_rows, "new": n_new, "dropped": n_dropped, "status_changes": n_status,
            "collapsed": len(rows) - n_rows, "compared_to": prev}


def write_shortage_history(con, path):
    """One row per shortage: when we first and last saw it, and its latest status."""
    write_parquet(con, """
        SELECT shortage_key,
               min(snapshot_date) AS first_seen,
               max(snapshot_date) AS last_seen,
               count(DISTINCT snapshot_date) AS days_seen,
               arg_max(status, snapshot_date) AS latest_status,
               arg_max(generic_name, snapshot_date) AS generic_name,
               arg_max(company_name, snapshot_date) AS company_name
        FROM shortage_snapshots
        GROUP BY shortage_key
        ORDER BY shortage_key
    """, path)


# ---------------------------------------------------------------- NDC directory

def save_ndc(con, records, path, workdir):
    """Keep the NDC directory columns we need for matching and counting makers."""
    rows, columns = flatten(records)
    load_batch(con, rows, columns, "ndc_batch", workdir)
    keep = ", ".join(f'"{c}"' for c in NDC_COLUMNS if c in columns)
    write_parquet(con, f"SELECT {keep} FROM ndc_batch", path)
    return len(rows)


# ---------------------------------------------------------------- run

def run(data_dir, now, stats):
    """Do the whole run on a staged copy, then swap the files in only if every step worked."""
    today = now.date()
    con = duckdb.connect()
    try:
        with tempfile.TemporaryDirectory() as workdir:
            stage = Path(workdir) / "stage"
            stage.mkdir()
            for name in DATA_FILES:
                if (data_dir / name).exists():
                    shutil.copy2(data_dir / name, stage / name)
            state_path = stage / STATE_PATH.name
            state = read_state(state_path)
            manifest = None

            # 1. Recalls
            recalls = stage / RECALLS_PATH.name
            if recalls.exists():
                start = (today - timedelta(days=RECALL_WINDOW_DAYS)).strftime("%Y%m%d")
                mode = f"last {RECALL_WINDOW_DAYS} days"
                records = fetch_api("enforcement", search=f"report_date:[{start} TO {today:%Y%m%d}]")
            else:
                mode = "full history (first run)"
                manifest = get_json(MANIFEST_URL)
                records = from_bulk_files(manifest, "enforcement") or fetch_api("enforcement")
            r = merge_recalls(con, records, recalls, stage / RECALL_VERSIONS_PATH.name,
                              today, now, workdir)
            stats.update(recalls_mode=mode, recalls_pulled=r["pulled"], recalls_new=r["new"],
                         recalls_changed=r["changed"], recalls_total=r["total"])
            print(f"Recalls ({mode}): pulled {r['pulled']:,}, new {r['new']:,}, "
                  f"changed by FDA {r['changed']:,}, total {r['total']:,}, "
                  f"skipped without a recall number {r['no_number']}")

            # 2. Shortages
            records = fetch_api("shortages")
            if not records:
                raise RuntimeError("The shortage list came back empty. Stopping before saving anything.")
            s = save_snapshot(con, records, stage / SNAPSHOTS_PATH.name,
                              stage / CURRENT_SHORTAGES_PATH.name, today, workdir)
            write_shortage_history(con, stage / HISTORY_PATH.name)
            stats.update(shortage_rows=s["rows"], shortages_new=s["new"],
                         shortages_dropped=s["dropped"], shortage_status_changes=s["status_changes"],
                         duplicate_listings_merged=s["collapsed"])
            if s["compared_to"] is None:
                change = "first snapshot, nothing to compare yet"
            else:
                change = (f"vs {s['compared_to']}: new {s['new']}, dropped off {s['dropped']}, "
                          f"status changes {s['status_changes']}")
            print(f"Shortages ({today}): {s['rows']:,} rows "
                  f"({s['collapsed']} duplicate listings merged), {change}")

            # 3. NDC directory, weekly
            ndc = stage / NDC_PATH.name
            last = state.get("ndc_refreshed")
            if ndc.exists() and last and (today - date.fromisoformat(last)).days < NDC_REFRESH_DAYS:
                stats["ndc_refreshed"] = "no"
                print(f"NDC directory: last refreshed {last}, skipping until it's {NDC_REFRESH_DAYS} days old")
            else:
                manifest = manifest or get_json(MANIFEST_URL)
                records = from_bulk_files(manifest, "ndc")
                if not records:
                    raise RuntimeError("The NDC directory isn't in openFDA's bulk file list.")
                n = save_ndc(con, records, ndc, workdir)
                state["ndc_refreshed"] = today.isoformat()
                stats["ndc_refreshed"] = "yes"
                print(f"NDC directory: refreshed, {n:,} products")

            # 4. Matching IDs: normalized NDCs and firm keys
            ids = build_ids(con, ndc, recalls, stage / SNAPSHOTS_PATH.name, {
                "ndc_directory": stage / NDC_DIRECTORY_PATH.name,
                "recall_ids": stage / RECALL_IDS_PATH.name,
                "shortage_ids": stage / SHORTAGE_IDS_PATH.name,
            }, workdir)
            stats.update(recalls_with_ndc_pct=ids["recalls_with_ndc_pct"],
                         shortages_with_ndc_pct=ids["shortages_with_ndc_pct"])
            print(f"IDs: NDC found for {ids['recalls_with_ndc']:,} of {ids['recalls']:,} recalls "
                  f"({ids['recalls_with_ndc_pct']}%) and {ids['shortages_with_ndc']:,} of "
                  f"{ids['shortages']:,} shortage listings ({ids['shortages_with_ndc_pct']}%), "
                  f"{ids['directory_packages']:,} directory packages")

            # 5. Matching: which drug each recall is about, and which shortages share it
            m = build_matches(con, {
                "ndc": ndc, "recalls": recalls,
                "recall_ids": stage / RECALL_IDS_PATH.name,
                "shortage_ids": stage / SHORTAGE_IDS_PATH.name,
                "snapshots": stage / SNAPSHOTS_PATH.name,
                "recall_drugs": stage / RECALL_DRUGS_PATH.name,
                "shortage_drugs": stage / SHORTAGE_DRUGS_PATH.name,
                "links": stage / LINKS_PATH.name,
                "unmatched": stage / UNMATCHED_PATH.name,
            }, workdir)
            stats.update(recalls_identified_pct=m["identified_pct"], recalls_unmatched=m["unmatched"],
                         recalls_linked=m["linked_recalls"], shortages_linked=m["linked_shortages"])
            levels = ", ".join(f"{name.replace('_', ' ')} {n:,}" for name, n in m["by_level"].items())
            print(f"Matching: identified {m['identified']:,} of {m['recalls']:,} recalls "
                  f"({m['identified_pct']}%), {m['unmatched']:,} unmatched. Linked "
                  f"{m['linked_recalls']:,} recalls to {m['linked_shortages']:,} of "
                  f"{m['shortages']:,} shortage listings by their strongest match: {levels}")

            # 6. Root causes: rules first, then Claude for the rest (only when switched on)
            client = make_client() if os.getenv("SHORTAGESIGNAL_USE_CLAUDE") == "1" else None
            t = build_root_causes(recalls, stage / CLAUDE_TAGS_PATH.name,
                                  stage / ROOT_CAUSES_PATH.name, stage / TAG_REVIEW_PATH.name,
                                  workdir, client=client)
            stats.update(recalls_tagged_pct=t["tagged_pct"], tag_backlog=t["backlog"],
                         claude_calls=t["claude_calls"], claude_cost_usd=t["claude_cost"])
            note = (f"{t['claude_calls']:,} new Claude calls (about ${t['claude_cost']:.2f})"
                    if client else "Claude off for this run")
            print(f"Root causes: tagged {t['tagged']:,} of {t['recalls']:,} recalls "
                  f"({t['tagged_pct']}%), {t['by_rule']:,} by rules and {t['by_claude']:,} by "
                  f"Claude, {t['backlog']:,} still waiting. {note}. "
                  f"{t['to_review']} unsure tags to review")

            state["last_run"] = now.isoformat(timespec="seconds")
            write_state(state, state_path)

            # 7. Data checks. A failed error check stops the run before anything is saved.
            checks = collect_checks(con, {
                "recalls": recalls,
                "snapshots": stage / SNAPSHOTS_PATH.name,
                "recall_ids": stage / RECALL_IDS_PATH.name,
                "shortage_ids": stage / SHORTAGE_IDS_PATH.name,
                "ndc_directory": stage / NDC_DIRECTORY_PATH.name,
            }, stats, state, today, now, last_good_run(data_dir / RUN_LOG_PATH.name),
                read_history(data_dir / CHECK_LOG_PATH.name))
            stats["checks_failed"] = sum(c.status == "fail" for c in checks)
            stats["checks_warned"] = sum(c.status == "warn" for c in checks)
            report(checks, data_dir / CHECK_LOG_PATH.name, now.isoformat(timespec="seconds"))

            # Every step worked, so swap the staged files in.
            for name in DATA_FILES:
                staged = stage / name
                if staged.exists():
                    tmp = data_dir / (name + ".tmp")
                    shutil.copy2(staged, tmp)
                    os.replace(tmp, data_dir / name)
    finally:
        con.close()


def run_and_log(data_dir):
    """Run once and add a row to run_log.csv, whether the run worked or not."""
    data_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    started = time.monotonic()
    stats = {}
    status, error = "failed", "interrupted"
    try:
        run(data_dir, now, stats)
        status, error = "success", ""
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        append_run_log(data_dir / RUN_LOG_PATH.name, {
            "run_at_utc": now.isoformat(timespec="seconds"), "status": status,
            "seconds": round(time.monotonic() - started, 1), **stats, "error": error,
        })


def main():
    run_and_log(DATA_DIR)
    print(f"\nDone. Files are in {DATA_DIR}")


if __name__ == "__main__":
    main()
