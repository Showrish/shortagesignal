"""Ask the data: the SQL safety check, the locked database, scoring, and the Claude calls."""
from datetime import date
from types import SimpleNamespace

import duckdb
import pytest

from shortagesignal.ask import (
    build_sandbox,
    check_sql,
    results_match,
    run_query,
    write_answer,
    write_sql,
)


def test_check_sql_lets_one_select_through():
    assert check_sql("SELECT COUNT(*) FROM recalls;") == "SELECT COUNT(*) FROM recalls"
    assert check_sql("WITH a AS (SELECT 1) SELECT * FROM a")
    assert check_sql("SELECT * FROM recalls WHERE reason ILIKE '%set; drop table%'")  # inside quotes
    for bad in ["DROP TABLE recalls", "SELECT 1; DROP TABLE recalls", "UPDATE recalls SET drug = 'x'",
                "SELECT * FROM read_csv('/etc/passwd')", "COPY recalls TO 'x.csv'",
                "ATTACH 'other.db'", "PRAGMA version", "SET enable_external_access = true",
                "INSTALL httpfs", "", "   "]:
        with pytest.raises(ValueError):
            check_sql(bad)


def _parquet(con, path, columns, rows):
    def literal(v):
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, date):
            return f"DATE '{v.isoformat()}'"
        return "'" + str(v).replace("'", "''") + "'"
    values = ", ".join("(" + ", ".join(literal(v) for v in row) + ")" for row in rows)
    con.execute(f"COPY (SELECT * FROM (VALUES {values}) t({', '.join(columns)})) "
                f"TO '{path.as_posix()}' (FORMAT PARQUET)")


def _sandbox(tmp_path):
    con = duckdb.connect()
    p = {name: tmp_path / f"{name}.parquet" for name in
         ("recalls", "root_causes", "risk", "shortages", "links", "weekly", "makers", "history")}
    _parquet(con, p["recalls"], ["recall_number", "event_id", "report_date", "recall_initiation_date",
                                 "classification", "status", "recalling_firm", "product_description",
                                 "reason_for_recall"], [
        ("D-1", "E1", "20250304", "20250220", "Class I", "Ongoing", "Hospira", "Heparin vial", "Sterility"),
        ("D-2", "E1", "20250304", "20250220", "Class I", "Ongoing", "Hospira", "Heparin bag", "Sterility"),
        ("D-3", "E2", "20240110", "20240101", "Class II", "Completed", "Acme", "Aspirin", "Labeling"),
    ])
    _parquet(con, p["root_causes"], ["recall_number", "root_cause"],
             [("D-1", "Sterility"), ("D-2", "Sterility"), ("D-3", "Labeling or packaging")])
    _parquet(con, p["risk"], ["recall_number", "drug_key", "flag", "points", "reasons", "labelers", "injectable"],
             [("D-1", "heparin sodium", "high", 5, "sterility, 2 labelers, injectable", 2, True),
              ("D-2", "heparin sodium", "high", 5, "sterility, 2 labelers, injectable", 2, True),
              ("D-3", "aspirin", "low", 0, "", 40, False)])
    _parquet(con, p["shortages"], ["shortage_key", "generic_name", "company_name", "list_type", "status",
                                   "availability", "shortage_reason", "therapeutic_category",
                                   "dosage_form", "initial_posting_date"],
             [("k1", "Heparin Sodium", "Hospira", "shortage", "Current", "Limited", "Demand",
               '["Hematology", "Cardiology"]', "Injection", "03/15/2025")])
    _parquet(con, p["links"], ["recall_number", "shortage_key", "match_level", "shortage_generic_name",
                               "shortage_status", "shortage_list_type", "shortage_posted"],
             [("D-1", "k1", "drug_and_firm", "Heparin Sodium", "Current", "shortage", "03/15/2025")])
    _parquet(con, p["weekly"], ["week", "events", "recalls", "center", "ucl", "lcl", "signal"],
             [(date(2025, 3, 3), 1, 2, 1.0, 3.0, 0.0, "")])
    _parquet(con, p["makers"], ["drug_key", "labelers"], [("heparin sodium", 6), ("aspirin", 40)])
    _parquet(con, p["history"], ["shortage_key", "first_seen", "last_seen", "days_seen", "latest_status",
                                 "generic_name", "company_name"],
             [("k1", date(2026, 10, 11), date(2026, 10, 22), 12, "Current", "Heparin Sodium", "Hospira"),
              ("k2", date(2026, 10, 11), date(2026, 10, 15), 5, "Resolved", "Cefazolin", "Acme")])
    return build_sandbox(p)


def test_sandbox_has_friendly_tables_and_reads_nothing_else(tmp_path):
    con = _sandbox(tmp_path)
    columns, rows = run_query(con, "SELECT drug, COUNT(*) AS n, COUNT(DISTINCT event_id) AS events "
                                   "FROM recalls GROUP BY drug ORDER BY n DESC")
    assert columns == ["drug", "n", "events"] and rows[0] == ("heparin sodium", 2, 1)
    assert run_query(con, "SELECT posted FROM shortages")[1] == [(date(2025, 3, 15),)]
    assert run_query(con, "SELECT therapeutic_category FROM shortages")[1] == [("Hematology, Cardiology",)]
    assert run_query(con, "SELECT companies FROM drug_makers WHERE drug = 'heparin sodium'")[1] == [(6,)]
    left = run_query(con, "SELECT drug FROM shortage_history WHERE NOT still_listed")[1]
    assert left == [("Cefazolin",)]                     # last seen before the latest snapshot
    (tmp_path / "secret.csv").write_text("a\n1\n")
    with pytest.raises(Exception):     # files are out of reach, even past check_sql
        con.execute(f"SELECT * FROM read_csv('{(tmp_path / 'secret.csv').as_posix()}')").fetchall()
    with pytest.raises(Exception):     # and the lock can't be undone
        con.execute("SET enable_external_access = true")
    assert len(run_query(con, "SELECT * FROM range(1000)", limit=200)[1]) == 200


def test_results_match_sets_check_every_reference_value():
    assert results_match([("a",), ("b",)], [("b", 2), ("a", 5)])        # any order, extra columns
    assert results_match([(12.34,)], [(12.3,)])                         # rounded to 1 decimal
    assert not results_match([(42,)], [(41,)])
    assert not results_match([("a",)], [(str(i),) for i in range(50)] + [("a",)])   # too big
    assert not results_match([], [(1,)])


def test_results_match_values_check_the_top_row_and_allow_ties():
    ranked = [("Failed specification", 824)] + [(f"cause {i}", 100 - i) for i in range(10)]
    assert results_match([("Failed specification",)], ranked, "value")    # a long ranked list is fine
    assert not results_match([("cause 3",)], ranked, "value")             # but it has to be on top
    assert results_match([("2025-11-03",), ("2025-06-09",)], [("2025-06-09", 31)], "value")   # a tie
    assert results_match([(42,)], [(42,)], "value")
    assert not results_match([(42,)], [], "value")


class FakeClient:
    def __init__(self, tool_input=None, text=None):
        self.tool_input, self.text = tool_input, text
        self.messages = self

    def create(self, **kwargs):
        usage = SimpleNamespace(input_tokens=2000, output_tokens=100)
        if self.tool_input is not None:
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=self.tool_input)], usage=usage)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)], usage=usage)


def test_write_sql_and_write_answer_read_claudes_replies():
    plan = write_sql(FakeClient({"sql": "SELECT 1", "explanation": "Counts one."}), "How many?")
    assert (plan["sql"], plan["explanation"], plan["tokens"]) == ("SELECT 1", "Counts one.", (2000, 100))
    declined = write_sql(FakeClient({"sql": "", "explanation": "No weather data."}), "Weather?")
    assert declined["sql"] == ""
    reply = write_answer(FakeClient(text=" 2 recalls. "), "How many?", "Counts recalls.", ["n"], [(2,)])
    assert reply["text"] == "2 recalls."
