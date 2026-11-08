"""Risk flags, maker counts and the weekly control chart."""
import csv
from datetime import date, timedelta

import duckdb
import pytest

from shortagesignal.risk import (
    build_control_chart,
    build_risk,
    check_report,
    control_limits,
    drug_labelers,
    flag_lift,
    is_injectable,
    judge_log,
    log_units,
    run_backtest,
    score_recall,
    score_units,
    summarize,
    wilson,
)
from shortagesignal.config import ROOT
from shortagesignal.run_sql import read_query
from shortagesignal.storage import load_batch, write_parquet


def save(con, rows, path, workdir):
    columns = sorted({c for r in rows for c in r})
    load_batch(con, rows, columns, "fixture", workdir)
    write_parquet(con, "SELECT * FROM fixture", path)


def test_score_recall_adds_up_the_signs():
    assert score_recall(True, True) == (3, "high", "on the shortage list now, injectable")
    assert score_recall(True, False) == (2, "high", "on the shortage list now")
    assert score_recall(False, True) == (1, "watch", "injectable")
    assert score_recall(False, False) == (0, "low", "")


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
             ("recalls", "root_causes", "recall_drugs", "ndc", "risk", "makers", "links")}
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
    save(con, [  # only a current shortage listing counts as short now
        {"recall_number": "D-1", "shortage_list_type": "shortage", "shortage_status": "Resolved"},
        {"recall_number": "D-2", "shortage_list_type": "shortage", "shortage_status": "Current"},
        {"recall_number": "D-3", "shortage_list_type": "discontinuation",
         "shortage_status": "To Be Discontinued"},
    ], paths["links"], tmp_path)
    return paths


def test_build_risk_scores_every_recall_and_logs_new_ones_once(tmp_path):
    con, today = duckdb.connect(), date(2026, 10, 16)
    p = _risk_fixture(con, tmp_path, today)
    log = tmp_path / "risk_log.csv"
    args = (p["recalls"], p["root_causes"], p["recall_drugs"], p["ndc"], p["risk"], p["makers"],
            log, tmp_path, today)

    stats = build_risk(*args, links_path=p["links"])
    assert stats["recent"] == {"high": 0, "watch": 1, "low": 1}   # D-1 and D-3 are recent
    assert stats["all"] == {"high": 1, "watch": 1, "low": 1}
    assert stats["logged"] == 2
    flags = dict(con.execute(
        f"SELECT recall_number, flag FROM read_parquet('{p['risk'].as_posix()}')").fetchall())
    # D-1 is an injectable whose shortage was resolved, D-2 is short now, D-3 is neither
    assert flags == {"D-1": "watch", "D-2": "high", "D-3": "low"}
    points, labelers, injectable, short = con.execute(
        f"SELECT points, labelers, injectable, in_shortage FROM read_parquet('{p['risk'].as_posix()}') "
        "WHERE recall_number = 'D-2'").fetchone()
    assert (points, labelers, injectable, short) == (3, 1, True, True)   # makers are still counted

    again = build_risk(*args, links_path=p["links"])   # the same day again: nothing new to log
    assert again["logged"] == 0
    with open(log, newline="") as f:
        rows = list(csv.DictReader(f))
    assert [(r["recall_number"], r["flag"], r["flagged_on"]) for r in rows] == [
        ("D-1", "watch", "2026-10-16"), ("D-3", "low", "2026-10-16")]


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


def test_score_units_scores_each_drug_in_an_event_on_its_own():
    labelers = {"heparin sodium": 2, "carboplatin": 1}
    rows = [("e1", "heparin sodium", "Sterility", True, "Heparin Sodium Injection, 10 mL vial"),
            ("e1", "heparin sodium", "Sterility", True, "Heparin Sodium Injection, 30 mL vial"),
            ("e1", "carboplatin", "Sterility", False, "Carboplatin tablets"),
            ("e2", "aspirin", "CGMP", False, "Aspirin tablets")]
    units = {(u["root_cause"], u["labelers"]): u for u in score_units(rows, labelers)}
    assert len(units) == 3                              # two drugs in e1, one in e2
    heparin, carboplatin, aspirin = units[("Sterility", 2)], units[("Sterility", 1)], units[("CGMP", None)]
    assert (heparin["flag"], heparin["followed"]) == ("watch", True)   # an injectable
    assert (carboplatin["flag"], carboplatin["followed"]) == ("low", False)
    assert aspirin["flag"] == "low"
    overall, table = summarize(list(units.values()), lambda u: u["flag"])
    assert overall == pytest.approx(1 / 3)
    assert table["watch"] == (1, 1, 1.0, pytest.approx(3.0))
    assert table["low"] == (2, 0, 0.0, 0.0)


def test_lag_counts_this_drug_going_short_not_anything_in_the_event(tmp_path):
    con = duckdb.connect()
    files = {name: tmp_path / f"{name}.parquet" for name in ("recall_risk", "recalls", "links")}
    save(con, [
        # one pharmacy event with two drugs, recalled under three recall numbers
        {"recall_number": "D-1", "event_id": "e1", "drug_key": "heparin sodium", "root_cause": "Sterility"},
        {"recall_number": "D-2", "event_id": "e1", "drug_key": "carboplatin", "root_cause": "Sterility"},
        {"recall_number": "D-3", "event_id": "e1", "drug_key": "heparin sodium", "root_cause": "Sterility"},
        {"recall_number": "D-4", "event_id": "e2", "drug_key": None, "root_cause": "CGMP"},   # no drug named
        {"recall_number": "D-5", "event_id": "e3", "drug_key": "morphine", "root_cause": "CGMP"},  # too old
    ], files["recall_risk"], tmp_path)
    save(con, [{"recall_number": n, "recall_initiation_date": d} for n, d in
               [("D-1", "20250101"), ("D-2", "20250101"), ("D-3", "20250101"), ("D-4", "20250101"),
                ("D-5", "20190101")]], files["recalls"], tmp_path)
    save(con, [{"recall_number": "D-3", "shortage_list_type": "shortage", "shortage_posted": "04/11/2025"},
               {"recall_number": "D-5", "shortage_list_type": "shortage", "shortage_posted": "02/01/2019"}],
         files["links"], tmp_path)
    for name, path in files.items():
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path.as_posix()}')")

    rows = con.execute(read_query(ROOT / "sql" / "lag_by_root_cause.sql")).fetchall()
    # Heparin went short 100 days later, carboplatin didn't: 1 of 2, not "the event was followed"
    assert rows == [("Sterility", 2, 1, 50.0, 100.0)]
    followed = con.execute(read_query(ROOT / "sql" / "drugs_followed.sql")).fetchall()
    assert [(r[0], r[1], r[5]) for r in followed] == [("e1", "heparin sodium", 100)]


def test_run_backtest_works_on_the_files_a_daily_run_builds(tmp_path):
    con = duckdb.connect()
    paths = {name: tmp_path / f"{name}.parquet" for name in ("recalls", "risk", "links", "ndc")}
    save(con, [{"recall_number": "D-1", "recall_initiation_date": "20250101",
                "product_description": "Heparin Sodium Injection, 10 mL vial"},
               {"recall_number": "D-2", "recall_initiation_date": "20250101",
                "product_description": "Carboplatin tablets"}], paths["recalls"], tmp_path)
    save(con, [{"recall_number": "D-1", "event_id": "e1", "drug_key": "heparin sodium",
                "root_cause": "Sterility"},
               {"recall_number": "D-2", "event_id": "e1", "drug_key": "carboplatin",
                "root_cause": "Sterility"}], paths["risk"], tmp_path)
    save(con, [{"recall_number": "D-1", "shortage_list_type": "shortage",
                "shortage_posted": "04/11/2025"}], paths["links"], tmp_path)
    save(con, [{"generic_name": "Heparin Sodium", "labeler_name": "Pfizer"},
               {"generic_name": "Carboplatin", "labeler_name": "Teyro Labs"}], paths["ndc"], tmp_path)

    lines, summary = run_backtest(paths["recalls"], paths["risk"], paths["links"], paths["ndc"],
                                  date(2026, 11, 8))
    assert lines[0] == "# Risk flag backtest"
    assert "| watch | 1 | 1 | 100.0% | 2.0x |" in lines           # the injectable went short
    assert (summary["recalled_drugs"], summary["followed"], summary["rate"]) == (2, 1, 0.5)
    assert summary["rate_by_flag"] == {"watch": 1.0, "low": 0.0}
    assert summary["computed_on"] == "2026-11-08"


def test_flag_lift_reads_a_saved_backtest(tmp_path):
    path = tmp_path / "risk_backtest.json"
    path.write_text('{"rate_by_flag": {"watch": 0.019, "low": 0.009}}', encoding="utf-8")
    assert flag_lift(path)["rate_by_flag"]["watch"] == 0.019
    assert flag_lift(tmp_path / "missing.json") is None


# ---------------------------------------------------------------- the forward test

def test_wilson_gives_the_95_percent_range():
    low, high = wilson(5, 9)
    assert (round(low, 3), round(high, 3)) == (0.267, 0.811)
    assert wilson(0, 10)[0] == 0.0 and round(wilson(0, 10)[1], 3) == 0.278
    assert wilson(0, 0) is None


def test_log_units_follows_each_drug_from_the_day_it_was_flagged(tmp_path):
    con = duckdb.connect()
    risk, links, log = tmp_path / "risk.parquet", tmp_path / "links.parquet", tmp_path / "risk_log.csv"
    save(con, [
        {"recall_number": "D-1", "event_id": "e1", "drug_key": "heparin sodium"},
        {"recall_number": "D-2", "event_id": "e1", "drug_key": "heparin sodium"},   # same drug, same event
        {"recall_number": "D-3", "event_id": "e2", "drug_key": "carboplatin"},
        {"recall_number": "D-4", "event_id": "e3", "drug_key": None},               # no drug name
        {"recall_number": "D-5", "event_id": "e4", "drug_key": "morphine sulfate"},
        {"recall_number": "D-6", "event_id": "e5", "drug_key": "lidocaine"},
    ], risk, tmp_path)
    save(con, [
        {"recall_number": "D-2", "shortage_list_type": "shortage", "shortage_posted": "12/01/2026"},
        {"recall_number": "D-1", "shortage_list_type": "discontinuation", "shortage_posted": "11/15/2026"},
        {"recall_number": "D-3", "shortage_list_type": "shortage", "shortage_posted": "10/01/2026"},  # before
        {"recall_number": "D-6", "shortage_list_type": "shortage", "shortage_posted": "12/15/2027"},  # too late
        {"recall_number": "D-5", "shortage_list_type": "shortage", "shortage_posted": "01/15/2026"},
    ], links, tmp_path)
    with open(log, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["recall_number", "report_date", "flagged_on", "flag", "points", "reasons"])
        writer.writerows([["D-1", "20261020", "2026-10-27", "watch", "1", "injectable"],
                          ["D-2", "20261021", "2026-10-28", "low", "0", ""],
                          ["D-3", "20261020", "2026-10-27", "low", "0", ""],
                          ["D-4", "20261020", "2026-10-27", "low", "0", ""],
                          ["D-5", "20250925", "2025-10-01", "high", "4", "sterility, 1 labeler"],
                          ["D-6", "20261029", "2026-10-30", "low", "0", ""]])

    units, unnamed = log_units(con, risk, links, log)
    found = {u["drug_key"]: (u["flag"], u["flagged_on"], u["first_posted"]) for u in units}
    assert found == {
        # one unit for D-1 and D-2: the first day either was flagged, the highest flag, and
        # D-2's shortage counts, since a shortage happens to the drug
        "heparin sodium": ("watch", date(2026, 10, 27), date(2026, 12, 1)),
        "carboplatin": ("low", date(2026, 10, 27), None),        # posted before the flag
        "lidocaine": ("low", date(2026, 10, 30), None),          # posted after the year was up
        "morphine sulfate": ("high", date(2025, 10, 1), date(2026, 1, 15)),
    }
    assert unnamed == 1
    assert log_units(con, risk, links, tmp_path / "missing.csv") == ([], 0)


def _unit(flag, flagged_on, first_posted=None, key="a drug"):
    return {"event_id": "e", "drug_key": key, "flag": flag, "flagged_on": flagged_on,
            "first_posted": first_posted}


def test_judge_log_only_counts_full_years():
    units = [_unit("watch", date(2026, 10, 27), date(2026, 12, 1), "heparin"),
             _unit("watch", date(2026, 11, 1), None, "carboplatin"),
             _unit("low", date(2026, 10, 27), None, "aspirin"),
             _unit("low", date(2027, 6, 1), date(2027, 7, 1), "lidocaine"),   # still in its year
             _unit("watch", date(2025, 10, 1), date(2026, 1, 15), "morphine")]  # the old points
    result = judge_log(units, date(2027, 11, 15))
    watch, low = result["table"]["watch"], result["table"]["low"]
    assert (watch["recalled_drugs"], watch["full_year"], watch["followed"], watch["rate"]) == (2, 2, 1, 0.5)
    # lidocaine's early hit is listed, but it stays out of the rate until its year is up
    assert (low["full_year"], low["followed"], low["rate"]) == (1, 0, 0.0)
    assert (low["in_their_year"], low["followed_already"]) == (1, 1)
    assert result["verdict"] == "can't tell"
    assert result["old"] == {"recalled_drugs": 1, "followed": 1}
    assert [u["drug_key"] for u in result["followed"]] == ["heparin", "lidocaine"]


def test_judge_log_verdicts():
    early = judge_log([_unit("watch", date(2026, 10, 27)), _unit("low", date(2026, 10, 28))],
                      date(2026, 11, 7))
    assert (early["verdict"], early["first_full_year"]) == ("too early", date(2027, 10, 27))
    done = date(2027, 12, 1)
    strong = [_unit("watch", date(2026, 11, 1), date(2026, 12, 1) if i < 25 else None, f"w{i}")
              for i in range(50)] + [_unit("low", date(2026, 11, 1), key=f"l{i}") for i in range(50)]
    assert judge_log(strong, done)["verdict"] == "working"
    flipped = [dict(u, flag="low" if u["flag"] == "watch" else "watch") for u in strong]
    assert judge_log(flipped, done)["verdict"] == "not working"


def test_check_report_says_it_in_plain_words():
    result = judge_log([_unit("watch", date(2026, 10, 27)), _unit("low", date(2026, 10, 28))],
                       date(2026, 11, 7))
    text = "\n".join(check_report(result, 1, date(2026, 11, 7),
                                  {"rate_by_flag": {"watch": 0.019, "low": 0.009}}))
    assert "**Too early to judge.**" in text and "The first ones finish on Oct 27, 2027." in text
    assert "| watch | 1 | 0 | 0 | not yet | 1 | 0 |" in text
    assert "expects about 1.9% for watch and 0.9% for low" in text
    assert "No recall was logged under the old points." in text
    assert "1 logged recall has no drug name" in text

