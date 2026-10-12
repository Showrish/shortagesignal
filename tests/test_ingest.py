"""Tests for the daily pulls. They use small fake records, so no internet is needed."""
import csv
from datetime import date, datetime

import duckdb
import pytest

from shortagesignal import ingest
from shortagesignal.ingest import append_run_log, merge_recalls, save_snapshot
from shortagesignal.storage import flatten


def test_flatten_turns_nested_fields_into_text():
    rows, columns = flatten([{"a": 1, "b": {"x": [1, 2]}, "c": None}, {"d": "hi"}])
    assert columns == ["a", "b", "c", "d"]
    assert rows[0] == {"a": "1", "b": '{"x": [1, 2]}', "c": None}
    assert rows[1] == {"d": "hi"}


# ---------------------------------------------------------------- recalls

def recall(number, status):
    return {"recall_number": number, "status": status, "openfda": {}}


def test_merge_recalls_keeps_latest_and_every_version(tmp_path):
    con = duckdb.connect()
    path = tmp_path / "recalls.parquet"
    versions = tmp_path / "recall_versions.parquet"
    batch = [recall("D-1", "Terminated"), recall("D-2", "Ongoing"), {"status": "no recall number"}]

    merge_recalls(con, [recall("D-1", "Ongoing")], path, versions,
                  date(2026, 10, 1), datetime(2026, 10, 1, 6), tmp_path)
    second = merge_recalls(con, batch, path, versions,
                           date(2026, 10, 2), datetime(2026, 10, 2, 6), tmp_path)
    third = merge_recalls(con, batch, path, versions,     # same batch again, nothing changed
                          date(2026, 10, 3), datetime(2026, 10, 3, 6), tmp_path)

    latest = con.execute(
        f"SELECT recall_number, status, _first_seen FROM read_parquet('{path.as_posix()}') ORDER BY 1"
    ).fetchall()
    assert latest == [("D-1", "Terminated", date(2026, 10, 1)), ("D-2", "Ongoing", date(2026, 10, 2))]
    assert second == {"pulled": 3, "new": 1, "changed": 1, "total": 2, "no_number": 1}
    assert third == {"pulled": 3, "new": 0, "changed": 0, "total": 2, "no_number": 1}

    n_versions = con.execute(
        f"SELECT count(*) FROM read_parquet('{versions.as_posix()}')"
    ).fetchone()[0]
    assert n_versions == 3   # D-1 twice because FDA changed it, D-2 once, no repeats on day 3


# ---------------------------------------------------------------- shortages

def shortage(ndc, status, name="drug a", **extra):
    return {"package_ndc": ndc, "status": status, "generic_name": name,
            "company_name": "Some Co", "presentation": "1 vial", "update_date": "10/01/2026",
            **extra}


def snapshot_keys(con, path):
    return sorted(k for (k,) in con.execute(
        f"SELECT DISTINCT shortage_key FROM read_parquet('{path.as_posix()}')"
    ).fetchall())


def test_snapshot_rerun_same_day_replaces_and_tracks_changes(tmp_path):
    con = duckdb.connect()
    path, current = tmp_path / "snapshots.parquet", tmp_path / "current.parquet"
    day_one = [shortage("0409-1234-01", "Current"), shortage(None, "Current", name="drug b")]

    first = save_snapshot(con, day_one, path, current, date(2026, 10, 1), tmp_path)
    save_snapshot(con, day_one, path, current, date(2026, 10, 1), tmp_path)   # same day again
    count = con.execute(f"SELECT count(*) FROM read_parquet('{path.as_posix()}')").fetchone()[0]
    assert first["compared_to"] is None
    assert count == 2   # replaced, not doubled

    second = save_snapshot(con, [shortage("0409-1234-01", "Resolved")], path, current,
                           date(2026, 10, 2), tmp_path)
    assert second == {"rows": 1, "new": 0, "dropped": 1, "status_changes": 1,
                      "collapsed": 0, "compared_to": date(2026, 10, 1)}

    keys = snapshot_keys(con, path)
    assert keys[0] == "0409-1234-01|shortage|some co"
    assert keys[1].startswith("h:")   # no NDC, so the key falls back to a hash


def test_snapshot_separates_list_types_and_merges_true_duplicates(tmp_path):
    con = duckdb.connect()
    path, current = tmp_path / "snapshots.parquet", tmp_path / "current.parquet"
    listings = [
        shortage("0009-0775-26", "Current", contact_info="call the company"),
        shortage("0009-0775-26", "To Be Discontinued"),   # same package, other list
        shortage("65219-080-05", "To Be Discontinued"),
        shortage("65219-080-05", "To Be Discontinued"),   # FDA listed it twice
    ]
    result = save_snapshot(con, listings, path, current, date(2026, 10, 1), tmp_path)

    assert result["rows"] == 3 and result["collapsed"] == 1
    assert snapshot_keys(con, path) == [
        "0009-0775-26|discontinuation|some co",
        "0009-0775-26|shortage|some co",
        "65219-080-05|discontinuation|some co",
    ]
    listed = con.execute(
        f"SELECT fda_listings FROM read_parquet('{path.as_posix()}') WHERE shortage_key LIKE '65219%'"
    ).fetchone()[0]
    assert listed == 2

    # The current file keeps every column, the history only the lean ones.
    assert "contact_info" in con.sql(f"SELECT * FROM read_parquet('{current.as_posix()}')").columns
    assert "contact_info" not in con.sql(f"SELECT * FROM read_parquet('{path.as_posix()}')").columns


# ---------------------------------------------------------------- run log and failures

def test_run_log_writes_header_once(tmp_path):
    log = tmp_path / "run_log.csv"
    append_run_log(log, {"run_at_utc": "2026-10-11T12:00:00", "status": "success"})
    append_run_log(log, {"run_at_utc": "2026-10-12T12:00:00", "status": "failed", "error": "boom"})
    with open(log, newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["status"] for r in rows] == ["success", "failed"]
    assert rows[1]["error"] == "boom"


def test_run_log_upgrades_an_old_header(tmp_path):
    log = tmp_path / "run_log.csv"
    log.write_text("run_at_utc,status\n2026-10-11T12:00:00,success\n")
    append_run_log(log, {"run_at_utc": "2026-10-12T12:00:00", "status": "success",
                         "recalls_with_ndc_pct": "60.1"})
    with open(log, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == ingest.RUN_LOG_COLUMNS
    assert [r["run_at_utc"] for r in rows] == ["2026-10-11T12:00:00", "2026-10-12T12:00:00"]
    assert rows[1]["recalls_with_ndc_pct"] == "60.1"


def test_failed_run_keeps_old_data_and_logs_the_failure(tmp_path, monkeypatch):
    (tmp_path / "recalls.parquet").write_bytes(b"yesterday's data")

    def broken_api(*args, **kwargs):
        raise RuntimeError("openFDA is down")

    monkeypatch.setattr(ingest, "fetch_api", broken_api)
    with pytest.raises(RuntimeError):
        ingest.run_and_log(tmp_path)

    assert (tmp_path / "recalls.parquet").read_bytes() == b"yesterday's data"
    with open(tmp_path / "run_log.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["status"] == "failed"
    assert "openFDA is down" in rows[-1]["error"]
