"""Data checks: history rules, reporting, and the checks themselves on small files."""
import csv
from datetime import date, datetime

import duckdb
import pytest

from shortagesignal.checks import (
    Check,
    DataCheckError,
    collect_checks,
    history_flag,
    last_good_run,
    read_history,
    report,
)


@pytest.mark.parametrize(
    ("value", "previous", "expected"),
    [
        (120, [100, 110, 95, 105], None),     # normal wobble
        (300, [100, 110, 95, 105], "spike"),  # more than double the usual, by a lot
        (25, [5, 6, 4], None),                # doubled, but too small to matter
        (0, [3, 4, 2, 5, 3], "silent"),       # always busy, suddenly nothing
        (0, [3, 0, 2, 5, 3], None),           # zero has happened before
        (500, [100], None),                   # not enough history yet
    ],
)
def test_history_flag(value, previous, expected):
    assert history_flag(value, previous) == expected


def test_report_logs_every_check_and_only_stops_on_errors(tmp_path):
    log = tmp_path / "check_log.csv"
    warned = report([Check("a", "error", 0, True), Check("b", "warning", 30, False, "stale")],
                    log, "2026-10-12T12:00:00")
    assert warned == 1

    with pytest.raises(DataCheckError, match="broken"):
        report([Check("c", "error", 2, False, "broken")], log, "2026-10-13T12:00:00")

    with open(log, newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["check"], r["status"]) for r in rows] == [("a", "pass"), ("b", "warn"), ("c", "fail")]
    assert read_history(log) == {"a": [0.0], "b": [30.0], "c": [2.0]}


def test_last_good_run_skips_failed_runs(tmp_path):
    log = tmp_path / "run_log.csv"
    log.write_text("run_at_utc,status,recalls_total\n1,success,100\n2,failed,\n")
    assert last_good_run(log)["recalls_total"] == "100"
    assert last_good_run(tmp_path / "missing.csv") == {}


def write(con, path, sql):
    con.execute(f"COPY ({sql}) TO '{path.as_posix()}' (FORMAT PARQUET)")


def fixtures(con, tmp_path, recall_numbers):
    now = "TIMESTAMP '2026-10-12 12:00:00'"
    rows = ", ".join(
        f"('{n}', '20261009', 'Class II', 'Heparin Injection', 'Hospira', 'CGMP', {now})"
        for n in recall_numbers)
    f = {name: tmp_path / f"{name}.parquet" for name in
         ("recalls", "snapshots", "recall_ids", "shortage_ids", "ndc_directory")}
    write(con, f["recalls"], f"SELECT * FROM (VALUES {rows}) t(recall_number, report_date, "
          "classification, product_description, recalling_firm, reason_for_recall, _pulled_at)")
    write(con, f["snapshots"], "SELECT * FROM (VALUES (DATE '2026-10-12', 'S-1', 'Heparin', "
          "'Hospira', 'Current', '0409-4888-10', '01/15/2026', '10/08/2026')) t(snapshot_date, "
          "shortage_key, generic_name, company_name, status, package_ndc, initial_posting_date, "
          "update_date)")
    for name in ("recall_ids", "shortage_ids", "ndc_directory"):
        write(con, f[name], "SELECT '00409-4888-10' AS ndc11, '00409-4888' AS ndc9")
    return f


def run_checks(con, f, stats):
    return {c.name: c for c in collect_checks(
        con, f, stats, {"ndc_refreshed": "2026-10-11"}, date(2026, 10, 12),
        datetime(2026, 10, 12, 12), {"recalls_total": "2", "shortage_rows": "1"}, {})}


def test_clean_data_passes_every_check(tmp_path):
    con = duckdb.connect()
    f = fixtures(con, tmp_path, ["D-1", "D-2"])
    checks = run_checks(con, f, {"recalls_total": 2, "recalls_pulled": 2})
    assert [name for name, c in checks.items() if not c.ok] == []


def test_duplicates_and_a_shrinking_table_fail(tmp_path):
    con = duckdb.connect()
    f = fixtures(con, tmp_path, ["D-1", "D-1"])
    checks = run_checks(con, f, {"recalls_total": 1, "recalls_pulled": 2})
    assert checks["recall numbers are unique"].status == "fail"
    assert checks["recall table never shrinks"].status == "fail"
