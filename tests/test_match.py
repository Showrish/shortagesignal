"""Matching recalls to shortages."""
import duckdb

from shortagesignal.match import build_matches, identify_drug
from shortagesignal.storage import load_batch, write_parquet

NDC_MAP = {"00409-4888": "heparin sodium"}
VOCABULARY = {"heparin sodium", "carboplatin"}
BRANDS = {"paraplatin": "carboplatin"}


def test_identify_drug_tries_ndc_then_openfda_then_text():
    assert identify_drug(["00409-4888"], None, "", NDC_MAP, VOCABULARY, BRANDS) == (
        "heparin sodium", "ndc_directory")
    assert identify_drug([], '{"generic_name": ["CARBOPLATIN"]}', "", NDC_MAP, VOCABULARY,
                         BRANDS) == ("carboplatin", "openfda")
    assert identify_drug([], None, "Carboplatin Injection, 50 mg", NDC_MAP, VOCABULARY,
                         BRANDS) == ("carboplatin", "text_name")
    assert identify_drug([], None, "Paraplatin (carboplatin) injection", NDC_MAP, VOCABULARY,
                         BRANDS) == ("carboplatin", "text_brand")
    assert identify_drug([], None, "Mystery Compound tablets", NDC_MAP, VOCABULARY,
                         BRANDS) == (None, None)


def save(con, rows, path, workdir):
    columns = sorted({c for r in rows for c in r})
    load_batch(con, rows, columns, "fixture", workdir)
    write_parquet(con, "SELECT * FROM fixture", path)


def test_build_matches_links_at_the_strongest_level(tmp_path):
    con = duckdb.connect()
    f = {name: tmp_path / f"{name}.parquet" for name in (
        "ndc", "recalls", "recall_ids", "shortage_ids", "snapshots",
        "recall_drugs", "shortage_drugs", "links", "unmatched")}

    save(con, [
        {"product_ndc": "0409-4888", "generic_name": "Heparin Sodium", "brand_name": "Heparin Sodium"},
        {"product_ndc": "63323-540", "generic_name": "Carboplatin", "brand_name": "Paraplatin"},
    ], f["ndc"], tmp_path)
    recall = {"openfda": "{}", "report_date": "20260101", "recall_initiation_date": "20251215",
              "classification": "Class II"}
    save(con, [
        {**recall, "recall_number": "D-1", "recalling_firm": "Hospira, Inc.",
         "product_description": "Heparin Sodium Injection, NDC 0409-4888-10"},
        {**recall, "recall_number": "D-2", "recalling_firm": "Acme Inc",
         "product_description": "Paraplatin (carboplatin) injection, 10 mg/mL"},
        {**recall, "recall_number": "D-3", "recalling_firm": "Teyro Labs",
         "product_description": "Carboplatin Injection, 50 mg"},
        {**recall, "recall_number": "D-4", "recalling_firm": "Unknown LLC",
         "product_description": "Mystery Compound tablets"},
    ], f["recalls"], tmp_path)
    save(con, [
        {"recall_number": "D-1", "firm_key": "HOSPIRA", "ndc11": "00409-4888-10",
         "ndc9": "00409-4888", "source": "text"},
        {"recall_number": "D-2", "firm_key": "ACME", "ndc11": None, "ndc9": None, "source": "none"},
        {"recall_number": "D-3", "firm_key": "TEYRO", "ndc11": None, "ndc9": None, "source": "none"},
        {"recall_number": "D-4", "firm_key": "UNKNOWN", "ndc11": None, "ndc9": None, "source": "none"},
    ], f["recall_ids"], tmp_path)
    save(con, [
        {"shortage_key": "S-1", "firm_key": "HOSPIRA", "ndc11": "00409-4888-10",
         "ndc9": "00409-4888", "source": "text"},
        {"shortage_key": "S-2", "firm_key": "TEYRO", "ndc11": "60505-6282-01",
         "ndc9": "60505-6282", "source": "text"},
    ], f["shortage_ids"], tmp_path)
    snapshot = {"snapshot_date": "2026-10-11", "status": "Current", "list_type": "shortage"}
    save(con, [
        {**snapshot, "shortage_key": "S-1", "generic_name": "Heparin Sodium Injection",
         "company_name": "Hospira, Inc.", "initial_posting_date": "01/15/2026"},
        {**snapshot, "shortage_key": "S-2", "generic_name": "Carboplatin Injection",
         "company_name": "Teyro Labs", "initial_posting_date": "05/01/2023"},
    ], f["snapshots"], tmp_path)

    stats = build_matches(con, f, tmp_path)

    links = con.execute(
        f"SELECT recall_number, shortage_key, match_level FROM read_parquet('{f['links'].as_posix()}') "
        "ORDER BY 1, 2"
    ).fetchall()
    assert links == [("D-1", "S-1", "package"), ("D-2", "S-2", "drug"), ("D-3", "S-2", "drug_and_firm")]

    unmatched = con.execute(
        f"SELECT recall_number FROM read_parquet('{f['unmatched'].as_posix()}')"
    ).fetchall()
    assert unmatched == [("D-4",)]
    assert stats["identified"] == 3 and stats["unmatched"] == 1
    assert stats["linked_recalls"] == 3 and stats["linked_shortages"] == 2
    assert stats["by_level"] == {"package": 1, "product": 0, "drug_and_firm": 1, "drug": 1}
