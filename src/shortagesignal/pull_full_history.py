"""
Day 1: pull the full FDA history into a local database.

What it does, in plain English:
  1. Downloads every FDA drug recall (enforcement report) and the drug shortage list.
  2. Saves each one as a raw file in data/raw/ (one record per line).
  3. Loads both into a DuckDB database file: data/shortagesignal.duckdb

How it gets the data:
  - First choice: openFDA's bulk download files (one zip per dataset, the full history).
  - Fallback: the live API, 1,000 records per request, if a bulk file isn't listed.

Run:  python -m shortagesignal.pull_full_history
"""
import io
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone

import requests

from shortagesignal.config import DB_PATH, RAW_DIR

MANIFEST_URL = "https://api.fda.gov/download.json"   # openFDA's list of bulk files
API_URL = "https://api.fda.gov/drug/{endpoint}.json"
HEADERS = {"User-Agent": "ShortageSignal/0.1 (student portfolio project)"}
API_KEY = os.getenv("OPENFDA_API_KEY")              # optional, only raises rate limits

# our table name -> openFDA endpoint name
DATASETS = {"recalls": "enforcement", "shortages": "shortages"}


def get_json(url, params=None):
    """GET a URL and return JSON, retrying a few times if the server hiccups."""
    for attempt in range(4):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=120)
        if resp.status_code == 200:
            return resp.json()
        print(f"    got HTTP {resp.status_code}, retrying...")
        time.sleep(2 ** attempt)
    resp.raise_for_status()


def from_bulk_files(manifest, endpoint):
    """Download the full dataset from openFDA's bulk zip files. Returns None if not listed."""
    try:
        info = manifest["results"]["drug"][endpoint]
        partitions = info["partitions"]
    except (KeyError, TypeError):
        return None
    print(f"  bulk files exported on {info.get('export_date', 'unknown date')}")
    records = []
    for part in partitions:
        print(f"  downloading {part['file']}")
        resp = requests.get(part["file"], headers=HEADERS, timeout=600)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                with zf.open(name) as f:
                    records.extend(json.load(f)["results"])
    return records


def from_api(endpoint):
    """Page through the live API, 1,000 records per request."""
    records, skip = [], 0
    while True:
        params = {"limit": 1000, "skip": skip}
        if API_KEY:
            params["api_key"] = API_KEY
        page = get_json(API_URL.format(endpoint=endpoint), params)
        records.extend(page.get("results", []))
        total = page["meta"]["results"]["total"]
        skip += 1000
        if skip >= total or not page.get("results"):
            return records
        if skip >= 25000:
            sys.exit("API paging stops at 25,000 records. This dataset needs the bulk files.")
        time.sleep(0.3)  # be polite to the server


def save_ndjson(records, path):
    """Write one JSON record per line, a format DuckDB reads directly."""
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def load_into_duckdb(files):
    """Create one raw table per dataset. Re-running replaces them."""
    import duckdb

    con = duckdb.connect(str(DB_PATH))
    for table, path in files.items():
        con.execute(f"""
            CREATE OR REPLACE TABLE raw_{table} AS
            SELECT *, current_timestamp AS _loaded_at
            FROM read_json_auto('{path.as_posix()}',
                                format = 'newline_delimited',
                                sample_size = -1)
        """)
        n = con.execute(f"SELECT count(*) FROM raw_{table}").fetchone()[0]
        print(f"  raw_{table}: {n:,} rows")
    con.close()


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print("Reading openFDA's bulk file list...")
    manifest = get_json(MANIFEST_URL)

    files, summary = {}, []
    for table, endpoint in DATASETS.items():
        print(f"\n[{table}] openFDA endpoint: drug/{endpoint}")
        records = from_bulk_files(manifest, endpoint)
        source = "bulk files"
        if records is None:
            print("  not in the bulk file list, using the API instead")
            records = from_api(endpoint)
            source = "API"
        path = RAW_DIR / f"{table}.ndjson"
        save_ndjson(records, path)
        files[table] = path
        summary.append({"dataset": table, "source": source, "records": len(records)})
        print(f"  saved {len(records):,} records to {path}")

    print("\nLoading into DuckDB...")
    load_into_duckdb(files)

    with open(RAW_DIR / "pull_summary.json", "w") as f:
        pulled_at = datetime.now(timezone.utc).isoformat()
        json.dump({"pulled_at": pulled_at, "datasets": summary}, f, indent=2)
    print(f"\nDone. Database: {DB_PATH}")
    print("Next: python -m shortagesignal.day1_explore")


if __name__ == "__main__":
    main()
