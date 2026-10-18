"""Risk flags, maker counts and the weekly control chart."""
import csv
from datetime import date, timedelta

import duckdb
import pytest

from shortagesignal.risk import (
    build_control_chart,
    build_risk,
    control_limits,
    drug_labelers,
    is_injectable,
    score_events,
    score_recall,
    summarize,
)
from shortagesignal.storage import load_batch, write_parquet


def save(con, rows, path, workdir):
    columns = sorted({c for r in rows for c in r})
    load_batch(con, rows, columns, "fixture", workdir)
    write_parquet(con, "SELECT * FROM fixture", path)


def test_score_recall_adds_up_the_signs():
    assert score_recall("Sterility", 1, True) == (5, "high", "sterility, 1 labeler, injectable")
    assert score_recall("Sterility", 2, False) == (4, "high", "sterility, 2 labelers")
    assert score_recall("CGMP", 4, True) == (2, "watch", "4 labelers, injectable")
    assert score_recall("Impurities", 12, True) == (1, "low", "injectable")
    assert score_recall("CGMP", None, False) == (0, "low", "")


def test_is_injectable():
    assert is_injectable("Heparin Sodium Injection, 10 mL vial")
    assert is_injectable("Morphine 1 mg/mL in a 30 mL syringe")
    assert is_injectable("Sodium chloride IV bag")
    assert not is_injectable("Amoxicillin 500 mg capsules")
    assert not is_injectable("Ivermectin 3 mg tablets")
    assert not is_injectable(None)
    assert is_injectable("Carboplatin 10 mg/mL, 45 mL vial")                  # a vial counts
    assert not is_injectable("Lubricant Eye Drops, 0.4 mL single-use vials")   # unless it's for the eye
    assert is_injectable("Ceftriaxone for Injection, antibiotic, 1 g vial")   # "otic" inside a word


def test_control_limits_use_the_moving_range():
    center, ucl, lcl = control_limits([10, 12, 8, 10])
    assert center == 10
    assert ucl == pytest.approx(10 + 2.66 * 8 / 3)
    assert lcl == pytest.approx(10 - 2.66 * 8 / 3)
    assert control_limits([5]) is None


def test_drug_labelers_counts_companies_without_repackagers(tmp_path):
    con = duckdb.connect()
    ndc = tmp_path / "ndc.parquet"
    save(con, [
        {"generic_name": "Heparin Sodium", "labeler_name": "Hospira, Inc."},
        {"generic_name": "Heparin Sodium", "labeler_name": "Hospira Inc"},     # same company
        {"generic_name": "Heparin Sodium", "labeler_name": "Fresenius Kabi USA, LLC"},
        {"generic_name": "Heparin Sodium", "labeler_name": "RemedyRepack Inc."},
        {"generic_name": "Carboplatin", "labeler_name": "Teyro Labs"},
    ], ndc, tmp_path)
    assert drug_labelers(con, ndc.as_posix()) == {"heparin sodium": 2, "carboplatin": 1}


def _risk_fixture(con, tmp_path, today):
    paths = {name: tmp_path / f"{name}.parquet" for name in
             ("recalls", "root_causes", "recall_drugs", "ndc", "risk", "makers")}
    recent, old = (today - timedelta(days=5)).strftime("%Y%m%d"), "20200101"
    save(con, [
        {"recall_number": "D-1", "event_id": "1", "report_date": recent, "classification": "Class I",
         "product_description": "Heparin Sodium Injection, 10 mL vial"},
        {"recall_number": "D-2", "event_id": "2", "report_date": old, "classification": "Class II",
         "product_description": "Carboplatin 10 mg/mL vial"},
        {"recall_number": "D-3", "event_id": "3", "report_date": recent, "classification": "Class III",
         "product_description": "Mystery powder"},
    ], paths["recalls"], tmp_path)
    save(con, [{"recall_number": "D-1", "root_cause": "Sterility"},
               {"recall_number": "D-2", "root_cause": "CGMP"},
               {"recall_number": "D-3", "root_cause": "Labeling or packaging"}],
         paths["root_causes"], tmp_path)
    save(con, [{"recall_number": "D-1", "drug_key": "heparin sodium"},
               {"recall_number": "D-2", "drug_key": "carboplatin"},
               {"recall_number": "D-3", "drug_key": None}], paths["recall_drugs"], tmp_path)
    save(con, [{"generic_name": "Heparin Sodium", "labeler_name": "Hospira, Inc."},
               {"generic_name": "Heparin Sodium", "labeler_name": "Fresenius Kabi USA, LLC"},
               {"generic_name": "Carboplatin", "labeler_name": "Teyro Labs"}], paths["ndc"], tmp_path)
    return paths


def test_build_risk_scores_every_recall_and_logs_new_ones_once(tmp_path):
    con, today = duckdb.connect(), date(2026, 10, 16)
    p = _risk_fixture(con, tmp_path, today)
    log = tmp_path / "risk_log.csv"
    args = (p["recalls"], p["root_causes"], p["recall_drugs"], p["ndc"], p["risk"], p["makers"],
            log, tmp_path, today)

    stats = build_risk(*args)
    assert stats["recent"] == {"high": 1, "watch": 0, "low": 1}   # D-1 and D-3 are recent
    assert stats["all"] == {"high": 1, "watch": 1, "low": 1}
    assert stats["logged"] == 2
    flags = dict(con.execute(
        f"SELECT recall_number, flag FROM read_parquet('{p['risk'].as_posix()}')").fetchall())
    assert flags == {"D-1": "high", "D-2": "watch", "D-3": "low"}
    points, labelers, injectable = con.execute(
        f"SELECT points, labelers, injectable FROM read_parquet('{p['risk'].as_posix()}') "
        "WHERE recall_number = 'D-1'").fetchone()
    assert (points, labelers, injectable) == (5, 2, True)

    again = build_risk(*args)                  # the same day again: nothing new to log
    assert again["logged"] == 0
    with open(log, newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["recall_number"], r["flag"], r["flagged_on"]) for r in rows] == [
        ("D-1", "high", "2026-10-16"), ("D-3", "low", "2026-10-16")]


def test_control_chart_fills_empty_weeks_and_flags_a_spike(tmp_path):
    con = duckdb.connect()
    monday = date(2026, 1, 5)
    rows, event = [], 0
    for i in range(30):
        if i == 20:
            continue                                         # a week with no recalls
        for _ in range(9 if i == 29 else 2):
            event += 1
            rows.append({"recall_number": f"D-{event}", "event_id": str(event),
                         "report_date": (monday + timedelta(weeks=i, days=2)).strftime("%Y%m%d")})
    recalls, weekly = tmp_path / "recalls.parquet", tmp_path / "weekly.parquet"
    save(con, rows, recalls, tmp_path)
    today = monday + timedelta(weeks=30, days=2)             # Wednesday of an unfinished week

    w = build_control_chart(recalls, weekly, tmp_path, today)
    assert (w["last_events"], w["signal"], w["center"]) == (9, "above", 2.0)
    table = con.execute(
        f"SELECT week, events, signal FROM read_parquet('{weekly.as_posix()}') ORDER BY week"
    ).fetchall()
    assert len(table) == 30                                  # every week, none missing
    assert table[20][1:] == (0, "below")


def test_score_events_uses_the_riskiest_product_in_each_event():
    labelers = {"heparin sodium": 2, "carboplatin": 1}
    rows = [("e1", "Sterility", True, "Heparin vial", "heparin sodium"),
            ("e1", "Sterility", True, "Carboplatin tablets", "carboplatin"),
            ("e2", "CGMP", False, "Aspirin tablets", None)]
    events = score_events(rows, labelers)
    by_cause = {e["root_cause"]: e for e in events}
    assert (by_cause["Sterility"]["labelers"], by_cause["Sterility"]["flag"]) == (1, "high")
    assert by_cause["CGMP"]["flag"] == "low"
    overall, table = summarize(events, lambda e: e["flag"])
    assert overall == 0.5
    assert table["high"] == (1, 1, 1.0, 2.0)
