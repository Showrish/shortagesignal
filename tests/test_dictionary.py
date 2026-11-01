import json
from datetime import date

import duckdb

from shortagesignal.dictionary import TABLES, build, nice_type


def test_every_table_says_what_a_row_is_and_how_it_is_made():
    for table in TABLES:
        assert table["row"] and table["made_by"] and table["columns"], table["file"]
    files = [t["file"] for t in TABLES]
    assert len(files) == len(set(files))


def test_nice_type():
    assert nice_type("VARCHAR") == "text"
    assert nice_type("BIGINT") == "whole number"
    assert nice_type("TIMESTAMP WITH TIME ZONE") == "timestamp"
    assert nice_type("DECIMAL(4,1)") == "number"


def test_build_reads_the_real_columns_and_flags_what_is_missing(tmp_path):
    con = duckdb.connect()
    # recall_drugs as it really is, plus one column nobody described yet
    con.execute(f"""COPY (SELECT 'D-1' AS recall_number, 'heparin sodium' AS drug_key,
                         'openfda' AS id_source, 7 AS mystery)
                    TO '{(tmp_path / "recall_drugs.parquet").as_posix()}' (FORMAT parquet)""")
    # drug_makers missing a described column
    con.execute(f"""COPY (SELECT 'heparin sodium' AS drug_key)
                    TO '{(tmp_path / "drug_makers.parquet").as_posix()}' (FORMAT parquet)""")
    (tmp_path / "risk_log.csv").write_text("recall_number,report_date,flagged_on,flag,points,"
                                           "reasons\nD-1,20261020,2026-10-26,watch,1,injectable\n")
    (tmp_path / "state.json").write_text(json.dumps({"ndc_refreshed": "2026-10-25"}))

    text, warnings = build(tmp_path, date(2026, 10, 31))
    assert "| [recall_drugs.parquet](#recall_drugsparquet) | `recall_drugs` |" in text
    assert "| `drug_key` | text | The drug's cleaned generic name, like heparin sodium." in text
    assert "| `mystery` | whole number | *Not described yet.* |" in text
    assert "| `flagged_on` | text | The day the flag was given. |" in text
    assert "## state.json" in text and "Oct 31, 2026" in text
    assert any("drug_makers.parquet: describes labelers" in w for w in warnings)
    assert any(w.startswith("recalls.parquet: not in") for w in warnings)
