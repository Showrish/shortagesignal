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

Storage: one Parquet file per table in DATA_DIR, plus state.json for bookkeeping.
DuckDB is only the engine that reads and writes those files.

Run:  python -m shortagesignal.ingest
"""
import hashlib
import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import requests

from shortagesignal.config import (
    DATA_DIR,
    HISTORY_PATH,
    NDC_PATH,
    RECALL_VERSIONS_PATH,
    RECALLS_PATH,
    SNAPSHOTS_PATH,
    STATE_PATH,
)
from shortagesignal.pull_full_history import API_KEY, API_URL, HEADERS, MANIFEST_URL
from shortagesignal.pull_full_history import from_bulk_files, get_json

RECALL_WINDOW_DAYS = 60   # FDA sometimes corrects past reports, so re-pull a safety window
NDC_REFRESH_DAYS = 7
NDC_COLUMNS = [
    "product_ndc", "generic_name", "brand_name", "labeler_name", "dosage_form", "route",
    "product_type", "marketing_category", "active_ingredients", "packaging",
    "marketing_start_date", "marketing_end_date", "listing_expiration_date", "finished",
]


# ---------------------------------------------------------------- helpers

def flatten(records):
    """Turn every value into text, with nested fields as JSON strings.

    The shape of nested fields changes from pull to pull, which breaks merging old and
    new data. As text, the columns look the same every time, and SQL can still parse
    the JSON later when it's needed.
    """
    rows, columns = [], set()
    for rec in records:
        row = {}
        for key, value in rec.items():
            if isinstance(value, (dict, list)):
                row[key] = json.dumps(value, sort_keys=True)
            elif value is None:
                row[key] = None
            else:
                row[key] = str(value)
        rows.append(row)
        columns.update(row)
    return rows, sorted(columns)


def load_batch(con, rows, columns, name, workdir, extra=""):
    """Load rows into a DuckDB table where every column is text."""
    path = Path(workdir) / f"{name}.ndjson"
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    spec = ", ".join(f"'{c}': 'VARCHAR'" for c in columns)
    extra_cols = f", {extra}" if extra else ""
    con.execute(f"""
        CREATE OR REPLACE TABLE {name} AS
        SELECT *{extra_cols}
        FROM read_json('{path.as_posix()}',
                       format = 'newline_delimited',
                       columns = {{{spec}}})
    """)


def write_parquet(con, query, path):
    """Write a query result to Parquet via a temp file, so a crash never leaves half a file."""
    tmp = path.with_name(path.name + ".tmp")
    con.execute(f"COPY ({query}) TO '{tmp.as_posix()}' (FORMAT PARQUET)")
    os.replace(tmp, path)


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


def read_state():
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def write_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


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

def save_snapshot(con, records, path, today, workdir):
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

    source = "SELECT * FROM shortage_today"
    if path.exists():
        source = (f"SELECT * FROM read_parquet('{path.as_posix()}') WHERE snapshot_date <> {day} "
                  "UNION ALL BY NAME SELECT * FROM shortage_today")
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

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()
    state = read_state()
    con = duckdb.connect()
    manifest = None

    with tempfile.TemporaryDirectory() as workdir:
        # 1. Recalls
        if RECALLS_PATH.exists():
            start = (today - timedelta(days=RECALL_WINDOW_DAYS)).strftime("%Y%m%d")
            mode = f"last {RECALL_WINDOW_DAYS} days"
            records = fetch_api("enforcement", search=f"report_date:[{start} TO {today:%Y%m%d}]")
        else:
            mode = "full history (first run)"
            manifest = get_json(MANIFEST_URL)
            records = from_bulk_files(manifest, "enforcement") or fetch_api("enforcement")
        r = merge_recalls(con, records, RECALLS_PATH, RECALL_VERSIONS_PATH, today, now, workdir)
        print(f"Recalls ({mode}): pulled {r['pulled']:,}, new {r['new']:,}, "
              f"changed by FDA {r['changed']:,}, total {r['total']:,}, "
              f"skipped without a recall number {r['no_number']}")

        # 2. Shortages
        records = fetch_api("shortages")
        if not records:
            raise RuntimeError("The shortage list came back empty. Stopping before saving anything.")
        s = save_snapshot(con, records, SNAPSHOTS_PATH, today, workdir)
        write_shortage_history(con, HISTORY_PATH)
        if s["compared_to"] is None:
            change = "first snapshot, nothing to compare yet"
        else:
            change = (f"vs {s['compared_to']}: new {s['new']}, dropped off {s['dropped']}, "
                      f"status changes {s['status_changes']}")
        print(f"Shortages ({today}): {s['rows']:,} rows "
              f"({s['collapsed']} duplicate listings merged), {change}")

        # 3. NDC directory, weekly
        last = state.get("ndc_refreshed")
        if NDC_PATH.exists() and last and (today - date.fromisoformat(last)).days < NDC_REFRESH_DAYS:
            print(f"NDC directory: last refreshed {last}, skipping until it's {NDC_REFRESH_DAYS} days old")
        else:
            manifest = manifest or get_json(MANIFEST_URL)
            records = from_bulk_files(manifest, "ndc")
            if not records:
                raise RuntimeError("The NDC directory isn't in openFDA's bulk file list.")
            n = save_ndc(con, records, NDC_PATH, workdir)
            state["ndc_refreshed"] = today.isoformat()
            print(f"NDC directory: refreshed, {n:,} products")

    state["last_run"] = now.isoformat(timespec="seconds")
    write_state(state)
    con.close()
    print(f"\nDone. Files are in {DATA_DIR}")


if __name__ == "__main__":
    main()
