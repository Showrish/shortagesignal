"""Tests for the daily pulls. They use small fake records, so no internet is needed."""
from datetime import date, datetime

import duckdb

from shortagesignal.ingest import flatten, merge_recalls, save_snapshot


def test_flatten_turns_nested_fields_into_text():
    rows, columns = flatten([{"a": 1, "b": {"x": [1, 2]}, "c": None}, {"d": "hi"}])
    assert columns == ["a", "b", "c", "d"]
    assert rows[0] == {"a": "1", "b": '{"x": [1, 2]}', "c": None}
    assert rows[1] == {"d": "hi"}


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


def shortage(ndc, status, name="drug a"):
    return {"package_ndc": ndc, "status": status, "generic_name": name,
            "company_name": "Some Co", "presentation": "1 vial", "update_date": "10/01/2026"}


def snapshot_keys(con, path):
    return sorted(k for (k,) in con.execute(
        f"SELECT DISTINCT shortage_key FROM read_parquet('{path.as_posix()}')"
    ).fetchall())


def test_snapshot_rerun_same_day_replaces_and_tracks_changes(tmp_path):
    con = duckdb.connect()
    path = tmp_path / "shortage_snapshots.parquet"
    day_one = [shortage("0409-1234-01", "Current"), shortage(None, "Current", name="drug b")]

    first = save_snapshot(con, day_one, path, date(2026, 10, 1), tmp_path)
    save_snapshot(con, day_one, path, date(2026, 10, 1), tmp_path)   # same day again
    count = con.execute(f"SELECT count(*) FROM read_parquet('{path.as_posix()}')").fetchone()[0]
    assert first["compared_to"] is None
    assert count == 2   # replaced, not doubled

    second = save_snapshot(con, [shortage("0409-1234-01", "Resolved")], path,
                           date(2026, 10, 2), tmp_path)
    assert second == {"rows": 1, "new": 0, "dropped": 1, "status_changes": 1,
                      "collapsed": 0, "compared_to": date(2026, 10, 1)}

    keys = snapshot_keys(con, path)
    assert keys[0] == "0409-1234-01|shortage|some co"
    assert keys[1].startswith("h:")   # no NDC, so the key falls back to a hash


def test_snapshot_separates_list_types_and_merges_true_duplicates(tmp_path):
    con = duckdb.connect()
    path = tmp_path / "shortage_snapshots.parquet"
    listings = [
        shortage("0009-0775-26", "Current"),
        shortage("0009-0775-26", "To Be Discontinued"),   # same package, other list
        shortage("65219-080-05", "To Be Discontinued"),
        shortage("65219-080-05", "To Be Discontinued"),   # FDA listed it twice
    ]
    result = save_snapshot(con, listings, path, date(2026, 10, 1), tmp_path)

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
