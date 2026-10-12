"""Reading and writing tables. Shared by every pipeline step."""
import json
import os
from pathlib import Path


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
