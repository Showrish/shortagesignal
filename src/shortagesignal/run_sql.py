"""
Run a SQL file against the project's tables and print the first rows.

  python -m shortagesignal.run_sql sql/root_cause_rules.sql        first 20 rows
  python -m shortagesignal.run_sql sql/root_cause_rules.sql 50     first 50 rows

Every table is there under a short name, so a query can just say FROM recalls:
  recalls, recall_versions, recall_ids, recall_drugs, unmatched_recalls,
  shortage_snapshots, shortages_current, shortage_history, shortage_ids,
  shortage_drugs, links, ndc_directory, root_causes, claude_tags, claude_drugs,
  recall_risk, drug_makers, weekly_recalls, and answer_key (your hand audit).
"""
import sys
import time
from pathlib import Path

import duckdb

from shortagesignal.config import (
    CLAUDE_DRUGS_PATH,
    CLAUDE_TAGS_PATH,
    CURRENT_SHORTAGES_PATH,
    DATA_DIR,
    HISTORY_PATH,
    LINKS_PATH,
    MAKERS_PATH,
    NDC_DIRECTORY_PATH,
    RECALL_DRUGS_PATH,
    RECALL_IDS_PATH,
    RECALL_VERSIONS_PATH,
    RECALLS_PATH,
    RISK_PATH,
    ROOT,
    ROOT_CAUSES_PATH,
    SHORTAGE_DRUGS_PATH,
    SHORTAGE_IDS_PATH,
    SNAPSHOTS_PATH,
    UNMATCHED_PATH,
    WEEKLY_PATH,
)

TABLES = {
    "recalls": RECALLS_PATH, "recall_versions": RECALL_VERSIONS_PATH,
    "recall_ids": RECALL_IDS_PATH, "recall_drugs": RECALL_DRUGS_PATH,
    "unmatched_recalls": UNMATCHED_PATH, "shortage_snapshots": SNAPSHOTS_PATH,
    "shortages_current": CURRENT_SHORTAGES_PATH, "shortage_history": HISTORY_PATH,
    "shortage_ids": SHORTAGE_IDS_PATH, "shortage_drugs": SHORTAGE_DRUGS_PATH,
    "links": LINKS_PATH, "ndc_directory": NDC_DIRECTORY_PATH,
    "root_causes": ROOT_CAUSES_PATH, "claude_tags": CLAUDE_TAGS_PATH,
    "claude_drugs": CLAUDE_DRUGS_PATH, "recall_risk": RISK_PATH,
    "drug_makers": MAKERS_PATH, "weekly_recalls": WEEKLY_PATH,
}


def connect(data_dir=DATA_DIR, audit_dir=ROOT / "audit"):
    """A DuckDB connection with every table that exists available by its short name."""
    con = duckdb.connect()
    for name, path in TABLES.items():
        file = Path(data_dir) / path.name
        if file.exists():
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{file.as_posix()}')")
    key = Path(audit_dir) / "answer_key.csv"
    if key.exists():
        con.execute(f"CREATE VIEW answer_key AS "
                    f"SELECT * FROM read_csv('{key.as_posix()}', all_varchar = true)")
    return con


def read_query(path):
    """The SQL in a file, without a trailing semicolon, so it can be wrapped as a subquery."""
    return Path(path).read_text().strip().rstrip(";")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.exit("usage: python -m shortagesignal.run_sql path/to/query.sql [rows]")
    query = read_query(args[0])
    limit = int(args[1]) if len(args) > 1 else 20
    con = connect()
    started = time.monotonic()
    print(con.sql(query).limit(limit))
    total = con.sql(f"SELECT count(*) FROM (\n{query}\n)").fetchone()[0]
    print(f"{total:,} rows in total, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
